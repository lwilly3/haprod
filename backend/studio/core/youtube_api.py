"""
Le compte YouTube du studio, pour publier par l'API YouTube Data v3.

Il faut un client OAuth « application de bureau » d'un projet Google Cloud où l'API YouTube Data
v3 est activée : son fichier (client_secret.json) se dépose dans les Réglages. La connexion ouvre
le navigateur sur la page de consentement de Google (côté worker : elle attend la réponse) ;
le jeton obtenu est gardé et rafraîchi tout seul.

  data/youtube/client.json    le client OAuth
  data/youtube/token.json     le jeton du compte connecté
  data/youtube/channel.json   la chaîne de ce compte (titre, id, avatar)

Tant que Google n'a pas audité le projet, les vidéos envoyées par l'API restent privées.
"""
import json

from ..config import DATA_DIR

DIR = DATA_DIR / "youtube"
CLIENT_FILE = DIR / "client.json"
TOKEN_FILE = DIR / "token.json"
CHANNEL_FILE = DIR / "channel.json"
# envoi des vidéos et des vignettes, lecture de la chaîne
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def save_client(raw: bytes) -> None:
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError("ce n'est pas un fichier JSON") from e
    if "installed" not in data:
        raise ValueError("il faut un client OAuth de type « Application de bureau » (clé « installed »)")
    DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_bytes(raw)
    disconnect()


def disconnect() -> None:
    TOKEN_FILE.unlink(missing_ok=True)
    CHANNEL_FILE.unlink(missing_ok=True)


def credentials():
    """Les identifiants du compte connecté (rafraîchis au besoin), ou None."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_FILE.is_file():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds if creds.valid else None


def client():
    """Le client de l'API YouTube Data v3 ; erreur explicite si le compte n'est pas connecté."""
    from googleapiclient.discovery import build

    creds = credentials()
    if creds is None:
        raise RuntimeError("compte YouTube non connecté (Réglages)")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def connect() -> dict:
    """Le consentement Google dans le navigateur (bloquant), puis la chaîne du compte."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_FILE.is_file():
        raise RuntimeError("dépose d'abord le fichier client_secret.json")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  success_message="Studio est connecté à YouTube : tu peux fermer cet onglet.")
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    items = client().channels().list(part="snippet", mine=True).execute().get("items") or []
    if not items:
        disconnect()
        raise RuntimeError("ce compte Google n'a pas de chaîne YouTube")
    snippet = items[0]["snippet"]
    channel = {"id": items[0]["id"], "title": snippet.get("title"),
               "thumbnail": ((snippet.get("thumbnails") or {}).get("default") or {}).get("url")}
    CHANNEL_FILE.write_text(json.dumps(channel, ensure_ascii=False), encoding="utf-8")
    return channel


def status() -> dict:
    channel = json.loads(CHANNEL_FILE.read_text(encoding="utf-8")) if CHANNEL_FILE.is_file() else None
    return {"client": CLIENT_FILE.is_file(), "connected": TOKEN_FILE.is_file() and channel is not None,
            "channel": channel}


def ready() -> bool:
    return status()["connected"]
