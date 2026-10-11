"""
Côté worker, pour le montage de la vidéo longue :
- le monteur : un tour de `claude -p` dans le dossier du projet, qui modifie la timeline et
  écrit les compositions de motion design ;
- le rendu d'une composition en .mov ProRes 4444 avec transparence (HyperFrames) ;
- la forme d'onde et les vignettes de la vidéo source (ffmpeg).
"""
import json
import math
import subprocess
import time
from pathlib import Path

from ...core import claude, jobs
from ...core.system import tool
from ...core.tasks import TaskContext
from ..animations import render as hyperframes
from ..settings.service import language, language_name
from . import montage, service, transitions

MOTION_RULES = """\
# Contrat d'une composition de motion design (montage/motion/<id>.html)
- Charge style.css (même dossier : <link rel="stylesheet" href="style.css">) et GSAP \
(https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js). Lis montage/motion/exemples/ avant ta \
première composition : elles montrent le contrat technique et le niveau attendu.
- Racine : <div id="stage" class="youtube" data-composition-id="<id>" data-duration="<dur>" \
data-hero="<instant où elle est la plus complète>">, 1920×1080 px, fond TRANSPARENT : elle est \
rendue en .mov avec alpha et posée au-dessus de la vidéo dans Resolve.
- Une seule timeline : `const tl = gsap.timeline({ paused: true })`, enregistrée dans \
`window.__timelines["<id>"] = tl`, construite de façon synchrone. Jamais tl.play(), pas de \
setTimeout, de Date.now(), de Math.random(), de repeat infini.
- Temps 0 = début du motion (son `at` dans la timeline). Cale chaque étape sur le mot prononcé : \
(instant du mot dans contexte.md) − at.
- Apparitions sûres au seek : gsap.set(el, {autoAlpha: 0}) au départ, puis tl.to(el, {autoAlpha: 1}) \
+ un fromTo pour le mouvement. Anime transform et opacity, pas width/height/top/left.
- Entrée ET sortie animées dans la composition (c'est la transition) : sortie dans les 0,4 dernières \
secondes. Garde 80 px de marge avec les bords. Respecte la place du beat (plein écran, tiers gauche \
ou droit, bandeau haut ou bas) : hors plein écran, rien ne passe sur le visage.
- Pas une pastille de texte : schéma, chiffre qui se construit, liste qui se coche, comparaison, \
chronologie…
- Montre, ne dis pas. Le spectateur entend déjà la voix et voit déjà l'image : un texte qui redit l'une \
ou l'autre est du bruit. Il dit « je joue aux jeux vidéo et je regarde des animes » → on voit des jeux \
vidéo puis des animes, sans « Jeux vidéo » écrit dessous. Pas d'étiquette sous une image ou une icône \
qui se reconnaît, pas de titre qui annonce ce que la composition montre, pas de phrase qu'il prononce \
recopiée, pas de légende qui commente.
- Pas de sur-titre (.kicker) ni d'étiquette qui explique ce qu'on regarde ou le lien entre deux \
éléments (« Vrai nom », « Avant », « Résultat », « Cause », « Le problème ») : c'est l'aveu que \
l'animation n'a pas montré ce lien. Le lien passe par le mouvement. Voltaire, pseudonyme de \
François-Marie Arouet : le nom « Voltaire » se soulève comme un masque et découvre « François-Marie \
Arouet » dessous ; ces deux noms suffisent, sans « Vrai nom » ni « Pseudonyme ». Un avant / après : \
l'un se transforme en l'autre. Une cause : une flèche, un élément qui en pousse un autre.
- Test, pour chaque texte : si on l'enlève, le spectateur, qui entend la voix et voit le reste de \
l'image, perd-il une information ? Sinon, enlève-le. Restent en général : un chiffre ou une date \
(le compteur, c'est le visuel), un nom propre qu'on ne reconnaîtrait pas, ce qu'on ne peut pas \
dessiner. Ce texte-là est court et se lit d'un coup d'œil.
- Composition écrite, relis-la texte par texte (chaque nœud qui affiche des mots, y compris \
.kicker, étiquettes, légendes) et applique le test ; supprime ce qui ne le passe pas avant de rendre.
- Une idée par composition. Chaque élément apparaît 0,2 s avant le mot qui le nomme. Un mouvement de \
caméra ou un changement de focus ARRIVE sur le mot qui nomme sa cible (il part 0,3 à 0,5 s avant, pas \
pendant les phrases d'avant) : tant qu'il parle d'autre chose, le cadre reste sur ce dont il parle. La sortie dure \
environ 75 % de l'entrée. Pas d'oscillation décorative (ni repeat: -1 ni yoyo). Avant le moment fort, \
0,3 à 0,75 s d'immobilité.
- La timeline doit couvrir toute la durée : ajoute `tl.to({}, {duration: <dur>}, 0)`, sinon l'image \
devient noire avant la fin.
- Une vidéo ou une image de contexte.md dans la composition : `src="media/<id>-<nom court sans espace>.<ext>"` \
et `data-from="<son src exact listé dans contexte.md>"`, sur la balise elle-même (<video>, <img>). Le studio \
copie le fichier à cet endroit ; tu ne peux pas copier de fichier toi-même. Une vidéo : `muted`, avec \
data-start / data-duration (et data-media-start pour partir plus loin dans le média)."""

