"""
Reglages du studio : pour l'instant, le profil de la chaine YouTube.

Il est donne a Claude dans toutes les etapes d'ecriture (angles, titres, script,
assistant) : sans lui, Claude ecrit pour « un createur YouTube » quelconque. Mais c'est
une toile de fond : le brief, l'angle retenu et la methode du skill passent avant.

data/channel.json : {cle: texte} pour chaque champ de FIELDS, vide si non renseigne,
"youtube" : la chaine YouTube choisie dans la recherche (ou null), et "language" : la langue
de la chaine, celle de tout ce que Claude ecrit, des transcriptions et de la publication.
"""
import json
import re

from ...config import DATA_DIR
from ...core import jobs

MODULE = "settings"
CHANNEL_FILE = DATA_DIR / "channel.json"

# cle, intitule dans le prompt, groupe : "rule" s'applique a chaque video,
# "context" ne sert que si le sujet s'y prete (sinon l'identite de l'auteur deborde partout)
FIELDS = (
    ("name", "Nom", "context"),
    ("identity", "Qui est l'auteur", "context"),
    ("pitch", "Positionnement", "context"),
    ("audience", "Public", "rule"),
    ("tone", "Ton et style", "rule"),
    ("formats", "Formats habituels", "context"),
    ("avoid", "À éviter", "rule"),
    ("videos", "Vidéos déjà publiées", "context"),
)
YOUTUBE_KEYS = ("id", "title", "handle", "url", "thumbnail", "followers")
# code ISO 639-1 → nom dans les prompts (ecrits en francais)
LANGUAGES = {"fr": "français", "en": "anglais", "es": "espagnol", "de": "allemand", "it": "italien", "pt": "portugais"}
SEARCH_LIMIT = 8


def channel() -> dict:
    data = json.loads(CHANNEL_FILE.read_text(encoding="utf-8")) if CHANNEL_FILE.is_file() else {}
    return {**{key: str(data.get(key) or "") for key, _, _ in FIELDS}, "youtube": _youtube(data.get("youtube")),
            "language": _language(data.get("language"), CHANNEL_FILE.is_file())}


def save_channel(values: dict) -> dict:
    data = {key: str(values.get(key) or "").strip() for key, _, _ in FIELDS}
    data["youtube"] = _youtube(values.get("youtube"))
    data["language"] = _language(values.get("language"), True)
    CHANNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHANNEL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _youtube(value) -> dict | None:
    if not isinstance(value, dict) or not value.get("id"):
        return None
    return {key: value.get(key) for key in YOUTUBE_KEYS}


def _language(value, existing: bool) -> str:
    if value in LANGUAGES:
        return value
    # un channel.json d'avant ce reglage date d'un studio qui ecrivait tout en francais
    return "fr" if existing else "en"


def language() -> str:
    """La langue de la chaine (code ISO 639-1)."""
    return channel()["language"]


def language_name() -> str:
    """« français », « anglais »… : pour les prompts."""
    return LANGUAGES[language()]


def has_tone() -> bool:
    return bool(channel()["tone"].strip())


def channel_prompt() -> str:
    """Le bloc « La chaîne » des prompts, vide si rien n'est renseigné."""
    data = channel()

    def section(group: str) -> str:
        return "\n\n".join(f"### {label}\n{data[key].strip()}"
                           for key, label, g in FIELDS if g == group and data[key].strip())

    rules, context = section("rule"), section("context")
    if not rules and not context:
        return ""
    parts = ["# La chaîne\n"
             "Le profil de la chaîne, tel que l'auteur le décrit. C'est une toile de fond, pas une consigne : "
             "le brief, l'angle retenu et la méthode du skill passent avant."]
    if rules:
        parts.append("## À respecter dans chaque vidéo\n\n" + rules)
    if context:
        parts.append(
            "## Contexte, à n'utiliser qu'à propos\n"
            "Ne t'en sers que quand le sujet s'y prête vraiment : une anecdote vécue, une légitimité sur le "
            "sujet, une suite à une vidéo passée. Beaucoup de vidéos n'ont aucun rapport avec le parcours de "
            "l'auteur : ne l'y ramène pas, ne le cite pas par réflexe, et ne fais pas de son identité l'angle "
            "d'une vidéo si le brief ne le demande pas. Ne repropose pas un angle déjà traité dans ses vidéos "
            "publiées, sauf pour le prolonger explicitement.\n\n" + context)
    return "\n\n".join(parts)


