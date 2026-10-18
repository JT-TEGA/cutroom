# My creator style

My default look for every video. Order of priority: this file < the content-type preset
(`presets/<type>.md`) < the brief. Anything a brief leaves blank falls back to the preset, then here.

## Look
- Clean, modern, minimal text. Let the footage do the work.
- Captions only when I'm talking: white, clean sans-serif (Inter), soft shadow, sentence case,
  the word being said is bright and the rest of the line slightly faded. Lower-middle of frame.
- Titles and labels: same clean sans, small and tidy. No thick outlines, no clutter.
- One emphasis colour (soft yellow) for a key word: write it as *word* in any text.

## End card
- My handle **tegathefn** for 1.5 seconds, over a blurred last frame.
- Optional: off by default for dumps and vlogs (the presets decide), and any brief can switch it on or off.

## Pacing
- No dead air. Cut silences, filler words (um, uh, erm...) and false starts when I talk.

## Voiceover
- Recorded separately into `voiceover/` (voice memo .m4a / .wav / .mp3). Cleaned so it sounds like a proper mic:
  noise reduction, de-ess, light compression, normalised.
- B-roll matches what I'm saying (when I say "chest day", show the chest clip). Captions on. Music ducks under it.

## Export
- 1080x1920, 30fps, H.264/AAC MP4, loudness -14 LUFS (Reels/TikTok standard)

## Settings
The pipeline reads the block below. Presets and briefs can override any of these.
Colours are hex. Positions are 0 = top of frame, 1 = bottom.

```settings
# who I am
handle: @tegathefn

# captions (only ever shown on talking parts)
captions: talking
caption_font: Inter
caption_weight: 700
caption_size: 64
caption_case: as-is
caption_color: #FFFFFF
caption_highlight_color: #FFFFFF
caption_inactive_opacity: 0.6
caption_outline_color: #000000
caption_outline_px: 0
caption_max_words: 4
caption_max_chars: 24
caption_position: 0.70
caption_animation: pop

# titles, labels, stickers, cards
title_font: Inter
title_weight: 800
title_color: #FFFFFF
title_outline_color: #000000
title_outline_px: 0
label_font: Inter
accent_color: #FFFFFF
emphasis_color: #FFD54A
accent_text_color: #111111
text_style: sticker

# look
grade: none
grain: 0
vignette: false
handheld: 0
kenburns: 0.06
photo_fit: auto
transition: cut

# pacing / auto-cut (talking)
max_pause: 0.30
cut_pad_in: 0.07
cut_pad_out: 0.12
fillers: um, umm, uh, uhh, erm, er, ah, hmm, mm, mhm

# pacing (no-talk footage and photos)
shot_min: 0.6
shot_max: 1.8
beat_every: 0

# voice clean-up (voiceover/ recordings; "all" also cleans to-camera audio)
voice_clean: voiceover
voice_denoise_db: 15
voice_deess: 0.4
voice_comp_ratio: 2.5
voice_highpass: 80

# B-roll under a voiceover (seconds per shot)
vo_shot_min: 1.0
vo_shot_max: 2.5

# transcription
language: en
whisper_model: large-v3-turbo
vocab:

# end card
end_card: true
end_card_seconds: 1.5
end_card_text:
end_card_logo:
end_card_background: blur

# audio
music_mode: bed
music_under_voice_db: -14
music_alone_lufs: -14
duck: true
duck_db: 8
ambient_share: 0
ambient_lufs: -20
ambient_duck_db: 7
loudness_lufs: -14
true_peak_db: -1.5

# export
width: 1080
height: 1920
fps: 30
video_crf: 18
audio_bitrate: 192k
```
