"""
Whisper sur la puce Apple (MLX, GPU Metal) : sur un Mac, faster-whisper ne tourne que sur le CPU,
plus lentement que le temps réel avec un gros modèle. Importé uniquement par le worker.

mlx-whisper transcrit un fichier d'un bloc, sans progression ni annulation. On lui donne donc la
voix par paquets d'au plus 30 s (la fenêtre de Whisper), découpés aux silences par le détecteur
de voix de faster-whisper : les blancs ne sont pas transcrits (pas d'hallucinations), l'avancement
remonte à chaque paquet et l'annulation n'attend jamais plus d'un paquet.
"""
import importlib.util
import os
import platform
import re
import sys
import threading
from pathlib import Path
from typing import Callable

from .cues import Segment, Word

MODEL_NAME = os.environ.get("TRANSCRIPT_MODEL", "large-v3-turbo")
SAMPLE_RATE = 16000
# la fenêtre de Whisper : un paquet plus long serait redécoupé par le modèle, au milieu d'un mot
WINDOW = 30.0
# sur du bruit (foule, musique, sono), Whisper invente : sous ce score (le seuil d'échec de Whisper lui-même),
# il a épuisé toutes ses températures sans rien trouver de crédible
LOGPROB_MIN = -1.0
# les crédits de sous-titres appris par cœur, qu'il récite avec aplomb sur un bout de bruit
CREDITS = re.compile(r"sous-titr|amara\.org|subtitles by|thanks for watching|merci d'avoir regardé", re.IGNORECASE)


def available() -> bool:
    return (sys.platform == "darwin" and platform.machine() == "arm64"
            and os.environ.get("TRANSCRIPT_DEVICE", "auto") in ("auto", "mlx")
            and importlib.util.find_spec("mlx_whisper") is not None)


def _repo(name: str) -> str:
    """Les modèles convertis de mlx-community : « whisper-<nom>-mlx », sauf le turbo."""
    if "/" in name:
        return name
    return f"mlx-community/whisper-{name}" if name.endswith("turbo") else f"mlx-community/whisper-{name}-mlx"


def pack(regions: list[tuple[float, float]], window: float = WINDOW) -> list[list[tuple[float, float]]]:
    """Range les passages de voix (début, fin) en paquets d'au plus `window` secondes de voix."""
    packs: list[list[tuple[float, float]]] = []
    length = 0.0
    for start, end in regions:
        if packs and length + (end - start) <= window:
            packs[-1].append((start, end))
            length += end - start
        else:
            packs.append([(start, end)])
            length = end - start
    return packs


def restore(t: float, regions: list[tuple[float, float]], is_end: bool = False) -> float:
    """Un temps mesuré dans le paquet (les passages mis bout à bout) -> le temps dans le fichier.
    Pile sur une jointure, une fin appartient au passage d'avant et un début à celui d'après."""
    offset = 0.0
    for i, (start, end) in enumerate(regions):
        length = end - start
        last = i == len(regions) - 1
        if t < offset + length or (is_end and t == offset + length) or last:
            return start + min(max(t - offset, 0.0), length)
        offset += length
    return t


def invented(segment: dict) -> bool:
    """Un segment que le modèle a inventé plutôt qu'entendu."""
    text = segment["text"].strip()
    return (not text.strip(" .…") or segment.get("avg_logprob", 0.0) < LOGPROB_MIN
            or bool(CREDITS.search(text)))


class MlxEngine:
    def __init__(self):
        self._loaded = False
        self._lock = threading.Lock()
        self.device, self.compute_type = "mlx", "float16"

    def describe(self) -> dict:
        return {"model": MODEL_NAME, "device": "GPU", "compute_type": "MLX", "loaded": self._loaded}

    def transcribe(self, wav: Path, language: str | None,
                   on_status: Callable[[str], None],
                   on_segment: Callable[[Segment, float], None],
                   check_cancel: Callable[[], None]) -> str:
        """Même contrat que whisper.Engine : rend la langue détectée, les segments arrivent par on_segment."""
        import mlx_whisper
        import numpy as np
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        with self._lock:
            on_status("loading")
            audio = decode_audio(str(wav), sampling_rate=SAMPLE_RATE)
            total = len(audio) / SAMPLE_RATE
            # un passage de plus de 30 s serait redécoupé par le modèle lui-même, et le turbo part alors
            # en boucle (« A,A,A,A… ») : le détecteur de voix le recoupe avant, au meilleur micro-silence
            speech = get_speech_timestamps(audio, VadOptions(max_speech_duration_s=WINDOW - 1),
                                           sampling_rate=SAMPLE_RATE)
            packs = pack([(s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in speech])
            check_cancel()
            on_status("transcribing")
            for regions in packs:
                check_cancel()
                chunk = np.concatenate([audio[round(a * SAMPLE_RATE):round(b * SAMPLE_RATE)] for a, b in regions])
                # le premier appel télécharge (une fois) et charge le modèle ; la langue trouvée sur le
                # premier paquet vaut pour la suite : un paquet court ne la ferait pas changer en route
                result = mlx_whisper.transcribe(
                    chunk, path_or_hf_repo=_repo(MODEL_NAME), language=language, word_timestamps=True,
                    # voir whisper.Engine : sinon une phrase redite juste après est souvent avalée
                    condition_on_previous_text=False, verbose=None)
                self._loaded = True
                language = language or result.get("language")
                for s in result["segments"]:
                    text = s["text"].strip()
                    if invented(s):
                        continue
                    words = [Word(restore(float(w["start"]), regions), restore(float(w["end"]), regions, True),
                                  w["word"]) for w in s.get("words") or []]
                    start = words[0].start if words else restore(float(s["start"]), regions)
                    end = words[-1].end if words else restore(float(s["end"]), regions, True)
                    on_segment(Segment(start, max(end, start), text, words), total)
            return language or "en"
