"""
Transcription cote worker : ffmpeg -> Whisper (ou l'API choisie dans les reglages), segments
pousses en base au fil de l'eau.
"""
import tempfile
from pathlib import Path

from ...core import jobs
from ...core.tasks import Task, TaskContext
from ..settings import service as settings
from . import cues, service
from .cloud import CloudEngine
from .whisper import Engine

ENGINE_META = "transcript.engine"

_engine: Engine | None = None


def startup() -> None:
    global _engine
    _engine = Engine()
    jobs.set_meta(ENGINE_META, _engine.describe())


def _pick_engine() -> Engine | CloudEngine:
    """Relu a chaque job : changer de moteur dans les reglages ne demande pas de relancer le worker."""
    name, key = settings.transcription_engine()
    return CloudEngine(name, key) if key else _engine


def transcribe(ctx: TaskContext) -> None:
    job, state = ctx.job, ctx.state
    engine = _pick_engine()
    srcs = service.sources(job)
    sequence = len(srcs) > 1
    # un job relance apres un arret du worker repart de zero ; le moteur est garde pour savoir
    # plus tard quels transcripts refaire (Whisper lisse les faux departs, ElevenLabs les garde)
    state.update(segments=[], parts=[], outputs=[], extracted=0, engine=engine.describe()["model"])

    ctx.set_status("extracting")
    with tempfile.TemporaryDirectory() as tmp:
        part_wavs = []
        for i, source in enumerate(srcs):
            part_wav = Path(tmp) / f"part{i}.wav"
            # en sequence, chaque morceau doit durer exactement autant que le clip
            duration = cues.probe_duration(source) if sequence else None
            cues.extract_audio(source, part_wav, duration)
            part_wavs.append(part_wav)
            state["extracted"] = i + 1
            ctx.save(force=True)
            ctx.check_cancel()

        wav = Path(tmp) / "audio.wav"
        durations = cues.concat_wavs(part_wavs, wav)
        for part_wav in part_wavs:
            part_wav.unlink()
        start = 0.0
        for source, duration in zip(srcs, durations):
            state["parts"].append({"name": source.name, "start": start, "duration": duration})
            start += duration
        state["duration"] = start
        ctx.save(force=True)

        segments: list[cues.Segment] = []

        def on_status(status: str):
            if status == "reset":
                segments.clear()
                state["segments"] = []
                ctx.progress = 0.0
                ctx.save(force=True)
            else:
                ctx.set_status(status)
                jobs.set_meta(ENGINE_META, engine.describe())

        def on_segment(seg: cues.Segment, total: float):
            segments.append(seg)
            state["segments"].append(seg.to_json())
            if total:
                ctx.progress = min(seg.end / total, 1.0)
            ctx.save()

        state["detected_language"] = engine.transcribe(
            wav, job.payload["language"], on_status, on_segment, ctx.check_cancel)

    state["outputs"] = service.write_outputs(job, segments, state["level"])


TASKS = {service.KIND: Task(queue="gpu", run=transcribe)}
