# Task: build the edit plan

You get the brief, the content-type preset, brand basics, the clips (metadata), transcripts of what is said, and a
DRAFT plan the software already made: silences and um/uh cut, best silent moments picked, beat sync applied, B-roll
laid over the voiceover by cue and file name. Review it like an editor reviewing an assistant's rough cut and return
the final plan.

- Talking clips: match the script (if any) to the transcript. Keep the best take of each line; drop false starts,
  repeats and stumbles. Segments are source ranges: trim or split them using the transcript times, never inside a
  word. Keep a talking segment's "text" equal to what is said in it.
- Voiceover blocks: check each B-roll shot shows what is being said while it is on screen (the draft match-up shows
  the words heard over each shot). Move or add `cue`s so shots cut on the right words; B-roll shots last at least
  1 s. If a clip-to-phrase match-up from the contact sheets is given, follow it.
- Follow the preset's Structure (hook first, blocks in order, reveal on the drop...). The first 1-2 s must be the
  strongest moment; label that segment "hook".
- Turn the brief's "Labels & stickers" and "Text on screen" into `text` items in the preset's text style (sticker /
  timestamp / lower3 / card / macros / credits / label / title-minimal...). Anchor them with `"on"` (a segment label
  or "#n", counting shots as listed in the draft view, where each B-roll shot in a voiceover block is one) so they
  move with their shot, or `"cue"` to appear when a phrase is said.
- Keep `style`, `beat_sync` and `music` from the draft unless the brief says otherwise; they already hold the brief's
  overrides.
- Fix misheard caption words in `captions.replace`.
- Give every judgement call a short reason: in the segment's `reason`, and a line in `notes` for anything you
  removed or reordered ("Dropped take 1 of the intro: stumbled on 'Saturday'").
- Keep the total near the target length (talking sets its own length; the draft is already close).
- Use the draft's vocabulary only: segment types clip / image / compare / color / vo, files from the input.

Return `{"timeline": <the full edit plan>, "summary": "<2-3 sentences for the creator about the edit>",
"changes": ["what you changed from the draft and why", ...]}`.
