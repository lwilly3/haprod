"""
La bibliothèque des transitions du montage : les transitions `xfade` de ffmpeg, rangées par famille comme
une galerie de logiciel de montage (fondus, balayages, glissements, formes, effets).

Une transition dans la timeline : {"fx": <id ci-dessous>, "dur": s}
- entre deux clips de l'A-roll (`transition` du clip entrant), centrée sur la coupe ;
- à l'entrée ou à la sortie d'un B-roll ou d'un motion (`enter` / `exit`) : depuis ou vers ce qui est
  dessous ; un plan qui suit un autre plan de la même piste sans trou s'enchaîne avec lui par son `enter`,
  centré sur la coupe (comme entre deux clips de l'A-roll).

La démo de chaque transition (galerie) est rendue par ffmpeg lui-même, donc identique au rendu final.
"""
import subprocess
from pathlib import Path

from ...config import DATA_DIR
from ...core.system import tool

# id (= nom xfade), famille, ce qu'on voit (pour Daryl)
CATALOG: list[tuple[str, str, str]] = [
    ("fade", "fondus", "fondu enchaîné"),
    ("fadeblack", "fondus", "passage par le noir"),
    ("fadewhite", "fondus", "passage par le blanc (flash)"),
    ("fadegrays", "fondus", "fondu qui passe par le gris"),
    ("dissolve", "fondus", "dissolution en grain"),
    ("wipeleft", "balayages", "balayage net vers la gauche (le nouveau plan arrive par la droite)"),
    ("wiperight", "balayages", "balayage net vers la droite (arrive par la gauche)"),
    ("wipeup", "balayages", "balayage net vers le haut (arrive par le bas)"),
    ("wipedown", "balayages", "balayage net vers le bas (arrive par le haut)"),
    ("smoothleft", "balayages", "balayage doux vers la gauche"),
    ("smoothright", "balayages", "balayage doux vers la droite"),
    ("smoothup", "balayages", "balayage doux vers le haut"),
    ("smoothdown", "balayages", "balayage doux vers le bas"),
    ("diagtl", "balayages", "balayage en diagonale vers le coin haut gauche"),
    ("diagtr", "balayages", "balayage en diagonale vers le coin haut droit"),
    ("diagbl", "balayages", "balayage en diagonale vers le coin bas gauche"),
    ("diagbr", "balayages", "balayage en diagonale vers le coin bas droit"),
    ("wipetl", "balayages", "volet qui se replie vers le coin haut gauche"),
    ("wipetr", "balayages", "volet qui se replie vers le coin haut droit"),
    ("wipebl", "balayages", "volet qui se replie vers le coin bas gauche"),
    ("wipebr", "balayages", "volet qui se replie vers le coin bas droit"),
    ("radial", "balayages", "balayage en aiguille d'horloge"),
    ("hlslice", "balayages", "lamelles verticales vers la gauche"),
    ("hrslice", "balayages", "lamelles verticales vers la droite"),
    ("vuslice", "balayages", "lamelles horizontales vers le haut"),
    ("vdslice", "balayages", "lamelles horizontales vers le bas"),
    ("hlwind", "balayages", "coup de vent vers la gauche"),
    ("hrwind", "balayages", "coup de vent vers la droite"),
    ("vuwind", "balayages", "coup de vent vers le haut"),
    ("vdwind", "balayages", "coup de vent vers le bas"),
    ("slideleft", "glissements", "poussée vers la gauche : le nouveau plan pousse l'ancien"),
    ("slideright", "glissements", "poussée vers la droite"),
    ("slideup", "glissements", "poussée vers le haut"),
    ("slidedown", "glissements", "poussée vers le bas"),
    ("coverleft", "glissements", "le nouveau plan glisse par-dessus, depuis la droite"),
    ("coverright", "glissements", "le nouveau plan glisse par-dessus, depuis la gauche"),
    ("coverup", "glissements", "le nouveau plan glisse par-dessus, depuis le bas"),
    ("coverdown", "glissements", "le nouveau plan glisse par-dessus, depuis le haut"),
    ("revealleft", "glissements", "l'ancien plan s'en va vers la gauche et découvre le nouveau"),
    ("revealright", "glissements", "l'ancien plan s'en va vers la droite"),
    ("revealup", "glissements", "l'ancien plan s'en va vers le haut"),
    ("revealdown", "glissements", "l'ancien plan s'en va vers le bas"),
    ("circleopen", "formes", "iris qui s'ouvre depuis le centre"),
    ("circleclose", "formes", "iris qui se ferme sur le centre"),
    ("circlecrop", "formes", "iris qui se ferme au noir puis s'ouvre sur le nouveau plan"),
    ("rectcrop", "formes", "cadre qui se ferme au noir puis s'ouvre sur le nouveau plan"),
    ("vertopen", "formes", "portes qui s'ouvrent (bande verticale depuis le centre)"),
    ("vertclose", "formes", "portes qui se ferment"),
    ("horzopen", "formes", "ouverture horizontale depuis le centre"),
    ("horzclose", "formes", "fermeture horizontale"),
    ("zoomin", "effets", "zoom avant dans l'ancien plan puis fondu"),
    ("squeezeh", "effets", "l'ancien plan s'écrase verticalement"),
    ("pixelize", "effets", "pixellisation"),
    ("hblur", "effets", "flou de mouvement horizontal"),
    ("distance", "effets", "fondu par distance de couleur"),
]
IDS = [c[0] for c in CATALOG]
GROUPS = ["fondus", "balayages", "glissements", "formes", "effets"]
DUR = (0.2, 2.0)
DEFAULT_DUR = 0.6

