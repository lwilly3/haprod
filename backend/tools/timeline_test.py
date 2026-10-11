r"""
Timeline de test pour vérifier ce que Resolve relit d'un FCPXML Studio :
une coupe sèche, un zoom animé décalé vers la droite, un whoosh sur la coupe,
un fondu enchaîné, une musique à -18 dB.

    ..\..\.venv\Scripts\python tools\timeline_test.py <rush1> <rush2> <rush3>

Écrit data/tests/timeline/test.fcpxml (et les sons générés à côté).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.config import DATA_DIR  # noqa: E402
from studio.core.system import tool  # noqa: E402
from studio.modules.projects import timeline  # noqa: E402

OUT = DATA_DIR / "tests" / "timeline"


def generate(dest: Path, source: str, seconds: float) -> Path:
    """Un son de synthèse (ffmpeg lavfi), pour ne dépendre d'aucune bibliothèque."""
    if not dest.exists():
        subprocess.run([tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", str(seconds),
                        "-ar", "48000", "-ac", "2", str(dest)], check=True)
    return dest


def main(rushes: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # whoosh : bruit rose filtré, qui monte puis retombe
    whoosh = generate(OUT / "whoosh.wav", "anoisesrc=color=pink:amplitude=0.8,highpass=f=400,"
                      "afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35", 0.7)
    music = generate(OUT / "music.wav", "sine=frequency=220:sample_rate=48000,volume=0.5", 30)

    assets = {f"rush{n}": timeline.asset(p) for n, p in enumerate(rushes, 1)}
    assets["whoosh"] = timeline.asset(whoosh)
    assets["music"] = timeline.asset(music)
    first = assets["rush1"]
    tl = {
        "fps_num": first["fps_num"], "fps_den": first["fps_den"], "width": first["width"], "height": first["height"],
        "assets": assets,
        "clips": [
            {"asset": "rush1", "in": 1.0, "out": 5.0},
            # zoom de 1 à 1,4 entre 1 s et 3 s du clip, centre décalé de 10 % de la largeur vers la droite
            {"asset": "rush2", "in": 1.0, "out": 6.0,
             "zoom": [{"t": 1.0, "scale": 1.0, "x": 0.0, "y": 0.0}, {"t": 3.0, "scale": 1.4, "x": 0.1, "y": 0.0}]},
            {"asset": "rush3", "in": 1.0, "out": 6.0, "transition": {"type": "dissolve", "duration": 1.0}},
        ],
        "audio": [
            {"asset": "whoosh", "at": 3.65, "in": 0.0, "out": 0.7, "gain_db": -3, "role": "sfx"},
            {"asset": "music", "at": 0.0, "in": 0.0, "out": 14.0, "gain_db": -18, "role": "music"},
        ],
    }
    problems = timeline.check(tl)
    if problems:
        sys.exit("\n".join(problems))
    dest = OUT / "test.fcpxml"
    dest.write_text(timeline.fcpxml(tl, "Studio — test FCPXML"), encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(sys.argv[1:])
