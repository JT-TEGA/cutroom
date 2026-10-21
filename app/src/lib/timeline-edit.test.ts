// The plan screen's own edits: length (trim / seconds), text on a shot, captions per part and the end card. Each one
// returns a new plan, never touches the input, and refuses (throws a message) rather than save one that can't render.
import { describe, expect, it } from "vitest"
import type { Timeline } from "@/api/types"
import { addText, lengthMode, setCaptions, setDuration, setEndCard, trimShot } from "./timeline-edit"

const plan = (): Timeline =>
  ({
    segments: [
      { src: "inputs/clips/talk.mp4", in: 1, out: 4, talk: true, label: "hook" },
      { src: "inputs/clips/bench.mp4", beats: 2, to: "drop" },
      { src: "inputs/photos/fit.jpg", type: "image", dur: 2 },
      {
        type: "vo",
        src: "inputs/voiceover/vo.wav",
        shots: [
          { src: "inputs/clips/a.mp4", in: 0 },
          { src: "inputs/clips/b.mp4", cue: "four sets", at: 2 },
          { src: "inputs/clips/c.mp4" },
        ],
      },
    ],
    text: [{ text: "5AM", style: "sticker", on: "hook" }],
    captions: { enabled: true, replace: {}, hide: [] },
    end_card: null,
  }) as unknown as Timeline

describe("length", () => {
  it("trims a clip and lets the trim set the length", () => {
    const tl = plan()
    const out = trimShot(tl, 1, null, 0.5, 2.25, { clipDur: 10 })
    expect(out.segments[1]).toMatchObject({ in: 0.5, out: 2.25 })
    expect(out.segments[1]).not.toHaveProperty("beats")
    expect(out.segments[1]).not.toHaveProperty("to")
    expect(tl.segments[1]).toMatchObject({ beats: 2 })            // the input is untouched
  })

  it("refuses a trim that can't render", () => {
    expect(() => trimShot(plan(), 0, null, 2, 12, { clipDur: 8 })).toThrow("only 8.0 s long")
    expect(() => trimShot(plan(), 0, null, 3, 3.1, { clipDur: 8 })).toThrow("at least")
    expect(() => trimShot(plan(), 0, null, -1, 2, { clipDur: 8 })).toThrow("before the start")
    expect(() => trimShot(plan(), 2, null, 0, 1)).toThrow("Only clips")
  })

  it("sets a length in seconds, within what's left of the clip", () => {
    const out = setDuration(plan(), 0, null, 1.5, { clipDur: 8 })
    expect(out.segments[0]).toMatchObject({ in: 1, dur: 1.5 })
    expect(out.segments[0]).not.toHaveProperty("out")
    expect(() => setDuration(plan(), 0, null, 9, { clipDur: 8 })).toThrow("only has 7.0 s left")
    expect(() => setDuration(plan(), 0, null, 0.1, { clipDur: 8 })).toThrow("at least")
    expect(setDuration(plan(), 2, null, 3.2).segments[2]).toMatchObject({ dur: 3.2 })   // a photo: no clip to run out of
  })

  it("trims B-roll under a voiceover: the part of the clip it uses, and how long it plays", () => {
    const shots = trimShot(plan(), 3, 1, 1.5, 2.7, { clipDur: 6, blockAt: 2.35 }).segments[3].shots!
    expect(shots[1]).toMatchObject({ in: 1.5, at: 2.35 })
    expect(shots[2]).toMatchObject({ at: 3.55 })
    expect(() => trimShot(plan(), 3, 2, 0, 1, { blockAt: 4 })).toThrow("Only clips")     // the last one: no
  })

  it("gives B-roll under a voiceover exactly that length: its start stays, the next shot starts after it", () => {
    const out = setDuration(plan(), 3, 1, 1.4, { clipDur: 6, blockAt: 2.35 })
    const shots = out.segments[3].shots!
    expect(shots[1]).toMatchObject({ at: 2.35 })            // pinned where it was (its cue put it there)
    expect(shots[1]).not.toHaveProperty("cue")
    expect(shots[2]).toMatchObject({ at: 3.75 })
    expect(shots[0]).toEqual({ src: "inputs/clips/a.mp4", in: 0 })   // nothing before it changes
    const first = setDuration(plan(), 3, 0, 2, { blockAt: 0 }).segments[3].shots!
    expect(first[0]).not.toHaveProperty("at")               // the first shot always opens the part
    expect(first[1]).toMatchObject({ at: 2 })
    expect(lengthMode(plan(), 3, 2)).toMatchObject({ dur: false })   // the last one runs to the end of the voiceover
    expect(() => setDuration(plan(), 3, 2, 1, { blockAt: 4 })).toThrow("end of the voiceover")
    expect(() => setDuration(plan(), 3, null, 1)).toThrow("as long as what's said")
    expect(() => setDuration(plan(), 3, 0, 9, { clipDur: 6, blockAt: 0 })).toThrow("only has 6.0 s left")
  })
})

describe("text on a shot", () => {
  it("anchors new text to the shot, labelling it if it has no label yet", () => {
    const { timeline, index } = addText(plan(), { segment: 1, shot: null, idx: 2, duration: 2 }, { text: "  Incline bench " })
    expect(index).toBe(1)
    expect(timeline.segments[1].label).toBe("shot-2")
    expect(timeline.text![1]).toEqual({ text: "Incline bench", style: "label", on: "shot-2" })
  })

  it("reuses an existing label and keeps short shots' text readable", () => {
    const { timeline } = addText(plan(), { segment: 0, shot: null, idx: 1, duration: 0.8 }, { text: "Day 1", style: "card" })
    expect(timeline.text![1]).toEqual({ text: "Day 1", style: "card", on: "hook", dur: 2.5 })
    const vo = addText(plan(), { segment: 3, shot: 1, idx: 5, duration: 1 }, { text: "4 × 10" }).timeline
    expect(vo.segments[3].shots![1]).toMatchObject({ label: "shot-5" })
    expect(vo.text![1]).toMatchObject({ on: "shot-5", dur: 1.2 })
  })

  it("refuses empty text", () => {
    expect(() => addText(plan(), { segment: 0, idx: 1, duration: 3 }, { text: "  " })).toThrow("Type the text")
  })
})

describe("captions and end card", () => {
  it("turns captions off and back on for one part", () => {
    const off = setCaptions(plan(), 0, false)
    expect(off.segments[0].captions).toBe(false)
    expect(setCaptions(off, 0, true).segments[0]).not.toHaveProperty("captions")
  })

  it("turns the end card on or off for the video", () => {
    expect(setEndCard(plan(), true).end_card).toEqual({ enabled: true })
    const tl = { ...plan(), end_card: { enabled: true, seconds: 2 } } as Timeline
    expect(setEndCard(tl, false).end_card).toEqual({ enabled: false, seconds: 2 })
  })
})
