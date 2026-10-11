# Plan — storyboard de motion design et bibliothèque d'inspirations

Reprise d'idées d'**editing-os** (dossier `editing-os-starter/`, kit Claude Code + HyperFrames d'un autre
créateur, licence MIT, analysé le 09/10/2026). On en reprend les méthodes, pas les fichiers : ses scripts
supposent macOS et ses cartes sont en anglais, calées sur ses styles.

## Où on en est

**Fait (10/10/2026)**
- Dérush automatique : onglet **Daryl** de l'étape Dérush (`backend/studio/modules/projects/autoderush.py`,
  `web/src/project/steps/derush/AutoDerush.vue`). Recalage des mots sur le son, silences avec respiration
  selon le contexte, bégaiements, lecture des prises par Claude (coupes désignées en texte + ancre
  `before`, jamais en timecode), contrôles (phrase encore dite deux fois, contenu coupé sans équivalent,
  coupe introuvable). Rien n'est coupé sans « Appliquer ». Testé sur « Lever l'anonymat ? » : 35 coupes
  de prises toutes retrouvées, 1 avertissement, ~1 min.
- Les transcriptions enregistrent leur moteur (`state.engine`, `transcript/tasks.py`). Dans « Lever
  l'anonymat ? », les rushes 0021, 0024, 0025, 0026 et 0028 sont encore en Whisper (à refaire en ElevenLabs).

- Phase 1.1 + 1.2 : `backend/studio/modules/projects/storyboard.py` (job `project_storyboard`, file
  `storyboard`), routes `GET/POST /{pid}/montage/storyboard` et `POST …/storyboard/stop`. Le transcript de
  la timeline est reconstruit mot à mot (`timeline_words`) ; Claude donne `line` + `anchor` + `until`
  (jamais de timecode) ; `at` = mot d'ancre − 0,2 s, fin = dernier mot couvert + 0,5 s (2,5 à 15 s) ;
  `fit` raccourcit un beat qui déborde ; `check` (refait à chaque lecture) signale `anchor`, `late`
  (hors −0,2 / +1,8 s), `overlap`, `busy` (motion déjà là), `density`. Testé sur « Lever l'anonymat ? »
  (17 min, densité équilibrée) : 32 beats en 2 min, toutes les ancres retrouvées, aucun avertissement.
- Phase 1.3 : le storyboard est **une étape à part** (`storyboard`, phase « long », avant Montage) :
  `web/src/project/steps/StoryboardStep.vue` + `montage/useStoryboard.ts`. Beats en cartes larges
  (quand / il dit + on montre / place, type, base du kit, son), aperçu fixe à droite avec la place du
  beat dessinée dessus, bande de rythme en haut, ↑/↓ d'un beat à l'autre. Retouches par
  `PUT …/storyboard`. « Valider → Montage » termine l'étape, sans rien générer.
- Places d'un beat : `full`, `left`, `right`, `top`, `lower` (l'ancien `side` est lu comme `right`).
  Choisies sur un petit écran 16:9 cliquable. À la génération, Daryl reçoit 3 images de la vidéo
  (20 / 50 / 80 % de la durée) pour mettre le visuel du côté libre. Les zooms restent au Montage.
- Chat du storyboard, sous l'aperçu (`storyboard_chat.py`, job `{pid}-storyboard-chat`, file `storyboard` ;
  `web/src/project/steps/storyboard/StoryboardChat.vue`) : demande sur toute la vidéo ou sur le moment
  choisi (beat sélectionné, sinon tête de lecture), avec l'image de la vidéo source à ce moment
  (ffmpeg → `montage/frames/frame-<ms>.jpg`, lue par Daryl avec Read). Réponse structurée
  (`add` / `update` / `remove`) : un beat ajouté est placé par ses mots exacts (`locate`), une ancre
  introuvable est signalée. Les retouches à la main sont bloquées pendant sa réponse. Session reprise
  d'un tour à l'autre (le transcript n'est envoyé qu'au premier). Pas encore testé avec Claude.
- Phase 1.4, dans le Montage (c'est là qu'on teste le rendu) : les beats cochés sans animation sont en
  pointillés sur la piste motion (clic = la lecture va sur le beat) et en slide sur l'aperçu, à leur place
  (`Preview.vue`, props `beats` / `create` / `anims`), avec « Créer l'animation », et « Créer les n
  animations » dans la barre d'outils. `POST …/storyboard/animate` (`beats` : ids, sinon tous) :
  `storyboard.compose` pose un motion par beat (`beat` = id du beat, place et durée validées) et son son
  d'entrée (0,15 s avant, −12 dB), puis **une tâche par beat** (`beat_anim.py`, job `{pid}-anim-{beat}`)
  écrit `motion/<id>.html` avec une fiche courte (`storyboard.brief`, mots du beat avec leurs instants,
  `MOTION_RULES`, charte, modèle du kit). 3 files (`beat_anim_0..2`) : 3 créations à la fois, les autres
  en file. État par beat dans `view.anim_jobs` (file, en cours + activité, échec) : sur la slide et dans
  la barre « Animations » du Montage, avec Arrêter / Relancer. Un beat compte comme animé quand son HTML
  existe (`storyboard.animated`) : un motion posé mais jamais écrit se relance. Le chat du monteur ne
  compose plus de beats ; `contexte.md` liste les motions en cours de création pour qu'il n'y touche pas.
  Lois chiffrées d'editing-os ajoutées à `MOTION_RULES`, « Fais le travail » retiré.
