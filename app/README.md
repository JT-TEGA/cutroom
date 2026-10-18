# Cutroom app

The web app for Cutroom: React 19 + TypeScript + Vite, Tailwind CSS 4 + shadcn/ui, TanStack Query, Framer Motion,
dnd-kit. It talks to the FastAPI server in `server/` through `/api` (Vite proxies REST, media streams and the job
WebSocket), so it never needs to know the API's port.

Start everything from the repo root with `./cutroom` (API + this dev server + browser). To work on the app alone:

```bash
npm install
npm run dev          # http://localhost:5173, expects the API on :8000 (CUTROOM_API_PORT to change)
npm run gen:api      # regenerate src/api/schema.d.ts from the FastAPI OpenAPI schema (no server needed)
npm run typecheck
npm run build
```

## Layout

```
src/
  api/          schema.d.ts (generated), client.ts (typed openapi-fetch client, errors, uploads with progress,
                media URLs), queries.ts (TanStack Query hooks), jobs.ts (live job progress over the WebSocket)
  components/   app shell + sidebar, Claude banner, badges, thumbnails, video player, caption preview, shadcn/ui
  lib/          presets (groups, icons, defaults), status mapping, timeline edits, formatting
  pages/        Home, NewVideo, Settings, Presets, and project/: setup wizard, questions, job progress,
                timeline review (bin · monitor · inspector · track), result
scripts/        gen-api.mjs, walkthrough.mjs (end-to-end run with the demo brain + screenshots)
```

## The API client

`npm run gen:api` imports the FastAPI app in Python, dumps its OpenAPI schema and turns it into TypeScript types with
`openapi-typescript`; `openapi-fetch` uses them, so every path, parameter and body is checked at compile time. Errors
come back as `ApiError` (`code`, `message`, `hint`), which the UI shows as toasts, inline states or the Claude banner
(not installed / not logged in / usage limit / API key missing).

## Screenshots

`node app/scripts/walkthrough.mjs` drives the whole app in headless Chrome against a server started with
`./cutroom --demo` (scripted brain, separate `.demo/` workspace) and writes `docs/screenshots/*.png`. Generate the
synthetic demo footage first with `.venv/bin/python scripts/demo_media.py`.
