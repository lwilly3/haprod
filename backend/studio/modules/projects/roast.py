"""
Roasting : Claude relit le script avec la grille du skill youtube-scriptwriting et rend une
critique structurée (notes, fiches de section, courbe d'intérêt, boucles, promesses, remarques).

Chaque roast est un job (kind KIND), rattaché au projet par payload["project"] ; le dernier lancé
est aussi dans project["jobs"]["roast"], pour que l'interface le suive.

  payload   blocks    le script au moment du roast : [{id, md}] (les ids de script.json)
            plans     ses plans à ce moment-là : ce qu'on voit à l'écran (type, note, passage, fichiers)
            cold      à froid : titre, vignette et texte seulement, sans brief ni notes
            note      ce que l'auteur veut qu'on regarde
  state     result    la sortie de Claude, nettoyée (voir _clean) ; chaque remarque a un id
            marks     {id de remarque: "done" | "ignored"}, posé par l'interface

Les remarques écartées (« ignored ») sont redonnées aux roasts suivants pour qu'ils ne les refassent pas.
"""
import re
import uuid

from ...core import jobs
from ...core.tasks import TaskContext
from . import prompts, service
from . import script as script_doc

KIND = "project_roast"
MARKS = ("done", "ignored")
WORDS_PER_MIN = 150


def _words(md: str) -> int:
    """Les mots dits d'un bloc (comme wordCount côté interface) : ni titres, ni indications entre crochets."""
    lines = [line.strip() for line in md.split("\n")]
    spoken = [re.sub(r"[*_`]", "", re.sub(r"^>\s*|^[-*]\s+", "", line)) for line in lines
              if line and not line.startswith(("[", "#")) and line != "---"]
    return len(" ".join(spoken).split())


def _mmss(sec: float) -> str:
    t = round(sec)
    return f"{t // 60}:{t % 60:02d}"


def _plan(p: dict) -> dict:
    """Ce qu'un plan montre : son type, sa note, le passage qu'il couvre et le nom de ses fichiers."""
    names = [re.sub(r"\.\w{2,4}$", "", m.get("name") or "") for m in p.get("media") or []]
    return {"block": p["block"], "end": p.get("end"), "type": p.get("type", ""), "note": p.get("note", ""),
            "q": " ".join((p.get("q") or "").split()), "media": [n for n in names if n]}


def annotate(blocks: list[dict], plans: list[dict] | None = None) -> list[dict]:
    """Les blocs avec les plans qui y commencent, et pour chaque titre de section son début, son nombre
    de mots et sa durée."""
    out, sections, words = [], [], 0
    by_block: dict[str, list[dict]] = {}
    for p in plans or []:
        by_block.setdefault(p["block"], []).append(p)
    for b in blocks:
        entry = {"id": b["id"], "md": b["md"], "plans": by_block.get(b["id"], [])}
        if re.match(r"^##\s", b["md"]):
            entry.update(section=True, start=_mmss(words / WORDS_PER_MIN * 60), words=0)
            sections.append(entry)
        elif sections:
            sections[-1]["words"] += _words(b["md"])
        words += _words(b["md"])
        out.append(entry)
    for s in sections:
        s["duration"] = _mmss(s["words"] / WORDS_PER_MIN * 60)
    return out


def _plain(md: str) -> str:
    return " ".join(re.sub(r"\[([^\]]*)\]\([^)]*\)|[*_`>#]", lambda m: m.group(1) or "", md).split())


def _loose(text: str) -> str:
    return text.replace("’", "'").replace("«", '"').replace("»", '"').lower()


def _clean(output: dict, blocks: list[dict]) -> dict:
    """Ce que Claude a rendu, sans les ids de bloc inventés ; une remarque mal ancrée est recalée sur sa citation."""
    ids = {b["id"] for b in blocks}
    ok = lambda bid: bid if bid in ids else ""  # noqa: E731

    findings = []
    for f in output.get("findings") or []:
        block = ok(f.get("block", ""))
        quote = (f.get("quote") or "").strip()
        if not block and quote:
            needle = _loose(_plain(quote))
            block = next((b["id"] for b in blocks if needle and needle in _loose(_plain(b["md"]))), "")
        findings.append({**f, "id": "f" + uuid.uuid4().hex[:8], "block": block, "quote": quote})
    by_key = {c["key"]: c for c in output.get("criteria") or [] if c.get("key") in prompts.ROAST_CRITERIA}
    return {
        "verdict": output.get("verdict") or {"score": 0, "decision": "retouche", "headline": ""},
        "criteria": [{**by_key[k], "block": ok(by_key[k].get("block", ""))} for k in prompts.ROAST_CRITERIA
                     if k in by_key],
        "sections": [s for s in output.get("sections") or [] if s.get("block") in ids],
        "interest": [i for i in output.get("interest") or [] if i.get("block") in ids],
        "loops": [{**lp, "close": ok(lp.get("close", ""))} for lp in output.get("loops") or [] if lp.get("open") in ids],
        "promises": [{**p, "block": ok(p.get("block", ""))} for p in output.get("promises") or []],
        "findings": findings,
    }


# --- Lancement -----------------------------------------------------------------------------

