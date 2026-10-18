import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { mediaUrl } from "@/api/client"
import type { ResolvedOverlay, ResolvedShot, TimelineView } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { Button } from "@/components/ui/button"
import { secs, tc } from "@/lib/format"
import { cn } from "@/lib/utils"
import { shotSrc, thumbTime } from "./Track"

/** Roughly where and how each text style sits in the frame (the real look is rendered by the pipeline). */
function OverlayText({ o }: { o: ResolvedOverlay }) {
  const [main, sub] = (o.text ?? "").split(" / ")
  const emph = (t: string) =>
    t.split(/(\*[^*]+\*)/).map((p, i) => (p.startsWith("*") ? <span key={i} className="text-[#FFD54A]">{p.slice(1, -1)}</span> : p))
  switch (o.style) {
    case "sticker":
      return (
        <div className="absolute top-[11%] left-[7%] -rotate-2 rounded-[0.35em] bg-white px-[0.55em] py-[0.25em] text-[0.62em] font-semibold text-[#111] shadow-lg">
          {emph(main)}
        </div>
      )
    case "timestamp":
      return (
        <div className="absolute top-[10%] left-[7%] text-[0.62em] font-semibold tracking-[0.08em] text-white uppercase drop-shadow">
          <span className="mr-[0.4em] inline-block size-[0.45em] rounded-full bg-[#FFD54A] align-middle" />
          {emph(main)}
          {sub && <div className="mt-[0.15em] text-[0.8em] font-medium tracking-normal normal-case opacity-80">{sub}</div>}
        </div>
      )
    case "lower3":
    case "lower":
      return (
        <div className="absolute top-[60%] left-[7%] border-l-[0.18em] border-[#FFD54A] pl-[0.5em] text-white drop-shadow-lg">
          <div className="text-[0.78em] leading-tight font-bold">{emph(main)}</div>
          {sub && <div className="text-[0.6em] opacity-85">{sub}</div>}
        </div>
      )
    case "card":
    case "macros":
      return (
        <div className="absolute inset-x-[12%] top-[38%] rounded-[0.6em] bg-black/60 px-[0.8em] py-[0.6em] text-center text-white backdrop-blur-sm">
          <div className="text-[0.75em] font-bold">{emph(main)}</div>
          {sub && <div className="mt-[0.2em] text-[0.58em] opacity-80">{sub}</div>}
        </div>
      )
    case "credits":
      return <div className="absolute inset-x-0 bottom-[22%] text-center text-[0.55em] font-medium text-white/90 drop-shadow">{o.text}</div>
    case "title":
    case "big":
    case "title-minimal":
    case "title-serif":
      return (
        <div
          className={cn(
            "absolute inset-x-[8%] top-[16%] text-center text-[1.05em] leading-tight font-extrabold text-white drop-shadow-lg",
            o.style === "title-serif" && "font-serif font-normal italic",
          )}
        >
          {emph(main)}
        </div>
      )
    default:
      return (
        <div className="absolute inset-x-0 top-[9%] text-center">
          <span className="rounded-full bg-black/45 px-[0.6em] py-[0.2em] text-[0.58em] font-semibold text-white backdrop-blur-sm">{emph(main)}</span>
        </div>
      )
  }
}

export function Monitor({
  view,
  pid,
  shot,
  onPrev,
  onNext,
}: {
  view: TimelineView
  pid: string
  shot: ResolvedShot | undefined
  onPrev: () => void
  onNext: () => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  useEffect(() => {
    setPlaying(false)
    video.current?.pause()
  }, [shot?.idx])

  if (!shot) return <div className="grid h-full place-items-center text-muted-foreground">No shots</div>
  const src = shotSrc(view, shot)
  const overlays = view.overlays.filter((o) => o.kind === "text" && o.start < shot.end - 0.05 && o.end > shot.start + 0.05)
  const words = shot.heard ?? shot.said
  const canPlay = shot.kind === "clip" && !!src

  const play = () => {
    const v = video.current
    if (!v) return
    if (playing) {
      v.pause()
      return
    }
    v.currentTime = shot.in
    v.playbackRate = shot.speed || 1
    v.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
  }

  return (
    <div className="flex h-full min-h-0 flex-col items-center">
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-white/[0.08] bg-black shadow-[0_30px_60px_-30px_rgb(0_0_0/0.9)]" style={{ aspectRatio: "9 / 16", containerType: "size" }}>
        {shot.kind === "color" ? (
          <div className="absolute inset-0" style={{ background: String((view.timeline.segments[shot.segment] as { color?: string }).color ?? "#000") }} />
        ) : (
          <Thumb key={`${shot.idx}-${src}`} path={src ? `${pid}/${src}` : null} w={720} t={thumbTime(shot)} className="absolute inset-0" />
        )}
        {canPlay && (
          <video
            ref={video}
            src={mediaUrl(`${pid}/${src}`)}
            muted={shot.role === "mute"}
            playsInline
            preload="none"
            onTimeUpdate={(e) => {
              if (e.currentTarget.currentTime >= shot.out - 0.02) {
                e.currentTarget.pause()
                setPlaying(false)
              }
            }}
            onPause={() => setPlaying(false)}
            className={cn("absolute inset-0 size-full object-cover transition-opacity", playing ? "opacity-100" : "opacity-0")}
          />
        )}
        <div className="pointer-events-none absolute inset-0" style={{ fontSize: "6.2cqh" }}>
          {overlays.map((o) => (
            <OverlayText key={`${o.kind}-${o.index}`} o={o} />
          ))}
          {words && view.captions?.enabled !== false && (
            <div className="absolute inset-x-[8%] top-[68%] text-center text-[0.62em] leading-snug font-bold text-white [text-shadow:0_2px_12px_rgb(0_0_0/0.7)]">
              {words.split(" ").slice(0, 8).join(" ")}
              {words.split(" ").length > 8 && "…"}
            </div>
          )}
        </div>
        <div className="absolute top-3 right-3 rounded-md bg-black/55 px-1.5 py-0.5 font-mono text-[11px] text-zinc-200 backdrop-blur-md">#{shot.idx}</div>
        {canPlay && (
          <button
            onClick={play}
            className="absolute bottom-3 left-1/2 inline-flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-full whitespace-nowrap border border-white/15 bg-black/60 px-3 text-[12px] font-medium text-white backdrop-blur-md transition hover:bg-black/80"
          >
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            {playing ? "Pause" : "Play shot"}
          </button>
        )}
      </div>
      <div className="mt-3 flex w-full max-w-[340px] items-center justify-between gap-2">
        <Button size="icon-sm" variant="ghost" onClick={onPrev} aria-label="Previous shot">
          <ChevronLeft />
        </Button>
        <div className="text-center font-mono text-[11.5px] text-muted-foreground">
          {tc(shot.start)} → {tc(shot.end)}
          <span className="mx-1.5 text-subtle">·</span>
          {secs(shot.duration)}
        </div>
        <Button size="icon-sm" variant="ghost" onClick={onNext} aria-label="Next shot">
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
