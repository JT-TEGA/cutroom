// Smoke test of the editing interactions, checked against the API: reorder clips in the wizard, reorder segments,
// swap a clip in from the media bin, delete a shot and undo, edit a label, and drop files the way the Photos app hands
// them to the browser (a JPEG without an extension, a HEIC with no type, a MOV), plus a drop with nothing in it. Run against a demo workspace that has
// the walkthrough's projects (node app/scripts/walkthrough.mjs first).
//
//   CUTROOM_URL=http://localhost:5173 node app/scripts/check-interactions.mjs
import { execFileSync } from "node:child_process"
import { mkdtempSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { BASE, hop, launch, sleep, watchErrors } from "./browser.mjs"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")

const api = async (p) => (await fetch(`${BASE}/api${p}`)).json()
let failures = 0
const check = (ok, what) => {
  console.log(`${ok ? "✓" : "✗"} ${what}`)
  if (!ok) failures++
}
async function until(fn, timeout = 10_000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    if (await fn()) return true
    await sleep(250)
  }
  return false
}

async function drag(page, from, to) {
  const a = await (await page.waitForSelector(from)).boundingBox()
  const b = await (await page.waitForSelector(to)).boundingBox()
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(a.x + a.width / 2 + 10, a.y + a.height / 2, { steps: 4 })
  await page.mouse.move(b.x + b.width / 2 + 4, b.y + b.height / 2, { steps: 16 })
  await sleep(200)
  await page.mouse.up()
}

const browser = await launch({ width: 1440, height: 900 })
const page = await browser.newPage()
const watch = watchErrors(page)
const projects = await api("/projects")
const find = (name) => projects.find((p) => p.name === name)

// 1. wizard: reorder clips by dragging
const bts = find("Studio shoot BTS")
const before = (await api(`/projects/${bts.id}/files`)).map((f) => f.name)
await page.goto(`${BASE}/projects/${bts.id}/setup/media`, { waitUntil: "networkidle0" })
const tiles = await page.$$("[aria-roledescription='sortable']")
check(tiles.length === before.length, `media step shows ${before.length} sortable clips`)
await page.evaluate(() => document.querySelectorAll("[aria-roledescription='sortable']").forEach((el, i) => el.setAttribute("data-i", String(i))))
await drag(page, "[data-i='0']", "[data-i='2']")
check(await until(async () => (await api(`/projects/${bts.id}/files`))[2].name === before[0]), `dragging clip 1 to place 3 saves the new order (${before[0]} is now 3rd)`)
await hop(page)
check((await page.$$("[aria-roledescription='sortable']")).length === before.length, "after leaving and coming back the clips are all there")

// 2. timeline: reorder segments, undo
const legs = find("Leg day routine")
const order = async () => (await api(`/projects/${legs.id}/timeline`)).timeline.segments.map((s) => s.src)
const o1 = await order()
await page.goto(`${BASE}/projects/${legs.id}/plan`, { waitUntil: "networkidle0" })
await page.waitForSelector("[data-shot='1']")
await drag(page, "[data-shot='1']", `[data-shot='${o1.length}']`)
check(await until(async () => (await order())[o1.length - 1] === o1[0]), "dragging the first segment to the end moves it there")
await sleep(500)
await page.keyboard.down("Meta")
await page.keyboard.press("z")
await page.keyboard.up("Meta")
check(await until(async () => JSON.stringify(await order()) === JSON.stringify(o1)), "⌘Z puts it back")
await hop(page)

// 3. swap a clip in from the media bin
await sleep(600)
const files = await api(`/projects/${legs.id}/files`)
const other = files.find((f) => f.kind === "clip" && f.path !== o1[0])
const bin = await page.$$(`[title^="${other.name}"]`)
check(bin.length > 0, `media bin shows ${other.name}`)
await page.evaluate((name) => document.querySelector(`[title^="${name}"]`).setAttribute("data-drag", "1"), other.name)
await drag(page, "[data-drag='1']", "[data-shot='1']")
check(await until(async () => (await order())[0] === other.path), `dropping ${other.name} on shot 1 swaps it in`)
await hop(page)

