// End-to-end walkthrough of the app with the scripted demo brain, saving a screenshot of every screen.
//
//   ./cutroom --demo --no-open &            (or with CUTROOM_API_PORT / CUTROOM_APP_PORT)
//   .venv/bin/python scripts/demo_media.py  (synthetic clips, voice memo and track in .demo/media)
//   node app/scripts/walkthrough.mjs        (CUTROOM_URL=http://localhost:5173 by default)
//
// A few side projects are created through the API (so the projects grid has something in every state); the main
// one, "5AM chest day", goes through the UI: new video wizard -> questions -> plan -> timeline edits -> render ->
// result -> revise -> v2. Screenshots (2x JPEG) land in docs/screenshots/.
//
// Along the way it leaves every screen and comes back (client-side, so screens really unmount), including in the
// middle of planning and rendering, then sweeps every route; any page error or console error fails the run.
// CUTROOM_CHROME=/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome runs it in your own Chrome.
import { mkdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { assertNoErrorScreen, BASE, go, hop, launch, sleep, watchErrors } from "./browser.mjs"

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, "../..")
const MEDIA = path.join(repo, ".demo/media")
const OUT = path.join(repo, "docs/screenshots")
const PAGES_ONLY = process.argv.includes("--pages-only")    // just settings, presets and projects
const USAGE_LIMIT = process.argv.includes("--usage-limit")  // the server runs with CUTROOM_DEMO_FAIL=usage_limit
const SWEEP_ONLY = process.argv.includes("--sweep-only")    // just the every-route sweep + the error screen
const SKIP_SEED = PAGES_ONLY || SWEEP_ONLY || process.argv.includes("--no-seed")
mkdirSync(OUT, { recursive: true })

const log = (...a) => console.log("·", ...a)

// ---------------------------------------------------------------- API helpers (seeding)

async function api(p, opts = {}) {
  const r = await fetch(`${BASE}/api${p}`, {
    ...opts,
    headers: opts.body && !(opts.body instanceof FormData) ? { "content-type": "application/json" } : undefined,
  })
  const text = await r.text()
  const body = text ? JSON.parse(text) : null
  if (!r.ok) throw new Error(`${opts.method ?? "GET"} ${p}: ${r.status} ${text.slice(0, 300)}`)
  return body
}

async function upload(pid, files, kind) {
  const form = new FormData()
  for (const f of files) form.append("files", new Blob([readFileSync(f)]), path.basename(f))
  if (kind) form.append("kind", kind)
  return api(`/projects/${pid}/files`, { method: "POST", body: form })
}

async function run(pid, kind, body) {
  const job = await api(`/projects/${pid}/${kind}?wait=true`, { method: "POST", body: body ? JSON.stringify(body) : undefined })
  if (job.status !== "done") throw new Error(`${kind} for ${pid}: ${job.status} ${JSON.stringify(job.error)}`)
  return job
}

const m = (...p) => path.join(MEDIA, ...p)

async function seed() {
  const existing = await api("/projects")
  if (existing.length) return log(`workspace has ${existing.length} projects; not seeding`)

  log("seed: Studio shoot BTS (draft)")
  const bts = await api("/projects", { method: "POST", body: JSON.stringify({ name: "Studio shoot BTS", brief: { content_type: "fashion-bts", talking: "no" } }) })
  await upload(bts.id, ["set-lights.mp4", "makeup-chair.mp4", "first-look.mp4"].map((f) => m("bts", f)))

  log("seed: 12-week glow up (needs review)")
  const glow = await api("/projects", {
    method: "POST",
    body: JSON.stringify({ name: "12-week glow up", brief: { content_type: "transformation", talking: "no", labels: "Week 1, Week 6, Week 12" } }),
  })
  await upload(glow.id, ["week-1.jpg", "week-6.jpg", "week-12.jpg"].map((f) => m("glow-up", f)))
  await upload(glow.id, [m("afro-drill-120.wav")], "music")
  await run(glow.id, "plan")

  log("seed: Leg day routine (planned, then rendered)")
  const legs = await api("/projects", {
    method: "POST",
    body: JSON.stringify({
      name: "Leg day routine",
      brief: { content_type: "workout-routine", talking: "no", idea: "three moves, form first", labels: "Squats 4x8, Leg press 3x12, Walking lunges 3x20" },
    }),
  })
  await upload(legs.id, ["squats.mp4", "leg-press.mp4", "walking-lunges.mp4"].map((f) => m("legs", f)))
  await upload(legs.id, [m("afro-drill-120.wav")], "music")
  await run(legs.id, "plan")
  await run(legs.id, "render")

  log("seed: Lekki night out (rendered)")
  const night = await api("/projects", {
    method: "POST",
    body: JSON.stringify({ name: "Lekki night out", brief: { content_type: "photo-dump", talking: "no", idea: "friday night in Lekki", labels: "Lekki, 9PM" } }),
  })
  await upload(night.id, [1, 2, 3, 4, 5, 6].map((i) => m("night", `IMG_080${i}.jpg`)))
  await upload(night.id, [m("afro-drill-120.wav")], "music")
  await run(night.id, "plan")
  await run(night.id, "render")
  return { glow, legs, night, bts }
}

