import {
  type CollisionDetection,
  closestCenter,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
} from "@dnd-kit/core"
import { Clapperboard, Film, Loader2, Minus, Plus, RefreshCw, Undo2, Wand2 } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"
import { useSaveTimeline, useStartJob, useTimeline } from "@/api/queries"
import type { ProjectFile, ResolvedShot, TextOverlay, Timeline } from "@/api/types"
import { EmptyState, ErrorState } from "@/components/States"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { clock, pluralize } from "@/lib/format"
import { deleteShot, deleteText, moveSegment, pinAnchors, setTransition, swapSource, updateText } from "@/lib/timeline-edit"
import { cn } from "@/lib/utils"
import { useProjectCtx } from "../ProjectLayout"
import { Inspector } from "./Inspector"
import { BinTile, MediaBin } from "./MediaBin"
import { Monitor } from "./Monitor"
import { type Selection, Track } from "./Track"

/** Bin clips land on shots (to swap); segments land on segments (to reorder). */
const collision: CollisionDetection = (args) => {
  const bin = args.active.data.current?.type === "bin"
  const containers = args.droppableContainers.filter((c) => c.data.current?.type === (bin ? "shot" : "segment"))
  return (bin ? pointerWithin : closestCenter)({ ...args, droppableContainers: containers })
}

function srcsOf(tl: Timeline): Set<string> {
  const out = new Set<string>()
  for (const s of tl.segments) {
    if (s.src) out.add(s.src)
    for (const sh of s.shots ?? []) if (sh.src) out.add(sh.src)
    if (s.a?.src) out.add(s.a.src)
    if (s.b?.src) out.add(s.b.src)
  }
  for (const b of tl.broll ?? []) out.add(b.src)
  return out
}

