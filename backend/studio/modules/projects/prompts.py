"""
Ce que Claude reçoit pour les étapes d'écriture : chercher des angles, en retravailler
un, proposer des titres et des compositions de vignette, écrire le script, répondre dans l'assistant du script.

Il travaille dans le dossier script/ du projet (brief.md, notes.md, documentation.md,
script.md, skill/, titres/, vignette/, vignette-refs/) et ne voit rien d'autre. Les sources qu'il trouve ne vont pas dans un
fichier : il les renvoie (sortie structurée) et elles rejoignent le tableau de l'onglet
Recherche, que documentation.md lui redonne ensuite.
"""
import json

from ..settings.service import channel_prompt, has_tone, language, language_name
from .script import PLAN_TYPES
from .service import (BRIEF_FILE, DOCUMENTATION_FILE, MAX_TITLES, NOTES_FILE, SCRIPT_FILE, SKILL_DIR, THUMB_REFS_DIR,
                      THUMB_SKILL_DIR, TITLES_SKILL_DIR)

WEB_TOOLS = "WebSearch,WebFetch"
READ_TOOLS = "Read,Glob,Grep"

ROLE = """\
Tu es le co-auteur d'un créateur de vidéos YouTube, dont la chaîne est en {lang}. Tu suis la méthode du skill \
youtube-scriptwriting copié dans {skill}/ : lis {skill}/SKILL.md, et ouvre ses fichiers \
{skill}/references/ quand l'étape s'y rapporte (research.md, hooks.md, structures.md, \
retention.md, editing.md). Le skill est en anglais ; tout ce que tu écris est en {lang}.

Matière fournie par l'auteur (à lire, jamais à modifier) : {brief} (idée, direction, durée, \
liens), {notes} (ses notes), {doc} (le tableau des sources du projet, avec pour chacune ce \
qu'il faut en retenir ou s'il faut la consulter). C'est une matière première de premier rang, \
souvent plus fiable et plus personnelle que ce que tu trouves toi-même."""


def role() -> str:
    """Le rôle, suivi du profil de la chaîne (écran Réglages) s'il est renseigné."""
    base = ROLE.format(lang=language_name(), skill=SKILL_DIR, brief=BRIEF_FILE, notes=NOTES_FILE, doc=DOCUMENTATION_FILE)
    channel = channel_prompt()
    return f"{base}\n\n{channel}" if channel else base


def _not_translated() -> str:
    """Les exemples des skills sont en anglais : à adapter, pas à décalquer."""
    if language() == "en":
        return ""
    return " : les exemples du skill sont en anglais, n'en traduis pas les tournures mot à mot"


def tone() -> str:
    return ("le ton de l'auteur décrit dans « La chaîne »" if has_tone()
            else "le ton de l'auteur (direct, il assume son avis)")


# --- Sorties structurées ----------------------------------------------------------

SOURCES = {
    "type": "array",
    "description": f"Les sources réellement consultées qui comptent pour la vidéo (pas celles déjà dans "
                   f"{DOCUMENTATION_FILE}).",
    "items": {
        "type": "object",
        "required": ["title", "url", "note"],
        "properties": {
            "title": {"type": "string", "description": "Titre court : média, rapport, étude…"},
            "url": {"type": "string"},
            "note": {"type": "string",
                     "description": "Une phrase : ce qu'elle apporte (fait, chiffre) et s'il faut la "
                                    "consulter avant d'écrire ou de tourner."},
        },
    },
}
ANGLE_ITEM = {
    "type": "object",
    "required": ["title", "promise", "why"],
    "properties": {
        "title": {"type": "string", "description": "Titre de travail, tel qu'il pourrait être publié."},
        "promise": {"type": "string", "description": "La promesse au spectateur, en quelques mots."},
        "why": {"type": "string",
                "description": "Une ou deux phrases : sur quoi l'angle s'appuie (fait, source du brief) "
                               "et ce qu'il demande ou risque."},
    },
}
ANGLES_SCHEMA = {
    "type": "object", "required": ["angles", "sources"],
    "properties": {"angles": {"type": "array", "minItems": 1, "maxItems": 3, "items": ANGLE_ITEM},
                   "sources": SOURCES},
}
ANGLE_SCHEMA = {"type": "object", "required": ["angle", "sources"],
                "properties": {"angle": ANGLE_ITEM, "sources": SOURCES}}
SCRIPT_SCHEMA = {
    "type": "object", "required": ["message", "sources"],
    "properties": {"message": {"type": "string",
                               "description": "2 à 4 phrases : ce que tu as fait et ce qui reste à trancher."},
                   "sources": SOURCES},
}


ANGLE_CHAT_SCHEMA = {
    "type": "object", "required": ["message", "angles", "sources"],
    "properties": {
        "message": {"type": "string", "description": "Ta réponse à l'auteur, brève."},
        "angles": {"type": "array", "maxItems": 3, "items": ANGLE_ITEM,
                   "description": "Les angles que tu proposes dans cette réponse (nouveaux ou retravaillés), "
                                  "vide si tu n'en proposes pas."},
        "sources": SOURCES,
    },
}