TRANSITIONS = "\n".join(transitions.prompt_lines())


def system_prompt(project: dict, work: str, ids: list[str]) -> str:
    """`work` : le dossier de travail de la demande (relatif au projet) ; `ids` : les ids de motion qui lui sont
    réservés."""
    return f"""\
Tu es le monteur d'un créateur de vidéos YouTube. Il est ton client : il te demande des \
changements dans le chat et voit ta timeline en direct dans son interface. Tu montes la vidéo \
longue « {project.get("title") or ""} » : plans de coupe (B-roll), zooms, motion design, \
sound design, musique, chapitres. Vise le niveau d'un monteur professionnel de chaîne \
éducative : rythmé, lisible, jamais gratuit.

# Fichiers (dossier courant = le dossier du projet)
- {work}/contexte.md : régénéré avant chaque demande. Le transcript EN TEMPS DE LA TIMELINE, \
les chapitres, la liste exacte des médias utilisables (B-roll, musique, sons) avec leur durée, \
et la sélection faite par le client dans la timeline. Lis-le en premier.
- {work}/timeline.json : ta copie de travail de la timeline, que tu modifies (Edit de \
préférence, ou Write du fichier entier). Le client continue de monter à la main pendant que tu \
travailles, dans sa propre timeline (montage/timeline.json : n'y touche pas) ; le studio fusionne \
ta copie dans la sienne à la fin de ton tour. D'autres de ses demandes sont peut-être traitées en \
même temps, chacune dans sa copie, sur d'autres passages. Ne change que ce que la demande implique : \
ce que tu laisses tel quel garde ses retouches et celles des autres demandes.
- montage/motion/<id>.html : une composition HyperFrames par motion design (voir le contrat).
- {work}/insertions.json : pour insérer un clip dans l'A-roll (voir plus bas). Le studio l'applique \
et l'efface aussitôt écrit.

# La timeline ({work}/timeline.json)
Temps de la timeline en secondes (`at`, `dur`, `t`) ; `in`/`out` : temps dans le média.
{{
  "aroll":   [{{"id": "a1", "in": 0, "out": 264.25, "transition": null}}, {{"id": "a2", "src": "assets/broll/extrait.mp4", "in": 0, "out": 3.9, "transition": null, "gain_db": -3}}, {{"id": "a3", "in": 264.25, "out": 754.2, "transition": null}}],
  "zooms":   [{{"id": "z1", "at": 31.2, "dur": 4.5, "scale": 1.25, "x": 0, "y": -0.05}}],
  "broll":   [{{"id": "b1", "src": "assets/broll/ville.mp4", "at": 42.0, "in": 3.0, "out": 7.5, "enter": {{"fx": "wipeleft", "dur": 0.5}}}}],
  "motion":  [{{"id": "m1", "at": 60.4, "dur": 7.0, "title": "nom court", "kind": "schéma", "idea": "ce qu'il montre"}}],
  "audio":   [{{"id": "s1", "src": "library/sfx/whoosh.wav", "at": 60.2, "in": 0, "out": 1.1, "gain_db": -10, "role": "sfx"}}],
  "texts":   [{{"id": "t1", "at": 75.0, "dur": 3.0, "text": "« vingt-cinq millisecondes »", "x": 0.5, "y": 0.8, "size": 0.075, "color": "#FFFFFF", "angle": -4}}],
  "markers": [{{"id": "k1", "t": 0, "text": "Introduction", "kind": "chapter", "by": "ai", "done": false}}]
}}
- aroll : la vidéo source (dérushée en amont : les hésitations sont déjà coupées), bout à bout. N'y \
touche que sur demande explicite. Une coupe = deux clips ; "transition" : la transition avec le clip \
précédent (null : coupe franche). Un clip avec `src` est un autre média inséré dans l'A-roll (un extrait, \
une archive) : il passe en plein écran AVEC SON SON, la voix du client s'arrête le temps du clip ; pas de \
transition avec lui. `gain_db` : le volume d'un clip (−20 à +12, absent : 0) ; tu peux le changer directement.
- Insérer un clip dans l'A-roll (« mets l'extrait X à tel moment ») : ne le fais JAMAIS à la main dans \
ta copie (il faudrait décaler tout ce qui suit). Écris {work}/insertions.json : \
[{{"src": "<chemin listé dans contexte.md>", "at": <instant de la timeline, de préférence dans un silence \
entre deux phrases>, "in": 0, "out": <durée du média>, "gain_db": 0}}]. Le studio coupe l'A-roll à `at`, \
insère le clip et décale tout ce qui suit (zooms, B-roll, motions, sons, marqueurs, storyboard). Ensuite \
RELIS {work}/timeline.json (elle a changé) avant toute autre modification : le clip y est, avec son id ; les temps \
d'après sont décalés de sa durée. Ajoute alors ce qui l'accompagne (un whoosh à l'entrée et à la sortie, \
par exemple) en temps de la timeline à jour.
- zooms : recadrage progressif de l'A-roll (montée et descente de 0,4 s faites à l'export). \
scale 1.1 à 1.4 ; x, y : décalage du centre en fraction de l'image (−0.5 à 0.5).
- broll : plan de coupe muet qui couvre l'A-roll (la voix continue). `src` : EXACTEMENT un \
chemin listé dans contexte.md ; in/out dans la durée du média. 2 à 6 s en général.
- motion : `id` nouveau, pris dans les ids qui te sont réservés pour cette demande, dans l'ordre : \
{", ".join(ids)} (les autres demandes en cours ont les leurs), puis écris montage/motion/<id>.html. \
Durée = celle de la composition (data-duration).
- audio : sons (role "sfx", −8 à −14 dB) et musique (role "music", −20 à −26 dB sous la voix) ; \
quand contexte.md donne un volume (« à poser à … dB »), c'est celui-là. \
`src` : un chemin listé dans contexte.md (un son de la bibliothèque « library/… » est copié \
dans le projet automatiquement). Un whoosh accompagne bien l'entrée d'un motion ou d'un B-roll \
(il démarre 0,1 à 0,2 s avant).
- texts : des notes écrites à la main par le client, à l'écran (corriger un mot mal audible, préciser). \
x, y : le centre du texte (fraction de l'image, 0 à 1) ; size : hauteur de la police (fraction de la hauteur \
de l'image) ; angle en degrés. Ce sont SES notes : garde-les telles quelles, n'en ajoute ou n'en change que \
sur demande explicite.
- markers : les chapitres (kind "chapter", ils deviennent les chapitres YouTube) ; les tiens ont "by": "ai".
- Ids uniques. Pas de chevauchement sur une même piste (B-roll, motion).

# Transitions
`transition` (A-roll), `enter` et `exit` (B-roll, motion) : {{"fx": <id>, "dur": 0.2 à 2 s}}, ou absent \
pour une coupe franche (souvent la bonne réponse : une transition doit servir le récit). L'entrée se \
joue sur les premières `dur` secondes du plan, depuis ce qui est dessous ; la sortie sur ses \
dernières. Un plan collé au précédent de la même piste (son `at` = la fin de l'autre) s'enchaîne avec \
lui par son `enter`, centré sur la coupe. Un motion anime déjà son entrée et sa sortie : ne lui en \
ajoute que sur demande. Varie : pas le même fondu partout ; une poussée ou un balayage dans le sens \
du propos, un passage par le noir pour un changement de partie, un iris pour isoler un détail. \
Les transitions disponibles :
{TRANSITIONS}

{MOTION_RULES}

# Comment tu travailles
- Une demande peut porter sur la sélection du client (plage de temps ou élément) : elle est \
indiquée dans contexte.md et dans le message. Tiens-t'en à cette portée.
- Les motions d'ensemble viennent du storyboard que le client a validé ; leurs animations sont créées \
par des tâches à part. Un motion en cours de création (listé dans contexte.md) : n'y touche pas.
- Pour une demande précise du client (« un zoom ici », « remplace ce B-roll », « corrige ce motion »), \
fais-la directement : modifie {work}/timeline.json (le client voit tes changements à la fin \
de ton tour), puis écris les compositions. Ne lance pas de création d'ensemble de toi-même : propose plutôt de passer par \
le storyboard.
- Ne crée ni ne modifie aucun autre fichier que {work}/timeline.json, {work}/insertions.json \
et montage/motion/*.html.
- Si un média manque (pas de B-roll adapté, pas de son), dis-le dans ta réponse plutôt que \
d'inventer un chemin.
- Ta réponse finale : en {language_name()}, 2 à 5 phrases, ce que tu as fait et où (timecodes)."""


