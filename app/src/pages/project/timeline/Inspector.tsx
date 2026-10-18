import { AlertTriangle, ArrowLeftRight, Film, Loader2, Music2, Quote, Repeat2, Send, Sparkles, Trash2, Type, Wind, Zap, ZoomIn } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"
import type { Project, ProjectFile, ResolvedShot, TextOverlay, Timeline, TimelineView } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Textarea } from "@/components/ui/textarea"
import { basename, clock, secs, tc } from "@/lib/format"
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
      <span className="min-w-0 truncate text-right text-zinc-200">{children}</span>
    </div>
  )
}

function Why({ children }: { children: ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-primary/25 bg-gradient-to-br from-primary/[0.14] to-primary/[0.03] p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] text-violet-200 uppercase">
        <Sparkles className="size-3.5" /> Why this cut
      </div>
      <div className="text-[13.5px] leading-relaxed text-violet-50">{children}</div>
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
      <PopoverContent align="start" className="w-[300px] border-white/10 bg-popover p-3">
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
              <Thumb path={`${pid}/${f.path}`} w={140} className="aspect-[9/16] rounded-md border border-white/10 transition group-hover:border-primary" />
              <div className="mt-1 truncate text-[10.5px] text-muted-foreground">{f.name}</div>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function ShotPanel({
  s,
  view,
  pid,
  files,
  onTransition,
  onSwap,
  onDelete,
}: {
  s: ResolvedShot
  view: TimelineView
  pid: string
  files: ProjectFile[]
  onTransition: (t: string | null) => void
  onSwap: (f: ProjectFile) => void
  onDelete: () => void
}) {
  const src = shotSrc(view, s)
  const seg = view.timeline.segments[s.segment]
  const kind = s.voiceover ? "B-roll under the voiceover" : s.kind === "image" ? "Photo" : s.kind === "compare" ? "Before / after" : s.kind === "color" ? "Colour card" : s.said ? "Talking" : "Clip"
  const swappable = s.kind === "clip" || s.kind === "image"
  const words = s.heard ?? s.said
  const role = { voice: "your voice", ambient: "its own sound", mute: "muted (music / voiceover)" }[s.role] ?? s.role
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
        <span className="rounded-md bg-white/[0.05] px-2 py-1 font-mono text-[11.5px] text-zinc-300">{secs(s.duration)}</span>
      </div>

      <Why>{s.reason || (seg.type === "vo" ? seg.reason : null) || <span className="text-violet-200/60">No reason recorded for this shot.</span>}</Why>

      {words && (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
            <Quote className="size-3.5" /> {s.heard ? "Heard over it" : "Said in it"}
          </div>
          <div className="text-[13.5px] leading-relaxed text-zinc-200">“{words}”</div>
        </div>
      )}

      {s.warning && (
        <div className="flex gap-2 rounded-xl border border-warn/25 bg-warn/[0.06] p-3 text-[12.5px] text-amber-100">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" /> {s.warning}
        </div>
      )}

      <div className="divide-y divide-white/[0.05] rounded-xl border border-white/[0.06] px-4 py-1">
        <Row k="Source">{basename(src) || "–"}</Row>
        {s.kind === "clip" && <Row k="Uses">{`${tc(s.in)} – ${tc(s.out)} of the clip`}</Row>}
        <Row k="Plays">{`${tc(s.start)} – ${tc(s.end)}`}</Row>
        <Row k="Sound">{role}</Row>
        {s.speed !== 1 && <Row k="Speed">{`${s.speed}×${s.ramp ? " (ramp)" : ""}`}</Row>}
        <Row k="On the beat">{s.beat_synced ? "yes" : "no"}</Row>
      </div>

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
                    "flex h-14 flex-col items-center justify-center gap-1 rounded-lg border text-[11.5px] font-medium transition",
                    on ? "border-primary/60 bg-primary/15 text-white" : "border-white/[0.07] text-muted-foreground hover:border-white/15 hover:text-foreground",
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
        <Button variant="outline" size="sm" className="flex-1 hover:border-destructive/40 hover:text-red-200" onClick={onDelete}>
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
          <Input name="overlay-text" value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} className="bg-white/[0.03]" />
          <div className="mt-1 text-[11.5px] text-subtle">Wrap a word in *stars* for the emphasis colour.</div>
        </div>
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Second line</label>
          <Input value={sub} onChange={(e) => setSub(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} placeholder="e.g. 4 × 10" className="bg-white/[0.03]" />
        </div>
        <div>
          <label className="mb-1.5 block text-[12px] font-medium text-muted-foreground">Style</label>
          <div className="flex flex-wrap gap-1.5">
            {STYLES.map((st) => (
              <button
                key={st}
                onClick={() => onChange({ style: st })}
                className={cn(
                  "h-7 rounded-md border px-2.5 text-[12px] font-medium transition",
                  item.style === st ? "border-primary/60 bg-primary/15 text-white" : "border-white/[0.07] text-muted-foreground hover:text-foreground",
                )}
              >
                {st === "lower3" ? "lower third" : st}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Button variant="outline" size="sm" className="hover:border-destructive/40 hover:text-red-200" onClick={onDelete}>
        <Trash2 /> Remove text
      </Button>
    </div>
  )
}

function Overview({ view, project, onRevise, revising }: { view: TimelineView; project: Project; onRevise: (notes: string) => void; revising: boolean }) {
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
      <div className="divide-y divide-white/[0.05] rounded-xl border border-white/[0.06] px-4 py-1">
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
        <Row k="End card">{view.end_card ? String(view.end_card.handle) : "off"}</Row>
      </div>
      {(view.notes?.length ?? 0) > 0 && (
        <div>
          <div className="mb-2 text-[12px] font-medium text-muted-foreground">Editor's notes</div>
          <ul className="grid gap-2">
            {view.notes!.map((n, i) => (
              <li key={i} className="flex gap-2.5 text-[12.5px] leading-relaxed text-zinc-300">
                <Film className="mt-1 size-3 shrink-0 text-primary" />
                {n}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(view.problems?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-warn/20 bg-warn/[0.05] p-3">
          <div className="mb-1.5 text-[12px] font-medium text-amber-200">Worth a look</div>
          <ul className="grid gap-1 text-[12px] text-amber-100/80">
            {view.problems!.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
        <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-zinc-300">
          <Sparkles className="size-3.5 text-primary" /> Ask Claude to change something
        </div>
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder="Open on the bench set, and make the sticker say “5AM”" className="bg-black/20 text-[13px]" />
        <Button size="sm" className="mt-2 w-full" disabled={!notes.trim() || revising} onClick={() => onRevise(notes.trim())}>
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
          onTransition={(t) => onTransition(s, t)}
          onSwap={(f) => onSwap(s, f)}
          onDelete={() => onDeleteShot(s)}
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
          <Thumb path={`${project.id}/${b.src}`} w={360} className="aspect-[9/16] w-32 rounded-lg border border-white/10" />
          <Why>{b.reason || "Covers the explanation with something to look at."}</Why>
          <div className="divide-y divide-white/[0.05] rounded-xl border border-white/[0.06] px-4 py-1">
            <Row k="Source">{basename(b.src)}</Row>
            {o && <Row k="Plays">{`${tc(o.start)} – ${tc(o.end)}`}</Row>}
            {b.cue && <Row k="Cue">“{b.cue}”</Row>}
          </div>
        </div>
      )
  }
  return <Overview view={view} project={project} onRevise={onRevise} revising={revising} />
}
