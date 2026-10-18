# Cutroom

**An AI video editor for short-form creators.** Drop in clips, photos, a voice memo and a track, describe the video
in plain words, and Cutroom plans and renders a finished 9:16 Reel / TikTok: talking cut tight, B-roll matched to
what you say, cuts on the beat, captions, labels, colour grade and loudness done.

The editing decisions (which take to keep, which shot shows which line, where labels go) are made by Claude, run
through **your logged-in Claude Code, headless: no API key needed**. Everything mechanical (transcription, silence
cutting, beat detection, framing, rendering) is a deterministic Python pipeline.

> Status: **Phase 1 — engine + backend API.** The React app (Phase 2) comes next.

![Cutroom app screenshot placeholder](docs/screenshots/app-placeholder.png)
<!-- screenshot: project view with the timeline (Phase 2) -->

---

## How it works

```mermaid
flowchart LR
    subgraph clients[" "]
        UI["React app<br/>(Phase 2)"]
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
scripts/ve serve                  # http://127.0.0.1:8000  ·  API docs: http://127.0.0.1:8000/docs
```

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
| `GET/PUT /projects/{id}/timeline` | the plan, resolved to output times; save your own edits |
| `GET /jobs/{id}`, `WS /ws/jobs/{id}` | status, step, % done, log lines, result |
| `POST /jobs/{id}/retry` | run a failed, cancelled or interrupted job again with the same inputs |

Job records are saved in each project's `work/jobs.json`, so they survive a server restart. A job that was queued
or running when the server stopped comes back as `interrupted`, ready to retry.
| `GET /projects/{id}/outputs`, `…/outputs/{v}/video` | versions; video streams with HTTP Range |
| `GET /media/thumbnail?path=`, `GET /media/file?path=` | thumbnails; any workspace file, range-enabled |
| `GET /presets`, `PUT /presets/{name}`, `GET/PUT /settings`, `GET /system/status` | configuration |

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
app/               React frontend (Phase 2)
presets/           content-type presets (photo-dump, gym-vlog, …): notes + settings
brand.md           the creator's look; its settings block is what GET/PUT /settings edits
assets/            fonts, SFX
tests/             pytest: brief parsing, timeline schema, brain (mocked), API, end-to-end render
workspace/         projects (git-ignored)
```

Paths to shared resources can be moved with `CUTROOM_ROOT`, `CUTROOM_WORKSPACE`, `CUTROOM_PRESETS`,
`CUTROOM_BRAND`, `CUTROOM_FONTS`, `CUTROOM_SFX`, `CUTROOM_MODELS` and `CUTROOM_CLAUDE_BIN`.

## Development

```bash
.venv/bin/python -m pytest        # 57 tests, ~20 s; never calls Claude (the brain is mocked)
.venv/bin/ruff check .
```

The end-to-end test generates tiny clips, a photo and a 120 BPM track, then plans, edits, renders, revises and
renders again through the API.

## Screenshots

| | |
|---|---|
| ![Brief and questions (placeholder)](docs/screenshots/brief-placeholder.png) | ![Timeline (placeholder)](docs/screenshots/timeline-placeholder.png) |
| *Brief + clarifying questions* | *Timeline with the reason for every cut* |
| ![Render progress (placeholder)](docs/screenshots/render-placeholder.png) | ![Contact sheet (placeholder)](docs/screenshots/contact-placeholder.png) |
| *Live render progress* | *Contact sheet review* |

## Roadmap

- **Phase 2:** React app: upload, brief form with the brain's questions, timeline editor, player, version compare.
- Packaged desktop build; multi-user workspaces.