TITLES_SCHEMA = {
    "type": "object", "required": ["titles", "message"],
    "properties": {
        "titles": {"type": "array", "minItems": 1, "maxItems": 30, "items": {
            "type": "object",
            "required": ["title", "pattern", "why", "top"],
            "properties": {
                "title": {"type": "string", "description": "Le titre, tel qu'il serait publié."},
                "pattern": {"type": "string",
                            "description": "Le motif ou la formule du skill qu'il applique, en deux ou "
                                           "trois mots."},
                "why": {"type": "string", "description": "Une phrase : pourquoi ce public cliquerait."},
                "top": {"type": "boolean", "description": f"Un de tes {MAX_TITLES} titres conseillés."},
            },
        }},
        "message": {"type": "string",
                    "description": f"2 ou 3 phrases : pourquoi ces {MAX_TITLES} titres conseillés, et "
                                   "lesquels opposer dans un A/B test."},
    },
}


# --- Angles ---------------------------------------------------------------------

def angles_system(web: bool) -> str:
    research = ("documente le sujet (WebSearch, et WebFetch sur les liens du brief et les sources à consulter)"
                if web else "appuie-toi sur le brief, les notes, les sources et tes connaissances")
    return f"""{role()}

# Ta tâche : proposer des angles
- Lis {BRIEF_FILE}, {NOTES_FILE} et {DOCUMENTATION_FILE}, puis {research}.
- Propose des angles vraiment différents les uns des autres et des angles déjà proposés.
- Renvoie aussi les sources utiles que tu as trouvées, chacune avec une phrase sur ce qu'elle \
apporte : elles rejoignent le tableau des sources du projet.
- N'écris aucun fichier : ta réponse, c'est la sortie structurée."""


def angles_prompt(existing: list[dict], keep: dict | None, note: str, count: int) -> str:
    parts = [f"Propose {count} angle{'s' if count > 1 else ''} pour cette vidéo."]
    if keep:
        parts.append(f"L'auteur a retenu cet angle, garde-le en tête mais ne le repropose pas : "
                     f"« {keep['t']} » ({keep.get('p', '')}).")
    others = [a["t"] for a in existing if not keep or a["t"] != keep["t"]]
    if others:
        parts.append("Déjà proposés (ne pas refaire) :\n" + "\n".join(f"- {t}" for t in others))
    if note.strip():
        parts.append(f"Orientation demandée par l'auteur : {note.strip()}")
    return "\n\n".join(parts)


def iterate_prompt(angle: dict, note: str) -> str:
    return (f"Retravaille cet angle en tenant compte de la remarque de l'auteur.\n\n"
            f"Angle : « {angle['t']} »\nPromesse : {angle.get('p', '')}\nPourquoi : {angle.get('why', '')}\n\n"
            f"Remarque de l'auteur : {note.strip()}")


def angle_chat_system(web: bool) -> str:
    look = " Vérifie sur le web ce qui doit l'être (WebSearch, WebFetch)." if web else ""
    return f"""{role()}

# Ta tâche : aider l'auteur à choisir l'angle de sa vidéo
Il discute avec toi des angles proposés : les comparer, en mélanger deux, en pousser un, en \
trouver un plus personnel ou plus polémique, juger ce qui marchera sur YouTube (clic, rétention, \
faisabilité du tournage).{look}
- Réponds brièvement et franchement : dis ce que tu recommandes et pourquoi.
- Quand tu proposes un angle (nouveau, mélangé ou retravaillé), mets-le dans `angles` de la \
sortie structurée : l'auteur pourra l'ajouter à sa liste d'un clic. Ne le recopie pas dans le message.
- Renvoie les sources nouvelles que tu as consultées, avec une phrase sur ce qu'elles apportent.
- N'écris aucun fichier."""


def angle_chat_prompt(text: str, angles: list[dict], selected: int | None) -> str:
    if angles:
        listing = "\n".join(f"{chr(65 + i)}. « {a['t']} » — {a.get('p', '')}{' (retenu)' if i == selected else ''}"
                            for i, a in enumerate(angles))
        context = f"Les angles actuels :\n{listing}"
    else:
        context = "Aucun angle n'a encore été proposé."
    return f"{context}\n\nMessage de l'auteur : {text}"


# --- Titres ---------------------------------------------------------------------

def titles_system() -> str:
    return f"""{role()}

# Ta tâche : proposer des titres
Pour les titres, suis le skill copié dans {TITLES_SKILL_DIR}/ : lis {TITLES_SKILL_DIR}/SKILL.md et \
applique sa méthode, ses formules et ses règles. Adapte le skill à ce cadre :
- Ne pose aucune question : le sujet, l'idée forte et le public sont dans {BRIEF_FILE}, \
{NOTES_FILE}, {DOCUMENTATION_FILE} et l'angle retenu.
- Les fichiers de référence que le skill mentionne et qui n'existent pas : passe-t'en.
- Les titres sont en {language_name()}{_not_translated()}.
- Chaque titre tient la promesse de l'angle retenu : la vidéo doit pouvoir la tenir.
- Marque `top` sur tes {MAX_TITLES} meilleurs : l'auteur en retiendra jusqu'à {MAX_TITLES} pour l'A/B \
test de YouTube, donc des titres assez différents pour que le test apprenne quelque chose.
- N'écris aucun fichier, même si le skill le demande : ta réponse, c'est la sortie structurée."""


