---
name: commit-convention
description: Convention de commit à appliquer. Utilise ce skill dès que tu rédiges un message de commit ou que tu prépares un `git commit` dans ce projet, pour respecter le format Conventional Commits.
---

# Convention de commit 

Les dépôts suivent la spécification **[Conventional Commits](https://www.conventionalcommits.org/)**,
le standard des projets open source. Applique cette convention pour **tout** message de commit.

Les commits sont sur main, sauf mention explicite de l'utilisateur qui demande une branche

N'inscris pas Claude en coauthor

## Format

```
<type>(<scope facultatif>): <description>
```

- **Une seule ligne** dans l'immense majorité des cas (pas de corps de message).
- **En anglais**, toujours.
- **Description en minuscule**, concise, à l'impératif ou descriptive courte.
- **Pas de point final** (sauf phrase explicative volontaire).
- Un corps de message (body) reste possible, séparé par une ligne vide, uniquement quand un contexte
  supplémentaire est réellement utile (breaking change, explication d'un choix, référence à une issue).

## Types autorisés

Utilise **exactement** ces types (au singulier, orthographe exacte) :

| Type       | Usage                                                            |
|------------|-----------------------------------------------------------------|
| `feat`     | nouvelle fonctionnalité                                         |
| `fix`      | correction de bug                                              |
| `docs`     | documentation uniquement                                       |
| `style`    | formatage, sans impact fonctionnel (whitespace, lint…)         |
| `refactor` | refactoring sans ajout de feature ni correction de bug         |
| `perf`     | amélioration de performance                                    |
| `test`     | ajout ou correction de tests                                   |
| `build`    | système de build, dépendances, packaging, déploiement          |
| `ci`       | configuration d'intégration continue                          |
| `chore`    | tâches diverses (maintenance, config, montées de version…)     |
| `revert`   | annulation d'un commit précédent                              |

### Cas particulier : les releases

Les commits de version utilisent toujours ce format exact :

```
chore(release): v3.1.2
```

## Scope

Le scope est **facultatif** et rarement utilisé, hormis `chore(release)`.
Ne l'ajoute que s'il clarifie réellement (ex. `fix(toc): ...`, `feat(cli): ...`).

## Ne fais PAS

Les variantes suivantes traînent dans l'historique mais sont des **écarts à ne pas reproduire**.
Remappe-les toujours vers le type canonique :

| À éviter                          | Utiliser à la place        |
|-----------------------------------|----------------------------|
| `doc:` / `documentation:`         | `docs:`                    |
| `chores:`                         | `chore:`                   |
| `refacto:` / `refactoring:`       | `refactor:`                |
| `add:` / `update:` / `remove:` / `change:` / `upgrade:` | choisis `feat` / `fix` / `chore` selon la nature réelle du changement |
| `debug:` / `wip:` / `experimentation:` | à bannir : décris le vrai changement (`fix`, `chore`…) |
| type ou description en français   | tout en anglais            |

## Exemples valides (tirés de l'historique)

```
feat: add composable to find surrounded and related content
fix: tags page were broken
fix: dom manipulation on non existing block
docs: add recipe to use ai
refactor: improve social link component
perf: use zero runtime on the nuxt sitemap module
build: add deployment configuration to deploy on netlify
chore: update dependencies
chore(release): v3.0.0
```

## Procédure

1. Détermine le **type** en fonction de la nature réelle du diff (pas du nom du fichier).
2. Rédige une description **anglaise**, courte, en minuscule, sans point final.
3. Ajoute un scope seulement s'il apporte de la clarté.
4. N'ajoute un body que si un contexte est nécessaire.
5. En cas de doute entre deux types, privilégie `feat` (nouveauté visible), `fix` (correction),
   sinon `chore`.

## Passer le message à git

Ce projet est sous Windows, avec **deux shells disponibles** : PowerShell et Bash (Git Bash).
La syntaxe multi-ligne n'est pas la même, et **mélanger les deux corrompt silencieusement le message** :
git accepte n'importe quoi, l'erreur ne se voit qu'après coup dans `git log`.

Comme la convention impose une seule ligne dans l'immense majorité des cas, `-m "..."` suffit
et fonctionne dans les deux shells. **C'est le défaut à privilégier.**

Pour les rares commits avec un body :

| Shell        | Syntaxe                                                    |
|--------------|------------------------------------------------------------|
| Bash         | heredoc : `git commit -F - <<'EOF'` … `EOF`                |
| PowerShell   | here-string : `git commit -m @'` … `'@` (le `'@` en colonne 0) |

### Le piège à ne pas reproduire

Utiliser la here-string PowerShell `@'...'@` dans le tool **Bash**. Bash ne connaît pas cette
syntaxe : il lit `@` + une chaîne quotée + `@`, et les deux `@` atterrissent dans le message.

Symptôme : le sujet devient `@ ci: mon vrai sujet` (git recolle le `@` orphelin au sujet, faute de
ligne vide entre les deux) et un `@` traîne en fin de body.

Vérifie le message après coup, il n'y a pas d'erreur pour te prévenir :

```bash
git log -1 --format="SUBJECT: [%s]%n%nBODY:%n%b"
```

Si le message est cassé et **non poussé**, `git commit --amend -F -` est la bonne correction :
un nouveau commit ne répare pas un message.

