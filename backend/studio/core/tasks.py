"""
Ce qu'un module declare pour le worker, et ce que le worker passe a chaque tache.
"""
import time
from dataclasses import dataclass
from typing import Callable

from . import jobs


class Cancelled(Exception):
    pass


@dataclass
class Task:
    # les taches d'une meme file passent une par une : "gpu" pour Whisper,
    # "network" pour les telechargements... deux files differentes tournent en parallele
    queue: str
    run: Callable[["TaskContext"], None]


class TaskContext:
    """Vue du job cote worker : l'etat est pousse en base sans la marteler."""

    SAVE_EVERY = 1.0
    CANCEL_CHECK_EVERY = 0.5

    def __init__(self, job: jobs.Job):
        self.job = job
        self.payload = job.payload
        self.state = job.state
        self.progress = 0.0
        self._saved_at = 0.0
        self._cancel_checked_at = 0.0

    def set_status(self, status: str) -> None:
        jobs.update(self.job.id, status=status)

    def save(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._saved_at >= self.SAVE_EVERY:
            jobs.update(self.job.id, state=self.state, progress=round(self.progress, 4))
            self._saved_at = now

    def check_cancel(self) -> None:
        now = time.monotonic()
        if now - self._cancel_checked_at < self.CANCEL_CHECK_EVERY:
            return
        self._cancel_checked_at = now
        if jobs.is_cancel_requested(self.job.id):
            raise Cancelled()
