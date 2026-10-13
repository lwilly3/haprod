"""
L'étape Vignette côté API : les compositions proposées par Claude, la génération d'images par fal.ai.

Chaque variante (project.thumbs, éditée par l'interface) est associée à l'un des titres, et a sa
description, le texte que le modèle écrit dans l'image (vide : aucun), ses portraits et ses
vignettes de style, choisis dans la bibliothèque (toutes catégories) ou les médias du projet.
Une génération lance un job par modèle (`<pid>-thumb-<variante>-<modèle>`), les modèles tournent en parallèle ; une retouche
(`start_edit`) fait de même en partant d'une image de la galerie et d'une consigne. Les images produites
vont dans vignettes/ ; leur liste, project.thumb_images (variante -> images), n'est écrite que
par l'API (`sync`, `remove_image`) : l'interface, qui renvoie project.thumbs en entier, ne peut
pas l'écraser.
"""
from pathlib import Path

from ...core import fal, jobs
from . import library, service

# l'endpoint d'édition (images de référence) de chaque modèle, et ses réglages pour du 16:9
MODELS = {
    "nano-banana-pro": {"label": "Nano Banana Pro", "endpoint": "fal-ai/nano-banana-pro/edit",
                        "args": {"aspect_ratio": "16:9", "resolution": "2K", "output_format": "png"}},
    "seedream-5-pro": {"label": "Seedream 5 Pro", "endpoint": "bytedance/seedream/v5/pro/edit",
                       "args": {"image_size": {"width": 1920, "height": 1080}, "output_format": "png"}},
    "gpt-image-2.5": {"label": "GPT Image 2.5", "endpoint": "openai/gpt-image-2.5/flare/edit",
                      "args": {"image_size": "landscape_16_9", "quality": "high", "output_format": "png"}},
    "flux-3": {"label": "FLUX 3", "endpoint": "blackforestlabs/flux-3/edit-image",
               "args": {"aspect_ratio": "16:9", "resolution": "2k", "output_format": "png"}},
    # moins chers, surtout pour les retouches : ~0,08 $ (1K) au lieu de 0,15 $, et ~0,03 $ (0,03 $ / mégapixel)
    "nano-banana-2": {"label": "Nano Banana 2", "endpoint": "fal-ai/nano-banana-2/edit",
                      "args": {"aspect_ratio": "16:9", "resolution": "1K", "output_format": "png"}},
    "qwen-image-edit": {"label": "Qwen Image Edit", "endpoint": "fal-ai/qwen-image-edit-2511",
                        "args": {"image_size": {"width": 1280, "height": 720}, "output_format": "png"}},
}
# le plus petit plafond d'images de référence parmi les modèles
MAX_REFS = 10


def job_name(tid: str, model: str) -> str:
    return f"thumb:{tid}:{model}"


def ready() -> bool:
    return bool(fal.key())


# une référence prise dans les médias du projet plutôt que dans la bibliothèque
PROJECT_PREFIX = "projet/"


def _ref_path(project: dict, rel: str) -> Path:
    """Une image de la bibliothèque, quelle que soit sa catégorie (le sélecteur les propose toutes), ou
    « projet/<rel> » : une image des médias du projet."""
    root = service.project_dir(project["id"]) if rel.startswith(PROJECT_PREFIX) else library.LIBRARY_DIR
    path = (root / rel.removeprefix(PROJECT_PREFIX)).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"image de référence introuvable : {rel}")
    return path


def build_prompt(thumb: dict, video_title: str, portraits: int, styles: int) -> str:
    """Le prompt envoyé au modèle : le rôle de chaque image de référence, puis ce que la vignette montre."""
    lines = ["A YouTube video thumbnail, 16:9, bold and readable at small size.", "", "Reference images, in order:"]
    if portraits:
        span = "Image 1" if portraits == 1 else f"Images 1 to {portraits}"
        what = "a photo" if portraits == 1 else "photos"
        lines.append(f"- {span}: {what} of the person who must appear in the thumbnail. Keep this person's face "
                     "and features exactly recognizable: same identity, no beautification, no change of age.")
    if styles:
        first = portraits + 1
        span = f"Image {first}" if styles == 1 else f"Images {first} to {portraits + styles}"
        what = "an example thumbnail" if styles == 1 else "example thumbnails"
        lines.append(f"- {span}: {what}, for style only. Reproduce their composition, framing, color "
                     "palette, lighting, contrast and graphic treatment. Do not copy the people, faces, logos or "
                     "text that appear in them.")
    lines += ["", f"Video title: {video_title}"]
    if thumb.get("prompt", "").strip():
        lines += ["", f"What the thumbnail shows: {thumb['prompt'].strip()}"]
    text = thumb.get("text", "").strip()
    if text:
        lines += ["", f'Write exactly this text, large, bold and perfectly spelled: "{text}". No other text.']
    else:
        lines += ["", "Do not write any text, letters or logos."]
    return "\n".join(lines)


def video_title(project: dict, thumb: dict) -> str:
    """Le titre associé à la variante, sinon le premier retenu à l'étape Titre, sinon celui du projet."""
    return (thumb.get("title") or "").strip() \
        or next((t["t"] for t in project["titles"] if t.get("pick")), None) or project["title"]


def build_edit_prompt(instruction: str, portraits: int) -> str:
    """Le prompt d'une retouche : l'image 1 est la vignette à modifier, le reste ne bouge pas."""
    lines = ["Image 1 is a YouTube video thumbnail (16:9). Edit it as asked below and change nothing else: "
             "same composition, framing, person, pose, colors, lighting and text, unless the request says otherwise."]
    if portraits:
        span = "Image 2" if portraits == 1 else f"Images 2 to {portraits + 1}"
        lines.append(f"{span}: photos of the person in the thumbnail, only to keep their face exactly "
                     "recognizable if it has to change. Do not add them as new elements.")
    lines += ["", f"Requested change: {instruction.strip()}",
              "", "Any text in the image must stay perfectly spelled."]
    return "\n".join(lines)


