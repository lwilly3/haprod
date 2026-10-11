"""
Dérush automatique : Daryl propose toutes les coupes d'un coup, l'utilisateur les passe en revue
et les applique à la timeline (rien n'est coupé sans lui).

Méthode reprise d'editing-os (cut-silences, cut-mistakes, verify-cuts) :
1. Les timings des mots sont recalés sur le son : Whisper étire parfois un mot sur un silence
   (un « le » de 9 s), ce qui cache ce silence à toute coupe faite entre les mots.
2. Les vides entre les mots deviennent des coupes, en gardant une respiration qui dépend du
   contexte (plus longue après une phrase ou une longue pause) ; les bégaiements (« de de ») aussi.
3. Claude lit tout le transcript et choisit les prises : il désigne chaque coupe par son texte
   et les mots qui la suivent (`before`), jamais par un timecode. Le texte est ensuite retrouvé
   dans les mots du rush ; une coupe introuvable est signalée, pas devinée.
4. Contrôles sur le résultat : phrases encore présentes deux fois, contenu coupé qu'on ne
   retrouve nulle part ailleurs, coupes introuvables.

Le résultat (job.state["result"]) : {items, warnings, stats} ; un item = une coupe proposée
{id, rush, start, end, kind, text, reason}, en secondes du rush.
"""
import re

from ...core import jobs
from ...core.tasks import TaskContext
from ..settings.service import language_name
from ..transcript import cues
from . import derush, runtime, service

KIND = "project_autoderush"

# une pause plus longue est coupée
GAP = 0.55
# respiration gardée dans une pause coupée : après une longue pause, après une phrase, sinon
KEEP_LONG, KEEP_SENTENCE, KEEP_SHORT = 0.24, 0.20, 0.14
LONG_PAUSE = 2.0
# part de la respiration gardée après la parole (le reste, avant le mot suivant)
KEEP_AFTER_SHARE = 0.55
# marge gardée avant le premier mot et après le dernier d'un rush
HEAD, TAIL = 0.22, 0.34
# deux mêmes mots à moins de STUTTER_GAP : un bégaiement
STUTTER_GAP = 0.5
# doublés qui sont du français correct ou de l'insistance
LEGIT_DOUBLES = {"nous", "vous", "tres", "non", "si", "oui", "bien", "plus", "encore", "vite", "tout", "beaucoup",
                 "the", "that", "had", "very", "no", "yes", "so", "really"}
# un mot plus long est vérifié sur le son
STRETCHED = 1.0
# un calme plus long, dans un mot, n'est pas de la parole
QUIET_IN_WORD = 0.45
# un mot sans aucun son devient un mot de cette durée, collé à la suite
PHANTOM = 0.25
# marges des coupes de prises : un peu avant le mot coupé, pas trop près du mot gardé
CUT_LEAD, CUT_GUARD = 0.02, 0.08
# une phrase du transcript lu par Claude : coupée à la ponctuation, à un blanc ou au-delà de N mots
LINE_GAP, LINE_WORDS = 0.8, 40
# recherche du texte d'une coupe autour de sa ligne (en mots)
SEARCH_BEFORE, SEARCH_AFTER = 40, 400
# phrases répétées : n-grammes de N mots, à moins de N secondes l'un de l'autre
REPEAT_NGRAM, REPEAT_WINDOW = 6, 120.0

SCHEMA = {
    "type": "object",
    "required": ["cuts", "message"],
    "properties": {
        "message": {"type": "string",
                    "description": "Deux ou trois phrases pour l'auteur : ce que tu as coupé, et ce qu'il doit vérifier."},
        "cuts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["line", "text", "before", "kind", "reason"],
                "properties": {
                    "line": {"type": "integer", "description": "Le numéro de la ligne (Lnn) où la coupe commence."},
                    "text": {"type": "string",
                             "description": "Les mots à retirer, recopiés exactement comme dans le transcript "
                                            "(ils peuvent courir sur plusieurs lignes d'un même rush)."},
                    "before": {"type": "string",
                               "description": "Les 2 à 5 mots qui suivent immédiatement la coupe, recopiés tels quels. "
                                              "Vide si la coupe va jusqu'à la fin du rush."},
                    "kind": {"type": "string", "enum": ["retake", "false_start", "meta", "stutter", "other"]},
                    "reason": {"type": "string", "description": "Pourquoi, en une phrase courte."},
                },
            },
        },
    },
}

