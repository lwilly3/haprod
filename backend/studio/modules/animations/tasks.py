"""
Un tour de conversation cote worker : `claude -p` dans le dossier du projet. Claude y
ecrit lui-meme le plan et les compositions ; on suit son activite au fil de l'eau.
"""
import re
import time
from pathlib import Path

from ...core import claude, jobs
from ...core.tasks import Task, TaskContext
from ..projects import media
from ..settings.service import claude_model
from . import captions, service
from . import render as montage

_FILE_PATH = re.compile(r'"file_path"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _tool_label(block: dict) -> str:
    args = block.get("input") or {}
    target = args.get("file_path") or args.get("pattern") or ""
    name = Path(target).name if "file_path" in args else target
    verb = {"Write": "écrit", "Edit": "retouche", "Read": "lit"}.get(block["name"], block["name"])
    return f"{verb} {name}".strip()


def _writing_label(tool: str, partial: str) -> str:
    """« écrit s3.html · 2,4 Ko » d'apres l'entree JSON encore incomplete de l'outil."""
    found = _FILE_PATH.search(partial)
    label = _tool_label({"name": tool, "input": {"file_path": found.group(1)} if found else {}})
    size = f"{len(partial) / 1024:.1f}".replace(".", ",")
    return f"{label} · {size} Ko"


def chat(ctx: TaskContext) -> None:
    state, job = ctx.state, ctx.job
    messages = state["messages"]
    # un tour interrompu (worker relance) repart de zero
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()
    directory = service.project_dir(job)
    # pas encore de session (premier tour, ou premier tour annule avant de demarrer)
    prompt = service.turn_prompt(job, first=not state.get("session_id"))

    service.snapshot(directory)
    plan_before = service.plan_text(directory)
    started = time.time()
    reply = service.message("assistant", "")
    reply["tools"] = []
    messages.append(reply)
    state["activity"] = None
    ctx.set_status("thinking")
    ctx.save(force=True)

    settings = {**service.DEFAULT_SETTINGS, **state.get("settings", {})}
    has_captions = (directory / captions.JSON_FILE).is_file()
    events = claude.stream(prompt, directory, service.system_prompt(settings, has_captions),
                           state.get("session_id"), ctx.payload.get("model") or claude_model("heavy"), ctx.check_cancel)
    status = "thinking"
    # l'outil en cours : son nom et son entree JSON, qui arrive par morceaux
    tool, tool_input = "", ""

    def set_status(new: str) -> None:
        nonlocal status
        if new != status:
            status = new
            ctx.set_status(new)

    try:
        for event in events:
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                state["session_id"] = event["session_id"]
                state["model"] = event.get("model")
                # "none" : pas de cle API, c'est l'abonnement claude.ai qui sert
                state["auth"] = event.get("apiKeySource")
                ctx.save(force=True)
            elif kind == "stream_event":
                e = event["event"]
                block = e.get("content_block") or {}
                delta = e.get("delta") or {}
                if e["type"] == "content_block_start" and block.get("type") == "text" and reply["text"]:
                    reply["text"] += "\n\n"
                elif e["type"] == "content_block_start" and block.get("type") == "thinking":
                    set_status("thinking")
                    state["activity"] = "réfléchit"
                    ctx.save(force=True)
                elif e["type"] == "content_block_start" and block.get("type") == "tool_use":
                    set_status("working")
                    tool, tool_input = block.get("name", ""), ""
                    state["activity"] = _tool_label({"name": tool})
                    ctx.save(force=True)
                elif delta.get("type") == "input_json_delta":
                    # un gros fichier s'ecrit en une ou deux minutes : on montre qu'il avance
                    tool_input += delta.get("partial_json", "")
                    state["activity"] = _writing_label(tool, tool_input)
                    ctx.save()
                elif delta.get("type") == "text_delta":
                    set_status("writing")
                    reply["text"] += delta["text"]
                    ctx.save()
            elif kind == "assistant":
                for block in event["message"]["content"]:
                    if block["type"] == "tool_use":
                        label = _tool_label(block)
                        reply["tools"].append(label)
                        state["activity"] = label
                        ctx.save(force=True)
            elif kind == "rate_limit_event":
                # remplissage des fenetres de l'abonnement (5 h, 7 jours)
                windows = event["rate_limit_info"].get("unifiedWindows") or {}
                state["usage"] = {k: w.get("utilization") for k, w in windows.items()}
            elif kind == "result":
                reply["duration"] = event.get("duration_ms")
                if event.get("is_error"):
                    raise RuntimeError(event.get("result") or "Claude a renvoye une erreur")
                # le texte affiche : seulement la reponse finale, pas les commentaires entre deux outils
                reply["text"] = event.get("result") or reply["text"]
    finally:
        state["activity"] = None
        reply["changed"] = service.changed_since(directory, started)
        # une simple question ne laisse pas d'etape vide dans l'historique
        if not reply["changed"] and service.plan_text(directory) == plan_before:
            service.drop_last_snapshot(directory)


def render_video(ctx: TaskContext) -> None:
    """Rendu final : video + slides gardees + sous-titres, par HyperFrames."""
    project = jobs.get(ctx.payload["project"])
    if project is None:
        raise RuntimeError("le projet a été supprimé")
    directory = service.project_dir(project)
    duration = project.payload["duration"]
    with_captions = captions.build(directory, duration, service.size(project))
    slides = [s for s in service.slides_with_files(project) if not s["discarded"] and s["url"]]
    info = media.probe(directory / project.payload["video"])
    num, den = info.get("fps_num") or 30, info.get("fps_den") or 1
    montage.write_index(directory, project.payload["video"], duration, service.size(project),
                        slides, with_captions, fps=str(num) if den == 1 else f"{num}/{den}")
    ctx.set_status("rendering")

    def on_progress(value: float, stage: str) -> None:
        ctx.progress = value
        ctx.state["stage"] = stage
        ctx.save()

    montage.render(directory, service.render_output(ctx.job), on_progress, ctx.check_cancel)


TASKS = {service.KIND: Task(queue="claude", run=chat),
         service.RENDER_KIND: Task(queue="render", run=render_video)}
