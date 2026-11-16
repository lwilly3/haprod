"""
Les sons du montage, choisis et posés : Claude lit la vidéo source minutée, dit quel son irait où,
chaque idée est cherchée parmi les sons libres de droits (free_audio), Claude retient le meilleur
candidat de chaque idée, et les fichiers retenus sont téléchargés puis posés sur la timeline.

Claude n'entend rien : il choisit sur le titre, les mots-clés, la durée et la licence. C'est une
proposition à écouter. La timeline garde son historique : la pose s'annule comme toute retouche, et
la relancer remplace les sons de la pose précédente (identifiants « sp-… »), jamais ceux de l'auteur.
"""
import uuid

from ...core import jobs
from ...core.tasks import TaskContext
from ..settings.service import language_name
from . import autoderush, free_audio, library, montage, service, storyboard

KIND = "project_sound_place"
PREFIX = "sp-"
CANDIDATES = 5
MAX_TEXT = 16000
# sans mixage automatique sous la voix : une musique reste en fond, un bruitage se détache sans couvrir
GAIN = {"musique": -24.0, "sfx": -10.0}
# un bruitage ne dure pas plus que ça, même si le fichier est long (une ambiance en boucle…)
SFX_MAX = 8.0

SYSTEM = """You are the sound designer of a YouTube video, working on its edit. You read the video line by \
line (each line has a number and a timecode) and decide which sounds to place on the timeline, from \
royalty-free libraries (Freesound for sound effects, Jamendo for music).

Less is more: the voice carries the video. Place a sound only where it clearly adds something: an ambience \
the picture lacks, an accent on a key word, a transition between two parts, a discreet music bed.
At most 8 sound effects and 3 pieces of music; pieces of music must not overlap. Answer in {lang} except `query`."""

IDEAS_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "one or two sentences on the overall approach"},
        "ideas": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["sfx", "musique"]},
                "query": {"type": "string", "description": "1 to 3 plain English keywords, as these libraries are tagged"},
                "label": {"type": "string", "description": "short name of the idea"},
                "why": {"type": "string", "description": "one sentence: what the sound adds at this moment"},
                "line": {"type": "integer", "description": "number of the line where the sound starts"},
                "where": {"type": "string", "enum": ["start", "end"],
                          "description": "at the start of that line, or right after it (a reaction, a transition)"},
                "until": {"type": "integer", "description": "music only: number of the last line it covers"},
                "seconds": {"type": "number", "description": "sound effect only: how long it should last"}},
            "required": ["kind", "query", "label", "why", "line", "where"]}},
    },
    "required": ["ideas"],
}

PICK_SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {
        "type": "object",
        "properties": {"idea": {"type": "integer"},
                       "candidate": {"type": "integer", "description": "number of the candidate kept, 0 to drop the idea"},
                       "reason": {"type": "string"}},
        "required": ["idea", "candidate"]}}},
    "required": ["picks"],
}


def _lines(project: dict, timeline: dict) -> tuple[list[dict], float]:
    """Les lignes numérotées de la vidéo telle qu'elle est montée ({n, start, end, text}) et sa durée."""
    words = storyboard.timeline_words(project, timeline)
    total = sum(c["out"] - c["in"] for c in timeline["aroll"])
    lines = autoderush.lines_of([{"id": "timeline"}], {"timeline": words})
    for i, line in enumerate(lines):
        last = (lines[i + 1]["first"] if i + 1 < len(lines) else len(words)) - 1
        line["end"] = words[last].end
    return lines, total


def ideas_prompt(project: dict, lines: list[dict], total: float, kept: list[dict], note: str) -> str:
    text = "\n".join(f"L{l['n']} [{storyboard._clock(l['start'])}] {l['text']}" for l in lines)
    parts = [f"Video: {project['title']} ({storyboard._clock(total)} long)", "", "The video, line by line:", text[:MAX_TEXT]]
    if kept:
        parts += ["", "Sounds already on the timeline, placed by the author (do not duplicate them):",
                  *(f"- {storyboard._clock(s['at'])} {s['src'].split('/')[-1]} ({s['role']})" for s in kept)]
    if note.strip():
        parts += ["", f"Author's request: {note.strip()}"]
    return "\n".join(parts)


def pick_prompt(found: list[tuple[dict, list[dict]]]) -> str:
    parts = ["Here is what the libraries returned for each idea. You cannot listen: judge from the title, the tags, "
             "the duration and the license. Keep, for each idea, the candidate that fits best: a clean, short sound for "
             "an accent; a track long enough for a music bed; when two fit equally, the one without required credit "
             "(CC0). Answer 0 to drop an idea whose candidates are all off-topic.", ""]
    for n, (idea, results) in enumerate(found, 1):
        parts.append(f"Idea {n}: {idea['label']} ({idea['kind']}, « {idea['query']} ») — {idea['why']}")
        for k, r in enumerate(results, 1):
            tags = ", ".join(r.get("tags") or [])
            parts.append(f"  {k}. {r['title']} · {r['duration'] or '?'} s · {r['license']}" + (f" · {tags}" if tags else ""))
    return "\n".join(parts)


