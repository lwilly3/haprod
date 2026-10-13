"""
Transcribe new takes with ElevenLabs Scribe (word timings), in parallel.

    python transcribe.py <pid> <file> [<file> ...]      # files relative to the project (ressources/x.mp4)

Writes <work>/<stem>_raw.json and <stem>.txt (one line per phrase, times in the file) and prints the text.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from common import DATA, project_dir, work_dir

URL = "https://api.elevenlabs.io/v1/speech-to-text"


def run(pid: str, rel: str, key: str) -> Path:
    src = project_dir(pid) / rel
    out = work_dir(pid)
    mp3 = out / f"{src.stem}.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-b:a", "96k", str(mp3)], check=True)
    with mp3.open("rb") as f:
        r = httpx.post(URL, headers={"xi-api-key": key}, timeout=900,
                       data={"model_id": "scribe_v2", "timestamps_granularity": "word", "tag_audio_events": "false",
                             "diarize": "false", "language_code": "fr"},
                       files={"file": (mp3.name, f, "audio/mpeg")})
    r.raise_for_status()
    mp3.unlink(missing_ok=True)
    raw = r.json()
    (out / f"{src.stem}_raw.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    words = [w for w in raw["words"] if w["type"] == "word"]
    lines, line = [], []
    for w in words:
        if line and (w["start"] - line[-1]["end"] > 0.5 or line[-1]["text"][-1:] in ".?!"):
            lines.append(line)
            line = []
        line.append(w)
    if line:
        lines.append(line)
    text = "\n".join(f"{l[0]['start']:.2f}-{l[-1]['end']:.2f} {' '.join(x['text'] for x in l)}" for l in lines)
    (out / f"{src.stem}.txt").write_text(text, encoding="utf-8")
    return out / f"{src.stem}.txt"


if __name__ == "__main__":
    pid, files = sys.argv[1], sys.argv[2:]
    key = json.loads((DATA / "transcription.json").read_text(encoding="utf-8"))["keys"]["elevenlabs"]
    with ThreadPoolExecutor(len(files)) as ex:
        for txt in ex.map(lambda f: run(pid, f, key), files):
            print(f"===== {txt}")
            print(txt.read_text(encoding="utf-8"))
