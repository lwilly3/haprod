"""
Retrouver un passage des rushes en le décrivant : « une foule dans une tribune », « le gardien qui plonge ».

Tout se passe sur la machine. Un modèle de vision multilingue (CLIP, via open_clip) regarde une image
de chaque rush toutes les deux secondes et en garde une empreinte ; la description tapée reçoit la
sienne, et les images les plus proches remontent. S'y ajoutent les passages où les mots de la recherche
sont dits (les transcripts), qui ne demandent aucun modèle.

L'index d'un rush (search/<rush>.npz dans le dossier du projet) est refait quand le fichier change.
Le modèle (environ 1,5 Go) est téléchargé une fois, au premier usage.
"""
import re
import subprocess
import tempfile
import threading
import unicodedata
from pathlib import Path

from ...core import jobs
from ...core.system import tool
from ...core.tasks import TaskContext
from . import derush, service

KIND = "project_search_index"
DIR = "search"
MODEL = ("xlm-roberta-base-ViT-B-32", "laion5b_s13b_b90k")
# une image toutes les STEP secondes : assez pour retrouver un plan, assez peu pour indexer vite
STEP = 2.0
BATCH = 32
# deux résultats d'un même rush sont au moins à cet écart : un plan de dix secondes ne remonte pas cinq fois
SPREAD = 8.0
LIMIT = 12

_lock = threading.Lock()
_loaded: dict = {}


def available() -> bool:
    try:
        import numpy  # noqa: F401
        import open_clip  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def _model() -> dict:
    """Le modèle, chargé une fois par process (l'API pour chercher, le worker pour indexer)."""
    with _lock:
        if not _loaded:
            import open_clip
            import torch

            model, _, preprocess = open_clip.create_model_and_transforms(MODEL[0], pretrained=MODEL[1])
            device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
            _loaded.update(model=model.to(device).eval(), preprocess=preprocess, device=device,
                           tokenizer=open_clip.get_tokenizer(MODEL[0]))
        return _loaded


def _index_file(pid: str, rush: dict) -> Path:
    return service.project_dir(pid) / DIR / f"{rush['id']}.npz"


def _stamp(rush: dict) -> float:
    return Path(rush["path"]).stat().st_mtime


def _load(pid: str, rush: dict):
    """(temps, empreintes) du rush s'il est indexé et inchangé depuis, sinon None."""
    import numpy as np

    path = _index_file(pid, rush)
    if not path.is_file() or not Path(rush["path"]).is_file():
        return None
    data = np.load(path)
    if float(data["stamp"]) != _stamp(rush) or tuple(data["model"]) != MODEL:
        return None
    return data["times"], data["vectors"].astype("float32")


def index_rush(pid: str, rush: dict, check_cancel) -> int:
    """Indexe un rush ; rend le nombre d'images vues."""
    import numpy as np
    import torch
    from PIL import Image

    m = _model()
    vectors = []
    with tempfile.TemporaryDirectory() as tmp:
        # format=yuvj420p : le JPEG veut des couleurs « pleine plage », que les vidéos d'iPhone n'ont pas toujours
        # les images clés seulement (une toutes les demi-secondes sur un boîtier) : décoder de la 4K entière serait long
        proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-skip_frame", "nokey", "-i", rush["path"], "-an",
                               "-vf", f"fps=1/{STEP},scale=336:-2,format=yuvj420p", "-q:v", "4", str(Path(tmp) / "%06d.jpg")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        files = sorted(Path(tmp).glob("*.jpg"))
        if proc.returncode != 0 and not files:
            raise RuntimeError(f"rush illisible : {Path(rush['path']).name}")
        for i in range(0, len(files), BATCH):
            check_cancel()
            batch = torch.stack([m["preprocess"](Image.open(f).convert("RGB")) for f in files[i:i + BATCH]])
            with torch.no_grad():
                out = m["model"].encode_image(batch.to(m["device"]))
                out = out / out.norm(dim=-1, keepdim=True)
            vectors.append(out.float().cpu().numpy())
    path = _index_file(pid, rush)
    path.parent.mkdir(parents=True, exist_ok=True)
    stacked = np.concatenate(vectors) if vectors else np.zeros((0, 1), dtype="float32")
    # le filtre fps rend une image par tranche de STEP secondes, la première à 0
    times = np.arange(len(stacked), dtype="float32") * STEP
    np.savez(path, times=times, vectors=stacked.astype("float16"), stamp=_stamp(rush), model=np.array(MODEL))
    return len(stacked)


