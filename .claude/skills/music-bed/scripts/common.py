"""Shared helpers: repo paths, backend imports, scratch dir, studio API, ffmpeg measurements."""
import json
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"
sys.path.insert(0, str(REPO / "backend"))

API = "https://localhost:4400/api"
SR = 48000


def project_dir(pid: str) -> Path:
    return DATA / "projects" / pid


def work_dir(pid: str) -> Path:
    """Scratch space (voice mix, transcripts, Epidemic downloads, configs): outside the repo and data/."""
    d = Path(tempfile.gettempdir()) / "music-bed" / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def timeline(pid: str) -> dict:
    return json.loads((project_dir(pid) / "montage" / "timeline.json").read_text(encoding="utf-8"))


def total(tl: dict) -> float:
    return sum(c["out"] - c["in"] for c in tl["aroll"])


def inserted_clips(tl: dict) -> list[dict]:
    """A-roll clips from outside media (archives, TV, memes): they play with their own sound, no music under
    them. Clips from ressources/ are the user's own re-recorded takes: they get music like the source."""
    out, t = [], 0.0
    for c in tl["aroll"]:
        d = c["out"] - c["in"]
        if (c.get("src") or "").startswith(("assets/", "library/")):
            out.append({"id": c["id"], "src": c["src"], "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def pause_clips(tl: dict) -> list[dict]:
    """A-roll pauses: the voice stops (black, silence) under a full-screen motion (`pause` = its id), usually a
    part title. Not an inserted clip: each one gets its own short musical cue."""
    out, t = [], 0.0
    titles = {m["id"]: m["title"] for m in tl["motion"]}
    for c in tl["aroll"]:
        d = c["out"] - c["in"]
        if c.get("pause"):
            out.append({"id": c["id"], "motion": c["pause"], "title": titles.get(c["pause"], ""),
                        "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def _ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # local dev certificate
    return ctx


def api_get(path: str) -> dict:
    with urllib.request.urlopen(API + path, context=_ctx()) as r:
        return json.loads(r.read().decode("utf-8"))


def api_put(path: str, body: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method="PUT",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, context=_ctx()) as r:
        return json.loads(r.read().decode("utf-8"))


def lufs(path: Path | str, gain_db: float = 0.0) -> float:
    """Integrated loudness of a file (after an optional gain)."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", f"volume={gain_db}dB,ebur128",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])


def short_term(path: Path | str) -> list[tuple[float, float]]:
    """(time, short-term LUFS) every 0.1 s."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", "ebur128=metadata=1,"
                        "ametadata=print:key=lavfi.r128.S", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out, t = [], 0.0
    for line in r.stderr.splitlines():
        if "pts_time:" in line:
            t = float(line.split("pts_time:")[1].split()[0])
        elif "lavfi.r128.S=" in line:
            out.append((t, float(line.split("=")[1])))
    return out


def read_pcm(path: Path | str):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def write_wav(path: Path | str, pcm) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", str(path)], input=pcm.astype("float32").tobytes(), check=True)
