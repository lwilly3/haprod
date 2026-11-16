"""
Codex (l'agent en ligne de commande d'OpenAI) en mode non interactif : comme pour Claude Code, c'est
l'abonnement connecté (ChatGPT) qui est utilisé, pas des crédits API. Sert à générer des images.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from .login import BrowserLogin

# sinon le CLI pourrait les préférer à l'abonnement (et facturer l'API)
API_ENV = ("OPENAI_API_KEY",)
TIMEOUT = 15 * 60
_status: tuple[float, bool] = (0.0, False)


def executable() -> str | None:
    found = shutil.which("codex")
    if found:
        return found
    for folder in (Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path.home() / ".local" / "bin"):
        if (folder / "codex").is_file():
            return str(folder / "codex")
    return None


def env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in API_ENV}


def logged_in() -> bool:
    """Codex est installé et connecté (relu au plus toutes les 30 s : la question revient à chaque affichage)."""
    global _status
    at, value = _status
    if time.time() - at < 30:
        return value
    exe, value = executable(), False
    if exe:
        try:
            out = subprocess.run([exe, "login", "status"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", env=env(), timeout=20)
            value = out.returncode == 0 and "logged in" in (out.stdout + out.stderr).lower()
        except (OSError, subprocess.TimeoutExpired):
            value = False
    _status = (time.time(), value)
    return value


def _need() -> str:
    exe = executable()
    if not exe:
        raise RuntimeError("Codex est introuvable : installe-le (npm install -g @openai/codex) puis relance le studio.")
    return exe


# --- Connexion du compte ChatGPT depuis l'interface (voir core/login.py) -----------------

_browser_login = BrowserLogin(lambda: [_need(), "login"], lambda: env())
login_start, login_cancel, login_state = _browser_login.start, _browser_login.cancel, _browser_login.state


def account() -> dict:
    """L'état du compte, relu sans attendre : c'est la page Réglages qui le demande."""
    global _status
    _status = (0.0, False)
    return {"installed": executable() is not None, "loggedIn": logged_in(), **login_state()}


def logout() -> None:
    global _status
    login_cancel()
    out = subprocess.run([_need(), "logout"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env(), timeout=30)
    _status = (0.0, False)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[-300:] or "déconnexion impossible")


def generate_image(prompt: str, images: list[Path], cwd: Path, dest_name: str,
                   check_cancel: Callable[[], None]) -> Path:
    """Fait générer une image par Codex dans `cwd` (les `images` jointes, dans l'ordre) et rend son chemin."""
    exe = executable()
    if not exe:
        raise RuntimeError("Codex est introuvable : installe-le puis connecte-toi (codex login).")
    args = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "workspace-write", "-C", str(cwd)]
    for image in images:
        args += ["-i", str(image)]
    # « -- » : la liste d'images de -i s'arrête là, le reste est la demande
    args += ["--", prompt + f"\n\nUse your image generation tool for this (do not draw it with code). "
                            f"Save the final image as {dest_name} in the current directory, then stop."]
    log = cwd / "codex.log"
    with log.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(args, cwd=cwd, env=env(), stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT)
        start = time.time()
        try:
            while proc.poll() is None:
                check_cancel()
                if time.time() - start > TIMEOUT:
                    raise RuntimeError("Codex n'a pas répondu à temps")
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    result = cwd / dest_name
    if not result.is_file() or result.stat().st_size == 0:
        tail = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][-3:]
        raise RuntimeError("Codex n'a pas rendu d'image : " + " / ".join(tail)[-400:])
    return result
