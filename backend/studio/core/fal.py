"""
fal.ai : les modeles d'image (et plus tard de video) heberges par fal, appeles par leur
file d'attente HTTP. La cle vient de FAL_KEY : de l'environnement, ou a defaut de celui
de l'utilisateur Windows (un `setx FAL_KEY ...` suffit, sans rouvrir de terminal).

  POST queue.fal.run/<endpoint>  -> request_id, status_url, response_url, cancel_url
  GET  status_url                -> IN_QUEUE | IN_PROGRESS | COMPLETED
  GET  response_url              -> le resultat ({"images": [{"url": ...}]} pour une image)
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Callable

import certifi

QUEUE_URL = "https://queue.fal.run"
POLL_EVERY = 1.5
TIMEOUT = 10 * 60
# les certificats de certifi : ceux de Windows vus par Python peuvent etre perimes
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def key() -> str | None:
    found = os.environ.get("FAL_KEY")
    if found or sys.platform != "win32":
        return found
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
            return winreg.QueryValueEx(reg, "FAL_KEY")[0] or None
    except OSError:
        return None


def _request(url: str, method: str = "GET", body: dict | None = None) -> dict:
    api_key = key()
    if not api_key:
        raise RuntimeError("clé fal.ai absente : définis FAL_KEY (setx FAL_KEY \"ta-clé\")")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"fal.ai : {_error_detail(e)}") from e


def _error_detail(e: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(e.read()).get("detail")
    except (ValueError, AttributeError):
        return f"erreur {e.code}"
    if isinstance(detail, list):
        # erreurs de validation : [{"loc": [...], "msg": ...}]
        return "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    return str(detail or f"erreur {e.code}")


def run(endpoint: str, arguments: dict, check_cancel: Callable[[], None],
        on_status: Callable[[str], None] | None = None) -> dict:
    """Soumet une demande et attend son resultat ; `check_cancel` peut l'interrompre (la demande est annulee)."""
    submitted = _request(f"{QUEUE_URL}/{endpoint}", "POST", arguments)
    started = time.monotonic()
    status = ""
    try:
        while True:
            check_cancel()
            current = _request(submitted["status_url"]).get("status", "")
            if current != status and on_status:
                on_status(current)
            status = current
            if status == "COMPLETED":
                return _request(submitted["response_url"])
            if time.monotonic() - started > TIMEOUT:
                raise RuntimeError("fal.ai ne répond pas (délai dépassé)")
            time.sleep(POLL_EVERY)
    except BaseException:
        if status != "COMPLETED" and submitted.get("cancel_url"):
            try:
                _request(submitted["cancel_url"], "PUT")
            except RuntimeError:
                pass
        raise


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120, context=SSL_CONTEXT) as res:
        return res.read()
