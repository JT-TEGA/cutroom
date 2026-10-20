// End-to-end walkthrough of the app with the scripted demo brain, saving a screenshot of every screen.
//
//   ./cutroom --demo --no-open &            (or with CUTROOM_API_PORT / CUTROOM_APP_PORT)
//   .venv/bin/python scripts/demo_media.py  (synthetic clips, voice memo and track in .demo/media)
//   node app/scripts/walkthrough.mjs        (CUTROOM_URL=http://localhost:5173 by default)
//
// A few side projects are created through the API (so the projects grid has something in every state); the main
// one, "5AM chest day", goes through the UI: new video wizard -> voiceover recorded in the app -> questions -> plan
// -> timeline edits -> render -> result -> revise -> v2. Screenshots (2x JPEG) land in docs/screenshots/.
//
// The recorder hears the demo voice memo through Chrome's fake microphone (--use-file-for-fake-audio-capture), so
// the take that gets used is the same speech the planning step cleans up and transcribes.
//
// Along the way it leaves every screen and comes back (client-side, so screens really unmount), including in the
// middle of planning and rendering, then sweeps every route; any page error or console error fails the run.
// CUTROOM_CHROME=/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome runs it in your own Chrome.
import { execFileSync } from "node:child_process"
import { existsSync, mkdirSync, readFileSync } from "node:fs"
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
const PHOTOS_DENIED = process.argv.includes("--photos-denied")  // the server runs with CUTROOM_PHOTOS=denied
const SKIP_SEED = PAGES_ONLY || SWEEP_ONLY || PHOTOS_DENIED || process.argv.includes("--no-seed")
mkdirSync(OUT, { recursive: true })

const log = (...a) => console.log("·", ...a)

