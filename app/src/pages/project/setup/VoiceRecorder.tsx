import { Check, Loader2, Mic, MicOff, Pause, Play, Plus, RotateCcw, RotateCw, Square, Trash2, Volume2 } from "lucide-react"
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { type ApiError, mediaUrl } from "@/api/client"
import { useDeleteTake, useOpenPrivacySettings, useSaveTake, useTakes } from "@/api/queries"
import type { Project, ProjectFile, Take } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { clock, timeAgo } from "@/lib/format"
import { type LevelHint, type MicProblem, type Recording, useRecorder } from "@/lib/recorder"
import { cn } from "@/lib/utils"

const NEW = "new" // the recorder, rather than a take

/** 12.34 -> "0:12.3" (a running timer: whole seconds never jump ahead) */
const stopwatch = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}.${Math.floor((s * 10) % 10)}`
const takeNumber = (id: string | null | undefined) => id?.match(/take-(\d+)/)?.[1]

/** The take's audio, fetched back from the project, as a file to upload as the voiceover. */
export async function takeFile(pid: string, take: Take): Promise<File> {
  const r = await fetch(mediaUrl(`${pid}/${take.path}`))
  if (!r.ok) throw new Error(`Couldn't read take ${take.number} (${r.status})`)
  const blob = await r.blob()
  return new File([blob], take.path.split("/").pop() ?? `${take.id}.webm`, { type: blob.type })
}

const MIC_HELP: Record<MicProblem, { title: string; body: string; steps?: ReactNode[] }> = {
  denied: {
    title: "Let Cutroom use your microphone",
    body: "Chrome is blocking the mic for this page. Your takes only go to this project, on this Mac.",
    steps: [
      <>
        Click the <b>site controls</b> icon at the left end of the address bar, next to <b>localhost</b>.
      </>,
      <>
        Turn on <b>Microphone</b> (or set it to <b>Allow</b>).
      </>,
      <>
        Click <b>Try again</b>. If Chrome asks you to reload the page, reload: your takes are saved.
      </>,
    ],
  },
  "denied-system": {
    title: "macOS is keeping the mic from Chrome",
    body: "Chrome is allowed to ask, but your Mac hasn't given it the microphone yet.",
    steps: [
      <>
        Open <b>System Settings → Privacy &amp; Security → Microphone</b>.
      </>,
      <>
        Turn on <b>Google Chrome</b> (or the browser you're using).
      </>,
      <>
        Quit the browser completely (<kbd className="rounded-md bg-surface-2 px-1.5 font-mono text-[11.5px]">⌘Q</kbd>), open it again, come
        back here and click <b>Try again</b>.
      </>,
    ],
  },
  "no-mic": {
    title: "No microphone found",
    body: "Plug in a mic or headphones with one, or pick an input in System Settings → Sound → Input. Then try again.",
  },
  busy: {
    title: "The microphone is busy",
    body: "Another app may be using it (FaceTime, Zoom, Voice Memos). Close it, then try again.",
  },
  unsupported: {
    title: "This browser can't record audio",
    body: "Use a recent Chrome, Safari or Firefox. Or record a voice memo on your phone and Browse for it.",
  },
  insecure: {
    title: "Recording only works on localhost",
    body: "Browsers only allow the mic on localhost or https. Open Cutroom at the http://localhost address ./cutroom prints.",
  },
  error: {
    title: "Couldn't start recording",
    body: "Something went wrong opening the mic. Try again, or Browse for a voice memo instead.",
  },
}

function MicHelp({ kind, detail, onRetry }: { kind: MicProblem; detail: string; onRetry: () => void }) {
  const open = useOpenPrivacySettings()
  const h = MIC_HELP[kind]
  return (
    <div data-testid="mic-help" data-problem={kind} className="flex flex-col items-center px-2 py-2 text-center">
      <span className="mb-3 grid size-11 place-items-center rounded-full bg-accent text-accent-ink">
        <MicOff className="size-5" />
      </span>
      <h3 className="text-[16px] font-semibold tracking-[-0.01em]">{h.title}</h3>
      <p className="mt-1 max-w-[400px] text-[12.5px] leading-relaxed text-muted-foreground">{h.body}</p>
      {h.steps && (
        <ol className="mt-4 grid w-full gap-2 text-left text-[12.5px] leading-relaxed">
          {h.steps.map((step, i) => (
            <li key={i} className="flex gap-3 rounded-2xl bg-surface-2/60 px-3.5 py-2.5">
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-control font-mono text-[11px] text-control-ink">{i + 1}</span>
              <span className="text-foreground">{step}</span>
            </li>
          ))}
        </ol>
      )}
      {kind === "denied" && (
        <p className="mt-3 text-[11.5px] leading-relaxed text-subtle">
          Still blocked? Look in <code className="rounded bg-surface-2 px-1 font-mono">chrome://settings/content/microphone</code>, and on a Mac in System
          Settings → Privacy &amp; Security → Microphone.
        </p>
      )}
      {kind === "denied-system" && (
        <button
          onClick={() => open.mutate("microphone")}
          className="mt-3 text-[12.5px] font-medium text-foreground underline decoration-ink/30 underline-offset-2 hover:decoration-ink"
        >
          Open Microphone settings for me
        </button>
      )}
      {kind === "error" && detail && <p className="mt-2 font-mono text-[11px] text-subtle">{detail}</p>}
      <Button className="mt-4" onClick={onRetry}>
        <RotateCw /> Try again
      </Button>
    </div>
  )
}

const SEGMENTS = 28

function LevelMeter({ level, dim }: { level: number; dim: boolean }) {
  const lit = Math.round(level * SEGMENTS)
  return (
    <div data-testid="level-meter" data-level={level.toFixed(2)} className={cn("flex h-7 w-full items-center gap-[3px] transition-opacity", dim && "opacity-40")} aria-hidden>
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <span
          key={i}
          className={cn(
            "min-w-0 flex-1 rounded-full transition-[height,background-color] duration-75",
            i < lit ? (i >= SEGMENTS - 3 ? "bg-warn" : "bg-ink") : "bg-ink/10",
          )}
          style={{ height: i < lit ? `${45 + (55 * i) / SEGMENTS}%` : "30%" }}
        />
      ))}
    </div>
  )
}

