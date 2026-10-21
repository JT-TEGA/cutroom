// The visual trimmer inside the shot inspector, against the fake API: the filmstrip shimmers until it's built, the
// handles drag (snapping to beats, not with Alt, never under the minimum), and the exact-time inputs and the handles
// follow each other both ways. What gets saved is the same call the number inputs make.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ResolvedShot, TimelineView } from "@/api/types"
import { server } from "@/test/server"
import { LengthEditor } from "./Inspector"

const FRAMES = Array.from({ length: 12 }, (_, i) => ({ t: i * 0.5, path: `p1/work/_cache/filmstrip/k/f_${String(i + 1).padStart(3, "0")}.jpg` }))

const shot: ResolvedShot = {
  idx: 2, segment: 1, shot: null, kind: "clip", src: "inputs/clips/bench.mp4", in: 1, out: 3, start: 0.25, end: 2.25,
  duration: 2, role: "mute", speed: 1, ramp: false, beat_synced: false,
} as ResolvedShot

const view = (beatCut = true) =>
  ({
    timeline: {
      segments: [{ src: "inputs/clips/talk.mp4", in: 0, out: 0.25 }, { src: "inputs/clips/bench.mp4", in: 1, out: 3 }],
      text: [], captions: { enabled: true, replace: {}, hide: [] },
    },
    duration: 2.25, shots: [], overlays: [], captions: { enabled: true },
    // 120 BPM: a beat every 0.5 s of the edit
    music: { src: "inputs/music/x.wav", bpm: 120, beats: [0, 0.5, 1, 1.5, 2, 2.5, 3], beat_cut: beatCut },
  }) as unknown as TimelineView

function setup({ beatCut = true, building = 1 } = {}) {
  let asks = 0
  server.on("GET /api/projects/p1/filmstrip", ({ url }) => {
    expect(url.searchParams.get("src")).toBe("inputs/clips/bench.mp4")
    asks++
    return asks <= building
      ? { status: 200, json: { src: "inputs/clips/bench.mp4", status: "building", duration: 6, frames: [] } }
      : { status: 200, json: { src: "inputs/clips/bench.mp4", status: "ready", duration: 6, frames: FRAMES } }
  })
  const onTrim = vi.fn()
  const onDuration = vi.fn()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <LengthEditor s={shot} view={view(beatCut)} pid="p1" clipDur={6} onTrim={onTrim} onDuration={onDuration} />
    </QueryClientProvider>,
  )
  // the strip is 600 px wide: 100 px per second of the 6 s clip
  const strip = screen.getByTestId("filmstrip")
  vi.spyOn(strip, "getBoundingClientRect").mockReturnValue({ left: 0, width: 600, top: 0, height: 56, right: 600, bottom: 56, x: 0, y: 0, toJSON: () => ({}) })
  return { onTrim, onDuration }
}

const handle = (name: "Trim start" | "Trim end") => screen.getByRole("slider", { name })
function drag(name: "Trim start" | "Trim end", toX: number, opts: { altKey?: boolean } = {}) {
  const h = handle(name)
  fireEvent.pointerDown(h, { pointerId: 1, clientX: 0 })
  fireEvent.pointerMove(h, { pointerId: 1, clientX: toX, ...opts })
  return () => fireEvent.pointerUp(h, { pointerId: 1, clientX: toX })
}
const openExact = () => fireEvent.click(screen.getByRole("button", { name: /Enter exact times/ }))
const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement

beforeEach(() => server.reset())

