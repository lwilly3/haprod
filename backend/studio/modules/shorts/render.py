"""
Montage d'un short avec ffmpeg : les extraits du rush colles bout a bout, dans
l'ordre du montage, recadres en vertical (ou au format d'origine).

Les extraits sont en temps global : dans une sequence de plusieurs fichiers, un
extrait a cheval sur deux fichiers est coupe en deux morceaux.
"""
import json
import subprocess
from pathlib import Path
from typing import Callable

from ...core.system import tool

VERTICAL = (1080, 1920)
# fondu tres court a chaque coupe : evite les clics dans le son
FADE = 0.03


def probe(source: Path) -> dict:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", str(source)],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    streams = json.loads(out).get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        return {"video": False}
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(num or 0) else 30.0
    width, height = int(video["width"]), int(video["height"])
    # telephone filme en portrait : la rotation est dans les metadonnees
    rotation = abs(int(next((d.get("rotation", 0) for d in video.get("side_data_list", [])
                             if "rotation" in d), 0)))
    if rotation in (90, 270):
        width, height = height, width
    return {"video": True, "width": width, "height": height, "fps": round(fps, 3)}


def pieces(clips: list[list[float]], parts: list[dict]) -> list[tuple[int, float, float]]:
    """(fichier, debut, fin) en temps local a chaque fichier."""
    out = []
    for start, end in clips:
        for i, part in enumerate(parts):
            p0, p1 = part["start"], part["start"] + part["duration"]
            a, b = max(start, p0), min(end, p1)
            if b - a > 0.05:
                out.append((i, a - p0, b - p0))
    return out


def _even(n: float) -> int:
    return int(n) // 2 * 2


def render(sources: list[Path], parts: list[dict], clips: list[list[float]], fmt: str, dest: Path,
           on_progress: Callable[[float], None], check_cancel: Callable[[], None]) -> None:
    cuts = pieces(clips, parts)
    if not cuts:
        raise RuntimeError("aucun extrait à monter")
    info = probe(sources[cuts[0][0]])
    has_video = info["video"]
    total = sum(b - a for _, a, b in cuts)

    args = [tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
    for i, a, b in cuts:
        args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(sources[i])]

    if has_video:
        if fmt == "vertical":
            w, h = VERTICAL
            # remplit le cadre puis coupe ce qui depasse, centre
            frame = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        else:
            w, h = _even(info["width"]), _even(info["height"])
            frame = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        # tous les morceaux au meme format, sinon concat refuse
        vf = f"{frame},setsar=1,fps={info['fps']},format=yuv420p,setpts=PTS-STARTPTS"
    filters, labels = [], []
    for k, (_, a, b) in enumerate(cuts):
        d = b - a
        if has_video:
            filters.append(f"[{k}:v:0]{vf}[v{k}]")
            labels.append(f"[v{k}]")
        filters.append(f"[{k}:a:0]aresample=48000,aformat=channel_layouts=stereo,"
                       f"afade=t=in:d={FADE},afade=t=out:st={max(d - FADE, 0):.3f}:d={FADE},"
                       f"asetpts=PTS-STARTPTS[a{k}]")
        labels.append(f"[a{k}]")
    filters.append(f"{''.join(labels)}concat=n={len(cuts)}:v={int(has_video)}:a=1"
                   + ("[v][a]" if has_video else "[a]"))
    args += ["-filter_complex", ";".join(filters)]
    if has_video:
        # une image cle par seconde : le navigateur et le rendu HyperFrames s'y deplacent sans figer
        args += ["-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-g", str(max(1, round(info["fps"])))]
    args += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".part.mp4")
    proc = subprocess.Popen([*args, str(partial)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    try:
        for line in proc.stdout:
            check_cancel()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit() and total:
                on_progress(min(int(value) / 1e6 / total, 1.0))
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg a échoué : {proc.stderr.read().strip()[-400:]}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.returncode != 0:
            partial.unlink(missing_ok=True)
    partial.replace(dest)
