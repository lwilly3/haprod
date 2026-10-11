"""
Shorts : Claude lit un transcript et propose des passages a monter en shorts.

Un short est une suite d'extraits, chacun une plage de lignes du transcript
(L12 a L18), dans l'ordre ou ils seront montes : pas forcement l'ordre de la
video (accroche d'abord), avec des coupes pour retirer redites et digressions.

Claude ne fait pas les calculs : il designe des lignes, et c'est ici que la duree
de chaque short est calculee a partir des timecodes. Un short trop long lui est
renvoye avec l'ecart a combler, jusqu'a ce que tout tienne dans la limite.

Les lignes du transcript sont figees a la creation (state.lines) : corriger le
transcript ensuite ne decale pas les extraits deja choisis.

Un short envoye au montage est decoupe par ffmpeg (job "render", un par short),
a la demande seulement. Un montage est identifie par sa signature (extraits +
format) : un short inchange n'est pas redecoupe.

select : payload name, transcript_job, model
         state   settings, lines, messages, shorts, session_id, model, usage, activity
render : payload selection, signature, title, format, clips, transcript_job
         state   output
"""
import hashlib
import json
import shutil
import time
from pathlib import Path

from ...config import DATA_DIR
from ...core import jobs
from ..settings.service import language_name
from ..transcript import cues as transcript_cues
from ..transcript import service as transcript

MODULE = "shorts"
KIND = "select"
RENDER_KIND = "render"
# claude -p a besoin d'un dossier ou tourner ; il n'y lit ni n'ecrit rien
WORK_DIR = DATA_DIR / "shorts"

MAX_DURATIONS = (60, 90, 180)
FORMATS = ("vertical", "original")
DEFAULT_SETTINGS = {"max_duration": 180, "count": 0, "context": "", "format": "vertical"}
# marge autour de chaque extrait : whisper place les debuts de mots un peu tard et
# les fins un peu tot ; on n'empiete jamais sur plus de la moitie du blanc voisin
PAD_BEFORE, PAD_AFTER = 0.15, 0.3
# en dessous, ce n'est plus un short mais un extrait sans contexte
MIN_DURATION = 15
# allers-retours avec Claude quand un short ne respecte pas la duree
MAX_FIXES = 2
DEFAULT_REQUEST = "Propose les meilleurs shorts de cette vidéo."

SCHEMA = {
    "type": "object",
    "required": ["shorts", "message"],
    "properties": {
        "message": {"type": "string",
                    "description": "2 à 4 phrases : ce que tu as choisi et pourquoi."},
        "shorts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "hook", "clips"],
                "properties": {
                    "title": {"type": "string", "description": "Titre du short, comme publié."},
                    "hook": {"type": "string",
                             "description": "Pourquoi ce short accroche, en une phrase."},
                    "clips": {
                        "type": "array",
                        "minItems": 1,
                        "description": "Les extraits dans l'ordre du montage.",
                        "items": {
                            "type": "object",
                            "required": ["from", "to"],
                            "properties": {
                                "from": {"type": "integer", "description": "Première ligne (le n de Ln)."},
                                "to": {"type": "integer", "description": "Dernière ligne, incluse."},
                                "role": {"type": "string",
                                         "description": "accroche, contexte, développement, chute…"},
                            },
                        },
                    },
                },
            },
        },
    },
}


