# Cutroom: case study

How an AI video editor for short-form content was built: what made it hard, the decisions behind it, and two bugs
worth describing in detail. Code references point into this repo.

## The problem

I make 9:16 videos for Instagram and TikTok: lifestyle, fashion shoots, gym content. Editing one takes far longer than
filming it. Most of that time goes into a handful of judgement calls (which take, which shot shows which line, where
each cut lands), plus a lot of mechanical work around them: syncing to the beat, framing landscape footage for a
vertical screen, captions, levels.

The tools I tried either automate the whole thing (fast, but every video looks the same and you can't see why it made
a cut) or automate nothing. I wanted something in between:

- **The judgement calls go to an LLM**, which explains each one.
- **Everything that must be exact stays in deterministic code**: timing, framing, audio, rendering.
- **I review the plan before anything renders**, change what I disagree with by hand, and those changes inform the
  next plan.

That split is the core design decision, and most of the hard problems below sit on the boundary between the two halves.

## Architecture

```
React app (Vite, TS, TanStack Query)      scripts/ve (CLI, the original chat-driven workflow)
        │ REST + WebSocket                         │
FastAPI server ── job queue (1 render worker, brain pool; job records persisted, interrupted jobs retryable)
        │
engine.pipeline: brief check → transcribe → voice clean-up → B-roll match → draft → plan → (review) → render
        │                                         │
   engine.brain ── claude -p --output-format json (Claude Code, headless) | Anthropic API
   engine/*.py  ── FFmpeg · faster-whisper · librosa · OpenCV (YuNet faces) · Puppeteer (text layers)
```

- **The plan is data.** An edit is a JSON timeline (`engine/timeline.py`, Pydantic models): segments with source
  in/out points, voiceover blocks with B-roll shots cued to phrases, text anchored to shots by label, music, captions,
  end card. The brain writes it, the app edits it, the renderer reads it. `timeline.view()` lays it out into output
  times (beat grid, voiceover cues, end card), and that layout is what the review screen shows.
- **The brain is Claude Code run headless.** `engine/brain/claude_code.py` runs the `claude` CLI in print mode inside
  the project folder, on the user's existing subscription: no API key, nothing saved (`--no-session-persistence`), no
  user or project settings, hooks, plugins or `CLAUDE.md` (`--setting-sources ""`), no MCP servers, and
  `--permission-mode dontAsk`. `Read` is the only tool, allowed for `work/**` (contact sheets) and denied for raw
  inputs and outputs. Any `ANTHROPIC_API_KEY` in the environment is stripped, so a call can't silently bill an API
  account.
- **The pipeline is plain Python around CLI tools.** It predates the app: Cutroom began as a set of scripts I drove from
  a Claude Code chat (`scripts/ve`, `CLAUDE.md`), and was refactored into an importable package so the server could
  call it. The command line still works on the same engine.

## Hard problems

### 1. Structured, validated edit plans, with retry

An LLM returning JSON is easy. An LLM returning a plan that **will actually render** is not: it can name a file that
was never uploaded, cue a shot to a phrase nobody says, or anchor a label to a shot that doesn't exist.

Every brain function goes through one call, `ask()` (`engine/brain/base.py`):

1. The schema (generated from the Pydantic model) is appended to the system prompt.
2. The reply is parsed tolerantly (`extract_json`: the whole reply, a fenced block, or the first `{…}` that decodes),
   because models wrap JSON in prose.
3. It is validated against the schema, then by a task-specific `check` that inspects the real project. For a plan,
   `file_check` rejects any file that isn't an upload or a shared asset, then runs `timeline.check()`: the same
   validation the renderer uses, plus a full layout that resolves every anchor and cue.
4. If anything fails, the call is retried **once**, with the specific problems and the previous answer in the prompt.
   A second failure is a clear `invalid_output` API error, not a broken render later.

Each attempt is logged with its duration and outcome in the project's `work/jobs.log`. The clip matcher's `check`
verifies every phrase it returns with `find_phrase` against the voiceover transcript, so "the phrase must actually be
said" is enforced in code, not left to the prompt.