def titles_prompt(angle: dict | None, kept: list[str], existing: list[str], note: str) -> str:
    parts = ["Propose des titres pour cette vidéo : autant que le skill en prévoit, au moins 10.",
             f"L'angle retenu : « {angle['t']} » — {angle.get('p', '')}. {angle.get('why', '')}"
             if angle else "Aucun angle n'a été retenu : appuie-toi sur le brief."]
    if kept:
        parts.append("L'auteur a déjà retenu ces titres (ne les repropose pas, cherche plutôt de quoi "
                     "les challenger) :\n" + "\n".join(f"- {t}" for t in kept))
    if existing:
        parts.append("Déjà proposés (ne pas refaire) :\n" + "\n".join(f"- {t}" for t in existing))
    if note.strip():
        parts.append(f"Orientation demandée par l'auteur : {note.strip()}")
    return "\n\n".join(parts)


# --- Vignette : compositions ----------------------------------------------------------

THUMB_IDEAS = 3

THUMB_IDEAS_SCHEMA = {
    "type": "object", "required": ["compositions", "message"],
    "properties": {
        "compositions": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
            "type": "object",
            "required": ["name", "scene", "text", "colors", "hook"],
            "properties": {
                "name": {"type": "string", "description": "Son nom en deux à quatre mots (« Le terminal rouge »)."},
                "scene": {"type": "string",
                          "description": "Ce que montre l'image, pour le modèle d'image : 3 à 5 phrases. L'auteur "
                                         "(expression, regard, place dans le cadre), l'élément focal, le fond, la "
                                         "lumière, les couleurs. Sans le texte de la vignette."},
                "text": {"type": "string", "description": "Le texte que le modèle écrit dans l'image, 0 à 3 mots "
                                                          "en capitales ; vide s'il n'y en a pas."},
                "colors": {"type": "string", "description": "Les deux ou trois couleurs dominantes."},
                "hook": {"type": "string", "description": "Une phrase : la question que se pose le spectateur."},
            },
        }},
        "message": {"type": "string",
                    "description": "2 ou 3 phrases : laquelle tu conseilles, et lesquelles opposer dans un A/B test."},
    },
}


def thumb_ideas_system() -> str:
    channel = channel_prompt()
    base = f"""Tu aides un créateur de vidéos YouTube, dont la chaîne est en {language_name()}, à composer ses vignettes. Suis le \
skill copié dans {THUMB_SKILL_DIR}/ : lis {THUMB_SKILL_DIR}/SKILL.md et applique ses règles.

Matière (à lire, jamais à modifier) : {BRIEF_FILE} (idée, direction, public), {NOTES_FILE}, \
{SCRIPT_FILE} s'il existe. Les images de {THUMB_REFS_DIR}/ sont celles que l'auteur a choisies \
pour la variante : regarde-les avec Read."""
    return f"""{base}{f"{chr(10) * 2}{channel}" if channel else ""}

# Ta tâche : proposer des compositions de vignette
Ce que tu proposes part ensuite vers un modèle d'image (Nano Banana, Seedream…), avec :
- les portraits de l'auteur ({THUMB_REFS_DIR}/portrait-*) : son visage, que le modèle reproduit. \
Tu choisis l'expression, le regard, la pose et la place dans le cadre ;
- les vignettes de référence ({THUMB_REFS_DIR}/style-*) : le style visé, choisi par l'auteur. \
Tes compositions restent dans cette famille (cadrage, palette, lumière, traitement) ;
- ta scène, et le texte, que le modèle écrit lui-même dans l'image : rien n'est posé par-dessus \
ensuite. L'auteur peut le modifier ou l'enlever avant de lancer la génération.

Adapte le skill à ce cadre :
- Ne pose aucune question, n'écris aucun fichier : ta réponse, c'est la sortie structurée.
- L'auteur apparaît seul sur la vignette, sauf s'il n'a donné aucun portrait.
- Pas de logo dans la scène : le modèle les dessine mal. Si un logo s'impose, dis-le dans le \
message pour que l'auteur l'ajoute.
- Propose un texte pour chaque composition, sauf si la scène se suffit vraiment à elle-même. \
Il est en {language_name()} et complète le titre associé à la variante sans le répéter.
- Des compositions vraiment différentes les unes des autres : elles serviront à l'A/B test."""