def _mmss(sec: float) -> str:
    return f"{int(sec // 60):02d}:{sec % 60:04.1f}"


# une transition sélectionnée dans la timeline : le champ qui la porte
FX_FIELDS = {"transition": "`transition` (avec le clip précédent)", "enter": "d'entrée (`enter`)", "exit": "de sortie (`exit`)"}


def _item_scope(item: dict) -> str:
    """L'élément sélectionné, ou l'une de ses transitions, en une phrase."""
    what = f"l'élément {item.get('id')} (piste {item.get('track')})"
    fx = FX_FIELDS.get(item.get("fx") or "")
    return f"la transition {fx} de {what} : ne change que ce champ, sauf demande contraire" if fx else what


def write_context(pid: str, selection: dict | None, path: Path) -> None:
    """contexte.md (`path`) : ce que Claude doit savoir avant chaque demande."""
    project = service.load(pid)
    from . import runtime

    timeline = montage.load(pid)
    source = runtime.source_transcript(project) or {}
    lines = montage.transcript_lines(project, timeline, source.get("lines") or [])
    total = sum(c["out"] - c["in"] for c in timeline["aroll"])
    parts = [f"# Contexte du montage\n\nDurée de la timeline : {_mmss(total)} ({total:.1f} s).\n"]
    if selection:
        if selection.get("range"):
            a, b = selection["range"]
            parts.append(f"## Sélection du client\nPlage {_mmss(a)} → {_mmss(b)} ({a:.2f} → {b:.2f} s).\n")
        if selection.get("item"):
            scope = _item_scope(selection["item"])
            parts.append(f"## Sélection du client\n{scope[0].upper()}{scope[1:]}.\n")
    inserted, cursor = [], 0.0
    for c in timeline["aroll"]:
        if c.get("src"):
            inserted.append(f"- {c['id']} · {_mmss(cursor)} → {_mmss(cursor + c['out'] - c['in'])} · {c['src']}"
                            + (f" · {c['gain_db']:+.0f} dB" if c.get("gain_db") else ""))
        cursor += c["out"] - c["in"]
    if inserted:
        parts.append("## Clips insérés dans l'A-roll (absents du transcript)\n" + "\n".join(inserted) + "\n")
    chapters = [k for k in timeline["markers"] if k["kind"] == "chapter"]
    if chapters:
        parts.append("## Chapitres\n" + "\n".join(f"- {_mmss(k['t'])} {k['text']}" for k in chapters) + "\n")
    from . import storyboard

    plans = storyboard.script_plans(pid, storyboard.timeline_words(project, timeline))
    if plans:
        parts.append("## Plans prévus dans le script par le client (à respecter)\n" + "\n".join(
            f"- {_mmss(p['at']) + ' → ' + _mmss(p['end']) if p['at'] is not None else 'passage introuvable'} "
            f"{p['type']} : {p['note'] or '(sans note)'} · passage « {p['passage'][:160]} »" for p in plans) + "\n")
    from . import beat_anim

    busy = sorted(m for m in beat_anim.running(pid) if m)
    if busy:
        parts.append("## Motions en cours de création (n'y touche pas)\n" + ", ".join(busy) + "\n")
    parts.append("## Médias utilisables (src · durée · à quoi il sert)")
    for category, label in (("broll", "B-roll"), ("musique", "Musique"), ("sfx", "Sons")):
        items = [m for m in montage.available(pid) if m["category"] == category]
        parts.append(f"### {label}\n" + ("\n".join(
            f"- {m['src']} · {m['duration'] or 0:.1f} s"
            + (f" · à poser à {m['gain_db']:+.0f} dB" if m.get("gain_db") is not None else "")
            + (f" · {m['description']}" if m.get("description") else "")
            for m in items) if items else "(aucun)"))
    parts.append("\n## Transcript (temps de la timeline)\n" + "\n".join(
        f"[{_mmss(l['start'])} → {_mmss(l['end'])}] {l['text']}" for l in lines))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _label(block: dict) -> str:
    args = block.get("input") or {}
    target = args.get("file_path") or args.get("pattern") or ""
    shown = Path(target).name if "file_path" in args else target
    verb = {"Write": "écrit", "Edit": "retouche", "Read": "lit"}.get(block.get("name", ""), block.get("name", ""))
    return f"{verb} {shown}".strip()


