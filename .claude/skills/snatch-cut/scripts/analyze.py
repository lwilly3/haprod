"""Analyze a video sequence to prepare a snatch cut.

Writes to OUT_DIR:
  - overview_NN.png   contact sheets at 5 fps (timecode + source frame number)
  - dense_NN.png      frame-by-frame sheets (or 1 in --step) over --dense start:end (seconds)
  - cuts.txt          detected cuts (seconds and frame)
  - frames.tsv        per frame: difference from the previous one, luminance (motion / light-on cues)
  - audio.tsv         per frame: level in dB, spectral centroid; onsets in the header
  - spectrum.png      spectrogram of the whole duration
  - transcript.txt    word-level transcript (normalized audio, Whisper on CPU) unless --no-transcribe

Usage:
  .venv/Scripts/python -I analyze.py VIDEO OUT_DIR [--dense 0:6.2] [--step 2] [--no-transcribe]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

FONT = Path("C:/Windows/Fonts/arial.ttf")


def ff(*args, capture=False):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-y", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode and not capture:
        sys.exit(r.stderr[-2000:])
    return r.stderr


def probe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=r_frame_rate,width,height,nb_frames:format=duration", "-of", "json", str(video)],
                       capture_output=True, text=True)
    j = json.loads(r.stdout)
    num, den = j["streams"][0]["r_frame_rate"].split("/")
    return float(num) / float(den), float(j["format"]["duration"])


def sheets(video, out, prefix, vf_select, label, cols=6, rows=5):
    # drawtext needs a font path without ':' -> local copy
    shutil.copy(FONT, out / "font.ttf")
    vf = (f"{vf_select},scale=384:-1,drawtext=fontfile=font.ttf:text='{label}':x=5:y=5:fontsize=20:"
          f"fontcolor=yellow:box=1:boxcolor=black,tile={cols}x{rows}")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video.resolve()), "-vf", vf,
                    "-fps_mode", "passthrough", f"{prefix}_%02d.png"], cwd=out, check=True)


def frame_stats(video, fps):
    W, H = 192, 108
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-vf", f"scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    diff = np.concatenate([[0], np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))])
    return diff, f.mean(axis=(1, 2))


def audio_stats(video, fps):
    sr = 22050
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    hop = int(round(sr / fps))
    n = len(x) // hop
    blocks = x[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((blocks ** 2).mean(1)) + 1e-9)
    spec = np.abs(np.fft.rfft(blocks * np.hanning(hop), axis=1))
    cent = (spec * np.fft.rfftfreq(hop, 1 / sr)).sum(1) / (spec.sum(1) + 1e-9)
    # onsets: spectral flux over 1024-sample windows, hop 256
    N, h = 1024, 256
    win = np.lib.stride_tricks.sliding_window_view(x, N)[::h] * np.hanning(N)
    S = np.log1p(np.abs(np.fft.rfft(win, axis=1)) * 10)
    flux = np.maximum(0, np.diff(S, axis=0)).sum(1)
    thr = np.median(flux) + 2.5 * flux.std()
    onsets = [round((i + 1) * h / sr, 2) for i in range(1, len(flux) - 1)
              if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]]
    return db, cent, onsets


def transcribe(video, out):
    wav = out / "voice.wav"
    # voices are often very quiet: normalize first, otherwise Whisper hallucinates
    ff("-i", str(video), "-ac", "1", "-ar", "16000", "-af", "highpass=f=80,dynaudnorm=f=150:g=15:m=30", str(wav))
    from faster_whisper import WhisperModel  # CPU: the cuBLAS DLL is not always available
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(wav), language="fr", word_timestamps=True)
    lines = []
    for s in segs:
        lines.append(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text.strip()}")
        lines.append("    " + " ".join(f"{w.word.strip()}@{w.start:.2f}" for w in s.words))
    (out / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    wav.unlink()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--dense", help="start:end in seconds for the frame-by-frame sheets")
    ap.add_argument("--step", type=int, default=1, help="keep 1 frame in N in the dense sheets")
    ap.add_argument("--scene", type=float, default=0.12, help="cut detection threshold")
    ap.add_argument("--no-transcribe", action="store_true")
    a = ap.parse_args()
    video, out = Path(a.video).resolve(), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fps, dur = probe(video)
    print(f"{video.name}: {dur:.2f}s, {fps:g} fps")

    sheets(video, out, "overview", "fps=5", f"%{{pts\\:hms}} f%{{eif\\:t*{fps:g}\\:d}}")
    if a.dense:
        t0, t1 = (float(v) for v in a.dense.split(":"))
        f0, f1 = int(t0 * fps), int(t1 * fps)
        sheets(video, out, "dense", f"select='between(n\\,{f0}\\,{f1})*not(mod(n\\,{a.step}))'",
               f"f%{{eif\\:t*{fps:g}\\:d}}")

    log = ff("-i", str(video), "-vf", f"select='gt(scene,{a.scene})',showinfo", "-f", "null", "-", capture=True)
    cuts = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", log)]
    (out / "cuts.txt").write_text("\n".join(f"{t:.3f}s f{round(t * fps)}" for t in cuts), encoding="utf-8")

    diff, lum = frame_stats(video, fps)
    with open(out / "frames.tsv", "w", encoding="utf-8") as f:
        f.write("frame\ttime\tdiff\tlum\n")
        for i, (d, l) in enumerate(zip(diff, lum)):
            f.write(f"{i}\t{i / fps:.3f}\t{d:.1f}\t{l:.1f}\n")

    db, cent, onsets = audio_stats(video, fps)
    with open(out / "audio.tsv", "w", encoding="utf-8") as f:
        f.write(f"# onsets (s): {onsets}\nframe\ttime\tdb\tcentroid_hz\n")
        for i, (d, c) in enumerate(zip(db, cent)):
            f.write(f"{i}\t{i / fps:.3f}\t{d:.1f}\t{c:.0f}\n")
    ff("-i", str(video), "-lavfi", "showspectrumpic=s=1600x400:legend=1:stop=8000", str(out / "spectrum.png"))

    print(f"cuts: {[round(c, 2) for c in cuts]}")
    print(f"onsets: {onsets}")
    if not a.no_transcribe:
        transcribe(video, out)
        print((out / "transcript.txt").read_text(encoding="utf-8"))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
