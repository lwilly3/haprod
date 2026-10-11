"""
Importe les cartes de motion design d'editing-os (style-library/) dans la bibliothèque, onglet
Animations : 12 styles, chacun avec sa charte (tokens.css, polices) et ses cartes HyperFrames.

  ..\\.venv\\Scripts\\python scripts/import_editing_os.py [chemin/vers/editing-os-starter]

Par défaut, le kit est cherché dans ../editing-os-starter. Sortie dans
data/library/animations/editing-os/ (contenu de tiers, jamais versionné) : un dossier par style,
à l'arborescence d'origine pour que les « ../../tokens.css » des cartes se résolvent, et index.json
que lit l'API. Relancer le script remplace l'import précédent.
"""
import json
import re
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from studio.modules.projects.library import EDITING_OS_DIR  # noqa: E402

# ce qu'il faut d'un style pour afficher ses cartes : pas les aperçus ni les références
KEEP = ("tokens.css", "style.json", "DESIGN.md", "PLAYBOOK.md", "fonts", "cards")


def card_info(path: Path) -> dict:
    """Titre, description et format d'une carte, lus dans son commentaire d'en-tête et sa racine."""
    html = path.read_text(encoding="utf-8")
    comment = re.search(r"<!--(.*?)-->", html, re.S)
    lines = [ln.strip() for ln in comment.group(1).strip().splitlines()] if comment else []
    # 1re ligne « MAISON · tier1 · stat · NAVY COUNTUP » ; la ligne « Slots: » est pour l'assembleur
    head = lines[0].split("·")[-1].strip().capitalize() if lines else path.stem
    text = " ".join(ln for ln in lines[1:] if ln and not ln.lower().startswith("slots"))
    root = re.search(r"<div[^>]*data-composition-id=\"([^\"]+)\"[^>]*>", html)
    tag = root.group(0) if root else ""
    w = re.search(r'data-width="(\d+)"', tag)
    h = re.search(r'data-height="(\d+)"', tag)
    short = bool(w and h and int(h.group(1)) > int(w.group(1)))
    return {"id": root.group(1) if root else path.stem, "head": head, "description": text,
            "format": "short" if short else "youtube"}


def main() -> None:
    kit = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND_DIR.parent / "editing-os-starter"
    library = kit / "style-library"
    registry = json.loads((library / "registry.json").read_text(encoding="utf-8"))
    if EDITING_OS_DIR.exists():
        shutil.rmtree(EDITING_OS_DIR)
    EDITING_OS_DIR.mkdir(parents=True)

    styles, cards = [], {}
    for style in registry["styles"]:
        folder = library / style["folder"]
        for name in KEEP:
            src = folder / name
            if src.is_dir():
                shutil.copytree(src, EDITING_OS_DIR / style["folder"] / name)
            elif src.is_file():
                (EDITING_OS_DIR / style["folder"]).mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, EDITING_OS_DIR / style["folder"] / name)
        out = []
        for card in style["cards"]:
            path = library / card["file"]
            if not path.is_file():
                continue
            info = card_info(path)
            out.append({"file": card["file"], "id": info["id"], "key": card["id"],
                        "title": f"{card['purpose']} · {info['head']}".replace("-", " "),
                        "description": info["description"], "tier": card["tier"], "purpose": card["purpose"],
                        "slots": card.get("slots", []), "format": info["format"],
                        "duration": (card.get("duration") or {}).get("max")})
        styles.append({"id": style["id"], "name": style["name"], "inspiration": style.get("inspiration", ""),
                       "count": len(out)})
        cards[style["id"]] = out
        print(f"{style['id']:<18} {len(out):>5} cartes")

    (EDITING_OS_DIR / "index.json").write_text(
        json.dumps({"styles": styles, "cards": cards}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(s['count'] for s in styles)} cartes dans {EDITING_OS_DIR}")


if __name__ == "__main__":
    main()