DEMO_DIR = DATA_DIR / "cache" / "transitions"
DEMO_SIZE = (480, 270)
DEMO_FPS = 30
# démo : le plan A tenu, la transition, le plan B tenu
DEMO_HOLD, DEMO_DUR = 0.5, 1.0


def clean(raw) -> dict | None:
    """Une transition sûre, ou None (coupe franche). Un nombre seul (ancienne timeline) est un fondu."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = {"fx": "fade", "dur": raw}
    if not isinstance(raw, dict):
        return None
    try:
        dur = round(float(raw.get("dur", DEFAULT_DUR)), 3)
    except (TypeError, ValueError):
        dur = DEFAULT_DUR
    if dur < DUR[0] / 2:
        return None
    fx = raw.get("fx") if raw.get("fx") in IDS else "fade"
    return {"fx": fx, "dur": min(dur, DUR[1])}


def label(fx: str) -> str:
    return next((c[2] for c in CATALOG if c[0] == fx), fx)


def prompt_lines() -> list[str]:
    """Le catalogue pour Daryl, famille par famille."""
    return [f"- {g} : " + " ; ".join(f"`{i}` {d}" for i, grp, d in CATALOG if grp == g) for g in GROUPS]


def catalog() -> list[dict]:
    return [{"fx": i, "group": g} for i, g, _ in CATALOG]


def demo(fx: str) -> Path:
    """La démo de la transition (A → B), rendue une fois par ffmpeg puis gardée."""
    if fx not in IDS:
        raise ValueError(f"transition inconnue : {fx}")
    dest = DEMO_DIR / f"{fx}.mp4"
    if dest.is_file():
        return dest
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    w, h = DEMO_SIZE
    length = DEMO_HOLD * 2 + DEMO_DUR
    font = "C\\:/Windows/Fonts/arialbd.ttf" if Path("C:/Windows/Fonts/arialbd.ttf").is_file() else ""
    def plate(name: str, c0: str, c1: str) -> str:
        text = (f",drawtext=fontfile='{font}':text={name}:fontsize={h // 2}:fontcolor=white@0.92:"
                f"x=(w-tw)/2:y=(h-th)/2") if font else ""
        return (f"gradients=s={w}x{h}:r={DEMO_FPS}:d={length}:c0={c0}:c1={c1}:x0=0:y0=0:x1={w}:y1={h}:speed=0"
                f"{text},format=yuv420p,settb=1/{DEMO_FPS}")
    graph = (f"{plate('A', '0x2b6cb0', '0x153e75')}[a];{plate('B', '0xdd6b20', '0x9c3d10')}[b];"
             f"[a][b]xfade=transition={fx}:duration={DEMO_DUR}:offset={DEMO_HOLD}[v]")
    tmp = dest.with_suffix(".tmp.mp4")
    subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-filter_complex", graph, "-map", "[v]",
                    "-t", f"{length}", "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(tmp)], check=True, capture_output=True)
    tmp.replace(dest)
    return dest