// ---------------------------------------------------------------- browser helpers

let page
let watch
const shot = async (name, settle = 700) => {
  await sleep(settle)
  await page.screenshot({ path: path.join(OUT, `${name}.jpg`), type: "jpeg", quality: 90 })
  log(`screenshot ${name}.jpg`)
}
const waitText = (text, timeout = 60_000) =>
  page.waitForFunction((t) => document.body.innerText.includes(t), { timeout, polling: 200 }, text)
const waitUrl = (re, timeout = 60_000) => page.waitForFunction((r) => new RegExp(r).test(location.pathname), { timeout, polling: 200 }, re.source)
// scroll targets to the middle first: near the bottom edge they sit under the sticky wizard footer.
// Navigations render in a transition (the old screen stays up a moment after the URL changes), so an element can be
// replaced between finding and clicking it: find it again and retry.
async function press(selector) {
  for (let attempt = 1; ; attempt++) {
    try {
      const h = await page.locator(selector).setTimeout(15_000).waitHandle()
      await h.evaluate((el) => el.scrollIntoView({ block: "center" }))
      await sleep(150)
      return await h.click()
    } catch (e) {
      if (attempt >= 4 || !/detached|not attached|Node is either not visible/i.test(String(e))) throw e
      await sleep(400)
    }
  }
}
const click = (text, tag = "button") => press(`${tag} ::-p-text(${text})`)
const idle = () => page.waitForNetworkIdle({ idleTime: 600, timeout: 20_000 }).catch(() => undefined)
async function type(selector, text) {
  await press(selector)
  await page.keyboard.type(text, { delay: 2 })
}

async function main() {
  if (!SKIP_SEED) await seed()

  const browser = await launch()
  page = await browser.newPage()
  watch = watchErrors(page)

  if (USAGE_LIMIT) {
    await usageLimit()
    return finish(browser)
  }
  if (SWEEP_ONLY) {
    await page.goto(`${BASE}/`, { waitUntil: "networkidle0" })
    await sweep()
    return finish(browser)
  }
  if (!PAGES_ONLY) await mainFlow()

  // 12. settings, presets, projects (innerText is what's on screen: eyebrows read in upper case)
  await page.goto(`${BASE}/settings`, { waitUntil: "networkidle0" })
  await waitText("Your look, captions and sound")
  await page.waitForFunction(() => /Connected|Not installed|not logged in/.test(document.body.innerText), { timeout: 30_000 }).catch(() => undefined)
  await shot("17-settings", 2500)
  await page.evaluate(() => document.querySelector("#brain").scrollIntoView({ block: "start" }))
  await shot("17b-settings-brain", 900)
  await hop(page, "/")
  await page.goto(`${BASE}/presets/gym-vlog`, { waitUntil: "networkidle0" })
  await waitText("presets/gym-vlog.md")
  await shot("18-presets", 1200)
  await hop(page)

  const glow = (await api("/projects")).find((p) => p.name === "12-week glow up")
  if (glow && glow.status === "planned") await api(`/projects/${glow.id}/render`, { method: "POST", body: "{}" })
  await page.goto(`${BASE}/`, { waitUntil: "networkidle0" })
  await waitText("New video")
  await page.waitForFunction(() => /Rendering/.test(document.body.innerText), { timeout: 20_000 }).catch(() => undefined)
  await idle()
  await shot("01-projects", 3000)
  await hop(page)

  await sweep()
  await finish(browser)
}

