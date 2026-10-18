# Pipeline scripts

Everything runs through `scripts/ve <command>` (it uses the project venv). Work files live in
`work/<name>/` where `<name>` is the brief's file name (`briefs/oct-dump.md` → `oct-dump`).
Transcripts, face tracks, moment scores, beat grids, converted photos and cleaned voiceovers are cached in
`work/_cache/`.

Settings resolve in layers: `brand.md` < `presets/<content type>.md` < the brief (stored as `"style"` in the edit plan).

| Command | What it does |
|---|---|
| `ve brief briefs/<name>.md` | parse brief, load its preset, list inputs (folders expanded), print GAPS; writes `work/<name>/brief.json` |
| `ve presets` | list content-type presets |
| `ve ref <name> <url> [--cookies chrome]` | REFERENCE mode: download (yt-dlp), cut detection, hook strip, shot sheet, transcript, BPM |
| `ve media <folder>` | a folder's photos/clips in capture order (EXIF / QuickTime dates) |
| `ve transcribe <clips or folders> [--show]` | faster-whisper word timestamps (`large-v3-turbo`, ~2.5× real time) |
| `ve vo voiceover/<file> [--force]` | clean a voiceover (noise reduction, de-ess, compression, -16 LUFS; cached) + transcript |
| `ve draft <name> <clips/folders...> [--preset --music --talk --vo --length]` | draft plan: talking clips cut (silences, um/uh), no-talk clips → best moments, photos → shots, voiceovers → cut + B-roll matched to what's said, preset pacing + beat sync. Also writes `vo_preview.wav` (the VO cleaned + cut) and `broll.jpg` (one frame per clip) |
| `ve moments <clip>` | NO-TALK scoring: best windows by sharpness / steadiness / exposure / action / faces |
| `ve beats <audio>` | BPM, beats, downbeats, drops (librosa; kick-aligned) |
| `ve plan <name> [--cuts]` | timeline preview of `work/<name>/edl.json`; `--cuts` = what was removed and why |
| `ve render <name> [--draft]` | export `output/<name>.mp4` + `output/<name>_contact.jpg` (old versions → `work/<name>/versions/`) |
| `ve sheet <video> [--times ...]` | contact sheet at chosen moments |
| `ve faces <clip> [--preview]` | check face tracking |
| `ve sfx` / `ve doctor` | starter SFX kit / check all tools |

## Presets (`presets/*.md`)

Each preset has notes for me (length, pacing, captions, text style, music, transitions, grade, structure)
and a ```settings block the scripts read. Keys a preset (or brief) can set include:
`target_length, talk_default, shot_min, shot_max, beat_every (0|1|2|4|auto), beat_every_after_drop,
hold_last_beats, one_per_clip, shake_ok, captions (talking|off), caption_*, title_font, title_case,
voice_clean (voiceover|all|off), voice_denoise_db, voice_deess, voice_comp_ratio, voice_highpass, vo_shot_min, vo_shot_max,
text_style, music_mode (bed|lead|mix), music_start (auto|drop|drop-16|seconds), music_under_voice_db,
ambient_share, ambient_lufs, transition, transition_location, transition_downbeat, transition_drop,
ramp_on_drop, compare_mode (swipe|split), grade, grain, vignette, handheld, kenburns, kb_moves,
photo_fit (auto|crop|blur), card_min_seconds, end_card, end_card_seconds`.

## Talking modes (`Talking in this video?` in the brief)

| talk | what happens |
|---|---|
| `yes` / `some` | to-camera clips: silences + fillers cut, captions, face-tracked crop, music ducks under the voice. `some`: clips without speech are B-roll |
| `no` | NO-TALK: moments by look, cut to the music |
| `voiceover` | a recording in `voiceover/` is cleaned, cut like talking, and every clip goes **under** it as B-roll (muted unless `"ambient": true`); captions on |
| `mixed` | to camera + voiceover + music-only parts. The VO sits where it's listed in the clip order (else before the first B-roll clip) and takes the clips listed after it as needed; the rest stay music-only |

Naming a voiceover with talk `no` means `voiceover`; with `yes`/`some` it means `mixed`. Captions turn on for
talking/voiceover parts unless the brief says `Captions: off` (even in presets that have them off for no-talk edits).

**Matching B-roll to the voiceover** (draft): 1. the brief's *Visual cues* (`when I say "meal prep" show
raw/meal.mp4`), 2. clips whose file/folder name is said ("squats" → `raw/squats.mp4`), 3. the rest in brief order,
reused when they run out. Shots last `vo_shot_min`–`vo_shot_max` s; cuts land just before a word. Cues said to
camera become B-roll cutaways over the talking. Unnamed clips (`IMG_1234.MOV`): look at `broll.jpg` and set `cue`s.

**Voice clean-up** (`voice.py`, timing untouched so transcripts stay valid): high-pass 80 Hz → FFT noise
reduction profiled on the quietest pause → gentle expander on pauses → EQ (−2 dB mud, +2 dB presence) →
2.5:1 compression → de-ess → −16 LUFS. On for voiceovers; `voice_clean: all` also cleans to-camera audio.

## Edit plan: `work/<name>/edl.json`

Times in `segments` are **source** seconds. Overlay times (`text`, `sfx`, `broll`, `flash`, `graphics`)
are **output** seconds, or anchor to a shot with `"on": "<label>"` / `"on": "#3"` (+ `"offset"`, `"dur"`), or to
the moment a phrase is said with `"cue": "<phrase>"` (to camera or voiceover; `"nth": 2` for the 2nd time).
`#n` counts shots as `ve plan` numbers them (each B-roll shot in a voiceover block is one). A voiceover block's
`label` spans the whole block. Cue matching copes with plurals, word splits ("meal prep"/"mealprep") and
near-misses in the transcript.