- **Types de beats** (`type`) : `motion`, `zoom`, `broll`, `transition` (un ancien beat est un motion).
  - zoom : `zoom {scale 1,05–1,5, x, y}`, le centre borné pour que le cadre reste dans l'image (`zoom_of`),
    2 à 8 s, 0,1 s avant le mot ; posé tel quel sur la piste `zooms` (champ `beat`).
  - broll : `src` (média visuel du projet ou de la bibliothèque, `storyboard.visuals`) ou, vide, une
    suggestion « à trouver » avec `search`. Une vidéo va sur la piste `broll` ; une image devient un motion
    animé par Daryl (copiée dans `motion/media/<beat>-<nom>`, plein écran ou sur un côté comme un portrait).
    Les plans Image / Écran / B-roll du script deviennent des broll avec leur média attaché.
  - transition : plein écran, 1,2 s, 0,9 s avant les premiers mots de la nouvelle partie ; un motion animé
    par Daryl avec une fiche dédiée.
  - Contrôles : chevauchement entre ce qui occupe l'écran (motion, broll, transition) et entre zooms,
    `hidden` (zoom sous un plein écran), `busy` par piste ; la densité ne compte que les motions.
  - Génération : choix des types à proposer (`types`). Écran : filtres par type, couleurs, carte par type
    (zoom : grossissement + cadre cliquable sur l'image de la vidéo ; broll : média, aperçu, recherche à
    copier, lien Assets). Montage : « Créer les n animations » et « Poser n zooms et B-roll » ; un zoom ou
    un B-roll vidéo pas encore posé se voit déjà dans l'aperçu. `POST …/animate` rend
    `{queued, placed, skipped, missing}`. Pas encore testé avec une vraie génération de Claude.
- **Suite décidée** : retours image par image dans le Montage (temps local du motion + beat + HTML
  envoyés à Daryl, sans rendu ; retours accumulés puis envoyés ; un retour généralisable devient une règle).
- Plans du script : les plans Animation / Texte à l'écran de `script.json` sont les beats de départ
  (`origin: "script"`, `plan` = id du plan), repérés dans la timeline par vote de triplets de mots
  (`find_passage`) ; Daryl les détaille sans les remplacer et n'ajoute des beats (`origin: "daryl"`) que
  pour la densité ; un plan qu'il oublie est posé tel quel ; un plan introuvable est signalé. Les plans
  Image / Écran / B-roll / Insert / Plan de coupe occupent l'écran : contrôle `cover`. Les plans sont
  aussi listés dans `contexte.md` pour le chat du monteur. « Lever l'anonymat ? » : 12 plans repris sur 13
  (« 35 millions de comptes » dit autrement), 21 beats ajoutés, aucun avertissement.

- **Bibliothèque de transitions** (10/10/2026) : `backend/studio/modules/projects/transitions.py`, les 55
  transitions `xfade` de ffmpeg 7.1 en 5 familles (fondus, balayages, glissements, formes, effets ; `squeezev`
  retirée, elle fait planter ffmpeg). Timeline : `transition` de l'A-roll = `{fx, dur}` (un ancien nombre est lu
  comme un fondu), `enter` / `exit` sur B-roll et motions. Rendu (`render.overlay_groups`) : entrée et sortie =
  `xfade` contre une image transparente, un plan collé au précédent de sa piste avec une entrée s'enchaîne avec
  lui (centré sur la coupe, vraies images du média autour). Galerie : démos rendues par ffmpeg
  (`data/cache/transitions/`), onglet Transitions de la Bibliothèque, sélecteur dans l'inspecteur du Montage et
  sur les cartes motion / B-roll du storyboard. Aperçu du Montage en CSS (`web/src/lib/transitions.ts`,
  `layersAt`), approché pour lamelles, vent, pixels, dissolution. Daryl propose `enter_fx` / `exit_fx` au
  storyboard et connaît le catalogue au chat du Montage. Resolve : fondu enchaîné à la place des autres
  transitions de l'A-roll, coupes franches pour les entrées / sorties (signalé à l'export).

