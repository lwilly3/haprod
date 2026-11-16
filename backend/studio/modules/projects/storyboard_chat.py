"""
Le chat du storyboard : on discute avec Daryl des beats, sur toute la vidéo ou à un moment précis
(le timecode choisi, et l'image de la vidéo à ce moment, qu'il regarde). Il répond par des changements
structurés (beats ajoutés, retouchés, retirés) : un beat ajouté est placé par ses mots exacts, comme à la
génération, jamais par un timecode ; un beat introuvable est signalé, pas deviné.

L'image est tirée de la vidéo source (ffmpeg), au temps de la source qui correspond au temps de la
timeline : on y voit le cadrage et la personne, pas les B-roll ni les motions.
"""
import copy
import re
import subprocess
from pathlib import Path

from ...core import jobs
from ...core.system import tool
from ...core.tasks import TaskContext
from ..settings.service import language_name
from . import autoderush, montage, service, storyboard

KIND = "project_storyboard_chat"
FRAMES_DIR = "frames"

_BEAT = copy.deepcopy(storyboard.SCHEMA["properties"]["beats"]["items"])
_BEAT["properties"].pop("plan")
_BEAT["required"] = [k for k in _BEAT["required"] if k != "plan"]

SCHEMA = {
    "type": "object",
    "required": ["reply", "add", "update", "remove"],
    "properties": {
        "reply": {"type": "string", "description": "Ta réponse à l'auteur, 1 à 4 phrases."},
        "add": {"type": "array", "items": _BEAT, "description": "Les beats que tu ajoutes (vide si aucun)."},
        "update": {
            "type": "array",
            "description": "Les beats existants que tu retouches : `id`, et seulement les champs qui changent.",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string", "enum": storyboard.TYPES},
                    "show": {"type": "string"},
                    "kind": {"type": "string", "enum": storyboard.KINDS},
                    "place": {"type": "string", "enum": storyboard.PLACES},
                    "anim": {"type": "string"},
                    "sfx": {"type": "string"},
                    "enter_fx": _BEAT["properties"]["enter_fx"],
                    "exit_fx": _BEAT["properties"]["exit_fx"],
                    "why": {"type": "string"},
                    "motion": _BEAT["properties"]["motion"],
                    "zoom": _BEAT["properties"]["zoom"],
                    "media": _BEAT["properties"]["media"],
                    "search": _BEAT["properties"]["search"],
                    "start": _BEAT["properties"]["start"],
                },
            },
        },
        "remove": {"type": "array", "items": {"type": "string"}, "description": "Les ids des beats à retirer."},
    },
}