def _search(idea: dict) -> list[dict]:
    """Les candidats d'une idée ; trop précise pour le catalogue, la recherche s'élargit mot par mot."""
    words = idea["query"].split()
    while words:
        found = free_audio.search(idea["kind"], " ".join(words))["items"][:CANDIDATES]
        if found:
            return found
        words = words[:-1]
    return []


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p, state = ctx.payload, ctx.state
    pid = p["project"]
    project = service.load(pid)
    timeline = montage.load(pid)
    lines, total = _lines(project, timeline)
    if not lines:
        raise RuntimeError("La vidéo source n'est pas transcrite : passe d'abord par l'étape Vidéo source.")
    by_n = {l["n"]: l for l in lines}
    kept = [s for s in timeline["audio"] if not s["id"].startswith(PREFIX)]

    state["activity"] = "lit la vidéo"
    ctx.save(force=True)
    out = ask(ctx, ideas_prompt(project, lines, total, kept, p.get("note", "")),
              SYSTEM.format(lang=language_name()), "Read", None, IDEAS_SCHEMA)
    output = out["output"] or {}
    ideas = [i for i in output.get("ideas") or []
             if i.get("kind") in free_audio.FILTERS and (i.get("query") or "").strip() and i.get("line") in by_n]
    if not ideas:
        raise RuntimeError("Claude n'a proposé aucun son pour cette vidéo.")

    found: list[tuple[dict, list[dict]]] = []
    skipped: list[dict] = []
    for n, idea in enumerate(ideas):
        ctx.check_cancel()
        state["activity"] = f"cherche « {idea['query']} »"
        ctx.progress = 0.3 + 0.3 * n / len(ideas)
        ctx.save(force=True)
        try:
            results = _search(idea)
        except ValueError as e:
            skipped.append({"label": idea["label"], "reason": str(e)})
            continue
        if results:
            found.append((idea, results))
        else:
            skipped.append({"label": idea["label"], "reason": "rien trouvé dans les catalogues"})
    if not found:
        raise RuntimeError("Aucun son trouvé pour les idées de Claude : " + "; ".join(s["reason"] for s in skipped[:2]))

    state["activity"] = "choisit les sons"
    ctx.progress = 0.65
    ctx.save(force=True)
    picked = ask(ctx, pick_prompt(found), SYSTEM.format(lang=language_name()), "Read", None, PICK_SCHEMA,
                 out["session_id"])
    picks = {x.get("idea"): x for x in (picked["output"] or {}).get("picks") or []}

    placed: list[dict] = []
    audio = list(kept)
    music_until = 0.0
    for n, (idea, results) in enumerate(found, 1):
        ctx.check_cancel()
        pick = picks.get(n) or {}
        k = pick.get("candidate")
        if not isinstance(k, int) or not 1 <= k <= len(results):
            skipped.append({"label": idea["label"], "reason": pick.get("reason") or "aucun candidat ne convenait"})
            continue
        choice = results[k - 1]
        line = by_n[idea["line"]]
        at = line["start"] if idea.get("where") != "end" else line["end"]
        length = choice["duration"] or 0.0
        if idea["kind"] == "musique":
            last = by_n.get(idea.get("until")) or line
            at = max(at, music_until)
            dur = max(last["end"], at + 10.0) - at
            dur = min(dur, total - at, length or dur)
            music_until = at + dur
        else:
            dur = min(float(idea.get("seconds") or SFX_MAX), SFX_MAX, length or SFX_MAX)
        if dur < 0.3 or at >= total:
            skipped.append({"label": idea["label"], "reason": "plus de place à cet endroit de la vidéo"})
            continue
        state["activity"] = f"télécharge « {choice['title'][:40]} »"
        ctx.progress = 0.7 + 0.3 * n / len(found)
        ctx.save(force=True)
        try:
            rel = free_audio.add(idea["kind"], choice["id"])
        except ValueError as e:
            skipped.append({"label": idea["label"], "reason": str(e)})
            continue
        gain = library.gains().get(rel, GAIN[idea["kind"]])
        audio.append({"id": f"{PREFIX}{uuid.uuid4().hex[:8]}", "src": f"library/{rel}", "at": round(at, 3), "in": 0.0,
                      "out": round(dur, 3), "gain_db": gain, "role": "music" if idea["kind"] == "musique" else "sfx"})
        placed.append({"label": idea["label"], "kind": idea["kind"], "why": idea["why"], "at": round(at, 2),
                       "dur": round(dur, 2), "title": choice["title"], "creator": choice["creator"],
                       "license": choice["license"], "required": choice["required"], "url": choice["url"],
                       "reason": pick.get("reason", ""), "said": line["text"][:120]})
    if not placed:
        raise RuntimeError("Aucun son n'a pu être posé : " + "; ".join(s["reason"] for s in skipped[:2]))
    # relue juste avant d'écrire : l'auteur a pu retoucher la timeline pendant la recherche
    fresh = montage.load(pid)
    fresh["audio"] = [s for s in fresh["audio"] if not s["id"].startswith(PREFIX)] + [s for s in audio if s["id"].startswith(PREFIX)]
    montage.save(pid, fresh)
    state.update(result={"placed": placed, "skipped": skipped, "message": output.get("message", "")}, activity=None)


def result(job_id: str | None) -> dict | None:
    job = jobs.get(job_id) if job_id else None
    if not job:
        return None
    return {"status": job.status, "finished": job.finished, "progress": job.progress, "error": job.error,
            "activity": job.state.get("activity"), "note": job.payload.get("note", ""),
            "result": job.state.get("result") if job.status == "done" else None}