**Pas encore fait, à garder en tête**
- Vérification après rendu (re-transcrire le MP4 exporté et vérifier que les coupes ont porté).
- Mastering -14 LUFS (loudnorm deux passes, puis `aresample=48000`, `alimiter`, `aformat=s16` avant l'AAC :
  voir `editing-os-starter/scripts/master.py`).
- Export de la timeline du dérush : remis à plus tard par l'utilisateur.

## Constat de départ (étape Montage)

- Daryl crée les motions **directement** dans `montage/timeline.json` + `montage/motion/<id>.html`. Son
  prompt dit « Fais le travail, ne propose pas seulement » (`montage_tasks.py`), ce qui contredit la règle
  de l'utilisateur : l'IA propose, l'utilisateur décide.
- Une seule charte (`animations/kit/style.css`) et 2 exemples (`exemple-arbre`, `exemple-chronologie`).
- Les shorts ont leur propre flux de slides (`animations/service.py`), avec des densités sobre / équilibrée / dense.

## Phase 1 — Storyboard dans l'étape Montage

But : Daryl propose d'abord un storyboard, l'utilisateur le valide, et seulement ensuite il compose.
Méthode reprise de `editing-os-starter/.claude/skills/design-beats/SKILL.md`.

### 1.1 Génération (job `project_storyboard`, sortie structurée)
- Entrées : transcript en temps timeline (comme `contexte.md`), chapitres, script, charte, densité choisie,
  sélection d'inspirations (phase 2).
- La question pour chaque passage : « qu'est-ce qu'on **montre** pendant qu'il dit ça ? », jamais « quel
  texte on affiche ». Grille de traduction adaptée à la vidéo longue éducative : chiffre → compteur qui se
  construit ; processus → schéma qui s'assemble ; comparaison → A/B ; date → chronologie ; outil cité →
  capture ou logo ; liste → éléments qui se cochent. Interdits : carte-label statique, texte qui répète la
  parole, décor.
- Un beat : `{id, at, dur, anchor (mots exacts du départ), says, show, kind, place (plein écran | côté |
  bas), motion (entrée / entretien / sortie), sfx, ref (inspiration, phase 2), why}`.
- Stockage : `montage/storyboard.json`.

