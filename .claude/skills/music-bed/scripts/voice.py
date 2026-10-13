"""Analyze the voice of the current timeline: A-roll audio mix, loudness, pauses, inserted clips, transcript.

Usage: voice.py <pid> [--no-stt]
Writes to the scratch dir: aroll.wav, silences.json, stt.json; prints a summary and the transcript.
"""
import json
import re
import subprocess
import sys

from common import inserted_clips, lufs, project_dir, timeline, total, work_dir


def mix_aroll(pid: str, tl: dict, dest) -> None:
    base = project_dir(pid)
    args, parts = ["ffmpeg", "-y", "-v", "error"], []
    for i, c in enumerate(tl["aroll"]):
        d = c["out"] - c["in"]
        src = base / (c.get("src") or "source/" + _source_name(pid))
        args += ["-ss", f"{c['in']:.3f}", "-t", f"{d:.3f}", "-i", str(src)]
        parts.append(f"[{i}:a]aresample=16000,aformat=channel_layouts=mono,volume={c.get('gain_db') or 0}dB,"
                     f"apad=whole_dur={d:.3f},atrim=0:{d:.3f}[a{i}]")
    n = len(tl["aroll"])
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[o]"
    subprocess.run(args + ["-filter_complex", graph, "-map", "[o]", str(dest)], check=True)


def _source_name(pid: str) -> str:
    project = json.loads((project_dir(pid) / "project.json").read_text(encoding="utf-8"))
    return project["source"]["name"]


def silences(wav, noise="-38dB", min_d=0.5) -> list[list[float]]:
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(wav), "-af", f"silencedetect=n={noise}:d={min_d}",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return [[max(0.0, a), b] for a, b in zip(starts, ends)]


def transcribe(wav) -> list[dict]:
    from studio.modules.transcript.whisper import Engine
    out = []
    Engine().transcribe(wav, "fr", lambda s: None,
                        lambda seg, d: out.append({"s": round(seg.start, 2), "e": round(seg.end, 2), "t": seg.text}),
                        lambda: None)
    return out


def main() -> None:
    pid = sys.argv[1]
    tl, work = timeline(pid), work_dir(pid)
    wav = work / "aroll.wav"
    mix_aroll(pid, tl, wav)
    sil = silences(wav)
    (work / "silences.json").write_text(json.dumps(sil), encoding="utf-8")
    print(f"timeline {total(tl):.2f} s · voice {lufs(wav):.1f} LUFS")
    print("pauses >= 0.9 s:", [(round(a, 1), round(b - a, 2)) for a, b in sil if b - a >= 0.9])
    print("inserted clips (no music under them):")
    for c in inserted_clips(tl):
        print(f"  {c['start']:8.2f} -> {c['end']:8.2f}  {c['src']}")
    print("part titles (short motions):")
    for m in tl["motion"]:
        if m["kind"] == "transition" or m["dur"] <= 1.5:
            print(f"  {m['at']:8.2f}  {m['title'][:70]}")
    if "--no-stt" in sys.argv:
        return
    lines = transcribe(wav)
    (work / "stt.json").write_text(json.dumps(lines, ensure_ascii=False, indent=0), encoding="utf-8")
    for l in lines:
        print(f"{l['s']:7.1f}-{l['e']:6.1f} {l['t']}")


if __name__ == "__main__":
    main()