# une image en pause : le passage autour d'elle (s), pour savoir si deux demandes se recoupent
FRAME_SPAN = 1.0
WAIT_POLL = 2.0


def _span(pid: str, request: dict) -> list[float] | None:
    """Le passage de la timeline sur lequel porte une demande ; None : toute la vidéo."""
    selection = request.get("selection") or {}
    if selection.get("range"):
        return [float(x) for x in selection["range"]]
    if selection.get("item"):
        item = selection["item"]
        timeline = montage.load(pid)
        if item.get("track") == "aroll":
            for c, start in zip(timeline["aroll"], montage._starts(timeline["aroll"])):
                if c["id"] == item.get("id"):
                    return [start, start + c["out"] - c["in"]]
        for x in timeline.get(item.get("track")) or []:
            if x["id"] == item.get("id"):
                at = x.get("at", x.get("t", 0.0))
                return [at, at + (x["dur"] if "dur" in x else x.get("out", 0.0) - x.get("in", 0.0))]
    if request.get("frame") is not None:
        return [float(request["frame"]) - FRAME_SPAN, float(request["frame"]) + FRAME_SPAN]
    return None


def _overlap(a: list[float] | None, b: list[float] | None) -> bool:
    return a is None or b is None or (a[0] < b[1] and b[0] < a[1])


