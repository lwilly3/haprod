---
name: replace-aroll-take
description: Replace a stretch of the editing timeline's A-roll (between two blade cuts, or up to the end) with a re-recorded take dropped in the project's resources, keeping everything else — B-roll, motions, sound design, zooms, texts — re-placed on the new delivery using word-level transcripts. Use when the user says they re-filmed a part ("j'ai refilmé…", "remplace de 11:35 à 13:44 par anonymat-partie6.mp4", "mets anonymat-outro à la place de la fin").
---

# Replace an A-roll stretch with a new take

The user re-recorded part of the video. They mark the stretch with blade cuts in the editing step
(`/p/<pid>/montage`) and drop the new file in the project's resources. Your job: swap the A-roll,
transcribe the new take, re-place every element that sat on the old delivery so it still lands on its
words, shift everything after, and report what no longer matches. The user decides what to cut or remove:
never trim their hesitations, never delete their motions without saying so.

Talk to the user in French. Scripts, comments and config are English.

## Setup

- Project data: `data/projects/<pid>/` (`montage/timeline.json`, `montage/motion/<id>.html`, `ressources/`).
  Timeline schema: docstring at the top of `backend/studio/modules/projects/montage.py`.
- Run scripts with the backend venv, from anywhere:
  `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/replace-aroll-take/scripts/<script>.py …`
- Scratch files (transcripts, configs) go to `%TEMP%/replace-aroll-take/<pid>/` (`common.work_dir`).
  Never name a scratch script after a stdlib module (`inspect.py` broke the backend import once).

## Steps

### 1. Find the zone

`zone.py <pid> clips` lists the A-roll clips with their timeline start/end. The user's times are
approximate: the zone is the clip run between the two blade cuts nearest to them (a cut between two
contiguous source clips, `out` of one == `in` of the next). "Jusqu'à la fin" means up to the last clip.

- The zone can contain clips inserted from other media (a meme answering a line, `src` set). Keep them
  and re-insert them at the same line in the new take. If the user had cut the line the gag answers,
  cut it in the new take too (that's their earlier decision, not yours). Say so in the report.
- Elements placed just before the first cut (a part title, its whoosh) stay where they are; elements just
  before the end cut that announce the next part follow the end (the `tail` setting, 1 s by default).

### 2. Transcribe and compare

- `transcribe.py <pid> ressources/<take>.mp4 [more takes]` — ElevenLabs Scribe v2 (key in
  `data/transcription.json`), several files in parallel. Prints the phrases with times in the file.
- `zone.py <pid> old <a> <b>` — the old words on the timeline, and every element touching the zone
  (motions with their idea, sounds with their `motion`, zooms with their `beat`).
- `zone.py <pid> new <raw.json> <a> [<in>]` — the new take's words in timeline time.
- Loudness: `ffmpeg -ss <src_in> -t <len> -i <old media> -vn -af ebur128 -f null -` vs the new file;
  the new clip's `gain_db` = old LUFS − new LUFS (keep the old clips' own gain in mind).

### 3. Decide where everything goes

The new take is usually rewritten: lines appear, disappear, change order. Work element by element, with
the words in front of you. For every element on the zone, pick one:

- **Moved as is** (`groups`): its words are said the same way. Anchor it at the same distance from the
  same word. Sounds tied to a motion (`"motion": id`) follow automatically.
- **Retimed inside** (`motions`): a motion whose internal cues (comments like `// « chercheurs » (1.4)`)
  no longer match the new pace. Give knots `(old_t, new_t)` relative to the motion start: one per cue
  that must land on a word (new_t = new word time − new start − the same lead as before, usually 0.2 s),
  plus the exit and the end. The new `dur` usually changes. Sounds tied to it, and untied ones you list in
  `sounds` (a pop just before the entry, a ding on a counter), go through the same map. Helper calls
  (`lever("#i1", 2.56, 3.76)`, `panel(".p1", 8.45)`, `step(2, 1.06, …)`, `light(…, 2.6)`) need a regex
  in `helpers`; tween positions `}, t)` and the composition's `<script id="sfx">` cues are handled.
