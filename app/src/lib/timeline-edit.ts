import type { ProjectFile, Segment, Shot, TextOverlay, Timeline, TimelineView } from "@/api/types"

/** Edits the creator makes on the timeline screen. Each returns a new Timeline (the input is never mutated). */

const ANCHORED = ["text", "broll", "graphics", "sfx", "flash"] as const
type Anchored = { on?: string | null; [k: string]: unknown }

const clone = <T,>(x: T): T => structuredClone(x)

function lists(tl: Timeline): Anchored[][] {
  const t = tl as unknown as Record<string, unknown>
  return ANCHORED.map((k) => (Array.isArray(t[k]) ? (t[k] as Anchored[]) : [])).map((l) => l.filter((x) => x && typeof x === "object"))
}

function labelsIn(tl: Timeline): Set<string> {
  const out = new Set<string>()
  for (const s of tl.segments) {
    if (s.label) out.add(s.label)
    for (const sh of s.shots ?? []) if ((sh as Shot & { label?: string }).label) out.add((sh as Shot & { label?: string }).label!)
  }
  return out
}

function target(tl: Timeline, seg: number, shot: number | null | undefined): (Segment | Shot) & { label?: string | null } {
  const s = tl.segments[seg]
  return (shot != null && s.shots ? s.shots[shot] : s) as (Segment | Shot) & { label?: string | null }
}

/**
 * "#3" anchors mean "the 3rd shot", which breaks as soon as shots move. Give those shots a label and anchor to it,
 * so labels and stickers travel with their shot.
 */
export function pinAnchors(tl: Timeline, view: TimelineView): Timeline {
  const out = clone(tl)
  const used = labelsIn(out)
  for (const list of lists(out)) {
    for (const x of list) {
      const m = typeof x.on === "string" ? /^#(\d+)$/.exec(x.on) : null
      if (!m) continue
      const shot = view.shots.find((s) => s.idx === Number(m[1]))
      if (!shot) continue
      const t = target(out, shot.segment, shot.shot)
      if (!t.label) {
        let name = `shot-${shot.idx}`
        for (let n = 2; used.has(name); n++) name = `shot-${shot.idx}-${n}`
        t.label = name
        used.add(name)
      }
      x.on = t.label
    }
  }
  return out
}

export function moveSegment(tl: Timeline, from: number, to: number): Timeline {
  const out = clone(tl)
  const [s] = out.segments.splice(from, 1)
  out.segments.splice(to, 0, s)
  return out
}

/** Remove a shot (a whole segment, or one B-roll shot of a voiceover block). Overlays anchored to it go too. */
export function deleteShot(tl: Timeline, seg: number, shot: number | null | undefined): { timeline: Timeline; removed: number } {
  const out = clone(tl)
  const s = out.segments[seg]
  const gone = new Set<string>()
  if (shot != null && s.shots && s.shots.length > 1) {
    const [sh] = s.shots.splice(shot, 1)
    const l = (sh as Shot & { label?: string }).label
    if (l) gone.add(l)
  } else {
    if (out.segments.length <= 1) throw new Error("A plan needs at least one shot.")
    const [x] = out.segments.splice(seg, 1)
    if (x.label) gone.add(x.label)
    for (const sh of x.shots ?? []) if ((sh as Shot & { label?: string }).label) gone.add((sh as Shot & { label?: string }).label!)
  }
  let removed = 0
  const t = out as unknown as Record<string, Anchored[] | undefined>
  for (const k of ANCHORED) {
    const l = t[k]
    if (!Array.isArray(l)) continue
    const keep = l.filter((x) => !(typeof x?.on === "string" && gone.has(x.on)))
    removed += l.length - keep.length
    t[k] = keep
  }
  return { timeline: out, removed }
}