The same validator also guards the human. Saving the timeline from the review screen (`PUT /projects/{id}/timeline`)
runs `timeline.check()` and returns 422 on problems. The app also compares the problems before and after each save,
and undoes any edit that introduces a new one, with the reason shown. That last check came from a real failure: a
"set length" control for B-roll under a voiceover only pushed the *next* shot, so the shot itself floated and dragged
its neighbour past the end of its clip. The end-to-end browser test caught it. The fix pins the shot's start and the
next shot's start, and the safety net catches any case like it that I haven't thought of.

### 2. Beat-accurate cutting

A cut feels "on the beat" within a frame or two, at 30 fps about 33 ms each. Off-the-shelf beat tracking isn't that
accurate on its own. `engine/beats.py` runs librosa's tracker (with a numpy fallback: spectral flux, autocorrelation
tempo with a prior around 110 BPM, dynamic-programming beat tracking) and then corrects it:

- **Wrong phase.** Trackers sometimes lock onto off-beat hi-hats. The low band (<150 Hz) onset energy is compared at
  the beats and half a period later; if the off-beats carry clearly more kick (1.3×), the whole grid shifts by half a
  beat.
- **Late grid.** Onset envelopes peak a frame or two after the hit; the low end of a kick peaks 30–40 ms after its
  attack click. `_attack_offset` measures the median distance from each beat to the sharpest transient just before
  it and shifts the grid onto the attack (clamped to ±60 ms).
- **Missing beats.** Quiet intros and breaks lose beats; `_fill_gaps` keeps a regular grid through them.
- **Structure.** Downbeats are the 1-in-4 phase with the most kick energy; drops are downbeats where the energy after
  is more than 1.5× the energy before and loud in absolute terms.

