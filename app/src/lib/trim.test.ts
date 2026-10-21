// The visual trimmer's maths: dragging a handle gives the same plan as typing the numbers, handles snap to the clip's
// ends and to beats (not with Alt), and never get closer than the minimum shot.
import { describe, expect, it } from "vitest"
import type { Timeline } from "@/api/types"
import { MIN_SHOT, trimShot } from "./timeline-edit"
import { clampRange, moveHandle, playsFor, snapPoints, timeAt, type TrimCtx, withPlaysFor } from "./trim"

const ctx = (over: Partial<TrimCtx> = {}): TrimCtx => ({ clipDur: 6, speed: 1, shotStart: 0.25, beats: [], ...over })
const SNAP = { snap: true, tolerance: 0.1 }
const FREE = { snap: false, tolerance: 0.1 }

const plan = (): Timeline =>
  ({
    segments: [
      { src: "inputs/clips/talk.mp4", in: 0, out: 1, talk: true },
      { src: "inputs/clips/bench.mp4", beats: 2 },
    ],
    text: [],
    captions: { enabled: true, replace: {}, hide: [] },
  }) as unknown as Timeline

describe("dragging = typing", () => {
  it("a drag saves the same plan the number inputs save", () => {
    const r0 = { in: 1, out: 3 }
    const a = moveHandle("in", 1.37, r0, ctx(), FREE).range
    const b = moveHandle("out", 2.64, a, ctx(), FREE).range
    expect(b).toEqual({ in: 1.37, out: 2.64 })
    const dragged = trimShot(plan(), 1, null, b.in, b.out, { clipDur: 6 })
    const typed = trimShot(plan(), 1, null, 1.37, 2.64, { clipDur: 6 })
    expect(dragged).toEqual(typed)
    expect(dragged.segments[1]).toMatchObject({ in: 1.37, out: 2.64 })
    expect(dragged.segments[1]).not.toHaveProperty("beats")
  })

  it("plays-for and in/out are the same thing at the shot's speed", () => {
    expect(playsFor({ in: 1, out: 2.9 }, 1)).toBe(1.9)
    expect(playsFor({ in: 1, out: 4 }, 2)).toBe(1.5)
    expect(withPlaysFor({ in: 1, out: 2 }, 1.5, ctx())).toEqual({ in: 1, out: 2.5 })
    expect(withPlaysFor({ in: 1, out: 2 }, 1.5, ctx({ speed: 2 }))).toEqual({ in: 1, out: 4 })
    expect(withPlaysFor({ in: 5, out: 5.5 }, 3, ctx())).toEqual({ in: 5, out: 6 })      // not past the clip
  })

  it("maps the pointer to the clip", () => {
    expect(timeAt(150, 0, 300, 6)).toBe(3)
    expect(timeAt(-20, 0, 300, 6)).toBe(0)
    expect(timeAt(999, 0, 300, 6)).toBe(6)
  })
})

describe("snapping", () => {
  // 120 BPM from 0: beats every 0.5 s of the edit; the shot starts at 0.25 s
  const beats = [0, 0.5, 1, 1.5, 2, 2.5, 3]

  it("lands the shot's end on the nearest beat", () => {
    const c = ctx({ beats })
    // end at in + (beat - shotStart): 1 + 1.25 = 2.25 for the beat at 1.5 s
    const r = moveHandle("out", 2.31, { in: 1, out: 3 }, c, SNAP)
    expect(r).toEqual({ range: { in: 1, out: 2.25 }, snapped: "beat" })
    const end = 0.25 + playsFor(r.range, 1)
    expect(beats).toContain(end)
    // the start handle keeps the end where it is, so it snaps to out - (beat - shotStart)
    const s = moveHandle("in", 0.8, { in: 1, out: 3 }, c, SNAP)
    expect(s).toEqual({ range: { in: 0.75, out: 3 }, snapped: "beat" })
    expect(beats).toContain(0.25 + playsFor(s.range, 1))
  })

  it("counts beats at the shot's speed", () => {
    const r = moveHandle("out", 3.45, { in: 1, out: 4 }, ctx({ beats, speed: 2 }), SNAP)
    expect(r.range.out).toBe(3.5)                     // 1.25 s of the edit at 2x = 2.5 s of the clip
    expect(0.25 + playsFor(r.range, 2)).toBe(1.5)
  })

  it("snaps to the clip's start and end", () => {
    expect(moveHandle("in", 0.06, { in: 1, out: 3 }, ctx(), SNAP)).toEqual({ range: { in: 0, out: 3 }, snapped: "start" })
    expect(moveHandle("out", 5.93, { in: 1, out: 3 }, ctx(), SNAP)).toEqual({ range: { in: 1, out: 6 }, snapped: "end" })
  })

  it("holding Alt (no snapping) leaves it where it's dropped", () => {
    expect(moveHandle("out", 2.31, { in: 1, out: 3 }, ctx({ beats }), FREE)).toEqual({ range: { in: 1, out: 2.31 }, snapped: null })
  })

  it("only offers beats inside the clip, after the shot starts", () => {
    const pts = snapPoints("out", { in: 4, out: 5 }, ctx({ beats, shotStart: 1.2 }))
    expect(pts.filter((p) => p.kind === "beat").map((p) => p.t)).toEqual([4.3, 4.8, 5.3, 5.8])
  })
})

describe("the minimum", () => {
  it("a handle can't cross the other closer than the minimum shot", () => {
    expect(moveHandle("out", 1.05, { in: 1, out: 3 }, ctx(), FREE).range).toEqual({ in: 1, out: 1 + MIN_SHOT })
    expect(moveHandle("in", 2.95, { in: 1, out: 3 }, ctx(), FREE).range).toEqual({ in: 3 - MIN_SHOT, out: 3 })
    expect(moveHandle("out", 0, { in: 1, out: 3 }, ctx({ speed: 2 }), FREE).range).toEqual({ in: 1, out: 1 + 2 * MIN_SHOT })
  })

  it("a snap point inside the minimum doesn't count as snapped", () => {
    // a beat would put the end 0.1 s after the start: it stops at the minimum instead
    const r = moveHandle("out", 1.1, { in: 1, out: 3 }, ctx({ beats: [0.35], shotStart: 0.25 }), SNAP)
    expect(r).toEqual({ range: { in: 1, out: 1.3 }, snapped: null })
  })

  it("keeps the range inside the clip", () => {
    expect(clampRange({ in: -1, out: 9 }, ctx(), "out")).toEqual({ in: 0, out: 6 })
    expect(clampRange({ in: 5.9, out: 6 }, ctx(), "in")).toEqual({ in: 5.7, out: 6 })
  })

  it("what the trimmer allows, the saved trim accepts", () => {
    const r = moveHandle("out", 0, { in: 1, out: 3 }, ctx(), FREE).range
    expect(() => trimShot(plan(), 1, null, r.in, r.out, { clipDur: 6 })).not.toThrow()
  })
})