def _wait_turn(ctx: TaskContext, pid: str) -> None:
    """Plusieurs demandes tournent à la fois ; une demande attend que celles parties avant elle sur le même passage
    (ou sur toute la vidéo) soient finies, pour partir de la timeline où elles sont fusionnées."""
    me = jobs.get(ctx.job.id)
    order = (me.started_at or 0, me.id)
    while True:
        before = [j for j in jobs.list_jobs(service.MODULE)
                  if j.kind in montage.TASK_KINDS and j.payload.get("project") == pid and j.id != me.id
                  and not j.finished and j.status != "queued" and ((j.started_at or 0), j.id) < order]
        # « span » absent (la demande n'a pas encore dit sur quoi elle porte) : comme toute la vidéo
        if not any(_overlap(ctx.state["span"], j.state.get("span")) for j in before):
            return
        ctx.state["activity"] = "attend la fin d'une demande sur le même passage"
        ctx.save(force=True)
        ctx.check_cancel()
        time.sleep(WAIT_POLL)


def _composition(pid: str, block: dict) -> str | None:
    """La composition qu'écrit un Write ou un Edit de Daryl (son nom de fichier), sinon None."""
    if block.get("name") not in ("Write", "Edit"):
        return None
    target = Path((block.get("input") or {}).get("file_path") or "")
    if not target.is_absolute():
        target = service.project_dir(pid) / target
    return target.name if target.suffix == ".html" and target.parent.resolve() == montage.motion_dir(pid).resolve() else None


