# Cutroom

**An AI video editor for short-form creators.** Drop in clips, photos, a voice memo and a track, describe the video
in plain words, and Cutroom plans and renders a finished 9:16 Reel / TikTok: talking cut tight, B-roll matched to
what you say, cuts on the beat, captions, labels, colour grade and loudness done.

The editing decisions (which take to keep, which shot shows which line, where labels go) are made by Claude, run
through **your logged-in Claude Code, headless: no API key needed**. Everything mechanical (transcription, silence
cutting, beat detection, framing, rendering) is a deterministic Python pipeline.

![The timeline review: every shot with the words heard over it, labels, voiceover and music lanes, and the reason for each cut](docs/screenshots/10-timeline.jpg)

```bash
./cutroom            # starts the API and the app, opens http://localhost:5173
./cutroom --demo     # the same with a scripted brain and a separate demo workspace: try it without using Claude
```

> Status: **Phase 2: the app.** Phase 1 built the engine and the API; Phase 2 adds the React app on top.

---

## How it works

```mermaid
flowchart LR
    subgraph clients[" "]
        UI["React app<br/><code>app/</code>"]
        CLI["scripts/ve<br/>command line"]
    end

    UI -- "REST + WebSocket" --> API["FastAPI server<br/><code>server/</code>"]
    API --> JOBS["Job queue<br/>1 render worker · brain pool"]
    JOBS --> PIPE["Editing workflow<br/><code>engine.pipeline</code>"]
    CLI --> ENGINE
    PIPE --> ENGINE["Pipeline<br/><code>engine/</code><br/>brief · transcribe · voice<br/>draft · beats · render"]
    PIPE --> BRAIN["Brain<br/><code>engine.brain</code>"]
    BRAIN -- "claude -p --output-format json" --> CC["Claude Code CLI<br/>(your subscription)"]
    BRAIN -. "optional" .-> APIK["Anthropic API<br/>(API key)"]
    ENGINE --> TOOLS["ffmpeg · OpenCV<br/>faster-whisper · librosa<br/>Puppeteer"]
    ENGINE --> WS[("workspace/&lt;project&gt;/<br/>project.json · inputs/<br/>work/ · output/v1, v2…")]
```

A **plan** job runs the same steps a human editor would, with software and the brain each doing their part:

| Step | Who | What |
|---|---|---|
| Check the brief | software + brain | Gaps (no music for a beat-cut preset, missing files…) become one round of plain-language questions |
| Transcribe | software | faster-whisper word timestamps, in a subprocess (it can't share a process with OpenCV) |
| Clean the voiceover | software | noise reduction, de-ess, compression, −16 LUFS; timing untouched |
| Match B-roll | brain | only when clip names say nothing (`IMG_1234.MOV`): it looks at a contact sheet of the clips |
| Draft | software | silences and um/uh cut, best moments of silent clips scored, cuts snapped to the beat |
| Plan | brain | reviews the draft like an editor: best takes, structure from the preset, labels, reasons for every call |
| Render | software | face-aware 9:16 framing, ramps, transitions, captions/text layer, grade, loudness-normalised mix |

### The brain (Claude Code, headless)

Every decision is a function that returns **JSON validated with Pydantic**:

```python
brain.brief.analyse(...)          # -> clarifying questions (or none)
brain.plan.build(...)             # -> the edit plan (timeline)
brain.match.clips(...)            # -> which clip shows which voiceover phrase, with reasons
brain.reference.style_spec(...)   # -> a reference reel's style, as settings
brain.revise.revise(...)          # -> the plan with your notes applied
```

`ClaudeCodeBrain` calls the `claude` CLI in print mode, in the project folder, prompt on stdin, with `--model sonnet`
to go easier on your subscription usage (`brain_model` in the app settings; empty = the CLI's default). Each call
is isolated: no user/project settings, hooks, plugins, MCP servers or `CLAUDE.md`; nothing saved; a low turn limit;
and the only tool, `Read`, is allowed for the project's `work/` folder (contact sheets) and denied for raw media. Any
`ANTHROPIC_API_KEY` is stripped from its environment so calls stay on your Claude subscription. Replies are parsed,
validated (schema + "do these files exist, is this phrase actually said"), retried once with the errors, and logged
with their duration to the project's `work/jobs.log`. Failures come back as clear API errors: *Claude Code not
installed*, *not logged in*, *usage limit reached (resets …)*, *timed out*.

An `AnthropicAPIBrain` backend (API key in `.env`) sits behind the same interface for people without Claude Code.
It uses Claude Sonnet 5.5 (`claude-sonnet-5-5`) unless `anthropic_model` in the app settings says otherwise.

---

## Setup on a fresh Mac

1. **Homebrew, Python 3.10+, Node, ffmpeg**
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install python@3.12 node ffmpeg
   ```
2. **Claude Code**, logged in with your Claude account (this is the editing brain):
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude            # log in once, then exit
   ```
3. **Cutroom**
   ```bash
   git clone <this repo> cutroom && cd cutroom
   scripts/setup.sh  # venv + Python deps, npm (Puppeteer), fonts, face model, SFX kit; ends with a health check
   ```
   The Whisper model (~1.6 GB) downloads on the first transcription.

## Run

```bash
./cutroom                         # API on :8000 + app on :5173, opens the browser; Ctrl-C stops both
./cutroom --demo                  # scripted brain + .demo/ workspace (your projects and brand.md untouched)
./cutroom --no-open               # don't open the browser
```

`./cutroom` installs the app's npm packages on its first run. If port 8000 or 5173 is taken, it says so; pick
others with `CUTROOM_API_PORT` / `CUTROOM_APP_PORT`. The API alone: `scripts/ve serve` (docs at
http://127.0.0.1:8000/docs).

## The app

| | |
|---|---|
| ![Projects](docs/screenshots/01-projects.jpg) | ![New video: content type](docs/screenshots/02-new-video.jpg) |
| **Projects**: every video with its status (draft, planning, needs review, rendering, done), live progress, search and a filter by content type | **New video, step 1**: the content type, grouped Lifestyle / Fashion / Gym |
| ![Media](docs/screenshots/03-media.jpg) | ![The idea](docs/screenshots/04-idea.jpg) |
| **Step 2, media**: drop clips and photos, a voice memo and a track; drag to reorder, click a name to rename it | **Step 3, the idea**: the brief as a form that autosaves; the preset's defaults are the placeholders, advanced fields fold away |
| ![Review](docs/screenshots/05-review.jpg) | ![Claude reading the brief](docs/screenshots/06-claude-reading.jpg) |
| **Step 4, review**: checks and what happens next | **Claude reads the brief** (live over the job WebSocket) |
| ![Questions](docs/screenshots/07-questions.jpg) | ![Planning progress](docs/screenshots/08-plan-progress.jpg) |
| **Questions**: anything Claude needs, asked once, with suggested answers and the assumptions it will make | **Planning**: each stage of the pipeline, the progress bar and the log |
| ![Claude is planning](docs/screenshots/09-claude-planning.jpg) | ![A shot and its reason](docs/screenshots/11-timeline-shot.jpg) |
| **Claude is planning…** while the brain call runs | **Timeline review**: click a shot for the reason it's there, the words heard over it, its transition; swap or delete it |
| ![Editing a label](docs/screenshots/12-timeline-text.jpg) | ![Rendering](docs/screenshots/13-render.jpg) |
| **Labels**: edit the text and style; drag shots to reorder, drop a clip from Media onto a shot to swap it, ⌘Z to undo | **Rendering**: live progress per stage |
| ![Result](docs/screenshots/14-result.jpg) | ![Version 2](docs/screenshots/16-result-v2.jpg) |
| **Result**: the 9:16 player, Download, Open in Finder, request changes, the contact sheet | **Version 2** after “make the first label say 5AM and use flash cuts”: versions side by side |
| ![Settings](docs/screenshots/17-settings.jpg) | ![Brain settings](docs/screenshots/17b-settings-brain.jpg) |
| **Settings**: handle, colours, captions with a live preview in the real font, music levels, end card | **Brain**: Claude Code or the Anthropic API, with connection status and the system check |
| ![Presets](docs/screenshots/18-presets.jpg) | ![Usage limit](docs/screenshots/19-usage-limit.jpg) |
| **Presets**: each content type's notes and defaults, editable | **When Claude can't work** (usage limit, logged out, not installed, no API key) a banner says what to do |
| ![Claude revising](docs/screenshots/15-claude-revising.jpg) | ![Error screen](docs/screenshots/20-error-screen.jpg) |
| **Revising**: your notes go to Claude, then straight to a new render | **If a screen ever crashes**: a calm error screen inside the app with Go back / Reload and the technical details folded away |

The screenshots come from a real end-to-end run against `./cutroom --demo`: synthetic footage, a `say` voice memo
and a generated beat track went through the wizard, the pipeline (transcription, voice clean-up, beat detection,
rendering) and the scripted brain. See [Development](#development) to regenerate them.

## From the terminal

A whole edit from the terminal (`?wait=true` blocks until a job is done; without it you get a job to poll or
stream from `ws://127.0.0.1:8000/ws/jobs/<id>`):

```bash
API=http://127.0.0.1:8000
ID=$(curl -s -X POST $API/projects -H 'content-type: application/json' \
  -d '{"name": "Lekki night", "brief": {"content_type": "photo-dump", "talking": "no",
       "idea": "night out with friends", "labels": "Lekki, 7PM"}}' | jq -r .id)

curl -s -F files=@clip1.mov -F files=@clip2.mov -F files=@IMG_0042.HEIC $API/projects/$ID/files
curl -s -F kind=music -F files=@track.mp3 $API/projects/$ID/files

curl -s -X POST "$API/projects/$ID/analyse?wait=true" | jq .result.questions    # anything to answer?
curl -s -X POST "$API/projects/$ID/plan?wait=true"    | jq .result.shots        # the timeline
curl -s -X POST "$API/projects/$ID/render?wait=true"  | jq .result              # output/v1/
curl -s -X POST "$API/projects/$ID/revise?wait=true" -H 'content-type: application/json' \
  -d '{"notes": "open on the dancing clip, sticker should say 8PM", "render": true}'
```

`GET /system/status` checks ffmpeg, Node/Puppeteer, Python packages, the Whisper model, fonts and Claude Code
(installed + logged in).

### API overview

| | |
|---|---|
| `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}`, `POST /projects/import` | projects; import a `briefs/*.md` |
| `POST/GET/PATCH /projects/{id}/files`, `PATCH/DELETE /projects/{id}/files/{file}` | uploads (HEIC ok), order, rename, trims |
| `POST /projects/{id}/analyse` · `plan` · `render` · `revise` · `reference` | background jobs |
| `GET/PUT /projects/{id}/timeline` | the plan, resolved to output times (each shot knows its segment); save your own edits |
| `GET /projects/{id}/voiceover`, `POST /projects/{id}/reveal` | voice preview + clean-up numbers; show a render in Finder |
| `GET /jobs/{id}`, `WS /ws/jobs/{id}` | status, step, % done, log lines, result |
| `POST /jobs/{id}/retry` | run a failed, cancelled or interrupted job again with the same inputs |

Job records are saved in each project's `work/jobs.json`, so they survive a server restart. A job that was queued
or running when the server stopped comes back as `interrupted`, ready to retry.
| `GET /projects/{id}/outputs`, `…/outputs/{v}/video` | versions; video streams with HTTP Range (`?download=true` to save) |
| `GET /media/thumbnail?path=&t=`, `GET /media/file?path=` | thumbnails (at a time); any workspace file, range-enabled |
| `GET /presets`, `PUT /presets/{name}`, `GET/PUT /settings`, `GET /system/status`, `GET /fonts/{file}` | configuration |

## The command line still works

The original chat-driven workflow (Claude Code reading `CLAUDE.md`) runs on the same engine:

```bash
scripts/ve brief briefs/my-video.md      # parse + gaps
scripts/ve draft my-video raw/a.mp4 raw/shoot/
scripts/ve render my-video
scripts/ve import briefs/my-video.md     # turn a brief into an app project
scripts/ve doctor                        # health check
```

See [scripts/README.md](scripts/README.md) for every command and the edit-plan format.

## Project layout

```
engine/            the pipeline as a package
  brain/           Brain interface, Claude Code + API backends, task prompts (prompts/*.md)
  pipeline.py      the editing workflow for app projects
  project.py       projects in workspace/<id>/
  timeline.py      the edit plan as Pydantic models + resolved view
  config.py        configurable paths, per-job layout, progress reporting
  render.py …      framing, overlay, audio mix, export (carried over from the chat era)
server/            FastAPI app, routes, background job queue
app/               React app: Vite, TypeScript, Tailwind + shadcn/ui, TanStack Query (see app/README.md)
cutroom            one command: API + app + browser (--demo for the scripted brain)
presets/           content-type presets (photo-dump, gym-vlog, …): notes + settings
brand.md           the creator's look; its settings block is what GET/PUT /settings edits
assets/            fonts, SFX
scripts/           ve (the CLI), setup.sh, demo_media.py (synthetic footage for demos)
tests/             pytest: brief parsing, timeline schema, brain (mocked), API, end-to-end render
docs/screenshots/  the app, from the walkthrough below
workspace/         projects (git-ignored)
```

Paths to shared resources can be moved with `CUTROOM_ROOT`, `CUTROOM_WORKSPACE`, `CUTROOM_PRESETS`,
`CUTROOM_BRAND`, `CUTROOM_FONTS`, `CUTROOM_SFX`, `CUTROOM_MODELS` and `CUTROOM_CLAUDE_BIN`.

## Development

```bash
.venv/bin/python -m pytest        # 72 tests, ~20 s; never calls Claude (the brain is mocked)
.venv/bin/ruff check .
cd app && npm run lint            # the app's lint (also runs in npm run build); npm run gen:api regenerates its typed client
```

`npm run lint` includes `cutroom/effect-returns` (app/eslint-rules/), which fails on any `useEffect` that can return
something other than a cleanup function: async effects, one-line effects like `useEffect(() => el.scrollTo(...))`,
`return setTimeout(...)`. React calls whatever an effect returns when the screen unmounts, so those crash with
"destroy is not a function" (newer Chrome made `scrollTo()` return a Promise, which is how one slipped in).

The end-to-end test generates tiny clips, a photo and a 120 BPM track, then plans, edits, renders, revises and
renders again through the API.

The app is checked end to end in a real browser (headless Chrome via Puppeteer) against the demo brain:

```bash
.venv/bin/python scripts/demo_media.py             # synthetic clips, photos, a voice memo, a track -> .demo/media
./cutroom --demo --no-open &
node app/scripts/walkthrough.mjs                   # every screen, start to finish -> docs/screenshots/*.jpg
node app/scripts/check-interactions.mjs            # drag to reorder, swap from the bin, delete + undo, edit a label
```

Both leave every screen and come back (client-side, so screens really unmount), including mid-planning and
mid-render; the walkthrough then sweeps every route and the error screen (`--sweep-only` runs just that). Any page
error or console error fails the run. They use Puppeteer's Chrome; to test your own browser, point
`CUTROOM_CHROME` at it, e.g. `CUTROOM_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`.

`CUTROOM_DEMO_FAIL=usage_limit ./cutroom --demo` makes the demo brain fail like Claude Code at its usage limit
(`node app/scripts/walkthrough.mjs --usage-limit` takes that screenshot).

## Roadmap

- ~~Phase 1: engine + API~~ · ~~Phase 2: the React app~~
- Packaged desktop build; multi-user workspaces.