def _thumb(project: dict, tid: str) -> dict:
    thumb = next((t for t in project["thumbs"] if t.get("id") == tid), None)
    if not thumb:
        raise ValueError("variante inconnue")
    return thumb


def _launch(project: dict, tid: str, models: list[str], prompt: str, refs: list[Path], **extra) -> None:
    """Un job par modèle pour la variante `tid` ; ceux qui tournent déjà sont laissés tranquilles."""
    if not models or any(m not in MODELS for m in models):
        raise ValueError("choisis au moins un modèle")
    if len(refs) > MAX_REFS:
        raise ValueError(f"{MAX_REFS} images de référence au plus")
    dest = service.project_dir(project["id"]) / service.VIGNETTES_DIR
    for model in models:
        name = job_name(tid, model)
        current = jobs.get(project["jobs"].get(name) or "")
        if current and not current.finished:
            continue
        payload = {"project": project["id"], "thumb": tid, "model": model, "endpoint": MODELS[model]["endpoint"],
                   "args": MODELS[model]["args"], "prompt": prompt, "refs": [str(p) for p in refs],
                   "dest": str(dest), **extra}
        job = service.requeue(f"{project['id']}-thumb-{tid}-{model}", f"project_thumb:{model}", payload, {})
        project["jobs"][name] = job.id
    service.start_step(project, "vignette")


def start(project: dict, tid: str, models: list[str]) -> None:
    """Génère des vignettes neuves pour la variante `tid`, à partir de sa description et de ses références."""
    thumb = _thumb(project, tid)
    portraits = [_ref_path(project, r) for r in thumb.get("portraits") or []]
    styles = [_ref_path(project, r) for r in thumb.get("styles") or []]
    if not portraits and not styles:
        raise ValueError("choisis au moins un portrait ou une vignette de référence")
    prompt = build_prompt(thumb, video_title(project, thumb), len(portraits), len(styles))
    _launch(project, tid, models, prompt, portraits + styles)


def start_edit(project: dict, tid: str, file: str, instruction: str, models: list[str]) -> None:
    """Retouche une image de la galerie de `tid` : elle part en image 1, avec les portraits pour garder le visage."""
    thumb = _thumb(project, tid)
    if file not in {i["file"] for i in project.get("thumb_images", {}).get(tid, [])}:
        raise ValueError("image inconnue")
    if not instruction.strip():
        raise ValueError("dis ce qu'il faut changer")
    base = service.project_dir(project["id"]) / service.VIGNETTES_DIR / file
    if not base.is_file():
        raise ValueError(f"fichier introuvable : {file}")
    portraits = [_ref_path(project, r) for r in thumb.get("portraits") or []][:MAX_REFS - 1]
    _launch(project, tid, models, build_edit_prompt(instruction, len(portraits)), [base, *portraits],
            source=file, edit=instruction.strip())


def ideas_payload(project: dict, tid: str, note: str) -> dict:
    """Ce que reçoit Claude pour proposer des compositions : le projet et les références de la variante."""
    thumb = next((t for t in project["thumbs"] if t.get("id") == tid), None)
    if not thumb:
        raise ValueError("variante inconnue")
    sel = project.get("angle_sel")
    angle = project["angles"][sel] if sel is not None and 0 <= sel < len(project["angles"]) else None
    return {"thumb": tid, "note": note, "angle": angle, "current": thumb, "variants": project["thumbs"],
            "titles": [t["t"] for t in project["titles"] if t.get("pick")], "title": video_title(project, thumb),
            "portraits": [str(_ref_path(project, r)) for r in thumb.get("portraits") or []],
            "styles": [str(_ref_path(project, r)) for r in thumb.get("styles") or []]}


def apply_ideas(project: dict, result: dict, tid: str) -> None:
    """Les compositions proposées remplacent les précédentes."""
    project["thumb_ideas"] = {"thumb": tid, "items": result["compositions"], "message": result.get("message", "")}


def sync(project: dict) -> bool:
    """Les images des générations terminées rejoignent leur variante."""
    changed = False
    images = project.setdefault("thumb_images", {})
    for name, job_id in project["jobs"].items():
        if not name.startswith("thumb:"):
            continue
        job = jobs.get(job_id)
        if not job or job.status != "done" or job.state.get("applied") is not False:
            continue
        found = images.setdefault(job.payload["thumb"], [])
        # une retouche garde la trace de l'image d'origine et de la demande
        origin = {"source": job.payload["source"], "edit": job.payload["edit"]} if job.payload.get("source") else {}
        found[:0] = [{"file": f, "model": job.payload["model"], **origin} for f in job.state.get("files", [])]
        job.state["applied"] = True
        jobs.update(job.id, state=job.state)
        changed = True
    return changed


def remove_image(project: dict, tid: str, file: str) -> None:
    """Retire une image de la galerie de la variante (le fichier reste dans vignettes/)."""
    images = project.setdefault("thumb_images", {})
    images[tid] = [i for i in images.get(tid, []) if i["file"] != file]
    for t in project["thumbs"]:
        if t.get("id") == tid and t.get("image") == file:
            t["image"] = None


def view() -> dict:
    return {"models": [{"id": k, "label": m["label"]} for k, m in MODELS.items()], "ready": ready()}
