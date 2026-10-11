"""
File de jobs partagee entre l'API et le worker, persistee en SQLite.

L'API cree les jobs et lit leur avancement ; le worker (un autre process) les
execute et ecrit leur etat. Comme tout passe par la base, l'API peut redemarrer
a chaud sans rien perdre, et un job interrompu est relance au demarrage du worker.

- `payload` : les parametres du job, fixes a la creation
- `state`   : ce que le job produit au fil de l'eau (propre a chaque module)
- `status`  : queued, puis une etape libre choisie par le module
              (extracting, downloading...), puis done | error | cancelled
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import DATA_DIR, DB_PATH

FINISHED = ("done", "error", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (status, kind, created_at);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Job:
    id: str
    module: str
    kind: str
    status: str = "queued"
    progress: float = 0.0
    payload: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    error: str | None = None
    cancel_requested: bool = False
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def finished(self) -> bool:
        return self.status in FINISHED

    @property
    def elapsed(self) -> float | None:
        if not self.started_at:
            return None
        return (self.finished_at or time.time()) - self.started_at

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        data["state"] = json.loads(data["state"])
        data["cancel_requested"] = bool(data["cancel_requested"])
        return cls(**data)


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        # WAL : l'API lit pendant que le worker ecrit
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


def create(module: str, kind: str, payload: dict, state: dict | None = None,
           job_id: str | None = None, status: str = "queued") -> Job:
    """`status` : "done" pour un job cree sans rien a executer (ex. un document importe)."""
    now = time.time()
    job = Job(id=job_id or uuid.uuid4().hex[:10], module=module, kind=kind, status=status,
              payload=payload, state=state or {}, created_at=now,
              finished_at=now if status in FINISHED else None)
    with _db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, module, kind, status, payload, state, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job.id, module, kind, status, json.dumps(payload), json.dumps(job.state), job.created_at,
             job.finished_at))
    return job


def get(job_id: str) -> Job | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def list_jobs(module: str) -> list[Job]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM jobs WHERE module = ? ORDER BY created_at",
                            (module,)).fetchall()
    return [Job.from_row(r) for r in rows]


def update(job_id: str, **fields: Any) -> None:
    """Ne touche qu'aux colonnes passees : l'API et le worker n'ecrivent jamais les memes."""
    if not fields:
        return
    for key in ("payload", "state"):
        if key in fields:
            fields[key] = json.dumps(fields[key])
    if "cancel_requested" in fields:
        fields["cancel_requested"] = int(fields["cancel_requested"])
    columns = ", ".join(f"{k} = ?" for k in fields)
    with _db() as conn:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", (*fields.values(), job_id))


def delete(job_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def cancel(job: Job) -> None:
    """Un job en attente est annule tout de suite ; un job en cours s'arrete a la prochaine etape."""
    with _db() as conn:
        conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job.id,))
        conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? "
                     "WHERE id = ? AND status = 'queued'", (time.time(), job.id))


def is_cancel_requested(job_id: str) -> bool:
    with _db() as conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
    # un job supprime pendant son execution doit s'arreter aussi
    return row is None or bool(row[0])


def claim(kinds: list[str]) -> Job | None:
    """Le worker prend le plus ancien job en attente parmi ces types."""
    marks = ",".join("?" * len(kinds))
    with _db() as conn:
        row = conn.execute(
            f"UPDATE jobs SET status = 'running', started_at = ?, progress = 0, error = NULL "
            f"WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND cancel_requested = 0 "
            f"AND kind IN ({marks}) ORDER BY created_at LIMIT 1) RETURNING *",
            (time.time(), *kinds)).fetchone()
    return Job.from_row(row) if row else None


def requeue_interrupted() -> int:
    """Au demarrage du worker : ce qui tournait quand il s'est arrete repart de zero."""
    with _db() as conn:
        return conn.execute(
            "UPDATE jobs SET status = 'queued', progress = 0, started_at = NULL "
            "WHERE status NOT IN ('queued', 'done', 'error', 'cancelled')").rowcount


# --- meta : petites infos partagees (etat du worker, device GPU...) ----------

def set_meta(key: str, value: Any) -> None:
    with _db() as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                     (key, json.dumps(value)))


def get_meta(key: str, default: Any = None) -> Any:
    with _db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default
