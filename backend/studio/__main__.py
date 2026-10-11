"""
Lanceur du studio (depuis studio/backend, avec le .venv du repo) :

  python -m studio dev      API (rechargement a chaud) + worker + Vite (HMR)  -> http://localhost:4400
  python -m studio          interface buildee servie par l'API + worker       -> http://localhost:4400
  python -m studio api      l'API seule (--reload pour le rechargement)
  python -m studio worker   le worker seul (--reload pour le relancer quand ses fichiers changent)

L'interface ecoute aussi sur le reseau local (http://<ip-du-pc>:4400, affichee au lancement).
STUDIO_NO_BROWSER=1 evite d'ouvrir le navigateur.
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from .config import API_PORT, PACKAGE_DIR, STUDIO_DIR, UI_PORT, WEB_DIST

BACKEND_DIR = PACKAGE_DIR.parent
WEB_DIR = STUDIO_DIR / "web"
# fichiers que seule l'API charge : les modifier ne doit pas relancer le worker
# (ce qui couperait une transcription en cours)
API_ONLY = ("api.py", "app.py", "__main__.py")


def run_api(port: int, reload: bool, host: str) -> None:
    import uvicorn
    # timeout_graceful_shutdown : la video du derush garde sa requete (media d'un rush) ouverte,
    # et sans delai l'arret attendrait sa fermeture indefiniment (rechargement bloque)
    uvicorn.run("studio.app:app", host=host, port=port, reload=reload,
                reload_dirs=[str(PACKAGE_DIR)] if reload else None, timeout_graceful_shutdown=2)


def _worker_filter(change, path: str) -> bool:
    return path.endswith(".py") and not path.endswith(API_ONLY)


def run_worker(reload: bool) -> None:
    from .core import worker
    if not reload:
        worker.main()
        return
    import watchfiles
    print("Worker : relance auto quand son code change (les jobs en cours repartent de zero).")
    watchfiles.run_process(PACKAGE_DIR, target=worker.main, watch_filter=_worker_filter)


def _spawn(args: list[str] | str, cwd: Path, shell: bool = False) -> subprocess.Popen:
    # PYTHONUNBUFFERED : sinon les logs du worker n'arrivent qu'a la fermeture
    env = {**os.environ, "PYTHONPATH": str(BACKEND_DIR), "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(args, cwd=cwd, env=env, shell=shell)


def _package_manager() -> str:
    for pm in ("pnpm", "npm"):
        if shutil.which(pm):
            return pm
    sys.exit("Node.js introuvable (ni pnpm ni npm dans le PATH) : il faut Node pour l'interface.")


def _lan_ip() -> str | None:
    # connect() en UDP n'envoie rien : il sert juste a trouver l'interface de sortie
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return None


def _open_browser(https: bool = False) -> None:
    scheme = "https" if https else "http"
    ip = _lan_ip()
    if ip:
        print(f"Studio sur le reseau local : {scheme}://{ip}:{UI_PORT}")
    if not os.environ.get("STUDIO_NO_BROWSER"):
        webbrowser.open(f"{scheme}://localhost:{UI_PORT}")


def _supervise(procs: list[subprocess.Popen]) -> None:
    """Attend Ctrl+C (ou la mort d'un des process) puis arrete tout le monde."""
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                if sys.platform == "win32":
                    # /T : emporte aussi les enfants (node lance par pnpm, process de reload...)
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                                   capture_output=True)
                else:
                    p.send_signal(signal.SIGINT)


def dev() -> None:
    py = sys.executable
    pm = _package_manager()
    if not (WEB_DIR / "node_modules").is_dir():
        subprocess.run(f"{pm} install", cwd=WEB_DIR, shell=True, check=True)
    procs = [
        _spawn([py, "-m", "studio", "api", "--reload", "--port", str(API_PORT)], BACKEND_DIR),
        _spawn([py, "-m", "studio", "worker", "--reload"], BACKEND_DIR),
        _spawn(f"{pm} run dev", WEB_DIR, shell=True),
    ]
    time.sleep(2)
    # Vite passe en HTTPS s'il trouve le certificat mkcert (voir vite.config.ts)
    _open_browser(https=(WEB_DIR / ".certs" / "cert.pem").is_file())
    _supervise(procs)


def start() -> None:
    if not WEB_DIST.is_dir():
        pm = _package_manager()
        print("Interface pas encore buildee : build en cours…")
        if not (WEB_DIR / "node_modules").is_dir():
            subprocess.run(f"{pm} install", cwd=WEB_DIR, shell=True, check=True)
        subprocess.run(f"{pm} run build", cwd=WEB_DIR, shell=True, check=True)
    py = sys.executable
    procs = [
        # 0.0.0.0 : joignable depuis le reseau local (en dev c'est Vite qui s'en charge)
        _spawn([py, "-m", "studio", "api", "--port", str(UI_PORT), "--host", "0.0.0.0"], BACKEND_DIR),
        _spawn([py, "-m", "studio", "worker"], BACKEND_DIR),
    ]
    time.sleep(1.5)
    _open_browser()
    _supervise(procs)


def main(argv: list[str]) -> None:
    command = argv[0] if argv else "start"
    reload = "--reload" in argv
    if command == "dev":
        dev()
    elif command == "start":
        start()
    elif command == "api":
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else API_PORT
        host = argv[argv.index("--host") + 1] if "--host" in argv else "127.0.0.1"
        run_api(port, reload, host)
    elif command == "worker":
        run_worker(reload)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
