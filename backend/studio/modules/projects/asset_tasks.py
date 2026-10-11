"""
Côté worker, l'étape Assets : la recherche d'images avec Claude (les liens trouvés sont
vérifiés et téléchargés dans assets/.candidates/) et les captures des pages sources (Edge
ou Chrome en headless). Comme les autres tâches, aucune n'écrit project.json.
"""
import mimetypes
import ssl
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

import certifi

from ...core.system import browser
from ...core.tasks import TaskContext
from . import assets, prompts, service

MAX_IMAGE = 25 * 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
               "image/svg+xml": ".svg", "image/avif": ".avif"}
# certains sites (Wikimedia notamment) refusent les clients sans User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# les certificats de certifi (dépendance de yt-dlp) : ceux de Windows vus par Python peuvent être périmés
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
CAPTURE_SIZE = (1920, 1080)
CAPTURE_TIMEOUT = 60


def fetch_image(url: str, dest_stem: Path) -> Path:
    """Télécharge `url` si c'est bien une image ; rend le fichier (extension d'après le type)."""
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("lien non web")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.5"})
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as res:
        ctype = (res.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = IMAGE_TYPES.get(ctype)
        if not ext:
            guessed = mimetypes.guess_type(urlparse(url).path)[0]
            if ctype not in ("", "application/octet-stream", "binary/octet-stream") or guessed not in IMAGE_TYPES:
                raise ValueError(f"pas une image ({ctype or 'type inconnu'})")
            ext = IMAGE_TYPES[guessed]
        data = res.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise ValueError("image trop lourde")
    if len(data) < 200:
        raise ValueError("fichier vide")
    dest = dest_stem.with_suffix(ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def images(ctx: TaskContext) -> None:
    from .tasks import ask  # tasks.py importe ce module pour sa table TASKS

    state, p = ctx.state, ctx.payload
    messages = state["messages"]
    # un tour interrompu (worker relancé) repart de zéro
    while messages and messages[-1]["role"] == "ai":
        messages.pop()
    request = messages[-1]
    results = state.setdefault("results", [])
    out = ask(ctx, prompts.images_prompt(request["text"], [r["url"] for r in results]), prompts.images_system(),
              f"{prompts.READ_TOOLS},{prompts.WEB_TOOLS}", prompts.WEB_TOOLS, prompts.IMAGES_SCHEMA,
              state.get("session_id"))
    state["session_id"] = out["session_id"]
    output = out["output"] or {}

    ctx.set_status("downloading")
    state["activity"] = "vérifie les images"
    ctx.save(force=True)
    cache = assets.candidates_dir(p["project"])
    known = {r["url"] for r in results}
    fresh, rejected = [], 0
    for img in output.get("images") or []:
        ctx.check_cancel()
        url = (img.get("url") or "").strip()
        if not url or url in known:
            continue
        known.add(url)
        rid = uuid.uuid4().hex[:10]
        try:
            path = fetch_image(url, cache / rid)
        except Exception:
            rejected += 1
            continue
        fresh.append({"id": rid, "title": (img.get("title") or "Image").strip(), "url": url,
                      "page": img.get("page") or "", "variant": (img.get("variant") or "").strip(),
                      "license": (img.get("license") or "").strip(), "file": path.name,
                      "query": request["text"], "added": None})
    state["results"] = fresh + results
    text = (output.get("message") or out["text"]).strip()
    if rejected:
        text += f" ({rejected} lien{'s' if rejected > 1 else ''} écarté{'s' if rejected > 1 else ''} : pas une image accessible.)"
    messages.append({"role": "ai", "text": text, "count": len(fresh)})
    state["activity"] = None


def screenshot(url: str, dest: Path) -> None:
    """Le haut de la page en 16:9, comme un plan de coupe."""
    w, h = CAPTURE_SIZE
    with tempfile.TemporaryDirectory() as profile:
        args = [browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
                "--no-default-browser-check", f"--user-data-dir={profile}", f"--window-size={w},{h}",
                "--force-device-scale-factor=1", "--virtual-time-budget=8000", f"--screenshot={dest}", url]
        try:
            subprocess.run(args, capture_output=True, timeout=CAPTURE_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("la page n'a pas fini de charger") from e
    if not dest.is_file() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("capture impossible")


def captures(ctx: TaskContext) -> None:
    p, state = ctx.payload, ctx.state
    root = service.project_dir(p["project"])
    folder = Path(p["dest"])
    folder.mkdir(parents=True, exist_ok=True)
    done = state.setdefault("done", {})
    todo = [s for s in p["sources"] if s["u"] not in done]
    ctx.set_status("capturing")
    for i, s in enumerate(todo):
        ctx.check_cancel()
        state["activity"] = f"capture {urlparse(s['u']).netloc or s['u']}"
        ctx.save(force=True)
        dest = service.unique_path(folder, service.safe_name(f"Capture - {s['t'][:80]}.png"))
        try:
            screenshot(s["u"], dest)
            done[s["u"]] = {"rel": dest.relative_to(root).as_posix(), "error": None}
        except Exception as e:
            done[s["u"]] = {"rel": None, "error": str(e)[:200]}
        ctx.progress = (i + 1) / len(todo)
        ctx.save(force=True)
    state["activity"] = None