def project_runs(pid: str) -> list[jobs.Job]:
    """Les roasts du projet, du plus ancien au plus récent."""
    return [j for j in jobs.list_jobs(service.MODULE) if j.kind == KIND and j.payload.get("project") == pid]


def _ignored(pid: str) -> list[dict]:
    out = []
    for job in project_runs(pid):
        marks = job.state.get("marks") or {}
        out += [f for f in (job.state.get("result") or {}).get("findings", []) if marks.get(f["id"]) == "ignored"]
    return out


def _context(project: dict, cold: bool) -> dict:
    """Ce que le spectateur voit avant de cliquer (titre, vignette) et, hors roast à froid, l'angle et la durée."""
    titles = [t["t"] for t in project.get("titles") or [] if t.get("pick")]
    thumbs = [t for t in project.get("thumbs") or [] if t.get("pick")]
    if not thumbs and project.get("thumb_sel") is not None and 0 <= project["thumb_sel"] < len(project["thumbs"]):
        thumbs = [project["thumbs"][project["thumb_sel"]]]
    context = {
        "title": titles[0] if titles else project["title"],
        "thumbs": [" — ".join(x for x in (f"texte « {t['text']} »" if t.get("text") else "", t.get("prompt") or "") if x)
                   for t in thumbs if t.get("text") or t.get("prompt")],
    }
    if not cold:
        sel = project.get("angle_sel")
        context["angle"] = project["angles"][sel] if sel is not None and 0 <= sel < len(project["angles"]) else None
        context["duration"] = project["brief"].get("dur", "")
    return context


def start(pid: str, cold: bool, note: str) -> jobs.Job:
    current = jobs.get(service.load(pid)["jobs"].get("roast") or "")
    if current and not current.finished:
        raise ValueError("un roast est déjà en cours")
    data = script_doc.load(pid)
    blocks = [{"id": b["id"], "md": b["md"]} for b in data["blocks"]]
    plans = [_plan(p) for p in data["plans"] if p.get("block")]
    if not any(_words(b["md"]) for b in blocks):
        raise ValueError("le script est vide")
    project = service.load(pid)
    payload = {"project": pid, "dir": str(service.project_dir(pid) / service.SCRIPT_DIR), "blocks": blocks,
               "plans": plans, "cold": cold, "note": note.strip(), "context": _context(project, cold), "ignored": _ignored(pid)}
    return jobs.create(service.MODULE, KIND, payload, {"marks": {}}, job_id=f"{pid}-roast-{uuid.uuid4().hex[:6]}")


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p = ctx.payload
    prompt = prompts.roast_prompt(annotate(p["blocks"], p.get("plans")), p["context"], p.get("ignored") or [], p.get("note", ""))
    out = ask(ctx, prompt, prompts.roast_system(p["cold"]), prompts.READ_TOOLS, None, prompts.ROAST_SCHEMA)
    if not out["output"]:
        raise RuntimeError("Claude n'a pas renvoyé de roast exploitable")
    ctx.state["result"] = _clean(out["output"], p["blocks"])


# --- Vue -------------------------------------------------------------------------------------

def view(job: jobs.Job) -> dict:
    p = job.payload
    return {"id": job.id, "status": job.status, "error": job.error, "finished": job.finished,
            "activity": job.state.get("activity"), "created_at": job.created_at, "finished_at": job.finished_at,
            "cold": p.get("cold", False), "note": p.get("note", ""), "blocks": p["blocks"],
            "result": job.state.get("result"), "marks": job.state.get("marks") or {}}


def chat_context(job: jobs.Job) -> dict:
    """Ce que la discussion sur un roast redonne à Claude : le script d'alors, annoté, et le roast,
    chaque remarque avec ce que l'auteur en a fait."""
    p, result = job.payload, dict(job.state.get("result") or {})
    marks = job.state.get("marks") or {}
    result["findings"] = [{**f, "suivi": {"done": "traitée", "ignored": "écartée"}.get(marks.get(f["id"]), "à traiter")}
                          for f in result.get("findings") or []]
    return {"blocks": annotate(p["blocks"], p.get("plans")), "context": p.get("context") or {},
            "note": p.get("note", ""), "result": result}


def labels() -> dict:
    return {"criteria": prompts.ROAST_CRITERIA, "categories": {**prompts.ROAST_CRITERIA, **prompts.ROAST_EXTRA}}


def set_marks(job: jobs.Job, changes: dict[str, str | None]) -> None:
    if not job.finished:
        raise ValueError("le roast n'est pas terminé")
    known = {f["id"] for f in (job.state.get("result") or {}).get("findings", [])}
    marks = job.state.get("marks") or {}
    for fid, mark in changes.items():
        if fid not in known or (mark is not None and mark not in MARKS):
            raise ValueError("remarque inconnue")
        if mark:
            marks[fid] = mark
        else:
            marks.pop(fid, None)
    job.state["marks"] = marks
    jobs.update(job.id, state=job.state)


def last_score(pid: str, job_id: str | None) -> float | None:
    """La note du dernier roast terminé (pour la barre latérale)."""
    job = jobs.get(job_id or "")
    result = job.state.get("result") if job and job.status == "done" else None
    return result["verdict"].get("score") if result else None
