import { useEffect, useRef, useState } from "react"
import { mediaUrl, thumbUrl } from "@/api/client"
import { useFilmstrip } from "@/api/queries"
import { type Handle, moveHandle, playsFor, type Range, type SnapKind, snapPoints, timeAt, type TrimCtx } from "@/lib/trim"
import { cn } from "@/lib/utils"

const SNAP_PX = 8           // a handle within this many pixels of a snap point lands on it
const NUDGE = 0.1           // arrow keys move a handle this far (Shift: 0.5 s)
const fmt = (x: number) => `${(Math.round(x * 100) / 100).toFixed(x < 10 ? 2 : 1).replace(/0$/, "")}s`

/**
 * The visual trimmer: the whole clip as a filmstrip, two handles marking the part the shot uses (the rest dimmed), a
 * playhead with the frame under it. Handles snap to the clip's start / end and, in beat-cut edits, to the cuts that
 * land the shot's end on a beat; hold Alt for no snapping. `range` is the live (uncommitted) trim, shared with the
 * exact-time inputs; onCommit fires once per drag or nudge.
 */
export function Trimmer({
  pid,
  src,
  ctx,
  range,
  onChange,
  onCommit,
}: {
  pid: string
  src: string
  ctx: TrimCtx
  range: Range
  onChange: (r: Range) => void
  onCommit: (r: Range) => void
}) {
  const strip = useFilmstrip(pid, src)
  const track = useRef<HTMLDivElement>(null)
  const live = useRef(range)
  live.current = range
  const [drag, setDragState] = useState<Handle | "scrub" | null>(null)
  const dragging = useRef<Handle | "scrub" | null>(null)      // read by pointer handlers before React re-renders
  const setDrag = (d: Handle | "scrub" | null) => {
    dragging.current = d
    setDragState(d)
  }
  const [snapped, setSnapped] = useState<SnapKind | null>(null)
  const [play, setPlay] = useState(range.in)
  const start = useRef<Range>(range)

  // a new shot (or a committed trim from elsewhere): the playhead goes to its start
  useEffect(() => {
    if (!dragging.current) setPlay(range.in)
  }, [src, range.in])

  const D = ctx.clipDur
  const pct = (t: number) => `${(Math.max(0, Math.min(D, t)) / D) * 100}%`
  const at = (clientX: number) => {
    const r = track.current!.getBoundingClientRect()
    return { t: timeAt(clientX, r.left, r.width, D), tol: r.width > 0 ? (SNAP_PX / r.width) * D : 0 }
  }

  const grab = (h: Handle) => (e: React.PointerEvent) => {
    e.stopPropagation()
    e.preventDefault()
    ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
    start.current = live.current
    setDrag(h)
    setPlay(live.current[h])
  }
  const dragMove = (h: Handle) => (e: React.PointerEvent) => {
    if (dragging.current !== h) return
    const { t, tol } = at(e.clientX)
    const res = moveHandle(h, t, live.current, ctx, { snap: !e.altKey, tolerance: tol })
    setSnapped(res.snapped)
    setPlay(res.range[h])
    live.current = res.range
    onChange(res.range)
  }
  const release = (e: React.PointerEvent) => {
    ;(e.currentTarget as Element).releasePointerCapture?.(e.pointerId)
    const was = start.current
    const now = live.current
    setDrag(null)
    setSnapped(null)
    if (now.in !== was.in || now.out !== was.out) onCommit(now)
  }
  const nudge = (h: Handle) => (e: React.KeyboardEvent) => {
    const step = (e.shiftKey ? 5 : 1) * NUDGE * (e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0)
    if (!step) return
    e.preventDefault()
    const res = moveHandle(h, live.current[h] + step, live.current, ctx, { snap: false, tolerance: 0 })
    if (res.range[h] === live.current[h]) return
    setPlay(res.range[h])
    onChange(res.range)
    onCommit(res.range)
  }
  const scrub = (e: React.PointerEvent) => {
    if (e.type === "pointerdown") {
      ;(e.currentTarget as Element).setPointerCapture?.(e.pointerId)
      setDrag("scrub")
    } else if (dragging.current !== "scrub") return
    setPlay(at(e.clientX).t)
  }

  const frames = strip.data?.status === "ready" ? (strip.data.frames ?? []) : []
  const nearest = frames.length ? frames.reduce((a, f) => (Math.abs(f.t - play) < Math.abs(a.t - play) ? f : a)) : null
  // while moving: the nearest strip frame (instant); at rest: the exact frame
  const preview = drag || !nearest ? nearest && mediaUrl(nearest.path) : thumbUrl(`${pid}/${src}`, 160, Math.round(play * 10) / 10)
  const beats = ctx.beats.length ? snapPoints("out", range, ctx).filter((p) => p.kind === "beat") : []
  const kept = playsFor(range, ctx.speed)
  const handleCls = "absolute top-0 z-20 flex h-full w-3.5 cursor-ew-resize touch-none items-center justify-center bg-accent outline-none focus-visible:ring-2 focus-visible:ring-ink"

  return (
    <div className="select-none" data-testid="trimmer">
      {/* the frame under the playhead */}
      <div className="relative mb-1.5 h-[92px]">
        <div
          className="absolute bottom-0 z-30 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `clamp(28px, ${pct(play)}, calc(100% - 28px))` }}
          data-testid="playhead-preview"
        >
          <div className="h-[74px] w-[42px] overflow-hidden rounded-md bg-surface-2 shadow-soft ring-1 ring-ink/15">
            {preview && (
              <img
                src={preview}
                alt=""
                draggable={false}
                className="size-full object-cover"
                onError={(e) => nearest && ((e.currentTarget as HTMLImageElement).src = mediaUrl(nearest.path))}
              />
            )}
          </div>
          {/* while a handle moves, its own label says the time (they'd sit on top of each other) */}
          <span className={cn("mt-0.5 font-mono text-[10.5px] text-muted-foreground", (drag === "in" || drag === "out") && "invisible")}>{fmt(play)}</span>
        </div>
      </div>

      <div
        ref={track}
        className="relative h-14 cursor-pointer touch-none overflow-visible rounded-lg bg-surface-2"
        onPointerDown={scrub}
        onPointerMove={scrub}
        onPointerUp={() => dragging.current === "scrub" && setDrag(null)}
        data-testid="filmstrip"
      >
        {/* the frames */}
        <div className="absolute inset-0 flex overflow-hidden rounded-lg">
          {frames.length
            ? frames.map((f) => <img key={f.path} src={mediaUrl(f.path)} alt="" draggable={false} className="h-full min-w-0 flex-1 object-cover" />)
            : strip.data?.status !== "failed" && <div className="size-full animate-pulse bg-gradient-to-r from-ink/[0.04] via-ink/[0.09] to-ink/[0.04]" data-testid="filmstrip-loading" />}
          {strip.data?.status === "failed" && (
            <div className="grid size-full place-items-center px-3 text-center text-[11.5px] text-muted-foreground">No filmstrip for this clip: use exact times below.</div>
          )}
        </div>

        {/* trimmed off: dimmed */}
        <div className="pointer-events-none absolute inset-y-0 left-0 rounded-l-lg bg-ink/60" style={{ width: pct(range.in) }} />
        <div className="pointer-events-none absolute inset-y-0 right-0 rounded-r-lg bg-ink/60" style={{ left: pct(range.out) }} />
        {/* the part the shot uses */}
        <div className="pointer-events-none absolute inset-y-0 border-y-[3px] border-accent" style={{ left: pct(range.in), right: `calc(100% - ${pct(range.out)})` }}>
          <span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink/75 px-2 py-0.5 text-[10.5px] font-medium whitespace-nowrap text-surface" data-testid="plays-for">
            plays for {fmt(kept)}
          </span>
        </div>

        {/* beats the end can land on */}
        {beats.map((b) => (
          <span key={b.t} className="pointer-events-none absolute -bottom-1.5 h-1.5 w-px bg-warn" style={{ left: pct(b.t) }} />
        ))}

        {/* playhead */}
        <div className="pointer-events-none absolute -inset-y-1 z-10 w-0.5 -translate-x-1/2 rounded bg-surface shadow-[0_0_0_1px_rgba(0,0,0,0.35)]" style={{ left: pct(play) }} />

        {(["in", "out"] as const).map((h) => (
          <div
            key={h}
            role="slider"
            tabIndex={0}
            aria-label={h === "in" ? "Trim start" : "Trim end"}
            aria-valuemin={0}
            aria-valuemax={Math.round(D * 100) / 100}
            aria-valuenow={range[h]}
            aria-valuetext={fmt(range[h])}
            className={cn(handleCls, h === "in" ? "-translate-x-full rounded-l-lg" : "rounded-r-lg")}
            style={{ left: pct(range[h]) }}
            onPointerDown={grab(h)}
            onPointerMove={dragMove(h)}
            onPointerUp={release}
            onPointerCancel={release}
            onKeyDown={nudge(h)}
          >
            <span className="h-5 w-0.5 rounded bg-accent-ink/60" />
            {drag === h && (
              <span className="absolute -top-6 left-1/2 -translate-x-1/2 rounded-md bg-ink px-1.5 py-0.5 font-mono text-[10.5px] whitespace-nowrap text-surface" data-testid="handle-time">
                {fmt(range[h])}
                {snapped === "beat" ? " · beat" : snapped ? ` · ${snapped}` : ""}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-subtle">
        <span>0s</span>
        <span>{ctx.beats.length ? "Snaps to the beat · hold Alt for fine control" : "Snaps to the clip's ends · hold Alt for fine control"}</span>
        <span>{fmt(D)}</span>
      </div>
    </div>
  )
}
