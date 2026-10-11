"""
Compare des moteurs de transcription sur un extrait de rush : Whisper local (celui du studio),
Voxtral (API Mistral), Gladia (Solaria) et ElevenLabs (Scribe v2).

  uv run python scripts/compare_stt.py <video> [--from 210] [--to 330] [--only gladia,elevenlabs]

Clés lues dans l'environnement (ou le registre Windows, comme FAL_KEY) :
MISTRAL_API_KEY, GLADIA_API_KEY, ELEVENLABS_API_KEY.

Sortie dans data/stt-compare/<horodatage>/ : par moteur, la réponse brute (.json), les phrases
(.txt) et les mots (.words.txt), avec les temps en secondes du rush.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from studio.config import DATA_DIR  # noqa: E402
from studio.core.system import tool  # noqa: E402

LANG = "fr"
# au-delà de cette pause entre deux mots, on commence une nouvelle phrase (moteurs sans segments)
GAP = 0.7


def key(name: str) -> str:
    found = os.environ.get(name)
    if not found and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                found = winreg.QueryValueEx(reg, name)[0]
        except OSError:
            pass
    if not found:
        raise RuntimeError(f"clé absente : {name}")
    return found


def extract(video: Path, start: float, end: float | None, out: Path) -> None:
    cmd = [tool("ffmpeg"), "-v", "error", "-y", "-ss", str(start), "-i", str(video)]
    if end is not None:
        cmd += ["-t", str(end - start)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", str(out)]
    subprocess.run(cmd, check=True)


# --- moteurs : chacun renvoie (réponse brute, mots [(début, fin, texte)], phrases [(début, fin, texte)])

def run_whisper(wav: Path):
    from studio.modules.transcript.whisper import Engine
    segs = []
    Engine().transcribe(wav, LANG, lambda s: None, lambda s, d: segs.append(s), lambda: None)
    words = [(w.start, w.end, w.text.strip()) for s in segs for w in s.words]
    return [s.to_json() for s in segs], words, [(s.start, s.end, s.text) for s in segs]


def run_voxtral(wav: Path):
    with wav.open("rb") as f:
        r = httpx.post("https://api.mistral.ai/v1/audio/transcriptions",
                       headers={"Authorization": f"Bearer {key('MISTRAL_API_KEY')}"},
                       data={"model": "voxtral-mini-latest", "timestamp_granularities": "word"},
                       files={"file": (wav.name, f, "audio/wav")}, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"Mistral {r.status_code} : {r.text}")
    raw = r.json()
    # avec timestamp_granularities=word, les « segments » renvoyés sont les mots
    words = [(w["start"], w["end"], w["text"].strip()) for w in raw.get("segments") or []]
    return raw, words, group(words)


def run_gladia(wav: Path):
    h = {"x-gladia-key": key("GLADIA_API_KEY")}
    with wav.open("rb") as f:
        up = httpx.post("https://api.gladia.io/v2/upload", headers=h,
                        files={"audio": (wav.name, f, "audio/wav")}, timeout=600)
    if up.status_code >= 400:
        raise RuntimeError(f"Gladia upload {up.status_code} : {up.text}")
    job = httpx.post("https://api.gladia.io/v2/pre-recorded", headers=h, timeout=60,
                     json={"audio_url": up.json()["audio_url"], "language_config": {"languages": [LANG]}})
    if job.status_code >= 400:
        raise RuntimeError(f"Gladia {job.status_code} : {job.text}")
    url = f"https://api.gladia.io/v2/pre-recorded/{job.json()['id']}"
    while True:
        raw = httpx.get(url, headers=h, timeout=60).json()
        if raw.get("status") == "done":
            break
        if raw.get("status") == "error":
            raise RuntimeError(f"Gladia : {json.dumps(raw)[:500]}")
        time.sleep(2)
    utts = (raw.get("result") or {}).get("transcription", {}).get("utterances") or []
    words = [(w["start"], w["end"], w["word"].strip()) for u in utts for w in u.get("words") or []]
    return raw, words, [(u["start"], u["end"], u["text"].strip()) for u in utts]


def run_elevenlabs(wav: Path):
    with wav.open("rb") as f:
        r = httpx.post("https://api.elevenlabs.io/v1/speech-to-text",
                       headers={"xi-api-key": key("ELEVENLABS_API_KEY")},
                       data={"model_id": "scribe_v2", "language_code": LANG, "timestamps_granularity": "word",
                             "tag_audio_events": "true", "diarize": "false"},
                       files={"file": (wav.name, f, "audio/wav")}, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code} : {r.text}")
    raw = r.json()
    words = [(w["start"], w["end"], w["text"].strip()) for w in raw.get("words") or []
             if w.get("type") != "spacing"]
    return raw, words, group(words)


def group(words):
    """Phrases à partir des mots seuls : coupure sur une pause, ou après une fin de phrase."""
    out, cur = [], []
    for w in words:
        if cur and (w[0] - cur[-1][1] >= GAP or cur[-1][2][-1:] in ".?!"):
            out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    return out


ENGINES = {"whisper": run_whisper, "voxtral": run_voxtral, "gladia": run_gladia, "elevenlabs": run_elevenlabs}


def ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--to", dest="end", type=float)
    ap.add_argument("--only", default=",".join(ENGINES))
    a = ap.parse_args()

    out_dir = DATA_DIR / "stt-compare" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "extrait.wav"
        extract(a.video, a.start, a.end, wav)
        for name in a.only.split(","):
            print(f"{name}…", flush=True)
            t0 = time.time()
            try:
                raw, words, segs = ENGINES[name](wav)
            except Exception as e:  # un moteur en échec n'empêche pas les autres
                print(f"  échec : {e}")
                (out_dir / f"{name}.error.txt").write_text(str(e), encoding="utf-8")
                continue
            o = a.start
            (out_dir / f"{name}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            (out_dir / f"{name}.txt").write_text(
                "".join(f"[{ts(s + o)} → {ts(e + o)}] {t}\n" for s, e, t in segs), encoding="utf-8")
            (out_dir / f"{name}.words.txt").write_text(
                "".join(f"{ts(s + o)} {ts(e + o)}  {t}\n" for s, e, t in words), encoding="utf-8")
            print(f"  {len(segs)} phrases, {len(words)} mots, {time.time() - t0:.0f} s")
    print(f"résultats : {out_dir}")


if __name__ == "__main__":
    main()