SYSTEM = """\
Tu es Daryl, le motion designer d'un créateur de vidéos YouTube éducatives (chaîne en {lang}). Vous \
discutez du storyboard de l'habillage de sa vidéo longue : la liste des « beats », les moments où \
l'image change, et ce qu'on y voit. Rien n'est composé ici : tu proposes, il valide.

Quatre types de beats (`type`) :
- motion : un visuel animé au-dessus de la vidéo, à sa `place` ;
- zoom : un recadrage sur lui pour appuyer une phrase forte (`zoom` : `style` smooth = montée et descente \
douces, cut = saut net pour un aparté face caméra ou une chute, slow = poussée lente sur toute la durée ; \
`scale` 1.12 léger à 1.35 serré, 1.05 à 1.15 en slow ; `x` / `y` pour garder son visage au centre du \
cadre), 2 à 6 s (slow : 5 à 15 s) ; jamais sous un visuel plein écran ;
- broll : un plan de coupe, 3 à 8 s. `media` = le src exact d'un média visuel de la liste (une vidéo \
passe en plein écran ; une image est animée en plein écran ou sur un côté, comme un portrait, selon \
`place`) ; si aucun ne convient, `media` vide et `search` = la recherche à faire pour le trouver ; pour une vidéo, \
`start` = la seconde du média où le plan commence, s'il désigne un passage précis ;
- transition : un carton animé plein écran au changement de partie ; la vidéo s'arrête dessous \
(image noire, voix coupée) environ 3 secondes, le temps de lire le titre, puis la voix reprend sur \
`anchor`. `anchor` = les premiers mots de la PREMIÈRE PHRASE de la nouvelle partie, `show` = ce \
qu'elle affiche. Ce qui précède doit être une pensée finie : une chute ou une courte conclusion qui \
suit (« Et ça, c'est pas bon. ») appartient encore à la partie précédente, la transition vient après \
elle ; jamais au milieu d'une phrase, ni entre une question et sa réponse.

L'auteur pose aussi des beats à la main sur la timeline (marqués « posé par l'auteur ») : un passage \
et sa consigne, souvent courte (« une animation ici », « un B-roll »). Quand il te le demande, précise-la \
par un `update` (`type`, `show`…) ; ses bornes restent les siennes. Ne les retire pas sans qu'il le demande.

{relevance}

Il peut te demander d'ajouter des beats, d'en retoucher, d'en retirer, ou simplement ton avis. Une \
demande peut porter sur un moment précis : le timecode et, s'il l'a jointe, l'image de la vidéo à ce \
moment (lis-la avec Read : regarde où est son visage, ce qui est libre dans le cadre, avant de choisir \
une place). Tiens-t'en à ce qu'il demande : ne refais pas le reste du storyboard.

Pour un motion, la question : « qu'est-ce qu'on MONTRE pendant qu'il dit ça ? », jamais « quel texte on \
affiche ». Un chiffre → un compteur qui se construit ; un processus → un schéma qui s'assemble ; une \
comparaison → A / B ; des dates → une chronologie ; une énumération de choses → ces choses montrées une à \
une, pas leurs noms écrits ; une énumération d'idées → des éléments qui se cochent. Une \
idée par beat, 4 à 10 secondes en général. Pas de chevauchement entre deux beats qui occupent l'écran \
(motion, broll, transition), ni entre deux zooms.

Un beat ajouté : `type` ; `line` = la ligne de l'ancre ; `anchor` = les mots exacts, recopiés à \
l'identique, sur lesquels le beat commence ; `until` = les derniers mots exacts qu'il couvre. Jamais de timecode. \
`anim` : le nom exact d'une animation du kit, ou vide ; `sfx` : le src exact d'un son, ou vide. \
Réponds en {lang}, sans markdown."""


def job_id(pid: str) -> str:
    return f"{pid}-storyboard-chat"


def source_time(timeline: dict, t: float) -> float | None:
    """Le temps dans la vidéo source qui correspond au temps `t` de la timeline."""
    acc = 0.0
    for c in timeline["aroll"]:
        length = c["out"] - c["in"]
        if t < acc + length:
            # dans un clip inséré d'un autre média, pas d'image de la source
            return None if c.get("src") else c["in"] + max(0.0, t - acc)
        acc += length
    return None


def grab_frame(pid: str, t: float) -> str | None:
    """L'image de la vidéo au temps `t` de la timeline, en JPEG dans montage/frames/ ; rend son chemin
    relatif au projet (None si la source ou le temps manquent)."""
    source = montage._source(service.load(pid))
    at = source_time(montage.load(pid), t) if source else None
    if at is None:
        return None
    folder = montage.root(pid) / FRAMES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"frame-{round(t * 1000)}.jpg"
    if not out.is_file():
        proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", source["path"],
                               "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "3", str(out)],
                              capture_output=True, timeout=60)
        if proc.returncode or not out.is_file():
            return None
    return out.relative_to(service.project_dir(pid)).as_posix()


def _beat_line(b: dict, composed: dict) -> str:
    state = "" if b.get("on", True) else " (décoché)"
    if b.get("origin") == "user":
        state += " (posé par l'auteur)"
    if b["id"] in composed:
        state += f" (déjà animé : {composed[b['id']]})"
    kind = b.get("type", "motion")
    if kind == "zoom":
        z = b.get("zoom") or {}
        what = f"zoom {z.get('style', 'smooth')} ×{z.get('scale', 1):.2f} (x {z.get('x', 0):+.2f}, y {z.get('y', 0):+.2f})"
    elif kind == "broll":
        what = f"broll · {b['place']} · " + (f"média {b['src']}" + (f" dès {b['start']:g} s" if b.get("start") else "")
                                             if b.get("src") else f"à trouver : {b.get('search') or '?'}")
    elif kind == "transition":
        what = "transition"
    else:
        images = storyboard.motion_media(b)
        what = (f"motion · {b['kind']} · {b['place']}{' · base ' + b['anim'] if b.get('anim') else ''}"
                + (f" · médias de l'auteur : {', '.join(images)}" if images else ""))
    ends = "".join(f" · {k} {b[k]['fx']}" for k in ("enter", "exit") if b.get(k))
    return (f"- {b['id']}{state} [{storyboard._clock(b['at'])} → {storyboard._clock(b['at'] + b['dur'])}] "
            f"{what}{ends}{' · son ' + b['sfx'] if b.get('sfx') else ''} · il dit « {b['says'][:160]} » · on montre : {b['show']}")


