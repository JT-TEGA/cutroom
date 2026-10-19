import { AnimatePresence, motion } from "framer-motion"
import { Clapperboard, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router"
import { toast } from "sonner"
import { isActive, useDeleteProject, useJobs, useProjects } from "@/api/queries"
import type { Job, ProjectSummary } from "@/api/types"
import { Page, PageHeader } from "@/components/Page"
import { EmptyState, ErrorState } from "@/components/States"
import { StatusBadge } from "@/components/StatusBadge"
import { Thumb } from "@/components/Thumb"
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { clock, timeAgo } from "@/lib/format"
import { GROUPS, groupOf, presetMeta } from "@/lib/presets"
import { STAGES, stageOf } from "@/lib/status"
import { cn } from "@/lib/utils"

const FILTERS = [{ id: "all", label: "All" }, ...GROUPS.map((g) => ({ id: g.id, label: g.label.split(" ")[0] }))]

function CardMenu({ onDelete }: { onDelete: () => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          aria-label="Project actions"
          className="absolute top-4 right-4 z-10 grid size-7 place-items-center rounded-full bg-surface/90 text-foreground opacity-0 shadow-soft backdrop-blur-md transition group-hover/card:opacity-100 hover:bg-surface data-[state=open]:opacity-100"
        >
          <MoreHorizontal className="size-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem variant="destructive" onClick={onDelete}>
          <Trash2 /> Delete project
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function NewTile() {
  return (
    <Link
      to="/new"
      className="group relative flex min-h-[320px] flex-col items-center justify-center overflow-hidden rounded-card border border-dashed border-ink/20 bg-surface/40 text-center transition hover:border-ink/40 hover:bg-surface/70"
    >
      <div className="pointer-events-none absolute -top-10 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-accent/60 opacity-0 blur-3xl transition group-hover:opacity-100" />
      <div className="relative grid size-11 place-items-center rounded-full bg-control text-control-ink shadow-pill transition group-hover:scale-105">
        <Plus className="size-5" />
      </div>
      <div className="relative mt-3 text-[14px] font-semibold">New video</div>
      <div className="relative mt-1 px-6 text-[12.5px] text-muted-foreground">Drop in clips, describe it, Claude plans the cut</div>
    </Link>
  )
}

export function Home() {
  const navigate = useNavigate()
  const projects = useProjects()
  const jobs = useJobs()
  const del = useDeleteProject()
  const [q, setQ] = useState("")
  const [filter, setFilter] = useState("all")
  const [confirm, setConfirm] = useState<ProjectSummary | null>(null)

  const activeJob = useMemo(() => {
    const m = new Map<string, Job>()
    for (const j of jobs.data ?? []) if (j.project_id && isActive(j) && !m.has(j.project_id)) m.set(j.project_id, j)
    return m
  }, [jobs.data])

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (projects.data ?? []).filter((p) => {
      if (filter !== "all" && groupOf(p.content_type)?.id !== filter) return false
      if (!needle) return true
      return [p.name, presetMeta(p.content_type).title, p.content_type ?? ""].some((s) => s.toLowerCase().includes(needle))
    })
  }, [projects.data, q, filter])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const p of projects.data ?? []) c[stageOf(p.status)] = (c[stageOf(p.status)] ?? 0) + 1
    return c
  }, [projects.data])

  const total = projects.data?.length ?? 0

  return (
    <Page wide>
      <PageHeader
        title="Projects"
        description={
          total ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>{total} videos</span>
              {(["review", "planning", "rendering", "done"] as const)
                .filter((s) => counts[s])
                .map((s) => (
                  <span key={s} className="inline-flex items-center gap-1.5">
                    <span className={cn("size-1.5 rounded-full", STAGES[s].dot)} />
                    {counts[s]} {STAGES[s].label.toLowerCase()}
                  </span>
                ))}
            </span>
          ) : (
            "Every video you're making, from the first upload to the final cut."
          )
        }
        actions={
          <Button onClick={() => navigate("/new")}>
            <Plus /> New video
          </Button>
        }
      />

      {total > 0 && (
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="relative w-72 max-w-full">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search projects"
              className="h-9 border-transparent pl-9 shadow-soft"
            />
          </div>
          <div className="flex h-9 items-center rounded-full bg-surface p-1 shadow-soft">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  "relative h-7 rounded-full px-3.5 text-[13px] font-medium text-ink-soft transition-colors hover:text-foreground",
                  filter === f.id && "text-accent-ink",
                )}
              >
                {filter === f.id && (
                  <motion.span layoutId="home-filter" className="absolute inset-0 rounded-full bg-accent" />
                )}
                <span className="relative">{f.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {projects.isLoading ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(216px,1fr))] gap-5">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[4/5] rounded-card" />
          ))}
        </div>
      ) : projects.error ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : total === 0 ? (
        <EmptyState
          className="py-24"
          icon={<Clapperboard className="size-5" />}
          title="Make your first video"
          description="Pick what kind of video it is, drop in your clips, a voice memo and a track, and say what you want. Claude plans the cut; you approve it before anything renders."
          action={
            <Button onClick={() => navigate("/new")}>
              <Plus /> New video
            </Button>
          }
        />
      ) : list.length === 0 ? (
        <div className="py-20 text-center text-[13.5px] text-muted-foreground">No projects match that.</div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(216px,1fr))] gap-5">
          {filter === "all" && !q && <NewTile />}
          <AnimatePresence mode="popLayout">
            {list.map((p) => (
              <div key={p.id} className="group/card relative">
                <ProjectCard p={p} job={activeJob.get(p.id)} />
                <CardMenu onDelete={() => setConfirm(p)} />
              </div>
            ))}
          </AnimatePresence>
        </div>
      )}

      <AlertDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{confirm?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Its uploads, plans and every rendered version are removed from the workspace. This can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-control-ink hover:bg-destructive/90"
              onClick={() =>
                confirm &&
                del.mutate(confirm.id, { onSuccess: () => toast.success(`Deleted “${confirm.name}”`) })
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Page>
  )
}