def thumb_ideas_prompt(angle: dict | None, titles: list[str], title: str, variants: list[dict],
                       current: dict | None, portraits: int, styles: int, note: str) -> str:
    parts = [f"Propose {THUMB_IDEAS} compositions de vignette pour cette vidéo.",
             f"L'angle retenu : « {angle['t']} » — {angle.get('p', '')}" if angle
             else "Aucun angle n'a été retenu : appuie-toi sur le brief."]
    parts.append("Titres retenus :\n" + "\n".join(f"- {t}" for t in titles) if titles
                 else "Aucun titre retenu pour l'instant.")
    if title:
        parts.append(f"Cette vignette accompagnera le titre « {title} ».")
    refs =([f"{portraits} portrait(s) de l'auteur"] if portraits else []) \
        + ([f"{styles} vignette(s) de référence pour le style"] if styles else [])
    parts.append(f"Dans {THUMB_REFS_DIR}/ : " + " et ".join(refs) + "." if refs
                 else "L'auteur n'a choisi ni portrait ni vignette de référence : propose quand même, il "
                      "les ajoutera ensuite.")
    # le payload passe par JSON : current n'est plus l'un des objets de variants
    cid = (current or {}).get("id")
    shown = [v for v in variants if v.get("id") != cid and (v.get("prompt") or "").strip()]
    if shown:
        parts.append("Les autres variantes (propose autre chose) :\n" + "\n".join(
            f"- {v.get('v')} : titre « {v.get('title') or ''} », texte « {v.get('text', '')} » ; "
            f"{v['prompt'].strip()}" for v in shown))
    if current and (current.get("prompt") or "").strip():
        parts.append(f"Piste notée par l'auteur pour la variante {current.get('v')} : {current['prompt'].strip()}")
    if note.strip():
        parts.append(f"Orientation demandée par l'auteur : {note.strip()}")
    return "\n\n".join(parts)


# --- Script ---------------------------------------------------------------------

def script_system(web: bool, duration: str) -> str:
    check = ", et vérifie sur le web ce qui doit l'être (WebSearch, WebFetch)" if web else ""
    return f"""{role()}

# Ta tâche : écrire {SCRIPT_FILE}
Suis les étapes du skill (structure, corps avec relances, relecture, outro). Appuie-toi sur \
les sources de {DOCUMENTATION_FILE} (ouvre celles que leur commentaire signale comme à consulter){check}.

# Format de {SCRIPT_FILE}
- En tête : `# Titre de travail`, puis « Durée visée » et le nombre de mots (~150 mots par \
minute), puis « Sources (vérifiées le JJ/MM/AAAA) » : une ligne par source, avec l'URL.
- Puis les sections, chacune avec un titre de niveau 2 au format exact \
`## Libellé — Titre` : `## Accroche — …`, `## Introduction — …`, `## Partie 1 — …`, …, \
`## Conclusion — …`. Le libellé est court et générique, le titre dit de quoi parle la section.
- C'est un texte dit à voix haute : phrases courtes, une idée par paragraphe, {tone()}. \
Pas de listes à puces dans le texte dit.
- Les intentions de plan sur leur propre ligne, juste AVANT le paragraphe qu'elles illustrent : \
`[VISUEL : Type — ce qu'on voit]`, Type parmi {", ".join(PLAN_TYPES)}. Elles deviennent les \
plans du paragraphe (l'auteur les voit sous le texte). Le gras pour les mots sur lesquels insister.
- Chaque chiffre, date, citation ou étude vient d'une source listée en tête. Ce que tu n'as \
pas pu vérifier est marqué [À VÉRIFIER].
{f"- Durée visée : {duration}." if duration else ""}
- N'écris que {SCRIPT_FILE}. Dans la sortie structurée : un court message (ce que tu as fait, \
ce qui reste à trancher) et les nouvelles sources que tu as consultées."""


def script_prompt(angle: dict | None, rewrite: bool) -> str:
    chosen = (f"L'angle retenu : « {angle['t']} » — {angle.get('p', '')}. {angle.get('why', '')}"
              if angle else "Aucun angle n'a été retenu : choisis le plus fort d'après le brief.")
    action = (f"{SCRIPT_FILE} existe déjà : réécris-le entièrement sur cet angle."
              if rewrite else f"Écris {SCRIPT_FILE}.")
    return f"Lis {SKILL_DIR}/SKILL.md, {BRIEF_FILE}, {NOTES_FILE} et {DOCUMENTATION_FILE}.\n\n{chosen}\n\n{action}"


# --- Assistant du script -----------------------------------------------------------

# ce que l'assistant peut proposer comme plan : ce qui illustre le texte dit (pas la face caméra ni le son)
PROPOSED_PLAN_TYPES = ("Animation", "B-roll", "Image", "Écran", "Texte à l'écran", "Insert", "Plan de coupe")
# au-delà, la liste des visuels disponibles est coupée
MAX_VISUALS = 200

SCRIPT_CHAT_SCHEMA = {
    "type": "object", "required": ["message", "plans"],
    "properties": {
        "message": {"type": "string",
                    "description": "Ta réponse à l'auteur. Pour une réécriture : le passage réécrit seul."},
        "plans": {
            "type": "array", "maxItems": 15,
            "description": "Les plans que tu proposes dans cette réponse, dans l'ordre du texte ; vide si tu n'en "
                           "proposes pas.",
            "items": {
                "type": "object",
                "required": ["type", "passage", "note", "why", "media"],
                "properties": {
                    "type": {"type": "string", "enum": list(PROPOSED_PLAN_TYPES)},
                    "passage": {"type": "string",
                                "description": f"Le passage qu'il illustre, recopié MOT POUR MOT depuis {SCRIPT_FILE}, "
                                               "sans le Markdown, à l'intérieur d'un seul paragraphe : une phrase ou "
                                               "un morceau de phrase."},
                    "note": {"type": "string",
                             "description": "Ce qu'on voit, concrètement, en une ou deux phrases : pour une "
                                            "animation, ce qui apparaît et ce qui bouge ; pour un B-roll, le plan à "
                                            "filmer ou à trouver ; pour une image, laquelle."},
                    "why": {"type": "string", "description": "Une phrase : ce que le plan apporte à ce moment-là."},
                    "media": {"type": "string",
                              "description": "Le visuel disponible à utiliser, recopié exactement depuis la liste "
                                             "donnée ; vide si aucun ne convient."},
                },
            },
        },
    },
}


