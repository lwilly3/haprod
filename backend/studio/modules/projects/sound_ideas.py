"""
Des sons et des musiques suggérés pour le projet : Claude lit le script et ce qui se dit dans les
rushes, propose des idées (une ambiance musicale, un bruitage sur un moment précis), et chaque idée
est aussitôt cherchée parmi les sons libres de droits (free_audio) : l'auteur écoute et ajoute.

Claude ne choisit pas les fichiers : il donne des mots-clés, la recherche trouve, l'auteur décide.
"""
from ...core import jobs
from ...core.tasks import TaskContext
from ..settings.service import language_name
from . import free_audio, runtime, service

KIND = "project_sound_ideas"
# ce qu'on montre par idée, et ce que Claude lit au plus (caractères) du script et du transcript
RESULTS = 4
MAX_TEXT = 14000

SYSTEM = """You are the sound designer of a YouTube video. From the script and what is said in the footage, \
you suggest sounds worth looking for in royalty-free libraries (Freesound for sound effects, Jamendo for music).

Suggest 6 to 10 ideas: 2 or 3 pieces of music (a mood for the intro, for the body, for a turning point), the \
rest sound effects tied to a precise moment (a transition, an emphasis, an ambience the footage lacks).
- `query`: 1 to 3 plain English keywords, the way these libraries are tagged ("crowd cheering", "whoosh", \
"upbeat african percussion"). No sentence, no artist name, no title.
- `label`: a short name for the idea, in {lang}.
- `moment`: where it goes, in {lang}: a few quoted words of the script or the footage, or the part of the video.
- `why`: one sentence, in {lang}: what the sound adds there.
Only suggest what serves the video: a talking-head video needs few effects. `message`: one or two sentences \
in {lang} on your overall approach."""

SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "ideas": {"type": "array", "items": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["sfx", "musique"]}, "query": {"type": "string"},
                           "label": {"type": "string"}, "moment": {"type": "string"}, "why": {"type": "string"}},
            "required": ["kind", "query", "label", "moment", "why"]}},
    },
    "required": ["ideas"],
}


def _spoken(project: dict) -> str:
    """Ce qui se dit dans les rushes gardés, une ligne par phrase."""
    try:
        segs = runtime.analysis(project, edited=False)["segs"]
    except Exception:  # noqa: BLE001  des rushes pas encore transcrits : on s'en passe
        return ""
    return "\n".join(s["text"] for s in segs if s.get("type") == "speech" and s.get("text"))


def prompt(project: dict, note: str) -> str:
    sel = project.get("angle_sel")
    angle = project["angles"][sel]["t"] if sel is not None and 0 <= sel < len(project["angles"]) else ""
    script = service.read_doc(project["id"], service.SCRIPT_FILE).strip()
    spoken = _spoken(project)
    parts = [f"Video: {project['title']}", f"Idea: {project['brief'].get('idea', '')}"]
    if angle:
        parts.append(f"Angle: {angle}")
    if script:
        parts += ["", "Script:", script[:MAX_TEXT]]
    if spoken:
        parts += ["", "What is said in the footage:", spoken[:MAX_TEXT]]
    if not script and not spoken:
        parts += ["", "There is no script or transcript yet: work from the idea."]
    if note.strip():
        parts += ["", f"Author's request: {note.strip()}"]
    return "\n".join(parts)


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p, state = ctx.payload, ctx.state
    project = service.load(p["project"])
    out = ask(ctx, prompt(project, p.get("note", "")), SYSTEM.format(lang=language_name()), "Read", None, SCHEMA)
    output = out["output"] or {}
    ideas = [i for i in output.get("ideas") or [] if i.get("kind") in free_audio.FILTERS and (i.get("query") or "").strip()]
    if not ideas:
        raise RuntimeError("Claude n'a proposé aucun son.")
    items = []
    for n, idea in enumerate(ideas):
        ctx.check_cancel()
        state["activity"] = f"cherche « {idea['query']} »"
        ctx.progress = 0.5 + 0.5 * n / len(ideas)
        ctx.save(force=True)
        try:
            found, error = free_audio.search(idea["kind"], idea["query"])["items"][:RESULTS], None
            words = idea["query"].split()
            # trop précis pour le catalogue (« african percussion upbeat ») : on élargit en retirant le dernier mot
            while not found and len(words) > 1:
                words = words[:-1]
                found = free_audio.search(idea["kind"], " ".join(words))["items"][:RESULTS]
        except ValueError as e:
            # la limite d'Openverse, ou une coupure : l'idée reste, l'auteur relancera la recherche à la main
            found, error = [], str(e)
        items.append({**idea, "results": found, "error": error})
    state.update(result={"items": items, "message": output.get("message", "")}, activity=None)


def result(job_id: str | None) -> dict | None:
    """L'état des suggestions pour l'interface."""
    job = jobs.get(job_id) if job_id else None
    if not job:
        return None
    return {"status": job.status, "finished": job.finished, "progress": job.progress, "error": job.error,
            "activity": job.state.get("activity"), "note": job.payload.get("note", ""),
            "result": job.state.get("result") if job.status == "done" else None}