def chat(ctx: TaskContext) -> None:
    state, pid = ctx.state, ctx.payload["project"]
    # la demande : son dossier de travail (daryl/<demande>/), à part de ceux des demandes qui tournent en même temps
    task = ctx.job.id.rsplit("-", 1)[-1]
    messages = state["messages"]
    while messages and messages[-1]["role"] == "ai":
        messages.pop()
    request = messages[-1]
    state["span"] = _span(pid, request)
    _wait_turn(ctx, pid)
    montage.prepare(pid)
    if not (montage.root(pid) / montage.TIMELINE_FILE).is_file():
        montage.save(pid, montage.load(pid), keep_history=False)
    # Daryl travaille sur une copie : le client continue de monter à la main, les deux sont fusionnées à la fin
    ids = montage.start_work(pid, task)
    work = montage.work_dir(pid, task).relative_to(service.project_dir(pid)).as_posix()
    write_context(pid, request.get("selection"), montage.work_dir(pid, task) / "contexte.md")
    touched: set[str] = set()

    reply = {"role": "ai", "text": "", "tools": [], "at": time.time()}
    messages.append(reply)
    state["activity"] = "lit la timeline"
    ctx.set_status("thinking")
    ctx.save(force=True)

    scope = ""
    # « selection » peut valoir None (demande sur toute la vidéo, ou composition de beats)
    selection = request.get("selection") or {}
    if selection.get("range"):
        a, b = selection["range"]
        scope = f"Portée : la plage {_mmss(a)} → {_mmss(b)} de la timeline.\n\n"
    elif selection.get("item"):
        scope = f"Portée : {_item_scope(selection['item'])}.\n\n"
    if request.get("frame") is not None:
        scope += _frame_scope(pid, float(request["frame"]), request.get("image"))
    prompt = f"Lis {work}/contexte.md puis {work}/timeline.json.\n\n{scope}Demande : {request['text']}"
    project = service.load(pid)
    insertions = montage.work_dir(pid, task) / montage.INSERTIONS_FILE
    try:
        for event in claude.stream(prompt, service.project_dir(pid), system_prompt(project, work, ids),
                                   state.get("session_id"), None, ctx.check_cancel):
            # une insertion demandée : appliquée tout de suite, pour que Daryl relise sa copie à jour
            if insertions.is_file():
                _insert(pid, task, reply)
                ctx.save(force=True)
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                state["session_id"] = event["session_id"]
                ctx.save(force=True)
            elif kind == "stream_event":
                e = event["event"]
                block = e.get("content_block") or {}
                if e["type"] == "content_block_start" and block.get("type") == "thinking":
                    state["activity"] = "réfléchit"
                    ctx.save(force=True)
                elif e["type"] == "content_block_start" and block.get("type") == "tool_use":
                    ctx.set_status("working")
                    state["activity"] = _label({"name": block.get("name")})
                    ctx.save(force=True)
                elif (e.get("delta") or {}).get("type") == "text_delta":
                    ctx.set_status("writing")
            elif kind == "assistant":
                for block in event["message"]["content"]:
                    if block["type"] == "tool_use":
                        if comp := _composition(pid, block):
                            touched.add(comp)
                        label = _label(block)
                        reply["tools"].append(label)
                        state["activity"] = label
                        ctx.save(force=True)
            elif kind == "rate_limit_event":
                windows = event["rate_limit_info"].get("unifiedWindows") or {}
                state["usage"] = {k: w.get("utilization") for k, w in windows.items()}
            elif kind == "result":
                if event.get("is_error"):
                    raise RuntimeError(event.get("result") or "Claude a renvoyé une erreur")
                reply["text"] = (event.get("result") or "").strip()
    finally:
        state["activity"] = None
        if insertions.is_file():
            _insert(pid, task, reply)
        _apply(pid, task)
        changed, kept = montage.finish_work(pid, task, touched)
        # les médias de ses compositions, copiés à côté d'elles avant l'aperçu et le rendu
        for comp in sorted(touched):
            kept += montage.bring_media(pid, comp)
        if changed:
            montage.after_change(pid)
        problems = reply.pop("problems", []) + kept
        if problems:
            reply["text"] = (reply["text"] + "\n\n" + "\n".join(f"⚠ {p}" for p in problems)).strip()
        reply["changed"] = changed