SYSTEM = """\
Tu es le monteur d'un créateur de vidéos YouTube (chaîne en {lang}). Tu fais le dérush de ses rushes : \
tu lis tout le transcript, de haut en bas, et tu choisis ce qu'il faut retirer pour que la vidéo \
s'enchaîne comme s'il avait tout dit d'une traite. Tu ne lis aucun fichier : tout est dans le message.

Ce que tu retires :
- les prises ratées : quand une phrase ou un passage est redit, garde UNE prise et retire les autres. \
En général la dernière est la bonne ; mais si une prise corrige un fait (un chiffre, un nom, une étape), \
garde celle qui est juste, et si la dernière s'arrête en route, garde la plus complète ;
- les faux départs : une phrase commencée puis abandonnée et relancée (« alors le… alors le principe c'est ») ;
- les indications de tournage et le méta-discours : « on la refait », « coupe », « attends », « c'est bon ça tourne » ;
- les bégaiements que tu repères (un mot ou un groupe de mots répété par accident).

Ce que tu gardes :
- la répétition voulue (« jamais, jamais »), les énumérations, les reformulations qui ajoutent quelque chose ;
- tout passage qui n'existe qu'en une seule prise, même imparfait : dans le doute, garde ;
- les silences : ils sont traités à part, ne propose pas de coupe pour eux.

Le script prévu est fourni pour t'aider à reconnaître les prises d'un même passage ; l'auteur s'en écarte \
souvent, ce n'est pas une erreur.

Une relance en milieu de phrase ne ressemble pas à une paire de phrases : lis tout, pas seulement les \
lignes qui se ressemblent. Les relances peuvent être dans un autre rush que la première prise.

Chaque coupe : `line` = la ligne où elle commence ; `text` = les mots retirés, recopiés à l'identique \
(sans les timecodes) ; `before` = les mots qui suivent immédiatement la coupe, recopiés à l'identique : \
c'est ce qui distingue deux passages identiques. Une coupe ne couvre qu'un rush ; coupe de préférence \
des phrases entières, du début de la prise ratée jusqu'au début de la bonne."""


# --- Mots ------------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return derush._norm(text).replace("'", " ").split()


def _rush_words(rush: dict) -> list[cues.Word]:
    segments, _ = derush.transcript_segments(rush.get("transcript"))
    return [w for seg in segments or [] for w in seg.words if w.text.strip()]


def _sound_runs(levels: list[int], lo: float, hi: float, threshold: float) -> list[tuple[float, float]]:
    """Les passages sonores de [lo, hi], même brefs (une syllabe) : rapprochés s'ils se touchent presque."""
    rate = derush.PEAKS_RATE
    runs: list[list[float]] = []
    for i in range(max(0, int(lo * rate)), min(len(levels), int(hi * rate) + 1)):
        if levels[i] <= threshold:
            continue
        t = i / rate
        if runs and t - runs[-1][1] <= 0.15:
            runs[-1][1] = t + 1 / rate
        else:
            runs.append([t, t + 1 / rate])
    return [(max(lo, a), min(hi, b)) for a, b in runs if b - a >= 0.04]


def repair_words(words: list[cues.Word], levels: list[int] | None) -> tuple[list[cues.Word], int]:
    """Rabote les mots que Whisper a étirés sur un silence. Rend les mots et le nombre de mots retouchés.
    Le début d'un mot n'est que retardé et sa fin qu'avancée : on ne rogne jamais de la parole."""
    if not levels:
        return words, 0
    threshold = derush._loud_threshold(levels)
    out, fixed = [], 0
    for w in words:
        start, end = w.start, w.end
        if end - start > STRETCHED:
            runs = _sound_runs(levels, start, end, threshold)
            if not runs:
                start = max(start, end - PHANTOM)
            else:
                if runs[0][0] - start >= QUIET_IN_WORD:
                    start = runs[0][0] - 0.05
                if end - runs[-1][1] >= QUIET_IN_WORD:
                    end = runs[-1][1] + 0.05
                # un long calme au milieu : la parole de tête est le mot, la suite un bruit
                for (a, b), (c, _) in zip(runs, runs[1:]):
                    if c - b >= QUIET_IN_WORD * 2:
                        end = b + 0.05
                        break
        if end - start < w.end - w.start - 0.1:
            fixed += 1
        out.append(cues.Word(round(start, 3), round(max(end, start + 0.02), 3), w.text))
    # dans l'ordre, sans chevauchement
    for a, b in zip(out, out[1:]):
        if b.start < a.end:
            b.start = a.end
            b.end = max(b.end, b.start + 0.02)
    return out, fixed


# --- Coupes mécaniques ---------------------------------------------------------------------

def _ends_sentence(text: str) -> bool:
    return text.rstrip()[-1:] in ".!?…"