def chat_system(web: bool) -> str:
    return f"""{role()}

# Ta tâche : répondre à l'auteur pendant qu'il retravaille {SCRIPT_FILE}
Tu ne modifies aucun fichier : l'auteur décide lui-même de ce qu'il reprend. Relis \
{SCRIPT_FILE} à chaque question (il le retouche entre deux messages).
- Quand la demande porte sur un passage sélectionné et appelle une réécriture (raccourcir, \
plus percutant, plus oral…), mets dans `message` UNIQUEMENT le passage réécrit, en Markdown, sans \
commentaire ni guillemets : il remplacera le passage tel quel.
- Quand on te demande de vérifier, cherche{" (WebSearch, WebFetch)" if web else ""}, dis ce que tu as \
trouvé avec les sources, et propose une correction si elle est justifiée.
- Quand on te demande des plans (sur un passage ou sur tout le script), mets-les dans `plans` : \
l'auteur les accepte ou les refuse un par un. Cherche les moments où l'image fait mieux que la face \
caméra : un chiffre, une comparaison ou un mécanisme à rendre visible (Animation : motion design, \
schéma, graphique animé), une chose ou un lieu qu'on peut montrer (B-roll), une personne, un logo, \
un document (Image), un site, un outil, un tweet (Écran), une phrase-clé à appuyer (Texte à \
l'écran). Ne propose pas ce que les plans existants couvrent déjà. Préfère peu de plans forts à \
un plan par phrase. Quand un visuel disponible convient, indique-le dans `media`. Le `message` \
dit en deux phrases ta logique d'ensemble, sans recopier les plans.
- Sinon, réponds brièvement, en {language_name()}, et laisse `plans` vide."""


def chat_prompt(text: str, quote: str | None, plans: list[dict], visuals: list[dict]) -> str:
    if quote:
        quoted = "\n".join(f"> {line}" for line in quote.splitlines())
        ask = f"Passage sélectionné dans {SCRIPT_FILE} :\n{quoted}\n\nDemande : {text}"
    else:
        ask = f"Question sur l'ensemble de {SCRIPT_FILE} : {text}"
    parts = []
    if plans:
        parts.append("Les plans déjà posés sur le script :\n" + "\n".join(
            f"- {p.get('type')} : {p.get('note') or '(sans note)'}"
            + (f" — sur « {p['q'][:80]} »" if p.get("q") else "") for p in plans))
    if visuals:
        cut = len(visuals) > MAX_VISUALS
        parts.append("Les visuels disponibles (images et vidéos déjà récupérées par l'auteur) :\n"
                     + "\n".join(f"- {v['label']}" for v in visuals[:MAX_VISUALS]) + ("\n- …" if cut else ""))
    return "\n\n".join([*parts, ask])


# --- Assets : recherche d'images -------------------------------------------------------

IMAGES_SCHEMA = {
    "type": "object",
    "required": ["message", "images"],
    "properties": {
        "message": {"type": "string", "description": "Une ou deux phrases pour l'auteur : ce que tu as trouvé, "
                                                     "ce qui manque, d'où viennent les images."},
        "images": {
            "type": "array",
            "description": "Jusqu'à 8 images, la plus utile d'abord.",
            "items": {
                "type": "object",
                "required": ["title", "url", "page", "variant"],
                "properties": {
                    "title": {"type": "string", "description": "Ce que montre l'image, en quelques mots "
                                                               "(« Logo Bruitparif », « Portrait de Gabriel Zucman »)."},
                    "url": {"type": "string", "description": "Lien DIRECT vers le fichier image (.png, .jpg, .svg, "
                                                             ".webp…), pas vers la page qui l'affiche."},
                    "page": {"type": "string", "description": "La page où l'image a été trouvée."},
                    "variant": {"type": "string", "description": "Ce qui distingue cette image des autres, très "
                                                                 "court : « officiel », « fond sombre », « en conférence »…"},
                    "license": {"type": "string", "description": "La licence ou l'usage permis quand la page le dit "
                                                                 "(CC BY-SA 4.0, kit presse…), sinon vide."},
                },
            },
        },
    },
}

