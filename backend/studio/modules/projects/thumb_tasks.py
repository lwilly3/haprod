"""
Côté worker, l'étape Vignette : une génération par fal.ai. Les images de référence sont
réduites (ffmpeg) puis envoyées en data URI ; les images produites sont téléchargées dans
vignettes/. Comme les autres tâches, n'écrit pas project.json : la liste des fichiers reste
dans l'état du job, l'API l'ajoute à la variante (thumbs.sync).
"""
import base64
import subprocess
import tempfile
import uuid
from pathlib import Path

from ...core import fal
from ...core.system import tool
from ...core.tasks import TaskContext

# assez pour garder un visage net, assez peu pour une requête légère
REF_MAX_SIDE = 1536
STATUS = {"IN_QUEUE": "en file chez fal.ai", "IN_PROGRESS": "génère"}


def _data_uri(path: Path, tmp: Path) -> str:
    """L'image réduite à REF_MAX_SIDE (sans l'agrandir), en JPEG."""
    out = tmp / f"{uuid.uuid4().hex[:8]}.jpg"
    scale = f"scale='min({REF_MAX_SIDE},iw)':'min({REF_MAX_SIDE},ih)':force_original_aspect_ratio=decrease"
    proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(path), "-vf", scale, "-frames:v", "1",
                           "-q:v", "3", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"image illisible : {path.name}")
    return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()


def generate(ctx: TaskContext) -> None:
    p, state = ctx.payload, ctx.state
    ctx.set_status("preparing")
    state["activity"] = "prépare les références"
    ctx.save(force=True)
    with tempfile.TemporaryDirectory() as tmp:
        refs = [_data_uri(Path(r), Path(tmp)) for r in p["refs"]]

    def on_status(status: str) -> None:
        state["activity"] = STATUS.get(status, status.lower())
        ctx.save(force=True)

    ctx.set_status("generating")
    result = fal.run(p["endpoint"], {**p["args"], "prompt": p["prompt"], "image_urls": refs}, ctx.check_cancel, on_status)
    images = result.get("images") or []
    if not images:
        raise RuntimeError("fal.ai n'a renvoyé aucune image")
    state["activity"] = "télécharge"
    ctx.save(force=True)
    dest = Path(p["dest"])
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for img in images:
        ext = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(img.get("content_type"), ".png")
        path = dest / f"{p['thumb']}-{p['model']}-{uuid.uuid4().hex[:6]}{ext}"
        path.write_bytes(fal.download(img["url"]))
        files.append(path.name)
    state.update(files=files, applied=False, activity=None)
