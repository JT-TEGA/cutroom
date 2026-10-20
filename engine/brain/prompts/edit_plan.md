# Edit plan format (the "timeline" object)

Times in `segments` are SOURCE seconds. Overlay times (`text`, `broll`, `sfx`) are OUTPUT seconds, or anchored to a
shot with `"on": "<label>"` / `"on": "#3"` (+ `"offset"`, `"dur"`), or to the moment a phrase is said with
`"cue": "<phrase>"` (`"nth": 2` for the second time). A voiceover block's `label` spans the whole block.

```jsonc
{
  "name": "...", "preset": "gym-vlog", "talk": "some",              // talk: yes | no | some | voiceover | mixed
  "target_length": 45,
  "style": {"grade": "warm"},                                         // brief overrides of preset / brand settings
  "beat_sync": {"every": 2},                                          // shots without out/dur follow the beat
  "segments": [
    {"src": "inputs/clips/a.mp4", "in": 1.2, "out": 3.3, "label": "hook", "talk": true, "text": "what is said",
     "reason": "best take of the opening line"},
    {"src": "inputs/clips/b.mp4", "in": 4.0, "beats": 2, "ambient": true},       // 2 beats long, keeps its real sound
    {"src": "inputs/clips/c.mp4", "in": 0.5, "beats": 4, "ramp": "fast-slow", "transition": "flash"},
    {"type": "image", "src": "inputs/clips/shoot/IMG_1.HEIC", "kb": "in"},       // photo: kb in|out|left|right|up|down|none
    {"src": "inputs/clips/d.mp4", "in": 2.0, "to": "drop"},                      // lasts until the next music drop
    {"type": "compare", "a": {"src": "inputs/clips/week1.jpg"}, "b": {"src": "inputs/clips/week12.mp4", "in": 1.0},
     "mode": "swipe", "labels": ["Week 1", "Week 12"], "beats": 8, "on_drop": true, "label": "reveal"},
    {"type": "color", "color": "#000000", "dur": 0.8},
    {"type": "vo", "src": "inputs/voiceover/vo.m4a", "label": "session",        // voiceover block: its words set the length
     "keep": [{"in": 0.99, "out": 2.56, "text": "so today is chest day."},      // VO source ranges kept
              {"in": 3.29, "out": 7.16, "text": "we start with incline bench, four sets of ten."}],
     "shots": [                                                                  // B-roll over it, muted unless "ambient"
       {"src": "inputs/clips/chest.mp4", "in": 3.1, "cue": "chest day"},        // first shot opens the block
       {"src": "inputs/clips/incline.mp4", "in": 2.8, "cue": "incline"},        // cuts in as "incline" is said
       {"src": "inputs/clips/rack.mp4", "in": 0.5, "ambient": true},            // no anchor: shares the time evenly
       {"type": "image", "src": "inputs/clips/plate.jpg", "at": 4.2}]}          // or seconds into the block
  ],
  "text": [
    {"text": "Lekki, 7PM", "style": "sticker", "on": "#2"},
    {"text": "6:30AM", "sub": "call time", "style": "timestamp", "on": "hook"},
    {"text": "Bulgarian split squat", "sub": "3 × 10", "style": "lower3", "on": "#1"},
    {"text": "Eat *2g* protein per kg", "style": "card", "on": "#4"},           // "fill": true = full-screen card
    {"style": "macros", "text": "This bowl", "items": ["Protein 40g", "Carbs 55g", "Fat 12g"], "on": "#5"},
    {"style": "credits", "lines": ["Photographer — @name", "Stylist — @name"], "on": "last"},
    {"text": "Incline bench", "sub": "4 × 10", "style": "lower3", "cue": "four sets", "dur": 2}
  ],
  "music": {"src": "inputs/music/track.mp3", "start": "drop"},       // start: seconds | auto | drop | drop-16
  "broll": [{"src": "inputs/clips/shake.mp4", "in": 1.0, "cue": "protein shake", "dur": 2}],  // cutaway over to-camera talk
  "sfx": [{"src": "assets/sfx/whoosh.wav", "on": "#3", "offset": -0.15, "gain_db": -6}],      // a sound FILE (see below)
  "captions": {"enabled": true, "replace": {"6 .30": "6:30"}},
  "end_card": {"enabled": false},
  "notes": ["Dropped take 1: stumbled"]
}
```

- Text styles: sticker, timestamp, lower3, card, macros, credits, label, title, big, title-minimal, title-serif,
  lower, caption. Options: x, y (0-1), size, color, bg, icon (pin|clock|none), italic, upper,
  anim (pop|slide|slide-left|fade|type|none). `*word*` = the emphasis colour.
- Transitions (into a shot): cut, flash, whip, zoom. Ramps: fast-slow, slow-fast, in, out, slow-normal-slow,
  normal-slow-normal. Zoom: a number >= 1 or keyframes [[t, z], [t, z, "cut"]].
- Grades: none, warm, clean-editorial, punchy, film.
- Sound: talking shots are the voice (music ducks under it); `"ambient": true` keeps a clip's real sound; anything
  else is muted under the music. Slow-mo is muted.
- Sound effects: every `sfx` item needs `"src"`, a real file: one from the "Sound effects" list in the request
  (assets/sfx/...) or an uploaded audio file. There is no other way to name a sound (no `"type"`, no made-up file
  names). If nothing in the list fits what the brief asks for, pick the closest one or leave it out, and say which in
  `notes`.
- A segment without `out`, `dur` or `beats` follows the beat grid when there is music.
