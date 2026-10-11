"""
Créer l'animation d'un beat du storyboard : une tâche par beat, à part du chat du monteur. Le motion est
déjà posé dans la timeline (place, durée, son d'entrée : `storyboard.compose`) ; Daryl n'écrit que sa composition,
montage/motion/<id>.html, avec juste ce qu'il lui faut (la fiche du beat, les mots et leurs instants, le
contrat, la charte, le modèle du kit, les sons de la bibliothèque). Chaque beat écrit un fichier différent : plusieurs
tâches tournent en parallèle, SLOTS au plus (une file par place), les suivantes attendent.

Le sound design se fait en même temps que l'animation : Daryl note dans sa composition les sons calés sur sa
timeline GSAP (un bloc JSON `<script type="application/json" id="sfx">`), et le studio les pose dans la timeline à
la fin de la tâche, à la place des sons du motion (place_sounds).
"""
import json
import re

from ...core import jobs
from ...core.tasks import TaskContext
from ..settings.service import language_name
from . import montage, montage_tasks, service, storyboard

SLOTS = 3
KINDS = [f"project_beat_anim_{i}" for i in range(SLOTS)]

SOUND_RULES = """\
# Le sound design de ta composition
Tu fais aussi le son du motion, en même temps que l'animation : c'est toi qui connais ses instants. \
Note les sons dans la composition, dans un bloc à part (le rendu l'ignore) :
<script type="application/json" id="sfx">
[{"t": 1.19, "src": "library/sfx/whoosh-2.wav", "gain_db": -24, "why": "la fenêtre monte"},
 {"t": 2.66, "src": "library/sfx/es-crayon-circle.wav", "in": 0, "out": 0.7, "gain_db": -20, "why": "noms entourés"}]
</script>
- `t` : l'instant où le son DÉMARRE, en secondes depuis le début de la composition (peut être légèrement \
négatif). Un son frappe un peu après son début : la description donne son attaque (« attaque à 0,14 s », \
« pic à 2,66 s ») ; pour qu'il frappe sur l'événement, t = instant de l'événement − attaque.
- `src` : EXACTEMENT un son de la liste qui t'est donnée. `in` / `out` : le passage du fichier à jouer \
(par défaut tout le fichier) ; respecte les coupes que donne la description. `gain_db` : pars du volume \
par défaut du son, ajuste de quelques dB au plus.
- Un son par événement qui compte (un élément qui arrive, se pose, frappe, se transforme), pas un son par \
mouvement. Le silence est un choix : une composition calme peut n'avoir que deux ou trois sons, voire aucun \
(bloc vide : []).
- Discret : la voix passe avant tout. Les volumes restent bas ; une nappe éventuelle, très bas, jamais plus \
longue que la composition.
- Un seul point d'orgue fort par composition (impact, tampon), à l'instant clé ; superposer deux sons \
(un impact sourd + un son d'objet) le rend plus riche.
- Un son jamais plus long que ce qu'il accompagne : coupe-le avec `out`.
- Un whoosh accompagne une entrée ou un mouvement de caméra ; préfère whoosh.wav et whoosh-2.wav.
- Varie les volumes de 1 à 2 dB quand un même son se répète.
- Ce bloc remplace les sons du motion dans la timeline à chaque fois que tu écris la composition."""

SYSTEM = """\
Tu es Daryl, motion designer d'un créateur de vidéos YouTube éducatives. Tu écris UNE composition \
HyperFrames (HTML + GSAP), un visuel animé posé au-dessus de la vidéo pendant qu'il parle, à partir \
d'un beat de storyboard qu'il a validé, et son sound design. Suis « on montre » au plus près ; si \
quelque chose est impossible, fais au plus près et dis-le.

{rules}

{sound}

# Comment tu travailles
- Lis montage/motion/style.css (la charte) et le modèle du kit indiqué s'il y en a un, sinon un ou deux \
exemples de montage/motion/exemples/ pour le contrat technique et le niveau attendu.
- Écris montage/motion/<id>.html, et aucun autre fichier. Son bloc de sons vient en dernier, une fois \
l'animation finie : relis ta timeline GSAP pour en caler les instants.
- Ta réponse finale : en {lang}, une ou deux phrases sur ce que tu as fait."""