// the fake mic: the voice memo as 48 kHz WAV (what Chrome's fake capture device plays), with a pause after it
const MIC = path.join(MEDIA, "chest-day-vo-mic.wav")
function micFile() {
  const src = path.join(MEDIA, "chest-day-vo.m4a")
  if (!existsSync(MIC))
    execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-i", src, "-af", "apad=pad_dur=4", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", MIC])
  return Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], { encoding: "utf8" }))
}

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
  // posted with the song added in Instagram: the result shows the start time and the copy without music
  await api(`/projects/${night.id}`, { method: "PATCH", body: JSON.stringify({ brief: { music_in_app: true } }) })
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

  const voSeconds = micFile()
  const browser = await launch(undefined, { mic: MIC })
  page = await browser.newPage()
  watch = watchErrors(page)

  if (USAGE_LIMIT) {
    await usageLimit()
    return finish(browser)
  }
  if (PHOTOS_DENIED) {
    await photosDenied()
    return finish(browser)
  }
  if (SWEEP_ONLY) {
    await page.goto(`${BASE}/`, { waitUntil: "networkidle0" })
    await sweep()
    return finish(browser)
  }
  if (!PAGES_ONLY) {
    await mainFlow(voSeconds)
    await voiceoverExtras()
    await songFlow()
    await photosFlow()
    await inAppResult()
  }

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
  const night = projects.find((p) => p.name === "Lekki night out")
  const job = (await api(`/jobs?project_id=${chest.id}`)).find((j) => j.status === "done")
  const paths = [
    "/", "/new", `/projects/${chest.id}`,
    ...["type", "media", "idea", "review"].map((s) => `/projects/${chest.id}/setup/${s}`),
    `/projects/${chest.id}/questions`, `/projects/${chest.id}/plan`, `/projects/${chest.id}/video`,
    ...(job ? [`/projects/${chest.id}/jobs/${job.id}`] : []),
    `/projects/${bts.id}/plan`, `/projects/${bts.id}/video`, `/projects/${bts.id}/setup/media`,
    ...(night ? [`/projects/${night.id}/video`, `/projects/${night.id}/setup/media`] : []),
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

/** Import from Photos (the demo's stand-in library): albums, multi-select, import into the BTS project. */
async function photosFlow() {
  const bts = (await api("/projects")).find((p) => p.name === "Studio shoot BTS")
  const before = (await api(`/projects/${bts.id}/files`)).length
  await go(page, `/projects/${bts.id}/setup/media`)
  await click("Import from Photos")
  await page.waitForSelector("[data-album='BTS']", { timeout: 30_000 })
  await hop(page)                                    // the picker closes when the screen unmounts; open it again
  await click("Import from Photos")
  await page.waitForSelector("[data-album='BTS']", { timeout: 30_000 })
  await press("[data-album='BTS']")
  await page.waitForFunction(() => document.querySelectorAll("[data-photo]").length === 3, { timeout: 15_000 })
  const tiles = await page.$$("[data-photo]")
  await tiles[0].click()
  await tiles[2].click()
  await press("[data-album='Night']")
  await page.waitForFunction(() => document.querySelectorAll("[data-photo]").length === 6, { timeout: 15_000 })
  await (await page.$$("[data-photo]"))[1].click()
  await page.waitForFunction(() => /^3\s+selected/.test(document.querySelector("[data-testid='photos-selected']")?.innerText ?? ""), { timeout: 5_000 })
  await page.waitForFunction(() => [...document.querySelectorAll("img")].filter((i) => i.src.includes("/photos/thumbnail/")).every((i) => i.complete), { timeout: 15_000 }).catch(() => undefined)
  await shot("03c-photos", 900)
  await click("Import 3")
  await waitText("Imported 3 items from Photos", 60_000)
  const after = (await api(`/projects/${bts.id}/files`)).length
  if (after !== before + 3) throw new Error(`import from Photos: expected ${before + 3} files, found ${after}`)
  log("photos: picked 3 across two albums, imported into the project")
  await hop(page)
}

/** The song on a 15s photo dump: the auto pick before the drop, playing from there; picking a start and back to auto. */
async function songFlow() {
  const night = (await api("/projects")).find((p) => p.name === "Lekki night out")
  await go(page, `/projects/${night.id}/setup/media`)
  await page.waitForSelector("[data-testid='waveform']", { timeout: 60_000 })
  await page.evaluate(() => document.querySelector("[data-testid='music-panel']").scrollIntoView({ block: "center" }))
  await waitText("Auto: two bars before the drop", 10_000)
  await press("button[aria-label='Play from the start point']")
  await sleep(1500)
  await shot("03b-music", 200)
  await press("button[aria-label='Pause']").catch(() => undefined)
  const wave = await (await page.$("[data-testid='waveform']")).boundingBox()
  await page.mouse.click(wave.x + wave.width * 0.5, wave.y + wave.height / 2)
  await waitText("Your pick", 10_000)
  const picked = await page.$eval("[data-testid='music-start']", (el) => el.textContent)
  await sleep(800)
  const b1 = (await api(`/projects/${night.id}`)).brief
  if (typeof b1.music_start !== "number" || `0:${String(Math.round(b1.music_start)).padStart(2, "0")}` !== picked)
    throw new Error(`the start point on screen (${picked}) wasn't saved (${b1.music_start})`)
  await hop(page)
  await waitText("Your pick", 20_000)                 // still there after leaving and coming back
  await click("Auto")
  await waitText("Auto: two bars before the drop", 10_000)
  await sleep(800)
  if ((await api(`/projects/${night.id}`)).brief.music_start !== null) throw new Error("Auto didn't clear the start point")
  log(`song: picked ${picked}, saved; back to auto`)
}

/** A video posted with the in-app sound: the start time card and the two downloads. */
async function inAppResult() {
  const night = (await api("/projects")).find((p) => p.name === "Lekki night out")
  await go(page, `/projects/${night.id}/video`)
  await page.waitForSelector("[data-testid='in-app-card']", { timeout: 20_000 })
  await idle()
  await shot("21-result-in-app", 2000)
  await hop(page)
}

/** With CUTROOM_PHOTOS=denied: the picker explains how to give access. */
async function photosDenied() {
  const p = (await api("/projects")).find((x) => x.name === "Studio shoot BTS")
  await page.goto(`${BASE}/projects/${p.id}/setup/media`, { waitUntil: "networkidle0" })
  await click("Import from Photos")
  await page.waitForSelector("[data-testid='photos-access']", { timeout: 30_000 })
  await shot("03d-photos-access", 900)
  await click("Check again")
  await page.waitForSelector("[data-testid='photos-access']", { timeout: 30_000 })
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

/** The Voiceover card's recorder on the main project: a take dropped by leaving mid-take, one kept by closing the
 * recorder mid-take (paused and resumed on the way), the whole voice memo as take 2, listening back, deleting take 1
 * and using take 2, which goes into the Voiceover slot like an imported memo. */
async function recordVoiceover(pid, voSeconds) {
  const takes = async () => (await api(`/projects/${pid}/takes`)).map((t) => t.id)
  const openRecorder = async () => {
    await press("[data-testid='drop-voiceover'] button::-p-text(Record)")
    await page.waitForSelector("[role='dialog'] [data-testid='record-tip']", { timeout: 10_000 })
  }
  const inDialog = (text) => press(`[role='dialog'] button::-p-text(${text})`)
  const status = (s) => page.waitForSelector(`[data-testid='recorder'][data-status='${s}']`, { timeout: 20_000 })

  // leaving the screen mid-take drops it (and lets go of the mic) without an error
  await openRecorder()
  await inDialog("Record")
  await status("recording")
  await sleep(1200)
  await hop(page)
  if ((await takes()).length) throw new Error("a take abandoned by leaving the screen was kept")

  // take 1: live level and timer, pause / resume, then closing the recorder keeps it
  await openRecorder()
  await inDialog("Record")
  await status("recording")
  await page.waitForFunction(() => Number(document.querySelector("[data-testid='level-meter']")?.dataset.level) > 0.3, { timeout: 15_000 })
  await sleep(2200)
  await shot("03e-recording", 200)
  await inDialog("Pause")
  await status("paused")
  await sleep(500)
  await inDialog("Resume")
  await status("recording")
  await sleep(800)
  await page.keyboard.press("Escape")
  await waitText("Saved take 1", 20_000)
  if ((await takes()).join() !== "take-1") throw new Error(`closing mid-take should keep it: ${await takes()}`)

  // take 2: the whole memo; listen back
  await openRecorder()
  await page.waitForSelector("[data-testid='take-review'][data-take='take-1']", { timeout: 10_000 })
  await inDialog("Re-record")
  await status("recording")
  await sleep(voSeconds * 1000 + 900)
  await inDialog("Stop")
  await page.waitForSelector("[data-testid='take-review'][data-take='take-2']", { timeout: 30_000 })
  await press("button[aria-label='Play the take']")
  await sleep(2500)
  await shot("03f-takes", 200)
  await press("button[aria-label='Pause the take']")

  // keep take 2: delete take 1, use take 2
  await press("[data-testid='takes'] [data-take='take-1']")
  await page.waitForSelector("[data-testid='take-review'][data-take='take-1']", { timeout: 10_000 })
  await inDialog("Delete")
  await page.waitForSelector("[data-testid='take-review'][data-take='take-2']", { timeout: 10_000 })
  if ((await takes()).join() !== "take-2") throw new Error(`Delete should leave take 2 only: ${await takes()}`)
  await inDialog("Use this")
  await waitText("Take 2 is your voiceover", 60_000)
  await page.waitForFunction(() => !document.querySelector("[role='dialog']"), { timeout: 10_000 })
  const vo = (await api(`/projects/${pid}/files`)).filter((f) => f.kind === "voiceover")
  if (vo.length !== 1 || vo[0].take !== "take-2" || vo[0].name !== "take-2.wav" || Math.abs(vo[0].duration - voSeconds) > 2)
    throw new Error(`the used take isn't the project's voiceover: ${JSON.stringify(vo)}`)
  log(`voiceover: recorded 2 takes, kept take 2 (${vo[0].duration.toFixed(1)}s, ${vo[0].info})`)
}

/** A blocked mic explains itself (then Try again records once it's allowed), and Browse still works for a voice memo.
 * On the BTS project, which is left as it was. */
async function voiceoverExtras() {
  const bts = (await api("/projects")).find((p) => p.name === "Studio shoot BTS")
  await go(page, `/projects/${bts.id}/setup/media`)

  // what Chrome does when the mic is blocked for the page
  await page.evaluate(() => {
    window.__gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"))
  })
  await press("[data-testid='drop-voiceover'] button::-p-text(Record)")
  await press("[role='dialog'] button::-p-text(Record)")
  await page.waitForSelector("[data-testid='mic-help'][data-problem='denied']", { timeout: 10_000 })
  await shot("03g-mic-blocked", 500)
  await page.evaluate(() => (navigator.mediaDevices.getUserMedia = window.__gum))
  await press("[role='dialog'] button::-p-text(Try again)")
  await page.waitForSelector("[data-testid='recorder'][data-status='recording']", { timeout: 15_000 })
  await hop(page)
  if ((await api(`/projects/${bts.id}/takes`)).length) throw new Error("the BTS project shouldn't keep a take")

  await (await page.$('input[data-testid="upload-voiceover"]')).uploadFile(m("chest-day-vo.m4a"))
  await waitText("chest-day-vo.m4a", 60_000)
  await press("[data-testid='drop-voiceover'] button[aria-label='Remove chest-day-vo.m4a']")
  await page.waitForFunction(() => !document.querySelector("[data-testid='drop-voiceover']").innerText.includes("chest-day-vo.m4a"), { timeout: 15_000 })
  if ((await api(`/projects/${bts.id}/files`)).some((f) => f.kind === "voiceover")) throw new Error("the browsed voice memo wasn't removed")
  log("voiceover: a blocked mic explains itself, Try again records; Browse adds and removes a memo")
}

async function mainFlow(voSeconds) {
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

  // 2a. nothing added yet: the clips card says what's needed, the edit order is a slim bar, Continue waits
  await page.waitForSelector("[data-testid='clips-required']", { timeout: 10_000 })
  await page.waitForSelector("[data-testid='edit-order'][data-state='collapsed']", { timeout: 10_000 })
  const continueOff = await page.$$eval("button", (bs) => bs.find((b) => b.innerText.trim().startsWith("Continue"))?.disabled)
  if (!continueOff) throw new Error("Continue should be disabled on the media step until a clip or photo is added")
  await shot("03a-media-empty", 900)

  // 2. media: clips, voice memo, track
  const clips = ["alarm-5am.mp4", "pre-workout.mp4", "incline-bench.mp4", "cable-fly.mp4", "lagoon-walk.mp4", "brunch-lekki.mp4", "fit-check.jpg"].map((f) => m("gym", f))
  await (await page.$('input[data-testid="upload-clip"]')).uploadFile(...clips)
  await waitText("Added 7 files", 120_000)
  await page.waitForSelector("[data-testid='edit-order'][data-state='expanded']", { timeout: 10_000 })
  if (await page.$("[data-testid='clips-required']")) throw new Error("the clips card still asks for a clip after 7 were added")
  await recordVoiceover(pid, voSeconds)
  await (await page.$('input[data-testid="upload-music"]')).uploadFile(m("afro-drill-120.wav"))
  await waitText("afro-drill-120.wav", 60_000)
  await idle()
  await shot("03-media", 1500)
  await hop(page)

  // a gym vlog is as long as this 48s song, so the song panel says it uses all of it (the photo dump picks a part)
  await page.waitForSelector("[data-testid='music-start']", { timeout: 60_000 })
  await waitText("so it uses all of it", 10_000)

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
  // the recorded take went through the voiceover clean-up like any voice memo: there's a preview and the numbers
  const [vo] = await api(`/projects/${pid}/voiceover`)
  if (!vo?.preview?.endsWith("vo_preview.wav") || vo.stats?.lufs_after == null) throw new Error(`no clean-up for the recorded take: ${JSON.stringify(vo)}`)
  log(`voiceover: cleaned ${vo.stats.lufs_before} -> ${vo.stats.lufs_after} LUFS, preview ${vo.preview}`)
  await idle()
  await shot("10-timeline", 2500)
  await page.locator('[data-shot="3"] button').click()
  await shot("11-timeline-shot", 1500)

  // the plan screen's own edits: each one saves through PUT /timeline (the pre-render check) and leaves a plan
  // with no problems
  const before = new Set((await api(`/projects/${pid}/timeline`)).problems ?? [])
  const planOk = async (what) => {
    await idle()
    const v = await api(`/projects/${pid}/timeline`)
    const added = (v.problems ?? []).filter((p) => !before.has(p))
    if (added.length) throw new Error(`${what} left problems: ${added.join("; ")}`)
    return v
  }
  const toastSays = (text) => waitText(text, 15_000)
  const setField = async (label, value) => {
    await page.click(`input[aria-label="${label}"]`, { clickCount: 3 })
    await page.keyboard.type(String(value))
  }
  const plays = await page.$('input[aria-label="Plays for (s)"]')
  if (plays) {
    const cur = Number(await plays.evaluate((el) => el.value))
    const next = Math.max(1, Math.round((cur - 0.3) * 10) / 10)
    await setField("Plays for (s)", next)
    await click("Set")
    await toastSays(`now plays for ${next} s`)
    const v = await planOk("setting a length")
    const got = v.shots.find((s) => s.idx === 3).duration
    if (Math.abs(got - next) > 0.05) throw new Error(`shot 3 should play for ${next} s, plays for ${got} s`)
    log(`length: shot 3 ${cur} s -> ${got.toFixed(2)} s`)
  }
  const capSwitch = await page.$('button[aria-label="Captions on this part"]')
  if (capSwitch) {
    await capSwitch.click()
    await toastSays("Captions off")
    await planOk("captions off")
    await page.click('button[aria-label="Captions on this part"]')
    await toastSays("Captions on")
    await planOk("captions on")
  }
  await type('input[name="new-text"]', "Chest day")
  await click("Add")
  await toastSays("Text added")
  const withText = await planOk("adding text")
  if (!withText.overlays.some((o) => o.kind === "text" && o.text === "Chest day")) throw new Error("the new text isn't on the timeline")
  await waitText("Text on screen")
  await shot("11b-timeline-add-text", 900)
  await click("Remove text")
  await toastSays("Text removed")
  await planOk("removing text")
  await page.keyboard.press("Escape")
  await waitText("The plan")
  const card = await page.$eval('button[aria-label="End card"]', (el) => el.getAttribute("aria-checked"))
  await page.click('button[aria-label="End card"]')
  await toastSays(card === "true" ? "End card off" : "End card on")
  await planOk("the end card toggle")
  await shot("11c-timeline-end-card", 900)
  await page.click('button[aria-label="End card"]')
  await toastSays(card === "true" ? "End card on" : "End card off")
  await planOk("the end card toggle")

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
