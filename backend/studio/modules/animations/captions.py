"""
Sous-titres mot a mot facon Submagic : de gros mots qui apparaissent par petits
groupes, le mot prononce mis en valeur au moment exact ou il est dit.

La source de verite est captions.json (groupes de mots timecodes, mots cles,
emojis), que Claude peut retoucher ; captions/captions.html, la composition HyperFrames
previsualisee et rendue, en est regeneree a chaque changement.

  captions.json : {"style": "pop", "position": "bas",
                   "groups": [{"words": [{"text", "start", "end", "key"}], "emoji": ""}]}
"""
import html
import json
import re
from pathlib import Path

from ..settings.service import language

JSON_FILE = "captions.json"
# dans un sous-dossier : a la racine du projet, le rendu la prendrait pour une 2e composition racine
HTML_FILE = "captions/captions.html"
COMPOSITION_ID = "captions"

STYLES = {
    "pop": "Pop : majuscules blanches contour noir, mot prononcé en jaune qui grossit",
    "box": "Encadré : majuscules blanches, mot prononcé sur un bloc de couleur",
    "clean": "Sobre : casse normale, mots à venir estompés",
}
POSITIONS = {"haut": 0.28, "milieu": 0.5, "bas": 0.7}
DEFAULT = {"style": "pop", "position": "bas"}

# un groupe : 3 mots au plus, ~15 caracteres, coupe sur la ponctuation et les silences
GROUP_WORDS = 3
GROUP_CHARS = 15
GROUP_GAP = 0.35
# un groupe reste a l'ecran jusqu'au suivant, sauf long silence
HOLD = 0.6


def merge_elisions(words: list[dict]) -> list[dict]:
    """Whisper coupe "qu'il" en " qu" + "'il" : un morceau sans espace devant rejoint le mot d'avant."""
    out = []
    for w in words:
        if out and w["text"] and not w["text"][:1].isspace():
            out[-1] = {**out[-1], "text": out[-1]["text"] + w["text"], "end": w["end"]}
        else:
            out.append(dict(w))
    return out


def group_words(words: list[dict]) -> list[dict]:
    """words : [{text, start, end}] (texte brut whisper) -> groupes affiches ensemble."""
    groups, current = [], []
    for w in merge_elisions(words):
        text = w["text"].strip()
        if not text:
            continue
        if current:
            chars = sum(len(c["text"]) + 1 for c in current) + len(text)
            gap = w["start"] - current[-1]["end"]
            if len(current) >= GROUP_WORDS or chars > GROUP_CHARS or gap > GROUP_GAP:
                groups.append({"words": current, "emoji": ""})
                current = []
        current.append({"text": text, "start": round(w["start"], 3), "end": round(w["end"], 3), "key": False})
        if text.endswith((".", "?", "!", "…", ",", ";", ":")):
            groups.append({"words": current, "emoji": ""})
            current = []
    if current:
        groups.append({"words": current, "emoji": ""})
    return groups


