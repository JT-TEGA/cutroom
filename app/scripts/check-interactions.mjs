// Smoke test of the editing interactions, checked against the API: reorder clips in the wizard, reorder segments,
// swap a clip in from the media bin, delete a shot and undo, edit a label. Run against a demo workspace that has
// the walkthrough's projects (node app/scripts/walkthrough.mjs first).
//
//   CUTROOM_URL=http://localhost:5173 node app/scripts/check-interactions.mjs
import { BASE, hop, launch, sleep, watchErrors } from "./browser.mjs"

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

await browser.close()
check(watch.errors.length === 0, `no page or console errors${watch.errors.length ? ":\n  " + watch.errors.join("\n  ") : ""}`)
console.log(failures ? `${failures} check(s) failed` : "all interactions work")
process.exit(failures ? 1 : 0)
