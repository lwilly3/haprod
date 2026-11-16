"""
API des reglages : le profil de la chaine, la recherche de la chaine sur YouTube, la
connexion a ytwatch, l'analyse de la chaine par Claude, la description par defaut des
videos et le moteur de transcription.
"""
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ...core import claude, codex, youtube_api
from . import service

router = APIRouter()


@router.get("/channel")
def get_channel():
    return service.channel()


@router.put("/channel")
def put_channel(values: dict):
    return service.save_channel(values)


@router.get("/channels/search")
def search_channels(q: str):
    if len(q.strip()) < 2:
        return []
    try:
        return service.search_channels(q)
    except Exception as e:  # noqa: BLE001  yt-dlp leve des erreurs de toutes sortes (reseau, YouTube)
        raise HTTPException(502, f"recherche YouTube impossible : {e}") from e


@router.get("/publish")
def get_publish():
    return service.publish_settings()


@router.put("/publish")
def put_publish(values: dict):
    return service.save_publish_settings(values)


class Ytwatch(BaseModel):
    url: str = ""
    token: str = ""


@router.get("/ytwatch")
def get_ytwatch():
    return service.ytwatch_view()


@router.put("/ytwatch")
def put_ytwatch(body: Ytwatch):
    try:
        return service.save_ytwatch(body.url, body.token)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/ytwatch")
def delete_ytwatch():
    return service.remove_ytwatch()


@router.get("/claude")
def get_claude():
    return service.claude_models()


@router.put("/claude")
def put_claude(values: dict):
    try:
        return service.save_claude_models(values)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# --- Compte Claude : connexion et déconnexion ----------------------------------------
# Réservé à ce Mac : le studio écoute aussi sur le réseau local (prompteur), et personne d'autre
# ne doit pouvoir y brancher son propre compte ni déconnecter celui de l'auteur.

def _local(request: Request) -> None:
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "le compte Claude ne se gère que depuis l'ordinateur du studio")


def _claude_account() -> dict:
    return {**claude.auth_status(), **claude.login_state()}


@router.get("/claude/account")
def get_claude_account(request: Request):
    _local(request)
    return _claude_account()


@router.post("/claude/login")
def claude_login(request: Request):
    _local(request)
    try:
        claude.login_start()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    return _claude_account()


class ClaudeCode(BaseModel):
    code: str


@router.post("/claude/code")
def claude_code(request: Request, body: ClaudeCode):
    _local(request)
    try:
        claude.login_code(body.code)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return _claude_account()


@router.post("/claude/cancel")
def claude_cancel(request: Request):
    _local(request)
    claude.login_cancel()
    return _claude_account()


@router.delete("/claude/account")
def claude_logout(request: Request):
    _local(request)
    try:
        claude.logout()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    return _claude_account()


# --- Compte ChatGPT (Codex) : il génère les miniatures par l'abonnement -----------------

@router.get("/chatgpt/account")
def get_chatgpt_account(request: Request):
    _local(request)
    return codex.account()


@router.post("/chatgpt/login")
def chatgpt_login(request: Request):
    _local(request)
    try:
        codex.login_start()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    return codex.account()


@router.post("/chatgpt/cancel")
def chatgpt_cancel(request: Request):
    _local(request)
    codex.login_cancel()
    return codex.account()


@router.delete("/chatgpt/account")
def chatgpt_logout(request: Request):
    _local(request)
    try:
        codex.logout()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    return codex.account()


class Transcription(BaseModel):
    engine: str
    key: str = ""


@router.get("/transcription")
def get_transcription():
    return service.transcription_view()


@router.put("/transcription")
def put_transcription(body: Transcription):
    try:
        return service.save_transcription(body.engine, body.key)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/transcription/keys/{engine}")
def delete_transcription_key(engine: str):
    return service.remove_transcription_key(engine)


@router.get("/analysis")
def get_analysis():
    return service.analysis_view()


@router.post("/analysis")
def start_analysis():
    try:
        return service.start_analysis()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/analysis/cancel")
def cancel_analysis():
    return service.cancel_analysis()


# --- Compte YouTube (publication) ------------------------------------------------------

@router.get("/youtube")
def get_youtube():
    return service.youtube_view()


@router.post("/youtube/client")
def upload_youtube_client(file: UploadFile = File(...)):
    """Le client OAuth (client_secret.json) : le remplacer déconnecte le compte."""
    try:
        youtube_api.save_client(file.file.read())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return service.youtube_view()


@router.post("/youtube/connect")
def connect_youtube():
    try:
        return service.start_youtube_connect()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/youtube/cancel")
def cancel_youtube():
    return service.cancel_youtube_connect()


@router.delete("/youtube")
def disconnect_youtube():
    youtube_api.disconnect()
    return service.youtube_view()
