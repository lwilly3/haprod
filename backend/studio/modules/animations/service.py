"""
Projets d'animation : a partir d'un transcript, Claude cree des slides animees
qu'on affine ensuite a la main ou en lui parlant.

Une slide est une composition HyperFrames (HTML + timeline GSAP en pause) que Claude
ecrit lui-meme dans le dossier du projet ; l'interface la previsualise dans une iframe
en pilotant sa timeline. Le dossier du projet est la source de verite des slides :

  transcript.txt       le transcript timecode
  style.css            la charte commune (copiee du kit)
  exemples/            deux compositions de reference (copiees du kit)
  slides.json          le plan : [{id, start, end, title, kind, idea, why, discarded}]
  slides/<id>.html     une composition par slide (temps 0 = debut de la slide)
  .history/<n>/        etats precedents de slides.json + slides/ + captions.json, pour annuler

Projet cree depuis un short (module shorts) : la video montee est copiee dans le
projet, avec ses sous-titres mot a mot :

  video.mp4            le short monte (temps 0 = debut du short)
  captions.json        les sous-titres, que Claude peut retoucher (voir captions.py)
  captions/           leur composition, regeneree depuis captions.json
  index.html, renders/ le rendu final (HyperFrames)

Un projet = un job. Chaque message de l'utilisateur remet le job en file : le worker
lance un tour de `claude -p` dans le dossier, en reprenant la session precedente.
L'API ne touche aux fichiers que lorsque Claude ne travaille pas.

payload : name, transcript_job, media, project_dir, model (+ video, duration, short)
state   : settings, messages, session_id, auth, model, usage, activity
"""
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

from ...config import DATA_DIR
from ...core import jobs
from ..settings.service import language_name
from ..transcript import cues as transcript_cues
from . import captions, kit

MODULE = "animations"
KIND = "chat"
# "render" est deja pris par le montage des shorts : les types de job sont globaux au worker
RENDER_KIND = "export"
RENDERS_DIR = "renders"
PROJECTS_DIR = DATA_DIR / "animations"
TRANSCRIPT_FILE = "transcript.txt"
PLAN_FILE = "slides.json"
SLIDES_DIR = "slides"
HISTORY_DIR = ".history"
HISTORY_MAX = 30
VIDEO_EXTENSIONS = (".mov", ".mp4", ".mkv", ".webm", ".m4v", ".avi", ".mts", ".mxf")
VIDEO_FILE = "video.mp4"
SHORT_REQUEST = ("Mets en valeur les mots clés dans captions.json et ajoute quelques emojis bien choisis. "
                 "N'ajoute une slide que si un passage le justifie vraiment.")

SIZES = {"youtube": (1920, 1080), "short": (1080, 1920)}
FORMATS = {
    "youtube": "Vidéo YouTube classique, 1920×1080, face caméra. Le visage est en général au "
               "centre : place les compositions sur un côté (tiers gauche ou droit) ou en bas, "
               "et garde le centre libre. Une slide dure en général de 4 à 12 s.",
    "short": "Short vertical, 1080×1920, rythme rapide. Le visage occupe le centre et les "
             "sous-titres le tiers bas : place les compositions dans le tiers haut. Textes très "
             "courts et gros (lisibles sur un téléphone), slides de 2 à 6 s.",
}
DENSITIES = {
    "sobre": "Sobre : seulement les moments forts, environ une slide par minute et demie.",
    "equilibre": "Équilibrée : environ une slide toutes les 30 à 45 secondes, quand c'est justifié.",
    "dense": "Dense : environ une slide toutes les 15 à 20 secondes ; la vidéo est très rythmée.",
}
DEFAULT_SETTINGS = {"format": "youtube", "density": "equilibre", "context": ""}
DEFAULT_REQUEST = "Crée les slides de cette vidéo."

_TIMING = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_SLIDE_ID = re.compile(r"s\d+")