/** A project card; its menu sits on top of it (outside the link) so clicking the menu doesn't open the project. */
function ProjectCard({ p, job }: { p: ProjectSummary; job?: Job }) {
  const meta = presetMeta(p.content_type)
  const Icon = meta.icon
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }}>
      <Link
        to={`/projects/${p.id}`}
        className="group relative block rounded-card bg-card p-2 shadow-soft transition duration-300 hover:-translate-y-0.5 hover:shadow-lift"
      >
        <div className="relative aspect-[4/5] overflow-hidden rounded-2xl">
          <Thumb
            path={p.thumbnail}
            w={480}
            className="absolute inset-0"
            imgClassName="transition-transform duration-700 group-hover:scale-[1.04]"
          />
          <div className="absolute top-2 left-2">
            <StatusBadge status={p.status} />
          </div>
          {p.duration != null && !job && (
            <div className="absolute top-2 right-2 rounded-full bg-control/75 px-2 py-0.5 font-mono text-[11px] text-control-ink backdrop-blur-md transition group-hover:opacity-0">
              {clock(p.duration)}
            </div>
          )}
          {p.open_questions > 0 && !job && (
            <div className="absolute top-10 left-2 rounded-full bg-accent px-2.5 py-0.5 text-[11px] font-medium text-accent-ink shadow-soft">
              {p.open_questions} question{p.open_questions > 1 ? "s" : ""} for you
            </div>
          )}
        </div>
        <div className="px-2 pt-3 pb-1.5">
          {job && (
            <div className="mb-2.5">
              <div className="mb-1.5 flex justify-between gap-2 text-[11px] text-ink-soft">
                <span className="truncate capitalize">{job.status === "queued" ? "Waiting its turn" : job.step}</span>
                <span className="font-mono">{Math.round(job.progress)}%</span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-ink/10">
                <motion.div
                  className={cn("h-full rounded-full", job.kind === "render" ? "bg-info" : "bg-ink")}
                  animate={{ width: `${Math.max(4, job.progress)}%` }}
                  transition={{ ease: "easeOut" }}
                />
              </div>
            </div>
          )}
          <div className="truncate text-[15px] font-semibold tracking-[-0.01em]">{p.name}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-soft">
            <Icon className="size-3.5 shrink-0" />
            <span className="truncate">{meta.title}</span>
            <span aria-hidden>·</span>
            <span className="shrink-0">{p.latest_version ? `v${p.latest_version}` : `${p.files} files`}</span>
            <span aria-hidden>·</span>
            <span className="shrink-0">{timeAgo(p.updated_at)}</span>
          </div>
        </div>
      </Link>
    </motion.div>
  )
}

