"""
Cote worker :
- select : un tour de `claude -p`, qui renvoie les shorts en JSON (sortie structuree) ;
  on verifie les durees, un short trop long repart chez Claude pour correction ;
- render : le montage d'un short par ffmpeg.
"""
import time

from ...core import claude, jobs
from ...core.tasks import Task, TaskContext
from ..settings.service import claude_model
from ..transcript import service as transcript
from . import render as montage
from . import service


def _ask(ctx: TaskContext, prompt: str) -> dict:
    """Un echange avec Claude, en reprenant la session ; retourne sa reponse structuree."""
    state = ctx.state
    events = claude.stream(prompt, service.WORK_DIR, service.system_prompt(state["settings"]),
                           state.get("session_id"), ctx.payload.get("model") or claude_model("heavy"), ctx.check_cancel,
                           tools="", json_schema=service.SCHEMA)
    size, status, output = 0, "", None

    def set_status(new: str) -> None:
        nonlocal status
        if new != status:
            status = new
            ctx.set_status(new)

    for event in events:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            state["session_id"] = event["session_id"]
            state["model"] = event.get("model")
            ctx.save(force=True)
        elif kind == "stream_event":
            e = event["event"]
            block = e.get("content_block") or {}
            delta = e.get("delta") or {}
            if e["type"] == "content_block_start" and block.get("type") == "thinking":
                set_status("thinking")
                state["activity"] = "réfléchit"
                ctx.save(force=True)
            elif delta.get("type") == "input_json_delta":
                # la selection s'ecrit dans l'outil de sortie structuree
                size += len(delta.get("partial_json", ""))
                set_status("writing")
                state["activity"] = f"rédige la sélection · {size / 1024:.1f} Ko".replace(".", ",")
                ctx.save()
        elif kind == "rate_limit_event":
            windows = event["rate_limit_info"].get("unifiedWindows") or {}
            state["usage"] = {k: w.get("utilization") for k, w in windows.items()}
        elif kind == "result":
            if event.get("is_error"):
                raise RuntimeError(event.get("result") or "Claude a renvoye une erreur")
            # on laisse le process finir (et enregistrer la session) avant de rendre la main
            output = event.get("structured_output")
    if not isinstance(output, dict):
        raise RuntimeError("Claude n'a pas renvoyé de sélection exploitable")
    return output


def select(ctx: TaskContext) -> None:
    state, job = ctx.state, ctx.job
    messages = state["messages"]
    # un tour interrompu (worker relance) repart de zero
    while messages and messages[-1]["role"] == "assistant":
        messages.pop()
    service.WORK_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    lines, max_duration = state["lines"], state["settings"]["max_duration"]

    output = _ask(ctx, service.turn_prompt(job, first=not state.get("session_id")))
    shorts, problems = service.evaluate(output.get("shorts") or [], lines, max_duration)
    fixes = 0
    while problems and fixes < service.MAX_FIXES:
        fixes += 1
        ctx.set_status("fixing")
        state["activity"] = f"corrige les durées ({fixes}/{service.MAX_FIXES})"
        ctx.save(force=True)
        output = _ask(ctx, service.fix_prompt(shorts, problems))
        shorts, problems = service.evaluate(output.get("shorts") or [], lines, max_duration)

    state["shorts"] = shorts
    state["activity"] = None
    reply = service.message("assistant", str(output.get("message") or ""))
    reply["duration"] = round((time.time() - started) * 1000)
    reply["fixes"] = fixes
    messages.append(reply)
    # pas de montage ici : un short n'est decoupe que lorsqu'on l'envoie au montage


def render(ctx: TaskContext) -> None:
    payload = ctx.payload
    source = jobs.get(payload["transcript_job"])
    if source is None:
        raise RuntimeError("le transcript d'origine a été supprimé")
    ctx.set_status("rendering")

    def on_progress(value: float) -> None:
        ctx.progress = value
        ctx.save()

    montage.render(transcript.sources(source), source.state["parts"], payload["clips"],
                   payload["format"], service.render_file(ctx.job), on_progress, ctx.check_cancel)


TASKS = {service.KIND: Task(queue="claude", run=select),
         service.RENDER_KIND: Task(queue="ffmpeg", run=render)}