export function TimelineReview() {
  const { project, activeJob } = useProjectCtx()
  const pid = project.id
  const navigate = useNavigate()
  const tlq = useTimeline(pid, project.plan_version > 0)
  const save = useSaveTimeline(pid)
  const start = useStartJob(pid)
  const [selection, setSelection] = useState<Selection>(null)
  const [pps, setPps] = useState<number | null>(null)
  const [history, setHistory] = useState<Timeline[]>([])
  const [dragging, setDragging] = useState<ProjectFile | null>(null)
  const [confirmRegen, setConfirmRegen] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const view = tlq.data
  const files = useMemo(() => project.files ?? [], [project.files])
  const used = useMemo(() => (view ? srcsOf(view.timeline) : new Set<string>()), [view])

  // fit the whole edit in the track by default (zoom in from there)
  const [trackW, setTrackW] = useState(1000)
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const ro = new ResizeObserver(() => setTrackW(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [view === undefined])
  const total = view ? Math.max(view.duration, Number(view.end_card?.end ?? 0)) : 1
  const fit = Math.max(24, Math.min(140, (trackW - 130) / Math.max(1, total)))
  const zoom = pps ?? fit

  const shots = view?.shots ?? []
  const selShot = selection?.type === "shot" ? shots.find((s) => s.idx === selection.idx) : undefined
  const monitorShot = selShot ?? (selection?.type === "overlay" && view ? shots.find((s) => {
    const o = view.overlays.find((x) => x.kind === selection.kind && x.index === selection.index)
    return o && s.start <= o.start + 0.01 && s.end > o.start
  }) : undefined) ?? shots[0]

  const apply = useCallback(
    (next: Timeline, message?: string) => {
      if (!view) return
      setHistory((h) => [...h.slice(-19), view.timeline])
      save.mutate(next, {
        onSuccess: () => message && toast.success(message),
        onError: () => {
          setHistory((h) => h.slice(0, -1))
          tlq.refetch()
        },
      })
    },
    [view, save, tlq],
  )
  const base = () => pinAnchors(view!.timeline, view!)

  const undo = useCallback(() => {
    const prev = history[history.length - 1]
    if (!prev) return
    setHistory((h) => h.slice(0, -1))
    save.mutate(prev, { onSuccess: () => toast("Undone") })
  }, [history, save])

  const removeShot = useCallback(
    (s: ResolvedShot) => {
      try {
        const { timeline, removed } = deleteShot(pinAnchors(view!.timeline, view!), s.segment, s.shot)
        setSelection(null)
        apply(timeline, `Shot ${s.idx} deleted${removed ? ` with ${pluralize(removed, "label")} on it` : ""}`)
      } catch (e) {
        toast.error((e as Error).message)
      }
    },
    [view, apply],
  )

  // keyboard: ← → pick shots, Delete removes, ⌘Z undoes, Esc clears
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest("input, textarea, [contenteditable]")) return
      if ((e.metaKey || e.ctrlKey) && e.key === "z") {
        e.preventDefault()
        undo()
      } else if (e.key === "Escape") setSelection(null)
      else if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && shots.length) {
        e.preventDefault()
        const at = selShot ? shots.indexOf(selShot) : -1
        const next = shots[Math.max(0, Math.min(shots.length - 1, at + (e.key === "ArrowRight" ? 1 : -1)))]
        setSelection({ type: "shot", idx: next.idx })
        scroller.current?.querySelector(`[data-shot="${next.idx}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" })
      } else if ((e.key === "Delete" || e.key === "Backspace") && selShot) {
        e.preventDefault()
        removeShot(selShot)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [shots, selShot, undo, removeShot])

  if (project.plan_version === 0 || tlq.error) {
    const planning = activeJob && ["plan", "revise"].includes(activeJob.kind)
    if (tlq.error && (tlq.error as { status?: number }).status !== 404) return <div className="p-8"><ErrorState error={tlq.error} onRetry={() => tlq.refetch()} /></div>
    return (
      <div className="mx-auto max-w-[760px] p-8 pt-16">
        <EmptyState
          icon={<Clapperboard className="size-5" />}
          title={planning ? "Claude is planning this one" : "No plan yet"}
          description={planning ? "The timeline appears here as soon as the plan is ready." : "Finish the brief and generate a plan: the timeline shows up here for you to review."}
          action={
            <Button asChild>
              <Link to={planning ? `/projects/${pid}/jobs/${activeJob!.id}` : `/projects/${pid}/setup/review`}>{planning ? "Watch progress" : "Go to the brief"}</Link>
            </Button>
          }
        />
      </div>
    )
  }
  if (!view)
    return (
      <div className="grid gap-4 p-6">
        <Skeleton className="h-10 w-96 bg-white/[0.04]" />
        <div className="grid grid-cols-[250px_1fr_340px] gap-4">
          <Skeleton className="h-[440px] bg-white/[0.04]" />
          <Skeleton className="h-[440px] bg-white/[0.04]" />
          <Skeleton className="h-[440px] bg-white/[0.04]" />
        </div>
        <Skeleton className="h-60 bg-white/[0.04]" />
      </div>
    )

  const onDragStart = (e: DragStartEvent) => {
    if (e.active.data.current?.type === "bin") setDragging(files.find((f) => f.id === e.active.data.current?.fileId) ?? null)
  }
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null)
    const a = e.active.data.current
    const o = e.over?.data.current
    if (!a || !o) return
    if (a.type === "segment" && o.type === "segment" && a.segment !== o.segment) {
      apply(moveSegment(base(), a.segment, o.segment), "Moved")
    } else if (a.type === "bin" && o.type === "shot") {
      const f = files.find((x) => x.id === a.fileId)
      if (f) {
        apply(swapSource(base(), o.segment, o.shot, f), `${f.name} is now shot ${o.idx}`)
        setSelection({ type: "shot", idx: o.idx })
      }
    }
  }

  const over = view.target_length ? view.duration - view.target_length : 0
  const rendering = activeJob?.kind === "render"

  return (
    <DndContext sensors={sensors} collisionDetection={collision} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
      <div className="flex h-[calc(100vh-56px)] min-h-[720px] flex-col">
        {/* action bar */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-white/[0.06] px-6 py-3.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h1 className="text-[17px] font-semibold tracking-[-0.01em]">Review the plan</h1>
              <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">plan v{project.plan_version}</span>
              {save.isPending && (
                <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" /> Saving
                </span>
              )}
            </div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12.5px] text-muted-foreground">
              <span>{clock(view.duration)} long</span>
              {view.target_length ? (
                <span className={cn(Math.abs(over) > 5 && "text-warn")}>
                  target {clock(view.target_length)} ({over >= 0 ? "+" : "−"}
                  {Math.abs(over).toFixed(0)}s)
                </span>
              ) : null}
              <span>{pluralize(view.shots.length, "shot")}</span>
              <span>{pluralize(view.overlays.filter((o) => o.kind === "text").length, "label")}</span>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" disabled={!history.length || save.isPending} onClick={undo}>
                  <Undo2 /> Undo
                </Button>
              </TooltipTrigger>
              <TooltipContent>⌘Z</TooltipContent>
            </Tooltip>
            <Button variant="outline" size="sm" disabled={start.isPending} onClick={() => setConfirmRegen(true)}>
              <RefreshCw /> Regenerate plan
            </Button>
            <Button
              disabled={start.isPending || save.isPending || rendering}
              onClick={() => start.mutate({ kind: "render" }, { onSuccess: (j) => navigate(`/projects/${pid}/jobs/${j.id}`) })}
            >
              {start.isPending ? <Loader2 className="animate-spin" /> : <Film />}
              {rendering ? "Rendering…" : "Approve & render"}
            </Button>
          </div>
        </div>

        {/* bin · monitor · inspector */}
        <div className="grid min-h-0 flex-1 grid-cols-[236px_1fr_340px] gap-0 max-xl:grid-cols-[200px_1fr_310px]">
          <div className="min-h-0 border-r border-white/[0.06] p-4">
            <MediaBin files={files} pid={pid} used={used} />
          </div>
          <div className="min-h-0 bg-[radial-gradient(ellipse_at_center,rgb(124_92_255/0.07),transparent_65%)] p-5">
            <Monitor
              view={view}
              pid={pid}
              shot={monitorShot}
              onPrev={() => {
                const at = monitorShot ? shots.indexOf(monitorShot) : 0
                setSelection({ type: "shot", idx: shots[Math.max(0, at - 1)].idx })
              }}
              onNext={() => {
                const at = monitorShot ? shots.indexOf(monitorShot) : -1
                setSelection({ type: "shot", idx: shots[Math.min(shots.length - 1, at + 1)].idx })
              }}
            />
          </div>
          <div className="min-h-0 overflow-y-auto border-l border-white/[0.06] p-5">
            <Inspector
              view={view}
              project={project}
              files={files.filter((f) => f.kind === "clip" || f.kind === "photo")}
              selection={selection}
              onTransition={(s, t) => apply(setTransition(base(), s.segment, s.shot, t))}
              onSwap={(s, f) => apply(swapSource(base(), s.segment, s.shot, f), `${f.name} is now shot ${s.idx}`)}
              onDeleteShot={removeShot}
              onText={(i, p) => apply(updateText(view.timeline, i, p as Partial<TextOverlay>))}
              onDeleteText={(i) => {
                setSelection(null)
                apply(deleteText(view.timeline, i), "Text removed")
              }}
              revising={start.isPending}
              onRevise={(notes) => start.mutate({ kind: "revise", notes }, { onSuccess: (j) => navigate(`/projects/${pid}/jobs/${j.id}`) })}
            />
          </div>
        </div>

        {/* the timeline */}
        <div className="border-t border-white/[0.06] bg-[#0b0b0e]">
          <div className="flex items-center gap-4 px-5 pt-3 pb-1 text-[11.5px] text-muted-foreground">
            <span className="font-medium text-zinc-300">Timeline</span>
            <span className="max-lg:hidden">Drag shots to reorder · drop a clip from Media onto a shot to swap · ← → to step · Delete to remove</span>
            <span className="ml-auto inline-flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5">
                <span className="size-1.5 rounded-full bg-warn" /> on the beat
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Wand2 className="size-3 text-primary" /> transition
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-white/[0.07] p-0.5">
                <button className="rounded p-0.5 hover:bg-white/10" onClick={() => setPps(Math.max(16, zoom / 1.4))} aria-label="Zoom out">
                  <Minus className="size-3.5" />
                </button>
                <button className="px-1 font-mono text-[10.5px] hover:text-foreground" onClick={() => setPps(null)} title="Fit">
                  fit
                </button>
                <button className="rounded p-0.5 hover:bg-white/10" onClick={() => setPps(Math.min(240, zoom * 1.4))} aria-label="Zoom in">
                  <Plus className="size-3.5" />
                </button>
              </span>
            </span>
          </div>
          <div ref={scroller} className="overflow-x-auto overflow-y-hidden px-1 pt-5 pb-4" onClick={(e) => e.target === e.currentTarget && setSelection(null)}>
            <Track view={view} pid={pid} pps={zoom} selection={selection} onSelect={setSelection} />
          </div>
        </div>
      </div>

      <DragOverlay dropAnimation={null}>{dragging ? <BinTile file={dragging} pid={pid} overlay /> : null}</DragOverlay>

      <AlertDialog open={confirmRegen} onOpenChange={setConfirmRegen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Plan it again from scratch?</AlertDialogTitle>
            <AlertDialogDescription>
              Claude builds a fresh plan from the brief and your clips. Edits you made here are replaced (the current plan is kept in the
              project's history). To change only some things, use “Ask Claude to change something” instead.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep this plan</AlertDialogCancel>
            <AlertDialogAction onClick={() => start.mutate({ kind: "plan" }, { onSuccess: (j) => navigate(`/projects/${pid}/jobs/${j.id}`) })}>
              Regenerate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </DndContext>
  )
}