def _frame_scope(pid: str, t: float, image: str | None) -> str:
    """Le client a mis en pause sur une image pour en parler : le moment, ce qui est à l'écran,
    et l'image à lire : celle de son aperçu (`image`), sinon l'A-roll seul extrait de la source."""
    from .storyboard_chat import grab_frame

    timeline = montage.load(pid)
    on = [f"zoom {z['id']} ×{z['scale']:.2f}" for z in timeline["zooms"] if z["at"] <= t < z["at"] + z["dur"]]
    on += [f"B-roll {b['id']} ({b['src']})" for b in timeline["broll"] if b["at"] <= t < b["at"] + b["out"] - b["in"]]
    on += [f"motion {m['id']} « {m['title']} » (montage/motion/{m['id']}.html, à {t - m['at']:.2f} s de son début)"
           for m in timeline["motion"] if m["at"] <= t < m["at"] + m["dur"]]
    on += [f"son {s['id']} ({s['src']})" for s in timeline["audio"] if s["at"] <= t < s["at"] + s["out"] - s["in"]]
    on += [f"texte {x['id']} « {x['text']} »" for x in timeline["texts"] if x["at"] <= t < x["at"] + x["dur"]]
    if image:
        seen = (f"L'image telle que le client la voit dans l'aperçu (zoom, B-roll, motion, beats pas encore "
                f"créés montrés en slide) : {image} (lis-la).\n")
    else:
        frame = grab_frame(pid, t)
        seen = f"L'image de l'A-roll à ce moment (sans zoom ni calques) : {frame} (lis-la).\n" if frame else ""
    return (f"Moment : le client a mis en pause à {_mmss(t)} ({t:.2f} s de la timeline) et sa demande "
            f"porte sur cette image. À l'écran à ce moment : {', '.join(on) if on else 'l’A-roll seul'}.\n"
            + seen + "\n")


def _insert(pid: str, task: str, reply: dict) -> None:
    """Les clips que Daryl a demandé d'insérer dans l'A-roll ; ce qui a échoué s'ajoute à sa réponse."""
    problems = montage.apply_insertions(pid, task)
    reply["tools"].append("insère un clip dans l'A-roll")
    if problems:
        reply.setdefault("problems", []).extend(problems)