# --- Recherche de chaines YouTube -------------------------------------------------

def search_channels(query: str) -> list[dict]:
    """Les chaînes YouTube qui correspondent à un nom, un @handle ou une URL de chaîne."""
    import urllib.parse

    import yt_dlp  # import differe : l'API redemarre a chaque modif, autant qu'elle reste legere

    from ..youtube.service import ydl_options

    # une URL de chaine : on cherche son @handle, YouTube le place en tete
    handle = re.search(r"youtube\.com/(@[\w.-]+)", query)
    terms = handle.group(1) if handle else query.strip()
    # sp=EgIQAg== : le filtre « Chaînes » de la recherche YouTube
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(terms)}&sp=EgIQAg%3D%3D"
    with yt_dlp.YoutubeDL(ydl_options(extract_flat=True, skip_download=True, playlistend=SEARCH_LIMIT)) as ydl:
        info = ydl.extract_info(url, download=False)
    found = []
    for e in (info or {}).get("entries") or []:
        if not e.get("channel_id"):
            continue
        thumbs = sorted(e.get("thumbnails") or [], key=lambda t: t.get("height") or 0)
        thumb = thumbs[-1]["url"] if thumbs else None
        found.append({
            "id": e["channel_id"],
            "title": e.get("channel") or e.get("title") or "",
            "handle": e.get("uploader_id") or "",
            "url": e.get("uploader_url") or e.get("channel_url") or "",
            "thumbnail": f"https:{thumb}" if thumb and thumb.startswith("//") else thumb,
            "followers": e.get("channel_follower_count"),
            "description": e.get("description") or "",
        })
    return found


# --- ytwatch : les stats de la chaine, via son MCP -----------------------------------
# data/ytwatch.json : {"url", "token"}. Le jeton ne repart jamais vers l'interface.

YTWATCH_FILE = DATA_DIR / "ytwatch.json"
YTWATCH_URL = "https://ytwatch.hakanai.io/mcp"
YTWATCH_SERVER = "ytwatch"


def ytwatch() -> dict | None:
    data = json.loads(YTWATCH_FILE.read_text(encoding="utf-8")) if YTWATCH_FILE.is_file() else {}
    return data if data.get("token") else None


def ytwatch_view() -> dict:
    data = ytwatch()
    if not data:
        return {"connected": False, "url": YTWATCH_URL, "token_hint": ""}
    token = data["token"]
    return {"connected": True, "url": data["url"], "token_hint": f"{token[:4]}…{token[-4:]}"}


def save_ytwatch(url: str, token: str) -> dict:
    """Un jeton vide garde le jeton enregistre (l'interface ne le connait pas)."""
    current = ytwatch() or {}
    token = token.strip() or current.get("token", "")
    if not token:
        raise ValueError("jeton manquant")
    YTWATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    YTWATCH_FILE.write_text(json.dumps({"url": url.strip() or YTWATCH_URL, "token": token}, indent=2),
                            encoding="utf-8")
    return ytwatch_view()


def remove_ytwatch() -> dict:
    YTWATCH_FILE.unlink(missing_ok=True)
    return ytwatch_view()


def mcp_config(path) -> None:
    """Le fichier --mcp-config de claude -p, avec le jeton : a supprimer apres le tour."""
    data = ytwatch()
    path.write_text(json.dumps({"mcpServers": {YTWATCH_SERVER: {
        "type": "http", "url": data["url"], "headers": {"Authorization": f"Bearer {data['token']}"}}}}),
        encoding="utf-8")


# --- Moteur de transcription ---------------------------------------------------------
# data/transcription.json : {"engine", "keys": {fournisseur: cle}}. Whisper (local, gratuit) par
# defaut ; les API sont plus fideles pour le derush. Les cles ne repartent jamais vers l'interface.

TRANSCRIPTION_FILE = DATA_DIR / "transcription.json"
ENGINES = ("whisper", "elevenlabs", "gladia")
CLOUD_ENGINES = ENGINES[1:]


def _transcription() -> dict:
    data = json.loads(TRANSCRIPTION_FILE.read_text(encoding="utf-8")) if TRANSCRIPTION_FILE.is_file() else {}
    keys = {p: k for p, k in (data.get("keys") or {}).items() if p in CLOUD_ENGINES and k}
    engine = data.get("engine") if data.get("engine") in ENGINES else "whisper"
    return {"engine": engine if engine == "whisper" or engine in keys else "whisper", "keys": keys}