/** Put another uploaded clip / photo in a shot's place, keeping its length where the new clip allows. */
export function swapSource(tl: Timeline, seg: number, shot: number | null | undefined, file: ProjectFile): Timeline {
  const out = clone(tl)
  const t = target(out, seg, shot) as Record<string, unknown>
  const len = typeof t.in === "number" && typeof t.out === "number" ? (t.out as number) - (t.in as number) : null
  t.src = file.path
  t.reason = "Swapped in by you"
  if (file.kind === "photo") {
    t.type = "image"
    delete t.in
    delete t.out
  } else {
    if (t.type === "image") delete t.type
    t.in = 0
    if (len != null) t.out = Math.round(Math.min(len, file.duration ?? len) * 1000) / 1000
    else delete t.out
  }
  delete t.ramp
  return out
}

export function setTransition(tl: Timeline, seg: number, shot: number | null | undefined, tr: string | null): Timeline {
  const out = clone(tl)
  const t = target(out, seg, shot) as Record<string, unknown>
  if (tr) t.transition = tr
  else delete t.transition
  return out
}

export function updateText(tl: Timeline, index: number, patch: Partial<TextOverlay>): Timeline {
  const out = clone(tl)
  const list = (out.text ?? []) as TextOverlay[]
  list[index] = { ...list[index], ...patch }
  for (const [k, v] of Object.entries(patch)) if (v === "" || v == null) delete (list[index] as Record<string, unknown>)[k]
  out.text = list
  return out
}

export function deleteText(tl: Timeline, index: number): Timeline {
  const out = clone(tl)
  out.text = (out.text ?? []).filter((_, i) => i !== index)
  return out
}

// ---------------------------------------------------------------- length, text on a shot, captions, end card

/** Shortest shot the editor lets you set (the renderer needs a few frames; B-roll reads best at 1 s+). */
export const MIN_SHOT = 0.3
/** Text stays up long enough to read: labels 1.2 s, cards 2.5 s. */
export const minTextDur = (style?: string | null) => (style === "card" ? 2.5 : 1.2)

const r3 = (x: number) => Math.round(x * 1000) / 1000
const isImage = (t: Record<string, unknown>) => t.type === "image" || (typeof t.src === "string" && /\.(jpe?g|png|heic|heif|webp|gif|tiff?)$/i.test(t.src))
const isClip = (t: Record<string, unknown>) => (t.type == null || t.type === "clip") && !isImage(t)

/** What a shot's length can be changed with: "trim" (in/out of the clip), "dur" (output seconds), or nothing. */
export function lengthMode(tl: Timeline, seg: number, shot: number | null | undefined): { trim: boolean; dur: boolean; why?: string } {
  const s = tl.segments[seg]
  if (shot == null && s.type === "vo") return { trim: false, dur: false, why: "A voiceover part is as long as what's said: change the B-roll shots in it." }
  if (shot != null) {
    if (shot >= (s.shots?.length ?? 0) - 1) return { trim: false, dur: false, why: "The last shot runs to the end of the voiceover." }
    return { trim: isClip(s.shots![shot] as Record<string, unknown>), dur: true }
  }
  return { trim: isClip(s as Record<string, unknown>), dur: true }
}

/**
 * Trim a clip shot to [inS, outS] of the source. A shot of its own then follows the clip (snapped to the beat when
 * there's music); B-roll under a voiceover uses the clip from inS and plays for (outS - inS) / speed, its start in
 * the voiceover staying put (see setDuration). clipDur: the source's length, so a trim can't run past the end.
 */
export function trimShot(
  tl: Timeline,
  seg: number,
  shot: number | null | undefined,
  inS: number,
  outS: number,
  opts: { clipDur?: number | null; blockAt?: number } = {},
): Timeline {
  if (!lengthMode(tl, seg, shot).trim) throw new Error("Only clips can be trimmed: set a length instead.")
  if (!(inS >= 0)) throw new Error("The start can't be before the start of the clip.")
  if (opts.clipDur != null && outS > opts.clipDur + 0.05) throw new Error(`The clip is only ${opts.clipDur.toFixed(1)} s long.`)
  const t0 = target(tl, seg, shot) as Record<string, unknown>
  const speed = typeof t0.speed === "number" ? t0.speed : 1
  if (!(outS - inS >= MIN_SHOT * speed - 1e-6)) throw new Error(`A shot needs at least ${MIN_SHOT} s of the clip.`)
  if (shot != null) {
    const moved = clone(tl)
    ;(target(moved, seg, shot) as Record<string, unknown>).in = r3(inS)
    return setDuration(moved, seg, shot, r3((outS - inS) / speed), opts)
  }
  const out = clone(tl)
  const t = out.segments[seg] as Record<string, unknown>
  t.in = r3(inS)
  t.out = r3(outS)
  for (const k of ["dur", "beats", "to"]) delete t[k]
  return out
}

