"""
Rendu final d'un projet avec HyperFrames : la video, les slides gardees et les
sous-titres, assembles dans une composition racine (index.html) puis rendus en MP4
par le CLI (Chrome headless + ffmpeg).

Le CLI passe par npx, a une version figee : il est telecharge au premier rendu.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ...core.system import MAC_BIN_DIRS, tool
from ..settings.service import language
from . import captions

HYPERFRAMES = "hyperframes@0.8.111"
INDEX_FILE = "index.html"
# mesure sur un short de 1:50 (Ryzen 2700X, GTX 1060) : 3 min 50 en auto (3 workers), 2 min 25 ainsi.
# La capture plafonne vers 2 min quel que soit le nombre de workers ; --gpu encode en NVENC (1 min -> 15 s),
# seulement en MP4 (le MOV est en ProRes)
RENDER_OPTIONS = ["--workers", "12"]
GPU_OPTIONS = ["--gpu"]

_PERCENT = re.compile(r"(\d{1,3})%\s+(.*)")
# les avertissements du CLI quand une sous-composition n'a pas enregistré window.__timelines[id]
_UNREGISTERED = re.compile(r"Sub-composition timelines not registered|still waiting on the failed script")
# et l'erreur de son script (une par worker : dédoublonnée)
_SCRIPT_ERROR = re.compile(r"Composition script failed (.*)|\[Browser:PAGEERROR\] (.*)")
STAGES = {"Capturing": "capture des images", "Encoding": "encodage", "Assembling": "assemblage",
          "Extracting": "lecture de la vidéo", "Compiling": "préparation", "Render complete": "terminé"}


def write_index(directory: Path, video: str, duration: float, size: tuple[int, int],
                slides: list[dict], with_captions: bool, fps: str = "30") -> None:
    """
    La composition racine : chaque slide et les sous-titres y sont des sous-compositions.
    `fps` : la cadence de la video source ("25" ou "30000/1001"), sinon le rendu part a 30 i/s
    et capture des images en double.
    """
    width, height = size
    layers = [f'<video id="video" class="clip" src="{video}" data-start="0" data-duration="{duration:.3f}" '
              f'data-has-audio="true" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"></video>']
    for s in slides:
        length = min(s["end"], duration) - s["start"]
        if length <= 0:
            continue
        layers.append(f'<div id="slide-{s["id"]}" class="layer" data-composition-id="{s["id"]}" '
                      f'data-composition-src="slides/{s["id"]}.html" data-start="{s["start"]:.3f}" '
                      f'data-duration="{length:.3f}" style="z-index:2"></div>')
    if with_captions:
        layers.append(f'<div id="captions" class="layer" data-track-kind="captions" '
                      f'data-composition-id="{captions.COMPOSITION_ID}" '
                      f'data-composition-src="{captions.HTML_FILE}" data-start="0" '
                      f'data-duration="{duration:.3f}" style="z-index:3"></div>')
    body = "\n  ".join(layers)
    (directory / INDEX_FILE).write_text(f"""<!doctype html>
<html lang="{language()}">
<head>
<meta charset="utf-8">
<!-- genere par le studio a chaque rendu -->
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
html, body {{ margin: 0; padding: 0; background: #000; overflow: hidden; }}
/* le rendu n'embarque que les polices ecrites en toutes lettres dans un font-family (la charte
   passe par var(--font)), et toutes les compositions ont un #stage : la police de la charte
   arrive donc par heritage depuis chaque calque */
.layer {{ position: absolute; inset: 0; font-family: "Space Grotesk", "Inter", system-ui, sans-serif; }}
.fonts-charte-mono {{ font-family: "JetBrains Mono"; }}
</style>
</head>
<body>
<div id="root" data-composition-id="root" data-width="{width}" data-height="{height}" data-fps="{fps}" data-duration="{duration:.3f}">
  {body}
</div>
<script>
  // la racine n'anime rien elle-meme, mais doit declarer sa timeline (sinon le rendu l'attend 45 s)
  const tl = gsap.timeline({{ paused: true }});
  tl.set({{}}, {{}}, {json.dumps(round(duration, 3))});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["root"] = tl;
</script>
</body>
</html>
""", encoding="utf-8")


def _npx() -> str:
    # sous Windows, le dossier de Node.js contient aussi "npx" sans extension (un script shell)
    # que shutil.which renvoie en premier : seul npx.cmd se lance
    found = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if found:
        return found
    # le PATH herite n'a pas toujours Node.js (process lance avant son installation...)
    if os.name == "nt":
        candidates = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npx.cmd"]
    else:
        candidates = [Path(folder) / "npx" for folder in MAC_BIN_DIRS]
    for installed in candidates:
        if installed.is_file():
            return str(installed)
    raise RuntimeError("npx est introuvable : installe Node.js pour le rendu vidéo.")


def _kill_tree(proc: subprocess.Popen) -> None:
    # npx -> node -> Chrome : tuer le seul npx laisserait tourner le reste
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    proc.wait()


def render(directory: Path, output: Path, on_progress: Callable[[float, str], None],
           check_cancel: Callable[[], None], extra: list[str] | None = None) -> None:
    """`extra` : options du CLI en plus (ex. ["--format", "mov"] pour un rendu avec transparence)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    npx = _npx()
    # npx.cmd appelle node, et le rendu appelle ffmpeg/ffprobe : leurs dossiers doivent etre dans le PATH
    dirs = [str(Path(npx).parent), str(Path(tool("ffmpeg")).parent)]
    # au-dela de ~4 workers, le tas de node par defaut (4 Go) ne suffit plus
    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "NODE_OPTIONS": "--max-old-space-size=8192",
           "PATH": os.pathsep.join([*dirs, os.environ.get("PATH", "")])}
    proc = subprocess.Popen([npx, "-y", HYPERFRAMES, "render", str(directory), "-o", str(output),
                             *RENDER_OPTIONS, *([] if "--format" in (extra or []) else GPU_OPTIONS),
                             *(extra or [])],
                            cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    tail: list[str] = []
    # une composition dont le script plante n'enregistre pas sa timeline : le CLI rend quand même, image figée
    page_errors: list[str] = []
    unregistered = False
    try:
        # le CLI redessine sa barre avec \r : le mode texte en fait des lignes
        for line in proc.stdout:
            check_cancel()
            line = line.strip()
            if not line:
                continue
            tail = (tail + [line])[-40:]
            failed = _SCRIPT_ERROR.search(line)
            if failed:
                page_errors.append((failed.group(1) or failed.group(2)).strip())
            if _UNREGISTERED.search(line):
                unregistered = True
            found = _PERCENT.search(line)
            if found:
                label = found.group(2)
                stage = next((v for k, v in STAGES.items() if label.startswith(k)), label)
                on_progress(min(int(found.group(1)) / 100, 1.0), stage)
        if proc.wait() != 0 or not output.is_file():
            # les dernieres lignes hors traces techniques : c'est la que le CLI explique l'echec
            errors = [t for t in tail if not t.startswith("[INFO]")] or tail
            raise RuntimeError("le rendu HyperFrames a échoué : " + " | ".join(errors[-5:])[-800:])
        if unregistered:
            output.unlink(missing_ok=True)
            why = " | ".join(dict.fromkeys(page_errors))[-800:] or "aucune erreur de script remontée"
            raise RuntimeError(f"une composition n'a pas enregistré sa timeline (son script a planté ?), "
                               f"le rendu serait figé : {why}")
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