def captions_prompt() -> str:
    return f"""

# Sous-titres ({captions.JSON_FILE})
La vidéo a des sous-titres mot à mot façon Submagic : de gros mots qui apparaissent par petits groupes, le mot prononcé mis en valeur. Ils sont décrits dans {captions.JSON_FILE} :
  {{"style": "pop", "position": "bas", "groups": [{{"emoji": "", "words": [{{"text": "Clause", "start": 0.12, "end": 0.48, "key": false}}]}}]}}
- Tu peux y corriger un mot mal transcrit (sans toucher à ses timecodes), regrouper ou séparer des groupes (3 mots au plus, ~15 caractères), mettre "key": true sur les mots clés (un ou deux par phrase au plus : chiffres, noms, mots forts) et ajouter un "emoji" à un groupe quand il illustre vraiment le propos (un toutes les 4 à 8 secondes au plus).
- Ne modifie jamais start/end, ne change pas style ni position (l'utilisateur les choisit).
- Ne touche pas à {captions.HTML_FILE} : il est régénéré depuis {captions.JSON_FILE}.
- Les sous-titres occupent la zone "position" : place les slides ailleurs."""


def system_prompt(settings: dict, has_captions: bool = False) -> str:
    fmt = settings.get("format", "youtube")
    width, height = SIZES[fmt]
    context = settings.get("context", "").strip()
    return f"""\
Tu es le motion designer d'un créateur de vidéos. À partir du transcript timecodé d'une \
vidéo, tu conçois et tu codes des slides : des animations incrustées à l'image pendant que \
la personne parle. Ensuite, tu les affines avec lui. Vise la qualité d'un motion designer \
professionnel, pas celle d'un générateur de sous-titres.

# À quoi sert une slide
- APPUYER un propos : le mot, le chiffre ou la phrase clé apparaît au moment précis où il \
est prononcé, pour qu'il reste en tête ;
- ILLUSTRER un concept : rendre visible ce que la voix explique quand une image le fait \
comprendre plus vite qu'une phrase.

Une slide n'est PAS une pastille de texte. Demande-toi à chaque fois quelle forme visuelle \
porte l'idée : arbre de décision, schéma de flux, axe chronologique, avant/après qui se \
transforme, graphique qui se construit, compteur qui défile, jauge, liste qui se coche, \
pile de blocs, carte mentale, comparaison en colonnes, citation qui se compose mot à mot… \
Le texte seul est réservé aux phrases-chocs, et même là, il doit bouger avec intention.

Le mouvement raconte : les éléments se construisent au rythme de la voix (chaque étape au \
mot où elle est dite), une slide peut avoir plusieurs états et passer de l'un à l'autre \
(transition interne : le contenu sort, le suivant arrive, un repère avance) quand le propos \
évolue, et la fin conclut (un chemin s'allume, un chiffre pulse, un élément se coche).

# Choisir les moments
- Cherche : chiffres marquants, dualités et oppositions, énumérations, processus en étapes, \
définitions, phrases-chocs qui résument l'idée, changements de partie.
- Évite : digressions, anecdotes, passages où l'émotion du visage compte plus que \
l'information, slides qui se chevauchent dans le temps.
- Si l'utilisateur cite un passage qu'il veut absolument mettre en valeur, c'est la priorité.
- Calage : la slide démarre quand l'idée commence à être dite (jamais avant) et reste 2 à \
3 s après la dernière étape pour laisser le temps de lire.
- Le texte à l'écran est réécrit pour être lu d'un coup d'œil, jamais la phrase entière du \
transcript. Corrige les erreurs de transcription (noms propres, marques, termes techniques).

# Contexte
- Format : {FORMATS[fmt]}
- Densité : {DENSITIES[settings.get("density", "equilibre")]}
{f"- La vidéo, selon son auteur : {context}" if context else ""}
- Le transcript est dans {TRANSCRIPT_FILE}, une ligne par phrase : [début → fin] texte.

# Fichiers du projet (dossier courant)
- {PLAN_FILE} : le plan, la liste de toutes les slides, triée par début :
  [{{"id": "s1", "start": 83.4, "end": 91.0, "title": "nom court", "kind": "arbre de \
décision", "idea": "ce que montre l'animation et comment elle bouge", "why": "pourquoi ce \
moment", "discarded": false}}]
  Temps en secondes absolues dans la vidéo. Nouvelle slide : un id jamais utilisé (s + numéro).
- {SLIDES_DIR}/<id>.html : la composition de chaque slide.
- style.css : la charte commune (couleurs, typos, .card, .kicker, .title, .big, .node…). \
Ne la modifie pas : ajoute tes styles dans un <style> propre à la slide.
- exemples/ : les animations type du kit, chacune décrite par son commentaire d'en-tête (ce \
qu'elle montre, quand s'en servir). Avant ta première slide, lis exemple-arbre.html et \
exemple-chronologie.html en entier (le contrat technique et le niveau attendu), puis l'en-tête \
des autres : reprends celle qui colle à une idée.

# Contrat d'une composition ({SLIDES_DIR}/<id>.html)
- Charge ../style.css et GSAP (https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js).
- Racine : <div id="stage" class="{fmt}" data-composition-id="<id>" \
data-duration="<end - start>" data-hero="<instant où la slide est la plus complète>">, \
{width}×{height} px, fond transparent (la vidéo est dessous).
- Une seule timeline : `const tl = gsap.timeline({{ paused: true }})`, enregistrée dans \
`window.__timelines["<id>"] = tl`, construite de façon synchrone. Jamais tl.play(), pas de \
setTimeout, de Date.now(), de Math.random(), de repeat infini.
- Temps 0 = début de la slide. Cale chaque étape sur le transcript : (instant du mot) − start.
- Apparitions sûres au seek : gsap.set(el, {{autoAlpha: 0}}) une fois au départ, puis \
tl.to(el, {{autoAlpha: 1}}) + un fromTo pour le mouvement. Jamais set(opacity: 1) + \
from(opacity: 0).
- Anime transform et opacity (x, y, scale, rotation, autoAlpha), pas width/height/top/left. \
Pour un trait qui se dessine : SVG avec pathLength="1", stroke-dasharray: 1, et \
strokeDashoffset de 1 à 0.
- Eases : power1-4, back, expo, sine, circ (.in/.out/.inOut). Entrées en .out, sorties en .in.
- Sortie dans les 0,4 dernières secondes. Garde 80 px de marge avec les bords du cadre.

# Comment tu travailles
- Premier tour, dans cet ordre :
  1. lis {TRANSCRIPT_FILE} et les exemples de exemples/ (voir plus haut) ;
  2. écris tout de suite {PLAN_FILE} : choisis les moments et décris chaque idée en une ou \
deux phrases, sans concevoir le détail (l'interface affiche les slides dès que le plan existe) ;
  3. puis, slide par slide dans l'ordre, conçois la composition et écris-la aussitôt, avant de \
passer à la suivante. Ne prépare pas toutes les compositions de tête avant d'écrire.
- Ensuite, chaque message indique la portée de la demande. Pour une slide précise, ne \
touche qu'à son fichier (et à son entrée dans {PLAN_FILE} si son timing ou son nom change).
- L'utilisateur modifie aussi le plan à la main (timing, slides écartées avec \
"discarded": true) : relis {PLAN_FILE} avant de le modifier et respecte ses choix ; ne \
repropose pas une slide écartée sauf demande explicite.
- Ne crée aucun fichier en dehors de {PLAN_FILE} et {SLIDES_DIR}/{f" (et ne modifie que {captions.JSON_FILE} en plus)" if has_captions else ""}.
- Ta réponse finale : en {language_name()}, 2 à 5 phrases, ce que tu as fait et pourquoi.{captions_prompt() if has_captions else ""}"""


