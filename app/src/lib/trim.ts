import { MIN_SHOT } from "./timeline-edit"

/**
 * The visual trimmer's maths, in source seconds (where in the clip). Dragging a handle and typing a number both end
 * up here, so they give the same in / out and the same saved plan.
 */

export type Range = { in: number; out: number }
export type Handle = "in" | "out"
export type SnapKind = "start" | "end" | "beat"

export type TrimCtx = {
  /** the clip's length */
  clipDur: number
  /** playback speed of the shot (2 = the clip runs twice as fast, so a second of output uses two of the clip) */
  speed: number
  /** where the shot starts in the edit (output seconds): a beat at output time b means a cut at b - shotStart */
  shotStart: number
  /** the music's beats in output seconds, when the edit cuts on the beat (else empty) */
  beats: number[]
}

const r3 = (x: number) => Math.round(x * 1000) / 1000

/** The least of the clip a shot can use: the minimum shot length, at the shot's speed. */
export const minLen = (ctx: TrimCtx) => MIN_SHOT * ctx.speed

/** How long the shot plays for, in output seconds. */
export const playsFor = (r: Range, speed: number) => r3((r.out - r.in) / speed)

/** The range a "plays for" length gives: same start, the end moves (never past the end of the clip). */
export function withPlaysFor(r: Range, dur: number, ctx: TrimCtx): Range {
  return clampRange({ in: r.in, out: r.in + dur * ctx.speed }, ctx, "out")
}

/** Keep a range inside the clip and at least the minimum long, moving only the handle that was changed. */
export function clampRange(r: Range, ctx: TrimCtx, moved: Handle): Range {
  const m = minLen(ctx)
  let a = Math.max(0, Math.min(r.in, ctx.clipDur - m))
  let b = Math.min(ctx.clipDur, Math.max(r.out, m))
  if (b - a < m) {
    if (moved === "in") a = b - m
    else b = a + m
  }
  return { in: r3(Math.max(0, a)), out: r3(Math.min(ctx.clipDur, b)) }
}

/** Where a handle can snap to: the clip's start or end, and (beat-cut edits) the cuts that land the shot's end on a
 * beat. The shot's start stays where it is in the edit, so its end is shotStart + (out - in) / speed. */
export function snapPoints(handle: Handle, r: Range, ctx: TrimCtx): { t: number; kind: SnapKind }[] {
  const pts: { t: number; kind: SnapKind }[] = [
    { t: 0, kind: "start" },
    { t: ctx.clipDur, kind: "end" },
  ]
  for (const b of ctx.beats) {
    const len = (b - ctx.shotStart) * ctx.speed
    if (len <= 0) continue
    const t = handle === "out" ? r.in + len : r.out - len
    if (t >= 0 && t <= ctx.clipDur) pts.push({ t: r3(t), kind: "beat" })
  }
  return pts
}

/**
 * Move a handle to t (source seconds). With snapping on, it lands on the nearest snap point within `tolerance`
 * seconds; it never crosses the other handle closer than the minimum, nor leaves the clip.
 */
export function moveHandle(
  handle: Handle,
  t: number,
  r: Range,
  ctx: TrimCtx,
  opts: { snap: boolean; tolerance: number },
): { range: Range; snapped: SnapKind | null } {
  let target = t
  let snapped: SnapKind | null = null
  if (opts.snap) {
    let best = opts.tolerance
    for (const p of snapPoints(handle, r, ctx)) {
      const d = Math.abs(p.t - t)
      if (d <= best) {
        best = d
        target = p.t
        snapped = p.kind
      }
    }
  }
  const next = clampRange(handle === "in" ? { in: target, out: r.out } : { in: r.in, out: target }, ctx, handle)
  // clamping moved it off the snap point (it would have crossed the minimum): it didn't snap
  if (snapped && Math.abs(next[handle] - target) > 0.001) snapped = null
  return { range: next, snapped }
}

/** Source seconds under a pointer at clientX, for a strip spanning [left, left + width]. */
export function timeAt(clientX: number, left: number, width: number, clipDur: number): number {
  if (width <= 0) return 0
  return Math.max(0, Math.min(clipDur, ((clientX - left) / width) * clipDur))
}
