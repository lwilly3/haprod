"""
Dérush : à partir des transcripts des rushes (timecodes au mot), découpe chaque rush en
morceaux de parole, vides et prises ratées, rattache la parole aux sections du script,
et produit ce qui en découle : plages gardées, timeline .xml, transcript recalé.

Un morceau (« seg ») : {key, rush, start, end, type: speech | retake | sil, text, words, sec, line, state}.
Les morceaux pavent chaque rush de 0 à sa durée ; `state` vaut keep sauf si l'utilisateur
l'a coupé (project.derush.cuts[key]). Une « ligne » = un morceau de parole et le vide qui le précède.
Coupes et recoupes (project.derush.splits) sont l'ancien format : la timeline est désormais une liste
de bouts de rushes (project.derush.clips, voir runtime.clips), qui en découle tant qu'on n'y a pas touché.
"""
import difflib
import math
import re
import unicodedata
from array import array
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from ...core import jobs
from ..transcript import cues
from . import media, timeline

# un blanc plus long devient un vide qu'on peut couper
SILENCE_MIN = 1.0
# marge gardée autour de la parole quand on coupe un vide
PAD_BEFORE = 0.12
PAD_AFTER = 0.2
# une prise reprise juste après (dans les N morceaux suivants) est une prise ratée
RETAKE_WINDOW = 4
# finesse de la forme d'onde des rushes (crêtes par seconde)
PEAKS_RATE = 50
RETAKE_SIMILARITY = 0.72
RETAKE_PHRASES = ("on la refait", "je la refais", "je reprends", "je recommence", "on recommence",
                  "on reprend", "je la reprends", "on la reprend", "attends", "coupe")
FILLERS = {"euh", "heu", "hum", "bon", "alors", "ok", "okay", "donc", "voila", "voilà", "non", "pardon",
           "attends", "mince", "merde", "bref", "ben", "bah", "hein", "oui", "allez"}

_HEADING = re.compile(r"^##\s+(.*)$")
# un « silence » (trou entre les mots de Whisper) n'en est un que si le son y est calme ;
# ce qui y sonne comme de la voix devient un morceau de parole non transcrite
LOUD_MIN = 0.3
LOUD_BRIDGE = 0.3


# --- Script -------------------------------------------------------------------

def sections(script_md: str) -> list[dict]:
    """Les sections `## Libellé — Titre` du script ; même découpage que l'interface (ids s0, s1…)."""
    found: list[dict] = []
    for line in script_md.splitlines():
        m = _HEADING.match(line)
        if m:
            head = m.group(1).strip()
            label, sep, title = head.partition(" — ")
            found.append({"id": f"s{len(found)}", "label": label.strip() if sep else head,
                          "title": title.strip() if sep else "", "text": ""})
        elif found:
            found[-1]["text"] += line + "\n"
    return found


