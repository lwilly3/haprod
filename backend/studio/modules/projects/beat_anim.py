"""
Créer l'animation d'un beat du storyboard : une tâche par beat, à part du chat du monteur. Le motion est
déjà posé dans la timeline (place, durée, son : `storyboard.compose`) ; Daryl n'écrit que sa composition,
montage/motion/<id>.html, avec juste ce qu'il lui faut (la fiche du beat, les mots et leurs instants, le
contrat, la charte, le modèle du kit). Chaque beat écrit un fichier différent : plusieurs tâches tournent
en parallèle, SLOTS au plus (une file par place), les suivantes attendent.
"""
from ...core import jobs
from ...core.tasks import TaskContext
from ..settings.service import language_name
from . import montage, montage_tasks, service, storyboard

SLOTS = 3
KINDS = [f"project_beat_anim_{i}" for i in range(SLOTS)]

SYSTEM = """\
Tu es Daryl, motion designer d'un créateur de vidéos YouTube éducatives. Tu écris UNE composition \
HyperFrames (HTML + GSAP), un visuel animé posé au-dessus de la vidéo pendant qu'il parle, à partir \
d'un beat de storyboard qu'il a validé. Suis « on montre » au plus près ; si quelque chose est \
impossible, fais au plus près et dis-le.

{rules}

# Comment tu travailles
- Lis montage/motion/style.css (la charte) et le modèle du kit indiqué s'il y en a un, sinon un ou deux \
exemples de montage/motion/exemples/ pour le contrat technique et le niveau attendu.
- Écris montage/motion/<id>.html, et aucun autre fichier.
- Ta réponse finale : en {lang}, une ou deux phrases sur ce que tu as fait."""


def job_id(pid: str, beat: str) -> str:
    return f"{pid}-anim-{beat}"


def _slot() -> str:
    """La file la moins chargée (tous projets confondus)."""
    load = {k: 0 for k in KINDS}
    for j in jobs.list_jobs(service.MODULE):
        if j.kind in load and not j.finished:
            load[j.kind] += 1
    return min(KINDS, key=lambda k: load[k])


def enqueue(pid: str, beat: str, motion: str) -> None:
    """Met en file la création de l'animation d'un beat (sauf si elle est déjà en cours)."""
    jid = job_id(pid, beat)
    job = jobs.get(jid)
    if job and not job.finished:
        return
    if job:
        jobs.delete(jid)
    jobs.create(service.MODULE, _slot(), {"project": pid, "beat": beat, "motion": motion,
                                          "dir": str(service.project_dir(pid))}, {}, job_id=jid)


def running(pid: str) -> set[str]:
    """Les motions dont la création est en file ou en cours (le chat du monteur n'y touche pas)."""
    board = storyboard.load(pid) or {"beats": []}
    out = set()
    for b in board["beats"]:
        job = jobs.get(job_id(pid, b["id"]))
        if job and not job.finished:
            out.add(job.payload.get("motion"))
    return out


def states(pid: str, beats: list[dict]) -> dict:
    """L'état de la création de chaque beat qui en a une : {beat: {status, activity, error}}. Une création
    finie sans erreur n'y figure plus (le beat est animé)."""
    out = {}
    for b in beats:
        job = jobs.get(job_id(pid, b["id"]))
        if not job or job.status == "done":
            continue
        status = job.status if job.status in ("queued", "error", "cancelled") else "running"
        out[b["id"]] = {"status": status, "activity": job.state.get("activity"), "error": job.error}
    return out


def prompt(pid: str, beat: dict, motion: dict) -> str:
    project = service.load(pid)
    timeline = montage.load(pid)
    words = storyboard.timeline_words(project, timeline)
    start, end = motion["at"], motion["at"] + motion["dur"]
    spoken = [w for w in words if w.end > start - 0.3 and w.start < end + 0.3]
    mid = motion["id"]
    parts = [f"Compose montage/motion/{mid}.html (data-composition-id=\"{mid}\", data-duration=\"{motion['dur']:.2f}\").",
             "", storyboard.brief(pid, [mid]), "",
             "Ce qu'il dit pendant le beat, mot à mot (instant du mot en secondes depuis le début de la "
             "composition ; négatif : juste avant) :",
             " ".join(f"{w.text.strip()}@{w.start - start:.2f}" for w in spoken if w.text.strip())]
    return "\n".join(parts)


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p, state = ctx.payload, ctx.state
    pid, beat_id, mid = p["project"], p["beat"], p["motion"]
    board = storyboard.load(pid) or {"beats": []}
    beat = next((b for b in board["beats"] if b["id"] == beat_id), None)
    motion = next((m for m in montage.load(pid)["motion"] if m["id"] == mid), None)
    if not beat or not motion:
        raise RuntimeError("Le beat ou son motion n'existe plus.")
    montage.prepare(pid)
    target = montage.motion_dir(pid) / f"{mid}.html"
    before = target.stat().st_mtime if target.is_file() else None
    state["activity"] = "lit la charte"
    ctx.save(force=True)
    out = ask(ctx, prompt(pid, beat, motion),
              SYSTEM.format(rules=montage_tasks.MOTION_RULES, lang=language_name()), "Read,Write,Edit,Glob")
    if not target.is_file() or target.stat().st_mtime == before:
        raise RuntimeError("Daryl n'a pas écrit la composition." + (f" Il dit : {out['text'][:300]}" if out["text"] else ""))
    state["reply"] = out["text"].strip()
    state["activity"] = None
    montage.after_change(pid)