def job_id(pid: str, beat: str) -> str:
    return f"{pid}-anim-{beat}"


def _slot() -> str:
    """La file la moins chargée (tous projets confondus)."""
    load = {k: 0 for k in KINDS}
    for j in jobs.list_jobs(service.MODULE):
        if j.kind in load and not j.finished:
            load[j.kind] += 1
    return min(KINDS, key=lambda k: load[k])


def enqueue(pid: str, beat: str, motion: str) -> None:
    """Met en file la création de l'animation d'un beat (sauf si elle est déjà en cours)."""
    jid = job_id(pid, beat)
    job = jobs.get(jid)
    if job and not job.finished:
        return
    if job:
        jobs.delete(jid)
    jobs.create(service.MODULE, _slot(), {"project": pid, "beat": beat, "motion": motion,
                                          "dir": str(service.project_dir(pid))}, {}, job_id=jid)


def running(pid: str) -> set[str]:
    """Les motions dont la création est en file ou en cours (le chat du monteur n'y touche pas)."""
    board = storyboard.load(pid) or {"beats": []}
    out = set()
    for b in board["beats"]:
        job = jobs.get(job_id(pid, b["id"]))
        if job and not job.finished:
            out.add(job.payload.get("motion"))
    return out


def states(pid: str, beats: list[dict]) -> dict:
    """L'état de la création de chaque beat qui en a une : {beat: {status, activity, error}}. Une création
    finie sans erreur n'y figure plus (le beat est animé)."""
    out = {}
    for b in beats:
        job = jobs.get(job_id(pid, b["id"]))
        if not job or job.status == "done":
            continue
        status = job.status if job.status in ("queued", "error", "cancelled") else "running"
        out[b["id"]] = {"status": status, "activity": job.state.get("activity"), "error": job.error}
    return out


def prompt(pid: str, beat: dict, motion: dict) -> str:
    project = service.load(pid)
    timeline = montage.load(pid)
    words = storyboard.timeline_words(project, timeline)
    start, end = motion["at"], motion["at"] + motion["dur"]
    spoken = [w for w in words if w.end > start - 0.3 and w.start < end + 0.3]
    mid = motion["id"]
    parts = [f"Compose montage/motion/{mid}.html (data-composition-id=\"{mid}\", data-duration=\"{motion['dur']:.2f}\").",
             "", storyboard.brief(pid, [mid]), "",
             "Ce qu'il dit pendant le beat, mot à mot (instant du mot en secondes depuis le début de la "
             "composition ; négatif : juste avant) :",
             " ".join(f"{w.text.strip()}@{w.start - start:.2f}" for w in spoken if w.text.strip()), ""]
    palette = sounds(pid)
    if palette:
        parts += ["Les sons disponibles pour le sound design (`src` exact · durée · volume par défaut · description) :",
                  *(f"- {s['src']} · {s['duration']:.2f} s · {s['gain_db']:g} dB" + (f" · {s['description']}" if s["description"] else "")
                    for s in palette)]
    else:
        parts += ["Aucun son disponible : écris un bloc de sons vide."]
    return "\n".join(parts)


# --- Le sound design du motion -----------------------------------------------------------------

SFX_BLOCK = re.compile(r'<script[^>]*\bid=["\']sfx["\'][^>]*>(.*?)</script>', re.S | re.I)
SFX_GAIN = -20.0


