"""
API des reglages : le profil de la chaine, la recherche de la chaine sur YouTube, la
connexion a ytwatch, l'analyse de la chaine par Claude et le moteur de transcription.
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ...core import youtube_api
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
