"""
Modele Whisper (faster-whisper). Importe uniquement par le worker : c'est lui
qui garde le modele en memoire GPU, l'API n'en a jamais besoin.
"""
import glob
import os
import sys
import threading
from pathlib import Path
from typing import Callable

from .cues import Segment, Word

MODEL_NAME = os.environ.get("TRANSCRIPT_MODEL", "large-v3-turbo")


def _expose_cuda_dlls() -> None:
    """Les DLL cuBLAS/cuDNN viennent des wheels nvidia-* : ctranslate2 les cherche dans le PATH."""
    site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    dirs = [os.path.abspath(d) for d in glob.glob(str(site / "*" / "bin"))]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")


_expose_cuda_dlls()

import ctranslate2  # noqa: E402  (apres la mise a jour du PATH)
from faster_whisper import WhisperModel  # noqa: E402


def _pick_device() -> tuple[str, str]:
    wanted = os.environ.get("TRANSCRIPT_DEVICE", "auto")
    if wanted in ("auto", "cuda") and ctranslate2.get_cuda_device_count() > 0:
        supported = ctranslate2.get_supported_compute_types("cuda")
        # une GTX 10xx ne sait pas faire de float16 : int8 est alors le meilleur choix
        for ct in ("float16", "int8_float16", "int8", "float32"):
            if ct in supported:
                return "cuda", ct
    return "cpu", "int8"


class Engine:
    def __init__(self):
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()
        self.device, self.compute_type = _pick_device()

    def describe(self) -> dict:
        label = "GPU" if self.device == "cuda" else "CPU"
        return {"model": MODEL_NAME, "device": label, "compute_type": self.compute_type,
                "loaded": self._model is not None}

    def _load(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(MODEL_NAME, device=self.device,
                                       compute_type=self.compute_type)
        return self._model

    def _fallback_to_cpu(self) -> None:
        print("CUDA indisponible, bascule sur le CPU.", file=sys.stderr)
        self._model = None
        self.device, self.compute_type = "cpu", "int8"

    def transcribe(self, wav: Path, language: str | None,
                   on_status: Callable[[str], None],
                   on_segment: Callable[[Segment, float], None],
                   check_cancel: Callable[[], None]) -> str:
        """Retourne la langue detectee ; les segments arrivent au fil de l'eau via on_segment.

        `check_cancel` leve une exception pour interrompre la transcription.
        """
        with self._lock:
            try:
                return self._run(wav, language, on_status, on_segment, check_cancel)
            except RuntimeError:
                # DLL CUDA manquantes : l'erreur ne sort qu'au premier encodage
                if self.device != "cuda":
                    raise
                self._fallback_to_cpu()
                on_status("reset")
                return self._run(wav, language, on_status, on_segment, check_cancel)

    def _run(self, wav, language, on_status, on_segment, check_cancel) -> str:
        on_status("loading")
        model = self._load()
        on_status("transcribing")
        segments, info = model.transcribe(
            str(wav),
            language=language,
            beam_size=5,
            word_timestamps=True,
            # coupe les silences : evite les hallucinations sur les blancs
            vad_filter=True,
            # sinon une phrase redite juste apres (prise ratee puis bonne prise) est souvent
            # avalee : le modele, conditionne sur le texte precedent, ne la transcrit qu'une fois
            condition_on_previous_text=False,
        )
        for s in segments:
            check_cancel()
            words = [Word(float(w.start), float(w.end), w.word) for w in (s.words or [])]
            on_segment(Segment(float(s.start), float(s.end), s.text.strip(), words),
                       info.duration or 0.0)
        return info.language
