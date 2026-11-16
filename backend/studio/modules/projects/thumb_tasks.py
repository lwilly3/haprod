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

from ...core import claude, codex, fal
from ...core.system import tool
from ...core.tasks import TaskContext
from ..settings.service import claude_model
from . import asset_tasks, thumbs

# assez pour garder un visage net, assez peu pour une requête légère
REF_MAX_SIDE = 1536
# ce que rendent les générateurs par abonnement (ChatGPT, composition de Claude) : du 16:9 plein cadre
SIZE = (1920, 1080)
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


def _reduced(path: Path, dest: Path) -> Path:
    """La référence réduite à REF_MAX_SIDE, en JPEG, sous un nom simple (image1.jpg…) dans le dossier de travail."""
    scale = f"scale='min({REF_MAX_SIDE},iw)':'min({REF_MAX_SIDE},ih)':force_original_aspect_ratio=decrease"
    proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(path), "-vf", scale, "-frames:v", "1",
                           "-q:v", "3", str(dest)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"image illisible : {path.name}")
    return dest


def _to_frame(source: Path, dest: Path) -> None:
    """Remplit exactement le 16:9 de la vignette (1920×1080) : l'image est agrandie puis recadrée au centre."""
    w, h = SIZE
    proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(source), "-frames:v", "1", "-vf",
                           f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", str(dest)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("image rendue illisible")


def _by_codex(ctx: TaskContext, work: Path, refs: list[Path], dest: Path) -> None:
    """ChatGPT, par l'abonnement connecté dans Codex : les références sont jointes dans l'ordre du prompt."""
    ctx.state["activity"] = "ChatGPT génère"
    ctx.save(force=True)
    made = codex.generate_image(ctx.payload["prompt"], refs, work, "thumb.png", ctx.check_cancel)
    _to_frame(made, dest)


COMPOSE_SYSTEM = """You design YouTube thumbnails as a single static HTML page. You cannot generate images: you compose \
with the reference image files in the current directory, text, shapes and color.

Write one file, thumb.html, and nothing else:
- the page is exactly 1920x1080 px: html and body with margin 0, width 1920px, height 1080px, overflow hidden
- inline CSS only; no JavaScript, no external resource (no web fonts, no CDN): system fonts such as \
"Arial Black", Impact, "Helvetica Neue", Arial
- use the reference images by relative file name (image1.jpg…), as full-bleed backgrounds or cut-out frames \
(object-fit: cover); look at them first (Read) to place faces and subjects away from the text
- a thumbnail is read at small size: one clear subject, very large text (140px or more), strong contrast \
(outline, shadow or a color band behind the text), at most two typefaces and three colors
- write only the text you are asked to write, spelled exactly; if none is asked, write none
When the file is written, answer with one short sentence."""


def _by_claude(ctx: TaskContext, work: Path, refs: list[Path], dest: Path) -> None:
    """Claude écrit la mise en page (thumb.html) à partir des références, Chrome la photographie."""
    state = ctx.state
    names = ", ".join(r.name for r in refs) or "none"
    prompt = (f"{ctx.payload['prompt']}\n\nThe reference images are the files: {names} "
              f"(image1.jpg is Image 1, and so on). Compose the thumbnail in thumb.html.")
    state["activity"] = "Claude compose"
    ctx.save(force=True)
    for event in claude.stream(prompt, work, COMPOSE_SYSTEM, None, claude_model("heavy"), ctx.check_cancel,
                               tools="Read,Write,Edit,Glob"):
        if event.get("type") == "result":
            claude.record_usage(event, ctx.job.kind)
            if event.get("is_error"):
                raise RuntimeError(event.get("result") or "Claude a renvoyé une erreur")
    page = work / "thumb.html"
    if not page.is_file():
        raise RuntimeError("Claude n'a pas écrit la composition")
    state["activity"] = "photographie la composition"
    ctx.save(force=True)
    shot = work / "shot.png"
    asset_tasks.screenshot(page.as_uri(), shot)
    _to_frame(shot, dest)


def _by_subscription(ctx: TaskContext, kind: str) -> None:
    p, state = ctx.payload, ctx.state
    ctx.set_status("generating")
    out = Path(p["dest"])
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{p['thumb']}-{p['model']}-{uuid.uuid4().hex[:6]}.png"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        refs = [_reduced(Path(r), work / f"image{i}.jpg") for i, r in enumerate(p["refs"], 1)]
        (_by_codex if kind == "codex" else _by_claude)(ctx, work, refs, path)
    state.update(files=[path.name], applied=False, activity=None)


def generate(ctx: TaskContext) -> None:
    p, state = ctx.payload, ctx.state
    kind = thumbs.provider(p["model"])
    if kind != "fal":
        _by_subscription(ctx, kind)
        return
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