def sounds(pid: str) -> list[dict]:
    """Les sons que Daryl peut employer : ceux de la bibliothèque (décrits), puis ceux du projet qui n'en sont pas une copie.
    Chacun {src, duration, gain_db, description}."""
    sfx = [m for m in montage.available(pid) if m["category"] == "sfx"]
    common = {m["name"] for m in sfx if m["where"] == "bibliothèque"}
    return [{"src": m["src"], "duration": m["duration"] or 0.0, "gain_db": m.get("gain_db", SFX_GAIN),
             "description": m.get("description", "")}
            for m in sorted(sfx, key=lambda m: m["where"] != "bibliothèque")
            if m["where"] == "bibliothèque" or m["name"] not in common]


def cues(pid: str, mid: str) -> list[dict] | None:
    """Les sons notés dans montage/motion/<mid>.html ; None si elle n'en note pas (ou pas lisiblement)."""
    path = montage.motion_dir(pid) / f"{mid}.html"
    found = SFX_BLOCK.search(path.read_text(encoding="utf-8")) if path.is_file() else None
    if not found:
        return None
    try:
        raw = json.loads(found.group(1).strip() or "[]")
    except json.JSONDecodeError:
        return None
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else None


def place_sounds(pid: str, mid: str) -> int | None:
    """Pose dans la timeline les sons notés dans la composition du motion `mid`, à la place de ceux qui lui sont
    rattachés (son ancien sound design, le son d'entrée du storyboard). Rend le nombre de sons posés ; None si la
    composition n'en note pas : ses sons restent alors tels quels."""
    noted = cues(pid, mid)
    if noted is None:
        return None
    timeline = montage.load(pid)
    motion = next((m for m in timeline["motion"] if m["id"] == mid), None)
    if not motion:
        return None
    placed = []
    for c in noted:
        try:
            t = float(c.get("t", 0))
            gain = float(c.get("gain_db", SFX_GAIN))
            a = max(0.0, float(c.get("in") or 0))
            b = float(c["out"]) if c.get("out") is not None else None
        except (TypeError, ValueError):
            continue
        # un son peut démarrer juste avant la composition, pas après sa fin
        if not -1.0 <= t < motion["dur"]:
            continue
        # sans `out` : tout le fichier (borné par sa durée au nettoyage)
        placed.append({"src": str(c.get("src") or ""), "at": round(max(0.0, motion["at"] + t), 3), "in": a,
                       "out": b if b is not None else a + 60, "gain_db": gain, "role": "sfx", "motion": mid})
    timeline["audio"] = [s for s in timeline["audio"] if s.get("motion") != mid] + placed
    # nettoyée à l'enregistrement : un son inconnu disparaît, un son de la bibliothèque est copié dans le projet
    saved = montage.save(pid, timeline)
    return sum(1 for s in saved["audio"] if s.get("motion") == mid)


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p, state = ctx.payload, ctx.state
    pid, beat_id, mid = p["project"], p["beat"], p["motion"]
    board = storyboard.load(pid) or {"beats": []}
    beat = next((b for b in board["beats"] if b["id"] == beat_id), None)
    motion = next((m for m in montage.load(pid)["motion"] if m["id"] == mid), None)
    if not beat or not motion:
        raise RuntimeError("Le beat ou son motion n'existe plus.")
    montage.prepare(pid)
    target = montage.motion_dir(pid) / f"{mid}.html"
    before = target.stat().st_mtime if target.is_file() else None
    state["activity"] = "lit la charte"
    ctx.save(force=True)
    out = ask(ctx, prompt(pid, beat, motion),
              SYSTEM.format(rules=montage_tasks.MOTION_RULES, sound=SOUND_RULES, lang=language_name()),
              "Read,Write,Edit,Glob")
    if not target.is_file() or target.stat().st_mtime == before:
        raise RuntimeError("Daryl n'a pas écrit la composition." + (f" Il dit : {out['text'][:300]}" if out["text"] else ""))
    state["reply"] = out["text"].strip()
    state["activity"] = None
    # ses sons entrent dans la timeline (l'enregistrement relance aussi le rendu et l'export)
    if place_sounds(pid, mid) is None:
        montage.after_change(pid)
