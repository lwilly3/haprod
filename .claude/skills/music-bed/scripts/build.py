"""Build the music cues: cut, level, duck under the voice, fade, and compute each clip's gain.

Usage: build.py <pid> <config.json>
Config (paths relative to the scratch dir unless absolute):
{
  "duck_db": -9,                  # under the voice, relative to the pauses
  "under_voice_lufs": -47,        # target loudness of the music under the voice (voice ≈ -24.6 LUFS)
  "force_open": [[9.0, 13.85]],   # stretches without speech the silence detector misses (TV set noise…)
  "cues": [{
    "file": "dl/cryptic.wav", "name": "musique-01-ouverture-cryptic-secrecy",
    "at": 0.0,                    # timeline start
    "skip": 5.8,                  # seconds skipped at the start of the file (so the audible end lands right)
    "length": 94.2,               # seconds kept
    "fade_in": 0.8, "fade_out": 1.5,
    "level": -18.5,               # optional: short-term LUFS ceiling (flattens a track that swells)
    "dips": [[385.05, 386.65, -18]]  # optional: extra dips in timeline time (a meme inside the section)
  }]
}
Writes data/projects/<pid>/assets/music/<name>.wav and <scratch>/cues.json (ready for apply.py).
The ducking is baked into the files (the studio has no volume automation yet): pauses >= 0.9 s open up,
the music goes back down 0.05 s before the voice resumes.
"""
import json
import sys
from pathlib import Path

import numpy as np

from common import SR, lufs, project_dir, read_pcm, short_term, work_dir, write_wav

MIN_PAUSE = 0.9


def smooth(x):
    x = np.clip(x, 0, 1)
    return 0.5 - 0.5 * np.cos(np.pi * x)


def leveled(path: Path, ceiling: float):
    """Gain curve (only cuts) keeping the 3 s-smoothed short-term loudness under `ceiling`."""
    st = np.array(short_term(path))
    x = read_pcm(path)
    t = np.arange(len(x)) / SR
    grid = np.arange(0, t[-1] + 0.1, 0.1)
    loud = np.interp(grid, st[:, 0], st[:, 1])
    avg = np.convolve(np.pad(loud, 15, mode="edge"), np.ones(30) / 30, mode="same")[15:-15]
    gain = np.minimum(0.0, ceiling - avg)
    return x * (10 ** (np.interp(t, grid, gain) / 20))[:, None]


def main() -> None:
    pid, cfg_path = sys.argv[1], Path(sys.argv[2])
    work = work_dir(pid)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    duck, target = cfg.get("duck_db", -9.0), cfg.get("under_voice_lufs", -47.0)
    sil = json.loads((work / "silences.json").read_text(encoding="utf-8"))
    gaps = [(a, b) for a, b in sil if b - a >= MIN_PAUSE] + [tuple(g) for g in cfg.get("force_open", [])]
    out_dir = project_dir(pid) / "assets" / "music"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for c in cfg["cues"]:
        src = Path(c["file"]) if Path(c["file"]).is_absolute() else work / c["file"]
        x = leveled(src, c["level"]) if c.get("level") is not None else read_pcm(src)
        x = x[int(c.get("skip", 0) * SR):]
        if c.get("length"):
            x = x[:int(c["length"] * SR)]
        n, at = len(x), c["at"]
        t = at + np.arange(n) / SR
        opened = np.zeros(n)
        for a, b in gaps:
            if b < at or a > at + n / SR:
                continue
            opened = np.maximum(opened, smooth(np.minimum((t - (a + 0.1)) / 0.5, ((b - 0.05) - t) / 0.4)))
        db = duck * (1 - opened)
        for a, b, d in c.get("dips", []):
            db = db + d * smooth(np.minimum((t - (a - 0.1)) / 0.1, ((b + 0.1) - t) / 0.3))
        g = 10 ** (db / 20)
        rel = np.arange(n) / SR
        if c.get("fade_in"):
            g *= smooth(rel / c["fade_in"])
        if c.get("fade_out"):
            g *= smooth((n / SR - rel) / c["fade_out"])
        y = x * g[:, None]
        dest = out_dir / f"{c['name']}.wav"
        write_wav(dest, y)
        # the clip gain puts the (leveled, unducked) music at `target` once ducked under the voice
        tmp = work / "_level.wav"
        write_wav(tmp, x)
        gain = round(target - duck - lufs(tmp), 1)
        tmp.unlink()
        result.append({"src": f"assets/music/{dest.name}", "at": at, "in": 0.0, "out": round(n / SR, 3),
                       "gain_db": gain, "role": "music"})
        print(f"{dest.name}: {at:.2f} -> {at + n / SR:.2f} · gain {gain} dB · "
              f"open {100 * float((opened > 0.5).mean()):.1f} %")
    (work / "cues.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("->", work / "cues.json")


if __name__ == "__main__":
    main()
