// Shared by the browser scripts: launch, error collection, and client-side navigation "hops".
import puppeteer from "puppeteer"

export const BASE = process.env.CUTROOM_URL ?? "http://localhost:5173"
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** Bundled Chrome for Testing by default; CUTROOM_CHROME=/path/to/Chrome to test a real install (newer Chromes
 * behave differently: Element.scrollTo() returns a Promise from Chrome 15x).
 * mic: a WAV file the browser hears as its microphone (Chrome's fake capture device; the permission is granted). */
export async function launch(viewport = { width: 1440, height: 900, deviceScaleFactor: 2 }, { mic } = {}) {
  const browser = await puppeteer.launch({
    // CUTROOM_HEADLESS=shell: chrome-headless-shell, which keeps drawing while the Mac's display sleeps (the full
    // headless Chrome stops painting then, so screenshots and clicks time out)
    headless: process.env.CUTROOM_HEADLESS === "shell" ? "shell" : true,
    defaultViewport: viewport,
    executablePath: process.env.CUTROOM_CHROME || undefined,
    args: [
      "--autoplay-policy=no-user-gesture-required",
      // the audio service's sandbox can't open the file (the mic is then silent), so it's off for this test browser
      ...(mic
        ? [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            `--use-file-for-fake-audio-capture=${mic}%noloop`,
            "--disable-features=AudioServiceSandbox",
          ]
        : []),
    ],
  })
  console.log(`· browser ${await browser.version()}`)
  return browser
}

/** Every page error and console error, so a run fails on crashes React only logs (unmount errors, bad effects).
 * "Failed to load resource" lines are expected HTTP errors (a 404 timeline before a plan exists) and are skipped. */
export function watchErrors(page) {
  const errors = []
  let paused = false
  page.on("pageerror", (e) => !paused && errors.push(`page error: ${e.message}`))
  page.on("console", (m) => {
    if (paused || m.type() !== "error") return
    const text = m.text()
    if (/^Failed to load resource/.test(text)) return
    errors.push(`console error: ${text.split("\n")[0].slice(0, 300)}`)
  })
  return {
    errors,
    /** run fn while errors are expected (the deliberate /__crash screen) */
    async expecting(fn) {
      paused = true
      try {
        return await fn()
      } finally {
        await sleep(300)
        paused = false
      }
    },
  }
}

/** Navigate like a user would (client-side, so the current screen unmounts): to `path` and wait. */
export async function go(page, path, settle = 900) {
  await page.evaluate((p) => window.__cutroom.navigate(p), path)
  await page.waitForFunction((p) => location.pathname === p.split("?")[0], { timeout: 15_000 }, path).catch(() => undefined)
  await sleep(settle)
}

/** Away to another screen and back again (history.back, like the browser button); fails on the error screen. */
export async function hop(page, away = "/settings", settle = 900) {
  const here = await page.evaluate(() => location.pathname)
  await go(page, away === here ? "/presets" : away, settle)
  await page.evaluate(() => history.back())
  await page.waitForFunction((p) => location.pathname === p, { timeout: 15_000, polling: 50 }, here).catch(() => undefined)
  await sleep(settle)
  await assertNoErrorScreen(page, `after leaving and coming back to ${here}`)
  return here
}

export async function assertNoErrorScreen(page, when) {
  const text = await page.evaluate(() => document.body.innerText)
  if (/Something went wrong on this screen|Unexpected Application Error/.test(text))
    throw new Error(`the error screen is showing ${when}:\n${text.slice(0, 400)}`)
}
