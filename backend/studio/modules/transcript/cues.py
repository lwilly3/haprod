"""
Tout ce qui ne demande pas le modele : audio (ffmpeg), decoupage en cues,
corrections, export. Whisper tourne avec les timestamps au mot, ce qui permet
de reconstruire trois niveaux de decoupage (phrase / ligne courte / mot) sans
relancer le calcul.
"""
import difflib
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from ...core.system import tool

LEVELS = ("segment", "line", "word")
LINE_MAX_CHARS = 42
# un blanc plus long que ca force un retour a la ligne
LINE_MAX_GAP = 0.8
# au-dela, une virgule est un bon endroit pour couper
LINE_COMMA_BREAK = 18


@dataclass
class Word:
    start: float
    end: float
    text: str  # brut whisper, avec l'espace de tete


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]

    def to_json(self) -> dict:
        # les mots en listes [debut, fin, texte] : le transcript d'une heure reste leger en base
        return {"start": self.start, "end": self.end, "text": self.text,
                "words": [[w.start, w.end, w.text] for w in self.words]}

    @classmethod
    def from_json(cls, data: dict) -> "Segment":
        return cls(data["start"], data["end"], data["text"],
                   [Word(*w) for w in data["words"]])


def load_segments(data: list[dict]) -> list[Segment]:
    return [Segment.from_json(d) for d in data]


def dump_segments(segments: list[Segment]) -> list[dict]:
    return [s.to_json() for s in segments]


# --- Audio -------------------------------------------------------------------

