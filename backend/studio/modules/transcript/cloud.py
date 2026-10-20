"""
Transcription par une API (ElevenLabs Scribe, Gladia), au choix dans les reglages a la place de
Whisper. Plus fideles pour le derush : faux departs, phrases redites, hesitations et voix faibles
y sont gardes, la ou Whisper rend un texte nettoye.

Meme interface que whisper.Engine. Les mots sont regroupes en phrases ici (pauses, fins de
phrase), pareil pour les deux services, pour que le derush les traite de la meme facon.
"""
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

import httpx

from ...core.system import tool
from .cues import LINE_MAX_GAP, Segment, Word

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL = "scribe_v2"
GLADIA_URL = "https://api.gladia.io/v2"
LABELS = {"elevenlabs": "ElevenLabs Scribe v2", "gladia": "Gladia Solaria"}
TIMEOUT = 30 * 60
POLL_EVERY = 2.0
# ElevenLabs renvoie des codes ISO 639-3
# connexion perdue (paquets perdus, WinError 10060) : reessayee, rien n'a encore ete envoye
_http = httpx.Client(transport=httpx.HTTPTransport(retries=3))
ISO3 = {"fra": "fr", "eng": "en", "spa": "es", "deu": "de", "ita": "it", "por": "pt"}

Words = list[tuple[float, float, str]]


class CloudEngine:
    def __init__(self, provider: str, key: str):
        self.provider, self.key = provider, key

    def describe(self) -> dict:
        return {"model": LABELS[self.provider], "device": "API", "compute_type": "", "loaded": True}

    def transcribe(self, wav: Path, language: str | None,
                   on_status: Callable[[str], None],
                   on_segment: Callable[[Segment, float], None],
                   check_cancel: Callable[[], None]) -> str:
        on_status("transcribing")
        # envoye compresse : le wav d'une heure fait plus de 100 Mo
        mp3 = wav.with_suffix(".mp3")
        subprocess.run([tool("ffmpeg"), "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-b:a", "96k", str(mp3)],
                       check=True)
        try:
            run = self._elevenlabs if self.provider == "elevenlabs" else self._gladia
            words, detected = run(mp3, language, check_cancel)
        except httpx.TransportError as e:
            # coupure reseau, pare-feu, proxy : le message brut (WinError 10060...) ne dit pas qui
            raise RuntimeError(f"{LABELS[self.provider]} injoignable ({type(e).__name__}) : "
                               "vérifie la connexion, ou repasse sur Whisper dans les réglages") from e
        finally:
            mp3.unlink(missing_ok=True)
        segments = group(words)
        total = segments[-1].end if segments else 0.0
        for seg in segments:
            on_segment(seg, total)
        return detected or language or ""

    def _elevenlabs(self, audio: Path, language: str | None, check_cancel) -> tuple[Words, str | None]:
        data = {"model_id": ELEVENLABS_MODEL, "timestamps_granularity": "word",
                "tag_audio_events": "false", "diarize": "false"}
        if language:
            data["language_code"] = language
        with audio.open("rb") as f:
            r = _http.post(ELEVENLABS_URL, headers={"xi-api-key": self.key}, data=data,
                           files={"file": (audio.name, f, "audio/mpeg")}, timeout=TIMEOUT)
        _raise(r, "ElevenLabs")
        raw = r.json()
        words = [(w["start"], w["end"], w["text"]) for w in raw.get("words") or [] if w.get("type") == "word"]
        code = raw.get("language_code") or ""
        return words, ISO3.get(code, code[:2] or None)

    def _gladia(self, audio: Path, language: str | None, check_cancel) -> tuple[Words, str | None]:
        h = {"x-gladia-key": self.key}
        with audio.open("rb") as f:
            up = _http.post(f"{GLADIA_URL}/upload", headers=h, files={"audio": (audio.name, f, "audio/mpeg")},
                            timeout=TIMEOUT)
        _raise(up, "Gladia")
        body: dict = {"audio_url": up.json()["audio_url"]}
        if language:
            body["language_config"] = {"languages": [language]}
        job = _http.post(f"{GLADIA_URL}/pre-recorded", headers=h, json=body, timeout=60)
        _raise(job, "Gladia")
        url = f"{GLADIA_URL}/pre-recorded/{job.json()['id']}"
        while True:
            check_cancel()
            r = _http.get(url, headers=h, timeout=60)
            _raise(r, "Gladia")
            raw = r.json()
            if raw.get("status") == "done":
                break
            if raw.get("status") == "error":
                raise RuntimeError(f"Gladia : échec de la transcription ({raw.get('error_code')})")
            time.sleep(POLL_EVERY)
        tr = (raw.get("result") or {}).get("transcription") or {}
        words = [(w["start"], w["end"], w["word"]) for u in tr.get("utterances") or [] for w in u.get("words") or []]
        langs = tr.get("languages") or []
        return words, langs[0] if langs else None


def _raise(r: httpx.Response, name: str) -> None:
    if r.status_code in (401, 403):
        raise RuntimeError(f"{name} : clé API refusée (vérifie-la dans les réglages)")
    if r.status_code >= 400:
        raise RuntimeError(f"{name} {r.status_code} : {r.text[:300]}")


def group(words: Words) -> list[Segment]:
    """Phrases à partir des mots : coupure sur une pause, ou après une fin de phrase."""
    out: list[Segment] = []
    cur: list[Word] = []

    def close():
        if cur:
            out.append(Segment(cur[0].start, cur[-1].end, "".join(w.text for w in cur).strip(), cur[:]))
            cur.clear()

    for start, end, text in words:
        text = text.strip()
        if not text:
            continue
        # « Comme si la haine-- » : un faux depart, ecrit comme une phrase en suspens
        if text.endswith("--"):
            text = text[:-2] + "…"
        # ponctuation seule (« ? » horodaté à part) : collée au mot d'avant, sans compter sa pause
        if not re.search(r"\w", text) and cur:
            cur[-1].text += " " + text
            continue
        if cur and (start - cur[-1].end >= LINE_MAX_GAP or cur[-1].text[-1:] in ".?!…"):
            close()
        # le texte des mots garde son espace de tete, comme chez Whisper
        cur.append(Word(float(start), float(end), " " + text))
    close()
    return out
