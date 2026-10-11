"""
Recuperation de videos (YouTube et tout ce que yt-dlp sait lire).

payload : url, mode (video | audio | thumbnail), max_height, mp4, output_dir, transcribe, language,
          start, end, label, precise (clip : seulement la plage start-end, en secondes)
state   : title, uploader, duration, thumbnail, filepath, stream, downloaded,
          total, speed, eta, transcript_job
"""
import os
import re
from pathlib import Path

from ...config import DATA_DIR
from ...core import jobs
from ...core.system import tool

MODULE = "youtube"
KIND = "download"

OUTPUT_DIR = Path(os.environ.get("YOUTUBE_OUTPUT_DIR", DATA_DIR / "downloads"))


def ydl_options(**extra) -> dict:
    return {
        # YouTube exige un runtime JS pour resoudre la signature 'n' ;
        # sans lui certains formats manquent et les URLs DASH sont bridees.
        # deno d'abord (defaut yt-dlp), node en repli.
        "js_runtimes": {"deno": {}, "node": {}},
        "ffmpeg_location": tool("ffmpeg"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        **extra,
    }


def probe(url: str) -> dict:
    """Titre, miniature, duree et resolutions d'une URL ; ValueError si yt-dlp ne sait pas la lire."""
    import yt_dlp  # import differe : l'API redemarre a chaque modif, autant qu'elle reste legere

    try:
        with yt_dlp.YoutubeDL(ydl_options(skip_download=True)) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise ValueError(str(e).removeprefix("ERROR: ")) from e
    heights = sorted({f["height"] for f in info.get("formats", [])
                      if f.get("height") and f.get("vcodec") not in (None, "none")}, reverse=True)
    return {"id": info.get("id"), "extractor_key": info.get("extractor_key"),
            "title": info.get("title"), "uploader": info.get("uploader"),
            "duration": info.get("duration"), "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url"), "heights": heights}


def format_selector(mode: str, max_height: int | None, mp4: bool, clip: bool = False) -> str:
    # extrait : ffmpeg saute directement au bon segment d'un flux HLS, alors que dans un fichier
    # unique (DASH https) il lit tout ce qui precede, et YouTube le bride : des minutes pour 7 s en fin de video longue
    hls = "[protocol=m3u8_native]"
    if mode == "audio":
        return f"ba{hls}/ba/b" if clip else "ba/b"
    h = f"[height<={max_height}]" if max_height else ""
    if mp4:
        # h264/aac en mp4 : s'importe tel quel dans n'importe quel logiciel de montage
        sel = f"bv*{h}[ext=mp4]+ba[ext=m4a]/b{h}[ext=mp4]/bv*{h}+ba/b{h}"
        return f"bv*{h}[vcodec^=avc1]{hls}+ba{hls}/{sel}" if clip else sel
    sel = f"bv*{h}+ba/b{h}"
    return f"bv*{h}{hls}+ba{hls}/{sel}" if clip else sel


def create_job(url: str, mode: str, max_height: int | None, mp4: bool,
               output_dir: Path, transcribe: bool, language: str | None,
               clip: dict | None = None, precise: bool = False) -> jobs.Job:
    payload = {"url": url, "mode": mode, "max_height": max_height, "mp4": mp4,
               "output_dir": str(output_dir), "transcribe": transcribe, "language": language}
    if clip:
        payload.update(start=clip["start"], end=clip["end"], label=clip.get("label") or "", precise=precise)
    return jobs.create(MODULE, KIND, payload)


def clip_suffix(start: float, end: float, label: str | None) -> str:
    """'01m30s-03m45s intro' : la plage dans le nom, pour ne pas ecraser la video entiere ni les autres clips."""
    def stamp(sec: float) -> str:
        s = int(sec)
        h, m = divmod(s // 60, 60)
        return (f"{h}h" if h else "") + f"{m:02d}m{s % 60:02d}s"

    # le libelle va tel quel dans le modele de nom yt-dlp : ni caracteres interdits sous Windows, ni '%'
    label = re.sub(r'[<>:"/\\|?*%]', "", label or "").strip()
    return f"{stamp(start)}-{stamp(end)}" + (f" {label}" if label else "")


def transcript_job(job: jobs.Job) -> str | None:
    """Le transcript de la video, s'il existe encore (il a pu etre retire de la transcription)."""
    tid = job.state.get("transcript_job")
    return tid if tid and jobs.get(tid) else None


def summary(job: jobs.Job) -> dict:
    return {"id": job.id, "status": job.status, "progress": job.progress, "error": job.error,
            "elapsed": job.elapsed, "created_at": job.created_at,
            **job.payload, **job.state, "transcript_job": transcript_job(job)}