const HINTS: Record<Exclude<LevelHint, null>, string> = {
  quiet: "Quiet: move a little closer or speak up",
  loud: "Too loud: back off a little",
  ok: "Good level",
}

/** A take's waveform as the playback bar: click or drag to move through it. */
function TakePlayer({ pid, take }: { pid: string; take: Take }) {
  const audio = useRef<HTMLAudioElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const [playing, setPlaying] = useState(false)
  const [t, setT] = useState(0)
  const dur = take.duration
  const peaks = useMemo(() => (take.peaks?.length ? take.peaks : Array.from({ length: 60 }, () => 0.3)), [take.peaks])

  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      if (audio.current) setT(audio.current.currentTime)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  const seek = (e: React.PointerEvent) => {
    const r = box.current!.getBoundingClientRect()
    const at = Math.min(dur, Math.max(0, ((e.clientX - r.left) / Math.max(1, r.width)) * dur))
    if (audio.current) audio.current.currentTime = at
    setT(at)
  }
  const toggle = () => {
    const a = audio.current
    if (!a) return
    if (a.paused) a.play().catch(() => setPlaying(false))
    else a.pause()
  }

  return (
    <div className="flex items-center gap-3" data-testid="take-player">
      <button
        onClick={toggle}
        className="grid size-10 shrink-0 place-items-center rounded-full bg-control text-control-ink shadow-pill transition hover:bg-control-hover"
        aria-label={playing ? "Pause the take" : "Play the take"}
      >
        {playing ? <Pause className="size-4" /> : <Play className="size-4 translate-x-px" />}
      </button>
      <audio
        ref={audio}
        src={mediaUrl(`${pid}/${take.path}`)}
        preload="auto"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false)
          setT(0)
        }}
      />
      <div
        ref={box}
        role="slider"
        aria-label="Position in the take"
        aria-valuemin={0}
        aria-valuemax={Math.round(dur)}
        aria-valuenow={Math.round(t)}
        tabIndex={0}
        onKeyDown={(e) => {
          const step = e.key === "ArrowRight" ? 2 : e.key === "ArrowLeft" ? -2 : 0
          if (!step || !audio.current) return
          const at = Math.min(dur, Math.max(0, t + step))
          audio.current.currentTime = at
          setT(at)
        }}
        onPointerDown={(e) => {
          dragging.current = true
          e.currentTarget.setPointerCapture?.(e.pointerId)
          seek(e)
        }}
        onPointerMove={(e) => dragging.current && seek(e)}
        onPointerUp={() => (dragging.current = false)}
        className="relative flex h-12 min-w-0 flex-1 cursor-pointer touch-none items-center gap-[2px] rounded-xl outline-none select-none focus-visible:ring-2 focus-visible:ring-ink/30"
      >
        {peaks.map((v, i) => (
          <span
            key={i}
            className={cn("min-w-0 flex-1 rounded-full", ((i + 0.5) / peaks.length) * dur <= t ? "bg-ink" : "bg-ink/20")}
            style={{ height: `${Math.round(12 + v * 82)}%` }}
          />
        ))}
      </div>
      <span className="min-w-[84px] shrink-0 text-right font-mono text-[12px] whitespace-nowrap text-ink-soft tabular-nums" data-testid="take-time">
        {clock(t)} / {clock(dur)}
      </span>
    </div>
  )
}

