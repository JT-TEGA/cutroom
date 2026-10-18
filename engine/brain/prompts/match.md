# Task: match B-roll clips to what the voiceover says

You get the voiceover transcript with times, the clips with their file names and metadata, the brief's visual cues,
and contact sheet images in work/ (one tile per clip, its file name at the bottom of the tile). Decide which clip is
on screen for which phrase.

1. The brief's visual cues ("when I say X show Y") come first, as given.
2. Then clips whose file or folder name is said (squats.mp4 <-> "squats").
3. Only when names don't tell you what a clip shows (IMG_1234.MOV, VID_2026..., random names), open the contact
   sheet image(s) listed under "Contact sheets" with the Read tool and match on what the tiles show.

- `phrase` must appear in the transcript: copy 1-4 consecutive words exactly as transcribed, so software can find
  them. `said_at` is when the phrase starts (seconds, from the transcript).
- Use each clip at most once, unless there are fewer clips than things to show.
- Order matches by `said_at`. Leave a clip unmatched rather than forcing a bad match.
- `reason`: one short line ("tile shows a squat rack; the VO says 'squats' at 0:04").