def run(ctx: TaskContext) -> None:
    pid, state = ctx.payload["project"], ctx.state
    rushes = [r for r in service.load(pid)["rushes"] if Path(r["path"]).is_file()]
    todo = [r for r in rushes if _load(pid, r) is None]
    state["activity"] = "charge le modèle"
    ctx.save(force=True)
    _model()
    failed = []
    for n, rush in enumerate(todo):
        state["activity"] = f"regarde {rush['name']}"
        ctx.progress = n / len(todo)
        ctx.save(force=True)
        try:
            index_rush(pid, rush, ctx.check_cancel)
        except RuntimeError:
            # un rush illisible ne prive pas les autres de la recherche
            failed.append(rush["name"])
    state["activity"] = None
    if failed:
        raise RuntimeError("rushes illisibles : " + ", ".join(failed))


def status(project: dict, job_id: str | None) -> dict:
    job = jobs.get(job_id) if job_id else None
    rushes = [r for r in project["rushes"] if Path(r["path"]).is_file()]
    indexed = sum(1 for r in rushes if _index_file(project["id"], r).is_file()) if rushes else 0
    return {"available": available(), "rushes": len(rushes), "indexed": indexed,
            "running": bool(job and not job.finished), "progress": job.progress if job else 0.0,
            "activity": job.state.get("activity") if job else None,
            "error": job.error if job and job.status == "error" else None}


# --- Chercher --------------------------------------------------------------------------------

def _plain(text: str) -> str:
    """Sans accents ni majuscules : « Édéa » se trouve en tapant « edea »."""
    text = unicodedata.normalize("NFD", text.lower())
    return re.sub(r"[^a-z0-9 ]+", " ", "".join(c for c in text if unicodedata.category(c) != "Mn"))


def _said(project: dict, query: str) -> list[dict]:
    """Les phrases des rushes où tous les mots de la recherche sont dits."""
    wanted = [w for w in _plain(query).split() if len(w) > 2]
    if not wanted:
        return []
    hits = []
    for rush in project["rushes"]:
        segments, _ = derush.transcript_segments(rush.get("transcript"))
        for seg in segments or []:
            words = _plain(seg.text).split()
            if all(any(w.startswith(q) for w in words) for q in wanted):
                hits.append({"kind": "said", "rush": rush["id"], "name": rush["name"], "t": round(seg.start, 2),
                             "text": seg.text.strip()[:160], "score": 1.0})
    return hits


def _seen(project: dict, query: str) -> list[dict]:
    """Les images des rushes indexés les plus proches de la description."""
    import numpy as np
    import torch

    indexes = [(r, _load(project["id"], r)) for r in project["rushes"]]
    indexes = [(r, i) for r, i in indexes if i is not None and len(i[0])]
    if not indexes:
        return []
    m = _model()
    with torch.no_grad():
        vec = m["model"].encode_text(m["tokenizer"]([query]).to(m["device"]))
        vec = (vec / vec.norm(dim=-1, keepdim=True)).float().cpu().numpy()[0]
    found = []
    for rush, (times, vectors) in indexes:
        scores = vectors @ vec
        kept: list[float] = []
        for i in np.argsort(-scores)[:40]:
            t = float(times[i])
            if all(abs(t - k) >= SPREAD for k in kept):
                kept.append(t)
                found.append({"kind": "seen", "rush": rush["id"], "name": rush["name"], "t": round(t, 2),
                              "text": "", "score": round(float(scores[i]), 4)})
            if len(kept) >= 3:
                break
    found.sort(key=lambda h: -h["score"])
    return found[:LIMIT]


def search(project: dict, query: str) -> dict:
    query = query.strip()
    if not query:
        raise ValueError("décris ce que tu cherches")
    said = _said(project, query)[:LIMIT]
    seen = _seen(project, query) if available() else []
    return {"said": said, "seen": seen}


def frame(pid: str, rush: dict, t: float) -> Path:
    """L'image du rush à l'instant t (à la seconde), calculée une fois puis gardée."""
    out = service.project_dir(pid) / DIR / "frames" / f"{rush['id']}-{int(max(0.0, t))}.jpg"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", rush["path"],
                               "-frames:v", "1", "-vf", "scale=320:-2,format=yuvj420p", "-q:v", "4", str(out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0 or not out.is_file():
            raise RuntimeError("image indisponible")
    return out