def silence_cuts(rush_id: str, words: list[cues.Word], duration: float, levels: list[int] | None) -> list[dict]:
    """Les vides du rush : début, fin, et toute pause d'au moins GAP entre deux mots (respiration gardée).
    Ce qui sonne comme de la voix dans une pause (parole non transcrite) n'est pas coupé."""
    threshold = derush._loud_threshold(levels) if levels else None
    spans: list[tuple[float, float]] = []
    if words[0].start - HEAD > 0.1:
        spans.append((0.0, words[0].start - HEAD))
    for prev, nxt in zip(words, words[1:]):
        gap = nxt.start - prev.end
        if gap < GAP:
            continue
        keep = KEEP_LONG if gap >= LONG_PAUSE else KEEP_SENTENCE if _ends_sentence(prev.text) else KEEP_SHORT
        spans.append((prev.end + keep * KEEP_AFTER_SHARE, nxt.start - keep * (1 - KEEP_AFTER_SHARE)))
    if duration - (words[-1].end + TAIL) > 0.1:
        spans.append((words[-1].end + TAIL, duration))

    out = []
    for a, b in spans:
        pieces = [(a, b)]
        if threshold is not None:
            # la voix non transcrite reste, avec la même marge que la parole
            pieces = []
            cursor = a
            for x, y in derush._loud_runs(levels, a, b, threshold):
                if x - derush.PAD_BEFORE > cursor:
                    pieces.append((cursor, x - derush.PAD_BEFORE))
                cursor = max(cursor, y + derush.PAD_AFTER)
            if b > cursor:
                pieces.append((cursor, b))
        for x, y in pieces:
            if y - x >= 0.15:
                out.append({"rush": rush_id, "start": round(x, 3), "end": round(y, 3), "kind": "silence",
                            "text": derush._sil_text(x, y), "reason": ""})
    return out


def stutter_cuts(rush_id: str, words: list[cues.Word]) -> list[dict]:
    """Un même mot dit deux fois d'affilée : on garde le second."""
    out = []
    for a, b in zip(words, words[1:]):
        ta, tb = _tokens(a.text), _tokens(b.text)
        if not ta or ta != tb or b.start - a.end >= STUTTER_GAP:
            continue
        if len(ta) == 1 and (ta[0] in LEGIT_DOUBLES or ta[0].isdigit()):
            continue
        out.append({"rush": rush_id, "start": a.start, "end": b.start, "kind": "stutter",
                    "text": a.text.strip(), "reason": ""})
    return out


# --- Le transcript lu par Claude ---------------------------------------------------------------

def lines_of(rushes: list[dict], words_by_rush: dict[str, list[cues.Word]]) -> list[dict]:
    """Le transcript en lignes numérotées : {n, rush, label, first (indice du 1er mot), start, text}."""
    lines: list[dict] = []

    def close(rush: dict, label: str, words: list[cues.Word], idx: list[int]) -> None:
        if idx:
            lines.append({"n": len(lines) + 1, "rush": rush["id"], "label": label, "first": idx[0],
                          "start": words[idx[0]].start, "text": "".join(words[k].text for k in idx).strip()})

    for i, rush in enumerate(rushes, 1):
        words = words_by_rush.get(rush["id"]) or []
        current: list[int] = []
        for k, w in enumerate(words):
            if current and (w.start - words[current[-1]].end >= LINE_GAP or len(current) >= LINE_WORDS):
                close(rush, f"R{i}", words, current)
                current = []
            current.append(k)
            if _ends_sentence(w.text):
                close(rush, f"R{i}", words, current)
                current = []
        close(rush, f"R{i}", words, current)
    return lines


