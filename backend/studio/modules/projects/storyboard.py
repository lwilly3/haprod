"""
Storyboard de l'habillage de la vidéo longue : Daryl propose d'abord une liste de « beats »
(ce qu'on montre, à quel moment), l'utilisateur les valide, et seulement ensuite ils entrent au montage.

Quatre types de beats :
- motion : un visuel animé (HyperFrames) au-dessus de la vidéo, à sa place à l'écran ;
- zoom : un recadrage progressif de l'A-roll (piste zooms), posé tel quel ;
- broll : un plan de coupe. Une vidéo va sur la piste B-roll ; une image est animée comme un motion
  (plein écran ou sur un côté) ; sans média, c'est une suggestion « à trouver » (`search`) ;
- transition : un enchaînement animé plein écran, court, au changement de partie.

L'auteur pose aussi des beats à la main sur la timeline du montage (`origin` "user") : un passage et une consigne
(« une animation ici », « un B-roll à trouver »), qu'il tire sur les mots et fait créer comme les autres.

Méthode reprise d'editing-os (skill design-beats, MOTION_PHILOSOPHY) :
- la question pour chaque passage est « qu'est-ce qu'on montre pendant qu'il dit ça ? », jamais
  « quel texte on affiche » ;
- Claude désigne chaque beat par les mots exacts qui le déclenchent (`anchor`) et les derniers mots
  qu'il couvre (`until`), jamais par un timecode. Les mots sont retrouvés dans le transcript de la
  timeline ; un beat introuvable est signalé, pas deviné ;
- le visuel arrive 0,2 s avant le mot (« Gate 0 » : entre 0,2 s avant et 1,8 s après), sans
  chevauchement, à la densité demandée.

Fichier : montage/storyboard.json
    {"density", "note", "message", "created",
     "beats": [{"id", "type", "at", "dur", "anchor", "until", "says", "show", "kind", "place",
                "motion": {"enter", "hold", "exit"}, "sfx", "ref", "why", "on",
                "zoom": {"scale", "x", "y"},       # zoom
                "src", "search"}]}                 # broll : le média (vide : à trouver), la recherche
`at` / `dur` en secondes de la timeline. Les contrôles (`check`) sont refaits à chaque lecture :
le montage de l'A-roll peut avoir bougé depuis la génération.
"""
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote, unquote

from ...core import jobs
from ...core.tasks import TaskContext
from ..settings.service import language_name
from ..transcript import cues
from . import autoderush, library, media, montage, runtime, service, transitions

KIND = "project_storyboard"
FILE = "storyboard.json"

# écart entre une slide et la suivante, en secondes (bornes basse et haute), par densité
DENSITIES = {"sobre": (75.0, 105.0), "equilibre": (30.0, 45.0), "dense": (15.0, 20.0)}
DEFAULT_DENSITY = "equilibre"
# le visuel arrive un peu avant le mot ; tolérance au contrôle (« Gate 0 » d'editing-os)
LEAD = 0.2
GATE_BEFORE, GATE_AFTER = 0.2, 1.8
# temps laissé après le dernier mot couvert (la sortie)
TAIL = 0.5
# durée d'un beat : bornes, et valeur par défaut quand sa fin est introuvable
MIN_DUR, MAX_DUR, DEFAULT_DUR = 2.5, 15.0, 6.0
# écart minimal entre deux beats ; un beat raccourci pour laisser passer le suivant garde au moins FIT_MIN
SPACING = 0.1
FIT_MIN = 1.5
# un plan du script garde la durée de son passage, jusqu'à cette limite
MAX_SCRIPT_DUR = 60.0
# recherche de l'ancre autour de sa ligne, et de la fin après l'ancre (en mots)
SEARCH_BEFORE, SEARCH_AFTER, UNTIL_SPAN = 20, 200, 80

TYPES = ["motion", "zoom", "broll", "transition"]
# les types qui occupent l'écran (un seul à la fois) ; un zoom recadre l'A-roll en dessous
SCREEN = ("motion", "broll", "transition")
# zoom : grossissement, décalage du centre, durée ; il arrive à peine avant le mot
ZOOM_SCALE = (1.05, 1.5)
ZOOM_DEFAULT = 1.25
ZOOM_DUR = (1.5, 8.0)
ZOOM_LEAD = 0.1
# transition : courte, l'écran couvert au milieu, juste avant les premiers mots de la nouvelle partie
TRANSITION_DUR = 1.2
TRANSITION_LEAD = 0.9
# un beat posé à la main : sa durée par défaut, et sa durée minimale
HAND_DUR = 3.0
MIN_SPAN = 0.3
# B-roll : bornes de durée ; médias listés à Daryl, au plus
BROLL_DUR = (2.0, 10.0)
MAX_VISUALS = 300
KINDS = ["counter", "diagram", "comparison", "timeline", "list", "logo", "screenshot", "quote", "map", "other"]
PLACES = ["full", "left", "right", "top", "lower"]
# pour Daryl : ce que chaque place veut dire à l'écran
PLACE_TEXT = {"full": "plein écran", "left": "tiers gauche de l'image", "right": "tiers droit de l'image",
              "top": "bandeau en haut de l'image", "lower": "bandeau en bas de l'image"}
# images de la vidéo montrées à Daryl pour qu'il voie où est la personne (en fraction de la durée)
FRAME_AT = (0.2, 0.5, 0.8)

SCHEMA = {
    "type": "object",
    "required": ["beats", "message"],
    "properties": {
        "message": {"type": "string",
                    "description": "Deux ou trois phrases pour l'auteur : le parti pris du storyboard, ce qu'il doit regarder."},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["plan", "type", "line", "anchor", "until", "show", "why"],
                "properties": {
                    "plan": {"type": "string",
                             "description": "L'id du plan du script repris par ce beat (P1, P2…), vide pour un beat "
                                            "que tu ajoutes."},
                    "type": {"type": "string", "enum": TYPES},
                    "line": {"type": "integer", "description": "Le numéro de la ligne (Lnn) où se trouve l'ancre."},
                    "anchor": {"type": "string",
                               "description": "Les 2 à 5 mots exacts, recopiés du transcript, au moment desquels le "
                                              "visuel apparaît."},
                    "until": {"type": "string",
                              "description": "Les 2 à 5 derniers mots exacts couverts par le beat, recopiés du "
                                             "transcript (le visuel sort juste après)."},
                    "show": {"type": "string",
                             "description": "Ce qu'on voit à l'écran et comment ça se construit, concret (éléments, "
                                            "chiffres, ordre d'apparition)."},
                    "kind": {"type": "string", "enum": KINDS},
                    "anim": {"type": "string",
                             "description": "Le nom exact de l'animation du kit qui sert de base à ce beat (liste dans "
                                            "le message), ou vide pour une animation sur mesure."},
                    "place": {"type": "string", "enum": PLACES,
                              "description": "full : plein écran ; left / right : le tiers gauche / droit de "
                                             "l'image, du côté libre (pas sur le visage) ; top / lower : un bandeau "
                                             "en haut / en bas de l'image."},
                    "motion": {
                        "type": "object",
                        "required": ["enter", "hold", "exit"],
                        "properties": {
                            "enter": {"type": "string", "description": "L'entrée, en quelques mots."},
                            "hold": {"type": "string", "description": "Ce qui bouge pendant qu'il parle (sur les mots)."},
                            "exit": {"type": "string", "description": "La sortie, en quelques mots."},
                        },
                    },
                    "sfx": {"type": "string", "description": "Le `src` exact d'un des sons disponibles listés dans "
                                                             "le message, pour l'entrée, ou vide."},
                    "enter_fx": {"type": "string", "enum": ["", *transitions.IDS],
                                 "description": "Motion et broll : la transition d'entrée au montage (id de la "
                                                "bibliothèque), ou vide pour une coupe franche."},
                    "exit_fx": {"type": "string", "enum": ["", *transitions.IDS],
                                "description": "Motion et broll : la transition de sortie, ou vide."},
                    "zoom": {
                        "type": "object",
                        "description": "Zoom seulement : le grossissement et le décalage du centre.",
                        "required": ["scale", "x", "y"],
                        "properties": {
                            "scale": {"type": "number", "description": "1.12 (léger) à 1.35 (serré)."},
                            "x": {"type": "number", "description": "Décalage horizontal du centre, en fraction de "
                                                                   "l'image (−0.3 à 0.3, positif : vers la droite)."},
                            "y": {"type": "number", "description": "Décalage vertical (positif : vers le bas)."},
                        },
                    },
                    "media": {"type": "string", "description": "B-roll seulement : le `src` exact d'un des médias "
                                                               "visuels listés dans le message, ou vide si aucun ne convient."},
                    "search": {"type": "string", "description": "B-roll sans média : la recherche à faire pour le "
                                                                "trouver (mots-clés concrets)."},
                    "start": {"type": "number", "description": "B-roll vidéo seulement : la seconde du média où le "
                                                               "plan commence (0 : son début)."},
                    "why": {"type": "string", "description": "Pourquoi un visuel ici, en une phrase."},
                },
            },
        },
    },
}



