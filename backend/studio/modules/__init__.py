"""
Les modules du studio. Chacun est un sous-package avec :

- api.py   : `router` (APIRouter), monte sous /api/<module>
- tasks.py : `TASKS` ({kind: Task}) et eventuellement `startup()`, charges
             uniquement par le worker (c'est la que vivent les imports lourds)

Ajouter un module = creer le dossier et l'ajouter a cette liste.
"""
MODULES = ("transcript", "youtube", "animations", "shorts", "projects", "settings")