/**
 * Set a shot's length in output seconds. A clip keeps its start and plays on from it. B-roll under a voiceover keeps
 * its start (pinned with "at", seconds into the voiceover part: blockAt) and the next shot starts exactly `dur` later
 * instead of on its cue, so nothing before it moves.
 */
export function setDuration(
  tl: Timeline,
  seg: number,
  shot: number | null | undefined,
  dur: number,
  opts: { clipDur?: number | null; blockAt?: number } = {},
): Timeline {
  const mode = lengthMode(tl, seg, shot)
  if (!mode.dur) throw new Error(mode.why ?? "This shot's length can't be changed.")
  if (!(dur >= MIN_SHOT)) throw new Error(`A shot needs to be at least ${MIN_SHOT} s.`)
  if (dur > 60) throw new Error("A shot can be at most 60 s.")
  const out = clone(tl)
  const t = target(out, seg, shot) as Record<string, unknown>
  if (isClip(t) && opts.clipDur != null) {
    const start = typeof t.in === "number" ? t.in : 0
    const speed = typeof t.speed === "number" ? t.speed : 1
    if (start + dur * speed > opts.clipDur + 0.05)
      throw new Error(`The clip only has ${((opts.clipDur - start) / speed).toFixed(1)} s left from this shot's start: trim its start earlier or pick another clip.`)
  }
  if (shot == null) {
    t.dur = r3(dur)
    for (const k of ["out", "beats", "to"]) delete t[k]
    return out
  }
  if (opts.blockAt == null) throw new Error("Where this shot starts in the voiceover is needed to change its length.")
  const next = out.segments[seg].shots![shot + 1] as Record<string, unknown>
  if (shot > 0) {
    t.at = r3(opts.blockAt)
    delete t.cue
  }
  delete t.dur
  next.at = r3(opts.blockAt + dur)
  delete next.cue
  return out
}

/** Add text on a shot, anchored to it (it moves with the shot), up for the whole shot or at least readable. */
export function addText(
  tl: Timeline,
  at: { segment: number; shot?: number | null; idx: number; duration: number },
  item: { text: string; style?: string | null; sub?: string | null },
): { timeline: Timeline; index: number } {
  const text = item.text.trim()
  if (!text) throw new Error("Type the text first.")
  const out = clone(tl)
  const t = target(out, at.segment, at.shot)
  if (!t.label) {
    const used = labelsIn(out)
    let name = `shot-${at.idx}`
    for (let n = 2; used.has(name); n++) name = `shot-${at.idx}-${n}`
    t.label = name
  }
  const style = item.style || "label"
  const x: TextOverlay = { text, style, on: t.label }
  if (item.sub?.trim()) x.sub = item.sub.trim()
  if (at.duration < minTextDur(style)) x.dur = minTextDur(style)
  out.text = [...(out.text ?? []), x]
  return { timeline: out, index: out.text.length - 1 }
}

/** Captions on or off for one segment (a voiceover part counts as one: its B-roll shots share its captions). */
export function setCaptions(tl: Timeline, seg: number, on: boolean): Timeline {
  const out = clone(tl)
  const s = out.segments[seg] as Record<string, unknown>
  if (on) delete s.captions
  else s.captions = false
  return out
}

/** The handle end card on or off for the whole video. */
export function setEndCard(tl: Timeline, on: boolean): Timeline {
  const out = clone(tl)
  out.end_card = { ...(out.end_card ?? {}), enabled: on }
  return out
}