async function finish(browser) {
  await browser.close()
  if (watch.errors.length) {
    console.error(`✗ ${watch.errors.length} error(s) in the browser:\n  ` + watch.errors.join("\n  "))
    process.exit(1)
  }
  log("done: no page or console errors")
}

/** Every route, reached the way a user gets there and left again; then the error screen, and recovering from it. */
async function sweep() {
  const projects = await api("/projects")
  const chest = projects.find((p) => p.name === "5AM chest day")
  const bts = projects.find((p) => p.name === "Studio shoot BTS")
  const job = (await api(`/jobs?project_id=${chest.id}`)).find((j) => j.status === "done")
  const paths = [
    "/", "/new", `/projects/${chest.id}`,
    ...["type", "media", "idea", "review"].map((s) => `/projects/${chest.id}/setup/${s}`),
    `/projects/${chest.id}/questions`, `/projects/${chest.id}/plan`, `/projects/${chest.id}/video`,
    ...(job ? [`/projects/${chest.id}/jobs/${job.id}`] : []),
    `/projects/${bts.id}/plan`, `/projects/${bts.id}/video`, `/projects/${bts.id}/setup/media`,
    "/presets", "/presets/photo-dump", "/settings", "/no-such-page", "/projects/no-such-project",
  ]
  for (const p of paths) {
    await go(page, p)
    await assertNoErrorScreen(page, `on ${p}`)
    await hop(page, p === "/" ? "/settings" : "/")
  }
  log(`sweep: ${paths.length} routes visited, left and revisited`)

  // the error screen: a screen that throws shows it inside the shell, and Go back recovers
  await watch.expecting(async () => {
    await go(page, "/presets")
    await go(page, "/__crash")
    await waitText("Something went wrong on this screen")
    await click("Technical details")
    await shot("20-error-screen", 600)
    await click("Go back")
    await page.waitForFunction(() => location.pathname.startsWith("/presets"), { timeout: 10_000 })
    await sleep(800)
  })
  await assertNoErrorScreen(page, "after Go back from the error screen")
  log("error screen: shown for a crashing screen, Go back recovers")
}

/** With the demo brain failing like Claude Code at its usage limit: the job's error and the banner. */
async function usageLimit() {
  const p = (await api("/projects")).find((x) => x.name === "5AM chest day")
  await page.goto(`${BASE}/projects/${p.id}/video`, { waitUntil: "networkidle0" })
  await type('textarea[placeholder^="Open on the bench"]', "Swap the opening shot for the alarm")
  await click("Revise & render")
  await waitText("usage limit", 60_000)
  await shot("19-usage-limit", 1500)
}

