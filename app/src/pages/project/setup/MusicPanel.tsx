import { useQueryClient } from "@tanstack/react-query"
import { Loader2, Pause, Play, RotateCcw, Smartphone, Sparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { fileContentUrl } from "@/api/client"
import { keys, useMusic, usePatchProject } from "@/api/queries"
import type { MusicInfo, Project, ProjectFile } from "@/api/types"
import { Skeleton } from "@/components/ui/skeleton"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { clock } from "@/lib/format"
import { cn } from "@/lib/utils"

const BARS = 180

function autoText(m: MusicInfo): string {
  switch (m.auto_reason) {
    case "drop":
      return `two bars before the drop at ${clock(m.auto_drop)}`
    case "loudest":
      return `the strongest ${Math.round(Math.min(m.length, m.duration))}s of the song`
    case "first-downbeat":
      return "from the first beat"
    case "preset-drop":
      return `the drop${m.auto_drop != null ? ` at ${clock(m.auto_drop)}` : ""} lands on the reveal; the exact start shows on the result`
    default:
      return "the preset's start"
  }
}

/** The waveform: the stretch the edit uses is lit, drops are marked, click or drag to move the start. */
function Waveform({
  m,
  start,
  playhead,
  onPick,
  onCommit,
}: {
  m: MusicInfo
  start: number
  playhead: number | null
  onPick: (s: number) => void
  onCommit: (s: number) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const bars = useMemo(() => {
    const p = m.peaks
    return Array.from({ length: BARS }, (_, i) => {
      const a = Math.floor((i * p.length) / BARS)
      const b = Math.max(a + 1, Math.floor(((i + 1) * p.length) / BARS))
      return Math.max(...p.slice(a, b), 0.04)
    })
  }, [m.peaks])
  const len = Math.min(m.length, m.duration)
  const maxStart = Math.max(0, m.duration - len)
  const fixed = maxStart < 1
  const at = (e: React.PointerEvent) => {
    const r = box.current!.getBoundingClientRect()
    const t = ((e.clientX - r.left) / r.width) * m.duration
    return Math.round(Math.min(maxStart, Math.max(0, t)))
  }
  const x = (t: number) => `${(100 * t) / m.duration}%`

  return (
    <div
      ref={box}
      data-testid="waveform"
      role="slider"
      aria-label="Where the edit starts in the song"
      aria-valuemin={0}
      aria-valuemax={Math.round(maxStart)}
      aria-valuenow={Math.round(start)}
      tabIndex={-1}
      onPointerDown={(e) => {
        if (fixed) return
        dragging.current = true
        e.currentTarget.setPointerCapture(e.pointerId)
        onPick(at(e))
      }}
      onPointerMove={(e) => dragging.current && onPick(at(e))}
      onPointerUp={(e) => {
        if (!dragging.current) return
        dragging.current = false
        onCommit(at(e))
      }}
      className={cn("relative h-[84px] touch-none select-none", !fixed && "cursor-pointer")}
    >
      <div
        className="absolute inset-y-0 rounded-xl bg-accent/55 ring-1 ring-ink/25"
        style={{ left: x(start), width: x(len) }}
      />
      <div className="absolute inset-0 flex items-center gap-[2px] px-px">
        {bars.map((v, i) => {
          const t = ((i + 0.5) / BARS) * m.duration
          const lit = t >= start && t <= start + len
          return (
            <span
              key={i}
              className={cn("min-w-0 flex-1 rounded-full transition-colors", lit ? "bg-ink" : "bg-ink/15")}
              style={{ height: `${Math.round(v * 86)}%` }}
            />
          )
        })}
      </div>
      {m.drops.map((d) => (
        <div key={d} className="pointer-events-none absolute inset-y-0" style={{ left: x(d) }} title={`drop at ${clock(d)}`}>
          <div className="h-full w-px bg-warn" />
          <span className="absolute -top-0.5 left-1 rounded-full bg-surface px-1.5 text-[10px] font-medium text-warn-ink shadow-soft">drop</span>
        </div>
      ))}
      {playhead != null && <div className="pointer-events-none absolute inset-y-0 w-0.5 rounded bg-info" style={{ left: x(playhead) }} />}
    </div>
  )
}

/** Music step: which part of the song the edit uses (waveform + slider, auto by default), a play/pause preview from
 * that point, and "I'll add this song in Instagram/TikTok when posting". */
export function MusicPanel({ project, file }: { project: Project; file: ProjectFile }) {
  const pid = project.id
  const qc = useQueryClient()
  const music = useMusic(pid, file.id)
  const patch = usePatchProject(pid)
  const audio = useRef<HTMLAudioElement>(null)
  const [pick, setPick] = useState<number | null | undefined>(undefined)
  const [playing, setPlaying] = useState(false)
  const [now, setNow] = useState<number | null>(null)
  const inApp = !!project.brief?.music_in_app
  const m = music.data

  const chosen = pick !== undefined ? pick : (m?.start ?? null)
  const start = chosen ?? m?.auto_start ?? 0
  const len = m ? Math.min(m.length, m.duration) : 0
  const end = start + len
  const whole = !!m && m.duration - len < 1        // the video is as long as the song: nothing to pick

  // the playhead follows the audio, and the preview stops where the edit ends
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      const a = audio.current
      if (a) {
        setNow(a.currentTime)
        if (a.currentTime >= end) a.pause()
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, end])

  const save = (brief: { music_start?: number | null; music_in_app?: boolean }) =>
    patch.mutate({ brief }, { onSuccess: () => qc.invalidateQueries({ queryKey: keys.music(pid, file.id) }) })
  const moveTo = (s: number) => {
    setPick(s)
    const a = audio.current
    if (a && !a.paused) a.currentTime = s
  }
  const commit = (s: number | null) => {
    setPick(s)
    save({ music_start: s })
  }
  const toggle = () => {
    const a = audio.current
    if (!a) return
    if (!a.paused) return a.pause()
    if (a.currentTime < start || a.currentTime >= end - 0.2) a.currentTime = start
    void a.play()
  }

  return (
    <div className="panel p-5" data-testid="music-panel">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[14px] font-semibold">The song</div>
          <div className="text-[12.5px] text-muted-foreground">
            Pick the part the edit uses: click or drag on the waveform. The cuts land on its beat.
          </div>
        </div>
        {m && (
          <div className="shrink-0 font-mono text-[12px] text-muted-foreground">
            {Math.round(m.bpm)} BPM · {clock(m.duration)}
          </div>
        )}
      </div>

      {music.isLoading ? (
        <div className="grid gap-3">
          <Skeleton className="h-[84px] rounded-xl" />
          <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> Finding the beat…
          </div>
        </div>
      ) : music.error || !m ? (
        <div className="flex items-center justify-between gap-3 rounded-2xl bg-surface-2/60 px-4 py-3 text-[12.5px] text-muted-foreground">
          <span>Couldn't read this track{music.error ? `: ${(music.error as Error).message}` : ""}.</span>
          <button onClick={() => music.refetch()} className="text-foreground underline-offset-2 hover:underline">
            Try again
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-4">
            <button
              onClick={toggle}
              className="grid size-10 shrink-0 place-items-center rounded-full bg-control text-control-ink shadow-pill transition hover:bg-control-hover"
              aria-label={playing ? "Pause" : "Play from the start point"}
            >
              {playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-px" />}
            </button>
            <audio
              ref={audio}
              src={fileContentUrl(pid, m.file_id)}
              preload="metadata"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
                <span className="text-muted-foreground">Starts at</span>
                <span className="font-mono text-[17px] font-semibold text-foreground" data-testid="music-start">
                  {clock(start)}
                </span>
                <span className="text-muted-foreground">to {clock(end)}</span>
              </div>
              <div className="truncate text-[12px] text-muted-foreground">
                {whole ? (
                  `The video is about as long as the song (${clock(m.duration)}), so it uses all of it.`
                ) : chosen == null ? (
                  <span className="inline-flex items-center gap-1">
                    <Sparkles className="size-3 text-primary" /> Auto: {autoText(m)}
                  </span>
                ) : (
                  "Your pick"
                )}
              </div>
            </div>
            {chosen != null && (
              <button
                onClick={() => commit(null)}
                className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-ink/80 px-3 text-[12.5px] font-medium text-foreground transition hover:bg-ink/[0.05]"
              >
                <RotateCcw className="size-3.5" /> Auto
              </button>
            )}
          </div>

          <div className="mt-4">
            <Waveform m={m} start={start} playhead={playing ? now : null} onPick={moveTo} onCommit={commit} />
            <Slider
              className="mt-3"
              min={0}
              max={Math.max(1, Math.floor(m.duration - len))}
              step={1}
              disabled={whole}
              value={[Math.round(start)]}
              onValueChange={([v]) => moveTo(v)}
              onValueCommit={([v]) => commit(v)}
              aria-label="Start point"
            />
            <div className="mt-1.5 flex justify-between font-mono text-[10.5px] text-subtle">
              <span>0:00</span>
              <span>{clock(m.duration)}</span>
            </div>
          </div>
        </>
      )}

      <label
        className={cn(
          "mt-5 flex cursor-pointer items-start gap-3 rounded-2xl px-4 py-3.5 transition",
          inApp ? "bg-accent-soft ring-1 ring-ink/70" : "bg-surface-2/60 hover:bg-surface-2",
        )}
      >
        <Smartphone className="mt-0.5 size-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] font-medium">I'll add this song in Instagram/TikTok when posting</span>
          <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted-foreground">
            The track is only used to find the beat and for the preview. You also get a copy without the music to post,
            and the exact second to start the song at in the app.
          </span>
        </span>
        <Switch
          checked={inApp}
          onCheckedChange={(v) => save({ music_in_app: v })}
          aria-label="I'll add this song in Instagram/TikTok when posting"
          className="mt-0.5"
        />
      </label>
    </div>
  )
}