def spoken_text(text: str) -> str:
    """Le texte dit : sans indications de montage, ni balises Markdown."""
    kept = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line == "---" or line.startswith("#"):
            continue
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        kept.append(re.sub(r"[*_`]", "", line))
    return "\n".join(kept)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("’", "'"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w' ]+", " ", text).strip()


def _content_words(text: str) -> set[str]:
    return {w for w in _norm(text).replace("'", " ").split() if len(w) > 3}


def _match_section(text: str, section_words: list[set[str]]) -> int | None:
    words = _content_words(text)
    if len(words) < 3 or not section_words:
        return None
    scores = [len(words & sw) / len(words) for sw in section_words]
    best = max(range(len(scores)), key=scores.__getitem__)
    return best if scores[best] >= 0.5 else None


# --- Découpage d'un rush --------------------------------------------------------

def _chunks(segments: list[cues.Segment]) -> list[list[cues.Word]]:
    """La parole d'un rush en morceaux : un par segment Whisper, recoupé aux longs blancs."""
    chunks: list[list[cues.Word]] = []
    for seg in segments:
        words = [w for w in seg.words if w.text.strip()]
        if not words:
            continue
        current = [words[0]]
        for w in words[1:]:
            if w.start - current[-1].end >= SILENCE_MIN:
                chunks.append(current)
                current = []
            current.append(w)
        chunks.append(current)
    return chunks


def _text(words: list[cues.Word]) -> str:
    return "".join(w.text for w in words).strip()


def _is_retake(i: int, texts: list[str]) -> bool:
    text = _norm(texts[i])
    if not text:
        return True
    if any(p in text for p in RETAKE_PHRASES) and len(text.split()) <= 12:
        return True
    words = text.replace("'", " ").split()
    if len(words) <= 6 and all(w in FILLERS for w in words):
        return True
    if len(words) < 2:
        return False
    for later in texts[i + 1:i + 1 + RETAKE_WINDOW]:
        other = _norm(later)
        # la reprise recommence la même phrase : on compare au début du morceau suivant
        head = other[:len(text) + 12]
        if difflib.SequenceMatcher(None, text, head, autojunk=False).ratio() >= RETAKE_SIMILARITY:
            return True
    return False


def frame_levels(raw: bytes, per: int) -> list[int]:
    """PCM 16 bits mono → la crête de chaque groupe de `per` échantillons."""
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    out = []
    for i in range(0, len(samples), per):
        chunk = samples[i:i + per]
        out.append(max(max(chunk), -min(chunk)) if chunk else 0)
    return out


def _loud_threshold(levels: list[int]) -> float:
    """Le seuil voix / calme d'un rush, entre son bruit de fond et le niveau de sa voix (en dB)."""
    db = sorted(20 * math.log10(max(v, 1)) for v in levels)
    floor, voice = db[len(db) // 10], db[int(len(db) * 0.95)]
    return 10 ** (max(floor + 6, floor + 0.3 * (voice - floor)) / 20)


def _loud_runs(levels: list[int], lo: float, hi: float, threshold: float) -> list[tuple[float, float]]:
    """Les passages sonores de [lo, hi] : rapprochés s'ils sont proches, sans les claquements isolés."""
    a, b = int(lo * PEAKS_RATE), min(len(levels), int(hi * PEAKS_RATE) + 1)
    runs: list[list[float]] = []
    for i in range(a, b):
        if levels[i] <= threshold:
            continue
        t = i / PEAKS_RATE
        if runs and t - runs[-1][1] <= LOUD_BRIDGE:
            runs[-1][1] = t + 1 / PEAKS_RATE
        else:
            runs.append([t, t + 1 / PEAKS_RATE])
    return [(max(lo, x), min(hi, y)) for x, y in runs if y - x >= LOUD_MIN]


def _check_silences(bounds: list[list], levels: list[int]) -> list[list]:
    """Recoupe chaque vide selon le son : ne restent vides que les passages calmes d'au moins SILENCE_MIN."""
    threshold = _loud_threshold(levels)
    out: list[list] = []
    for lo, hi, kind, k in bounds:
        if kind != "sil":
            out.append([lo, hi, kind, k])
            continue
        cursor = lo
        for x, y in _loud_runs(levels, lo, hi, threshold):
            # la voix garde un peu de marge, comme la parole transcrite
            x, y = max(cursor, x - PAD_BEFORE), min(hi, y + PAD_AFTER)
            if x - cursor >= SILENCE_MIN:
                out.append([cursor, x, "sil", -1])
            else:
                x = cursor
            out.append([x, y, "voice", -1])
            cursor = y
        if hi - cursor >= SILENCE_MIN or (cursor == lo and hi > lo):
            out.append([cursor, hi, "sil", -1])
        elif hi > cursor:
            out.append([cursor, hi, "voice", -1])
    # deux bouts de voix qui se touchent n'en font qu'un
    merged: list[list] = []
    for b in out:
        if merged and b[2] == merged[-1][2] == "voice" and abs(merged[-1][1] - b[0]) < 1e-6:
            merged[-1][1] = b[1]
        else:
            merged.append(b)
    return merged


def split_rush(rush_id: str, segments: list[cues.Segment], duration: float, levels: list[int] | None = None) -> list[dict]:
    """Pave [0, durée] du rush en morceaux de parole et en vides (vérifiés sur le son si on l'a)."""
    chunks = _chunks(segments)
    duration = max(duration, chunks[-1][-1].end if chunks else 0.0)
    if not chunks:
        bounds = [[0.0, duration, "sil", -1]]
        if levels:
            bounds = _check_silences(bounds, levels)
        return [{"rush": rush_id, "start": round(lo, 3), "end": round(hi, 3),
                 "type": "speech" if kind == "voice" else "sil", "words": []} for lo, hi, kind, _ in bounds if hi - lo > 0.01]
    out: list[dict] = []
    bounds = []
    for k, words in enumerate(chunks):
        start, end = words[0].start, words[-1].end
        prev_end = chunks[k - 1][-1].end if k else 0.0
        gap = start - prev_end
        if gap >= SILENCE_MIN:
            lo = max(prev_end + PAD_AFTER, 0.0) if k else 0.0
            hi = max(lo, start - PAD_BEFORE)
            if k:
                bounds[-1][1] = lo
            if hi > lo:
                bounds.append([lo, hi, "sil", -1])
            begin = hi
        else:
            begin = (prev_end + start) / 2 if k else 0.0
            if k:
                bounds[-1][1] = begin
        bounds.append([begin, end, "chunk", k])
    # la fin du rush
    tail = duration - chunks[-1][-1].end
    if tail >= SILENCE_MIN:
        bounds[-1][1] = chunks[-1][-1].end + PAD_AFTER
        bounds.append([bounds[-1][1], duration, "sil", -1])
    else:
        bounds[-1][1] = duration
    if levels:
        bounds = _check_silences(bounds, levels)
    for lo, hi, kind, k in bounds:
        if hi - lo <= 0.01:
            continue
        words = chunks[k] if kind == "chunk" else []
        out.append({"rush": rush_id, "start": round(lo, 3), "end": round(hi, 3),
                    "type": "sil" if kind == "sil" else "speech", "words": words})
    return out


# --- Analyse complète -------------------------------------------------------------

def transcript_segments(job_id: str | None) -> tuple[list[cues.Segment] | None, dict | None]:
    job = jobs.get(job_id) if job_id else None
    if not job:
        return None, None
    if job.status != "done":
        return None, {"status": job.status, "progress": job.progress, "error": job.error}
    return cues.load_segments(job.state.get("segments", [])), {"status": "done", "progress": 1.0}


def analyze(project: dict, script_md: str, levels=None) -> dict:
    """Les morceaux de tous les rushes (dans l'ordre des rushes) et l'avancement des transcriptions."""
    secs = sections(script_md)
    section_words = [_content_words(spoken_text(s["text"])) for s in secs]
    cuts = project["derush"]["cuts"]
    progress, segs = [], []
    ready = bool(project["rushes"])
    for rush in project["rushes"]:
        segments, status = transcript_segments(rush.get("transcript"))
        progress.append({"rush": rush["id"], **(status or {"status": "none", "progress": 0})})
        if segments is None:
            ready = False
            continue
        segs += split_rush(rush["id"], segments, rush.get("duration") or 0.0, levels(rush) if levels else None)
    if not ready:
        return {"ready": False, "transcripts": progress, "segs": [], "sections": _public(secs)}

    texts = [_text(s["words"]) if s["type"] == "speech" else "" for s in segs]
    # la voix non transcrite (sans mots) n'entre pas dans la recherche des prises ratées
    speech = [i for i, s in enumerate(segs) if s["type"] == "speech" and s["words"]]
    speech_texts = [texts[i] for i in speech]
    for n, i in enumerate(speech):
        if _is_retake(n, speech_texts):
            segs[i]["type"] = "retake"
    # numérotation et rattachement aux sections
    counters: dict[str, int] = {}
    line, current_sec = -1, None
    for i, s in enumerate(segs):
        n = counters.get(s["rush"], 0)
        counters[s["rush"]] = n + 1
        s["key"] = f"{s['rush']}:{n}"
        prev = segs[i - 1] if i else None
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        new_rush = not prev or prev["rush"] != s["rush"]
        if s["type"] == "sil":
            s["text"] = _sil_text(s["start"], s["end"])
            # un vide ouvre la ligne de la parole qui le suit ; en fin de rush, il reste sur la ligne d'avant
            opens = new_rush or bool(nxt and nxt["rush"] == s["rush"] and nxt["type"] != "sil")
        else:
            s["text"] = texts[i]
            opens = new_rush or prev["type"] != "sil"
            found = _match_section(texts[i], section_words)
            if found is not None:
                current_sec = secs[found]["id"]
        if opens:
            line += 1
        s["sec"] = current_sec
        s["line"] = line
        s["state"] = cuts.get(s["key"], "keep")
    for s in segs:
        s["words"] = [[round(w.start, 3), round(w.end, 3), w.text] for w in s["words"]]
    return {"ready": True, "transcripts": progress, "segs": segs, "sections": _public(secs)}


def _sil_text(start: float, end: float) -> str:
    return f"silence {end - start:.1f} s".replace(".", ",")


def apply_edits(segs: list[dict], splits: dict[str, list[float]], cuts: dict[str, str]) -> list[dict]:
    """Les morceaux recoupés aux instants choisis par l'utilisateur, avec leur état (gardé / coupé)."""
    out: list[dict] = []
    for s in segs:
        points = sorted(t for t in splits.get(s["rush"], []) if s["start"] + 0.01 < t < s["end"] - 0.01)
        if not points:
            out.append({**s, "state": cuts.get(s["key"], "keep")})
            continue
        bounds = [s["start"], *points, s["end"]]
        for a, b in zip(bounds, bounds[1:]):
            key = f"{s['key']}@{a:.3f}"
            words = [w for w in s.get("words", []) if a <= w[0] < b]
            text = _sil_text(a, b) if s["type"] == "sil" else "".join(w[2] for w in words).strip()
            out.append({**s, "key": key, "start": a, "end": b, "words": words, "text": text,
                        "state": cuts.get(key, cuts.get(s["key"], "keep"))})
    return out


def _public(secs: list[dict]) -> list[dict]:
    return [{k: s[k] for k in ("id", "label", "title")} for s in secs]


def kept_ranges(project: dict, segs: list[dict]) -> list[dict]:
    """Les plages gardées, dans l'ordre, fusionnées quand elles se suivent dans un même rush."""
    by_rush = {r["id"]: r for r in project["rushes"]}
    ranges: list[dict] = []
    for s in segs:
        if s["state"] != "keep":
            continue
        last = ranges[-1] if ranges else None
        if last and last["rush"] == s["rush"] and abs(last["end"] - s["start"]) < 1e-3:
            last["end"] = s["end"]
        else:
            ranges.append({"rush": s["rush"], "path": by_rush[s["rush"]]["path"],
                           "start": s["start"], "end": s["end"]})
    return ranges


# --- Transcript recalé sur le dérush -------------------------------------------

def derived_segments(clips: list[dict], project: dict) -> list[cues.Segment]:
    """Le transcript de la vidéo dérushée, sans relancer Whisper : on décale les mots de chaque bout."""
    words_by_rush: dict[str, list[cues.Word]] = {}
    for rush in project["rushes"]:
        segments, _ = transcript_segments(rush.get("transcript"))
        words_by_rush[rush["id"]] = [w for seg in segments or [] for w in seg.words if w.text.strip()]
    out: list[cues.Segment] = []
    offset = 0.0
    for c in clips:
        words = [cues.Word(round(offset + w.start - c["in"], 3), round(offset + min(w.end, c["out"]) - c["in"], 3), w.text)
                 for w in words_by_rush.get(c["rush"], []) if c["in"] <= w.start < c["out"]]
        # une phrase par groupe de mots sans blanc d'une seconde
        group: list[cues.Word] = []
        for w in words:
            if group and w.start - group[-1].end >= SILENCE_MIN:
                out.append(cues.Segment(group[0].start, group[-1].end, _text(group), group))
                group = []
            group.append(w)
        if group:
            out.append(cues.Segment(group[0].start, group[-1].end, _text(group), group))
        offset += c["out"] - c["in"]
    return out


# --- Timeline .xml (Final Cut Pro 7 / xmeml : lu par Resolve et Premiere) ---------

def _rate(info: dict) -> tuple[int, str]:
    fps = info.get("fps") or 25
    ntsc = info.get("fps_den") == 1001
    return round(fps), "TRUE" if ntsc else "FALSE"


def _pathurl(path: str) -> str:
    return "file://localhost/" + quote(Path(path).as_posix().lstrip("/"), safe="/:")


def timeline_xml(project: dict, ranges: list[dict], name: str) -> str:
    rushes = {r["id"]: r for r in project["rushes"]}
    first = rushes[ranges[0]["rush"]] if ranges else {}
    timebase, ntsc = _rate(first)
    fps = first.get("fps") or 25
    rate = f"<rate><timebase>{timebase}</timebase><ntsc>{ntsc}</ntsc></rate>"
    width, height = first.get("width") or 1920, first.get("height") or 1080

    def frames(t: float) -> int:
        return int(round(t * fps))

    files_done: set[str] = set()

    def file_xml(rush: dict) -> str:
        fid = f"file-{rush['id']}"
        if fid in files_done:
            return f'<file id="{fid}"/>'
        files_done.add(fid)
        channels = rush.get("audio_channels") or 2
        # timecode de départ du fichier : sans lui, Resolve ne relie pas les rushes de caméra (DJI…)
        start = timeline.timecode(rush)
        timecode = (f"<timecode>{rate}<string>{escape(start)}</string>"
                    f"<frame>{media.timecode_frames(start, rush.get('fps_num') or timebase, rush.get('fps_den') or 1)}</frame>"
                    f"<displayformat>{'DF' if ';' in start else 'NDF'}</displayformat></timecode>") if start else ""
        return (f'<file id="{fid}"><name>{escape(rush["name"])}</name><pathurl>{escape(_pathurl(rush["path"]))}</pathurl>'
                f"{rate}<duration>{frames(rush.get('duration') or 0)}</duration>{timecode}"
                f"<media><video><samplecharacteristics>{rate}<width>{rush.get('width') or width}</width>"
                f"<height>{rush.get('height') or height}</height></samplecharacteristics></video>"
                f"<audio><samplecharacteristics><depth>16</depth><samplerate>{rush.get('audio_rate') or 48000}"
                f"</samplerate></samplecharacteristics><channelcount>{channels}</channelcount></audio></media></file>")

    video_items, audio_items = [], []
    cursor = 0
    for n, r in enumerate(ranges, 1):
        rush = rushes[r["rush"]]
        src_in, src_out = frames(r["start"]), frames(r["end"])
        length = src_out - src_in
        if length <= 0:
            continue
        common = (f"<name>{escape(rush['name'])}</name><duration>{frames(rush.get('duration') or 0)}</duration>{rate}"
                  f"<start>{cursor}</start><end>{cursor + length}</end><in>{src_in}</in><out>{src_out}</out>")
        has_audio = rush.get("audio", True)
        # image et son liés : sans <link>, Resolve et Premiere les importent comme deux plans indépendants
        index = len(video_items) + 1
        links = f"<link><linkclipref>clipitem-v{n}</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>{index}</clipindex></link>"
        if has_audio:
            links += (f"<link><linkclipref>clipitem-a{n}</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex>"
                      f"<clipindex>{len(audio_items) + 1}</clipindex><groupindex>1</groupindex></link>")
        video_items.append(f'<clipitem id="clipitem-v{n}">{common}{file_xml(rush)}{links}</clipitem>')
        if has_audio:
            audio_items.append(f'<clipitem id="clipitem-a{n}">{common}<file id="file-{rush["id"]}"/>'
                               f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>{links}</clipitem>")
        cursor += length
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5">'
            f'<sequence id="sequence-1"><name>{escape(name)}</name><duration>{cursor}</duration>{rate}'
            f"<media><video><format><samplecharacteristics>{rate}<width>{width}</width><height>{height}</height>"
            f"<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>"
            f"<track>{''.join(video_items)}</track></video>"
            f"<audio><track>{''.join(audio_items)}</track></audio></media></sequence></xmeml>\n")
