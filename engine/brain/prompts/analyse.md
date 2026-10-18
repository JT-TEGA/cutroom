# Task: check the brief before editing

Decide whether anything critical is missing or unclear: the kind of gap that would make the edit wrong, not just
less polished. Ask about those (blocking = true). For everything else, decide and list the assumption you'll use.

Critical, ask:
- content type missing or unknown (offer the preset names as options)
- no clips or photos uploaded
- a beat-cut preset (photo-dump, shoot-slideshow, shoot-mashup, transformation) with no music track
- REFERENCE mode without a reference reel URL
- talking is voiceover / mixed but it's unclear which voiceover file to use
- several takes of the same thing and the brief doesn't say which one (only if the input shows it)
- a visual cue that can't be matched to an uploaded clip
- files the brief names that were not uploaded

Not critical, don't ask (add an assumption instead): no hook, no script, no colour grade, no target length,
no caption preference, no text on screen, no call to action.

The automatic checker's GAPS are listed in the input: turn each real gap into one plain-language question (the
creator is not technical; no file paths unless they help them choose). Merge related gaps. Don't ask again about
anything in "Previous answers". Ask everything now, in one go: at most 6 questions, most important first. Give
`options` when it is a choice (file names, preset names, on/off). Set `field` to the brief field the answer fills
(content_type, talking, track, voiceover_file, reference_url, target_length, colour_grade, captions, end_card...).
Use short stable ids like "music-track".

`ready` is true when there is no blocking question.
