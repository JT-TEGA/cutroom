import { useDroppable } from "@dnd-kit/core"
import { horizontalListSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { AlertTriangle, AudioLines, Film, Music2, Repeat2, Type, Wind, Zap, ZoomIn } from "lucide-react"
import { useMemo } from "react"
import type { ResolvedOverlay, ResolvedShot, TimelineView } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { basename, clock, tc } from "@/lib/format"
import { cn } from "@/lib/utils"

export type Selection = { type: "shot"; idx: number } | { type: "overlay"; kind: string; index: number } | null
/** The stretch of the edit on screen: the selected label, or the shot in the monitor. */
export type Span = { start: number; end: number }

const TRANSITION_ICON: Record<string, typeof Zap> = { flash: Zap, whip: Wind, zoom: ZoomIn }
export const SHOT_H = 86
const GUTTER = 16

export function shotSrc(view: TimelineView, s: ResolvedShot): string | null {
  if (s.src) return s.src
  const seg = view.timeline.segments[s.segment] as { a?: { src?: string | null } }
  return seg?.a?.src ?? null
}

/** Where to take a shot's thumbnail from: a third of the way into what is used. */
export const thumbTime = (s: ResolvedShot) => (s.kind === "clip" ? s.in + (s.out - s.in) * 0.3 : null)

function ShotBlock({
  s,
  pid,
  view,
  pps,
  selected,
  onSelect,
}: {
  s: ResolvedShot
  pid: string
  view: TimelineView
  pps: number
  selected: boolean
  onSelect: () => void
}) {
  const drop = useDroppable({ id: `shot-${s.idx}`, data: { type: "shot", segment: s.segment, shot: s.shot, idx: s.idx } })
  const w = s.duration * pps                      // exact, so overlays and sound line up with the shots
  const src = shotSrc(view, s)
  const Tr = s.transition ? TRANSITION_ICON[s.transition] : null
  const words = s.heard ?? s.said
  const color = (view.timeline.segments[s.segment] as { color?: string }).color
  return (
    <div ref={drop.setNodeRef} className="relative shrink-0 pr-[3px]" style={{ width: w }} data-shot={s.idx}>
      <button
        onClick={onSelect}
        className={cn(
          "group relative block w-full overflow-hidden rounded-lg border text-left transition",
          selected ? "z-10 border-ink shadow-[0_0_0_3px_var(--accent)]" : "border-transparent hover:border-ink/40",
          drop.isOver && "border-info shadow-[0_0_0_2px_var(--info)]",
        )}
        style={{ height: SHOT_H }}
      >
        {s.kind === "color" ? (
          <div className="absolute inset-0" style={{ background: color ?? "#000" }} />
        ) : (
          <Thumb path={src ? `${pid}/${src}` : null} w={Math.min(480, Math.max(160, Math.round(w * 2)))} t={thumbTime(s)} className="absolute inset-0" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-ink/70 via-ink/5 to-ink/25" />
        <span className="absolute top-1 left-1.5 font-mono text-[10.5px] font-medium text-control-ink">{s.idx}</span>
        {w > 58 && <span className="absolute right-1.5 bottom-1 font-mono text-[10.5px] text-control-ink">{s.duration.toFixed(1)}s</span>}
        {s.beat_synced && w > 40 && <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-warn ring-1 ring-ink/40" title="cut on the beat" />}
        {s.warning && <AlertTriangle className="absolute bottom-1 left-1.5 size-3 text-warn drop-shadow" />}
        {drop.isOver && (
          <div className="absolute inset-0 grid place-items-center bg-info/60 text-[11px] font-semibold text-control-ink backdrop-blur-[1px]">
            <span className="inline-flex items-center gap-1">
              <Repeat2 className="size-3.5" /> Swap
            </span>
          </div>
        )}
      </button>
      {Tr && (
        <span
          title={`${s.transition} transition`}
          className="absolute top-[30px] -left-[11px] z-20 grid size-[22px] place-items-center rounded-full bg-accent text-accent-ink shadow-soft ring-2 ring-surface"
        >
          <Tr className="size-3" />
        </span>
      )}
      <div
        className={cn("mt-1.5 h-[34px] overflow-hidden px-1 text-[11.5px] leading-[1.45]", words ? "text-foreground" : "text-subtle")}
        title={words ?? undefined}
      >
        {words ? `“${words}”` : w > 70 ? (s.role === "ambient" ? "ambient sound" : s.kind === "image" ? "photo" : "music only") : ""}
      </div>
    </div>
  )
}

function SegmentGroup({
  id,
  shots,
  children,
  vo,
}: {
  id: string
  shots: ResolvedShot[]
  children: React.ReactNode
  vo: boolean
}) {
  const s = useSortable({ id, data: { type: "segment", segment: shots[0].segment } })
  const style = { transform: CSS.Translate.toString(s.transform), transition: s.transition }
  return (
    <div
      ref={s.setNodeRef}
      style={style}
      {...s.attributes}
      {...s.listeners}
      className={cn("relative flex shrink-0 cursor-grab active:cursor-grabbing", s.isDragging && "z-30 opacity-80")}
    >
      {vo && (
        <div className="pointer-events-none absolute -top-[18px] right-0 left-0 flex items-center gap-1.5">
          <span className="h-[7px] flex-1 rounded-tl-md border-t border-l border-ink/35" />
          <span className="text-[10px] font-semibold tracking-wider text-ink-soft uppercase">VO block</span>
          <span className="mr-[3px] h-[7px] flex-1 rounded-tr-md border-t border-r border-ink/35" />
        </div>
      )}
      {children}
    </div>
  )
}

/** A pill is as wide as its time span, or as its text when the span is too short to read it. */
const pillWidth = (o: ResolvedOverlay, pps: number) =>
  Math.max((o.end - o.start) * pps - 2, 40 + 7.4 * (o.kind === "text" ? (o.text ?? "") : basename(o.src)).length)

function rows(items: ResolvedOverlay[], pps: number): ResolvedOverlay[][] {
  const out: { end: number; items: ResolvedOverlay[] }[] = []
  for (const o of [...items].sort((a, b) => a.start - b.start)) {
    const x = o.start * pps
    const row = out.find((r) => r.end <= x + 1)
    const end = x + pillWidth(o, pps) + 4
    if (row) {
      row.items.push(o)
      row.end = end
    } else out.push({ end, items: [o] })
  }
  return out.map((r) => r.items)
}

export function Track({
  view,
  pid,
  pps,
  selection,
  active,
  onSelect,
}: {
  view: TimelineView
  pid: string
  pps: number
  selection: Selection
  active?: Span
  onSelect: (s: Selection) => void
}) {
  const total = Math.max(view.duration, Number(view.end_card?.end ?? 0))
  const width = total * pps + GUTTER * 2 + 80
  const groups = useMemo(() => {
    const g: { segment: number; shots: ResolvedShot[] }[] = []
    for (const s of view.shots) {
      const last = g[g.length - 1]
      if (last && last.segment === s.segment) last.shots.push(s)
      else g.push({ segment: s.segment, shots: [s] })
    }
    return g
  }, [view.shots])
  const overlayRows = useMemo(() => rows(view.overlays.filter((o) => o.kind === "text" || o.kind === "broll"), pps), [view.overlays, pps])
  const voSpans = useMemo(
    () =>
      groups
        .filter((g) => g.shots[0].voiceover)
        .map((g) => ({ start: g.shots[0].start, end: g.shots[g.shots.length - 1].end, src: g.shots[0].voiceover! })),
    [groups],
  )
  const talk = view.shots.filter((s) => s.role === "voice" && !s.voiceover)
  const beats = useMemo(() => {
    if (!view.music?.bpm) return []
    const period = 60 / Number(view.music.bpm)
    const out: { t: number; down: boolean }[] = []
    for (let k = 0, t = Number(view.music.starts_at ?? 0) % period; t <= total; k++, t += period) out.push({ t, down: k % 4 === 0 })
    return out
  }, [view.music, total])
  const step = pps >= 60 ? 1 : pps >= 30 ? 2 : 5

  return (
    <div className="relative" style={{ width }}>
      {/* the active stretch, as a faint band down through the shots, labels and sound */}
      {active && (
        <div
          className="pointer-events-none absolute top-0 bottom-0 rounded-xl bg-accent/25"
          style={{ left: GUTTER + active.start * pps, width: Math.max(2, (active.end - active.start) * pps) }}
        />
      )}

      {/* the scrubber: a black rounded bar with the times in light text; the active stretch is a yellow pill on it */}
      <div className="relative mb-6 h-7" style={{ marginLeft: GUTTER, width: total * pps }} data-testid="scrubber">
        <div className="absolute inset-y-0 -right-2.5 -left-2.5 rounded-full bg-control shadow-pill" />
        {Array.from({ length: Math.floor(total / step) + 1 }).map((_, i) => (
          <div key={i} className="absolute inset-y-0 flex items-center" style={{ left: i * step * pps }}>
            <span className="absolute bottom-0 h-1.5 w-px bg-control-ink/35" />
            <span className="pl-1 font-mono text-[10px] text-control-ink/80">{clock(i * step)}</span>
          </div>
        ))}
        {view.target_length && view.target_length < total + 10 && (
          <div className="absolute inset-y-1 border-l-[1.5px] border-dashed border-warn" style={{ left: view.target_length * pps }}>
            <span className="absolute top-1/2 left-1 -translate-y-1/2 text-[10px] font-medium whitespace-nowrap text-warn">target {clock(view.target_length)}</span>
          </div>
        )}
        {active && (
          <div
            data-testid="scrubber-active"
            className="absolute inset-y-1 z-10 flex items-center justify-center rounded-full bg-accent px-2 font-mono text-[10.5px] font-semibold whitespace-nowrap text-accent-ink shadow-soft"
            style={{ left: active.start * pps, minWidth: Math.max(12, (active.end - active.start) * pps) }}
          >
            {tc(active.start)} – {tc(active.end)}
          </div>
        )}
      </div>

      {/* shots + the words heard over them */}
      <div className="relative flex pt-1" style={{ paddingLeft: GUTTER }}>
        <SortableContext items={groups.map((g) => `seg-${g.segment}`)} strategy={horizontalListSortingStrategy}>
          {groups.map((g) => (
            <SegmentGroup key={`seg-${g.segment}`} id={`seg-${g.segment}`} shots={g.shots} vo={!!g.shots[0].voiceover}>
              {g.shots.map((s) => (
                <ShotBlock
                  key={s.idx}
                  s={s}
                  pid={pid}
                  view={view}
                  pps={pps}
                  selected={selection?.type === "shot" && selection.idx === s.idx}
                  onSelect={() => onSelect({ type: "shot", idx: s.idx })}
                />
              ))}
            </SegmentGroup>
          ))}
        </SortableContext>
        {view.end_card && (
          <div
            className="flex shrink-0 flex-col items-center justify-center rounded-lg border border-dashed border-ink/25 bg-surface-2/50 text-[11px] text-muted-foreground"
            style={{ width: (Number(view.end_card.end) - Number(view.end_card.start)) * pps - 3, height: SHOT_H }}
          >
            <span className="font-semibold text-foreground">End card</span>
            <span>{String(view.end_card.handle ?? "")}</span>
          </div>
        )}
      </div>

      {/* overlays: text, stickers, cutaways */}
      <div className="mt-2 border-t border-border pt-2.5" style={{ paddingLeft: GUTTER }}>
        <div className="relative" style={{ height: Math.max(1, overlayRows.length) * 30 }}>
          {overlayRows.length === 0 && <span className="absolute top-1.5 text-[11.5px] text-subtle">No text on screen</span>}
          {overlayRows.map((row, r) =>
            row.map((o) => {
              const sel = selection?.type === "overlay" && selection.kind === o.kind && selection.index === o.index
              const Icon = o.kind === "text" ? Type : Film
              return (
                <button
                  key={`${o.kind}-${o.index}`}
                  onClick={() => o.index != null && onSelect({ type: "overlay", kind: o.kind, index: o.index })}
                  className={cn(
                    "absolute flex h-[25px] items-center gap-1.5 overflow-hidden rounded-full border px-2.5 text-[11.5px] font-medium whitespace-nowrap transition",
                    o.kind === "text"
                      ? "border-ink/15 bg-surface text-foreground shadow-soft hover:border-ink/35"
                      : "border-info/35 bg-info/10 text-info-ink hover:bg-info/20",
                    sel && "border-ink bg-accent text-accent-ink",
                  )}
                  style={{ left: o.start * pps, top: r * 30, width: pillWidth(o, pps) }}
                  title={o.text ?? o.src ?? ""}
                >
                  <Icon className="size-3 shrink-0 opacity-70" />
                  <span className="truncate">{o.kind === "text" ? o.text : basename(o.src)}</span>
                </button>
              )
            }),
          )}
        </div>
      </div>

      {/* sound */}
      <div className="mt-2 grid gap-1.5 border-t border-border pt-2.5" style={{ paddingLeft: GUTTER }}>
        {(voSpans.length > 0 || talk.length > 0) && (
          <div className="relative h-[26px]">
            {voSpans.map((v) => (
              <div
                key={v.start}
                className="absolute flex h-full items-center gap-1.5 overflow-hidden rounded-full border border-ink/20 bg-[repeating-linear-gradient(90deg,color-mix(in_oklab,var(--ink)_28%,transparent)_0_2px,transparent_2px_5px)] px-1.5 text-[11px] font-medium text-foreground"
                style={{ left: v.start * pps, width: (v.end - v.start) * pps }}
              >
                <span className="flex items-center gap-1 rounded-full bg-surface px-2 py-px shadow-soft">
                  <AudioLines className="size-3" /> {basename(v.src)}
                </span>
              </div>
            ))}
            {talk.map((s) => (
              <div
                key={s.idx}
                className="absolute h-full rounded-full border border-success/40 bg-[repeating-linear-gradient(90deg,color-mix(in_oklab,var(--success)_45%,transparent)_0_2px,transparent_2px_5px)]"
                style={{ left: s.start * pps, width: s.duration * pps }}
                title="your voice (to camera)"
              />
            ))}
          </div>
        )}
        {view.music && (
          <div className="relative h-[26px] overflow-hidden rounded-full border border-warn/45 bg-warn/10" style={{ width: view.duration * pps }}>
            {beats.map((b) => (
              <span key={b.t} className={cn("absolute top-0 bottom-0 w-px", b.down ? "bg-warn-ink/45" : "bg-warn/40")} style={{ left: b.t * pps }} />
            ))}
            {(view.music.drops as number[] | undefined)?.map((d) => (
              <span key={d} className="absolute top-1 -translate-x-1/2 rounded-full bg-warn px-1.5 text-[9px] font-bold text-ink" style={{ left: d * pps }}>
                DROP
              </span>
            ))}
            <span className="absolute top-1/2 left-1.5 flex -translate-y-1/2 items-center gap-1 rounded-full bg-surface px-2 py-px text-[11px] font-medium text-warn-ink shadow-soft">
              <Music2 className="size-3" /> {basename(String(view.music.src))} · {Math.round(Number(view.music.bpm))} BPM · from{" "}
              {clock(Number(view.music.starts_at ?? 0))}
              {view.music.in_app ? " · you add it in the app" : ""}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