def system_prompt(settings: dict) -> str:
    max_duration = settings["max_duration"]
    count = settings["count"]
    context = settings.get("context", "").strip()
    return f"""\
Tu es le monteur d'un créateur de vidéos. À partir du transcript d'une vidéo longue, tu \
repères les passages qui feront de bons shorts (YouTube Shorts, Reels, TikTok) et tu \
indiques comment les monter.

# Un bon short
- Il tient tout seul : quelqu'un qui n'a pas vu la vidéo comprend tout. Pas de « comme je \
disais », pas de référence à un passage absent.
- Il accroche dans les 3 premières secondes : une phrase forte, une question, un chiffre, une \
affirmation surprenante. Si cette phrase arrive plus loin dans le passage, monte-la en premier.
- Il porte une seule idée et finit sur une chute : conclusion, punchline, leçon.
- Il est dense : retire les hésitations, redites, digressions et phrases de transition en \
sautant les lignes concernées.

# Le montage
- Un short est une suite d'extraits ; un extrait est une plage de lignes consécutives du \
transcript, de Lfrom à Lto incluses.
- Les extraits s'enchaînent dans l'ordre que tu donnes, qui peut différer de l'ordre de la \
vidéo (accroche d'abord), et peuvent venir de moments éloignés s'ils racontent la même idée.
- Coupe là où la phrase est complète : un extrait commence au début d'une phrase et finit \
sur une ponctuation forte, jamais au milieu d'un mot ou d'une idée. Une ligne peut commencer \
en milieu de phrase : vérifie la ligne d'avant.
- Deux extraits d'un même short ne partagent aucune ligne.

# Durée
- Chaque ligne du transcript indique son début et sa durée. La durée d'un extrait va du début \
de Lfrom à la fin de Lto ; celle du short est la somme de ses extraits.
- Maximum strict : {max_duration} s par short. Minimum : {MIN_DURATION} s.
- La durée est recalculée après ta réponse : si un short dépasse, tu le recevras avec \
l'écart exact à combler. Retire alors des lignes faibles plutôt que de couper la chute.

# Contexte
- Nombre de shorts : {f"exactement {count}" if count else "autant que la vidéo en contient de vraiment bons (souvent 3 à 6) ; mieux vaut peu et forts"}.
{f"- La vidéo, selon son auteur : {context}" if context else ""}
- Les titres, les accroches et ta réponse sont en {language_name()} ; corrige au passage les erreurs de transcription \
(noms propres, termes techniques) dans les titres.
- Ensuite, l'utilisateur affine avec toi : chaque fois, renvoie la liste complète des shorts \
(ceux qu'il garde tels quels compris), pas seulement ceux qui changent."""


# --- Transcript --------------------------------------------------------------

def _tc(sec: float) -> str:
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:04.1f}"


def format_lines(lines: list[list]) -> str:
    """L12 00:01:02.3 (2.8 s) texte : de quoi choisir les coupes et estimer les durees."""
    return "\n".join(f"L{i} {_tc(start)} ({end - start:.1f} s) {text}"
                     for i, (start, end, text) in enumerate(lines, 1))


def lines_of(transcript_job: jobs.Job) -> list[list]:
    built = transcript_cues.build_cues(
        transcript_cues.load_segments(transcript_job.state["segments"]), "line")
    return [[round(c["start"], 3), round(c["end"], 3), c["text"]] for c in built]


# --- Verification des shorts -------------------------------------------------

def _seconds(sec: float) -> str:
    return f"{sec:.1f} s".replace(".", ",")