def transcription_engine() -> tuple[str, str | None]:
    """Le moteur choisi et sa clé (None pour Whisper)."""
    data = _transcription()
    return data["engine"], data["keys"].get(data["engine"])


def transcription_view() -> dict:
    data = _transcription()
    return {"engine": data["engine"],
            "keys": {p: f"{k[:4]}…{k[-4:]}" for p, k in data["keys"].items()}}


def save_transcription(engine: str, key: str = "") -> dict:
    """Choisit le moteur ; `key`, si elle est donnée, remplace celle de ce moteur."""
    if engine not in ENGINES:
        raise ValueError("moteur inconnu")
    data = _transcription()
    if key.strip():
        if engine == "whisper":
            raise ValueError("Whisper n'a pas de clé")
        data["keys"][engine] = key.strip()
    if engine != "whisper" and engine not in data["keys"]:
        raise ValueError("clé API manquante")
    data["engine"] = engine
    _write_transcription(data)
    return transcription_view()


def remove_transcription_key(engine: str) -> dict:
    """Oublie la clé ; si ce moteur était choisi, on revient à Whisper."""
    data = _transcription()
    data["keys"].pop(engine, None)
    if data["engine"] == engine:
        data["engine"] = "whisper"
    _write_transcription(data)
    return transcription_view()


def _write_transcription(data: dict) -> None:
    TRANSCRIPTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- Publication : le bloc commun a toutes les descriptions --------------------------
# Les liens, les outils, les reseaux : propose par defaut sous chaque description, a
# completer au-dessus (accroche) ou entre les deux (chapitres). Hors du profil : Claude n'en a pas besoin.

PUBLISH_FILE = DATA_DIR / "publish.json"


def publish_settings() -> dict:
    data = json.loads(PUBLISH_FILE.read_text(encoding="utf-8")) if PUBLISH_FILE.is_file() else {}
    return {"description": str(data.get("description") or "")}


def save_publish_settings(values: dict) -> dict:
    data = {"description": str(values.get("description") or "").strip()}
    PUBLISH_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLISH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def default_description() -> str:
    return publish_settings()["description"]


# --- Analyse de la chaine -----------------------------------------------------------
# Un job : Claude lit les stats (MCP ytwatch) et quelques transcriptions, et propose une
# version de chaque champ. Rien n'est ecrit dans le profil : l'auteur accepte champ par champ.

ANALYSIS_KIND = "channel_analysis"
WORK_DIR = DATA_DIR / "settings"


def analysis_job() -> jobs.Job | None:
    found = [j for j in jobs.list_jobs(MODULE) if j.kind == ANALYSIS_KIND]
    return found[-1] if found else None


def analysis_view() -> dict | None:
    job = analysis_job()
    if not job:
        return None
    return {"id": job.id, "status": job.status, "error": job.error, "activity": job.state.get("activity"),
            "result": job.state.get("result"), "finished_at": job.finished_at}


def start_analysis() -> dict:
    if not ytwatch():
        raise ValueError("connecte d'abord ytwatch")
    job = analysis_job()
    if job and not job.finished:
        return analysis_view()
    youtube = channel()["youtube"]
    jobs.create(MODULE, ANALYSIS_KIND, {"channel_id": youtube["id"] if youtube else None,
                                        "channel_url": youtube["url"] if youtube else None})
    return analysis_view()


def cancel_analysis() -> dict | None:
    job = analysis_job()
    if job and not job.finished:
        jobs.cancel(job)
    return analysis_view()


# --- Compte YouTube (publication par l'API) ------------------------------------------

YOUTUBE_KIND = "youtube_connect"


def youtube_job() -> jobs.Job | None:
    found = [j for j in jobs.list_jobs(MODULE) if j.kind == YOUTUBE_KIND]
    return found[-1] if found else None


def youtube_view() -> dict:
    from ...core import youtube_api

    job = youtube_job()
    return {**youtube_api.status(),
            "connecting": bool(job and not job.finished),
            "error": job.error if job and job.status == "error" else None}


def start_youtube_connect() -> dict:
    from ...core import youtube_api

    if not youtube_api.CLIENT_FILE.is_file():
        raise ValueError("dépose d'abord le fichier client_secret.json")
    job = youtube_job()
    if not (job and not job.finished):
        jobs.create(MODULE, YOUTUBE_KIND, {})
    return youtube_view()


def cancel_youtube_connect() -> dict:
    job = youtube_job()
    if job and not job.finished:
        jobs.cancel(job)
    return youtube_view()
