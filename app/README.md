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
npm run lint         # rule tests + eslint (cutroom/effect-returns, react-hooks/rules-of-hooks)
npm run build        # lint, then tsc, then vite build
```

### Look

The light "Butter" theme lives in `src/index.css`: a small palette (`--bg`, `--surface`, `--surface-2`, `--ink`,
`--ink-soft`, `--ink-faint`, `--border`, `--accent`, `--accent-ink`, `--control`, `--control-ink`, `--success` and
the text-safe `--*-ink` status colours) with shadcn's names mapped onto it. Components use those tokens (`bg-surface`,
`text-ink-soft`, `bg-accent`, `shadow-soft`, `rounded-card`…), never their own hex values. Black pill = the main action
on a screen (`<Button>`), outline pill = the second one, yellow = whatever is active or selected (`variant="accent"`
for a yellow pill). Every text token passes WCAG AA (4.5:1) on `--bg`, `--surface` and `--surface-2`; `--success`,
`--warn` and `--info` are for dots and fills, their `-ink` versions for text. The video's own look (caption colours,
stickers in the monitor preview) comes from brand.md, not from the theme.

### Lint

`eslint-rules/effect-returns.js` is a small custom rule: an effect may return nothing or a cleanup function.
React calls whatever an effect returns when the component unmounts, so `useEffect(async () => ...)`,
`useEffect(() => el.scrollTo({ top: 0 }))` (a Promise in newer Chrome) or `return setTimeout(...)` crash with
"destroy is not a function". Its cases are in `eslint-rules/effect-returns.test.js`; both run in `npm run build`.

### Errors

Every screen sits under a React Router `errorElement` (`components/ErrorScreen.tsx`), so a crash shows an error
screen inside the app (Go back, Reload, technical details with a copy button) instead of React Router's default
page; an `AppErrorBoundary` catches anything outside the router. In dev, `/__crash` throws on purpose to show it.

## Layout

```
src/
  api/          schema.d.ts (generated), client.ts (typed openapi-fetch client, errors, uploads with progress,
                media URLs), queries.ts (TanStack Query hooks), jobs.ts (live job progress over the WebSocket)
  components/   app shell + sidebar, Claude banner, badges, thumbnails, video player, caption preview, shadcn/ui
  lib/          presets (groups, icons, defaults), status mapping, timeline edits, formatting
  pages/        Home, NewVideo, Settings, Presets, and project/: setup wizard, questions, job progress,
                timeline review (bin · monitor · inspector · track), result
scripts/        gen-api.mjs, walkthrough.mjs (end-to-end run with the demo brain + screenshots),
                check-interactions.mjs (drag and drop, undo, edits), browser.mjs (shared: launch, error capture,
                client-side navigation "hops")
eslint-rules/   effect-returns.js (+ its tests)
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
