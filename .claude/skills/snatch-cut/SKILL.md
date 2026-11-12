---
name: snatch-cut
description: Analyze a video sequence and propose a Guy Ritchie-style "snatch cut" (a burst of object close-ups with snap zooms and punchy sound design, then a return to normal editing), with a preview render. Use when the user mentions a snatch cut, Guy Ritchie-style fast editing, a burst of shots with zooms and sound effects, or wants to energize an action sequence or a pre-intro.
---

# Snatch cut

A **burst of 4 to 7 object close-ups**, 0.5–0.7 s each, each shot punctuated by a snap zoom and a sound, telling an action through its details. The sound climax lands at the end of the burst, then the edit **returns to normal** (dialogue, long shots, no zoom). The reference analysis is in [references/snatch-breakdown.md](references/snatch-breakdown.md): read it before proposing a breakdown.

Hard rule: **the AI proposes, the user decides.** Never modify the user's files, timeline or media: produce previews alongside, under new names.

## Workflow

### 1. Analysis

```bash
# from the repository root
TMP=$(mktemp -d)   # working folder outside data/
.venv/Scripts/python -I .claude/skills/snatch-cut/scripts/analyze.py "<video>" "$TMP/analysis" --dense 0:6 --step 2
```

- **Contact sheets**: `overview_*.png` at 5 fps, `dense_*.png` frame by frame over the burst. **Look at them** (Read): that is where you see the approach, the action and the dead time in each shot.
- **`frames.tsv`**: the difference from the previous frame pinpoints the exact moment of an action (click, impact). A jump in luminance marks a light turning on, which cut detection sometimes reports as a cut.
- **`audio.tsv` and `spectrum.png`**: per-frame level and onsets. Find usable original sounds (clicks, handles), voices that are too quiet and buried breaths.
- **`transcript.txt`**: word by word, after loudness normalization. Without it, Whisper hallucinates text on a quiet voice.
- **The project's 4K rushes** (`data/projects/<id>/ressources`, `rushes`): if they exist for a shot, zooms will be much sharper from them.

### 2. Diagnosis and proposal (no render yet)

Present a shot-by-shot table:
- current duration and target duration;
- source frames `in` and `out`, with the action placed around the middle of the shot;
- the zoom (zoom frame, amount, anchor point);
- the sounds (original, Epidemic, our library) with their levels.

End with a list of **open questions**: lines cut or kept, original sound or sound effect, trailing black, whooshes. Wait for approval before rendering.

Guidelines:
- **Burst shots**: 15–20 frames at 30 fps, 26 at most for the first shot. Cut out the whole approach (the hand coming in) and the dead time.
- **The zoom**: +15 to +25 % over 3 frames, easing out, **on the action frame**, together with the sound. For an establishing first shot, a slow +8 % push over the whole shot.
- **Silence before the impact**: 3–8 frames of near-silence before the big sounds, especially before the final click. Never absolute digital silence: a very low room tone runs under the whole sequence.
- **The climax** on the last shot of the burst: click plus a low thud. The voice of the dialogue part can start 2–3 frames before its picture.
- **The dialogue part**: real time, no zoom, voice raised and compressed if it is weak.
- **A single punchy shot after the dialogue** (a click that cuts someone off) reuses the burst grammar: near-silence, then zoom and a dry sound.
- **The release** (sigh, look): long shot. When boosting a breath, boost **only its windows**, otherwise the room hiss comes up with it.

### 3. Sounds

User preferences:
- Our whooshes (`data/library/sfx/whoosh.wav`, `whoosh-2.wav`), not Epidemic's, which he finds too long.
- Low levels. No long sound on a short action.

Search Epidemic through the MCP (`SearchSoundEffects`, duration filter), then download as WAV into a dedicated folder (`$TMP/sfx`). Then find the **attack** of each sound (`silencedetect` or envelope) and align the attack with the picture, not the start of the file: that is the `sync` field of the breakdown. Include the preview links (`lqmp3Url`) in the proposal.