### 1.2 Contrôles automatiques
- L'ancre existe dans le transcript, et le beat démarre entre 0,2 s avant et 1,8 s après le mot ancré
  (« Gate 0 » d'editing-os) : sinon on recale ou on signale.
- Pas de chevauchement ; densité réelle comparée à la densité demandée.
- Ancre introuvable : signalée, pas devinée (comme le dérush automatique).

### 1.3 Écran (onglet Storyboard de l'étape Montage, à côté du chat)
- Une ligne par beat : timecode cliquable, « il dit », « on montre » modifiable, type, place, case à cocher,
  supprimer, « refaire ce beat ».
- Les beats en fantôme sur la piste motion de la timeline, pour juger le rythme.
- Bouton « Composer les n beats validés ».

### 1.4 Composition depuis le storyboard
- Daryl ne compose que les beats validés, en suivant « on montre » ; tout écart est re-proposé.
- Le chat garde l'édition directe pour les petites demandes explicites ; une création d'ensemble passe par
  le storyboard. Retirer « Fais le travail, ne propose pas seulement ».
- Ajouter à `MOTION_RULES` les lois chiffrées d'editing-os (`MOTION_PHILOSOPHY.md`, skill `motion-doctrine`) :
  une idée par beat ; visuel 0,2 s avant le mot ; sortie ≈ 75 % de la durée d'entrée ; pas d'oscillation
  décorative (`repeat: -1`, yoyo) ; immobilité de 0,3 à 0,75 s avant un climax ; la timeline doit durer
  toute la composition (`tl.to({}, {duration}, 0)`), sinon flash noir.

## Phase 2 — Bibliothèque d'inspirations

But : une galerie de références de motion (démo, mécanique, prompt) dans laquelle l'utilisateur choisit et
annote ce que Daryl doit suivre. Modèle : `editing-os-starter/motion-library/` et
`scripts/motion-library/` (import, catégories, planches), `editing-os/lib/selection.mjs`.

### 2.1 Données
- Base : `editing-os-starter/motion-library/analyse.json` — 270 références analysées (54 pépites,
  159 solides, 57 faibles ; 15 usages : explicatif, data, typo, UI, produit…). Chaque fiche :
  `titre, resume, usage, usages, ambiance, mecanique {transitions, rythme, texte, techniques}, niveau,
  pourquoi`.
- Import porté en Python : démos, posters et prompts depuis julienpocinho.fr et prompt-motion.com
  (décodage des morceaux RSC Next.js, voir `import.mjs`). 4 requêtes à la fois au plus.
- Planche de 12 images (4×3, 480×270) par démo avec ffmpeg, lue directement depuis l'URL ; vignette = le
  JPEG le plus lourd entre 25 et 85 % de la durée (les images noires pèsent presque rien).
- Stockage local `data/library/inspirations/` : **contenu de tiers, jamais dans le dépôt** (on ne versionne
  que l'importeur).
- Références de l'utilisateur : URL ou clip (téléchargement yt-dlp existant) ; Claude regarde la planche et
  remplit la fiche « mécanique » au même format.

### 2.2 Écran (onglet Inspirations de la page Bibliothèque)
- Grille de posters, démo au survol ; filtres usage / niveau / ambiance ; les faibles masqués par défaut.
- Fiche : démo, planche, mécanique, prompt d'origine. « Ajouter à ma sélection » avec une note.

### 2.3 Lien avec le storyboard
- Daryl reçoit la sélection et ses notes (prioritaires), puis l'index par usage ; il cite une référence par
  beat avancé, affichée en vignette sur la ligne du beat.
- On reprend la mécanique (mouvement, rythme, transitions), jamais l'habillage : la charte reste celle de
  l'utilisateur.

## Plus tard — styles (design system)
Plusieurs chartes au choix par projet (`tokens.css` + `DESIGN.md`), puis des cartes à emplacements de texte
(`data-slot` + `maxChars`), rangées par tier (t1 plein écran opaque, t2 transparent qui ne couvre pas le
visage) et par usage, avec une registry et un tirage reproductible sans répétition consécutive (voir
`editing-os-starter/style-library/GUIDE.md`, `.claude/skills/motion-graphics/`). Le champ `kind` / `place`
du storyboard deviendra le choix d'une carte.

## Ordre
1. Phase 1.1 + 1.2, testées sur un projet réel sans interface.
2. Phase 1.3 + 1.4 : utilisable pour de vrai.
3. Phase 2.1.
4. Phase 2.2 + 2.3.

## Décisions (10/10/2026)
1. **Vidéo longue uniquement** pour l'instant (les shorts plus tard).
2. Densité : reprendre les trois densités des slides (`animations/service.py`, `DENSITIES`) : sobre
   (~1 motion / 1 min 30), équilibrée (~1 / 30-45 s), dense (~1 / 15-20 s). Le rythme des reels
   d'editing-os (un événement toutes les 1 à 2 s) est trop dense pour une vidéo longue. **« Équilibrée »
   par défaut, réglable à chaque génération** (validé).
3. **Import complet** des inspirations (démos, posters, prompts des deux sites, en local).

## Notes d'outillage (réponses du 10/10/2026)
- **Analyser une animation** : editing-os ne décompose pas image par image. ffmpeg tire une planche de
  12 images réparties sur la démo, Claude la regarde (vision) avec le prompt d'origine et écrit la fiche
  « mécanique ». Ça capte la composition et les états, pas les courbes ni les timings fins. Pour reproduire
  une transition précise : une planche dense autour du moment (8 à 12 images par seconde sur 1 à 2 s),
  repéré par détection de changement de plan (`select='gt(scene,0.15)'`).
- **Détourage** : CLI HyperFrames, `npx hyperframes remove-background` (modèle u2net_human_seg, ~168 Mo,
  local, gratuit). Sortie ProRes 4444 ou WebM VP9 avec alpha. Lent : ~2 images/s en 1080p sur CPU, donc
  à réserver aux passages qui en ont besoin. Re-encoder d'abord une source à cadence variable (sinon sujet
  dédoublé), et appliquer les mêmes coupes à la vidéo et au détourage. Usages : texte derrière la personne
  (on rend vidéo + texte, puis on recolle la personne détourée par-dessus), personne qui dépasse d'une carte.
- **Musique et sons** :
  - editing-os : un pack de SFX maison nommés par rôle (`whoosh`, `pop`, `click`, `cash`, `impact`,
    `riser`, `buzzer`…) avec une table son ↔ animation et un volume par son (`asset-library/sfx/README.md`) ;
    la musique via `npx hyperframes media-use resolve --type bgm` (catalogue HeyGen, compte heygen
    requis) ; le mixage (ducking, fondus) via le skill `hyperframes-audio`.
  - Studio : bibliothèque `data/library/` (musique, sfx), Daryl ne place que des fichiers listés dans
    `contexte.md`, gains fixes, pas de ducking.
  - À reprendre : nommer les SFX par rôle et donner la table son ↔ animation à Daryl ; un `sfx` par beat
    dans le storyboard ; ducking de la musique sous la voix au rendu (`sidechaincompress` ffmpeg) ; le
    catalogue HeyGen seulement si l'utilisateur veut un compte de plus.