// 4. delete a shot with the keyboard, then undo
await sleep(600)
const n = (await order()).length
await page.click("[data-shot='2'] button")
await page.keyboard.press("Delete")
check(await until(async () => (await order()).length === n - 1), "Delete removes the selected shot")
await sleep(500)
await page.keyboard.down("Meta")
await page.keyboard.press("z")
await page.keyboard.up("Meta")
check(await until(async () => (await order()).length === n), "⌘Z brings it back")
await hop(page)

// 5. edit a label's text in the inspector
await sleep(600)
const tl = (await api(`/projects/${legs.id}/timeline`)).timeline
if (tl.text?.length) {
  await page.click(`button[title^="${tl.text[0].text}"]`)
  const input = await page.waitForSelector('input[name="overlay-text"]')
  await input.click({ clickCount: 3 })
  await page.keyboard.type("Squats 5x5")
  await page.keyboard.press("Enter")
  check(await until(async () => (await api(`/projects/${legs.id}/timeline`)).timeline.text[0].text === "Squats 5x5"), "editing a label saves it")
  await hop(page)
}

// 6. drop items like a drag out of the Photos app: odd names and types must still come in
{
  const dir = mkdtempSync(path.join(tmpdir(), "cutroom-drop-"))
  const heic = path.join(dir, "IMG_0043.HEIC")
  const mov = path.join(dir, "IMG_0044.MOV")
  execFileSync("sips", ["-s", "format", "heic", path.join(repo, ".demo/media/night/IMG_0802.jpg"), "--out", heic], { stdio: "ignore" })
  execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30", "-t", "1",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", mov])
  const b64 = (f) => readFileSync(f).toString("base64")
  const files = [
    { name: "IMG_0042", type: "image/jpeg", b64: b64(path.join(repo, ".demo/media/night/IMG_0801.jpg")) },
    { name: "IMG_0043.HEIC", type: "", b64: b64(heic) },
    { name: "IMG_0044.MOV", type: "video/quicktime", b64: b64(mov) },
  ]
  const target = find("Leg day routine")
  const names = async () => (await api(`/projects/${target.id}/files`)).map((f) => f.name)
  const n0 = (await names()).length
  await page.goto(`${BASE}/projects/${target.id}/setup/media`, { waitUntil: "networkidle0" })
  const drop = (list) =>
    page.evaluate((list) => {
      const dt = new DataTransfer()
      for (const f of list) dt.items.add(new File([Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0))], f.name, { type: f.type }))
      const zone = document.querySelector("[data-testid='drop-clip']")
      for (const t of ["dragenter", "dragover", "drop"]) zone.dispatchEvent(new DragEvent(t, { dataTransfer: dt, bubbles: true, cancelable: true }))
    }, list)
  await drop(files)
  check(
    await until(async () => {
      const n = await names()
      return n.length === n0 + 3 && n.includes("IMG_0042.jpg") && n.includes("IMG_0043.HEIC") && n.includes("IMG_0044.MOV")
    }, 30_000),
    "a Photos-style drop (no extension, HEIC with no type, MOV) adds all three files",
  )
  await drop([])
  check(
    await until(async () => page.evaluate(() => document.body.innerText.includes("Nothing came through from that drag"))),
    "an empty drop says what to do instead",
  )
  // put the project back as it was
  for (const f of (await api(`/projects/${target.id}/files`)).filter((f) => /^IMG_004[234]/.test(f.name)))
    await fetch(`${BASE}/api/projects/${target.id}/files/${f.id}`, { method: "DELETE" })
  await hop(page)
}

await browser.close()
check(watch.errors.length === 0, `no page or console errors${watch.errors.length ? ":\n  " + watch.errors.join("\n  ") : ""}`)
console.log(failures ? `${failures} check(s) failed` : "all interactions work")
process.exit(failures ? 1 : 0)