def probe_duration(source: Path) -> float | None:
    try:
        out = subprocess.run(
            [tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(source)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError, RuntimeError):
        return None


def extract_audio(source: Path, dest: Path, duration: float | None = None) -> None:
    """ffmpeg ne garde que l'audio, en 16 kHz mono : ce qu'attend Whisper.

    Avec `duration`, la piste est completee par du silence (ou coupee) pour durer
    exactement autant que le fichier : indispensable pour enchainer des clips
    sans que les timecodes derivent par rapport a la timeline de montage.
    """
    trim = ["-af", "apad", "-t", f"{duration:.3f}"] if duration else []
    proc = subprocess.run(
        [tool("ffmpeg"), "-y", "-v", "error", "-i", str(source),
         "-vn", "-ac", "1", "-ar", "16000", *trim, "-c:a", "pcm_s16le", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg n'a pas pu lire {source.name} : {proc.stderr.strip()[-300:]}")


def concat_wavs(parts: list[Path], dest: Path) -> list[float]:
    """Colle les WAV bout a bout ; retourne la duree de chacun."""
    durations = []
    with wave.open(str(dest), "wb") as out:
        for i, part in enumerate(parts):
            with wave.open(str(part), "rb") as src:
                if i == 0:
                    out.setparams(src.getparams())
                durations.append(src.getnframes() / src.getframerate())
                while chunk := src.readframes(1 << 20):
                    out.writeframes(chunk)
    return durations


# --- Decoupage en cues -------------------------------------------------------

def _join(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


def build_lines(segments: list[Segment]) -> list[dict]:
    """Regroupe les mots en lignes courtes, facon sous-titres."""
    cues = []
    for si, seg in enumerate(segments):
        # un nouveau segment whisper = une nouvelle phrase, donc une nouvelle ligne
        first = 0  # indice du premier mot de la ligne en cours

        def flush(end: int):
            nonlocal first
            if end > first:
                words = seg.words[first:end]
                cues.append({"start": words[0].start, "end": words[-1].end, "text": _join(words),
                             "seg": si, "w0": first, "w1": end})
            first = end

        for wi, w in enumerate(seg.words):
            if wi > first:
                too_long = len(_join(seg.words[first:wi + 1])) > LINE_MAX_CHARS
                gap = w.start - seg.words[wi - 1].end > LINE_MAX_GAP
                if too_long or gap:
                    flush(wi)
            line = _join(seg.words[first:wi + 1])
            if line.endswith((".", "?", "!", "…")) and len(line) > 12:
                flush(wi + 1)
            elif line.endswith((",", ";", ":")) and len(line) > LINE_COMMA_BREAK:
                flush(wi + 1)
        flush(len(seg.words))
    return cues


def build_cues(segments: list[Segment], level: str) -> list[dict]:
    """Chaque cue sait quels mots elle couvre (seg, w0, w1) : c'est ce qui permet de la corriger."""
    if level == "segment":
        return [{"start": s.start, "end": s.end, "text": s.text,
                 "seg": si, "w0": 0, "w1": len(s.words)} for si, s in enumerate(segments)]
    if level == "word":
        # "space" : whisper colle les elisions ("l" + "'est"), il faut le savoir pour recoller le texte
        return [{"start": w.start, "end": w.end, "text": w.text.strip(),
                 "space": w.text[:1].isspace(), "seg": si, "w0": wi, "w1": wi + 1}
                for si, s in enumerate(segments) for wi, w in enumerate(s.words) if w.text.strip()]
    return build_lines(segments)


# --- Corrections -------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Decoupe comme whisper : "l'est" -> " l" + "'est", pour retomber sur les memes mots."""
    tokens = []
    for chunk in text.split():
        pieces = [p for p in re.split(r"(?=['’])", chunk) if p]
        tokens.append(" " + pieces[0])
        tokens.extend(pieces[1:])
    return tokens


def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower().replace("’", "'"))


def _spread(texts: list[str], start: float, end: float) -> list[Word]:
    """Repartit [start, end] entre les mots, au prorata de leur longueur."""
    total = sum(len(t.strip()) for t in texts) or 1
    words, t = [], start
    for text in texts:
        d = (end - start) * len(text.strip()) / total
        words.append(Word(t, t + d, text))
        t += d
    return words


def edit_segment(seg: Segment, w0: int, w1: int, text: str) -> None:
    """Remplace seg.words[w0:w1] par le texte corrige en gardant au mieux les timecodes.

    Les mots inchanges (a la casse/ponctuation pres) gardent leur timing exact ;
    les mots modifies se partagent la duree de ceux qu'ils remplacent.
    """
    if not seg.words:  # segment sans timestamps au mot : on ne peut corriger que le texte
        seg.text = text.strip()
        return
    old = seg.words[w0:w1]
    tokens = _tokenize(text)
    matcher = difflib.SequenceMatcher(a=[_norm(w.text) for w in old],
                                      b=[_norm(t) for t in tokens], autojunk=False)
    new: list[Word] = []
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == "equal":
            new += [Word(old[a0 + k].start, old[a0 + k].end, tokens[b0 + k]) for k in range(a1 - a0)]
        elif op in ("replace", "insert") and b1 > b0:
            if a1 > a0:
                start, end = old[a0].start, old[a1 - 1].end
            else:  # mot ajoute : on le loge entre ses voisins
                before = new[-1].end if new else (seg.words[w0 - 1].end if w0 else old[0].start if old else seg.start)
                after = old[a0].start if a0 < len(old) else (seg.words[w1].start if w1 < len(seg.words) else before)
                start, end = before, max(before, after)
            new += _spread(tokens[b0:b1], start, end)
    # un mot colle a son voisin (elision "'est") doit le rester apres correction
    if old and new and not old[0].text[:1].isspace():
        new[0].text = new[0].text.lstrip()
    seg.words[w0:w1] = new
    seg.text = _join(seg.words)
    if seg.words:
        seg.start, seg.end = min(seg.start, seg.words[0].start), max(seg.end, seg.words[-1].end)


def replace_all(segments: list[Segment], find: str, repl: str, match_case: bool) -> int:
    """Rechercher / remplacer sur tout le transcript ; retourne le nombre d'occurrences."""
    pattern = re.compile(re.escape(find), 0 if match_case else re.IGNORECASE)
    count = 0
    for seg in segments:
        new_text, n = pattern.subn(repl, seg.text)
        if n:
            count += n
            edit_segment(seg, 0, len(seg.words), new_text)
    return count


# --- Export ------------------------------------------------------------------

def format_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    return "".join(
        f"{i}\n{format_timestamp(c['start'])} --> {format_timestamp(c['end'])}\n{c['text']}\n\n"
        for i, c in enumerate(cues, 1)
    )


def join_words(cues: list[dict]) -> str:
    return "".join((" " if c["space"] else "") + c["text"] for c in cues).strip()


def to_txt(cues: list[dict], level: str) -> str:
    if level == "word":
        return join_words(cues) + "\n"
    return "\n".join(c["text"] for c in cues) + "\n"
