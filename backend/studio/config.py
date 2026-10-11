"""
Chemins et ports du studio, surchargeables par variables d'environnement.
"""
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
STUDIO_DIR = PACKAGE_DIR.parent.parent
WEB_DIST = STUDIO_DIR / "web" / "dist"

DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", STUDIO_DIR / "data"))
DB_PATH = DATA_DIR / "studio.db"

# port de l'interface : Vite en dev, l'API elle-meme en mode "prod"
UI_PORT = int(os.environ.get("STUDIO_PORT", "4400"))
# en dev, l'API tourne a cote de Vite qui lui relaie /api
API_PORT = int(os.environ.get("STUDIO_API_PORT", "4401"))