# --- Transcript --------------------------------------------------------------

def _seconds(h: str, m: str, s: str, frac: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


def parse_subtitles(text: str) -> list[dict] | None:
    """Cues d'un .srt / .vtt ; None si le texte n'a aucun timecode."""
    found, current = [], None
    for line in text.splitlines():
        line = line.strip()
        timing = _TIMING.search(line)
        if timing:
            g = timing.groups()
            current = {"start": _seconds(*g[:4]), "end": _seconds(*g[4:]), "text": ""}
            found.append(current)
        elif not line:
            current = None
        elif current is not None:
            current["text"] = f"{current['text']} {line}".strip()
    return found or None


def _tc(sec: float) -> str:
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:04.1f}"


def format_transcript(cues: list[dict]) -> str:
    return "\n".join(f"[{_tc(c['start'])} → {_tc(c['end'])}] {c['text']}" for c in cues) + "\n"


def from_transcript_job(job_id: str) -> tuple[str, str, list[str]]:
    """(nom, transcript formate, medias) d'un job du module transcription."""
    from ..transcript import service as transcript

    job = jobs.get(job_id)
    if job is None or job.module != transcript.MODULE or job.status != "done":
        raise ValueError("transcript introuvable ou pas encore termine")
    built = transcript_cues.build_cues(transcript_cues.load_segments(job.state["segments"]), "line")
    return transcript.name(job), format_transcript(built), job.payload["sources"]