def _clock(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def prompt(rushes: list[dict], lines: list[dict], script_md: str, note: str) -> str:
    head = [f"R{i} = {r['name']}" for i, r in enumerate(rushes, 1)]
    spoken = derush.spoken_text(script_md).strip()
    parts = ["Les rushes, dans l'ordre de lecture :", *head, ""]
    if spoken:
        parts += ["Le script prévu (pour reconnaître les passages ; l'auteur s'en écarte souvent) :", "<script>",
                  spoken, "</script>", ""]
    if note.strip():
        parts += ["Consigne de l'auteur pour ce dérush :", note.strip(), ""]
    parts += ["Le transcript, une phrase par ligne (numéro, rush, minute:seconde dans le rush) :", "<transcript>"]
    parts += [f"L{l['n']} [{l['label']} {_clock(l['start'])}] {l['text']}" for l in lines]
    parts += ["</transcript>", "", "Rends les coupes à faire, dans l'ordre du transcript."]
    return "\n".join(parts)


# --- D'une coupe en texte à une plage du rush --------------------------------------------------------

def _token_index(words: list[cues.Word]) -> tuple[list[str], list[int]]:
    """Les mots du rush en jetons normalisés, et pour chaque jeton l'indice de son mot."""
    toks, owner = [], []
    for k, w in enumerate(words):
        for t in _tokens(w.text):
            toks.append(t)
            owner.append(k)
    return toks, owner


def resolve(spec: dict, line: dict, words: list[cues.Word], duration: float) -> tuple[int, int] | None:
    """Les indices du premier et du dernier mot coupés, ou None si le texte est introuvable près de sa ligne."""
    toks, owner = _token_index(words)
    cut, after = _tokens(spec.get("text", "")), _tokens(spec.get("before", ""))
    if not cut:
        return None
    first_tok = next((i for i, o in enumerate(owner) if o >= line["first"]), len(toks))
    lo, hi = max(0, first_tok - SEARCH_BEFORE), min(len(toks), first_tok + len(cut) + SEARCH_AFTER)

    def follows(end: int) -> bool:
        return not after or toks[end:end + len(after)] == after

    exact = [i for i in range(lo, hi - len(cut) + 1) if toks[i:i + len(cut)] == cut and follows(i + len(cut))]
    if exact:
        i = min(exact, key=lambda i: abs(i - first_tok))
        return owner[i], owner[i + len(cut) - 1]
    # recopie imparfaite : on s'accroche au début et à la fin de la coupe
    if len(cut) < 6:
        return None
    head, tail = cut[:4], cut[-4:]
    best = None
    for i in range(lo, hi):
        if toks[i:i + 4] != head:
            continue
        for j in range(i + int(len(cut) * 0.7) - 4, min(hi, i + int(len(cut) * 1.3) + 2)):
            if j >= i + 4 and toks[j - 4:j] == tail and follows(j):
                if best is None or abs(i - first_tok) < abs(best[0] - first_tok):
                    best = (i, j)
                break
    return (owner[best[0]], owner[best[1] - 1]) if best else None


def cut_range(words: list[cues.Word], a: int, b: int, duration: float) -> tuple[float, float]:
    """La plage coupée : de juste avant le premier mot coupé à un peu avant le mot gardé qui suit."""
    start = max(words[a].start - CUT_LEAD, words[a - 1].end if a else 0.0)
    if b + 1 < len(words):
        end = max(words[b].end, words[b + 1].start - CUT_GUARD)
    else:
        end = min(duration, words[b].end + TAIL)
    return round(start, 3), round(end, 3)


# --- Contrôles ------------------------------------------------------------------------------------

def _inside(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= t < b for a, b in spans)


def checks(rushes: list[dict], words_by_rush: dict[str, list[cues.Word]], items: list[dict]) -> list[dict]:
    """Ce qu'il faut regarder une fois toutes les coupes appliquées : {kind, rush, t, text}."""
    spans: dict[str, list[tuple[float, float]]] = {}
    for it in items:
        spans.setdefault(it["rush"], []).append((it["start"], it["end"]))
    kept: list[tuple[str, str, float, float]] = []  # (jeton, rush, temps du rush, temps lu bout à bout)
    offset = 0.0
    for rush in rushes:
        for w in words_by_rush.get(rush["id"]) or []:
            if not _inside((w.start + w.end) / 2, spans.get(rush["id"], [])):
                kept += [(t, rush["id"], w.start, offset + w.start) for t in _tokens(w.text)]
        offset += rush.get("duration") or 0.0
    warnings: list[dict] = []

    # une phrase encore dite deux fois, de près : une prise ratée restée
    seen: dict[tuple, tuple[str, float, float]] = {}
    flagged_until = -1.0
    for i in range(len(kept) - REPEAT_NGRAM + 1):
        gram = tuple(k[0] for k in kept[i:i + REPEAT_NGRAM])
        rush, t, at = kept[i][1], kept[i][2], kept[i][3]
        earlier = seen.get(gram)
        if earlier and at - earlier[2] <= REPEAT_WINDOW and at > flagged_until:
            warnings.append({"kind": "repeat", "rush": rush, "t": t, "text": " ".join(gram)})
            flagged_until = at + 10
        seen[gram] = (rush, t, at)
        if len(warnings) >= 12:
            break

    # une prise coupée dont on ne retrouve le contenu nulle part : du texte perdu ?
    kept_words = {k[0] for k in kept}
    for it in items:
        if it["kind"] not in ("retake", "false_start", "other"):
            continue
        content = {t for t in _tokens(it["text"]) if len(t) > 3}
        if len(content) >= 4 and len(content & kept_words) / len(content) < 0.5:
            warnings.append({"kind": "lost", "rush": it["rush"], "t": it["start"], "text": it["text"][:160]})
    return warnings


# --- La tâche ---------------------------------------------------------------------------------

def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p = ctx.payload
    project = service.load(p["project"])
    rushes = [r for r in project["rushes"] if r.get("duration")]
    state = ctx.state
    state["activity"] = "recale les mots sur le son"
    ctx.save(force=True)

    words_by_rush: dict[str, list[cues.Word]] = {}
    items: list[dict] = []
    repaired, silent = 0, []
    for n, rush in enumerate(rushes):
        ctx.check_cancel()
        words = _rush_words(rush)
        if not words:
            # sans parole (plan de coupe, B-roll) : on n'y touche pas
            silent.append(rush["name"])
            continue
        levels = runtime._levels_or_none(p["project"], rush)
        words, fixed = repair_words(words, levels)
        repaired += fixed
        words_by_rush[rush["id"]] = words
        items += silence_cuts(rush["id"], words, rush["duration"], levels)
        items += stutter_cuts(rush["id"], words)
        ctx.progress = 0.2 * (n + 1) / len(rushes)
        ctx.save()
    if not words_by_rush:
        raise RuntimeError("Aucun rush transcrit avec de la parole : rien à dérusher.")

    spoken_rushes = [r for r in rushes if r["id"] in words_by_rush]
    lines = lines_of(spoken_rushes, words_by_rush)
    script_md = service.read_doc(p["project"], service.SCRIPT_FILE)
    state["activity"] = "lit le transcript"
    ctx.save(force=True)
    out = ask(ctx, prompt(spoken_rushes, lines, script_md, p.get("note", "")),
              SYSTEM.format(lang=language_name()), "Read", None, SCHEMA)
    output = out["output"] or {}
    ctx.progress = 0.9

    by_n = {l["n"]: l for l in lines}
    durations = {r["id"]: r["duration"] for r in rushes}
    warnings: list[dict] = []
    for spec in output.get("cuts") or []:
        line = by_n.get(spec.get("line"))
        found = None
        if line:
            words = words_by_rush[line["rush"]]
            found = resolve(spec, line, words, durations[line["rush"]])
        if not found:
            warnings.append({"kind": "unresolved", "rush": line["rush"] if line else None,
                             "t": line["start"] if line else 0.0, "text": spec.get("text", "")[:160],
                             "reason": spec.get("reason", "")})
            continue
        a, b = found
        start, end = cut_range(words, a, b, durations[line["rush"]])
        items.append({"rush": line["rush"], "start": start, "end": end, "kind": spec.get("kind") or "other",
                      "text": "".join(w.text for w in words[a:b + 1]).strip(), "reason": spec.get("reason", "")})

    items.sort(key=lambda it: ([r["id"] for r in rushes].index(it["rush"]), it["start"]))
    for i, it in enumerate(items):
        it["id"] = f"a{i}"
    warnings += checks(spoken_rushes, words_by_rush, items)

    total = sum(r["duration"] for r in rushes)
    removed = _union_length(items)
    state["result"] = {
        "items": items, "warnings": warnings, "message": (output.get("message") or out["text"]).strip(),
        "stats": {"total": round(total, 1), "removed": round(removed, 1), "repaired": repaired, "silent": silent},
        "note": p.get("note", ""),
    }
    state["activity"] = None
    ctx.progress = 1.0


def _union_length(items: list[dict]) -> float:
    total = 0.0
    by_rush: dict[str, list[tuple[float, float]]] = {}
    for it in items:
        by_rush.setdefault(it["rush"], []).append((it["start"], it["end"]))
    for spans in by_rush.values():
        spans.sort()
        cur_a, cur_b = spans[0]
        for a, b in spans[1:]:
            if a > cur_b:
                total += cur_b - cur_a
                cur_a, cur_b = a, b
            else:
                cur_b = max(cur_b, b)
        total += cur_b - cur_a
    return total


def result(job_id: str | None) -> dict | None:
    """L'état du dérush automatique pour l'interface."""
    job = jobs.get(job_id) if job_id else None
    if not job:
        return None
    return {"status": job.status, "finished": job.finished, "progress": job.progress, "error": job.error,
            "activity": job.state.get("activity"), "note": job.payload.get("note", ""),
            "result": job.state.get("result") if job.status == "done" else None}
