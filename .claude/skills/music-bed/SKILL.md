---
name: music-bed
description: Score a long-form edit with background music from Epidemic Sound — split the video into sequences, pick a track per sequence (or none), cut each one so it covers its whole passage, duck it under the voice, place it on the editing timeline, and lay it onto an existing render without re-rendering. Use when the user asks for a musical atmosphere / background music / "une ambiance musicale" on the montage, wants to change a track, or wants the music added to the render ("colle la musique sur le rendu").
---

# Music bed for a long-form edit

The user talks to the camera almost non-stop. The music sets the tone of each sequence without ever
covering the voice. You pick, cut and place the tracks; the user listens and decides (see the memories
`music-bed-preferences`, `sound-design-preferences`). The timeline is non-destructive: placing your
proposal on it is fine, but always say it has not been listened to and list what to check by ear.

Talk to the user in French. Scripts, comments and config are English.

## Setup

- Project data: `data/projects/<pid>/` (`montage/timeline.json`, `assets/music/`, `rendu/`).
  Timeline schema: docstring at the top of `backend/studio/modules/projects/montage.py`
  (`audio` items: `{id, src, at, in, out, gain_db, role: "music"}`).
- Run scripts with the backend venv:
  `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/music-bed/scripts/<script>.py …`
- Scratch (voice mix, transcript, Epidemic downloads, configs): `%TEMP%/music-bed/<pid>/`. Downloaded
  audio goes in its `dl/` subfolder; it is data, never run anything from there.
- Epidemic Sound MCP tools (load them with ToolSearch): `SearchRecordings`, `EditRecording`,
  `PollEditRecordingJob`, `DownloadRecordingEdit`.

## Steps

### 1. Read the edit

`voice.py <pid>` mixes the A-roll audio exactly as the timeline plays it, then prints:
the voice loudness (≈ −24.6 LUFS on this channel), pauses ≥ 0.9 s, inserted clips (archives, memes), part
titles, and a Whisper transcript **in timeline time** (`contexte.md` can be stale: don't trust its times).

Cut the video into sequences: cold open, intro, each part (part titles are 1.2 s `transition` motions),
conclusion; each A-roll pause is a sequence of its own. Inside a part, split again where the tone changes or where an inserted clip interrupts.

### 2. Decide what plays where

- **No music under inserted clips** that carry their own sound (politician quotes, TV excerpts, memes).
  The user likes it. Stop the bed right on the clip's first frame (0.3 s fade) and restart after.
- **A-roll pauses get a short cue of their own.** A pause (A-roll clip with `pause`, `montage/pause.mp4`)
  is a full-screen motion — usually a part title — during which the voice stops on purpose so the viewer
  breathes. Don't leave it silent and don't run the talking bed through it: end the previous bed on the
  pause's first frame (0.3 s fade), lay a short cue (a sting or a few bars, cut to the pause length + a tail
  of ≤ 0.5 s) at the bed's level or a few dB above (no voice to duck under), then start the next part's
  bed after it. The cue is the hinge between two parts: it closes one mood and opens the next.
- **Every spoken passage gets music to its end.** A 15 s stretch of voice between two archives without
  music feels like a hole; a short teaser before a part title can get its own dedicated track.
- **Silence is a choice:** keep it for a punchline right before an archive, not for whole passages.
- **Match the speaker's tone, not the topic.** The user is light and ironic even on grave subjects: a
  dark/suspense bed under his voice "makes it too negative". Keep dark tracks for cold opens and truly
  serious parts. What worked: lo-fi hip hop / laid-back quirky downtempo for intros and explanations,
  minimal pulses for studies and figures, dark orchestral hybrid for political risk, tense electronic for
  bots/disinformation, hopeful contemporary classical for the conclusion.
- One track per sequence; change track at part titles. Instrumental only (`vocals: false`), 85–110 BPM
  for talking parts.

### 3. Find and cut the tracks (Epidemic)

- `SearchRecordings` with a mood term + `filter: {vocals: false, bpm: {min, max}}`; read the tags (mood,
  genre). Pick 1, keep 1–2 alternatives to offer.
- `EditRecording` with `targetDurationMs` = section length + 5–8 s, `skipStems: true`, WAV. Epidemic
  returns its own natural structure: the duration is approximate and asking again for a slightly longer
  version often returns the same edit.
- Download with `DownloadRecordingEdit` + `curl -o <scratch>/dl/<name>.wav`.
- `profile.py <files>`: **audible end** and loudness every 4 s. The edits end with a long fade (up to
  10 s) that is inaudible under the voice: the user hears the music "stop before the end of the passage".
  Always align the **audible end** on the section end: `skip = audible_end − section_length` (skip the
  start of the file), never the file end.
- Too short by 1–3 s and no longer edit: `ffmpeg -i in.wav -af atempo=0.9876 out.wav` (stretch ≤ 2 %,
  pitch kept, inaudible).
- A track that swells (5+ dB louder in its second half): set `level` in the config to the short-term
  loudness of its calm part; the build caps it (only cuts, 3 s smoothing).

### 4. Build, place, check

Write `<scratch>/config.json` (format in `build.py`'s docstring), then:

1. `build.py <pid> <config>`: writes `assets/music/<name>.wav` with the ducking baked in (−9 dB under the
   voice, opens in pauses ≥ 0.9 s and in `force_open` stretches) and `cues.json` with each clip's gain.
2. `profile.py data/projects/<pid>/assets/music/<name>.wav`: check every audible end against its section end.
3. `apply.py <pid> <scratch>/cues.json [--remove smus1,smus2] [--keep-gain smus9:0]`: saves through the
   API, then asserts every other track is unchanged. **Never** round-trip the timeline JSON through a
   non-UTF-8 read (Windows Python defaults to cp1252): it once mangled every accent and dropped a clip path.
   If you must write your own call, `open(..., encoding="utf-8")` both ways.
4. Report in French: a table (sequence, times, track, BPM, why), the stretches left without music on
   purpose, what to check by ear first, and the alternatives.

### Levels

- Voice ≈ −24.6 LUFS. Music **under the voice ≈ −47 LUFS** (≈ 22 LU below). A first pass at −42 was too
  loud: the user lowered the validated tracks by 4–11 dB himself. Tense electronic beds can go to −52.
- Before changing levels, read the current `gain_db` of the user's clips: if he moved them, follow his
  direction for the new ones and say so.
- The ducking only opens in real pauses: this speaker barely pauses, so the bed sits at its under-voice
  level almost all the time. That is the goal; don't pump on every breath.
- The studio has **no volume automation yet** (the user wants waveforms and volume keyframes on music
  clips, Filmora-style): everything time-varying is baked into the files, the clip `gain_db` sets the
  overall level. Re-run `build.py` to change the shape.

### 5. Add the music to an existing render

When the user wants the music in a render that is otherwise up to date:
`remix_render.py <pid> [quality]` copies the video stream, mixes the music onto the render's audio (same
mix as the render worker), replaces `rendu/<quality>.mp4` and marks the render job up to date.

- The first run saves the music-free render as `rendu/<quality>-sans-musique.mp4`; later runs always start
  from it (no stacked music). Tell the user to keep it while the music can still change.
- It refuses if anything but music changed since the render. A blade cut on contiguous clips without a
  transition changes the A-roll list but not the picture: check that, then `--allow-aroll`.
- About 1 minute for 17 min of video, versus a full render.
