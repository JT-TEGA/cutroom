# Task: apply the creator's notes to the edit plan

You get the current edit plan, the creator's notes (plain language, maybe messy), and context: the brief, the
clips, transcripts and the current timeline view (what plays when). Change only what the notes ask for and keep
everything else identical (same segments, text and timings), so unchanged shots stay cached and nothing the creator
liked moves.

- If a note is ambiguous, take the most reasonable reading and say which one in `changes`.
- If a note can't be done (it asks for footage that wasn't uploaded, or a slow-mo on a 30 fps clip), leave the plan
  as it is for that note and explain in `changes`.
- Add a line to the plan's `notes` for each judgement call you make.

Return `{"timeline": <the full updated plan>, "summary": "<1-2 sentences>", "changes": ["one line per note: what
you did"]}`.
