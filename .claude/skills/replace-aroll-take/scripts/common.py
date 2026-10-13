"""Shared helpers: repo paths, backend imports, the source transcript, A-roll geometry."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"
sys.path.insert(0, str(REPO / "backend"))


def project_dir(pid: str) -> Path:
    return DATA / "projects" / pid


def work_dir(pid: str) -> Path:
    """Scratch space for transcripts and configs (outside the repo and outside data/)."""
    d = Path(tempfile.gettempdir()) / "replace-aroll-take" / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def timeline(pid: str) -> dict:
    return json.loads((project_dir(pid) / "montage" / "timeline.json").read_text(encoding="utf-8"))


def clip_starts(tl: dict) -> list[float]:
    out, t = [], 0.0
    for c in tl["aroll"]:
        out.append(round(t, 3))
        t += c["out"] - c["in"]
    return out


def source_segments(pid: str) -> list[dict]:
    """Phrases (with word timings) of the main source video, from its transcription job."""
    project = json.loads((project_dir(pid) / "project.json").read_text(encoding="utf-8"))
    job = (project.get("source") or {}).get("transcript")
    if not job:
        return []
    db = sqlite3.connect(DATA / "studio.db")
    row = db.execute("select state from jobs where id = ?", (job,)).fetchone()
    return json.loads(row[0]).get("segments", []) if row else []


def source_words_on_timeline(pid: str, tl: dict, a: float, b: float) -> list[tuple[float, str]]:
    """Words of the main source as they sit on the timeline between a and b (clips with a `src` have none)."""
    words = [(w[0], w[2].strip()) for s in source_segments(pid) for w in s["words"]]
    out = []
    for c, start in zip(tl["aroll"], clip_starts(tl)):
        end = start + c["out"] - c["in"]
        if c.get("src") or end <= a or start >= b:
            continue
        out += [(round(start + t - c["in"], 2), w) for t, w in words if c["in"] <= t < c["out"]]
    return sorted(x for x in out if a - 3 <= x[0] < b + 3)
