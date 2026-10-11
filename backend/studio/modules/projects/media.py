"""
Infos sur les fichiers vidéo / audio (ffprobe) : durée, image, date de tournage, timecode.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

from ...core.system import tool


def probe(path: Path) -> dict:
    """{duration, width, height, fps, fps_num, fps_den, audio, timecode, shot_at} ; vide si ffprobe échoue."""
    try:
        out = subprocess.run(
            [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=60,
        ).stdout
        data = json.loads(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError):
        return {}
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    info: dict = {"duration": float(fmt["duration"]) if fmt.get("duration") else None,
                  "audio": audio is not None,
                  "audio_channels": int(audio.get("channels") or 2) if audio else 0,
                  "audio_rate": int(audio.get("sample_rate") or 48000) if audio else 48000}
    if video:
        num, _, den = (video.get("r_frame_rate") or "25/1").partition("/")
        num, den = int(num or 25), int(den or 1)
        info.update(width=video.get("width"), height=video.get("height"),
                    fps=round(num / den, 3) if den else 25, fps_num=num, fps_den=den or 1)
    # timecode de départ inscrit par la caméra (DJI, Sony…) : Resolve relie les médias par lui
    info["timecode"] = ((fmt.get("tags") or {}).get("timecode")
                        or next((s["tags"]["timecode"] for s in streams if (s.get("tags") or {}).get("timecode")), None))
    created = ((fmt.get("tags") or {}).get("creation_time")
               or ((video or {}).get("tags") or {}).get("creation_time"))
    info["shot_at"] = _local_time(created) if created else _mtime(path)
    return info


def timecode_frames(timecode: str | None, fps_num: int, fps_den: int) -> int:
    """Le numéro d'image d'un timecode « HH:MM:SS:FF » (« ; » : drop frame, en 29,97 / 59,94) ; 0 si illisible."""
    try:
        h, m, s, f = (int(x) for x in timecode.replace(";", ":").replace(".", ":").split(":"))
    except (AttributeError, ValueError):
        return 0
    nominal = round(fps_num / fps_den) if fps_den else 25
    drop = nominal // 15 if ";" in timecode and fps_den == 1001 else 0
    minutes = h * 60 + m
    return (minutes * 60 + s) * nominal + f - drop * (minutes - minutes // 10)


def _local_time(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return moment.astimezone().isoformat(timespec="seconds")


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None