# --- Les sons : ceux de la bibliothèque et du projet, jamais une liste figée ----------------------

def sounds(pid: str) -> list[dict]:
    """Les sons utilisables par un beat : {src, name, description}, comme les liste contexte.md."""
    return [{"src": m["src"], "name": Path(m["name"]).stem, "description": m.get("description", "")}
            for m in montage.available(pid) if m["category"] == "sfx"]


def kit_animations() -> list[dict]:
    """Les animations du kit, que le storyboard propose comme base d'un beat (copiées dans chaque projet)."""
    return library.animations()


def resolve_anim(value: str, names: list[str]) -> str:
    """Le nom d'une animation du kit (« exemple-arbre » ou « exemple-arbre.html »), sinon sur mesure."""
    value = Path((value or "").strip()).stem
    return f"{value}.html" if f"{value}.html" in names else ""


def resolve_sfx(value: str, srcs: list[str]) -> str:
    """Le `src` d'un son disponible : tel quel, sinon par son nom (« whoosh », d'un ancien storyboard ou
    d'une réponse approximative), sinon aucun son."""
    value = (value or "").strip()
    if not value or value in srcs:
        return value
    stem = Path(value).stem.lower()
    return next((s for s in srcs if Path(s).stem.lower() == stem), "")


# --- Les médias visuels : ce qu'un beat B-roll peut montrer --------------------------------------

def media_kind(src: str) -> str | None:
    """« video », « image », ou None pour un fichier qu'on ne pose pas à l'écran."""
    ext = Path(src or "").suffix.lower()
    if ext in library.VIDEO_EXT:
        return "video"
    if ext in library.IMAGE_EXT and ext != ".psd":
        return "image"
    return None


def visuals(pid: str) -> list[dict]:
    """Les vidéos et images utilisables par un B-roll : celles du projet (assets, fichiers ajoutés), puis
    celles de la bibliothèque. Chacune {src, name, kind, where, description, url} ; `src` comme la timeline."""
    base = service.project_dir(pid)
    enc = lambda rel: "/".join(quote(part) for part in rel.split("/"))  # noqa: E731
    out, seen = [], set()

    def add(path: Path, src: str, where: str, url: str, description: str = "") -> None:
        kind = media_kind(path.name)
        if kind and src not in seen:
            seen.add(src)
            out.append({"src": src, "name": path.name, "kind": kind, "where": where, "description": description,
                        "url": url})

    folders = [base / service.ASSETS_DIR / c for c in library.VISUAL_CATEGORIES]
    folders += [base / service.ASSETS_DIR, base / service.RESOURCES_DIR]
    for folder in folders:
        for path in library._files(folder):
            rel = path.relative_to(base).as_posix()
            add(path, rel, "projet", f"/api/projects/{pid}/files/{enc(rel)}")
    described = library.descriptions()
    for category in library.VISUAL_CATEGORIES:
        for path in library._files(library.LIBRARY_DIR / category):
            rel = f"{category}/{path.name}"
            add(path, f"library/{rel}", "bibliothèque", f"/api/projects/library/file/{enc(rel)}", described.get(rel, ""))
    return out


def resolve_media(value: str, srcs: list[str]) -> str:
    """Le `src` d'un média visuel : tel quel, sinon par son nom de fichier, sinon aucun (à trouver)."""
    value = (value or "").replace("\\", "/").strip()
    if not value or value in srcs:
        return value
    name = value.split("/")[-1].lower()
    return next((s for s in srcs if s.split("/")[-1].lower() == name), "")


def media_of_plan(pid: str, url: str) -> str:
    """Le `src` d'un média attaché à un plan du script (son adresse dans l'interface)."""
    url = unquote(url or "")
    own, common = f"/api/projects/{pid}/files/", "/api/projects/library/file/"
    if url.startswith(own):
        return url[len(own):]
    if url.startswith(common):
        return "library/" + url[len(common):]
    return ""


def needs_anim(beat: dict) -> bool:
    """Le beat passe par une composition HyperFrames écrite par Daryl (sinon il est posé tel quel)."""
    kind = beat.get("type", "motion")
    return kind in ("motion", "transition") or (kind == "broll" and media_kind(beat.get("src", "")) == "image")


