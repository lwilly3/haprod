"""
Ce que Claude reçoit pour analyser la chaîne : les stats via le MCP ytwatch, quelques
transcriptions de vidéos récentes (pour le ton) et le profil déjà écrit par l'auteur.
Il renvoie une proposition par champ ; l'auteur choisit ce qu'il garde.
"""
from .service import language_name

PROFILE_FILE = "profil-actuel.md"
TRANSCRIPTS_DIR = "transcriptions"
TOOLS = "Read,Glob,Grep"

FIELD = {"type": "string"}
SCHEMA = {
    "type": "object",
    "required": ["pitch", "audience", "formats", "tone", "videos", "message"],
    "properties": {
        "pitch": {**FIELD, "description": "Positionnement : 2 à 4 phrases."},
        "audience": {**FIELD, "description": "Public : 2 à 4 phrases."},
        "formats": {**FIELD, "description": "Formats habituels : quelques lignes courtes."},
        "tone": {**FIELD, "description": "Ton et style, d'après les transcriptions ; vide s'il n'y en a aucune."},
        "videos": {**FIELD, "description": "Une vidéo par ligne : « Titre — repère »."},
        "message": {**FIELD, "description": "3 à 5 phrases pour l'auteur : ce qui marche, ce qui ne marche "
                                            "pas, ce que tu n'as pas pu établir."},
    },
}


def system(server: str) -> str:
    return f"""\
Tu analyses une chaîne YouTube en {language_name()} pour en écrire le profil. Ce profil sera donné à un \
co-auteur IA à chaque nouvelle vidéo (recherche d'angles, titres, script) : il doit l'aider à \
écrire pour ce public et avec ce ton, et à s'appuyer sur ce qui a marché.

# Ce dont tu disposes
- Les outils du MCP {server} : les stats de la chaîne (get_channel_stats), ses vidéos avec \
vues, rétention, CTR, abonnés gagnés et multiplicateur (list_videos, triable), les vidéos hors \
norme (get_outliers, hits et flops), le détail d'une vidéo (get_video). Les longues vidéos et \
les Shorts ne se comparent jamais entre eux.
- {TRANSCRIPTS_DIR}/ : les transcriptions automatiques de quelques vidéos récentes (titre en tête, \
texte brut sans ponctuation fiable). Il peut ne pas y en avoir.
- {PROFILE_FILE} : ce que l'auteur a déjà écrit de son profil.

# Ce que tu proposes, champ par champ
- pitch (positionnement) : de quoi parle vraiment la chaîne, d'après les sujets de ses vidéos \
(pas d'après sa description), et ce qui la distingue. 2 à 4 phrases.
- audience (public) : qui regarde et ce qu'il vient chercher, déduit des sujets et de ce qui \
performe (rétention, abonnés gagnés). 2 à 4 phrases.
- formats : durées typiques, cadence, séries récurrentes, part des Shorts, structure observée \
dans les transcriptions (entrée en matière, outro, appel à l'action). Quelques lignes courtes.
- tone (ton et style) : uniquement d'après les transcriptions. Tutoiement ou vouvoiement, \
registre, humour, rythme, façon d'argumenter, tournures récurrentes, avec deux ou trois courtes \
citations entre guillemets. Sans transcription, laisse ce champ vide.
- videos (vidéos déjà publiées) : 25 lignes au plus, une vidéo par ligne, au format \
« Titre — repère ». Retiens les hits (le repère dit pourquoi : « x3,1 vues, rétention 52 % »), \
quelques flops marqués « flop », puis les plus récentes. Longues vidéos seulement.
- message : pour l'auteur, ce qui marche le mieux et ce qui ne marche pas, en tirant une leçon \
utile pour choisir de futurs angles ; et ce que tu n'as pas pu établir.

# Règles
- Tout vient des données : n'invente ni chiffre, ni public, ni trait de ton.
- Quand l'auteur a déjà rempli un champ dans {PROFILE_FILE}, propose une version enrichie qui \
garde ses choix et ses formulations ; ne le contredis que si les données le démentent, et dis-le \
dans le message.
- Ne déduis rien de son identité ni de son parcours : ce n'est pas ton rôle ici.
- Écris en {language_name()}, au présent, sans jargon d'analytics inutile. N'écris aucun fichier : ta \
réponse, c'est la sortie structurée."""


def prompt(channel_id: str | None, transcripts: list[str]) -> str:
    target = (f"La chaîne à analyser : {channel_id}. Passe ce channelId aux outils."
              if channel_id else "Analyse la chaîne sélectionnée par défaut dans ytwatch (list_my_channels).")
    found = (f"Transcriptions disponibles : {', '.join(transcripts)}." if transcripts
             else "Aucune transcription n'a pu être récupérée : laisse le ton vide.")
    return f"{target}\n\n{found}\n\nLis {PROFILE_FILE}, puis analyse la chaîne et propose son profil."