def from_file(filename: str, text: str) -> tuple[str, str, list[str]]:
    """Un .srt/.vtt fourni a la main ; un .txt sans timecodes est garde tel quel."""
    parsed = parse_subtitles(text)
    return filename, format_transcript(parsed) if parsed else text.strip() + "\n", []


def media_parts(job: jobs.Job) -> list[dict]:
    """Les videos source, pour afficher les slides par-dessus dans l'apercu."""
    from ..transcript import service as transcript

    if job.payload.get("video"):
        return [{"url": f"/api/animations/jobs/{job.id}/files/{job.payload['video']}",
                 "start": 0.0, "duration": job.payload["duration"]}]
    tid = job.payload.get("transcript_job")
    source = jobs.get(tid) if tid else None
    if source is None or source.module != transcript.MODULE:
        return []
    parts = source.state.get("parts") or []
    return [{"url": f"/api/transcript/jobs/{tid}/media?part={i}", "start": p["start"],
             "duration": p["duration"]}
            for i, p in enumerate(parts)
            if Path(p["name"]).suffix.lower() in VIDEO_EXTENSIONS]


# --- Slides (fichiers du projet) ---------------------------------------------

def project_dir(job: jobs.Job) -> Path:
    return Path(job.payload["project_dir"])


def _number(value, default: float) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def clean_slide(raw: dict) -> dict | None:
    """Une entree du plan exploitable, quoi que Claude ait ecrit ; None si sans id."""
    sid = str(raw.get("id") or "")
    if not _SLIDE_ID.fullmatch(sid):
        return None
    start = _number(raw.get("start"), 0.0)
    return {"id": sid, "start": start, "end": max(_number(raw.get("end"), start + 5), start + 0.5),
            "title": str(raw.get("title") or sid), "kind": str(raw.get("kind") or ""),
            "idea": str(raw.get("idea") or ""), "why": str(raw.get("why") or ""),
            "discarded": bool(raw.get("discarded"))}