describe("the visual trimmer", () => {
  it("shimmers while the filmstrip builds, then shows the frames", async () => {
    setup({ building: 1 })
    expect(screen.getByTestId("filmstrip-loading")).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId("filmstrip").querySelectorAll("img").length).toBe(12), { timeout: 3000 })
    expect(screen.queryByTestId("filmstrip-loading")).toBeNull()
  })

  it("dragging the end shows the time and the length live, snaps to the beat, and saves like a typed trim", async () => {
    const { onTrim } = setup({ building: 0 })
    const up = drag("Trim end", 231)                   // 2.31 s: the end lands on the 1.5 s beat at 2.25 s
    expect(screen.getByTestId("handle-time").textContent).toBe("2.25s · beat")
    expect(screen.getByTestId("plays-for").textContent).toBe("plays for 1.25s")
    expect(handle("Trim end").getAttribute("aria-valuenow")).toBe("2.25")
    expect(screen.getByTestId("playhead-preview").querySelector("span")!.className).toContain("invisible")   // no double label
    expect(onTrim).not.toHaveBeenCalled()              // nothing saved mid-drag
    up()
    expect(onTrim).toHaveBeenCalledOnce()
    expect(onTrim).toHaveBeenCalledWith(1, 2.25)
    expect(screen.queryByTestId("handle-time")).toBeNull()
  })

  it("Alt drops it exactly where it is", () => {
    const { onTrim } = setup({ building: 0 })
    drag("Trim end", 231, { altKey: true })()
    expect(onTrim).toHaveBeenCalledWith(1, 2.31)
  })

  it("no beats to snap to when the edit doesn't cut on the beat", () => {
    const { onTrim } = setup({ building: 0, beatCut: false })
    drag("Trim end", 231)()
    expect(onTrim).toHaveBeenCalledWith(1, 2.31)
  })

  it("a handle stops at the minimum shot", () => {
    const { onTrim } = setup({ building: 0 })
    drag("Trim start", 299, { altKey: true })()        // try to drag the start onto the end
    expect(onTrim).toHaveBeenCalledWith(2.7, 3)
    expect(screen.getByTestId("plays-for").textContent).toBe("plays for 0.3s")
  })

  it("arrow keys nudge a handle and save", () => {
    const { onTrim } = setup({ building: 0 })
    fireEvent.keyDown(handle("Trim start"), { key: "ArrowRight" })
    expect(onTrim).toHaveBeenLastCalledWith(1.1, 3)
    fireEvent.keyDown(handle("Trim end"), { key: "ArrowLeft", shiftKey: true })
    expect(onTrim).toHaveBeenLastCalledWith(1.1, 2.5)
  })

  it("clicking the strip moves the playhead (and its frame preview), not the trim", async () => {
    const { onTrim } = setup({ building: 0 })
    await waitFor(() => expect(screen.getByTestId("filmstrip").querySelectorAll("img").length).toBe(12))
    const strip = screen.getByTestId("filmstrip")
    fireEvent.pointerDown(strip, { pointerId: 2, clientX: 420 })
    fireEvent.pointerMove(strip, { pointerId: 2, clientX: 455 })
    const preview = screen.getByTestId("playhead-preview")
    expect(preview.textContent).toBe("4.55s")
    expect(preview.querySelector("img")!.getAttribute("src")).toContain("f_010.jpg")    // nearest frame, 4.5 s
    fireEvent.pointerUp(strip, { pointerId: 2 })
    await waitFor(() => expect(preview.querySelector("img")!.getAttribute("src")).toContain("/media/thumbnail"))
    expect(preview.querySelector("img")!.getAttribute("src")).toContain("t=4.60")       // the exact frame at rest
    expect(onTrim).not.toHaveBeenCalled()
  })
})

describe("exact times (folded away by default)", () => {
  it("are hidden until asked for", () => {
    setup({ building: 0 })
    expect(screen.queryByLabelText("Start (s)")).toBeNull()
    openExact()
    expect(input("Start (s)").value).toBe("1")
    expect(input("End (s)").value).toBe("3")
    expect(input("Plays for (s)").value).toBe("2")
  })

  it("follow the handles while dragging", () => {
    setup({ building: 0 })
    openExact()
    drag("Trim end", 231)
    expect(input("End (s)").value).toBe("2.25")
    expect(input("Plays for (s)").value).toBe("1.25")
    expect(input("Start (s)").value).toBe("1")
  })

  it("move the handles as you type, and save the typed trim on Enter", () => {
    const { onTrim } = setup({ building: 0 })
    openExact()
    act(() => input("Start (s)").focus())
    fireEvent.change(input("Start (s)"), { target: { value: "1.5" } })
    expect(handle("Trim start").getAttribute("aria-valuenow")).toBe("1.5")
    expect(screen.getByTestId("plays-for").textContent).toBe("plays for 1.5s")
    expect(input("Start (s)").value).toBe("1.5")       // the field being typed in isn't rewritten
    fireEvent.keyDown(input("Start (s)"), { key: "Enter" })
    expect(onTrim).toHaveBeenCalledWith(1.5, 3)
  })

  it("plays-for moves the end handle and still sets the length exactly (as before)", () => {
    const { onTrim, onDuration } = setup({ building: 0 })
    openExact()
    act(() => input("Plays for (s)").focus())
    fireEvent.change(input("Plays for (s)"), { target: { value: "1.2" } })
    expect(handle("Trim end").getAttribute("aria-valuenow")).toBe("2.2")
    expect(input("End (s)").value).toBe("2.2")
    fireEvent.click(screen.getByRole("button", { name: "Set" }))
    expect(onDuration).toHaveBeenCalledWith(1.2)
    expect(onTrim).not.toHaveBeenCalled()
  })

  it("a typed time past the clip stops the handle at the end", () => {
    setup({ building: 0 })
    openExact()
    fireEvent.change(input("End (s)"), { target: { value: "9" } })
    expect(handle("Trim end").getAttribute("aria-valuenow")).toBe("6")
  })
})