def zoom_of(raw) -> dict:
    """Un zoom sûr : grossissement borné, centre qui garde le cadre dans l'image."""
    raw = raw if isinstance(raw, dict) else {}

    def num(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    scale = max(ZOOM_SCALE[0], min(num("scale", ZOOM_DEFAULT), ZOOM_SCALE[1]))
    room = (scale - 1) / 2
    return {"scale": round(scale, 3), "x": round(max(-room, min(num("x", 0.0), room)), 3),
            "y": round(max(-room, min(num("y", 0.0), room)), 3)}


SYSTEM = """\
Tu es le motion designer d'un créateur de vidéos YouTube éducatives (chaîne en {lang}). Tu prépares \
le storyboard de l'habillage de sa vidéo longue : les moments où l'image change (un visuel animé, un \
zoom, un plan de coupe, une transition), et ce qu'on y voit. Tu ne composes rien : l'auteur valide le \
storyboard, le montage se fait ensuite. Tout est dans le message ; tu ne lis que les images de la vidéo qu'il cite.

Les types de beats (`type`) — ne propose que ceux que le message demande :
- motion : un visuel animé posé au-dessus de la vidéo (détails plus bas). C'est le seul type que \
compte la densité demandée.
- zoom : un recadrage progressif sur lui, pour appuyer une phrase forte, une chute, une confidence, \
une émotion. `zoom` : `scale` de 1.12 (léger) à 1.35 (serré), `x` / `y` pour garder son visage au \
centre du cadre (regarde les images de la vidéo). 2 à 6 secondes, environ un toutes les 20 à 40 \
secondes, jamais pendant un motion plein écran, un B-roll ou une transition (il peut accompagner un \
motion sur le côté ou en bandeau). `show` : ce qu'il appuie, en quelques mots.
- broll : un plan de coupe qui montre ce dont il parle (un lieu, un objet, une personne, une action, \
un site) à la place de son visage, 3 à 8 secondes. `media` = le src exact d'un média visuel de la \
liste quand l'un d'eux convient (d'après son nom et sa description) : une vidéo passe en plein écran ; \
une image est mise en scène, en plein écran (`place` full) ou sur un côté comme un portrait (`left` / \
`right`) : dans `motion`, des gestes nets calés sur ses mots (ce qui s'isole, se surligne, se détache, \
au mot qui le nomme), pas « fondu + lent zoom ». Sinon `media` vide, `search` = la recherche à faire pour le trouver (mots-clés concrets, en \
{lang}) et `show` = le plan idéal ; l'auteur le trouvera ou le tournera.
- transition : un enchaînement animé plein écran, court, au changement de partie ou de chapitre, \
une par changement au plus. `anchor` = les premiers mots de la nouvelle partie ; `show` = ce qu'elle \
affiche (le titre de la partie, en quelques mots) ; `until` = les mêmes mots que `anchor`.
`kind`, `anim` et `motion` ne servent qu'aux motions (et `place` aux motions et aux images) ; `sfx` \
aux motions, B-roll et transitions.

L'auteur a déjà prévu des plans dans son script (les « plans du script », P1, P2…) : ce sont les \
beats de départ. Chacun devient un beat (`plan` = son id), au passage indiqué : une animation → un \
motion ; une image, une capture, un B-roll → un broll, avec le média qu'il y a attaché s'il y en a \
un. Reprends son idée telle quelle : tu la précises (éléments, ordre d'apparition, mouvement, place, \
son), tu ne la remplaces pas. Quand sa note n'est qu'un pense-bête (« prévoir une animation »), c'est \
à toi de proposer le contenu. Ensuite seulement, tu ajoutes tes propres beats (`plan` vide) sur les \
passages que ses plans ne couvrent pas.

Pour les motions, la seule question, pour chaque passage : « qu'est-ce qu'on MONTRE pendant qu'il dit ça ? », jamais \
« quel texte on affiche ». Grille de traduction :
- un chiffre, une proportion → un compteur ou une jauge qui se construit sous les yeux ;
- un processus, une cause et ses effets → un schéma qui s'assemble étape par étape, sur les mots ;
- une comparaison, un avant / après → deux colonnes A / B qui se remplissent ;
- des dates, une histoire → une chronologie qui avance ;
- un outil, un site, une marque citée → son logo ou une capture ;
- une énumération → des éléments qui apparaissent et se cochent un à un ;
- une citation forte, une définition → la phrase, en grand, mot à mot ;
- un lieu → une carte.
Interdits : la carte-titre statique, le texte qui répète ce qu'il dit, le visuel décoratif sans idée.

L'auteur a un kit d'animations type, à sa charte (liste dans le message, avec ce que montre chacune \
et quand s'en servir). Pour chaque beat, si une animation du kit porte l'idée, indique-la dans \
`anim` et décris dans `show` comment tu l'adaptes (textes, chiffres, nombre d'éléments). Ne force \
pas : une idée que rien dans le kit ne porte reste sur mesure (`anim` vide). Varie : la même \
animation plusieurs fois de suite lasse.

Règles :
- une idée par beat ; le beat couvre le passage qui la développe (en général 4 à 10 secondes) ;
- choisis les passages qui gagnent vraiment à être vus : chiffres, mécanismes, comparaisons, \
noms propres, moments forts. Laisse respirer : une vidéo longue est d'abord un face-caméra ;
- place : "left" ou "right" (le tiers de l'image du côté libre : regarde les images de la vidéo \
citées dans le message pour voir où est la personne, jamais sur son visage), "top" ou "lower" (un \
bandeau en haut ou en bas) par défaut ; "full" (plein écran) seulement pour les moments clés ou les \
schémas qui ont besoin de place ;
- le mouvement suit la parole : chaque élément apparaît sur le mot qui le nomme ; pas d'oscillation \
décorative ; une courte immobilité avant le moment fort ;
- pas de chevauchement entre deux beats qui occupent l'écran (motion, broll, transition), ni entre \
deux zooms ; aucun beat sur un passage déjà couvert dans la timeline (listé dans le message) ;
- `enter_fx` / `exit_fx` (motion et broll) : la transition du montage à l'entrée et à la sortie, prise \
dans la bibliothèque (liste dans le message), ou vide pour une coupe franche. Un B-roll plein écran \
gagne souvent une entrée (balayage, poussée, iris) ; un motion anime déjà son entrée et sa sortie, \
laisse-les vides sauf raison précise. Varie et donne du sens : le sens d'une poussée ou d'un \
balayage suit le propos (on avance → vers la gauche), un passage par le noir marque une rupture, un \
iris isole un détail ; jamais le même fondu partout, et la coupe franche reste souvent la meilleure.

{relevance}

Chaque beat : `line` = la ligne de l'ancre ; `anchor` = les mots exacts, recopiés à l'identique, \
sur lesquels le visuel apparaît ; `until` = les derniers mots exacts qu'il couvre. Jamais de \
timecode. Rends les beats dans l'ordre du transcript. `show`, `motion`, `why` et `message` en {lang}."""


# --- Le transcript de la timeline, mot à mot ---------------------------------------------------

def timeline_words(project: dict, timeline: dict) -> list[cues.Word]:
    """Les mots de la vidéo source replacés sur la timeline (les passages coupés disparaissent)."""
    source = runtime.source_transcript(project) or {}
    job = jobs.get(source.get("id") or "")
    if not job or job.status != "done":
        return []
    words = [w for seg in cues.load_segments(job.state.get("segments", [])) for w in seg.words if w.text.strip()]
    out, cursor = [], 0.0
    for c in timeline["aroll"]:
        if c.get("src"):
            # un clip inséré d'un autre média : pas de mot de la source
            cursor += c["out"] - c["in"]
            continue
        for w in words:
            if c["in"] <= w.start < c["out"]:
                out.append(cues.Word(round(cursor + w.start - c["in"], 3), round(cursor + min(w.end, c["out"]) - c["in"], 3),
                                     w.text))
        cursor += c["out"] - c["in"]
    return out


# --- Les plans du script ----------------------------------------------------------------------

# les plans du script qui deviennent des beats, et ceux qui occupent déjà l'écran
MOTION_PLANS = ("Animation", "Texte à l'écran")
COVER_PLANS = ("Image", "Écran", "B-roll", "Plan de coupe", "Insert")
# repérage d'un passage du script dans ce qui a été dit : vote de triplets de mots
GRAM = 3


def _grams(toks: list[str]) -> dict[tuple, list[int]]:
    out: dict[tuple, list[int]] = {}
    for i in range(len(toks) - GRAM + 1):
        out.setdefault(tuple(toks[i:i + GRAM]), []).append(i)
    return out


def find_passage(passage: str, toks: list[str], owner: list[int], grams: dict[tuple, list[int]]) -> tuple[int, int] | None:
    """Le premier et le dernier mot de la timeline où le passage du script a été dit, ou None.
    L'auteur s'écarte du texte au tournage : chaque triplet de mots du passage retrouvé vote pour un
    début ; le début le mieux soutenu l'emporte, et la fin est le dernier triplet qui s'y accorde."""
    p = autoderush._tokens(passage)
    if len(p) < GRAM:
        return None
    hits: list[tuple[int, int]] = []  # (position dans le passage, position dans la timeline)
    for k in range(len(p) - GRAM + 1):
        for pos in grams.get(tuple(p[k:k + GRAM]), []):
            hits.append((k, pos))
    if not hits:
        return None
    votes: dict[int, int] = {}
    for k, pos in hits:
        votes[pos - k] = votes.get(pos - k, 0) + 1
    slack = 3 + len(p) // 4

    def support(s: int) -> int:
        return sum(n for start, n in votes.items() if abs(start - s) <= slack)

    best = max(votes, key=support)
    if support(best) < max(1, min(3, round((len(p) - GRAM + 1) * 0.25))):
        return None
    near = [pos for k, pos in hits if abs(pos - k - best) <= slack + len(p) // 2]
    return owner[min(near)], owner[min(len(toks) - 1, max(near) + GRAM - 1)]


def script_plans(pid: str, words: list[cues.Word]) -> list[dict]:
    """Les plans du script qui comptent pour le motion design, replacés sur la timeline :
    {id, ref (P1…), type, note, passage, motion (à animer, sinon il occupe déjà l'écran), at, end}
    (`at` None : passage introuvable, coupé au montage ou dit tout autrement)."""
    from . import script

    data = script._read(pid)
    order = [b["id"] for b in data["blocks"]]
    md = {b["id"]: b["md"] for b in data["blocks"]}
    toks, owner = autoderush._token_index(words)
    grams = _grams(toks)
    out = []
    for plan in data["plans"]:
        if plan.get("type") not in MOTION_PLANS + COVER_PLANS or plan.get("block") not in md:
            continue
        passage = (plan.get("q") or "").strip()
        if not passage:
            i = order.index(plan["block"])
            j = order.index(plan["end"]) if plan.get("end") in md else i
            passage = " ".join(script._plain(md[b]) for b in order[i:max(i, j) + 1])
        found = find_passage(passage, toks, owner, grams) if words else None
        out.append({"id": plan["id"], "type": plan["type"], "note": (plan.get("note") or "").strip(),
                    "passage": " ".join(passage.split()), "motion": plan["type"] in MOTION_PLANS,
                    # les médias qu'il y a attachés (src de la timeline)
                    "media": [s for s in (media_of_plan(pid, m.get("url", "")) for m in plan.get("media") or [])
                              if media_kind(s)],
                    "first": found[0] if found else None, "last": found[1] if found else None,
                    "at": round(words[found[0]].start, 2) if found else None,
                    "end": round(words[found[1]].end, 2) if found else None})
    out.sort(key=lambda p: (p["at"] is None, p["at"] or 0))
    for n, p in enumerate(out, 1):
        p["ref"] = f"P{n}"
    return out


# --- La pertinence : ce qui vaut un beat, commun au storyboard et au chat --------------------------

RELEVANCE = """\
Pertinence, à vérifier pour chaque beat avant de le proposer :
- le visuel illustre ce qu'il VEUT DIRE, pas ses mots : le nom propre cité dans la phrase n'est souvent pas \
la bonne chose à montrer. Derrière une affirmation, le vrai document (le post, l'article, le chiffre \
sourcé) est le candidat par défaut ; une idée abstraite appelle un motion ;
- un beat apporte ce que la parole n'apporte pas : la preuve (la vraie capture, le vrai document), la \
structure (un schéma, une comparaison), l'échelle (un chiffre qui se construit), un lieu, une personne. \
Jamais ses mots recopiés à l'écran, ni la liste de ce qu'il vient de dire, ni une carte-titre décorative ;
- un média n'entre que si ce qu'il MONTRE correspond à ce qu'il dit à ce moment-là (d'après sa \
description, ou ce que tu en vois) ; un nom de fichier qui partage un mot avec le passage ne suffit pas. \
Les médias de la liste sont une réserve, pas une liste à placer : n'essaie jamais de tous les utiliser ;
- un sommaire, un titre de partie ou une transition reprend les parties de la structure de la vidéo \
(donnée dans le message), avec leurs titres ; jamais un découpage inventé à partir d'une phrase. Sans \
structure donnée, pas de sommaire ;
- on reste sur lui quand il montre lui-même quelque chose à la caméra (« regardez », « vous m'avez \
reconnu ? ») ou quand son visage porte le moment (émotion, chute, adresse directe au spectateur) ;
- un doute sur le sens d'un passage ou sur le contenu d'un média : pas de beat (dans le chat, \
pose la question). Pas de visuel vaut mieux qu'un visuel à côté : la densité demandée est un ordre de \
grandeur, ne l'atteins pas avec des beats faibles."""


def structure(pid: str, words: list[cues.Word]) -> list[dict]:
    """Les parties du script (titres ## et ###), replacées sur la timeline : {level, title, at} (`at` None :
    début introuvable, coupé au montage ou dit tout autrement)."""
    from . import script

    md = service.read_doc(pid, service.SCRIPT_FILE)
    toks, owner = autoderush._token_index(words)
    grams = _grams(toks)
    out, current, body = [], None, []

    def close() -> None:
        if current:
            # le début de la partie : ses premiers mots, retrouvés dans ce qui a été dit
            text = " ".join(script._plain(" ".join(body)).split()[:40])
            found = find_passage(text, toks, owner, grams) if words and text else None
            out.append({**current, "at": round(words[found[0]].start, 2) if found else None})

    for line in md.splitlines():
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if m:
            close()
            current, body = {"level": len(m.group(1)) - 1, "title": script._plain(m.group(2))}, []
        elif current and line.strip():
            body.append(line)
    close()
    # une partie qui commence directement par une sous-partie commence avec elle
    for k, part in enumerate(out[:-1]):
        if part["at"] is None and out[k + 1]["level"] > part["level"]:
            part["at"] = out[k + 1]["at"]
    return out


def structure_lines(parts: list[dict]) -> list[str]:
    """La structure de la vidéo, pour Daryl."""
    if not parts:
        return []
    return ["La structure de la vidéo (les parties du script de l'auteur, où elles commencent dans la timeline) :",
            *(("  " * (p["level"] - 1)) + f"- {_clock(p['at']) if p['at'] is not None else '(introuvable)'} "
              f"{p['title']}" for p in parts), ""]


def _clock(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def target_count(total: float, density: str) -> tuple[int, int]:
    lo, hi = DENSITIES.get(density, DENSITIES[DEFAULT_DENSITY])
    return max(1, round(total / hi)), max(1, round(total / lo))


def _line_of(lines: list[dict], first_word: int) -> int:
    return max((l["n"] for l in lines if l["first"] <= first_word), default=1)


def prompt(project: dict, timeline: dict, lines: list[dict], total: float, density: str, note: str,
           script_md: str, plans: list[dict], sfx: list[dict], anims: list[dict], visual: list[dict],
           types: list[str], sections: list[dict] = (), mine: list[dict] = ()) -> str:
    lo, hi = DENSITIES[density]
    few, many = target_count(total, density)
    names = {"motion": "motion", "zoom": "zoom", "broll": "broll (plans de coupe)", "transition": "transition"}
    parts = [f"Vidéo : « {project.get('title') or ''} », {_clock(total)} de timeline.",
             "Types de beats à proposer : " + ", ".join(names[t] for t in types) + ".", ""]
    if "motion" in types:
        parts[-1:-1] = [f"Densité demandée pour les motions : un toutes les {lo:.0f} à {hi:.0f} secondes en moyenne, "
                        f"soit {few} à {many} motions en tout (plans du script compris), répartis sur toute la vidéo "
                        "(pas tous au début)."]
    wanted = [p for p in plans if p["at"] is not None and ("motion" if p["motion"] else "broll") in types]
    if wanted:
        parts += ["Les plans du script (prévus par l'auteur, un beat chacun) :"]
        parts += [f"- {p['ref']} [L{_line_of(lines, p['first'])} {_clock(p['at'])} → {_clock(p['end'])}] {p['type']} → "
                  f"{'motion' if p['motion'] else 'broll'} · passage : « {p['passage'][:300]} » · note : "
                  f"{p['note'] or '(aucune)'}" + (f" · médias : {', '.join(p['media'])}" if p["media"] else "")
                  for p in wanted]
        parts += [""]
    if note.strip():
        parts += ["Consigne de l'auteur pour ce storyboard :", note.strip(), ""]
    if mine:
        parts += ["Les beats qu'il a posés lui-même (ils restent tels quels : aucun beat qui occupe l'écran par-dessus) :",
                  *(f"- {_clock(b['at'])} → {_clock(b['at'] + b['dur'])} {b['type']} : {b['show'] or '(sans consigne)'}"
                    for b in mine), ""]
    chapters = [k for k in timeline["markers"] if k["kind"] == "chapter"]
    if chapters:
        parts += ["Chapitres :", *(f"- {_clock(k['t'])} {k['text']}" for k in chapters), ""]
    parts += structure_lines(list(sections))
    taken = [(m["at"], m["at"] + m["dur"], f"motion {m['title'] or m['kind']}") for m in timeline["motion"]]
    taken += [(b["at"], b["at"] + b["out"] - b["in"], f"B-roll {Path(b['src']).name}") for b in timeline["broll"]]
    if taken:
        parts += ["Déjà dans la timeline (rien qui occupe l'écran sur ces passages) :",
                  *(f"- {_clock(a)} → {_clock(b)} {what}" for a, b, what in sorted(taken)), ""]
    if "zoom" in types and timeline["zooms"]:
        parts += ["Zooms déjà dans la timeline (pas d'autre zoom dessus) :",
                  *(f"- {_clock(z['at'])} → {_clock(z['at'] + z['dur'])} ×{z['scale']:.2f}" for z in timeline["zooms"]), ""]
    if "broll" in types:
        if visual:
            parts += ["Les médias visuels disponibles (`media` = le src exact) :",
                      *(f"- {v['src']} · {'vidéo' if v['kind'] == 'video' else 'image'}"
                        + (f" · {v['description']}" if v["description"] else "") for v in visual[:MAX_VISUALS]), ""]
        else:
            parts += ["Aucun média visuel disponible : chaque broll est une suggestion (`media` vide, `search`).", ""]
    if anims and "motion" in types:
        parts += ["Les animations du kit (`anim` = le nom exact, ou vide pour du sur mesure) :",
                  *(f"- {Path(a['name']).stem} · {a['title']}" + (f" : {a['description']}" if a["description"] else "")
                    for a in anims), ""]
    if "motion" in types or "broll" in types:
        parts += ["Les transitions de la bibliothèque (`enter_fx` / `exit_fx` = l'id exact, ou vide) :",
                  *transitions.prompt_lines(), ""]
    if sfx:
        parts += ["Les sons disponibles (`sfx` = le src exact, ou vide ; un son seulement quand l'entrée le mérite) :",
                  *(f"- {x['src']}" + (f" · {x['description']}" if x["description"] else "") for x in sfx), ""]
    else:
        parts += ["Aucun son disponible : laisse `sfx` vide.", ""]
    if script_md.strip():
        parts += ["Le script de l'auteur (ses notes de visuels peuvent t'aider ; il s'en écarte souvent au tournage) :",
                  "<script>", script_md.strip(), "</script>", ""]
    parts += ["Le transcript de la timeline, une phrase par ligne (numéro, minute:seconde) :", "<transcript>"]
    parts += [f"L{l['n']} [{_clock(l['start'])}] {l['text']}" for l in lines]
    parts += ["</transcript>", "", "Rends le storyboard."]
    return "\n".join(parts)


# --- Des mots au temps de la timeline ------------------------------------------------------------

def _find(toks: list[str], seq: list[str], lo: int, hi: int, near: int) -> int | None:
    """Le début de `seq` dans toks[lo:hi], le plus proche de `near`."""
    if not seq:
        return None
    hits = [i for i in range(max(0, lo), min(len(toks), hi) - len(seq) + 1) if toks[i:i + len(seq)] == seq]
    return min(hits, key=lambda i: abs(i - near)) if hits else None


def locate(words: list[cues.Word], anchor: str, until: str, first_word: int) -> tuple[int, int | None] | None:
    """Les indices du mot d'ancre et du dernier mot couvert (None si la fin est introuvable),
    ou None si l'ancre est introuvable près de sa ligne."""
    toks, owner = autoderush._token_index(words)
    a_toks, u_toks = autoderush._tokens(anchor), autoderush._tokens(until)
    near = next((i for i, o in enumerate(owner) if o >= first_word), len(toks))
    i = _find(toks, a_toks, near - SEARCH_BEFORE, near + SEARCH_AFTER, near)
    if i is None:
        return None
    j = _find(toks, u_toks, i, i + len(a_toks) + UNTIL_SPAN, i)
    return owner[i], (owner[j + len(u_toks) - 1] if j is not None else None)


def _says(words: list[cues.Word], a: int, b: int) -> str:
    return "".join(w.text for w in words[a:b + 1]).strip()


# --- Contrôles ------------------------------------------------------------------------------------

def check(beats: list[dict], words: list[cues.Word], timeline: dict, total: float, density: str,
          covers: list[dict] = ()) -> dict:
    """Ce qu'il faut regarder : {warnings: [{kind, beat, t, text}], density: {...}}.
    kind : anchor (ancre plus dans le transcript : passage coupé depuis ?), late (le visuel arrive
    trop tôt ou trop tard sur son mot), overlap, busy (un motion existe déjà là), cover (un plan du
    script occupe déjà l'écran : image, capture, B-roll), density."""
    toks, owner = autoderush._token_index(words)
    warnings: list[dict] = []
    live = sorted((b for b in beats if b.get("on", True)), key=lambda b: b["at"])
    screen = [b for b in live if b.get("type", "motion") in SCREEN]
    zooms = [b for b in live if b.get("type") == "zoom"]
    for b in beats:
        if b.get("type") == "transition" or not b.get("anchor"):
            # une transition arrive exprès avant les premiers mots de la nouvelle partie ; un beat posé à la main sur
            # un clip inséré n'a pas de mots
            continue
        a_toks = autoderush._tokens(b.get("anchor", ""))
        near = next((i for i, o in enumerate(owner) if words[o].start >= b["at"] - 5), len(toks))
        i = _find(toks, a_toks, near - SEARCH_BEFORE, near + SEARCH_AFTER, near)
        if i is None:
            # loin de son beat (beat déplacé à la main) : signalé comme décalé
            i = _find(toks, a_toks, 0, len(toks), near)
        if i is None:
            warnings.append({"kind": "anchor", "beat": b["id"], "t": b["at"], "text": b.get("anchor", "")})
            continue
        # le visuel par rapport à son mot : de 0,2 s avant à 1,8 s après
        delta = b["at"] - words[owner[i]].start
        if not -GATE_BEFORE - 0.05 <= delta <= GATE_AFTER:
            warnings.append({"kind": "late", "beat": b["id"], "t": b["at"], "text": b.get("anchor", ""),
                             "delta": round(delta, 2)})

    def cross(a0: float, a1: float, b0: float, b1: float) -> float:
        return min(a1, b1) - max(a0, b0)

    for group in (screen, zooms):
        for prev, nxt in zip(group, group[1:]):
            if nxt["at"] < prev["at"] + prev["dur"]:
                warnings.append({"kind": "overlap", "beat": nxt["id"], "t": nxt["at"], "text": prev["id"]})
    # un zoom sous un visuel qui couvre tout l'écran ne se verrait pas
    for z in zooms:
        hit = next((b for b in screen if cross(z["at"], z["at"] + z["dur"], b["at"], b["at"] + b["dur"]) > 0.3
                    and (b.get("type") != "motion" or b.get("place") == "full")), None)
        if hit:
            warnings.append({"kind": "hidden", "beat": z["id"], "t": z["at"], "text": hit["id"]})
    # ce que la timeline a déjà, hors de ce qui vient du beat lui-même
    taken = [(m["at"], m["at"] + m["dur"], m.get("beat"), m["title"] or m["id"]) for m in timeline["motion"]]
    taken += [(x["at"], x["at"] + x["out"] - x["in"], x.get("beat"), Path(x["src"]).name) for x in timeline["broll"]]
    zoomed = [(x["at"], x["at"] + x["dur"], x.get("beat"), f"×{x['scale']:.2f}") for x in timeline["zooms"]]
    for b in live:
        for a0, a1, owner_beat, label in (zoomed if b.get("type") == "zoom" else taken):
            if owner_beat != b["id"] and cross(b["at"], b["at"] + b["dur"], a0, a1) > 0.3:
                warnings.append({"kind": "busy", "beat": b["id"], "t": b["at"], "text": label})
                break
        if b.get("type", "motion") != "motion":
            continue
        for c in covers:
            if cross(b["at"], b["at"] + b["dur"], c["at"], c["end"]) > 1.0:
                warnings.append({"kind": "cover", "beat": b["id"], "t": b["at"],
                                 "text": f"{c['type']}{' · ' + c['note'][:80] if c['note'] else ''}"})
                break
    # la densité ne compte que les motions
    motions = [b for b in live if b.get("type", "motion") == "motion"]
    few, many = target_count(total, density)
    every = round(total / len(motions), 1) if motions else None
    gaps = [b["at"] - (a["at"] + a["dur"]) for a, b in zip(motions, motions[1:])]
    if motions:
        gaps += [motions[0]["at"], total - (motions[-1]["at"] + motions[-1]["dur"])]
    longest = round(max(gaps), 1) if gaps else round(total, 1)
    if motions and not few * 0.75 <= len(motions) <= many * 1.25:
        warnings.append({"kind": "density", "beat": None, "t": 0.0, "text": f"{len(motions)}"})
    counts = {t: sum(1 for b in live if b.get("type", "motion") == t) for t in TYPES}
    return {"warnings": warnings, "density": {"count": len(motions), "target": [few, many], "every": every,
                                              "longest_gap": longest}, "counts": counts}


def fit(beats: list[dict], total: float) -> list[dict]:
    """Recale ce qui peut l'être sans rien inventer : un beat qui déborde sur le suivant est raccourci
    s'il garde MIN_DUR, et rien ne dépasse la fin de la timeline."""
    beats.sort(key=lambda b: b["at"])
    # ce qui occupe l'écran d'un côté, les zooms de l'autre : chacun ne gêne que les siens
    for group in ([b for b in beats if b.get("type", "motion") in SCREEN], [b for b in beats if b.get("type") == "zoom"]):
        for prev, nxt in zip(group, group[1:]):
            room = nxt["at"] - SPACING - prev["at"]
            if prev["at"] + prev["dur"] > nxt["at"] - SPACING and room >= FIT_MIN:
                prev["dur"] = round(room, 2)
    for b in beats:
        b["dur"] = round(max(0.3, min(b["dur"], total - b["at"])), 2)
    return beats


# --- Fichier --------------------------------------------------------------------------------------

def path(pid: str):
    return montage.root(pid) / FILE


def load(pid: str) -> dict | None:
    p = path(pid)
    if not p.is_file():
        return None
    try:
        board = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    # « side » d'avant la distinction gauche / droite
    for b in board.get("beats", []):
        if b.get("place") == "side":
            b["place"] = "right"
        # un storyboard d'avant les types : que des motions ; une « note » (type abandonné) : un motion
        if b.get("type") not in TYPES:
            b["type"] = "motion"
        b.pop("done", None)
    return board


def save(pid: str, board: dict) -> None:
    p = path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# --- Un beat, à partir de ce que rend Daryl ------------------------------------------------------

def refs(pid: str) -> dict:
    """Ce qui sert à rattacher les réponses de Daryl à de vrais fichiers : sons, animations du kit, médias."""
    return {"sfx": [x["src"] for x in sounds(pid)], "anims": [a["name"] for a in kit_animations()],
            "media": [v["src"] for v in visuals(pid)]}


def end_of(kind: str, value) -> dict | None:
    """Une transition d'entrée ou de sortie (un id de la bibliothèque, ou {fx, dur}), pour un motion ou un B-roll."""
    if kind not in ("motion", "broll") or not value:
        return None
    if isinstance(value, str):
        value = {"fx": value, "dur": transitions.DEFAULT_DUR}
    return transitions.clean(value) if isinstance(value, dict) and value.get("fx") in transitions.IDS else None


def ends_of(kind: str, enter, exit_) -> dict:
    return {"enter": end_of(kind, enter), "exit": end_of(kind, exit_)}


def make_beat(spec: dict, words: list[cues.Word], a: int, b: int | None, total: float, known: dict,
              plan: dict | None = None) -> dict:
    """Le beat (sans id) que décrit `spec`, ancré du mot `a` au mot `b` (None : fin introuvable)."""
    kind = spec.get("type") if spec.get("type") in TYPES else ("broll" if plan and not plan["motion"] else "motion")
    if b is None and plan and plan["last"] > a:
        # fin introuvable : celle du passage prévu dans le script
        b = plan["last"]
    start = words[a].start
    if kind == "transition":
        at, dur, b = max(0.0, start - TRANSITION_LEAD), TRANSITION_DUR, min(len(words) - 1, a + 4)
    else:
        at = max(0.0, start - (ZOOM_LEAD if kind == "zoom" else LEAD))
        end = words[b].end + TAIL if b is not None else at + DEFAULT_DUR
        lo, hi = {"zoom": ZOOM_DUR, "broll": BROLL_DUR}.get(kind, (MIN_DUR, MAX_DUR))
        if plan:
            # un plan du script garde la durée de son passage
            hi = MAX_SCRIPT_DUR
        dur = max(lo, min(end - at, hi))
    motion = spec.get("motion") or {}
    beat = {
        "type": kind, "at": round(at, 2), "dur": round(max(0.3, min(dur, total - at)), 2),
        "anchor": (spec.get("anchor") or "").strip(),
        "until": (spec.get("until") or "").strip() if b is not None and kind != "transition" else "",
        "says": _says(words, a, b if b is not None else a), "show": (spec.get("show") or "").strip(),
        "kind": spec.get("kind") if spec.get("kind") in KINDS else "other",
        "place": spec.get("place") if spec.get("place") in PLACES else ("right" if kind == "motion" else "full"),
        "anim": resolve_anim(spec.get("anim", ""), known["anims"]) if kind == "motion" else "",
        "motion": {k: str(motion.get(k) or "").strip() for k in ("enter", "hold", "exit")},
        "sfx": resolve_sfx(spec.get("sfx", ""), known["sfx"]) if kind != "zoom" else "", "ref": None,
        "why": (spec.get("why") or "").strip(), "on": True,
        "origin": "script" if plan else "daryl", "plan": plan["id"] if plan else None,
    }
    beat.update(ends_of(kind, spec.get("enter_fx"), spec.get("exit_fx")))
    if kind == "zoom":
        beat["zoom"] = zoom_of(spec.get("zoom"))
    if kind == "broll":
        src = resolve_media(spec.get("media", ""), known["media"])
        if not src and plan:
            src = next(iter(plan["media"]), "")
        beat["src"] = src
        beat["search"] = (spec.get("search") or "").strip()[:200] if not src else ""
        beat["start"] = start_of(spec.get("start"))
    return beat


def start_of(value) -> float:
    """La seconde du média où commence un B-roll vidéo : un nombre positif, sinon 0."""
    return round(max(0.0, float(value)), 2) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


# --- La tâche ---------------------------------------------------------------------------------

def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p = ctx.payload
    pid = p["project"]
    density = p.get("density") if p.get("density") in DENSITIES else DEFAULT_DENSITY
    project = service.load(pid)
    timeline = montage.load(pid)
    words = timeline_words(project, timeline)
    if not words:
        raise RuntimeError("Pas de transcript de la vidéo source : rien à storyboarder.")
    total = sum(c["out"] - c["in"] for c in timeline["aroll"])
    lines = autoderush.lines_of([{"id": "timeline"}], {"timeline": words})
    montage.root(pid).mkdir(parents=True, exist_ok=True)
    state = ctx.state
    state["activity"] = "lit le transcript"
    ctx.save(force=True)

    plans = script_plans(pid, words)
    types = [t for t in TYPES if t in (p.get("types") or TYPES)] or TYPES
    anims = kit_animations()
    visual = visuals(pid)
    known = refs(pid)
    from .storyboard_chat import grab_frame

    frames = [f for f in (grab_frame(pid, total * k) for k in FRAME_AT) if f]
    request = prompt(project, timeline, lines, total, density, p.get("note", ""),
                     service.read_doc(pid, service.SCRIPT_FILE), plans, sounds(pid), anims, visual, types,
                     structure(pid, words), [b for b in (load(pid) or {}).get("beats", []) if b.get("origin") == "user"])
    if frames:
        # le dossier de travail est montage/ : chemins relatifs à lui
        request += ("\n\nAvant de choisir les places et les zooms, regarde ces images de la vidéo (Read) : "
                    + ", ".join(f.removeprefix("montage/") for f in frames) + ".")
    out = ask(ctx, request,
              SYSTEM.format(lang=language_name(), relevance=RELEVANCE), "Read", None, SCHEMA)
    output = out["output"] or {}
    ctx.progress = 0.9

    by_n = {l["n"]: l for l in lines}
    # les plans du script repris : ceux des types demandés
    wanted = [pl for pl in plans if ("motion" if pl["motion"] else "broll") in types]
    by_ref = {pl["ref"]: pl for pl in wanted if pl["at"] is not None}
    beats, unresolved, taken = [], [], set()
    # un plan du script introuvable dans la timeline : signalé, pas placé
    for pl in wanted:
        if pl["at"] is None:
            unresolved.append({"anchor": pl["passage"][:120], "show": pl["note"], "t": 0.0, "origin": "script"})
    for spec in output.get("beats") or []:
        if spec.get("type") not in types:
            continue
        plan = by_ref.get((spec.get("plan") or "").strip().upper())
        if plan and plan["ref"] in taken:
            plan = None
        line = by_n.get(spec.get("line"))
        found = locate(words, spec.get("anchor", ""), spec.get("until", ""), line["first"]) if line else None
        if not found:
            if not plan:
                unresolved.append({"anchor": spec.get("anchor", ""), "show": spec.get("show", ""),
                                   "t": line["start"] if line else 0.0, "origin": "daryl"})
            continue
        if plan:
            taken.add(plan["ref"])
        beats.append(make_beat(spec, words, *found, total, known, plan))
    # un plan du script que Daryl n'a pas repris (ou mal recopié) : posé tel quel sur son passage
    for ref, pl in by_ref.items():
        if ref in taken:
            continue
        a = pl["first"]
        spec = {"type": "motion" if pl["motion"] else "broll", "anchor": "".join(w.text for w in words[a:a + 4]),
                "show": pl["note"] or pl["passage"][:300], "search": pl["note"],
                "why": "Prévu dans le script ; Daryl ne l'a pas détaillé."}
        beats.append(make_beat(spec, words, a, pl["last"], total, known, pl))
    beats = fit(beats, total)
    # ce que l'auteur a posé à la main (ses notes surtout) reste
    mine = [b for b in (load(pid) or {}).get("beats", []) if b.get("origin") == "user"]
    # des ids jamais pris dans la timeline : un beat refait n'hérite pas de ce qu'a posé l'ancien
    used = max((int(x[1:]) for x in [*composed(timeline), *(b["id"] for b in mine)] if re.fullmatch(r"b\d+", x)),
               default=0)
    for i, b in enumerate(beats, used + 1):
        b["id"] = f"b{i}"
    save(pid, {"density": density, "note": p.get("note", ""), "created": time.time(),
               "message": (output.get("message") or out["text"]).strip(),
               "beats": sorted(beats + mine, key=lambda b: b["at"]), "unresolved": unresolved})
    state["activity"] = None
    ctx.progress = 1.0


def retype(b: dict, kind) -> None:
    """Change le type d'un beat, avec ce qu'il faut au nouveau type (sa durée ne bouge pas)."""
    if kind not in TYPES or kind == b.get("type"):
        return
    b["type"] = kind
    # ce qui ne sert qu'à l'ancien type s'en va
    for key, owner in (("zoom", "zoom"), ("src", "broll"), ("search", "broll"), ("start", "broll")):
        if kind != owner:
            b.pop(key, None)
    if kind not in ("motion", "broll"):
        b["enter"] = b["exit"] = None
    if kind == "zoom":
        b.setdefault("zoom", zoom_of(None))
    if kind == "broll":
        b.setdefault("src", "")
        b.setdefault("search", "")
        b.setdefault("start", 0.0)
        if b.get("place") not in ("full", "left", "right"):
            b["place"] = "full"


def edit(pid: str, changes: list[dict]) -> None:
    """Les retouches de l'utilisateur : `changes` = les beats gardés, dans l'ordre, avec ce qu'il peut
    changer (type de beat, on montre, type de visuel, place, son, zoom, média, recherche, coché). Un beat
    absent est supprimé."""
    board = load(pid)
    if not board:
        raise ValueError("pas de storyboard")
    by_id = {b["id"]: b for b in board["beats"]}
    sfx = [x["src"] for x in sounds(pid)]
    names = [a["name"] for a in kit_animations()]
    media = [v["src"] for v in visuals(pid)]
    span: dict | None = None
    beats = []
    for c in changes:
        b = by_id.get(c.get("id"))
        if not b:
            continue
        retype(b, c.get("type"))
        at, dur = c.get("at"), c.get("dur")
        if _number(at) and _number(dur) and (abs(at - b["at"]) > 1e-3 or abs(dur - b["dur"]) > 1e-3):
            # déplacé ou redimensionné à la main : ses mots suivent
            span = span or _span_context(pid)
            respan(b, span["words"], at, dur, span["total"])
        if isinstance(c.get("show"), str):
            b["show"] = c["show"].strip()[:1000]
        if b["type"] == "zoom" and isinstance(c.get("zoom"), dict):
            b["zoom"] = zoom_of(c["zoom"])
        if b["type"] == "broll":
            if isinstance(c.get("src"), str):
                b["src"] = resolve_media(c["src"], media)
            if isinstance(c.get("search"), str):
                b["search"] = c["search"].strip()[:200]
            if "start" in c:
                b["start"] = start_of(c["start"])
        if c.get("kind") in KINDS:
            b["kind"] = c["kind"]
        if c.get("place") in PLACES:
            b["place"] = c["place"]
        if isinstance(c.get("sfx"), str):
            b["sfx"] = resolve_sfx(c["sfx"], sfx)
        if isinstance(c.get("anim"), str):
            b["anim"] = resolve_anim(c["anim"], names)
        if isinstance(c.get("on"), bool):
            b["on"] = c["on"]
        for key in ("enter", "exit"):
            if key in c:
                b[key] = end_of(b["type"], c[key])
        beats.append(b)
    board["beats"] = sorted(beats, key=lambda b: b["at"])
    save(pid, board)


# --- Les beats posés à la main -------------------------------------------------------------------

def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _span_context(pid: str) -> dict:
    timeline = montage.load(pid)
    return {"words": timeline_words(service.load(pid), timeline), "timeline": timeline,
            "total": sum(c["out"] - c["in"] for c in timeline["aroll"])}


def respan(b: dict, words: list[cues.Word], at: float, dur: float, total: float) -> None:
    """Pose le beat sur [at, at + dur] (l'interface l'a déjà aimanté aux mots) ; son ancre, ses derniers mots et ce
    qu'il dit sont relus dans le transcript. Hors de tout mot (un clip inséré), il garde ses bornes, sans ancre."""
    at = round(max(0.0, min(float(at), max(0.0, total - MIN_SPAN))), 2)
    end = min(total, at + max(MIN_SPAN, float(dur)))
    b["at"], b["dur"] = at, round(end - at, 2)
    inside = [i for i, w in enumerate(words) if at <= (w.start + w.end) / 2 <= end]
    if not inside:
        b["anchor"] = b["until"] = b["says"] = ""
        return
    a, z = inside[0], inside[-1]
    b["anchor"] = _says(words, a, min(z, a + 3))
    b["until"] = _says(words, max(a, z - 3), z) if z > a + 3 else ""
    b["says"] = _says(words, a, z)


def next_id(board: dict, timeline: dict) -> str:
    """Un id de beat jamais pris, ni dans le storyboard ni dans la timeline (un beat refait n'hérite de rien)."""
    ids = [b["id"] for b in board["beats"]] + list(composed(timeline))
    return f"b{max((int(x[1:]) for x in ids if re.fullmatch(r'b\d+', x)), default=0) + 1}"


def ensure(pid: str) -> dict:
    """Le storyboard, vide s'il n'a pas encore été généré : on peut y poser des beats à la main."""
    return load(pid) or {"density": DEFAULT_DENSITY, "note": "", "message": "", "created": time.time(), "beats": [],
                         "unresolved": []}


def blank(kind: str, show: str = "") -> dict:
    """Un beat posé à la main (sans id ni place dans le temps), sans rien de ce que Daryl aurait précisé."""
    b = {"type": "motion", "at": 0.0, "dur": HAND_DUR, "anchor": "", "until": "", "says": "", "show": show.strip()[:1000],
         "kind": "other", "place": "right", "anim": "", "motion": {"enter": "", "hold": "", "exit": ""}, "sfx": "",
         "ref": None, "why": "", "on": True, "origin": "user", "plan": None, "enter": None, "exit": None}
    retype(b, kind)
    return b


def add(pid: str, kind: str, at: float, dur: float, show: str = "") -> str:
    """Pose un beat à la main sur [at, at + dur] ; rend son id."""
    if kind not in TYPES:
        raise ValueError("type de beat inconnu")
    board = ensure(pid)
    span = _span_context(pid)
    b = {"id": next_id(board, span["timeline"]), **blank(kind, show)}
    respan(b, span["words"], at, dur, span["total"])
    board["beats"] = sorted([*board["beats"], b], key=lambda x: x["at"])
    save(pid, board)
    return b["id"]


def adopt_markers(pid: str) -> None:
    """Les marqueurs « note » d'avant (sans durée) deviennent des beats posés à la main, de HAND_DUR secondes, leur texte
    pour consigne."""
    timeline = montage.load(pid)
    old = [k for k in timeline["markers"] if k["kind"] != "chapter"]
    if not old:
        return
    board = ensure(pid)
    span = _span_context(pid)
    for k in old:
        b = {"id": next_id(board, timeline), **blank("motion", k["text"])}
        respan(b, span["words"], k["t"], HAND_DUR, span["total"])
        board["beats"].append(b)
    board["beats"].sort(key=lambda x: x["at"])
    save(pid, board)
    timeline["markers"] = [k for k in timeline["markers"] if k["kind"] == "chapter"]
    montage.save(pid, timeline)


# --- Entrée au montage ---------------------------------------------------------------------------

SFX_LEAD = 0.15
SFX_GAIN = -12.0
# les images des B-roll animés, copiées à côté des compositions (le rendu ne lit que ce dossier)
MEDIA_DIR = "media"


def composed(timeline: dict) -> dict[str, str]:
    """Les beats déjà dans la timeline : {id du beat: id de ce qu'il y a posé (motion, zoom ou B-roll)}."""
    return {x["beat"]: x["id"] for track in ("motion", "zooms", "broll") for x in timeline[track] if x.get("beat")}


def animated(pid: str, timeline: dict) -> dict[str, str]:
    """Les beats faits : un zoom ou un B-roll posé, un motion dont l'animation est écrite. Un motion posé dont
    Daryl n'a pas écrit la composition (tour arrêté ou en échec) ne compte pas : on peut relancer sa création."""
    folder = montage.motion_dir(pid)
    motions = {m["id"] for m in timeline["motion"]}
    return {b: x for b, x in composed(timeline).items() if x not in motions or (folder / f"{x}.html").is_file()}


def image_file(beat: dict) -> str:
    """Le nom, dans montage/motion/, de l'image d'un B-roll animé."""
    return f"{MEDIA_DIR}/{beat['id']}-{Path(beat['src']).name}"


def _ends(beat: dict) -> dict:
    """L'entrée et la sortie choisies pour le beat, telles que la timeline les attend."""
    return {k: beat[k] for k in ("enter", "exit") if beat.get(k)}


def compose(pid: str, only: list[str] | None = None) -> dict:
    """Fait entrer au montage les beats cochés pas encore faits (ceux de `only` s'il est donné), à la place et à la
    durée validées : un zoom ou un B-roll vidéo est posé tel quel ; un motion, une transition ou une image devient
    un motion (et son son d'entrée), dont Daryl écrit ensuite la composition.
    Rend {motions: ids des motions à écrire, placed: beats posés, skipped: beats écartés car la place est prise,
    missing: B-roll sans média}."""
    board = load(pid)
    if not board:
        raise ValueError("pas de storyboard")
    timeline = montage.load(pid)
    done = composed(timeline)
    written = animated(pid, timeline)
    sfx = {m["src"]: m for m in montage.available(pid) if m["category"] == "sfx"}

    def next_id(track: str) -> str:
        # jamais un id libéré : une ancienne composition m3.html passerait pour celle du nouveau m3
        prefix = montage.PREFIX[track]
        n = max((int(x["id"][len(prefix):]) for x in timeline[track] if re.fullmatch(rf"{prefix}\d+", x["id"])),
                default=0)
        return f"{prefix}{n + 1}"

    def busy(b: dict) -> bool:
        end = b["at"] + b["dur"]
        if b["type"] == "zoom":
            spans = [(z["at"], z["at"] + z["dur"]) for z in timeline["zooms"]]
        else:
            spans = [(m["at"], m["at"] + m["dur"]) for m in timeline["motion"]]
            spans += [(x["at"], x["at"] + x["out"] - x["in"]) for x in timeline["broll"]]
        return any(min(end, e) - max(b["at"], s) > 0.3 for s, e in spans)

    out = {"motions": [], "placed": [], "skipped": [], "missing": []}
    changed = False
    for b in board["beats"]:
        if not b.get("on") or (only is not None and b["id"] not in only) or b["id"] in written:
            continue
        if b["id"] in done:
            # déjà posé, composition jamais écrite : on la redemande sans le reposer
            out["motions"].append(done[b["id"]])
            continue
        kind = b.get("type", "motion")
        if kind == "broll" and not media_kind(b.get("src", "")):
            out["missing"].append(b["id"])
            continue
        if busy(b):
            out["skipped"].append(b["id"])
            continue
        if kind == "zoom":
            z = zoom_of(b.get("zoom"))
            timeline["zooms"].append({"id": next_id("zooms"), "at": b["at"], "dur": b["dur"], **z, "beat": b["id"]})
            out["placed"].append(b["id"])
            changed = True
            continue
        if kind == "broll" and media_kind(b["src"]) == "video":
            src = montage._resolve_src(pid, b["src"])
            if not src:
                out["missing"].append(b["id"])
                continue
            length = library.duration(service.project_dir(pid) / src)
            # le passage choisi dans le média, sans déborder de sa fin
            start = min(b.get("start") or 0.0, max(0.0, length - 0.5)) if length else b.get("start") or 0.0
            end = min(start + b["dur"], length) if length else start + b["dur"]
            timeline["broll"].append({"id": next_id("broll"), "src": src, "at": b["at"], "in": round(start, 3),
                                      "out": round(end, 3), **_ends(b), "beat": b["id"]})
        else:
            if kind == "broll":
                # l'image, à côté des compositions
                src = montage._resolve_src(pid, b["src"])
                if not src:
                    out["missing"].append(b["id"])
                    continue
                dest = montage.motion_dir(pid) / image_file(b)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(service.project_dir(pid) / src, dest)
            mid = next_id("motion")
            timeline["motion"].append({"id": mid, "at": b["at"], "dur": b["dur"], "title": b["show"][:60],
                                       "kind": "image" if kind == "broll" else "transition" if kind == "transition"
                                       else b["kind"], "idea": b["show"], **_ends(b), "beat": b["id"]})
            out["motions"].append(mid)
        sound = sfx.get(b.get("sfx") or "")
        if sound:
            timeline["audio"].append({"id": next_id("audio"), "src": sound["src"],
                                      "at": round(max(0.0, b["at"] - SFX_LEAD), 3), "in": 0.0,
                                      "out": round(min(sound["duration"] or 1.0, b["dur"]), 3),
                                      "gain_db": sound.get("gain_db", SFX_GAIN), "role": "sfx"})
        out["placed"].append(b["id"])
        changed = True
    if changed:
        for track in ("zooms", "broll", "motion", "audio"):
            timeline[track].sort(key=lambda x: x["at"])
        montage.save(pid, timeline)
    return out


# au-delà, une image agrandie se voit floue à l'écran
MAX_UPSCALE = 1.15


def image_brief(pid: str, b: dict) -> list[str]:
    """La fiche d'une image à mettre en scène : sa taille, ce qui la garde nette, et le niveau attendu."""
    info = media.probe(montage.motion_dir(pid) / image_file(b))
    w, h = info.get("width"), info.get("height")
    size = f", {w}×{h} px" if w and h else ""
    lines = [f"- Une image à mettre en scène : {image_file(b)} (dans la composition : src=\"{image_file(b)}\"){size}, "
             f"place : {PLACE_TEXT.get(b['place'], b['place'])}. Regarde-la (Read) avant de composer : où est le "
             "passage dont il parle, ce qui se lit, ce qui est du décor."]
    if w and h:
        lines.append(f"- Netteté : à l'écran, jamais plus de {round(w * MAX_UPSCALE)} × {round(h * MAX_UPSCALE)} px "
                     f"(sa taille ×{MAX_UPSCALE}, zooms compris) : au-delà, elle est floue."
                     + (" Elle est plus petite que l'écran : ne la force pas en plein cadre." if w < 1700 else ""))
    lines.append(
        "- Niveau attendu : un monteur pro, pas un diaporama. Pas de Ken Burns (dérive lente et continue) ni de fondu "
        "par défaut. Une capture, une page, un article se posent comme un objet sur un fond de la charte (carte ou "
        "page avec ombre et profondeur, fenêtre de navigateur, légère inclinaison 3D), à sa taille nette. Pour lire "
        "un passage de près, on ne zoome pas dans les pixels : on l'isole (le reste s'assombrit ou se floute) ou on "
        "le recompose en vrai texte net, à la police de la charte, qui se détache de l'image. Le cadre reste fixe "
        "tant que rien ne change ; chaque changement est un geste net (0,35 à 0,6 s, ease expo ou power3) déclenché "
        "par le mot qui le motive (en retard se lit comme voulu, en avance comme une erreur) ; au plus une dérive "
        "à peine perceptible (2 % sur tout le plan) pour qu'elle ne soit pas figée. Entrée et sortie : coupe franche, poussée, glissé ou masque qui s'ouvre ; un fondu "
        "seulement s'il a une raison.")
    if b["place"] != "full":
        lines.append("- Comme un portrait sur le côté : encadrée, avec une ombre, elle entre depuis son bord, reste "
                     "posée pendant qu'il parle, puis repart ; rien sur son visage à lui.")
    return lines


def brief(pid: str, ids: list[str]) -> str:
    """La fiche de chaque motion à composer : ce que le storyboard validé demande."""
    board = load(pid) or {"beats": []}
    by_beat = {b["id"]: b for b in board["beats"]}
    timeline = montage.load(pid)
    out = []
    for m in timeline["motion"]:
        b = by_beat.get(m.get("beat") or "")
        if m["id"] not in ids or not b:
            continue
        kind = b.get("type", "motion")
        motion = b.get("motion") or {}
        lines = [f"### {m['id']} · {m['at']:.2f} → {m['at'] + m['dur']:.2f} s ({m['dur']:.1f} s)",
                 f"- Il dit : « {b['says']} »",
                 f"- On montre : {b['show']}"]
        if kind == "transition":
            lines.append(f"- Transition plein écran entre deux parties de la vidéo : l'écran est entièrement couvert "
                         f"au milieu (vers {m['dur'] / 2:.2f} s), entrée et sortie rapides et franches ; ce qu'elle "
                         "affiche se lit d'un coup d'œil. Ici pas de marge : elle couvre tout le cadre.")
        elif kind == "broll":
            lines += image_brief(pid, b)
        else:
            lines.append(f"- Type : {b['kind']} · place : {PLACE_TEXT.get(b['place'], b['place'])}")
            if b.get("anim"):
                lines.append(f"- Base : l'animation du kit montage/motion/exemples/{b['anim']} (adapte-la, garde sa mécanique)")
        if b.get("enter") or b.get("exit"):
            lines.append("- Le montage ajoute " + " et ".join(
                f"{'en entrée' if k == 'enter' else 'en sortie'} la transition « {transitions.label(b[k]['fx'])} » "
                f"({b[k]['dur']:.1f} s)" for k in ("enter", "exit") if b.get(k))
                + " : la composition n'en refait pas une de ce côté (elle y est déjà en place).")
        if any(motion.values()):
            lines.append("- Mouvement : " + " → ".join(v for v in (motion.get("enter"), motion.get("hold"), motion.get("exit")) if v))
        if b.get("why"):
            lines.append(f"- Pourquoi : {b['why']}")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def job_id(pid: str) -> str:
    return f"{pid}-storyboard"


def view(pid: str) -> dict:
    """Le storyboard et ses contrôles, avec l'avancement de sa génération et le chat, pour l'interface."""
    from . import beat_anim, storyboard_chat
    job = jobs.get(job_id(pid))
    adopt_markers(pid)
    board = load(pid)
    project = service.load(pid)
    timeline = montage.load(pid)
    words = timeline_words(project, timeline)
    sfx = sounds(pid)
    anims = kit_animations()
    out = {"job": {"status": job.status, "finished": job.finished, "progress": job.progress, "error": job.error,
                   "activity": job.state.get("activity")} if job else None,
           "board": board, "checks": None, "densities": list(DENSITIES), "default_density": DEFAULT_DENSITY,
           "types": TYPES, "kinds": KINDS, "places": PLACES, "sfx": ["", *(x["src"] for x in sfx)],
           "visuals": visuals(pid),
           "sfx_help": {x["src"]: x["description"] for x in sfx}, "anims": anims, "composed": {},
           "chat": storyboard_chat.view(pid), "anim_jobs": {},
           # les mots de la timeline [début, fin], où s'aimantent les beats qu'on pose ou tire à la main
           "words": [[w.start, w.end] for w in words], "lead": LEAD, "tail": TAIL}
    if board:
        # un storyboard d'avant l'alignement sur la bibliothèque (« whoosh ») : rattaché au vrai fichier
        for b in board["beats"]:
            b["sfx"] = resolve_sfx(b.get("sfx", ""), out["sfx"][1:])
            # une animation retirée du kit depuis : le beat redevient sur mesure
            b["anim"] = resolve_anim(b.get("anim", ""), [a["name"] for a in anims])
        out["composed"] = animated(pid, timeline)
        out["anim_jobs"] = beat_anim.states(pid, board["beats"])
        total = sum(c["out"] - c["in"] for c in timeline["aroll"])
        covers = [p for p in script_plans(pid, words) if not p["motion"] and p["at"] is not None]
        out["checks"] = check(board["beats"], words, timeline, total, board.get("density") or DEFAULT_DENSITY, covers)
    return out
