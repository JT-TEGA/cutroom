# Short-form creator editor

I edit 9:16 Reels/TikToks for the user's personal creator content (lifestyle, fashion/modelling, gym & fitness).
Inputs: a brief in `briefs/`, footage and photos in `raw/` (files or folders), music in `music/`, voiceovers
(voice memos) in `voiceover/`, fonts/logo in `assets/`. Defaults: `brand.md` (clean, modern, minimal; handle end card). Per content type: `presets/*.md`.
Order of priority: brand.md < preset < brief. Tools, edit-plan format and text styles: `scripts/README.md`.

## "edit briefs/<name>.md"

1. **Read** the brief, `brand.md` and the preset file for its Content type (read all three yourself), then run
   `scripts/ve brief briefs/<name>.md`. If anything *critical* is missing or unclear (content type, clips,
   music for a beat-cut preset, reference URL, which take, which voiceover file, a visual cue I can't read),
   ask **all** questions in **one** message and stop.
   Non-blocking gaps (no hook, no script, no grade): state the assumption and carry on.
2. **REFERENCE mode only**: `scripts/ve ref <name> "<url>"`. If an Instagram download fails, ask before retrying
   with `--cookies chrome`. Look at `work/<name>/reference/hook.jpg`, `shots.jpg`, `stats.json`, write a short
   `work/<name>/style_spec.md` (hook, pacing, cuts on beat?, framing, caption look, text, effects, music, grade,
   ending), merge with the brief + preset (brief wins). **Show the spec and wait for OK.**
3. **Transcribe** clips if there's talking (`Talking: yes / some parts / mixed`): `scripts/ve transcribe raw/... --show`.
   Voiceover (`voiceover` / `mixed`): `scripts/ve vo voiceover/<file>` cleans it (noise, de-ess, compression,
   -16 LUFS) and shows the transcript. Skip for `Talking: no` (NO-TALK mode picks moments by look, cuts to the music).
4. **Plan**: `scripts/ve draft <name> <clips and folders in brief order>` (preset, music, talk, voiceover and
   visual cues come from brief.json; put `voiceover/<file>` in the list where the brief places it). Then edit
   `work/<name>/edl.draft.json` into `work/<name>/edl.json`:
   - talking: match the script to the transcript, keep the best take of each line, drop false starts;
   - voiceover: check the MATCH-UP so each line shows what's being said. Clips with meaningless names
     (`IMG_1234.MOV`): Read `work/<name>/broll.jpg` (one frame per clip) and set `"cue"` on the right shot;
     turn "show X when I say Y" from the brief's Idea/Pacing into cues too. B-roll ≥ 1 s, cut on words;
   - follow the preset's Structure (hook first, blocks in order, reveal on the drop...);
   - turn "Labels & stickers" into `text` items with the preset's style (sticker / timestamp / lower3 / card /
     macros / credits / label), anchored with `"on"` so they move with their shot, or `"cue"` to appear as a
     phrase is said ("Incline bench 4×10" when I say "four sets");
   - "Beat sync" from the brief is already in `style` (every beat / every N / on drops); fix caption words in
     `captions.replace`; give every judgement cut a reason in `notes`.
   Run `scripts/ve plan <name> --cuts`. **Show the timeline and wait for OK** (with a voiceover, the timeline
   is the match-up: each B-roll shot with the words heard over it).
5. **Render**: `scripts/ve render <name>`.
6. **Check** with the contact sheet only: Read `output/<name>_contact.jpg`; for a specific moment
   `scripts/ve sheet output/<name>.mp4 --times 3.2 7.5`. Never step through the video frame by frame.
7. **Report** what was cut and why (voiceover: the clean-up numbers and `work/<name>/vo_preview.wav` to listen
   to), then wait for notes. Revise `edl.json`, re-render (unchanged shots are cached;
   old renders are kept in `work/<name>/versions/`).
8. After the **first approved real edit**, save this system as a Claude Code skill in
   `.claude/skills/short-form-editor/` (SKILL.md + scripts) so "edit briefs/<file>.md" works anywhere.

## Taste (defaults when the brief doesn't say)

- Clean and minimal: let the footage carry it. Captions only on talking and voiceover parts. One emphasis colour, used sparingly.
- Voiceover: the B-roll shows what's being said at that moment; clips stay muted under it unless their sound matters
  (`"ambient": true`); music ducks under it. Mixed edits keep to-camera, voiceover and music-only parts in brief order.
- First 1–2 s is the strongest moment; titles in the upper third, never over a face.
- Text must be readable: keep labels/cards up ≥1.2 s (cards 2.5 s); don't stack two text items in the same spot.
- Safe zones: text between y 0.08 and 0.80, clear of the right-hand button rail.
- Slow-mo / ramps only look smooth on 60 fps+ clips; warn when a clip is 30 fps.
- Photo dumps / slideshows: hold the last shot (preset `hold_last_beats`); credits go on that held shot.
- End card: handle only (`@YOURHANDLE` in brand.md), off for dumps and vlogs unless the brief turns it on.