```jsonc
{
  "name": "oct-dump", "preset": "photo-dump", "talk": "no",          // talk: yes | no | some
  "style": {"grade": "warm", "beat_every": 1},                          // brief overrides of preset/brand
  "beat_sync": {"every": 2},                                            // shots without in/out or dur follow the beat
  "segments": [
    {"src": "raw/a.mp4", "in": 1.2, "out": 3.3, "label": "hook", "talk": true, "text": "what is said",
     "crop": "face", "fit": "crop", "zoom": [[0, 1.0], [0.6, 1.15, "cut"]], "speed": 1.0},
    {"src": "raw/b.mp4", "in": 4.0, "beats": 2, "ambient": true},       // 2 beats long, keeps its real sound
    {"src": "raw/c.mp4", "in": 0.5, "beats": 4, "ramp": "fast-slow", "transition": "flash"},
    {"type": "image", "src": "raw/shoot/IMG_1.HEIC", "kb": "in"},        // photo: kb in|out|left|right|up|down|none
    {"src": "raw/d.mp4", "in": 2.0, "to": "drop"},                     // lasts until the next music drop
    {"type": "compare", "a": {"src": "raw/week1.jpg"}, "b": {"src": "raw/week12.mp4", "in": 1.0},
     "mode": "swipe", "labels": ["Week 1", "Week 12"], "beats": 8, "on_drop": true, "label": "reveal"},
    {"type": "color", "color": "#000000", "dur": 0.8},
    {"type": "vo", "src": "voiceover/vo.m4a", "label": "session",       // voiceover block: its words set the length
     "keep": [{"in": 0.99, "out": 2.56, "text": "so today is chest day."},  // VO source ranges kept (fillers/silences cut)
              {"in": 3.29, "out": 7.16, "text": "we start with incline bench, four sets of ten."}],
     "shots": [                                                          // B-roll over it, muted unless "ambient": true
       {"src": "raw/chest.mp4", "in": 3.1, "cue": "chest day"},          // first shot opens the block
       {"src": "raw/incline.mp4", "in": 2.8, "cue": "incline"},          // cuts in as "incline" is said
       {"src": "raw/rack.mp4", "in": 0.5, "ambient": true},              // no anchor: shares the time evenly
       {"type": "image", "src": "raw/plate.jpg", "at": 4.2}]}            // or seconds into the block
  ],
  "text": [
    {"text": "Lekki, 7PM", "style": "sticker", "on": "#2"},
    {"text": "6:30AM", "sub": "call time", "style": "timestamp", "on": "hook"},
    {"text": "Bulgarian split squat", "sub": "3 × 10", "style": "lower3", "on": "#1"},
    {"text": "Eat *2g* protein per kg", "style": "card", "on": "#4"},     // "fill": true = full-screen card
    {"style": "macros", "text": "This bowl", "items": ["Protein 40g", "Carbs 55g", "Fat 12g"], "on": "#5"},
    {"style": "credits", "lines": ["Photographer — @name", "Stylist — @name"], "on": "last"},
    {"text": "Week 1", "style": "label", "x": 0.25},
    {"text": "Incline bench", "sub": "4 × 10", "style": "lower3", "cue": "four sets", "dur": 2}  // when it's said
  ],
  "music": {"src": "music/track.mp3", "start": "drop", "level_db": -14, "snap_cuts": true},
  "broll": [{"src": "raw/shake.mp4", "in": 1.0, "cue": "protein shake", "dur": 2}],   // cutaway over to-camera talking
  "graphics": [], "flash": [], "sfx": [], "sfx_on_cuts": null,
  "captions": {"enabled": true, "replace": {"6 .30": "6:30"}, "hide": []},
  "end_card": {"enabled": false},
  "notes": ["Dropped take 1: stumbled"]
}
```

