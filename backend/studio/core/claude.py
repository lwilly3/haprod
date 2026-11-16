"""
Claude Code en mode headless (`claude -p`) : c'est l'abonnement connecte dans
Claude Code qui est utilise, pas des credits API.

Le prompt passe par stdin (la ligne de commande Windows est limitee a 32k
caracteres, trop peu pour un transcript) et la reponse arrive en stream-json :
un evenement JSON par ligne.
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

from ..config import DATA_DIR
from .login import BrowserLogin

# par defaut : lire et ecrire les fichiers du projet ; pas de shell ni de reseau
TOOLS = "Read,Write,Edit,Glob,Grep"
# reflexion moderee : en "high", un premier tour pouvait reflechir 15 min avant d'ecrire quoi que ce soit
EFFORT = "medium"
# sinon le CLI les prefere a l'abonnement (et facture l'API)
API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# variables posees quand le studio est lui-meme lance depuis Claude Code
NESTED_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def executable() -> str:
    found = shutil.which("claude")
    if found:
        return found
    # l'installeur natif (~/.local/bin), puis Homebrew sous macOS
    name = "claude.exe" if os.name == "nt" else "claude"
    for folder in (Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        if (folder / name).is_file():
            return str(folder / name)
    raise RuntimeError("Claude Code est introuvable : installe-le puis connecte-toi (claude auth login).")


def env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in API_ENV + NESTED_ENV}


def auth_status() -> dict:
    """Compte connecte dans Claude Code (claude.ai = abonnement)."""
    try:
        out = subprocess.run([executable(), "auth", "status"], capture_output=True, text=True,
                             encoding="utf-8", env=env(), timeout=20).stdout
        status = json.loads(out)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"loggedIn": False, "error": str(e)}
    return {k: status.get(k) for k in ("loggedIn", "authMethod", "email")}


# --- Consommation --------------------------------------------------------------------
# Claude Code donne, à la fin de chaque tour, les jetons utilisés et leur prix au tarif de l'API.
# Avec un abonnement rien n'est facturé : ce prix sert d'unité pour comparer les étapes et les modèles.

USAGE_FILE = DATA_DIR / "claude-usage.jsonl"


def record_usage(event: dict, label: str) -> None:
    """Ajoute une ligne au journal pour l'événement "result" d'un tour (`label` : l'étape)."""
    usage = event.get("usage") or {}
    line = {"at": round(time.time()), "step": label, "models": sorted(event.get("modelUsage") or {}),
            "cost_usd": event.get("total_cost_usd"), "seconds": round((event.get("duration_ms") or 0) / 1000),
            "turns": event.get("num_turns"), "input": usage.get("input_tokens"),
            "cache_write": usage.get("cache_creation_input_tokens"),
            "cache_read": usage.get("cache_read_input_tokens"), "output": usage.get("output_tokens")}
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass  # un journal qui ne s'écrit pas ne doit pas faire échouer l'étape


# --- Connexion du compte depuis l'interface (voir core/login.py) -------------------------

_browser_login = BrowserLogin(lambda: [executable(), "auth", "login", "--claudeai"], lambda: env())
login_start, login_code, login_cancel, login_state = (_browser_login.start, _browser_login.code,
                                                      _browser_login.cancel, _browser_login.state)


def logout() -> None:
    login_cancel()
    out = subprocess.run([executable(), "auth", "logout"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env(), timeout=30)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[-300:] or "déconnexion impossible")


def stream(prompt: str, cwd: Path, system_prompt: str, session_id: str | None,
           model: str | None, check_cancel: Callable[[], None], tools: str = TOOLS,
           json_schema: dict | None = None, allowed_tools: str | None = None,
           mcp_config: Path | None = None) -> Iterator[dict]:
    """Lance un tour de conversation et rend les evenements au fil de l'eau.

    `check_cancel` est appele regulierement, meme quand Claude reflechit sans
    rien ecrire : s'il leve une exception, le process est tue.
    Avec `json_schema`, la reponse validee arrive dans `structured_output` de l'evenement "result".
    `allowed_tools` : outils autorises sans demander, en plus des ecritures (ex. "WebSearch,WebFetch") ;
    en headless, un outil qui demanderait une permission est refuse.
    `mcp_config` : fichier {"mcpServers": ...}, les seuls MCP de la session (ses outils restent a
    autoriser dans `allowed_tools`, ex. "mcp__ytwatch").
    """
    args = [executable(), "-p", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--tools", tools,
            # ecritures acceptees sans demander, mais seulement dans le dossier du projet (cwd)
            "--permission-mode", "acceptEdits",
            # ni CLAUDE.md, ni hooks, ni MCP, ni skills de l'utilisateur : une session propre
            "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
            "--effort", EFFORT, "--append-system-prompt", system_prompt]
    if session_id:
        args += ["--resume", session_id]
    if model:
        args += ["--model", model]
    if json_schema:
        args += ["--json-schema", json.dumps(json_schema)]
    if allowed_tools:
        args += ["--allowedTools", allowed_tools]
    if mcp_config:
        args += ["--mcp-config", str(mcp_config)]
    proc = subprocess.Popen(args, cwd=cwd, env=env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines: queue.Queue[str | None] = queue.Queue()

    def read():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    proc.stdin.write(prompt)
    proc.stdin.close()
    # ce qui n'est pas du JSON (erreur au demarrage...) sert de message d'erreur
    garbage: list[str] = []
    try:
        while True:
            check_cancel()
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if line.strip():
                    garbage.append(line.strip())
        if proc.wait() != 0 and garbage:
            raise RuntimeError("\n".join(garbage[-5:]))
    finally:
        if proc.poll() is None:
            proc.kill()
