import { AlertTriangle, ChevronRight, Loader2, RotateCw, X } from "lucide-react"
import { useEffect, useState } from "react"
import { Link, NavLink, Outlet, useLocation, useNavigate, useOutletContext, useParams } from "react-router"
import { isActive, useJobs, usePatchProject, useProject, useRetryJob } from "@/api/queries"
import type { Job, Project } from "@/api/types"
import { JOB_COPY } from "@/api/jobs"
import { Page } from "@/components/Page"
import { ErrorState } from "@/components/States"
import { StatusBadge } from "@/components/StatusBadge"
import { TypeBadge } from "@/components/TypeBadge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type Ctx = { project: Project; activeJob: Job | undefined; lastJob: Job | undefined }
export const useProjectCtx = () => useOutletContext<Ctx>()

function EditableName({ project }: { project: Project }) {
  const patch = usePatchProject(project.id)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(project.name)
  useEffect(() => setValue(project.name), [project.name])
  const save = () => {
    setEditing(false)
    const v = value.trim()
    if (v && v !== project.name) patch.mutate({ name: v, brief: { title: v } })
    else setValue(project.name)
  }
  if (editing)
    return (
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save()
          if (e.key === "Escape") {
            setValue(project.name)
            setEditing(false)
          }
        }}
        className="h-8 w-72 rounded-md border border-primary/50 bg-white/[0.04] px-2 text-[17px] font-semibold tracking-[-0.01em] outline-none"
      />
    )
  return (
    <button
      onClick={() => setEditing(true)}
      title="Rename"
      className="-mx-2 h-8 truncate rounded-md px-2 text-[17px] font-semibold tracking-[-0.01em] transition hover:bg-white/[0.05]"
    >
      {project.name}
    </button>
  )
}

function Tabs({ project }: { project: Project }) {
  const base = `/projects/${project.id}`
  const tabs = [
    { to: `${base}/setup/review`, match: "/setup", label: "Brief", enabled: true },
    { to: `${base}/plan`, match: "/plan", label: "Plan", enabled: project.plan_version > 0 },
    { to: `${base}/video`, match: "/video", label: "Video", enabled: (project.renders?.length ?? 0) > 0 },
  ]
  const { pathname } = useLocation()
  return (
    <div className="flex h-9 items-center rounded-lg border border-white/[0.07] bg-white/[0.02] p-1">
      {tabs.map((t) =>
        t.enabled ? (
          <NavLink
            key={t.label}
            to={t.to}
            className={cn(
              "h-7 rounded-md px-3 text-[13px] leading-7 font-medium text-muted-foreground transition-colors hover:text-foreground",
              pathname.includes(t.match) && "bg-white/[0.08] text-foreground",
            )}
          >
            {t.label}
          </NavLink>
        ) : (
          <span key={t.label} className="h-7 px-3 text-[13px] leading-7 font-medium text-subtle/70">
            {t.label}
          </span>
        ),
      )}
    </div>
  )
}

function JobPill({ job, pid }: { job: Job; pid: string }) {
  const copy = JOB_COPY[job.kind as keyof typeof JOB_COPY]
  return (
    <Link
      to={`/projects/${pid}/jobs/${job.id}`}
      className="inline-flex h-9 items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-3 text-[13px] font-medium text-violet-100 transition hover:bg-primary/15"
    >
      <Loader2 className="size-3.5 animate-spin" />
      {copy?.title ?? job.kind}
      <span className="font-mono text-[12px] text-violet-200/70">{Math.round(job.progress)}%</span>
    </Link>
  )
}

export function ProjectLayout() {
  const { pid = "" } = useParams()
  const project = useProject(pid)
  const jobs = useJobs(pid)
  const retry = useRetryJob()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [hideError, setHideError] = useState<string | null>(null)

  if (project.isLoading)
    return (
      <Page wide>
        <Skeleton className="mb-8 h-9 w-80 bg-white/[0.04]" />
        <Skeleton className="h-[480px] w-full rounded-2xl bg-white/[0.04]" />
      </Page>
    )
  if (project.error || !project.data)
    return (
      <Page>
        <ErrorState error={project.error} onRetry={() => project.refetch()} className="mt-12" />
      </Page>
    )

  const p = project.data
  const activeJob = jobs.data?.find(isActive)
  const lastJob = jobs.data?.[0]
  const onJobPage = pathname.includes("/jobs/")
  const err = p.last_error as { code?: string; message?: string; hint?: string } | null
  const failedJob = lastJob && ["failed", "interrupted"].includes(lastJob.status) ? lastJob : undefined
  const errKey = `${p.id}-${err?.message}`

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#08080a]/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-3 px-8 max-xl:px-6">
          <Link to="/" className="text-[13.5px] text-muted-foreground transition hover:text-foreground">
            Projects
          </Link>
          <ChevronRight className="size-3.5 text-subtle" />
          <div className="flex min-w-0 items-center gap-2.5">
            <EditableName project={p} />
            <TypeBadge type={p.brief?.content_type} className="max-lg:hidden" />
            <StatusBadge status={p.status} className="bg-transparent backdrop-blur-none" />
          </div>
          <div className="ml-auto flex items-center gap-2">
            {activeJob && !onJobPage && <JobPill job={activeJob} pid={p.id} />}
            <Tabs project={p} />
          </div>
        </div>
      </header>

      {err?.message && p.status === "error" && !onJobPage && hideError !== errKey && (
        <div className="mx-auto mt-4 w-full max-w-[1600px] px-8 max-xl:px-6">
          <div className="flex items-start gap-3 rounded-xl border border-destructive/25 bg-destructive/[0.06] px-4 py-3">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">{err.message}</div>
              {err.hint && <div className="mt-0.5 text-[12.5px] text-muted-foreground">{err.hint}</div>}
            </div>
            {failedJob && (
              <Button
                size="xs"
                variant="outline"
                onClick={() => retry.mutate(failedJob.id, { onSuccess: (j) => navigate(`/projects/${p.id}/jobs/${j.id}`) })}
              >
                <RotateCw /> Retry {failedJob.kind}
              </Button>
            )}
            <button onClick={() => setHideError(errKey)} className="rounded p-1 text-muted-foreground hover:text-foreground">
              <X className="size-3.5" />
            </button>
          </div>
        </div>
      )}

      <Outlet context={{ project: p, activeJob, lastJob } satisfies Ctx} />
    </div>
  )
}