def images_system() -> str:
    return f"""\
Tu aides un créateur de vidéos YouTube, dont la chaîne est en {language_name()}, à rassembler les images de sa prochaine \
vidéo : logos de marques ou d'organisations, photos de personnes, de lieux, d'objets. Le \
sujet de la vidéo est dans {BRIEF_FILE} (lis-le si la demande est ambiguë).

Pour chaque demande, cherche sur le web (WebSearch, WebFetch) et renvoie des liens DIRECTS \
vers des fichiers image, qui s'ouvrent tels quels dans un navigateur. Bonnes sources : le site \
officiel ou son kit presse pour un logo, Wikimedia Commons (prends le lien \
upload.wikimedia.org du fichier original, pas la page « File: »), les sites institutionnels, \
la presse. Préfère la meilleure résolution disponible, le SVG pour les logos. Propose \
plusieurs variantes quand elles existent (logo couleur / monochrome / fond sombre, portrait / \
en situation). N'invente jamais un lien : uniquement ceux que tu as vus dans une page \
consultée. Les liens sont vérifiés et téléchargés ensuite ; ceux qui ne sont pas des images \
sont écartés. Réponds en {language_name()}."""


def images_prompt(text: str, already: list[str]) -> str:
    seen = ("\n\nDéjà proposées (ne les redonne pas) :\n" + "\n".join(f"- {u}" for u in already[-40:])) if already else ""
    return f"Demande : {text}{seen}"


# --- Roasting -----------------------------------------------------------------------

# les critères notés, dans l'ordre de l'écran ; une remarque se range dans l'un d'eux ou dans ROAST_EXTRA
ROAST_CRITERIA = {
    "accroche": "Accroche",
    "valeur": "Valeur rapide",
    "relances": "Relances",
    "payoffs": "Setups / payoffs",
    "promesse": "Promesse tenue",
    "clarte": "Clarté",
    "emotion": "Variété émotionnelle",
    "fin": "Fin",
}
ROAST_EXTRA = {"longueur": "Longueur", "rythme": "Rythme", "faits": "Faits", "autre": "Autre"}
ROAST_DECISIONS = ("tourne", "retouche", "reecris")
ROAST_SEVERITIES = ("bloquant", "important", "detail")

_BLOCK = {"type": "string", "description": "L'id d'un bloc du script, tel qu'il est donné entre crochets ([b1a2b3c4])."}
_SCORE = {"type": "number", "minimum": 0, "maximum": 10}

ROAST_SCHEMA = {
    "type": "object",
    "required": ["verdict", "criteria", "sections", "interest", "loops", "promises", "findings"],
    "properties": {
        "verdict": {
            "type": "object", "required": ["score", "decision", "headline"],
            "properties": {
                "score": {**_SCORE, "description": "La note globale, au demi-point près, selon la grille."},
                "decision": {"type": "string", "enum": list(ROAST_DECISIONS),
                             "description": "tourne : prêt à tourner ; retouche : des corrections ciblées ; "
                                            "reecris : un problème de structure."},
                "headline": {"type": "string",
                             "description": "Une phrase : si l'auteur tournait demain, le problème n°1."},
            },
        },
        "criteria": {
            "type": "array", "description": "Un élément par critère, tous les critères.",
            "items": {
                "type": "object", "required": ["key", "score", "why", "block"],
                "properties": {
                    "key": {"type": "string", "enum": list(ROAST_CRITERIA)},
                    "score": _SCORE,
                    "why": {"type": "string", "description": "Une ou deux phrases, concrètes : ce qui marche, ce qui coince."},
                    "block": {**_BLOCK, "description": "Le bloc qui le montre le mieux (vide s'il n'y en a pas)."},
                },
            },
        },
        "sections": {
            "type": "array", "description": "Une fiche par section (titre de niveau 2), dans l'ordre.",
            "items": {
                "type": "object", "required": ["block", "role", "score", "payoff", "too_long", "verdict"],
                "properties": {
                    "block": {**_BLOCK, "description": "L'id du titre de la section."},
                    "role": {"type": "string", "description": "Son rôle dans la vidéo, en quelques mots."},
                    "score": _SCORE,
                    "payoff": {"type": "boolean", "description": "Donne-t-elle au spectateur une récompense à elle ?"},
                    "too_long": {"type": "boolean",
                                 "description": "Trop longue pour ce qu'elle apporte (sa durée est donnée)."},
                    "verdict": {"type": "string", "description": "Une ou deux phrases."},
                },
            },
        },
        "interest": {
            "type": "array",
            "description": "L'intérêt prédit du spectateur, un élément par bloc de texte dit (pas les titres), "
                           "dans l'ordre : 10 il ne lâche pas, 0 il part.",
            "items": {"type": "object", "required": ["block", "score"], "properties": {"block": _BLOCK, "score": _SCORE}},
        },
        "loops": {
            "type": "array",
            "description": "Les boucles ouvertes : questions, mystères, promesses (« on y revient », « je vous "
                           "montre ça plus tard ») que le texte ouvre, et où il les referme.",
            "items": {
                "type": "object", "required": ["question", "open", "close"],
                "properties": {
                    "question": {"type": "string", "description": "La question que se pose le spectateur."},
                    "open": {**_BLOCK, "description": "Le bloc qui l'ouvre."},
                    "close": {**_BLOCK, "description": "Le bloc qui y répond ; vide si elle n'est jamais refermée."},
                },
            },
        },
        "promises": {
            "type": "array",
            "description": "Ce que l'angle, le titre et la vignette promettent, et où le script le tient.",
            "items": {
                "type": "object", "required": ["source", "promise", "block", "note"],
                "properties": {
                    "source": {"type": "string", "enum": ["angle", "titre", "vignette"]},
                    "promise": {"type": "string", "description": "La promesse, en quelques mots."},
                    "block": {**_BLOCK, "description": "Le bloc où elle est tenue ; vide si elle ne l'est pas."},
                    "note": {"type": "string", "description": "Une phrase : tenue pleinement, à moitié, trop tard…"},
                },
            },
        },
        "findings": {
            "type": "array", "maxItems": 30,
            "description": "Les remarques, la plus grave d'abord : chacune un problème précis, à un endroit précis.",
            "items": {
                "type": "object", "required": ["block", "quote", "severity", "category", "problem", "fix"],
                "properties": {
                    "block": _BLOCK,
                    "quote": {"type": "string",
                              "description": "Le passage visé, recopié MOT POUR MOT depuis le bloc, sans le Markdown : "
                                             "une phrase ou un morceau de phrase (vide : tout le bloc)."},
                    "severity": {"type": "string", "enum": list(ROAST_SEVERITIES)},
                    "category": {"type": "string", "enum": [*ROAST_CRITERIA, *ROAST_EXTRA]},
                    "problem": {"type": "string", "description": "Le problème, en une ou deux phrases."},
                    "fix": {"type": "string",
                            "description": "Comment corriger : une réécriture du passage quand c'est possible, "
                                           "sinon la piste concrète."},
                },
            },
        },
    },
}