**Text styles:** `sticker` (pill + pin/clock icon), `timestamp` (big time + sub line, top-left), `lower3`
(title + sub with accent bar), `card` (big bold key point; `fill` covers the frame and hides captions), `macros`
(value/label cards), `credits` (role / name stack over a dim), `label` (small pill, before/after, weeks), `title`,
`big`, `title-minimal`, `title-serif`, `lower`, `caption`. Options: `x`, `y` (0–1), `size`, `color`, `bg`,
`icon` (pin|clock|none), `italic`, `upper`, `anim` (pop|slide|slide-left|fade|type|none). `*word*` = emphasis colour.
Text stays up at least 1.2 s (cards/macros/credits 2.5 s) unless `dur`/`end` is given.

**Transitions** (into a shot): `cut`, `flash`, `whip`, `zoom`. **Ramps:** `fast-slow`, `slow-fast`, `in`
(slow-mo into normal), `out`, `slow-normal-slow`, `normal-slow-normal`, or `[[fraction, speed], ...]`.
Slow-mo uses real frames from 60/120 fps clips and blends frames when the clip doesn't have enough.
**Grades:** `none`, `warm`, `clean-editorial`, `punchy`, `film`, `custom:<ffmpeg filters>`, or a `.cube` LUT path.
**Music start:** seconds, `auto` (first downbeat), `drop` (the first drop lands where the `on_drop` shot starts),
`drop-16` (start 16 beats before the drop).

**Sound per shot** (`seg_role`): talking → voice (levelled to -16 LUFS, captions, music ducks under it);
`ambient: true` or music_mode `mix` → real sound at `ambient_lufs` (music dips under ambient snippets in
`lead` mode); otherwise muted under the music. Slow-mo / ramps are muted unless `"audio": true`.
**Voiceover** is its own bus: cleaned, pieces placed sample-exact, levelled to -16 LUFS, captioned, music ducks
under it; B-roll under it is muted, or with `"ambient": true` plays its real sound ducked under the voice.
Talking shots are never beat-snapped, speed-ramped on a drop or held as the last beat shot.

## How it renders

1. **Shots**: ffmpeg decodes the needed range at the needed frame rate (iPhone HDR → SDR via VideoToolbox,
   rotation handled), OpenCV frames each shot (face-aware 9:16 crop or blurred fill, Ken Burns, zoom, handheld
   drift, whip / zoom transitions, split / swipe compares), H.264 intermediates cached by content.
2. **Overlay**: `overlay/overlay.html` draws captions/text/cards/end card for any time `t`; Puppeteer
   screenshots only frames that change → transparent PNGs (one corner pixel stays transparent so every frame keeps alpha).
3. **Audio**: voice (to camera + voiceover bus) / ambient / music / SFX mixed in numpy, ducking from the
   transcript timing, two-pass loudnorm to -14 LUFS / -1.5 dBTP.
4. **Export**: B-roll → colour grade → grain/vignette → graphics → text layer (text stays clean) →
   H.264 High / AAC 48 kHz, 1080×1920, 30 fps, BT.709, then the contact sheet.

## HyperFrames (optional motion graphics)

`npx hyperframes init work/<name>/hf`, build at 1080×1920, `npx hyperframes render work/<name>/hf --format mov
-o work/<name>/hf/title.mov` (MOV keeps transparency), then add it under `"graphics"`.

## Gotchas

- Never import `cv2` and `faster_whisper` in one process (duplicate libav). Transcription always runs as a subprocess.
- Bump `VERSION` in `render.py` after changing shot rendering code (invalidates the shot cache).
- Instagram downloads usually need `--cookies chrome`; ask first, it reads the browser's login.
- `afftdn` (noise reduction) delays audio ~25 ms; `voice.py` measures the delay and trims it, so the cleaned file
  lines up with the transcript sample-for-sample.
- Overlays render with `headless: 'shell'` (chrome-headless-shell); the new headless mode can hang on screenshots.