- **Trimmed** (`durs`): only to avoid an overlap, cutting the tail of a motion whose end matters least.
- **Fixed** (`fixed`): a single sound or zoom set to an absolute time.
- **Dropped** (`drop`): only for things that are plainly obsolete with the old take (a handwritten note
  about the old take's sound problem). Always report it.
- Content the new take no longer says (a figure, a study): keep the motion at the closest meaningful
  place, trimmed if needed, and list it under « à trier ».

Constraints to check: motions must not overlap; a motion can't cover an inserted A-roll clip (the gag
must be seen); a video inside a composition (`<video data-duration>`) must be long enough if you lengthen
the motion (fix it with `edits`).

### 4. Cut the new take

- `in`: keep the same lead before the first word as the old cut had (≈0.15–0.4 s).
- `out`: same tail after the last word; if the next clip has a transition, leave at least half its
  duration of media after the out point (the FCPXML transition eats it); never past the file's end.
- An internal transition of the old stretch (a punch-in `hblur` at a pivot line) is kept by splitting the
  new take in two clips at the matching line (cut in the silence before it).

### 5. Write the config, dry-run, apply

```python
# %TEMP%/replace-aroll-take/<pid>/zone1.py
SRC = "ressources/anonymat-partie6.mp4"
CFG = {
    "pid": "f728f85ffb",
    "clips": ["a10"],                 # the old clip run, in order
    "old": (694.4, 824.456),          # its timeline span (safety check: aborts if the timeline moved)
    "aroll": [                        # the replacement, in order; an id string reuses a clip of the run as is
        {"src": SRC, "in": 0.0, "out": 86.82, "gain_db": -1.2},
        "a7",                         # the meme kept between the two halves
        {"src": SRC, "in": 88.87, "out": 174.56, "gain_db": -1.2},
        # {"src": SRC, "in": …, "out": …, "transition": {"fx": "hblur", "dur": 0.5}, "gain_db": …},
    ],
    "raw": r"C:\Users\…\Temp\replace-aroll-take\f728f85ffb\anonymat-partie6_raw.json",
    "motions": {                      # retimed inside
        "m48": {"at": 721.64, "dur": 21.36, "sounds": ["s57"],
                "knots": [(0, 0), (1.56, 1.56), (2.56, 2.64), (3.76, 3.82), (11.26, 20.96), (11.66, 21.36)],
                "helpers": [r'lever\("#i\d", (?P<t1>-?\d+(?:\.\d+)?), (?P<t2>-?\d+(?:\.\d+)?)\)']},
    },
    "groups": [(794.84, ["m49"]), (830.17, ["z24", "z26", "z25"])],   # (new time of the first id, ids moved together)
    "fixed": {"s88": 326.45},
    "durs": {"m58": 4.95},
    "drop": [],
    "edits": {"m70.html": [('data-duration="5.01"', 'data-duration="7"')]},   # exact one-off replacements
}
```

`replace.py <config> --dry` first: it prints the new end, the delta applied to everything after, the
motion spans around the zone with `OVERLAP` marks, and how many instants each retimed composition gets.
It aborts if an element in the zone has no decision. Then run it without `--dry`. It:

1. saves the timeline through `montage.save` — one history step that holds the timeline **and every
   composition before the retiming**, plus the storyboard beat shift, so a single Ctrl+Z in the UI undoes
   the whole replacement (do the compositions only after this, never before);
2. moves the storyboard beats of re-placed elements with them;
3. rewrites the retimed compositions (keeping their CRLF line endings) and applies `edits`;
4. queues the motion renders and rewrites the FCPXML (`montage.after_change`);
5. writes `transcripts/<take>.srt/.txt` in the project.

Several zones in one request: apply them one after the other, re-reading `zone.py clips` in between
(the first one shifts the second).

### 6. Verify

- `zone.py <pid> clips`: the new clips, the total length (old total + delta).
- `montage.build(pid)` problems: only the usual ones (non-dissolve transitions, texts as markers,
  motions "pas encore rendu" while renders run).
- For retimed compositions, `diff --strip-trailing-cr` against `montage/.history/<last>/motion/<id>.html`:
  only instants changed. Cue comments keep their old word times; that's fine.

## Report (in French)

- What was replaced (zone, file, gain, delta, final length), what was kept (gags) and cut (if you mirrored
  an earlier cut of theirs).
- Each motion: moved, retimed (on which words), trimmed — and its new length when it changed.
- **À trier**: motions showing things no longer said, cues that land a bit early/late and why, anything
  dropped, new passages with nothing on screen (with timeline ranges).
- Remind them to reload the editing tab, and that one Ctrl+Z (focus on the timeline, not a text field)
  undoes the whole replacement.
