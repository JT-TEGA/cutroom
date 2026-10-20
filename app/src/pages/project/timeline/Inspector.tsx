import { AlertTriangle, ArrowLeftRight, Film, Loader2, Music2, Plus, Quote, Repeat2, Scissors, Send, Sparkles, Trash2, Type, Wind, Zap, ZoomIn } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"
import type { Project, ProjectFile, ResolvedShot, TextOverlay, Timeline, TimelineView } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { basename, clock, secs, tc } from "@/lib/format"
import { lengthMode, MIN_SHOT } from "@/lib/timeline-edit"
import { cn } from "@/lib/utils"
import { shotSrc, type Selection } from "./Track"

const TRANSITIONS = [
  { id: "", label: "Cut", icon: ArrowLeftRight },
  { id: "flash", label: "Flash", icon: Zap },
  { id: "whip", label: "Whip", icon: Wind },
  { id: "zoom", label: "Zoom", icon: ZoomIn },
]
const STYLES = ["sticker", "timestamp", "lower3", "label", "card", "title"]

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-[12.5px]">
      <span className="shrink-0 text-muted-foreground">{k}</span>
      <span className="min-w-0 truncate text-right text-foreground">{children}</span>
    </div>
  )
}

function Why({ children }: { children: ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-accent-soft p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] text-accent-ink uppercase">
        <Sparkles className="size-3.5" /> Why this cut
      </div>
      <div className="text-[13.5px] leading-relaxed text-foreground">{children}</div>
    </div>
  )
}

