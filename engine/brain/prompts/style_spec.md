# Task: describe a reference reel's style so the edit can copy it

You get measured stats (shot count, average and median shot length, cuts per 10 s, cuts on the beat, speech ratio,
BPM...), the transcript, and two contact sheets: `hook.jpg` (the first 2.5 s, 6 frames) and `shots.jpg` (one frame
per shot). Open both with the Read tool before writing.

Describe, concretely ("0.6 s average shot, every cut on a beat", not "fast"):
hook, pacing, whether cuts land on the beat, framing, caption look (weight, case, position, colour), on-screen
text, effects and transitions, music, colour grade, ending.

Then translate it into `style_overrides`, using only these setting keys (omit anything you're unsure of):
beat_every (0, 1, 2, 4 or "auto"), shot_min, shot_max (seconds), transition (cut|flash|whip|zoom),
transition_location, grade (none|warm|clean-editorial|punchy|film), grain (0-0.3), vignette (true|false),
handheld (0-1), kenburns (0-0.15), text_style (sticker|timestamp|lower3|card|label|title-minimal|title-serif|big),
caption_case (as-is|upper|lower|sentence), caption_position (0.08-0.8), caption_max_words (1-8),
caption_weight (400-900), caption_animation (pop|fade|none), music_mode (bed|lead|mix), end_card (true|false).
