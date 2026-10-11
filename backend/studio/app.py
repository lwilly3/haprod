"""
API du studio : chaque module monte ses routes sous /api/<module>.

Elle ne fait aucun calcul lourd (c'est le role du worker) : elle peut donc
redemarrer a chaque modification du code sans rien perdre.
"""
import importlib
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import WEB_DIST
from .core import jobs
from .modules import MODULES

# au-dela, on considere que le worker ne tourne plus
WORKER_TIMEOUT = 6.0

jobs.init()
app = FastAPI(title="Studio")

for name in MODULES:
    router = importlib.import_module(f"studio.modules.{name}.api").router
    app.include_router(router, prefix=f"/api/{name}", tags=[name])


@app.get("/api/status")
def status():
    worker = jobs.get_meta("worker")
    alive = bool(worker) and time.time() - worker["at"] < WORKER_TIMEOUT
    return {"modules": MODULES, "worker": {"alive": alive, **(worker or {})}}


class SPAFiles(StaticFiles):
    """Les routes de l'interface (/transcript, /youtube...) renvoient toutes index.html."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)


# en dev c'est Vite qui sert l'interface ; ici seulement le build (mode "start")
if WEB_DIST.is_dir():
    app.mount("/", SPAFiles(directory=WEB_DIST, html=True), name="web")