/** Record a voiceover in the app: the mic's level and a timer while recording, then each take to listen back to.
 * Takes are kept in the project; "Use this" uploads the picked one to the Voiceover slot like a voice memo. */
export function VoiceRecorder({
  project,
  open,
  onOpenChange,
  onUse,
}: {
  project: Project
  open: boolean
  onOpenChange: (open: boolean) => void
  /** upload the take as the voiceover (replacing the one from an earlier take); true when it's in */
  onUse: (take: Take, replace?: ProjectFile) => Promise<boolean>
}) {
  const pid = project.id
  const takesQ = useTakes(pid, open)
  const takes = useMemo(() => takesQ.data ?? [], [takesQ.data])
  const save = useSaveTake(pid)
  const del = useDeleteTake(pid)
  const [pick, setPick] = useState<string | null>(null) // a take id, NEW, or null: the take in use, else the newest
  const [failed, setFailed] = useState<{ rec: Recording; message: string; hint: string | null } | null>(null)
  const [using, setUsing] = useState(false)
  const shown = useRef(open)
  shown.current = open

  const keep = (rec: Recording) => {
    setFailed(null)
    save.mutate(
      { recording: rec.blob, name: `take${rec.ext}` },
      {
        onSuccess: (t) => {
          setPick(t.id)
          if (!shown.current) toast.success(`Saved take ${t.number}`, { description: "It's in Record, under Takes." })
        },
        onError: (e) => setFailed({ rec, message: e.message, hint: (e as ApiError).hint ?? null }),
      },
    )
  }
  const rec = useRecorder(keep)

  // opening again starts from the take in use (or the newest one)
  useEffect(() => {
    if (open) setPick(null)
  }, [open])

  const voices = (project.files ?? []).filter((f) => f.kind === "voiceover")
  const inUse = new Set(voices.map((f) => f.take).filter(Boolean))
  const current = pick === NEW ? undefined : (takes.find((t) => t.id === pick) ?? takes.find((t) => inUse.has(t.id)) ?? takes.at(-1))
  const recording = rec.active || rec.status === "asking"
  const busy = recording || save.isPending
  const replace = current ? voices.find((f) => f.take && f.take !== current.id) : undefined
  const imported = voices.filter((f) => !f.take)

  const record = () => {
    setPick(NEW)
    setFailed(null)
    void rec.start()
  }
  const close = (o: boolean) => {
    if (o) return onOpenChange(true)
    if (using) return // the take is on its way into the Voiceover slot
    if (rec.active) rec.stop() // closing mid-take keeps what was recorded
    onOpenChange(false)
  }
  const use = async () => {
    if (!current) return
    setUsing(true)
    const ok = await onUse(current, replace).catch((e: Error) => {
      toast.error(e.message)
      return false
    })
    setUsing(false)
    if (ok) onOpenChange(false)
  }
  const remove = (t: Take) =>
    del.mutate(t.id, {
      onSuccess: () =>
        toast.success(`Deleted take ${t.number}`, inUse.has(t.id) ? { description: "Your voiceover made from it stays in the project." } : undefined),
    })

  let panel: ReactNode
  if (failed)
    panel = (
      <div className="flex flex-col items-center py-6 text-center" data-testid="take-failed">
        <span className="mb-3 grid size-11 place-items-center rounded-full bg-accent text-accent-ink">
          <Mic className="size-5" />
        </span>
        <h3 className="text-[16px] font-semibold">Couldn't save that take</h3>
        <p className="mt-1 max-w-[400px] text-[12.5px] leading-relaxed text-muted-foreground">
          {failed.message}
          {failed.hint ? `. ${failed.hint}` : ""}
        </p>
        <div className="mt-4 flex gap-2">
          <Button variant="ghost" onClick={() => setFailed(null)}>
            Discard
          </Button>
          <Button onClick={() => keep(failed.rec)}>
            <RotateCw /> Try again
          </Button>
        </div>
      </div>
    )
  else if (save.isPending)
    panel = (
      <div className="grid place-items-center py-14 text-center" data-testid="take-saving">
        <Loader2 className="mb-2 size-5 animate-spin" />
        <div className="text-[13px] font-medium">Saving the take…</div>
      </div>
    )
  else if (rec.status === "blocked" && rec.problem && (pick === NEW || !current))
    panel = <MicHelp kind={rec.problem.kind} detail={rec.problem.detail} onRetry={record} />
  else if (recording || !current)
    panel = (
      <div className="flex flex-col items-center gap-4 py-4" data-testid="recorder" data-status={rec.status}>
        <div className="flex items-center gap-2 text-[12.5px] font-medium">
          {rec.status === "recording" ? (
            <>
              <span className="size-2.5 animate-pulse rounded-full bg-destructive" /> Recording
            </>
          ) : rec.status === "paused" ? (
            <>
              <Pause className="size-3.5" /> Paused
            </>
          ) : rec.status === "asking" ? (
            <span className="text-muted-foreground">Allow the microphone when your browser asks…</span>
          ) : (
            <span className="text-muted-foreground">{takes.length ? `Take ${(takes.at(-1)?.number ?? 0) + 1}` : "Ready when you are"}</span>
          )}
        </div>
        <div className="font-mono text-[44px] leading-none font-medium tracking-[-0.03em] tabular-nums" data-testid="rec-timer">
          {stopwatch(rec.elapsed)}
        </div>
        <LevelMeter level={rec.level} dim={rec.status !== "recording"} />
        <div className={cn("h-4 text-[12px]", rec.hint === "ok" ? "text-success-ink" : "text-warn-ink")} data-testid="level-hint">
          {rec.status === "recording" && rec.hint ? HINTS[rec.hint] : ""}
        </div>
        <div className="flex items-center gap-2">
          {rec.status === "recording" && (
            <Button variant="outline" onClick={rec.pause}>
              <Pause /> Pause
            </Button>
          )}
          {rec.status === "paused" && (
            <Button variant="outline" onClick={rec.resume}>
              <Mic /> Resume
            </Button>
          )}
          {rec.active ? (
            <Button onClick={rec.stop}>
              <Square className="fill-current" /> Stop
            </Button>
          ) : (
            <Button size="lg" onClick={record} disabled={rec.status === "asking"}>
              {rec.status === "asking" ? <Loader2 className="animate-spin" /> : <span className="size-3 rounded-full bg-destructive" />} Record
            </Button>
          )}
        </div>
      </div>
    )
  else
    panel = (
      <div className="flex flex-col gap-4 py-2" data-testid="take-review" data-take={current.id}>
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold">Take {current.number}</span>
          <span className="font-mono text-[12px] text-ink-soft">{clock(current.duration)}</span>
          {inUse.has(current.id) && (
            <span className="rounded-full bg-success/15 px-2 py-px text-[10.5px] font-semibold tracking-[0.04em] text-success-ink uppercase">In use</span>
          )}
          <span className="ml-auto text-[11.5px] text-subtle">{timeAgo(current.created_at)}</span>
        </div>
        <TakePlayer key={current.id} pid={pid} take={current} />
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={use} disabled={using || inUse.has(current.id)}>
            {using ? <Loader2 className="animate-spin" /> : <Check />} {inUse.has(current.id) ? "In use" : "Use this"}
          </Button>
          <Button variant="outline" onClick={record}>
            <RotateCcw /> Re-record
          </Button>
          <Button variant="ghost" onClick={() => remove(current)} className="ml-auto hover:text-destructive" disabled={using}>
            <Trash2 /> Delete
          </Button>
        </div>
        {!inUse.has(current.id) && (replace || imported.length > 0) && (
          <p className="text-[12px] text-muted-foreground">
            {replace
              ? `Replaces take ${takeNumber(replace.take) ?? ""} as your voiceover.`
              : `Adds it next to ${imported.map((f) => f.name).join(", ")}: remove that one from the Voiceover card if this replaces it.`}
          </p>
        )}
      </div>
    )

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="flex max-h-[90vh] max-w-[min(540px,94vw)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[min(540px,94vw)]" showCloseButton={!using}>
        <div className="flex items-center gap-3 border-b border-border px-5 py-3.5">
          <Mic className="size-4" />
          <DialogTitle className="text-[15px]">Record a voiceover</DialogTitle>
          <DialogDescription className="sr-only">Record your voiceover with the microphone, listen back and pick the take to use</DialogDescription>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-4 flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3.5 py-2.5 text-[12.5px]" data-testid="record-tip">
            <Volume2 className="size-4 shrink-0 text-ink-soft" />
            <span>Record in a quiet room, phone/mic ~20cm away.</span>
          </div>
          {panel}
        </div>
        {takes.length > 0 && (
          <div className="border-t border-border px-5 py-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="eyebrow">Takes</span>
              <span className="text-[11.5px] text-subtle">Saved in this project</span>
            </div>
            <div className="flex flex-wrap gap-2" data-testid="takes">
              {takes.map((t) => (
                <button
                  key={t.id}
                  data-take={t.id}
                  disabled={busy}
                  onClick={() => {
                    setFailed(null)
                    setPick(t.id)
                  }}
                  aria-pressed={current?.id === t.id}
                  className={cn(
                    "flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-medium transition disabled:opacity-45",
                    current?.id === t.id && !busy ? "bg-accent text-accent-ink" : "bg-surface-2 text-foreground hover:bg-ink/[0.08]",
                  )}
                >
                  {inUse.has(t.id) && <Check className="size-3.5" />}
                  Take {t.number}
                  <span className="font-mono text-[11px] text-ink-soft">{clock(t.duration)}</span>
                </button>
              ))}
              <button
                onClick={() => {
                  setFailed(null)
                  setPick(NEW)
                }}
                disabled={busy}
                className={cn(
                  "flex h-8 items-center gap-1 rounded-full border border-dashed border-ink/25 px-3 text-[12.5px] text-ink-soft transition hover:border-ink/50 hover:text-foreground disabled:opacity-45",
                  pick === NEW && !busy && "border-ink/60 text-foreground",
                )}
              >
                <Plus className="size-3.5" /> New take
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