def create(directory: Path, words: list[dict], style: str = "pop", position: str = "bas") -> None:
    data = {"style": style, "position": position, "groups": group_words(words)}
    (directory / JSON_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(directory: Path) -> dict | None:
    try:
        data = json.loads((directory / JSON_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("groups"), list) else None


def _clean_groups(groups: list) -> list[dict]:
    out = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        words = []
        for w in g.get("words") or []:
            try:
                words.append({"text": str(w["text"]).strip(), "start": float(w["start"]),
                              "end": float(w["end"]), "key": bool(w.get("key"))})
            except (KeyError, TypeError, ValueError):
                continue
        words = [w for w in words if w["text"]]
        if words:
            out.append({"words": sorted(words, key=lambda w: w["start"]),
                        "emoji": str(g.get("emoji") or "").strip()})
    return sorted(out, key=lambda g: g["words"][0]["start"])


def _display(text: str, style: str) -> str:
    # la ponctuation de fin alourdit l'ecran : on ne garde que ? et !
    text = re.sub(r"[.,;:…]+$", "", text)
    return text.upper() if style != "clean" else text


def build(directory: Path, duration: float, size: tuple[int, int]) -> bool:
    """Regenere captions.html si captions.json a change ; False s'il n'y a pas de sous-titres."""
    data = load(directory)
    target = directory / HTML_FILE
    if data is None:
        target.unlink(missing_ok=True)
        return False
    source = directory / JSON_FILE
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        return True
    target.parent.mkdir(exist_ok=True)
    target.write_text(render_html(data, duration, size), encoding="utf-8")
    return True


def render_html(data: dict, duration: float, size: tuple[int, int]) -> str:
    style = data.get("style") if data.get("style") in STYLES else DEFAULT["style"]
    position = POSITIONS.get(data.get("position"), POSITIONS[DEFAULT["position"]])
    groups = _clean_groups(data["groups"])
    width, height = size
    # chaque groupe tient jusqu'au suivant (pas de clignotement entre deux groupes proches)
    timeline, markup = [], []
    for i, g in enumerate(groups):
        start = g["words"][0]["start"]
        nxt = groups[i + 1]["words"][0]["start"] if i + 1 < len(groups) else duration
        end = min(nxt, g["words"][-1]["end"] + HOLD, duration)
        words = []
        for j, w in enumerate(g["words"]):
            cls = "w key" if w["key"] else "w"
            words.append(f'<span class="{cls}" id="g{i}w{j}"><span class="t">{html.escape(_display(w["text"], style))}</span></span>')
        emoji = f'<div class="emoji" id="g{i}e">{html.escape(g["emoji"])}</div>' if g["emoji"] else ""
        markup.append(f'<div class="group" id="g{i}">{emoji}<div class="line">{"".join(words)}</div></div>')
        timeline.append({"s": round(start, 3), "e": round(end, 3), "emoji": bool(g["emoji"]),
                         "w": [[round(w["start"], 3), round(w["end"], 3)] for w in g["words"]]})
    return _TEMPLATE.format(
        lang=language(),
        width=width, height=height, duration=f"{duration:.3f}", top=int(height * position),
        id=COMPOSITION_ID, style=style, groups="\n  ".join(markup),
        data=json.dumps(timeline, separators=(",", ":")))


_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<!-- genere depuis captions.json : modifier captions.json, pas ce fichier -->
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@800;900&display=block">
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
html, body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; }}
#stage {{ position: relative; overflow: hidden; width: {width}px; height: {height}px; font-family: "Montserrat", system-ui, sans-serif; }}
.group {{ position: absolute; left: 70px; right: 70px; top: {top}px; height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
.line {{ display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 0 34px; }}
.w {{ display: inline-block; position: relative; }}
.t {{ font-family: "Montserrat", system-ui, sans-serif; position: relative; display: inline-block; font-weight: 900; font-size: 96px; line-height: 1.1; letter-spacing: -.01em; color: #fff; }}
.emoji {{ font-size: 130px; line-height: 1; margin-bottom: 18px; }}

/* pop : contour epais, mot prononce en jaune */
.pop .t {{ -webkit-text-stroke: 16px #000; paint-order: stroke fill; text-shadow: 0 10px 0 rgba(0,0,0,.45); }}
.pop .key .t {{ color: #3dff74; }}

/* encadre : bloc de couleur derriere le mot prononce */
.box .t {{ -webkit-text-stroke: 12px #000; paint-order: stroke fill; z-index: 1; }}
.box .w::before {{ content: ""; position: absolute; inset: 2px -16px; border-radius: 18px; background: #7b3cff; opacity: var(--on, 0); transform: scale(var(--bs, .8)); }}
.box .key .t {{ color: #ffe14d; }}

/* sobre : casse normale, ombre douce */
.clean .t {{ font-weight: 800; font-size: 88px; text-shadow: 0 4px 18px rgba(0,0,0,.65), 0 2px 3px rgba(0,0,0,.8); }}
.clean .key .t {{ color: #ffd23f; }}
</style>
</head>
<body>
<div id="stage" class="{style}" data-composition-id="{id}" data-width="{width}" data-height="{height}" data-duration="{duration}">
  {groups}
</div>
<script>
(function () {{
  const G = {data};
  const style = "{style}";
  const tl = gsap.timeline({{ paused: true }});
  gsap.set(".group", {{ autoAlpha: 0 }});
  G.forEach((g, i) => {{
    const group = "#g" + i;
    tl.set(group, {{ autoAlpha: 1 }}, g.s);
    tl.fromTo(group + " .line", {{ scale: 0.82, y: 24 }}, {{ scale: 1, y: 0, duration: 0.16, ease: "back.out(3)" }}, g.s);
    if (g.emoji) tl.fromTo(group + " .emoji", {{ scale: 0, rotation: -20 }}, {{ scale: 1, rotation: 0, duration: 0.3, ease: "back.out(2.5)" }}, g.s);
    g.w.forEach(([s, e], j) => {{
      const word = "#g" + i + "w" + j;
      const off = j + 1 < g.w.length ? g.w[j + 1][0] : g.e;
      if (style === "pop") {{
        tl.fromTo(word + " .t", {{ color: "#ffffff" }}, {{ color: document.querySelector(word).classList.contains("key") ? "#3dff74" : "#ffe14d", duration: 0.01 }}, s);
        tl.fromTo(word, {{ scale: 1 }}, {{ scale: 1.08, duration: 0.1, ease: "power2.out" }}, s);
        tl.to(word, {{ scale: 1, duration: 0.12, ease: "power2.in" }}, Math.max(s + 0.1, off - 0.12));
        if (!document.querySelector(word).classList.contains("key")) tl.to(word + " .t", {{ color: "#ffffff", duration: 0.01 }}, off);
      }} else if (style === "box") {{
        tl.fromTo(word, {{ "--on": 0, "--bs": 0.8 }}, {{ "--on": 1, "--bs": 1, duration: 0.1, ease: "back.out(3)" }}, s);
        tl.to(word, {{ "--on": 0, duration: 0.01 }}, off);
      }} else {{
        tl.fromTo(word, {{ opacity: 0.55 }}, {{ opacity: 1, duration: 0.08 }}, s);
      }}
    }});
    tl.set(group, {{ autoAlpha: 0 }}, g.e);
  }});
  tl.set({{}}, {{}}, {duration});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["{id}"] = tl;
}})();
</script>
</body>
</html>
"""
