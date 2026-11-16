"""
Cote worker : l'analyse de la chaine. On recupere quelques transcriptions avec yt-dlp (le
MCP ytwatch n'en fournit pas), puis un tour de `claude -p` branche sur le MCP propose le profil.
"""
import re
import shutil
import threading
from pathlib import Path

from ...core import claude
from ...core.tasks import Task, TaskContext
from . import analysis, service

TRANSCRIPTS = 3
# en dessous, c'est un Short ou un extrait : pas representatif du ton
MIN_DURATION = 240
MAX_CHARS = 20000
TOOL_LABELS = {
    "list_my_channels": "cherche la chaîne", "get_channel_stats": "lit les stats de la chaîne",
    "get_daily_stats": "lit l'historique", "list_videos": "lit les vidéos",
    "get_video": "regarde une vidéo", "get_outliers": "cherche les hits et les flops",
}


def _vtt_text(vtt: str) -> str:
    """Sous-titres automatiques : chaque ligne y apparait plusieurs fois (defilement), avec des balises."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        if "-->" in raw or raw.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        line = re.sub(r"<[^>]+>", "", raw).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return " ".join(lines)


def _transcripts(ctx: TaskContext, channel_url: str, folder: Path) -> list[str]:
    """Les transcriptions des dernières longues vidéos, en .txt dans `folder` ; rend leurs noms."""
    import yt_dlp

    from ..youtube.service import ydl_options

    ctx.state["activity"] = "récupère les transcriptions"
    ctx.save(force=True)
    # lang : sinon YouTube renvoie certains titres traduits dans une autre langue
    with yt_dlp.YoutubeDL(ydl_options(extract_flat=True, skip_download=True, playlistend=15, noplaylist=False,
                                      extractor_args={"youtube": {"lang": [service.language()]}})) as ydl:
        listing = ydl.extract_info(f"{channel_url.rstrip('/')}/videos", download=False)
    videos = [e for e in (listing or {}).get("entries") or [] if (e.get("duration") or 0) >= MIN_DURATION]
    # la langue de la chaine d'abord, puis l'anglais
    langs_order = list(dict.fromkeys((service.language(), "en")))
    sub_langs = [[f"{lang}-orig", lang] for lang in langs_order]
    names = []
    for video in videos[:TRANSCRIPTS]:
        subs: dict[str, Path] = {}
        # une langue a la fois : demander l'anglais pour rien vaut souvent un 429 qui fait tout echouer
        for langs in sub_langs:
            ctx.check_cancel()
            options = ydl_options(skip_download=True, writeautomaticsub=True, writesubtitles=True,
                                  subtitleslangs=langs, subtitlesformat="vtt",
                                  outtmpl=str(folder / "%(id)s.%(ext)s"))
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download([video["url"]])
            except yt_dlp.utils.DownloadError:
                pass  # une des langues a echoue : les autres sont peut-etre la
            subs = {p.name.split(".")[-2]: p for p in folder.glob(f"{video['id']}.*.vtt")}
            if subs:
                break
        lang = next((lang for group in sub_langs for lang in group if lang in subs), None)
        if lang:
            text = _vtt_text(subs[lang].read_text(encoding="utf-8"))[:MAX_CHARS]
            name = f"{video['id']}.txt"
            (folder / name).write_text(f"# {video.get('title', '')}\n\n{text}\n", encoding="utf-8")
            names.append(name)
        for p in subs.values():
            p.unlink()
    return names


def analyse(ctx: TaskContext) -> None:
    p = ctx.payload
    work = service.WORK_DIR
    folder = work / analysis.TRANSCRIPTS_DIR
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    profile = service.channel()
    (work / analysis.PROFILE_FILE).write_text(
        "\n\n".join(f"## {label}\n{profile[key] or '(vide)'}" for key, label, _ in service.FIELDS) + "\n",
        encoding="utf-8")

    # la langue de la chaine d'abord, puis l'anglais
    langs_order = list(dict.fromkeys((service.language(), "en")))
    sub_langs = [[f"{lang}-orig", lang] for lang in langs_order]
    names = []
    if p.get("channel_url"):
        try:
            names = _transcripts(ctx, p["channel_url"], folder)
        except Exception as e:  # noqa: BLE001  sans transcription, l'analyse reste utile (sans le ton)
            ctx.state["warning"] = f"transcriptions indisponibles : {e}"

    config = work / "mcp.json"
    service.mcp_config(config)
    ctx.set_status("thinking")
    ctx.state["activity"] = "réfléchit"
    ctx.save(force=True)
    output = None
    try:
        for event in claude.stream(analysis.prompt(p.get("channel_id"), names), work,
                                   analysis.system(service.YTWATCH_SERVER), None, service.claude_model("light"), ctx.check_cancel,
                                   tools=analysis.TOOLS, json_schema=analysis.SCHEMA,
                                   allowed_tools=f"mcp__{service.YTWATCH_SERVER}", mcp_config=config):
            kind = event.get("type")
            if kind == "assistant":
                for block in event["message"]["content"]:
                    if block["type"] == "tool_use" and block.get("name") != "StructuredOutput":
                        name = block["name"].split("__")[-1]
                        ctx.state["activity"] = TOOL_LABELS.get(name, "lit les transcriptions" if name in (
                            "Read", "Glob", "Grep") else name)
                        ctx.set_status("working")
                        ctx.save(force=True)
            elif kind == "result":
                if event.get("is_error"):
                    raise RuntimeError(event.get("result") or "Claude a renvoyé une erreur")
                output = event.get("structured_output")
    finally:
        # le jeton ne reste pas sur le disque plus que le temps du tour
        config.unlink(missing_ok=True)
    if not output:
        raise RuntimeError("Claude n'a pas renvoyé de profil exploitable")
    ctx.state["activity"] = None
    ctx.state["result"] = output


def youtube_connect(ctx: TaskContext) -> None:
    """Le consentement Google attend dans le navigateur : on l'attend à côté, pour rester annulable."""
    from ...core import youtube_api

    result: dict = {}

    def wait() -> None:
        try:
            result["channel"] = youtube_api.connect()
        except Exception as e:  # noqa: BLE001  renvoyée au job
            result["error"] = e

    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    ctx.set_status("waiting")
    while thread.is_alive():
        thread.join(0.5)
        ctx.check_cancel()
    if "error" in result:
        raise result["error"]
    ctx.state["channel"] = result["channel"]


TASKS = {service.ANALYSIS_KIND: Task(queue="settings", run=analyse),
         service.YOUTUBE_KIND: Task(queue="youtube_auth", run=youtube_connect)}