async function mainFlow() {
  // 1. new video: content type
  await page.goto(`${BASE}/new`, { waitUntil: "networkidle0" })
  await waitText("Gym vlog")
  await hop(page)
  await type("#video-name", "5AM chest day")
  await click("Gym vlog")
  await shot("02-new-video")
  await click("Continue")
  await waitUrl(/\/setup\/media$/)
  await waitText("Add your media")
  const pid = page.url().split("/projects/")[1].split("/")[0]
  log("project", pid)

  // 2. media: clips, voice memo, track
  const clips = ["alarm-5am.mp4", "pre-workout.mp4", "incline-bench.mp4", "cable-fly.mp4", "lagoon-walk.mp4", "brunch-lekki.mp4", "fit-check.jpg"].map((f) => m("gym", f))
  await (await page.$('input[data-testid="upload-clip"]')).uploadFile(...clips)
  await waitText("Added 7 files", 120_000)
  await (await page.$('input[data-testid="upload-voiceover"]')).uploadFile(m("chest-day-vo.m4a"))
  await waitText("chest-day-vo.m4a", 60_000)
  await (await page.$('input[data-testid="upload-music"]')).uploadFile(m("afro-drill-120.wav"))
  await waitText("afro-drill-120.wav", 60_000)
  await idle()
  await shot("03-media", 1500)
  await hop(page)

  // 3. the idea
  await click("Continue")
  await waitUrl(/\/setup\/idea$/)
  await waitText("Describe the video")
  await click("Voiceover")
  await type('textarea[name="idea"]', "5AM to brunch: chest day, a walk by the lagoon, brunch with the girls. Show the discipline without being preachy, and make the training part hit.")
  await type('input[name="hook"]', "The 5:30 alarm, phone in hand")
  await click("Text on screen")
  await type('textarea[name="labels"]', "5:30AM, Incline bench 4x10, Lekki brunch")
  await click("Sound, look & pacing")
  await click("Punchy")
  await page.evaluate(() => document.querySelector("#main").scrollTo({ top: 0 }))
  await shot("04-idea", 1500)
  await hop(page)                                   // leaving the step saves what was typed (flush on unmount)
  const brief = (await api(`/projects/${pid}`)).brief
  if (!brief.idea?.startsWith("5AM to brunch") || !brief.labels?.includes("Lekki brunch"))
    throw new Error(`the brief wasn't saved when its step closed: ${JSON.stringify(brief).slice(0, 300)}`)

  // 4. review -> generate
  await click("Continue")
  await waitUrl(/\/setup\/review$/)
  await waitText("Ready to plan")
  await idle()
  await shot("05-review", 1200)
  await hop(page)
  await click("Generate plan")

  // 5. Claude reads the brief
  await waitText("Claude is reading your brief", 20_000)
  await shot("06-claude-reading", 1400)
  await hop(page, "/")                              // mid-analyse: the job page reconnects (or moves on if it finished)

  // 6. questions
  await waitUrl(/\/questions$/, 30_000)
  await waitText("from Claude")
  await hop(page)
  await waitText("from Claude")
  await sleep(800)
  await click("Incline bench")
  await press("button::-p-text(on)")
  await waitText("Then Claude plans the edit", 10_000)
  await shot("07-questions", 900)
  await click("Plan the edit")

  // 7. planning: transcription, voice clean-up, rough cut, then Claude
  await waitUrl(/\/jobs\//)
  await page.waitForFunction(() => /Clean up the voiceover|Rough cut|Transcribe/.test(document.body.innerText) && /%/.test(document.body.innerText), { timeout: 60_000 })
  await click("Show log")
  await sleep(4000)
  await shot("08-plan-progress", 300)
  await hop(page, "/")                              // mid-planning
  await waitText("Claude is planning", 240_000)
  await shot("09-claude-planning", 1600)
  await hop(page, `/projects/${pid}/setup/review`)  // while Claude is planning

  // 8. the timeline
  await waitUrl(/\/plan$/, 120_000)
  await waitText("Review the plan")
  await idle()
  await shot("10-timeline", 2500)
  await page.locator('[data-shot="3"] button').click()
  await shot("11-timeline-shot", 1500)
  const textPill = await page.$("button[title='5:30AM']")
  if (textPill) {
    await textPill.click()
    await sleep(500)
    await shot("12-timeline-text", 900)
  }
  await hop(page)

  // 9. approve & render
  await click("Approve & render")
  await waitUrl(/\/jobs\//)
  await page.waitForFunction(() => /Frame and cut every shot/.test(document.body.innerText), { timeout: 60_000 })
  await page.waitForFunction(() => {
    const m = document.body.innerText.match(/(\d+)\s*%/)
    return m && Number(m[1]) >= 25
  }, { timeout: 300_000, polling: 300 })
  await click("Show log")
  await shot("13-render", 1200)
  await hop(page, "/")                              // mid-render

  // 10. the result
  await waitUrl(/\/video$/, 600_000)
  await waitText("Version 1")
  await idle()
  await shot("14-result", 2500)
  await hop(page)

  // 11. request changes -> v2
  await type('textarea[placeholder^="Open on the bench"]', 'Make the first label say "5AM" and use flash cuts between shots')
  await click("Revise & render")
  await waitText("Claude is revising the plan", 30_000)
  await shot("15-claude-revising", 1400)
  await hop(page)                                   // mid-revise: coming back follows on to the render
  await page.waitForFunction(() => /Rendering/.test(document.body.innerText) && location.pathname.includes("/jobs/"), { timeout: 120_000 })
  await hop(page, "/presets")                       // mid-render of v2
  await waitUrl(/\/video$/, 600_000)
  await waitText("Version 2")
  await idle()
  await shot("16-result-v2", 2500)
  await hop(page)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