The layout (`engine/edl.py`) then builds the edit on that grid in output time, rounding every shot to whole frames so
errors never accumulate. Shots can last a number of beats (or "auto": the multiple of the beat period that fits the
preset's shot length), land on the drop, or switch rate after it. Cuts from a clip's natural length snap to the
nearest beat only within 120 ms, and **never on talking shots**, so a word is never clipped to hit a beat.

One detail that came from posting: Instagram and TikTok let you start a song only at a whole second. When the creator
adds the song in the app instead of baking it in, the grid is rebuilt from that whole-second start so the cuts still
line up with what the platform plays.

### 3. Shake versus motion

For edits without talking, the software picks each clip's best moments by look (`engine/moments.py`). It samples at
10 fps on a 288 px-short-side greyscale stream from FFmpeg and scores sharpness (Laplacian variance relative to the
clip's median), exposure, activity, faces (YuNet at 2 fps) and shake.

The naïve shake measure, frame difference, can't tell a shaky camera from a moving subject: it rejects exactly the shots
you want, someone walking, dancing or training. So shake is measured on **camera** motion only:

- `_camera_motion` tracks up to 200 corners with Lucas–Kanade optical flow and fits a partial affine transform with
  RANSAC. The result counts as the camera only if the inliers are spread across the frame (standard deviation at
  least 18% of width and height) and make up at least 40% of the tracked points. A person moving through the frame
  produces a cluster of outliers, not a frame-wide consensus.
- Otherwise it falls back to whole-frame phase correlation, and only trusts it when the correlation peak is clear.
  Otherwise it reports no motion rather than guessing.
- **Shake is the high-frequency part** of that motion: the trajectory minus its 5-sample moving average. A smooth pan
  has large motion but little jitter, so it passes; handheld wobble doesn't. Frames over 4.5 px of jitter (at analysis
  size) are excluded unless the brief allows shake.

Moment windows are then chosen from those that contain no blurry, shaky or badly exposed frame at all, not just a good
average. Only when a clip has no clean window does it fall back to the best-scoring one, with a penalty.

### 4. Voiceover-to-B-roll matching

In voiceover edits ("I wake up at 5:30, the alarm goes off, pre-workout, then the gym…") each shot should appear as
its phrase is spoken. There are three parts:

- **Matching** (`engine/brain/match.py`). The brain gets the word-timed transcript and the clip list. When file names
  are meaningless (`IMG_1234.MOV`) it reads a contact sheet, one frame per clip, through its only tool, scoped to
  `work/`. It returns `{phrase, src, reason}` matches, each verified against the transcript before it's accepted.
- **Finding the phrase** (`find_phrase` in `engine/edl.py`). Transcripts aren't exact: "meal prep" comes out as
  "mealprep", "chest day" as "chess day". Matching concatenates normalised tokens to handle word splits, then falls
  back to a fuzzy comparison (0.84) for longer phrases. Each search starts after the previous shot's cue, so a
  repeated word cues the right occurrence.
- **Placing the shots** (`vo_shots`). A cued shot cuts in 80 ms before its word lands. Shots can be pinned by
  seconds (`at`) or by length. A cue that lands on top of the previous shot or past the end of the voiceover is
  dropped with a warning shown in the review screen, never silently. Shots between anchors share the time evenly,
  nudged onto word onsets. The review screen shows each shot with the words heard over it, which makes a wrong match
  obvious at a glance.

The voiceover itself is cleaned (noise reduction, de-essing, compression, −16 LUFS) without touching its timing,
because every cue depends on the word timestamps.

### 5. Learning from hand edits

When the creator approves a plan they've changed, Cutroom turns the difference between Claude's plan and the approved
one into general notes for that content type ("Shortens the intro shots to under 2 s", "Keeps text off the hook").
Notes seen in two or more videos go into the next plan's prompt. Priority is brief > learned notes > preset defaults;
a note on a topic the brief sets is paused for that project.

- **Diffing** (`engine/edit_diff.py`) matches segments by the file they show, then reports order changes (a longest
  increasing subsequence finds what stayed in place), swaps, deletions, timing, captions, transitions, text and the
  end card as rules with stable keys, so the same habit adds up across videos.
- **The counting rules were the hard part.** The first version replaced a video's contribution on every approval.
  That had two failure modes:
  - Re-approving after Claude had started following a note dropped that video's vote, and could switch an active note
    off.
  - Any version that counted "the plan already does this" would let a note confirm itself forever.

  The rules now are:
  - **What counts:** only a hand edit to Claude's plan is a sighting.
  - **What doesn't:** approving again changes nothing.
  - **What counts against:** an edit in the opposite direction (`opposes()`: shorter vs longer, end card off vs on,
    sticker added vs removed…) withdraws that video's own sighting, or counts against a note other videos taught.
  - **Undo:** reverting your own edit before approving again counts as an undo. That's detected against a snapshot of
    the last approved plan, which is discarded whenever Claude proposes a new plan, so Claude's own changes are never
    taken for the creator's.
- **Two diff bugs turned up once the app had trim controls:**
  - **Trims misread as hook changes.** Trimming the first shot to start near another shot from the same clip made the
    matcher pair it with the wrong shot and report a new opening shot. Same file in the same position now always
    means the same shot.
  - **Voiceover trims never counted.** A voiceover block's total length is fixed by the voiceover, so timing changes to
    B-roll inside it were invisible to a per-segment diff. Voiceover B-roll is now compared shot by shot, counting only
    the shots whose timing the creator pinned. Its neighbours, which just share out the remaining time, don't count.

## Two debugging stories

### Bug 1: "destroy is not a function", only in a newer Chrome

**Symptom.** Navigating between screens crashed the app in my everyday Chrome (155) with React's *destroy is not a
function*. The automated browser walkthrough, running Puppeteer's bundled Chrome 148, passed every time.

**Cause.** The app shell scrolled to the top on each route change with a one-line effect:

```tsx
useEffect(() => main.current?.scrollTo({ top: 0 }), [pathname])
```

The arrow function returns `scrollTo()`'s return value, and React treats whatever an effect returns as its cleanup.
In Chrome 148 `Element.scrollTo()` returns `undefined`, so nothing happened. In the newer Chrome it returns a
**Promise**, which React stored and then tried to call on the next route change (and immediately in development,
through StrictMode's remount). The code was always wrong; a browser change made it fail.

**Fix** (`cdd72eb`, `08e0df9`). The bug itself was a one-line change, a block body. The fixes worth keeping are the
ones that stop this class of bug:
- A **custom ESLint rule**, `app/eslint-rules/effect-returns.js`, with its own tests. It fails the build on async
  effects, on one-line effects that return a value, and on returning anything but a function. Two more effects had
  the same shape, harmless only because those calls happen to return `undefined` today; they were rewritten too.
- **Error boundaries** at the router and app level, so a crash shows a recoverable screen instead of a blank page.
- **The browser checks now leave and revisit every screen**, including mid-planning, mid-render and during the Claude
  call, so components really unmount. Any page or console error fails the run, and `CUTROOM_CHROME` points the checks
  at a real Chrome install instead of the bundled one.

### Bug 2: a sound effect that passed every check

**Symptom.** A real project rendered every shot, then died in the final audio mix with `KeyError: 'src'`.

**Cause.** The brief asked for a "generic flash/shutter click sound". The brain answered with a sound effect that had
no file, `{"type": "camera-flash", "on": "hook"}`. The plan format never said what a sound effect item is, or which
sounds exist, so the model invented a shape. That should have been caught three times over: by the brain's check, by
the timeline save, and by the pre-render check. All three used the same file test:

```python
resolve(src or "").exists()
```

An empty path resolves to the **project folder**, which exists. So a missing file passed as present everywhere, and
the first code that actually needed `item["src"]` was the audio mix at the very end.

**Fix** (`22d179d`):
- **Validation names the problem.** Any item without a `src` is reported by name ("sound effect 1 ('camera-flash' on
  'hook') has no sound file"), for sound effects, B-roll, graphics and segments. A malformed voiceover keep no longer
  raises inside the checker itself.
- **The render checks before any work**, so a bad plan fails in seconds with "This plan can't be rendered yet", not
  after rendering every shot.
- **The review screen still lays out the shots** when only an overlay is wrong, and lists the problem, so one bad
  sound effect doesn't hide the whole plan.
- **The brain is told what exists.** The plan format documents sound effects, and the available sounds in
  `assets/sfx/` are listed in the plan, revise and analyse prompts. A phantom effect now goes back to the model with
  that list and is fixed on the retry.
- **Regression tests replay the exact item** from the failed project through validation, render, the review screen, a
  manual save and the brain's retry.

The lesson I took from it: a check that can't fail isn't a check. `"" → project folder → exists` is the kind of edge
case that only shows up when you test the validator with the inputs that should fail it, not just the ones that
should pass.

## How it's tested

- **pytest, 142 tests.** The brain is mocked: tests never call Claude or read the Photos library. Media is generated
  per run (tiny clips, a photo, a 120 BPM track), and the end-to-end test plans, edits, renders, revises and renders
  again through the API with real FFmpeg.
- **Vitest + Testing Library, 41 tests**, against a fake API. Examples: the voiceover recorder with a mocked
  microphone, and the trimmer, where dragging a handle and typing the numbers must produce the same saved plan.
- **Puppeteer walkthrough.** It drives every screen of the real app against a scripted "demo brain", including a
  voiceover recorded through Chrome's fake microphone, and fails on any page or console error. The screenshots in the
  README come from that run.

## What I'd do next

- **Evaluate the brain, not just validate it.** Validation proves a plan is renderable, not that it's good. A small set
  of real projects with edits I approved would let me compare prompts and models on how much I end up changing, which
  the learn-from-edits diff already measures.
- **A screen for learned preferences.** They're stored, applied and exposed through the API, but the creator can only
  turn them off or delete them through the API today.
- **Faster renders.** Each shot is rendered as its own clip and cached, so re-rendering after a small change is quick,
  but a first render is still serial per shot. The shots are independent and could run in parallel.
- **Leaner screenshots.** Every refresh of the README screenshots adds about 10 MB of history; they should move to
  Git LFS or a separate branch.
- **Beyond macOS and one user.** Photos import is Mac-only (osxphotos), and the workspace is a local folder for one
  person. A packaged desktop build is the natural next step for other creators.