ROAST_GRID = """\
- 9-10 : rien à changer, au niveau des meilleures vidéos du genre.
- 7-8 : bon ; quelques retouches ciblées le rendraient excellent.
- 5-6 : ça marche, mais le spectateur décroche à des endroits qu'on peut montrer.
- 3-4 : un problème de fond (structure, promesse, rythme) ; retoucher ne suffit pas.
- 0-2 : à réécrire."""


def roast_system(cold: bool) -> str:
    if cold:
        matter = f"""\
Tu lis le script À FROID, comme le spectateur qui vient de cliquer : tu ne connais que le titre, \
la vignette et le texte. N'ouvre pas {BRIEF_FILE}, {NOTES_FILE} ni {DOCUMENTATION_FILE} : les \
intentions de l'auteur ne doivent pas excuser ce que le texte ne fait pas."""
    else:
        matter = f"""\
Tu peux lire {BRIEF_FILE}, {NOTES_FILE} et {DOCUMENTATION_FILE} pour connaître l'intention de \
l'auteur et vérifier que le script exploite sa matière ; mais tu juges ce que le spectateur \
entendra, pas ce que l'auteur voulait dire."""
    channel = channel_prompt()
    return f"""\
Tu es le script doctor d'un créateur de vidéos YouTube, dont la chaîne est en {language_name()} : tu roastes son script \
avant le tournage. Franc, précis, sans complaisance ni méchanceté gratuite : chaque reproche \
pointe un endroit du texte et dit comment corriger.

Ta grille, c'est le skill youtube-scriptwriting copié dans {SKILL_DIR}/ : lis {SKILL_DIR}/SKILL.md, \
puis {SKILL_DIR}/references/hooks.md, retention.md, structures.md et editing.md (audits de flow, \
de compréhension, de speed-to-value). Le skill est en anglais ; tout ce que tu écris est en {language_name()}.

{matter}

# Le script
Il t'est donné dans le message, bloc par bloc, chaque bloc précédé de son id entre crochets. \
Sous un bloc, les lignes « ↳ à l'écran » sont les plans prévus : ce que le spectateur VOIT \
pendant qu'il entend le texte (face caméra, B-roll, extrait vidéo, image, animation, texte à \
l'écran ; le nom du fichier dit souvent ce qu'il montre). Juge le texte avec ses images : une \
citation dite sur un extrait vidéo de la personne qui parle est attribuée, un chiffre affiché \
à l'écran est lisible. Un passage sans plan est dit face caméra. \
Tu désignes un endroit du script par cet id dans les champs `block`, `open` et `close`, jamais par \
un id inventé ; dans tes phrases, l'auteur ne voit pas les ids : cite quelques mots du passage ou \
son moment (« vers 3:40 »). Les durées sont estimées \
à ~150 mots par minute ; ne les recalcule pas.

# Ce que tu regardes
- L'accroche : tient-elle le titre et la vignette dans les premières secondes, donne-t-elle une \
raison de rester ?
- La valeur : en combien de temps le spectateur a-t-il quelque chose ? Chaque section a-t-elle \
son mini-payoff ?
- Les relances : où l'attention retombe, et y a-t-il une relance avant ?
- Les setups et payoffs, les boucles ouvertes : chaque question posée trouve-t-elle sa réponse ?
- La promesse de l'angle, du titre et de la vignette : tenue, et à quel moment ?
- La clarté : jargon, sauts logiques, phrases trop longues pour être dites.
- La variété émotionnelle, le rythme, la longueur de chaque section pour ce qu'elle apporte.
- La fin : satisfait, ou donne envie d'enchaîner ?

# Les notes
Une note sur 10, au demi-point près, selon cette grille (la même pour chaque critère) :
{ROAST_GRID}
Sois exigeant : 7 est une bonne note. Ne gonfle pas les notes pour encourager.

# Ta réponse
Uniquement la sortie structurée ; n'écris aucun fichier. Les remarques : pas de généralités \
(« améliorer le rythme ») mais un passage, un problème, une correction. Pas de doublon entre \
remarques ; au plus 30, la plus grave d'abord.""" + (f"\n\n{channel}" if channel else "")