def _visual_line(v: dict) -> str:
    return f"- {v['src']} · {'vidéo' if v['kind'] == 'video' else 'image'}" + (f" · {v['description']}" if v["description"] else "")


def prompt(pid: str, request: dict, first: bool, frame: str | None, sent: list[str] | None = None) -> str:
    """`sent` : les médias déjà listés à Daryl dans cette conversation (None : on ne sait pas, on les relistera)."""
    project = service.load(pid)
    timeline = montage.load(pid)
    board = storyboard.load(pid) or {"beats": []}
    composed = storyboard.composed(timeline)
    parts = []
    if first:
        words = storyboard.timeline_words(project, timeline)
        lines = autoderush.lines_of([{"id": "timeline"}], {"timeline": words})
        anims = storyboard.kit_animations()
        sfx = storyboard.sounds(pid)
        parts += [f"Vidéo : « {project.get('title') or ''} ».", ""]
        if anims:
            parts += ["Les animations du kit (`anim`) :",
                      *(f"- {Path(a['name']).stem} · {a['title']}" + (f" : {a['description']}" if a["description"] else "")
                        for a in anims), ""]
        parts += ["Les sons disponibles (`sfx`) :" if sfx else "Aucun son disponible.",
                  *(f"- {x['src']}" + (f" · {x['description']}" if x["description"] else "") for x in sfx), ""]
        visual = storyboard.visuals(pid)[:storyboard.MAX_VISUALS]
        parts += ["Les médias visuels (`media` d'un broll) :" if visual else "Aucun média visuel : un broll est une suggestion.",
                  *(_visual_line(v) for v in visual), ""]
        chapters = [k for k in timeline["markers"] if k["kind"] == "chapter"]
        if chapters:
            parts += ["Chapitres :", *(f"- {storyboard._clock(k['t'])} {k['text']}" for k in chapters), ""]
    # la structure à chaque tour : courte, et une conversation commencée avant l'a aussi
    parts += storyboard.structure_lines(storyboard.structure(pid, storyboard.timeline_words(project, timeline)))
    if first:
        parts += ["Le transcript de la timeline, une phrase par ligne (numéro, minute:seconde) :", "<transcript>",
                  *(f"L{l['n']} [{storyboard._clock(l['start'])}] {l['text']}" for l in lines), "</transcript>", ""]
    else:
        # les médias ajoutés au projet depuis le début de la conversation
        known = set(sent or [])
        new = [v for v in storyboard.visuals(pid)[:storyboard.MAX_VISUALS] if v["src"] not in known]
        if new:
            parts += ["Les médias visuels disponibles (`media` d'un broll) :" if sent is None
                      else "Médias visuels ajoutés depuis (utilisables aussi en `media`) :",
                      *(_visual_line(v) for v in new), ""]
    parts += ["Le storyboard tel qu'il est maintenant :" if board["beats"] else "Le storyboard est vide.",
              *(_beat_line(b, composed) for b in board["beats"]), ""]
    if request.get("at") is not None:
        t = float(request["at"])
        parts += [f"Moment choisi par l'auteur : {storyboard._clock(t)} ({t:.2f} s de la timeline)."]
        beat = next((b for b in board["beats"] if b["id"] == request.get("beat")), None)
        if beat:
            parts += [f"Il parle du beat {beat['id']}."]
        if frame:
            parts += [f"L'image de la vidéo à ce moment : {frame} (lis-la)."]
        parts += [""]
    parts += [f"Sa demande : {request['text']}"]
    return "\n".join(parts)


