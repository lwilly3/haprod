"""
Process qui execute les jobs : c'est lui qui garde les modeles (Whisper...) en
memoire, pour que l'API puisse redemarrer a chaque modification sans les recharger.
"""
import importlib
import os
import threading
import time
import traceback
from collections import defaultdict

from ..modules import MODULES
from . import jobs
from .system import kill_children_on_exit
from .tasks import Cancelled, Task, TaskContext

IDLE_POLL = 0.5
HEARTBEAT_EVERY = 2.0


def _load_tasks() -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    for name in MODULES:
        module = importlib.import_module(f"studio.modules.{name}.tasks")
        if hasattr(module, "startup"):
            module.startup()
        tasks.update(module.TASKS)
    return tasks


def _log(message: str) -> None:
    """Une ligne de log, à l'heure : pour savoir quand un job a démarré, fini ou planté."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def _execute(job: jobs.Job, task: Task, queue: str) -> None:
    ctx = TaskContext(job)
    start = time.time()
    end = lambda status: _log(f"[{queue}] {job.kind} {job.id} : {status} en {time.time() - start:.0f} s")
    try:
        task.run(ctx)
    except Cancelled:
        ctx.save(force=True)
        jobs.update(job.id, status="cancelled", finished_at=time.time())
        end("annulé")
    except Exception as e:  # noqa: BLE001  l'erreur est affichee dans l'UI
        end("erreur")
        traceback.print_exc()
        ctx.save(force=True)
        jobs.update(job.id, status="error", error=str(e), finished_at=time.time())
    else:
        ctx.progress = 1.0
        ctx.save(force=True)
        jobs.update(job.id, status="done", finished_at=time.time())
        end("terminé")


def _consume(queue: str, tasks: dict[str, Task]) -> None:
    kinds = list(tasks)
    while True:
        try:
            job = jobs.claim(kinds)
        except Exception:  # noqa: BLE001  base verrouillee un instant : on reessaie
            traceback.print_exc()
            job = None
        if job is None:
            time.sleep(IDLE_POLL)
            continue
        _log(f"[{queue}] {job.kind} {job.id}")
        _execute(job, tasks[job.kind], queue)


def _heartbeat(queues: list[str]) -> None:
    while True:
        try:
            jobs.set_meta("worker", {"pid": os.getpid(), "at": time.time(), "queues": queues})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(HEARTBEAT_EVERY)


def main() -> None:
    kill_children_on_exit()
    jobs.init()
    requeued = jobs.requeue_interrupted()
    if requeued:
        _log(f"{requeued} job(s) interrompu(s) remis en file.")
    by_queue: dict[str, dict[str, Task]] = defaultdict(dict)
    for kind, task in _load_tasks().items():
        by_queue[task.queue][kind] = task
    for queue, tasks in by_queue.items():
        threading.Thread(target=_consume, args=(queue, tasks), daemon=True, name=queue).start()
    _log(f"Worker pret · files : {', '.join(by_queue)}")
    _heartbeat(list(by_queue))


if __name__ == "__main__":
    main()
