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