def load_plan(directory: Path) -> list[dict]:
    try:
        data = json.loads((directory / PLAN_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        # en cours d'ecriture par Claude, ou pas encore cree
        return []
    if not isinstance(data, list):
        data = data.get("slides", []) if isinstance(data, dict) else []
    slides = [s for s in (clean_slide(d) for d in data if isinstance(d, dict)) if s]
    return sorted(slides, key=lambda s: (s["start"], s["id"]))


def save_plan(directory: Path, slides: list[dict]) -> None:
    slides = sorted(slides, key=lambda s: (s["start"], s["id"]))
    (directory / PLAN_FILE).write_text(json.dumps(slides, ensure_ascii=False, indent=2), encoding="utf-8")


def slide_file(directory: Path, slide_id: str) -> Path:
    return directory / SLIDES_DIR / f"{slide_id}.html"


def slides_with_files(job: jobs.Job) -> list[dict]:
    """Le plan, avec pour chaque slide l'url de sa composition si Claude l'a deja ecrite."""
    directory = project_dir(job)
    slides = []
    for s in load_plan(directory):
        path = slide_file(directory, s["id"])
        # la date de modification force l'iframe a recharger une slide reecrite
        url = (f"/api/animations/jobs/{job.id}/files/{SLIDES_DIR}/{s['id']}.html?v={int(path.stat().st_mtime * 1000)}"
               if path.is_file() else None)
        slides.append({**s, "url": url})
    return slides


def snapshot(directory: Path) -> None:
    """Avant chaque changement : de quoi revenir en arriere (plan + compositions)."""
    history = directory / HISTORY_DIR
    target = history / f"{time.time_ns()}"
    target.mkdir(parents=True)
    if (directory / PLAN_FILE).is_file():
        shutil.copy2(directory / PLAN_FILE, target / PLAN_FILE)
    if (directory / SLIDES_DIR).is_dir():
        shutil.copytree(directory / SLIDES_DIR, target / SLIDES_DIR)
    if (directory / captions.JSON_FILE).is_file():
        shutil.copy2(directory / captions.JSON_FILE, target / captions.JSON_FILE)
    for old in sorted(history.iterdir())[:-HISTORY_MAX]:
        shutil.rmtree(old, ignore_errors=True)


def _snapshots(directory: Path) -> list[Path]:
    history = directory / HISTORY_DIR
    return sorted(history.iterdir()) if history.is_dir() else []


def drop_last_snapshot(directory: Path) -> None:
    snapshots = _snapshots(directory)
    if snapshots:
        shutil.rmtree(snapshots[-1])


def plan_text(directory: Path) -> str | None:
    """Le plan et les sous-titres : ce que Claude a pu changer en dehors des compositions."""
    texts = [(directory / name).read_text(encoding="utf-8")
             for name in (PLAN_FILE, captions.JSON_FILE) if (directory / name).is_file()]
    return "\n".join(texts) if texts else None


def can_undo(directory: Path) -> bool:
    return bool(_snapshots(directory))


def undo(directory: Path) -> None:
    latest = _snapshots(directory)[-1]
    for name in (PLAN_FILE, SLIDES_DIR, captions.JSON_FILE):
        # un projet sans sous-titres n'en a dans aucun etat : on ne touche a rien
        if name == captions.JSON_FILE and not (latest / name).exists():
            continue
        current = directory / name
        if current.is_dir():
            shutil.rmtree(current)
        elif current.exists():
            current.unlink()
        saved = latest / name
        if saved.is_dir():
            shutil.copytree(saved, current)
        elif saved.is_file():
            shutil.copy2(saved, current)
    shutil.rmtree(latest)


def changed_since(directory: Path, before: float) -> int:
    """Nombre de compositions ecrites pendant un tour de Claude."""
    folder = directory / SLIDES_DIR
    return sum(1 for p in folder.glob("*.html") if p.stat().st_mtime >= before) if folder.is_dir() else 0


# --- Projets -----------------------------------------------------------------

def message(role: str, text: str, slide: str | None = None) -> dict:
    return {"role": role, "text": text, "at": time.time(), "slide": slide}


def create_job(name: str, transcript: str, media: list[str], request: str, settings: dict,
               transcript_job: str | None, model: str | None, extra: dict | None = None,
               prepare: Callable[[Path], None] | None = None) -> jobs.Job:
    """`prepare` complete le dossier avant que le job parte en file (le worker peut le prendre aussitot)."""
    job_id = uuid.uuid4().hex[:10]
    directory = PROJECTS_DIR / job_id
    (directory / SLIDES_DIR).mkdir(parents=True, exist_ok=True)
    (directory / TRANSCRIPT_FILE).write_text(transcript, encoding="utf-8")
    kit.install(directory)
    if prepare:
        prepare(directory)
    payload = {"name": name, "transcript_job": transcript_job, "media": media,
               "project_dir": str(directory), "model": model, **(extra or {})}
    state = {"settings": {**DEFAULT_SETTINGS, **settings},
             "messages": [message("user", request.strip() or DEFAULT_REQUEST)], "session_id": None}
    return jobs.create(MODULE, KIND, payload, state, job_id=job_id)


def create_from_short(selection_id: str, short_id: str, model: str | None) -> jobs.Job:
    """Un projet au format short : le montage, son transcript et ses sous-titres mot a mot."""
    from ..shorts import service as shorts

    selection = jobs.get(selection_id)
    if selection is None or selection.kind != shorts.KIND:
        raise ValueError("sélection de shorts introuvable")
    short = next((s for s in selection.state["shorts"] if s["id"] == short_id), None)
    if short is None:
        raise ValueError("short introuvable")
    render = shorts.short_render(selection, short)
    if render is None:
        raise ValueError("ce short n'est pas encore monté")
    # ce montage a deja son projet : on le rouvre plutot que d'en creer un second
    existing = short_projects(selection_id).get((short_id, render.id))
    if existing:
        return jobs.get(existing)
    words, lines = shorts.retimed(selection, short)
    duration = round(sum(b - a for a, b in render.payload["clips"]), 3)
    fmt = "short" if render.payload["format"] == "vertical" else "youtube"
    def prepare(directory: Path) -> None:
        shutil.copy2(shorts.render_file(render), directory / VIDEO_FILE)
        captions.create(directory, words)

    return create_job(short["title"], format_transcript(lines), [], SHORT_REQUEST,
                     {"format": fmt, "density": "sobre",
                      "context": f"Short « {short['title']} ». {short['hook']}".strip()},
                     None, model,
                     extra={"video": VIDEO_FILE, "duration": duration,
                            "short": {"selection": selection_id, "short": short_id, "render": render.id}},
                      prepare=prepare)


def short_projects(selection_id: str) -> dict[tuple[str, str | None], str]:
    """Projets crees depuis les shorts d'une selection : (short, montage) -> projet."""
    found = {}
    for j in jobs.list_jobs(MODULE):
        origin = j.payload.get("short") if j.kind == KIND else None
        if origin and origin["selection"] == selection_id:
            found[(origin["short"], origin.get("render"))] = j.id
    return found


def origin(job: jobs.Job) -> dict | None:
    """D'ou vient le projet, pour y revenir : un short monte ou un transcript."""
    short = job.payload.get("short")
    if short:
        selection = jobs.get(short["selection"])
        found = next((s for s in selection.state["shorts"] if s["id"] == short["short"]), None) if selection else None
        return {"kind": "short", "selection": short["selection"], "short": short["short"],
                "title": found["title"] if found else job.payload["name"],
                "transcript_job": selection.payload["transcript_job"] if selection else None}
    tid = job.payload.get("transcript_job")
    return {"kind": "transcript", "transcript_job": tid} if tid and jobs.get(tid) else None


# --- Rendu final ---------------------------------------------------------------

def size(job: jobs.Job) -> tuple[int, int]:
    return SIZES[{**DEFAULT_SETTINGS, **job.state.get("settings", {})}["format"]]


def captions_info(job: jobs.Job) -> dict | None:
    directory = project_dir(job)
    if not job.payload.get("video") or not captions.build(directory, job.payload["duration"], size(job)):
        return None
    data = captions.load(directory) or {}
    stamp = int((directory / captions.HTML_FILE).stat().st_mtime * 1000)
    return {"url": f"/api/animations/jobs/{job.id}/files/{captions.HTML_FILE}?v={stamp}",
            "style": data.get("style", captions.DEFAULT["style"]),
            "position": data.get("position", captions.DEFAULT["position"])}


def set_captions(job: jobs.Job, style: str | None, position: str | None) -> None:
    directory = project_dir(job)
    data = captions.load(directory)
    if data is None:
        raise ValueError("ce projet n'a pas de sous-titres")
    if style is not None:
        if style not in captions.STYLES:
            raise ValueError(f"style inconnu : {style}")
        data["style"] = style
    if position is not None:
        if position not in captions.POSITIONS:
            raise ValueError(f"position inconnue : {position}")
        data["position"] = position
    snapshot(directory)
    (directory / captions.JSON_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def last_render(job: jobs.Job) -> jobs.Job | None:
    found = [j for j in jobs.list_jobs(MODULE) if j.kind == RENDER_KIND and j.payload["project"] == job.id]
    return found[-1] if found else None


def render_output(render: jobs.Job) -> Path:
    return Path(render.payload["project_dir"]) / RENDERS_DIR / f"{render.id}.mp4"


def enqueue_render(job: jobs.Job) -> jobs.Job:
    if not job.payload.get("video"):
        raise ValueError("le rendu vidéo n'est branché que pour les projets créés depuis un short")
    return jobs.create(MODULE, RENDER_KIND, {"project": job.id, "name": job.payload["name"],
                                             "project_dir": job.payload["project_dir"]}, {})


def render_summary(render: jobs.Job | None) -> dict | None:
    if render is None:
        return None
    ready = render.status == "done" and render_output(render).is_file()
    return {"id": render.id, "status": render.status, "progress": render.progress, "error": render.error,
            "stage": render.state.get("stage"),
            "url": f"/api/animations/renders/{render.id}/file" if ready else None}


def save_state(job: jobs.Job) -> None:
    jobs.update(job.id, state=job.state)


def send(job: jobs.Job, text: str, slide: str | None) -> None:
    """Nouveau message : le job repart en file pour un tour de plus."""
    job.state["messages"].append(message("user", text.strip(), slide))
    jobs.update(job.id, state=job.state, status="queued", cancel_requested=False,
                error=None, finished_at=None)


def remove_project(job: jobs.Job) -> None:
    for render in jobs.list_jobs(MODULE):
        if render.kind == RENDER_KIND and render.payload["project"] == job.id:
            jobs.delete(render.id)
    shutil.rmtree(project_dir(job), ignore_errors=True)


def turn_prompt(job: jobs.Job, first: bool) -> str:
    """Ce que Claude recoit a chaque tour : la demande et sa portee."""
    request = job.state["messages"][-1]
    slides = load_plan(project_dir(job))
    target = next((s for s in slides if s["id"] == request.get("slide")), None)
    if target:
        scope = (f"la slide {target['id']} « {target['title']} » uniquement "
                 f"({SLIDES_DIR}/{target['id']}.html)")
    else:
        scope = "toute la vidéo"
    if not first:
        intro = ""
    elif (project_dir(job) / captions.JSON_FILE).is_file():
        intro = (f"Lis {TRANSCRIPT_FILE} et {captions.JSON_FILE}. Avant d'écrire une slide, lis "
                 f"les exemples de exemples/ ; s'il n'y a "
                 f"aucune slide à faire, écris {PLAN_FILE} avec une liste vide.\n\n")
    else:
        intro = (f"Lis {TRANSCRIPT_FILE} et les exemples de exemples/, "
                 f"écris {PLAN_FILE}, puis les compositions une à une.\n\n")
    return f"{intro}Portée de la demande : {scope}.\n\nDemande : {request['text']}"


def summary(job: jobs.Job) -> dict:
    s = job.state
    return {"id": job.id, "name": job.payload["name"], "status": job.status, "error": job.error,
            "created_at": job.created_at, "slides": len(load_plan(project_dir(job))),
            "transcript_job": job.payload.get("transcript_job"), "from_short": bool(job.payload.get("short")),
            "format": {**DEFAULT_SETTINGS, **s.get("settings", {})}["format"]}


def detail(job: jobs.Job) -> dict:
    s = job.state
    directory = project_dir(job)
    return {**summary(job), "messages": s["messages"], "slides": slides_with_files(job),
            "settings": {**DEFAULT_SETTINGS, **s.get("settings", {})},
            "can_undo": can_undo(directory), "media": media_parts(job),
            "project_dir": str(directory), "activity": s.get("activity"),
            "model": s.get("model") or job.payload["model"], "auth": s.get("auth"),
            "usage": s.get("usage"), "captions": captions_info(job),
            "can_render": bool(job.payload.get("video")), "render": render_summary(last_render(job)),
            "origin": origin(job)}
