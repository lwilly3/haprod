"""
Sons et musiques libres de droits, cherchés en ligne et rangés dans la bibliothèque.

La source est Openverse (l'index ouvert de WordPress.org) : sans clé, il couvre Freesound (bruitages,
ambiances) et Jamendo (musique). On ne garde que les licences utilisables sur une chaîne monétisée :
domaine public (CC0, PDM) et CC BY, qui demande de citer l'auteur. Chaque fichier ajouté garde son
crédit dans l'index de la bibliothèque : l'étape Description le reprend (publish.audio_credits).

Sans clé, Openverse accorde 20 recherches par minute et 200 par jour.
"""
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

import certifi

from . import library, service

API = "https://api.openverse.org/v1/audio/"
USER_AGENT = "haprod-studio"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
# pas de « non commercial » ni de « partage à l'identique » : ils ne conviennent pas à une vidéo monétisée
LICENSES = ("cc0", "pdm", "by")
# ce que la bibliothèque appelle « Sound design » et « Musique », dit à Openverse
FILTERS = {"sfx": {"source": "freesound"}, "musique": {"category": "music"}}
PAGE_SIZE = 20
MAX_BYTES = 80 * 1024 * 1024
EXTENSIONS = {"mp3": ".mp3", "mp32": ".mp3", "ogg": ".ogg", "oga": ".ogg", "wav": ".wav", "flac": ".flac", "m4a": ".m4a"}
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise ValueError("trop de recherches d'affilée : Openverse en accorde 20 par minute et 200 par jour, "
                             "réessaie dans un moment") from e
        raise ValueError(f"Openverse a répondu {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValueError("Openverse est injoignable : vérifie la connexion") from e


def _license(item: dict) -> str:
    code, version = item.get("license") or "", item.get("license_version") or ""
    name = {"cc0": "CC0", "pdm": "Public domain", "by": "CC BY"}.get(code, code.upper())
    return f"{name} {version}".strip() if code != "pdm" else name


def _credit(item: dict) -> dict:
    """Ce qu'il faut pour citer le fichier. `required` : la licence oblige à le faire (CC BY)."""
    title = (item.get("title") or "").strip() or "Untitled"
    creator = (item.get("creator") or "").strip() or "unknown"
    page = item.get("foreign_landing_url") or ""
    return {"title": title, "creator": creator, "license": _license(item), "license_url": item.get("license_url") or "",
            "url": page, "required": item.get("license") == "by",
            "line": f"“{title}” by {creator} ({_license(item)}) {page}".strip()}


def _view(item: dict) -> dict:
    return {"id": item["id"], "preview": item.get("url") or "", "source": item.get("source") or "",
            "duration": (item.get("duration") or 0) / 1000 or None,
            "tags": [t["name"] for t in (item.get("tags") or [])[:6] if t.get("name")], **_credit(item)}


def search(category: str, query: str, page: int = 1) -> dict:
    if category not in FILTERS:
        raise ValueError("la recherche en ligne ne couvre que la musique et le sound design")
    if not query.strip():
        raise ValueError("dis ce que tu cherches")
    params = {"q": query.strip(), "license": ",".join(LICENSES), "page_size": PAGE_SIZE, "page": max(1, page),
              **FILTERS[category]}
    data = _get(f"{API}?{urllib.parse.urlencode(params)}")
    return {"items": [_view(x) for x in data.get("results", []) if x.get("url")],
            "page": data.get("page", 1), "pages": data.get("page_count", 1), "total": data.get("result_count", 0)}


def add(category: str, audio_id: str) -> str:
    """Télécharge le son dans la bibliothèque et rend son chemin relatif (« sfx/applause.mp3 »).

    L'adresse du fichier est redemandée à Openverse par son identifiant : l'interface ne peut pas
    faire télécharger n'importe quelle adresse au studio."""
    if category not in FILTERS:
        raise ValueError("catégorie inconnue")
    if not _ID.match(audio_id):
        raise ValueError("identifiant inconnu")
    item = _get(f"{API}{audio_id}/")
    if item.get("license") not in LICENSES:
        raise ValueError("la licence de ce fichier ne convient pas à une vidéo monétisée")
    url = item.get("url") or ""
    if not url.startswith("https://"):
        raise ValueError("fichier indisponible")
    credit = _credit(item)
    known = library.find_credit(category, credit["url"])
    if known:
        return known
    folder = library.library_folder(category)
    folder.mkdir(parents=True, exist_ok=True)
    ext = EXTENSIONS.get((item.get("filetype") or "").lower(), ".mp3")
    stem = service.safe_name((item.get("title") or "son").rsplit(".", 1)[0])[:60].strip() or "son"
    dest = folder / f"{stem}{ext}"
    if dest.exists():
        dest = folder / f"{stem}-{audio_id[:6]}{ext}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as res, dest.open("wb") as out:
            size = 0
            while chunk := res.read(1 << 16):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("fichier trop lourd")
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        dest.unlink(missing_ok=True)
        raise ValueError(str(e) if isinstance(e, ValueError) else "téléchargement impossible") from e
    rel = f"{category}/{dest.name}"
    tags = ", ".join(t["name"] for t in (item.get("tags") or [])[:6] if t.get("name"))
    library.remember_credit(rel, credit, f"{credit['title']}" + (f" ({tags})" if tags else ""))
    return rel