function SwapPicker({ files, pid, current, onPick }: { files: ProjectFile[]; pid: string; current: string | null; onPick: (f: ProjectFile) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="flex-1">
          <Repeat2 /> Swap clip
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[300px] p-3">
        <div className="mb-2 text-[12px] text-muted-foreground">Pick a clip or photo to use here</div>
        <div className="grid max-h-[320px] grid-cols-4 gap-2 overflow-y-auto">
          {files.map((f) => (
            <button
              key={f.id}
              onClick={() => {
                onPick(f)
                setOpen(false)
              }}
              disabled={f.path === current}
              className="group text-left disabled:opacity-40"
              title={f.name}
            >
              <Thumb path={`${pid}/${f.path}`} w={140} className="aspect-[9/16] rounded-xl ring-1 ring-ink/10 transition group-hover:ring-2 group-hover:ring-ink" />
              <div className="mt-1 truncate text-[10.5px] text-muted-foreground">{f.name}</div>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

const num = (v: string) => (v.trim() === "" ? NaN : Number(v))
const fmt = (x: number) => String(Math.round(x * 100) / 100)

function Field({ label, value, onChange, onCommit, hint }: { label: string; value: string; onChange: (v: string) => void; onCommit: () => void; hint?: string }) {
  return (
    <label className="grid gap-1">
      <span className="text-[11.5px] text-muted-foreground">{label}</span>
      <Input
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onCommit()}
        className="h-8 font-mono text-[12.5px]"
        aria-label={label}
      />
      {hint && <span className="text-[11px] text-subtle">{hint}</span>}
    </label>
  )
}

/** Trim a clip (start / end of the source) or set a shot's length in seconds. */
function LengthEditor({
  s,
  view,
  clipDur,
  onTrim,
  onDuration,
}: {
  s: ResolvedShot
  view: TimelineView
  clipDur?: number | null
  onTrim: (inS: number, outS: number) => void
  onDuration: (dur: number) => void
}) {
  const mode = lengthMode(view.timeline, s.segment, s.shot)
  const [a, setA] = useState(fmt(s.in))
  const [b, setB] = useState(fmt(s.out))
  const [d, setD] = useState(fmt(s.duration))
  useEffect(() => {
    setA(fmt(s.in))
    setB(fmt(s.out))
    setD(fmt(s.duration))
  }, [s.idx, s.in, s.out, s.duration])
  if (!mode.trim && !mode.dur)
    return (
      <div>
        <div className="mb-1 text-[12px] font-medium text-muted-foreground">Length</div>
        <div className="text-[12px] text-subtle">{mode.why}</div>
      </div>
    )
  const trimChanged = mode.trim && (num(a) !== Math.round(s.in * 100) / 100 || num(b) !== Math.round(s.out * 100) / 100)
  const durChanged = num(d) !== Math.round(s.duration * 100) / 100
  const commitTrim = () => trimChanged && onTrim(num(a), num(b))
  const commitDur = () => durChanged && onDuration(num(d))
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        <Scissors className="size-3.5" /> Length
      </div>
      <div className="grid gap-2.5 rounded-2xl border border-border p-3">
        {mode.trim && (
          <div className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
            <Field label="Start (s)" value={a} onChange={setA} onCommit={commitTrim} />
            <Field label="End (s)" value={b} onChange={setB} onCommit={commitTrim} />
            <Button size="sm" variant="outline" className="h-8" disabled={!trimChanged} onClick={commitTrim}>
              Trim
            </Button>
            {clipDur != null && <span className="col-span-3 -mt-1 text-[11px] text-subtle">of the clip ({fmt(clipDur)} s long)</span>}
          </div>
        )}
        <div className="grid grid-cols-[1fr_auto] items-end gap-2">
          <Field
            label="Plays for (s)"
            value={d}
            onChange={setD}
            onCommit={commitDur}
            hint={s.voiceover ? "It keeps its start; the next shot starts right after it (instead of on its cue)." : s.beat_synced ? "Sets it off the beat grid." : `At least ${MIN_SHOT} s; B-roll reads best at 1 s+.`}
          />
          <Button size="sm" variant="outline" className="mb-auto mt-[18px] h-8" disabled={!durChanged} onClick={commitDur}>
            Set
          </Button>
        </div>
      </div>
    </div>
  )
}

function AddText({ onAdd }: { onAdd: (text: string) => void }) {
  const [text, setText] = useState("")
  const add = () => {
    if (!text.trim()) return
    onAdd(text.trim())
    setText("")
  }
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        <Type className="size-3.5" /> Text on this shot
      </div>
      <div className="flex gap-2">
        <Input name="new-text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="e.g. Incline bench" className="h-8 text-[13px]" />
        <Button size="sm" variant="outline" className="h-8" disabled={!text.trim()} onClick={add}>
          <Plus /> Add
        </Button>
      </div>
    </div>
  )
}

function ShotPanel({
  s,
  view,
  pid,
  files,
  clipDur,
  onTransition,
  onSwap,
  onDelete,
  onTrim,
  onDuration,
  onCaptions,
  onAddText,
}: {
  s: ResolvedShot
  view: TimelineView
  pid: string
  files: ProjectFile[]
  clipDur?: number | null
  onTransition: (t: string | null) => void
  onSwap: (f: ProjectFile) => void
  onDelete: () => void
  onTrim: (inS: number, outS: number) => void
  onDuration: (dur: number) => void
  onCaptions: (on: boolean) => void
  onAddText: (text: string) => void
}) {
  const src = shotSrc(view, s)
  const seg = view.timeline.segments[s.segment]
  const kind = s.voiceover ? "B-roll under the voiceover" : s.kind === "image" ? "Photo" : s.kind === "compare" ? "Before / after" : s.kind === "color" ? "Colour card" : s.said ? "Talking" : "Clip"
  const swappable = s.kind === "clip" || s.kind === "image"
  const words = s.heard ?? s.said
  const role = { voice: "your voice", ambient: "its own sound", mute: "muted (music / voiceover)" }[s.role] ?? s.role
  const spoken = Boolean(s.voiceover || (s.said && s.role === "voice"))
  const captionsOn = seg.captions !== false
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[16px] font-semibold tracking-[-0.01em]">Shot {s.idx}</div>
          <div className="mt-0.5 text-[12.5px] text-muted-foreground">
            {kind}
            {s.label && !s.label.startsWith("shot-") && <> · “{s.label}”</>}
          </div>
        </div>
        <span className="rounded-full bg-surface-2 px-2.5 py-1 font-mono text-[11.5px] text-foreground">{secs(s.duration)}</span>
      </div>

      <Why>{s.reason || (seg.type === "vo" ? seg.reason : null) || <span className="text-ink-soft">No reason recorded for this shot.</span>}</Why>

      {words && (
        <div className="rounded-2xl bg-surface-2/60 p-4">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
            <Quote className="size-3.5" /> {s.heard ? "Heard over it" : "Said in it"}
          </div>
          <div className="text-[13.5px] leading-relaxed text-foreground">“{words}”</div>
        </div>
      )}

      {s.warning && (
        <div className="flex gap-2 rounded-2xl border border-warn/40 bg-warn/10 p-3 text-[12.5px] text-warn-ink">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {s.warning}
        </div>
      )}

      <div className="divide-y divide-border rounded-2xl border border-border px-4 py-1">
        <Row k="Source">{basename(src) || "–"}</Row>
        {s.kind === "clip" && <Row k="Uses">{`${tc(s.in)} – ${tc(s.out)} of the clip`}</Row>}
        <Row k="Plays">{`${tc(s.start)} – ${tc(s.end)}`}</Row>
        <Row k="Sound">{role}</Row>
        {s.speed !== 1 && <Row k="Speed">{`${s.speed}×${s.ramp ? " (ramp)" : ""}`}</Row>}
        <Row k="On the beat">{s.beat_synced ? "yes" : "no"}</Row>
      </div>

      <LengthEditor s={s} view={view} clipDur={clipDur} onTrim={onTrim} onDuration={onDuration} />

      {spoken && (
        <label className="flex items-center justify-between gap-3 rounded-2xl border border-border px-4 py-3">
          <span>
            <span className="block text-[12.5px] font-medium text-foreground">{s.voiceover ? "Captions on this voiceover part" : "Captions on this shot"}</span>
            <span className="block text-[11.5px] text-muted-foreground">
              {view.captions?.enabled ? (s.voiceover ? "Applies to every B-roll shot under it." : "The words said here.") : "Captions are off for the whole video."}
            </span>
          </span>
          <Switch aria-label="Captions on this part" checked={captionsOn} disabled={!view.captions?.enabled} onCheckedChange={(v) => onCaptions(v)} />
        </label>
      )}

      <AddText onAdd={onAddText} />

      {s.idx > 1 && (
        <div>
          <div className="mb-2 text-[12px] font-medium text-muted-foreground">Into this shot</div>
          <div className="grid grid-cols-4 gap-1.5">
            {TRANSITIONS.map((t) => {
              const on = (s.transition ?? "") === t.id
              return (
                <button
                  key={t.id || "cut"}
                  onClick={() => onTransition(t.id || null)}
                  className={cn(
                    "flex h-14 flex-col items-center justify-center gap-1 rounded-2xl border text-[11.5px] font-medium transition",
                    on ? "border-transparent bg-accent text-accent-ink" : "border-border text-muted-foreground hover:border-ink/30 hover:text-foreground",
                  )}
                >
                  <t.icon className="size-4" />
                  {t.label}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="flex gap-2">
        {swappable && <SwapPicker files={files} pid={pid} current={src} onPick={onSwap} />}
        <Button variant="outline" size="sm" className="flex-1 hover:border-destructive/40 hover:text-destructive" onClick={onDelete}>
          <Trash2 /> Delete shot
        </Button>
      </div>
    </div>
  )
}

function TextPanel({ item, span, onChange, onDelete }: { item: TextOverlay; span?: { start: number; end: number }; onChange: (p: Partial<TextOverlay>) => void; onDelete: () => void }) {
  const [text, setText] = useState(item.text ?? "")
  const [sub, setSub] = useState(item.sub ?? "")
  useEffect(() => {
    setText(item.text ?? "")
    setSub(item.sub ?? "")
  }, [item.text, item.sub])
  const anchor = item.cue ? `when “${item.cue}” is said` : item.on ? (item.on.startsWith("shot-") ? `on shot ${item.on.slice(5).split("-")[0]}` : item.on.startsWith("#") ? `on shot ${item.on.slice(1)}` : `on “${item.on}”`) : "at a fixed time"
  const commit = () => {
    const p: Partial<TextOverlay> = {}
    if (text.trim() && text !== item.text) p.text = text.trim()
    if (sub !== (item.sub ?? "")) p.sub = sub.trim()
    if (Object.keys(p).length) onChange(p)
  }
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2 text-[16px] font-semibold tracking-[-0.01em]">
          <Type className="size-4 text-primary" /> Text on screen
        </div>
        <div className="mt-0.5 text-[12.5px] text-muted-foreground">
          Shows {anchor}
          {span && ` · ${tc(span.start)} – ${tc(span.end)}`}
        </div>
      </div>
      <div className="grid gap-3">
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Text</label>
          <Input name="overlay-text" value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
          <div className="mt-1 text-[11.5px] text-subtle">Wrap a word in *stars* for the emphasis colour.</div>
        </div>
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Second line</label>
          <Input value={sub} onChange={(e) => setSub(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} placeholder="e.g. 4 × 10" />
        </div>
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Style</label>
          <div className="flex flex-wrap gap-1.5">
            {STYLES.map((st) => (
              <button
                key={st}
                onClick={() => onChange({ style: st })}
                className={cn(
                  "h-7 rounded-full border px-3 text-[12px] font-medium transition",
                  item.style === st ? "border-transparent bg-accent text-accent-ink" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {st === "lower3" ? "lower third" : st}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Button variant="outline" size="sm" className="hover:border-destructive/40 hover:text-destructive" onClick={onDelete}>
        <Trash2 /> Remove text
      </Button>
    </div>
  )
}

function Overview({
  view,
  project,
  onRevise,
  revising,
  onEndCard,
}: {
  view: TimelineView
  project: Project
  onRevise: (notes: string) => void
  revising: boolean
  onEndCard: (on: boolean) => void
}) {
  const [notes, setNotes] = useState("")
  const texts = view.overlays.filter((o) => o.kind === "text").length
  const broll = view.overlays.filter((o) => o.kind === "broll").length
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="text-[16px] font-semibold tracking-[-0.01em]">The plan</div>
        <div className="mt-0.5 text-[12.5px] text-muted-foreground">Click a shot or a label to see why it's there.</div>
      </div>
      {project.plan_summary && <Why>{project.plan_summary}</Why>}
      <div className="divide-y divide-border rounded-2xl border border-border px-4 py-1">
        <Row k="Length">
          {clock(view.duration)}
          {view.target_length ? <span className="text-muted-foreground"> / target {clock(view.target_length)}</span> : null}
        </Row>
        <Row k="Shots">{view.shots.length}</Row>
        <Row k="Text on screen">{texts || "none"}</Row>
        {broll > 0 && <Row k="Cutaways">{broll}</Row>}
        <Row k="Captions">{view.captions?.enabled ? `on · ${view.captions.words ?? 0} words` : "off"}</Row>
        {view.music && (
          <Row k="Music">
            <span className="inline-flex items-center gap-1">
              <Music2 className="size-3" /> {Math.round(Number(view.music.bpm))} BPM
            </span>
          </Row>
        )}
        <div className="flex items-center justify-between gap-4 py-1.5 text-[12.5px]">
          <span className="shrink-0 text-muted-foreground">End card</span>
          <span className="flex min-w-0 items-center gap-2.5">
            <span className="truncate text-foreground">{view.end_card ? String(view.end_card.handle) : "off"}</span>
            <Switch size="sm" aria-label="End card" checked={Boolean(view.end_card)} onCheckedChange={(v) => onEndCard(v)} />
          </span>
        </div>
      </div>
      {(view.notes?.length ?? 0) > 0 && (
        <div>
          <div className="mb-2 text-[12px] font-medium text-muted-foreground">Editor's notes</div>
          <ul className="grid gap-2">
            {view.notes!.map((n, i) => (
              <li key={i} className="flex gap-2.5 text-[12.5px] leading-relaxed text-foreground">
                <Film className="mt-1 size-3 shrink-0 text-primary" />
                {n}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(view.problems?.length ?? 0) > 0 && (
        <div className="rounded-2xl border border-warn/40 bg-warn/10 p-3">
          <div className="mb-1.5 text-[12px] font-medium text-warn-ink">Worth a look</div>
          <ul className="grid gap-1 text-[12px] text-warn-ink">
            {view.problems!.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="rounded-2xl bg-surface-2/60 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-foreground">
          <Sparkles className="size-3.5 text-primary" /> Ask Claude to change something
        </div>
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder="Open on the bench set, and make the sticker say “5AM”" className="text-[13px]" />
        <Button size="sm" variant="outline" className="mt-2 w-full" disabled={!notes.trim() || revising} onClick={() => onRevise(notes.trim())}>
          {revising ? <Loader2 className="animate-spin" /> : <Send />} Revise the plan
        </Button>
      </div>
    </div>
  )
}

export function Inspector({
  view,
  project,
  files,
  selection,
  onTransition,
  onSwap,
  onDeleteShot,
  onText,
  onDeleteText,
  onRevise,
  revising,
  clipDur,
  onTrim,
  onDuration,
  onCaptions,
  onAddText,
  onEndCard,
}: {
  view: TimelineView
  project: Project
  files: ProjectFile[]
  selection: Selection
  onTransition: (s: ResolvedShot, t: string | null) => void
  onSwap: (s: ResolvedShot, f: ProjectFile) => void
  onDeleteShot: (s: ResolvedShot) => void
  onText: (index: number, p: Partial<TextOverlay>) => void
  onDeleteText: (index: number) => void
  onRevise: (notes: string) => void
  revising: boolean
  /** a source file's length in seconds, by its path in the plan */
  clipDur: (src: string | null | undefined) => number | null | undefined
  onTrim: (s: ResolvedShot, inS: number, outS: number) => void
  onDuration: (s: ResolvedShot, dur: number) => void
  onCaptions: (s: ResolvedShot, on: boolean) => void
  onAddText: (s: ResolvedShot, text: string) => void
  onEndCard: (on: boolean) => void
}) {
  const tl: Timeline = view.timeline
  if (selection?.type === "shot") {
    const s = view.shots.find((x) => x.idx === selection.idx)
    if (s)
      return (
        <ShotPanel
          s={s}
          view={view}
          pid={project.id}
          files={files}
          clipDur={clipDur(shotSrc(view, s))}
          onTransition={(t) => onTransition(s, t)}
          onSwap={(f) => onSwap(s, f)}
          onDelete={() => onDeleteShot(s)}
          onTrim={(a, b) => onTrim(s, a, b)}
          onDuration={(d) => onDuration(s, d)}
          onCaptions={(on) => onCaptions(s, on)}
          onAddText={(t) => onAddText(s, t)}
        />
      )
  }
  if (selection?.type === "overlay" && selection.kind === "text") {
    const item = (tl.text ?? [])[selection.index]
    const o = view.overlays.find((x) => x.kind === "text" && x.index === selection.index)
    if (item)
      return (
        <TextPanel
          item={item}
          span={o ? { start: o.start, end: o.end } : undefined}
          onChange={(p) => onText(selection.index, p)}
          onDelete={() => onDeleteText(selection.index)}
        />
      )
  }
  if (selection?.type === "overlay" && selection.kind === "broll") {
    const b = (tl.broll ?? [])[selection.index]
    const o = view.overlays.find((x) => x.kind === "broll" && x.index === selection.index)
    if (b)
      return (
        <div className="flex flex-col gap-4">
          <div>
            <div className="text-[16px] font-semibold tracking-[-0.01em]">Cutaway</div>
            <div className="mt-0.5 text-[12.5px] text-muted-foreground">B-roll over your talking; your voice keeps playing.</div>
          </div>
          <Thumb path={`${project.id}/${b.src}`} w={360} className="aspect-[9/16] w-32 rounded-xl shadow-soft" />
          <Why>{b.reason || "Covers the explanation with something to look at."}</Why>
          <div className="divide-y divide-border rounded-2xl border border-border px-4 py-1">
            <Row k="Source">{basename(b.src)}</Row>
            {o && <Row k="Plays">{`${tc(o.start)} – ${tc(o.end)}`}</Row>}
            {b.cue && <Row k="Cue">“{b.cue}”</Row>}
          </div>
        </div>
      )
  }
  return <Overview view={view} project={project} onRevise={onRevise} revising={revising} onEndCard={onEndCard} />
}
