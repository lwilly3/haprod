"""
Description et Upload : ce qui accompagne chaque vidéo sur YouTube (la vidéo longue et les shorts
de la sélection), les vérifications avant l'envoi, et l'envoi par l'API YouTube Data v3.

project.json, "publish" (modifié par l'interface) :

    {
      "videos": {"long" | "<short>": {"title", "desc", "tags",
                 # vidéo longue seulement : la vignette A, et le test A/B (variantes B et C)
                 "thumb", "ab_on", "ab": [{"thumb", "title"}]}},
      "pub":    {"long" | "<short>": {"vis": "private" | "unlisted" | "public" | "scheduled",
                                      "sched": "2026-10-14T18:00"}}     # heure locale
    }

Un champ absent prend sa valeur par défaut (titres et vignettes retenus, titre et accroche du
short, description par défaut des réglages…). L'envoi de chaque vidéo est un job, dans
project["jobs"]["upload:<vidéo>"].

L'API ne sait pas créer le test A/B de YouTube : la variante A est envoyée, B et C se posent
dans YouTube Studio. Les shorts n'ont pas de vignette personnalisée par l'API.
"""
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ...core import jobs, youtube_api
from ...core.system import tool
from ...core.tasks import TaskContext
from ..settings.service import default_description, language
from . import library, montage, render, service

KIND = "project_upload"
MAX_TITLE = 100
MAX_DESC = 5000
MAX_VARIANTS = 3
VISIBILITIES = ("private", "unlisted", "public", "scheduled")
# Science et technologie
CATEGORY = "28"
# une vignette envoyée à YouTube : 2 Mo au plus
THUMB_MAX_BYTES = 2 * 1024 * 1024
CHUNK = 8 * 1024 * 1024


def _fmt_tc(t: float) -> str:
    t = int(t)
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def chapters(pid: str) -> list[dict]:
    """Les chapitres du montage, prêts pour la description (le premier part de 00:00)."""
    marks = sorted((k for k in montage.load(pid)["markers"] if k["kind"] == "chapter"), key=lambda k: k["t"])
    return [{"t": _fmt_tc(0 if i == 0 else k["t"]), "label": k["text"].strip() or "Chapitre"} for i, k in enumerate(marks)]


def audio_credits(pid: str) -> list[str]:
    """Les crédits que la licence oblige à citer (CC BY) pour les sons et musiques du montage venus de la
    recherche en ligne de la bibliothèque (free_audio), une ligne par fichier, dans l'ordre de la timeline."""
    lines: list[str] = []
    for item in sorted(montage.load(pid)["audio"], key=lambda s: s.get("at", 0)):
        credit = library.credit_of(item.get("src") or "")
        if credit and credit.get("required") and credit["line"] not in lines:
            lines.append(credit["line"])
    return lines


def thumb_file(project: dict, tid: str | None) -> Path | None:
    """L'image retenue d'une variante de vignette (sinon la plus récente)."""
    thumb = next((t for t in project["thumbs"] if t.get("id") == tid), None)
    if not thumb:
        return None
    images = project.get("thumb_images", {}).get(tid) or []
    name = thumb.get("image") or (images[-1]["file"] if images else None)
    path = service.project_dir(project["id"]) / service.VIGNETTES_DIR / name if name else None
    return path if path and path.is_file() else None


def _long_defaults(project: dict) -> dict:
    picked = [t for t in project["thumbs"] if t.get("pick") and t.get("id")]
    sel = project["thumbs"][project["thumb_sel"]] if project.get("thumb_sel") is not None \
        and project["thumb_sel"] < len(project["thumbs"]) else None
    first = sel if sel and sel.get("id") else (picked[0] if picked else None)
    titles = [t["t"] for t in project["titles"] if t.get("pick")]
    others = [t for t in picked if first is None or t["id"] != first["id"]][:MAX_VARIANTS - 1]
    return {"title": (first or {}).get("title") or (titles[0] if titles else project["title"]),
            "thumb": first["id"] if first else None, "desc": _with_footer(""), "tags": [],
            "ab_on": bool(others), "ab": [{"thumb": t["id"], "title": t.get("title") or ""} for t in others]}


def _with_footer(text: str) -> str:
    """Le texte, suivi de la description par défaut des réglages (le bloc commun à toutes les vidéos)."""
    return "\n\n".join(x for x in (text.strip(), default_description()) if x)


def _short_defaults(short: dict) -> dict:
    return {"title": short["title"], "desc": _with_footer(f"{short['hook']}\n\n#shorts"), "tags": ["shorts"]}


