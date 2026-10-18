import { AnimatePresence, motion } from "framer-motion"
import { Maximize2, Pause, Play, Volume2, VolumeX } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { clock } from "@/lib/format"
import { cn } from "@/lib/utils"

/** A 9:16 player with minimal controls: click to play, scrub, mute, fullscreen. Space toggles. */
export function VideoPlayer({ src, poster, className }: { src: string; poster?: string; className?: string }) {
  const v = useRef<HTMLVideoElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(0)
  const [muted, setMuted] = useState(false)
  const [hover, setHover] = useState(true)

  useEffect(() => {
    setPlaying(false)
    setT(0)
  }, [src])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea")) return
      if (e.code === "Space") {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  const toggle = () => {
    const el = v.current
    if (!el) return
    if (el.paused) el.play()
    else el.pause()
  }

  return (
    <div
      ref={wrap}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={cn("group relative overflow-hidden rounded-[22px] border border-white/[0.09] bg-black shadow-[0_40px_80px_-30px_rgb(0_0_0/0.95),0_0_0_6px_rgb(255_255_255/0.02)]", className)}
      style={{ aspectRatio: "9 / 16" }}
    >
      <video
        ref={v}
        src={src}
        poster={poster}
        playsInline
        preload="metadata"
        muted={muted}
        onClick={toggle}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
        className="size-full cursor-pointer object-cover"
      />
      <AnimatePresence>
        {!playing && (
          <motion.button
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 1.1 }}
            onClick={toggle}
            aria-label="Play"
            className="absolute top-1/2 left-1/2 grid size-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/25 bg-black/45 text-white shadow-2xl backdrop-blur-xl transition hover:bg-black/60"
          >
            <Play className="size-6 translate-x-0.5 fill-current" />
          </motion.button>
        )}
      </AnimatePresence>
      <div
        className={cn(
          "absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent px-4 pt-10 pb-3.5 transition-opacity duration-300",
          playing && !hover ? "opacity-0" : "opacity-100",
        )}
      >
        <div
          className="group/bar relative mb-2.5 h-4 cursor-pointer"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            if (v.current && dur) v.current.currentTime = ((e.clientX - r.left) / r.width) * dur
          }}
        >
          <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/20 transition-all group-hover/bar:h-1.5" />
          <div className="absolute top-1/2 left-0 h-1 -translate-y-1/2 rounded-full bg-white transition-all group-hover/bar:h-1.5" style={{ width: dur ? `${(t / dur) * 100}%` : 0 }} />
        </div>
        <div className="flex items-center gap-3 text-white">
          <button onClick={toggle} aria-label={playing ? "Pause" : "Play"} className="opacity-90 hover:opacity-100">
            {playing ? <Pause className="size-4 fill-current" /> : <Play className="size-4 fill-current" />}
          </button>
          <span className="font-mono text-[11.5px] text-white/80 tabular-nums">
            {clock(t)} / {clock(dur)}
          </span>
          <span className="flex-1" />
          <button onClick={() => setMuted((m) => !m)} aria-label={muted ? "Unmute" : "Mute"} className="opacity-80 hover:opacity-100">
            {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
          </button>
          <button onClick={() => wrap.current?.requestFullscreen?.()} aria-label="Fullscreen" className="opacity-80 hover:opacity-100">
            <Maximize2 className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
