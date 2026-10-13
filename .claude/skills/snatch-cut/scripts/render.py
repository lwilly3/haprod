"""Render a snatch cut preview from a JSON breakdown.

Each shot is rendered on its own with a fixed frame count, then everything is concatenated:
a zoompan inside a single graph with trim never ends (infinite stream).

Usage:
  .venv/Scripts/python -I render.py SPEC.json

Spec ("at" times: seconds, or {"shot": i, "frame": k} relative to the start of shot i in the output):
{
  "source": "path/sequence.mp4",            # source video of the shots
  "output": "path/preview.mp4",
  "fps": 30,
  "tail_black": 15,                           # black frames at the end (0 = none)
  "master_gain_db": 16, "limit": 0.79,        # master gain then limiter (linear, 0.79 ≈ −2 dB)
  "shots": [
    {"in": 64, "out": 82,                     # source frames [in, out)
     "zoom": {"at": 10, "dur": 3, "amount": 0.15, "anchor": [0.5, 0.4]},  # ease-out zoom at frame "at" of the shot
     "keep_audio": true}                      # keep the shot's source audio (micro-fades)
  ],
  "audio": [
    {"file": "source", "in": 6.10, "out": 12.45, "at": {"shot": 4, "frame": -3},
     "gain_db": 10, "filters": "acompressor=threshold=-30dB:ratio=3"},
    {"file": "sfx/switch.wav", "in": 0, "out": 0.5, "at": {"shot": 1, "frame": 10},
     "sync": 0.0, "gain_db": -11},           # sync = position of the attack in the excerpt
    {"file": "source", "in": 15.9, "out": 18.85, "at": {"shot": 7, "frame": 0},
     "filters": "afftdn=nr=25:nf=-55", "boost": {"windows": [[0.15, 0.8], [1.25, 1.7]], "in_db": 22, "out_db": 3}}
  ]
}
"""
import json
import subprocess
import sys
from pathlib import Path


def run(cmd):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *cmd], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-3000:])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    spec_path = Path(sys.argv[1]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base = spec_path.parent
    path = lambda p: str((base / p).resolve()) if p != "source" else str((base / spec["source"]).resolve())
    fps = spec.get("fps", 30)
    out = Path(path(spec["output"]))
    work = out.parent / (out.stem + "_shots")
    work.mkdir(parents=True, exist_ok=True)

    starts, files, cursor = [], [], 0
    for i, s in enumerate(spec["shots"]):
        a, b = s["in"], s["out"]
        vf = f"select='between(n\\,{a}\\,{b - 1})',setpts=N/{fps}/TB"
        z = s.get("zoom")
        if z:
            ax, ay = z.get("anchor", [0.5, 0.5])
            ez = f"1+{z['amount']}*(1-pow(1-clip((in-{z['at']})/{max(z['dur'], 1)}\\,0\\,1)\\,3))"
            # upscale before zoompan, otherwise the crop jumps pixel by pixel
            vf += (f",scale=3840:-1,zoompan=z='{ez}':x='(iw-iw/zoom)*{ax}':y='(ih-ih/zoom)*{ay}'"
                   f":d=1:s=1920x1080:fps={fps}")
        else:
            vf += ",scale=1920:1080"
        vf += ",format=yuv420p,setsar=1"
        fn = work / f"s{i:02d}.mp4"
        run(["-i", path("source"), "-vf", vf, "-frames:v", str(b - a), "-r", str(fps), "-an",
             "-c:v", "libx264", "-crf", "12", "-preset", "fast", str(fn)])
        files.append(fn)
        starts.append(cursor)
        cursor += b - a
    tail = spec.get("tail_black", 0)
    total = (cursor + tail) / fps

    def at(v):
        if isinstance(v, dict):
            return (starts[v["shot"]] + v.get("frame", 0)) / fps
        return float(v)

    clips = []
    for i, s in enumerate(spec["shots"]):
        if s.get("keep_audio"):
            d = (s["out"] - s["in"]) / fps
            clips.append({"file": "source", "in": s["in"] / fps, "out": s["out"] / fps, "at": starts[i] / fps,
                          "filters": f"afade=t=in:d=0.01,afade=t=out:st={d - 0.02:.3f}:d=0.02"})
    clips += spec.get("audio", [])

    inputs = ["-i", path("source")]
    for fn in files:
        inputs += ["-i", str(fn)]
    graph = ["".join(f"[{k + 1}:v]" for k in range(len(files)))
             + f"concat=n={len(files)}:v=1:a=0" + (f",tpad=stop={tail}:color=black" if tail else "") + "[vout]"]
    extra = {}
    for j, c in enumerate(clips):
        if c["file"] == "source":
            idx = 0
        else:
            p = path(c["file"])
            if p not in extra:
                extra[p] = len(files) + 1 + len(extra)
                inputs += ["-i", p]
            idx = extra[p]
        chain = [f"aformat=sample_rates=48000:channel_layouts=stereo",
                 f"atrim={c.get('in', 0)}:{c['out']}", "asetpts=PTS-STARTPTS"]
        if c.get("filters"):
            chain.append(c["filters"])
        if c.get("boost"):
            b = c["boost"]
            cond = "+".join(f"between(t,{w0},{w1})" for w0, w1 in b["windows"])
            chain.append(f"volume=eval=frame:volume='if({cond},{10 ** (b['in_db'] / 20):.3f},"
                         f"{10 ** (b.get('out_db', 0) / 20):.3f})'")
        chain.append(f"volume={c.get('gain_db', 0)}dB")
        ln = c["out"] - c.get("in", 0)
        fo = c.get("fade_out", 0.08 if c["file"] != "source" else 0)
        if fo:
            chain.append(f"afade=t=out:st={max(0, ln - fo):.3f}:d={fo}")
        ms = max(0, round((at(c["at"]) - c.get("sync", 0)) * 1000))
        chain.append(f"adelay={ms}|{ms}")
        graph.append(f"[{idx}:a]" + ",".join(chain) + f"[a{j}]")
    graph.append("".join(f"[a{j}]" for j in range(len(clips)))
                 + f"amix=inputs={len(clips)}:normalize=0:duration=longest,apad,atrim=0:{total:.3f},"
                 + f"volume={spec.get('master_gain_db', 0)}dB,alimiter=limit={spec.get('limit', 0.6)}:attack=2:release=50:level=0[aout]")

    run([*inputs, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total:.3f}", str(out)])
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    loud = [l.strip() for l in r.splitlines() if l.strip().startswith(("I:", "Peak:"))][-2:]
    print(json.dumps({"output": str(out), "duration": round(total, 3),
                      "shot_starts_frames": starts, "loudness": loud}, ensure_ascii=False))


if __name__ == "__main__":
    main()