def _roast_context(context: dict) -> list[str]:
    """Le titre, la vignette, l'angle et la durée visée."""
    parts = []
    if context.get("title"):
        parts.append(f"Le titre : « {context['title']} »")
    if context.get("thumbs"):
        parts.append("La vignette :\n" + "\n".join(f"- {t}" for t in context["thumbs"]))
    if context.get("angle"):
        a = context["angle"]
        parts.append(f"L'angle retenu : « {a['t']} » — {a.get('p', '')}")
    if context.get("duration"):
        parts.append(f"Durée visée : {context['duration']}")
    return parts


def _roast_script(blocks: list[dict]) -> str:
    """Le script bloc par bloc : id, plans à l'écran, et pour chaque section son début et sa durée."""
    lines = []
    for b in blocks:
        about = f"   ← section : début {b['start']}, {b['words']} mots, ~{b['duration']}" if b.get("section") else ""
        shown = []
        for p in b.get("plans") or []:
            what = " — ".join(x for x in (p["note"], "fichier : " + ", ".join(p["media"]) if p["media"] else "") if x)
            span = f" jusqu'à [{p['end']}]" if p.get("end") and p["end"] != b["id"] else ""
            on = f" sur « {p['q'][:120]}{'…' if len(p['q']) > 120 else ''} »" if p["q"] else ""
            shown.append(f"   ↳ à l'écran : {p['type']}{span}{on}" + (f" : {what}" if what else ""))
        lines.append("\n".join([f"[{b['id']}] {b['md']}{about}", *shown]))
    return "\n\n".join(lines)


def roast_prompt(blocks: list[dict], context: dict, ignored: list[dict], note: str) -> str:
    """Le titre, la vignette, l'angle, puis le script bloc par bloc."""
    parts = _roast_context(context)
    parts.append("Le script :\n\n" + _roast_script(blocks))
    if ignored:
        parts.append("L'auteur a écarté ces remarques d'un roast précédent : ne les refais pas.\n"
                     + "\n".join(f"- {f['problem']}" + (f" (« {f['quote'][:80]} »)" if f.get("quote") else "")
                                 for f in ignored))
    if note.strip():
        parts.append(f"Ce que l'auteur veut que tu regardes en particulier : {note.strip()}")
    return "\n\n".join(parts)


def roast_chat_system(web: bool, cold: bool) -> str:
    look = " Vérifie sur le web ce qui doit l'être (WebSearch, WebFetch)." if web else ""
    how = ("à froid (titre, vignette et texte seulement, sans le brief ni les notes)" if cold
           else "avec le contexte (brief, notes, sources, angle)")
    return f"""{role()}

# Ta tâche : discuter d'un roast avec l'auteur
Un script doctor a roasté le script de l'auteur, {how}, avec la grille du skill \
youtube-scriptwriting ({SKILL_DIR}/SKILL.md et ses references/). L'auteur ne comprend pas toujours \
ses remarques ou n'est pas d'accord : il te questionne sur une note, une section, une boucle, \
une promesse ou une remarque, que son message cite.
- Explique concrètement : quel passage pose problème, ce que le spectateur ressent à cet endroit, \
et la règle du skill derrière la remarque. Cite quelques mots du script ou le moment (« vers \
3:40 ») ; jamais les ids entre crochets, que l'auteur ne voit pas.
- Quand on te demande comment corriger, propose des pistes précises et, si ça aide, une \
réécriture du passage dans {tone()}.
- Le roast peut se tromper : si l'auteur conteste et qu'il a raison, dis-le franchement ; sinon, \
tiens ta position en expliquant pourquoi.{look}
- Le script a pu changer depuis le roast : relis {SCRIPT_FILE} si la question porte sur la version actuelle.
- Réponds brièvement, en {language_name()}, en texte simple (pas de titres Markdown). N'écris aucun fichier."""


def roast_chat_prompt(text: str, quote: str | None, roast: dict | None) -> str:
    """Le message de l'auteur avec l'élément du roast dont il parle ; au premier message, le roast entier."""
    parts = []
    if roast:
        parts += _roast_context(roast["context"])
        parts.append("Le script au moment du roast :\n\n" + _roast_script(roast["blocks"]))
        if roast.get("note"):
            parts.append(f"Ce que l'auteur avait demandé de regarder : {roast['note']}")
        parts.append("Le roast (sortie du script doctor ; chaque remarque porte son suivi par l'auteur) :\n"
                     + json.dumps(roast["result"], ensure_ascii=False, indent=1))
    if quote:
        quoted = "\n".join(f"> {line}" for line in quote.splitlines())
        parts.append(f"L'élément du roast dont parle l'auteur :\n{quoted}")
    parts.append(f"Message de l'auteur : {text}")
    return "\n\n".join(parts)
