"""
Connexion d'un compte par le navigateur, lancée depuis l'interface : la commande du CLI (Claude Code,
Codex) ouvre la page de connexion du service, puis attend que l'utilisateur y valide. On garde le
process pour suivre, annuler, ou lui passer le code que la page affiche quand le retour automatique
ne se fait pas. Tout vit dans le process de l'API ; c'est le CLI qui range la session, pas le studio.
"""
import re
import subprocess
import threading
from typing import Callable

_URL = re.compile(r"https?://\S+")


class BrowserLogin:
    def __init__(self, command: Callable[[], list[str]], env: Callable[[], dict[str, str]]):
        self._command, self._env = command, env
        self._proc: subprocess.Popen | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            self._lines.clear()
            proc = subprocess.Popen(self._command(), env=self._env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            self._proc = proc
            lines = self._lines

            def read() -> None:
                for line in proc.stdout:
                    lines.append(line.strip())

            threading.Thread(target=read, daemon=True).start()

    def code(self, code: str) -> None:
        """Le code affiché par la page, quand le navigateur ne revient pas tout seul."""
        if not self.running():
            raise RuntimeError("aucune connexion en cours")
        try:
            self._proc.stdin.write(code.strip() + "\n")
            self._proc.stdin.flush()
        except OSError as e:
            raise RuntimeError("la connexion s'est arrêtée") from e

    def cancel(self) -> None:
        with self._lock:
            if self.running():
                self._proc.kill()
                self._proc.wait()
            self._proc = None
            self._lines.clear()

    def state(self) -> dict:
        """`url` : la page à ouvrir à la main si le navigateur ne s'est pas ouvert."""
        found = _URL.search("\n".join(self._lines))
        failed = self._proc is not None and self._proc.poll() not in (None, 0)
        last = next((line for line in reversed(self._lines) if line), "connexion interrompue")
        return {"connecting": self.running(), "url": found.group(0) if found and self.running() else None,
                "error": last if failed else None}