def _check_title(title: str) -> bool:
    return bool(title.strip()) and len(title) <= MAX_TITLE


def videos(project: dict, selection: str | None = None) -> list[dict]:
    """Les vidéos à publier, avec leurs métadonnées effectives, vérifications et envoi."""
    from ..animations import service as animations

    pid = project["id"]
    saved = project.get("publish") or {}
    metas, pubs = saved.get("videos") or {}, saved.get("pub") or {}
    out = []

    # la vidéo longue : le rendu à jour, en 4K de préférence
    long_file, duration = None, 0.0
    for q in ("4k", "1080p"):
        v = render.view(project, q)
        duration = v["duration"]
        if v["url"] and v["current"]:
            long_file = str(render.output_file(pid, q))
            break
    meta = {**_long_defaults(project), **metas.get("long", {})}
    chaps = chapters(pid)
    variants = [{"thumb": meta["thumb"], "title": meta["title"]}, *meta["ab"]] if meta["ab_on"] else []
    checks = [
        {"k": "Vignette", "ok": thumb_file(project, meta["thumb"]) is not None, "fix": "vignette"},
        {"k": "Titre", "ok": _check_title(meta["title"]), "fix": "description", "meta": True},
    ]
    if chaps:
        checks.append({"k": "Chapitres", "ok": "00:00" in meta["desc"], "fix": "description", "meta": True})
    credits = audio_credits(pid)
    if credits:
        # une musique ou un son sous CC BY non cité, c'est une réclamation possible sur la vidéo
        checks.append({"k": "Crédits audio", "ok": all(line in meta["desc"] for line in credits),
                       "fix": "description", "meta": True})
    if meta["ab_on"]:
        checks.append({"k": "Test A/B", "fix": "description", "meta": True,
                       "ok": 2 <= len(variants) <= MAX_VARIANTS and all(
                           _check_title(a["title"]) and thumb_file(project, a["thumb"]) for a in variants)})
    checks.append({"k": "Rendu", "ok": long_file is not None, "fix": "rendu"})
    out.append({"id": "long", "kind": "long", "name": "Vidéo longue", "format": "16:9", "duration": duration,
                "meta": meta, "chapters": chaps, "credits": credits, "file": long_file, "checks": checks})

    # les shorts de la sélection affichée
    rows = render.shorts(project, selection)
    selection_job = jobs.get(rows["selection"] or "")
    by_id = {s["id"]: s for s in (selection_job.state.get("shorts", []) if selection_job else [])}
    for i, item in enumerate(rows["items"]):
        short = by_id.get(item["id"])
        if not short:
            continue
        meta = {**_short_defaults(short), **metas.get(item["id"], {})}
        r = item["render"]
        file = None
        if r and r["url"]:
            found = jobs.get(r["id"])
            file = str(animations.render_output(found)) if found else None
        out.append({"id": item["id"], "kind": "short", "name": f"Short {i + 1:02d}", "format": "9:16",
                    "duration": item["duration"], "meta": meta,
                    "passage": " … ".join(c["text"].strip() for c in short.get("clips", []) if c.get("text")),
                    "file": file, "checks": [
                        {"k": "Titre", "ok": _check_title(meta["title"]), "fix": "description", "meta": True},
                        {"k": "Description", "ok": bool(meta["desc"].strip()), "fix": "description", "meta": True},
                        {"k": "Rendu", "ok": file is not None, "fix": "rendu"},
                    ]})

    for v in out:
        v["pub"] = {"vis": "private", "sched": "", **pubs.get(v["id"], {})}
        job = jobs.get(project["jobs"].get(f"upload:{v['id']}") or "")
        v["upload"] = None if job is None else {
            "status": job.status, "progress": job.progress, "error": job.error,
            "video_id": job.state.get("video_id"), "warning": job.state.get("warning"),
            "url": f"https://youtu.be/{job.state['video_id']}" if job.state.get("video_id") else None}
    return out


def view(project: dict, selection: str | None = None) -> dict:
    found = videos(project, selection)
    return {"videos": found, "account": youtube_api.status(), "long_title": found[0]["meta"]["title"]}


def all_sent(found: list[dict]) -> bool:
    return bool(found) and all(v["upload"] and v["upload"]["status"] == "done" for v in found)


