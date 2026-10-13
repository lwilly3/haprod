"""Lay the timeline's music onto an existing render, without re-rendering the picture.

Usage: remix_render.py <pid> [quality=1080p]
- Only valid when the render matches the timeline except for the music (A-roll, zooms, overlays, texts and
  sound effects identical): checked, it stops otherwise. A contiguous blade cut without a transition
  changes the A-roll list but not the picture: confirm with the user and pass --allow-aroll.
- The music-free original is kept as rendu/<quality>-sans-musique.mp4 and is always the base: remixing
  twice never stacks the music. The video stream is copied; the audio is re-encoded once (AAC 320k).
- The render job is updated so the Rendu page shows the file as up to date.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import lufs

from studio.core import jobs
from studio.modules.projects import render, service


def is_music(s: dict) -> bool:
    return Path(s["path"]).parent.name == "music"


def main() -> None:
    pid = sys.argv[1]
    quality = next((a for a in sys.argv[2:] if not a.startswith("--")), "1080p")
    job = render.last_job(service.load(pid))
    assert job and job.status == "done" and job.payload["quality"] == quality, "no finished render in this quality"
    cur = render.plan(pid, quality)
    for k in ("zooms", "overlays", "texts") + (() if "--allow-aroll" in sys.argv else ("aroll",)):
        assert job.payload[k] == cur[k], f"{k} changed since the render: a full render is needed"
    assert [s for s in job.payload["sounds"] if not is_music(s)] == [s for s in cur["sounds"] if not is_music(s)], \
        "sound effects changed since the render: a full render is needed"
    dest = Path(job.payload["dest"])
    base = dest.with_name(f"{dest.stem}-sans-musique.mp4")
    if not base.is_file():
        assert not any(is_music(s) for s in job.payload["sounds"]), "the render already has music and no backup"
        shutil.copy2(dest, base)
    music = [s for s in cur["sounds"] if is_music(s)]
    work = dest.parent / ".tmp-music"
    work.mkdir(exist_ok=True)
    args, graph, labels = ["ffmpeg", "-y", "-v", "error", "-i", str(base)], [], ["[0:a]"]
    for i, s in enumerate(music, 1):
        args += ["-i", s["path"]]
        graph.append(f"[{i}:a]atrim=start={s['in']:.6f}:duration={s['out'] - s['in']:.6f},asetpts=PTS-STARTPTS,"
                     f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"volume={s['gain_db']}dB,adelay=delays={round(s['at'] * 1000)}:all=1[m{i}]")
        labels.append(f"[m{i}]")
    # same mix as render.mix_args: no normalisation, the first input (the render) sets the length
    graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0:dropout_transition=0[aout]")
    script = work / "mix.txt"
    script.write_text(";\n".join(graph), encoding="utf-8")
    out = work / dest.name
    subprocess.run(args + ["-filter_complex_script", str(script), "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-movflags", "+faststart", str(out)],
                   check=True)
    probe = lambda p: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                            "csv=p=0", str(p)], capture_output=True, text=True).stdout)
    assert abs(probe(out) - probe(base)) < 0.2, "duration changed"
    os.replace(out, dest)
    script.unlink()
    work.rmdir()
    jobs.update(job.id, payload={**job.payload, "aroll": cur["aroll"], "sounds": cur["sounds"],
                                 "signature": cur["signature"]})
    print(f"{len(music)} music clips · {probe(dest):.2f} s · {lufs(base):.1f} -> {lufs(dest):.1f} LUFS · "
          f"up to date: {render.view(service.load(pid), quality)['current']}")


if __name__ == "__main__":
    main()