def apply(pid: str, output: dict) -> dict:
    """Applique les changements de Daryl au storyboard ; rend ce qui a changé, pour le chat."""
    project = service.load(pid)
    timeline = montage.load(pid)
    words = storyboard.timeline_words(project, timeline)
    lines = autoderush.lines_of([{"id": "timeline"}], {"timeline": words})
    by_n = {l["n"]: l for l in lines}
    total = sum(c["out"] - c["in"] for c in timeline["aroll"])
    board = storyboard.load(pid) or {"density": storyboard.DEFAULT_DENSITY, "note": "", "message": "",
                                     "created": 0, "beats": [], "unresolved": []}
    known = storyboard.refs(pid)
    done = {"added": [], "updated": [], "removed": [], "missing": []}

    gone = set(output.get("remove") or [])
    done["removed"] = [b["id"] for b in board["beats"] if b["id"] in gone]
    board["beats"] = [b for b in board["beats"] if b["id"] not in gone]

    by_id = {b["id"]: b for b in board["beats"]}
    for u in output.get("update") or []:
        b = by_id.get(u.get("id"))
        if not b:
            continue
        storyboard.retype(b, u.get("type"))
        for key in ("show", "why"):
            if isinstance(u.get(key), str) and u[key].strip():
                b[key] = u[key].strip()[:1000]
        if u.get("kind") in storyboard.KINDS:
            b["kind"] = u["kind"]
        if u.get("place") in storyboard.PLACES:
            b["place"] = u["place"]
        if isinstance(u.get("anim"), str):
            b["anim"] = storyboard.resolve_anim(u["anim"], known["anims"])
        if isinstance(u.get("sfx"), str):
            b["sfx"] = storyboard.resolve_sfx(u["sfx"], known["sfx"])
        if b["type"] == "zoom" and isinstance(u.get("zoom"), dict):
            b["zoom"] = storyboard.zoom_of({**(b.get("zoom") or {}), **u["zoom"]})
        if b["type"] == "broll" and isinstance(u.get("media"), str) and u["media"].strip():
            b["src"] = storyboard.resolve_media(u["media"], known["media"])
        if b["type"] == "broll" and isinstance(u.get("search"), str) and u["search"].strip():
            b["search"] = u["search"].strip()[:200]
        if b["type"] == "broll" and "start" in u:
            b["start"] = storyboard.start_of(u["start"])
        for key in ("enter", "exit"):
            if isinstance(u.get(f"{key}_fx"), str):
                b[key] = storyboard.end_of(b["type"], u[f"{key}_fx"])
        if isinstance(u.get("motion"), dict):
            b["motion"] = {k: str(u["motion"].get(k) or b["motion"].get(k) or "").strip() for k in ("enter", "hold", "exit")}
        done["updated"].append(b["id"])

    numbers = [int(x[1:]) for x in [*by_id, *storyboard.composed(timeline)] if re.fullmatch(r"b\d+", x)]
    n = max(numbers, default=0)
    for spec in output.get("add") or []:
        line = by_n.get(spec.get("line"))
        found = storyboard.locate(words, spec.get("anchor", ""), spec.get("until", ""), line["first"]) if line else None
        if not found:
            done["missing"].append(spec.get("anchor", ""))
            continue
        n += 1
        beat = {"id": f"b{n}", **storyboard.make_beat(spec, words, *found, total, known)}
        board["beats"].append(beat)
        done["added"].append(beat["id"])

    board["beats"].sort(key=lambda x: x["at"])
    storyboard.save(pid, board)
    return done


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    state, pid = ctx.state, ctx.payload["project"]
    messages = state["messages"]
    while messages and messages[-1]["role"] == "ai":
        messages.pop()
    request = messages[-1]
    state["activity"] = "lit le storyboard"
    ctx.save(force=True)
    frame = grab_frame(pid, float(request["at"])) if request.get("frame") and request.get("at") is not None else None
    session = state.get("session_id")
    media = [v["src"] for v in storyboard.visuals(pid)[:storyboard.MAX_VISUALS]]
    out = ask(ctx, prompt(pid, request, not session, frame, state.get("media")),
              SYSTEM.format(lang=language_name(), relevance=storyboard.RELEVANCE),
              "Read", None, SCHEMA, session, level="heavy")
    state["media"] = media
    state["session_id"] = out["session_id"]
    output = out["output"] or {}
    changes = apply(pid, output)
    messages.append({"role": "ai", "text": (output.get("reply") or out["text"]).strip(), "changes": changes})
    state["activity"] = None


def view(pid: str) -> dict:
    job = jobs.get(job_id(pid))
    state = job.state if job else {}
    return {"messages": state.get("messages", []), "busy": bool(job and not job.finished),
            "activity": state.get("activity"), "error": job.error if job and job.status == "error" else None}