def _apply(pid: str, task: str) -> None:
    """Fin de tour : la copie écrite par Claude est nettoyée (ids, bornes, médias copiés).
    Pas pendant le tour : réécrire le fichier ferait échouer ses Edit suivants."""
    try:
        raw = json.loads(montage.work_file(pid, task).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    project = service.load(pid)
    cleaned = montage.clean(pid, raw, (montage._source(project) or {}).get("duration") or 0.0)
    if cleaned != raw:
        montage._dump(montage.work_file(pid, task), cleaned)


# --- Rendu d'un motion design --------------------------------------------------------------

def _index(directory: Path, comp: str, duration: float) -> None:
    (directory / "index.html").write_text(f"""<!doctype html>
<html lang="{language()}">
<head>
<meta charset="utf-8">
<!-- généré par le studio pour le rendu d'un motion design -->
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
html, body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; }}
.layer {{ position: absolute; inset: 0; font-family: "Space Grotesk", "Inter", system-ui, sans-serif; }}
.fonts-charte-mono {{ font-family: "JetBrains Mono"; }}
</style>
</head>
<body>
<div id="root" data-composition-id="root" data-width="1920" data-height="1080" data-duration="{duration:.3f}">
  <div id="motion" class="layer" data-composition-id="{comp}" data-composition-src="{comp}.html" data-start="0" data-duration="{duration:.3f}"></div>
</div>
<script>
  const tl = gsap.timeline({{ paused: true }});
  tl.set({{}}, {{}}, {json.dumps(round(duration, 3))});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["root"] = tl;
</script>
</body>
</html>
""", encoding="utf-8")


def render_motion(ctx: TaskContext) -> None:
    p = ctx.payload
    pid, item_id, sig = p["project"], p["motion"], p["signature"]
    directory = montage.motion_dir(pid)
    output = montage.motion_render_file(pid, item_id, sig)
    missing = montage.bring_media(pid, f"{item_id}.html")
    if missing:
        raise RuntimeError("; ".join(missing) + " : indique son src dans data-from")
    _index(directory, item_id, p["duration"])
    ctx.set_status("rendering")

    def on_progress(value: float, stage: str) -> None:
        ctx.progress = value
        ctx.state["stage"] = stage
        ctx.save()

    output.parent.mkdir(parents=True, exist_ok=True)
    extra = ["--format", "mov"]
    if p.get("width", 1920) >= 3840:
        extra += ["--resolution", "landscape-4k"]
    hyperframes.render(directory, output, on_progress, ctx.check_cancel, extra)
    # les rendus précédents de ce motion ne servent plus
    for old in output.parent.glob(f"{item_id}-*.mov"):
        if old != output:
            old.unlink(missing_ok=True)
    try:
        montage.export(pid)
    except Exception:  # noqa: BLE001
        pass


# --- Forme d'onde et vignettes ------------------------------------------------------------

def media(ctx: TaskContext) -> None:
    p = ctx.payload
    ctx.set_status("running")
    peaks, strip = Path(p["peaks"]), Path(p["filmstrip"])
    peaks.parent.mkdir(parents=True, exist_ok=True)
    if not peaks.is_file():
        proc = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", p["path"], "-vn", "-ac", "1",
                               "-ar", str(montage.PEAKS_RATE * 50), "-f", "s16le", "-"], capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg : {proc.stderr.decode(errors='replace')[-300:]}")
        peaks.write_text(json.dumps(montage.compute_peaks(proc.stdout)), encoding="utf-8")
    ctx.progress = 0.3
    ctx.save(force=True)
    ctx.check_cancel()
    if not strip.is_file():
        step = montage.filmstrip_step(p["duration"])
        count = max(1, math.ceil(p["duration"] / step))
        rows = math.ceil(count / montage.FILMSTRIP_COLS)
        height = montage.FILMSTRIP_HEIGHT
        width = round(height * p["width"] / p["height"] / 2) * 2
        vf = f"fps=1/{step},scale={width}:{height},tile={montage.FILMSTRIP_COLS}x{rows}"
        # seulement les images clés : bien plus rapide qu'un décodage complet
        proc = subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-skip_frame", "nokey", "-i", p["path"],
                               "-vf", vf, "-frames:v", "1", "-q:v", "6", str(strip)], capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg : {proc.stderr.decode(errors='replace')[-300:]}")