Sounds already used (Epidemic IDs):

| Use | Title | ID | Attack |
|---|---|---|---|
| Door handle | Doors, Hardware, Door, Open, Knob, Lock Mechanism | bf8d4a75-5557-465f-9315-85aec64a7cdd | rattle 0.1–0.9 s, latch 1.05 s |
| Light switch | Mechanical, Switch, Light Switch, On, Off | 2b2e2214-2f82-4614-a840-75eb7bff59b7 | 0.0 s (keep 0–0.5 s only) |
| Lamp | Mechanical, Switch, Light Switch, Turn On, Off, Apartment 02 | ccc6c7f4-bf41-451a-a49e-7ac716284623 | 0.195 s |
| Mouse click | Computers, Keyboard & Mouse, Mouse, Apple, Mighty Mouse, Click | 78e23a2d-c645-491d-b826-c5ca15d1efdd | 0.0 s |
| Low thud | Designed, Impact, Cinematic Hit, Impact, Thud, Thin, Reverb | 866b9c73-3ad6-4a2e-93f8-27c118b9e462 | 0.0 s (cut at 0.8 s) |
| Night room tone | Ambience, Room Tone, Big House, Interior, Room, Very Quiet… Night | 58b13873-07ae-4c23-b4b0-da455d8e39fe | 308 s file: extract only 15 s |
| Sigh (fallback) | Voices, Male, Sigh, Tired | 026d325c-9ac9-40db-973b-3667105f8e12 | — |

Starting levels in the breakdown, before master gain:

| Sound | Level |
|---|---|
| Sound effects (door, switch, lamp, mouse) | −9 to −14 dB |
| Low thud | −17 dB |
| Whoosh | −24 dB |
| Room tone | −28 dB |
| Weak voice (≈ −42 dB mean) | +10 dB and a compressor |

### 4. Preview render

Write the breakdown as JSON in `$TMP`. The format is documented at the top of `scripts/render.py`. A complete example, validated on the "anonymat" pre-intro, is in [references/example-spec.json](references/example-spec.json); its paths are relative to the JSON file's folder. Times are given per shot, `{"shot": i, "frame": k}`, so nothing has to be recomputed when a duration changes. Then run:

```bash
.venv/Scripts/python -I .claude/skills/snatch-cut/scripts/render.py "$TMP/spec.json"
```

- It takes about 20–30 s for 15 s of video. If it runs longer than a minute, something is broken: do not wait.
- The render comes out at −16 LUFS with a −1.5 dB peak (master gain 16 dB, limiter at 0.79). Adjust `master_gain_db` if the printed measurement drifts.
- Check the result before announcing it: a contact sheet of the rendered MP4, and the level at the key moments (no −180 dB silence in the middle).
- Copy the render to `data/projects/<id>/rendu/<name>-snatch-vN.mp4`, under a new name, never overwriting.

### 5. After approval

Only once the user has approved it by ear: copy the selected Epidemic sounds into `data/projects/<id>/assets/sfx/`. Integrating it into the edit is up to the user.

## ffmpeg pitfalls (costly in time)

- **`-nostdin` everywhere**: run in the background without it, ffmpeg waits for keyboard input and hangs forever.
- **A single `zoompan` in a large graph with `trim` never ends**, and `[0:v]` reused without `split` duplicates the first shot. Hence the shot-by-shot render with `-frames:v`, then concatenation. Always bound the output with `-t`.
- **`alimiter` raises the level up to 0 dB by default**: always set `level=0`.
- **`drawtext`**: the font is copied locally (`font.ttf`), because the `:` in `C:/Windows/...` breaks the filter syntax.
- **Python on Windows does not see `/tmp`**: pass relative paths, or the ones returned by `mktemp -d`.
- **An MP4 with "moov atom not found"** was copied while the export was still writing it. Re-import it once the export has finished.
