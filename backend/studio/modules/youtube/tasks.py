"""
Telechargement cote worker, avec l'avancement pousse en base.
"""
import copy
import threading
from contextlib import contextmanager
from pathlib import Path

import yt_dlp
from yt_dlp.downloader import external
from yt_dlp.utils import download_range_func

from ...core import jobs
from ...core.tasks import Cancelled, Task, TaskContext
from ..transcript import service as transcript
from . import service


@contextmanager
def _kill_ffmpeg_on_cancel(ctx: TaskContext):
    """Un extrait passe par ffmpeg, qui ne remonte aucun avancement : les hooks ne voient donc jamais
    l'annulation. On la guette a cote, et on tue les process lances par yt-dlp."""
    procs = []

    class Tracked(external.Popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            procs.append(self)

    stop = threading.Event()

    def watch():
        while not stop.wait(TaskContext.CANCEL_CHECK_EVERY):
            if jobs.is_cancel_requested(ctx.job.id):
                for proc in procs:
                    if proc.poll() is None:
                        proc.kill()
                return

    # la file "network" ne fait qu'un telechargement a la fois : remplacer Popen le temps de celui-ci suffit
    original = external.Popen
    external.Popen = Tracked
    threading.Thread(target=watch, daemon=True).start()
    try:
        yield
    finally:
        stop.set()
        external.Popen = original


def _remove_partials(out_dir: Path, video_id: str | None) -> None:
    """Ce qu'un telechargement annule laisse derriere lui (.part, .part-Frag12, .ytdl)."""
    if not video_id:
        return
    for f in out_dir.iterdir():
        if f"[{video_id}]" in f.name and (".part" in f.name or f.suffix == ".ytdl"):
            f.unlink(missing_ok=True)


def download(ctx: TaskContext) -> None:
    p, state = ctx.payload, ctx.state
    out_dir = Path(p["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    state.update(stream=0, downloaded=0, total=None, speed=None, eta=None)

    def on_progress(d: dict):
        ctx.check_cancel()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            state.update(downloaded=d.get("downloaded_bytes") or 0, total=total,
                         speed=d.get("speed"), eta=d.get("eta"))
            if total:
                ctx.progress = min(state["downloaded"] / total, 1.0)
            ctx.save()
        elif d["status"] == "finished":
            # video puis audio : deux flux telecharges l'un apres l'autre
            state["stream"] += 1
            ctx.save(force=True)

    def on_postprocess(d: dict):
        if d["status"] == "started":
            ctx.set_status("processing")

    name = "%(title)s [%(id)s]"
    clip = {}
    if p.get("start") is not None:
        name += " " + service.clip_suffix(p["start"], p["end"], p.get("label"))
        # yt-dlp passe alors par ffmpeg, qui ne lit que la plage demandee (pas d'avancement en cours de route)
        # en audio, la copie de flux sans re-encodage rend une duree fausse ; re-encoder l'audio ne coute rien
        clip = {"download_ranges": download_range_func(None, [(p["start"], p["end"])]),
                "force_keyframes_at_cuts": p.get("precise", False) or p["mode"] == "audio"}

    postprocessors = []
    if p["mode"] == "audio":
        postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": "m4a"})
    if p["mode"] == "thumbnail":
        # la miniature seule (la meilleure dispo), en jpg : YouTube la sert souvent en webp
        opts = service.ydl_options(
            skip_download=True, writethumbnail=True, ignore_no_formats_error=True,
            outtmpl=str(out_dir / f"{name}.%(ext)s"),
            postprocessors=[{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}],
        )
    else:
        opts = service.ydl_options(
            format=service.format_selector(p["mode"], p["max_height"], p["mp4"], clip=bool(clip)),
            outtmpl=str(out_dir / f"{name}.%(ext)s"),
            progress_hooks=[on_progress],
            postprocessor_hooks=[on_postprocess],
            postprocessors=postprocessors,
            **({"merge_output_format": "mp4"} if p["mode"] == "video" and p["mp4"] else {}),
            **clip,
        )

    ctx.set_status("probing")
    info = {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl, _kill_ffmpeg_on_cancel(ctx):
            info = ydl.extract_info(p["url"], download=False, process=False)
            state.update(title=info.get("title"), uploader=info.get("uploader"),
                         duration=info.get("duration"), thumbnail=info.get("thumbnail"))
            ctx.save(force=True)
            if clip:
                # les segments audio HLS de YouTube sont des .aac, que ffmpeg (>= 7.1) refuse sans
                # -extension_picky 0 ; option propre au HLS, qui ferait echouer une entree https
                chosen = ydl.process_ie_result(copy.deepcopy(info), download=False)
                ydl.params["external_downloader_args"] = {
                    f"ffmpeg_i{n + 1}": ["-extension_picky", "0"]
                    for n, f in enumerate(chosen.get("requested_formats") or [chosen])
                    if f.get("protocol") == "m3u8_native"}
            ctx.set_status("downloading")
            info = ydl.process_ie_result(info, download=True)
    except Exception as e:
        # yt-dlp enrobe parfois l'exception levee dans le hook ; un ffmpeg tue le fait echouer
        if isinstance(e, Cancelled) or jobs.is_cancel_requested(ctx.job.id):
            _remove_partials(out_dir, info.get("id"))
            raise Cancelled() from e
        raise

    if p["mode"] == "thumbnail":
        filepath = next((t["filepath"] for t in info.get("thumbnails") or [] if t.get("filepath")), None)
    else:
        downloads = info.get("requested_downloads") or []
        filepath = downloads[0].get("filepath") if downloads else None
    if not filepath:
        raise RuntimeError("yt-dlp n'a renvoye aucun fichier")
    state["filepath"] = filepath

    if p["transcribe"] and p["mode"] != "thumbnail":
        job = transcript.create_jobs([Path(filepath)], p["language"], "line",
                                     sequence=False, output_dir=out_dir)[0]
        state["transcript_job"] = job.id


TASKS = {service.KIND: Task(queue="network", run=download)}