def _publish_at(local: str) -> str:
    """« 2026-10-14T18:00 » (heure locale) -> RFC 3339 en UTC, dans le futur."""
    try:
        moment = datetime.fromisoformat(local).astimezone()
    except ValueError as e:
        raise ValueError("date de publication invalide") from e
    if moment <= datetime.now().astimezone():
        raise ValueError("la date de publication est passée")
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def start(project: dict, video_id: str, selection: str | None) -> jobs.Job:
    if not youtube_api.ready():
        raise ValueError("connecte d'abord ton compte YouTube (Réglages)")
    video = next((v for v in videos(project, selection) if v["id"] == video_id), None)
    if video is None:
        raise ValueError("vidéo inconnue")
    bad = [c["k"] for c in video["checks"] if not c["ok"]]
    if bad:
        raise ValueError(f"à corriger : {', '.join(bad)}")
    current = jobs.get(project["jobs"].get(f"upload:{video_id}") or "")
    if current and current.status == "done":
        raise ValueError("déjà envoyée")
    if current and not current.finished:
        raise ValueError("envoi déjà en cours")
    pub, meta = video["pub"], video["meta"]
    if pub["vis"] not in VISIBILITIES:
        raise ValueError(f"visibilité inconnue : {pub['vis']}")
    tags = [t.strip() for t in meta["tags"] if t.strip()]
    desc = meta["desc"]
    if video["kind"] == "short":
        # sur un short, ce sont les hashtags de la description qui comptent
        missing = [f"#{t.lstrip('#')}" for t in tags if f"#{t.lstrip('#')}".lower() not in desc.lower()]
        if missing:
            desc = f"{desc.rstrip()}\n{' '.join(missing)}"
    if len(desc) > MAX_DESC:
        raise ValueError(f"description trop longue ({len(desc)}/{MAX_DESC})")
    payload = {"project": project["id"], "video": video_id, "file": video["file"],
               "title": meta["title"].strip(), "desc": desc, "tags": [t.lstrip("#") for t in tags],
               "vis": pub["vis"], "publish_at": _publish_at(pub["sched"]) if pub["vis"] == "scheduled" else None,
               "thumb": str(thumb_file(project, meta.get("thumb"))) if video["kind"] == "long" else None}
    job = jobs.create(service.MODULE, KIND, payload, {})
    project["jobs"][f"upload:{video_id}"] = job.id
    service.start_step(project, "upload")
    return job


# --- Côté worker ------------------------------------------------------------------------

def _thumb_for_youtube(path: Path, tmp: Path) -> Path:
    """La vignette en JPEG 1280×720 si elle dépasse la taille admise par YouTube."""
    if path.stat().st_size <= THUMB_MAX_BYTES:
        return path
    out = tmp / "thumb.jpg"
    for q in (3, 6, 10):
        subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(path), "-vf", "scale=1280:-2",
                        "-q:v", str(q), str(out)], check=True, capture_output=True)
        if out.stat().st_size <= THUMB_MAX_BYTES:
            break
    return out


def upload(ctx: TaskContext) -> None:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    p = ctx.payload
    if not Path(p["file"]).is_file():
        raise RuntimeError("le fichier rendu a disparu : relance le rendu")
    client = youtube_api.client()
    status = {"privacyStatus": "private" if p["vis"] == "scheduled" else p["vis"], "selfDeclaredMadeForKids": False}
    if p["publish_at"]:
        status["publishAt"] = p["publish_at"]
    body = {"snippet": {"title": p["title"], "description": p["desc"], "tags": p["tags"], "categoryId": CATEGORY,
                        "defaultLanguage": language(), "defaultAudioLanguage": language()},
            "status": status}
    ctx.set_status("uploading")
    request = client.videos().insert(part="snippet,status", body=body, notifySubscribers=True,
                                     media_body=MediaFileUpload(p["file"], mimetype="video/mp4", chunksize=CHUNK,
                                                                resumable=True))
    response = None
    try:
        while response is None:
            progress, response = request.next_chunk()
            if progress:
                ctx.progress = progress.progress() * 0.97
                ctx.save()
            ctx.check_cancel()
    except HttpError as e:
        raise RuntimeError(f"YouTube a refusé l'envoi : {e.reason if hasattr(e, 'reason') else e}") from e
    ctx.state["video_id"] = response["id"]
    ctx.save(force=True)
    if p["thumb"] and Path(p["thumb"]).is_file():
        with tempfile.TemporaryDirectory() as tmp:
            try:
                thumb = _thumb_for_youtube(Path(p["thumb"]), Path(tmp))
                client.thumbnails().set(videoId=response["id"], media_body=MediaFileUpload(str(thumb))).execute()
            except Exception as e:  # noqa: BLE001  la vidéo est en ligne : la vignette se reposera à la main
                ctx.state["warning"] = f"vignette non envoyée : {e}"