def evaluate(raw: list[dict], lines: list[list], max_duration: int) -> tuple[list[dict], list[str]]:
    """Shorts exploitables (durees calculees) et ce qui ne va pas, a renvoyer a Claude."""
    shorts, problems = [], []
    for k, item in enumerate(raw, 1):
        title = str(item.get("title") or f"Short {k}").strip()
        label = f"Short {k} « {title} »"
        clips, used, errors = [], set(), []
        for j, clip in enumerate(item.get("clips") or [], 1):
            try:
                first, last = int(clip["from"]), int(clip["to"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"l'extrait {j} n'a pas de lignes valides")
                continue
            if not 1 <= first <= last <= len(lines):
                errors.append(f"l'extrait {j} (L{first}–L{last}) sort du transcript "
                              f"(L1–L{len(lines)}) ou est à l'envers")
                continue
            span = set(range(first, last + 1))
            if span & used:
                errors.append(f"l'extrait {j} (L{first}–L{last}) reprend des lignes d'un autre extrait")
            used |= span
            start, end = lines[first - 1][0], lines[last - 1][1]
            clips.append({"from": first, "to": last, "start": start, "end": end,
                          "role": str(clip.get("role") or ""),
                          "text": " ".join(line[2] for line in lines[first - 1:last])})
        duration = round(sum(c["end"] - c["start"] for c in clips), 2)
        if not clips:
            errors.append("aucun extrait utilisable")
        elif duration > max_duration:
            errors.append(f"dure {_seconds(duration)}, il faut retirer au moins "
                          f"{_seconds(duration - max_duration)} pour tenir en {max_duration} s")
        elif duration < MIN_DURATION:
            errors.append(f"ne dure que {_seconds(duration)}, le minimum est {MIN_DURATION} s")
        problems += [f"{label} : {e}." for e in errors]
        shorts.append({"id": f"s{k}", "title": title, "hook": str(item.get("hook") or ""),
                       "clips": clips, "duration": duration, "errors": errors})
    return shorts, problems


def durations_text(shorts: list[dict]) -> str:
    return "\n".join(f"- Short {k} « {s['title']} » : {_seconds(s['duration'])}"
                     for k, s in enumerate(shorts, 1))


def selection_text(shorts: list[dict]) -> str:
    """La selection telle qu'elle est maintenant (l'utilisateur a pu en retirer)."""
    if not shorts:
        return "(aucun short pour l'instant)"
    out = []
    for k, s in enumerate(shorts, 1):
        clips = ", ".join(f"L{c['from']}–L{c['to']}" for c in s["clips"])
        out.append(f"- Short {k} « {s['title']} » ({_seconds(s['duration'])}) : {clips}")
    return "\n".join(out)


# --- Jobs --------------------------------------------------------------------

def message(role: str, text: str) -> dict:
    return {"role": role, "text": text, "at": time.time()}


def clean_settings(raw: dict) -> dict:
    settings = {**DEFAULT_SETTINGS, **raw}
    if settings["format"] not in FORMATS:
        raise ValueError(f"format inconnu : {settings['format']}")
    if settings["max_duration"] not in MAX_DURATIONS:
        raise ValueError(f"durée maximale inconnue : {settings['max_duration']}")
    settings["count"] = int(settings["count"])
    if not 0 <= settings["count"] <= 10:
        raise ValueError("entre 1 et 10 shorts (0 = au choix de Claude)")
    return settings


def create_job(transcript_id: str, request: str, settings: dict, model: str | None) -> jobs.Job:
    source = jobs.get(transcript_id)
    if source is None or source.module != transcript.MODULE or source.status != "done":
        raise ValueError("transcript introuvable ou pas encore terminé")
    lines = lines_of(source)
    if not lines:
        raise ValueError("le transcript est vide")
    payload = {"name": transcript.name(source), "transcript_job": transcript_id, "model": model}
    state = {"settings": clean_settings(settings), "lines": lines, "shorts": [],
             "messages": [message("user", request.strip() or DEFAULT_REQUEST)], "session_id": None}
    return jobs.create(MODULE, KIND, payload, state)


def send(job: jobs.Job, text: str) -> None:
    """Nouveau message : le job repart en file pour un tour de plus."""
    job.state["messages"].append(message("user", text.strip()))
    jobs.update(job.id, state=job.state, status="queued", cancel_requested=False,
                error=None, finished_at=None)


def turn_prompt(job: jobs.Job, first: bool) -> str:
    request = job.state["messages"][-1]["text"]
    if first:
        return (f"Transcript ({len(job.state['lines'])} lignes) :\n\n"
                f"{format_lines(job.state['lines'])}\n\nDemande : {request}")
    return (f"Sélection actuelle :\n{selection_text(job.state['shorts'])}\n\n"
            f"Demande : {request}")


def fix_prompt(shorts: list[dict], problems: list[str]) -> str:
    return ("Durées recalculées à partir des timecodes :\n"
            f"{durations_text(shorts)}\n\nÀ corriger :\n" + "\n".join(f"- {p}" for p in problems)
            + "\n\nRenvoie la liste complète corrigée.")


# --- Montages ----------------------------------------------------------------

def render_dir(selection_id: str) -> Path:
    return WORK_DIR / selection_id


def padded(short: dict, lines: list[list]) -> list[list[float]]:
    """Les extraits avec un peu d'air autour, sans mordre sur la ligne voisine."""
    out = []
    for c in short["clips"]:
        before = c["start"] - (lines[c["from"] - 2][1] if c["from"] > 1 else 0.0)
        after = (lines[c["to"]][0] - c["end"]) if c["to"] < len(lines) else PAD_AFTER
        out.append([round(max(0.0, c["start"] - min(PAD_BEFORE, max(before, 0) / 2)), 3),
                    round(c["end"] + min(PAD_AFTER, max(after, 0) / 2), 3)])
    return out


def signature(clips: list[list[float]], fmt: str) -> str:
    return hashlib.sha1(json.dumps([clips, fmt]).encode()).hexdigest()[:12]


def renders(selection_id: str) -> dict[str, jobs.Job]:
    """Le dernier montage de chaque signature."""
    found = {}
    for j in jobs.list_jobs(MODULE):
        if j.kind == RENDER_KIND and j.payload["selection"] == selection_id:
            found[j.payload["signature"]] = j
    return found


def render_file(job: jobs.Job) -> Path:
    return render_dir(job.payload["selection"]) / f"{job.payload['signature']}.mp4"


def enqueue_render(selection: jobs.Job, short: dict, force: bool = False) -> None:
    fmt = {**DEFAULT_SETTINGS, **selection.state["settings"]}["format"]
    clips = padded(short, selection.state["lines"])
    sig = signature(clips, fmt)
    current = renders(selection.id).get(sig)
    if current and not force and current.status not in ("error", "cancelled"):
        return
    jobs.create(MODULE, RENDER_KIND, {
        "selection": selection.id, "signature": sig, "title": short["title"], "format": fmt,
        "clips": clips, "transcript_job": selection.payload["transcript_job"]}, {})


def mounted(selection: jobs.Job) -> list[dict]:
    """Les shorts envoyes au montage dans le format actuel (montage fait, en cours ou rate)."""
    fmt = {**DEFAULT_SETTINGS, **selection.state["settings"]}["format"]
    found = renders(selection.id)
    return [s for s in selection.state["shorts"]
            if signature(padded(s, selection.state["lines"]), fmt) in found]


def render_summary(job: jobs.Job | None) -> dict | None:
    if job is None:
        return None
    ready = job.status == "done" and render_file(job).is_file()
    return {"id": job.id, "status": job.status, "progress": job.progress, "error": job.error,
            "url": f"/api/shorts/renders/{job.id}/file?v={int(job.finished_at or 0)}" if ready else None}


def short_render(selection: jobs.Job, short: dict) -> jobs.Job | None:
    """Le montage termine de ce short dans le format choisi, s'il existe."""
    fmt = {**DEFAULT_SETTINGS, **selection.state["settings"]}["format"]
    job = renders(selection.id).get(signature(padded(short, selection.state["lines"]), fmt))
    return job if job and job.status == "done" and render_file(job).is_file() else None


def retimed(selection: jobs.Job, short: dict) -> tuple[list[dict], list[dict]]:
    """Mots et lignes du short, en temps du montage (0 = debut du short).

    Mots et lignes viennent du transcript tel qu'il est maintenant : les corrections
    faites depuis la selection se retrouvent dans les sous-titres et le .srt.
    """
    source = jobs.get(selection.payload["transcript_job"])
    segments = transcript_cues.load_segments(source.state["segments"]) if source else []
    all_words = [w for seg in segments for w in seg.words]
    # transcript supprime depuis : les lignes figees a la selection
    all_lines = (transcript_cues.build_cues(segments, "line") if segments else
                 [{"start": start, "end": end, "text": text} for start, end, text in selection.state["lines"]])
    words, lines, cursor = [], [], 0.0
    for a, b in padded(short, selection.state["lines"]):
        offset, end = cursor - a, cursor + b - a
        words += [{"text": w.text, "start": max(w.start + offset, cursor), "end": min(w.end + offset, end)}
                  for w in all_words if a <= (w.start + w.end) / 2 <= b]
        lines += [{"start": max(c["start"] + offset, cursor), "end": min(c["end"] + offset, end), "text": c["text"]}
                  for c in all_lines if a <= (c["start"] + c["end"]) / 2 <= b]
        cursor = end
    return words, lines


def remove_selection(job: jobs.Job) -> None:
    for render in renders(job.id).values():
        jobs.delete(render.id)
    shutil.rmtree(render_dir(job.id), ignore_errors=True)


def summary(job: jobs.Job) -> dict:
    s = job.state
    return {"id": job.id, "name": job.payload["name"], "transcript_job": job.payload["transcript_job"],
            "status": job.status, "error": job.error, "created_at": job.created_at,
            "count": len(s.get("shorts", []))}


def detail(job: jobs.Job) -> dict:
    from ..animations import service as animations

    s = job.state
    settings = {**DEFAULT_SETTINGS, **s["settings"]}
    done = renders(job.id)
    # le projet de sous-titres deja ouvert pour ce montage-la
    projects = animations.short_projects(job.id)
    shorts = []
    for short in s.get("shorts", []):
        render = done.get(signature(padded(short, s["lines"]), settings["format"]))
        shorts.append({**short, "render": render_summary(render),
                       # (projets d'avant le suivi des montages : rattaches au short seul)
                       "project": projects.get((short["id"], render.id)) or projects.get((short["id"], None))
                       if render else None})
    return {**summary(job), "settings": settings, "messages": s["messages"],
            "shorts": shorts, "activity": s.get("activity"),
            "model": s.get("model") or job.payload["model"], "usage": s.get("usage")}


def to_srt(selection: jobs.Job, short: dict) -> str:
    """Sous-titres du short monte : les lignes de chaque extrait, recalees bout a bout."""
    return transcript_cues.to_srt(retimed(selection, short)[1])
