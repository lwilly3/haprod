# Règles du projet

## Commits

- Commits conventionnels : chaque libellé est préfixé par son type (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:`, `perf:`, `style:`, `build:`, `ci:`), avec un scope optionnel (`feat(web): …`).
- Commits atomiques : un commit = un changement cohérent. Ne pas mélanger plusieurs sujets dans un même commit.
- Libellés et messages de commit en anglais.
- Pas de ligne `Co-Authored-By: Claude` (ni autre mention de Claude) dans les commits.

## Ce qui est versionné

Uniquement notre travail. Ne sont jamais commités :

- `editing-os-starter/` : kit tiers de référence ;
- `data/` : fichiers de travail (projets, médias, base…), y compris la bibliothèque d'assets communs `data/library/`.
