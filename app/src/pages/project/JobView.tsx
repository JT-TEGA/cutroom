import { AnimatePresence, motion } from "framer-motion"
import { AlertTriangle, ArrowLeft, Check, ChevronDown, Circle, Clock, Loader2, Minus, RotateCw, Terminal, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router"
import { api, call } from "@/api/client"
import { isBrainStep, JOB_COPY, JOB_STAGES, stageIndex, useJobStream } from "@/api/jobs"
import { useRetryJob, useStartJob } from "@/api/queries"
import type { JobKind } from "@/api/types"
import { BrainOrb } from "@/components/BrainOrb"
import { Page } from "@/components/Page"
import { ErrorState } from "@/components/States"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useProjectCtx } from "./ProjectLayout"

const BRAIN_SUB: Record<JobKind, string> = {
  analyse: "Checking the brief against your clips and the preset, so it can ask everything it needs in one go.",
  plan: "Picking the best takes, matching B-roll to your words, placing labels and writing a reason for every cut.",
  revise: "Changing only what your notes ask for and keeping everything else as it was.",
  render: "",
  reference: "Reading the reel's hook, pacing, text and grade.",
  "photos-import": "",
}

function useElapsed(since: string | null | undefined, running: boolean) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [running])
  if (!since) return null
  const s = Math.max(0, Math.round((now - new Date(since).getTime()) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

function Log({ lines }: { lines: string[] }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLPreElement>(null)
  useEffect(() => {
    if (open && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [open, lines.length])
  return (
    <div className="mt-6 overflow-hidden rounded-xl border border-white/[0.06] bg-[#0b0b0e]">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2.5 px-4 py-3 text-left text-[12.5px] text-muted-foreground transition hover:text-foreground">
        <Terminal className="size-3.5" />
        <span className="flex-1">{open ? "Hide" : "Show"} log</span>
        <span className="font-mono text-[11px] text-subtle">{pluralize(lines.length, "line")}</span>
        <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <pre ref={box} className="max-h-72 overflow-auto border-t border-white/[0.05] px-4 py-3 font-mono text-[11.5px] leading-[1.7] break-all whitespace-pre-wrap text-zinc-400">
              {lines.length ? lines.map((l, i) => (
                <div key={i} className={cn(/FAILED|error|!!/.test(l) && "text-red-300", /^\s*brain:/.test(l) && "text-violet-300")}>
                  {l}
                </div>
              )) : "Waiting for output…"}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** One instance per job: going from the analyse job to the plan job starts fresh (stream, timers, guards). */
export function JobView() {
  const { jobId = "" } = useParams()
  return <JobScreen key={jobId} jobId={jobId} />
}

function JobScreen({ jobId }: { jobId: string }) {
  const [search] = useSearchParams()
  const { project } = useProjectCtx()
  const navigate = useNavigate()
  const { job, seen, error } = useJobStream(jobId)
  const retry = useRetryJob()
  const start = useStartJob(project.id)
  const [cancelling, setCancelling] = useState(false)
  const moved = useRef(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const base = `/projects/${project.id}`

  const kind = (job?.kind ?? "plan") as JobKind
  const copy = JOB_COPY[kind]
  const status = job?.status
  const running = status === "running" || status === "queued"
  const elapsed = useElapsed(job?.started_at ?? job?.created_at, running)

  // when it's done, move on to the next screen (once; the timer isn't cancelled by re-renders, only skipped if the
  // page is gone by then)
  useEffect(() => {
    if (!job || job.status !== "done" || moved.current) return
    moved.current = true
    const go = async () => {
      if (!alive.current) return
      if (job.kind === "analyse") {
        const res = job.result as { questions?: unknown[] } | null
        if (res?.questions?.length) return navigate(`${base}/questions`, { replace: true })
        if (search.get("then") === "plan") {
          const next = await start.mutateAsync({ kind: "plan" }).catch(() => null)
          if (next) return navigate(`${base}/jobs/${next.id}`, { replace: true })
        }
        return navigate(`${base}/setup/review`, { replace: true })
      }
      if (job.kind === "revise" && (job.params as { render?: boolean })?.render) {
        const jobs = await call(api.GET("/jobs", { params: { query: { project_id: project.id } } })).catch(() => [])
        const r = jobs.find((j) => j.kind === "render" && ["queued", "running"].includes(j.status))
        if (r) return navigate(`${base}/jobs/${r.id}`, { replace: true })
      }
      if (job.kind === "photos-import") return navigate(`${base}/setup/media`, { replace: true })
      if (job.kind === "render") {
        const v = (job.result as { version?: number } | null)?.version
        return navigate(`${base}/video${v ? `?v=${v}` : ""}`, { replace: true })
      }
      navigate(`${base}/plan`, { replace: true })
    }
    setTimeout(go, 900)
  }, [job, base, navigate, project.id, search, start])

  if (error && !job) return <Page><ErrorState error={error} className="mt-12" /></Page>
  if (!job)
    return (
      <Page className="max-w-[760px]">
        <Skeleton className="mb-6 h-8 w-64 bg-white/[0.04]" />
        <Skeleton className="h-80 rounded-2xl bg-white/[0.04]" />
      </Page>
    )

  const brain = running && isBrainStep(job.step)
  const stages = JOB_STAGES[kind] ?? []
  const current = stageIndex(kind, job.step)
  const done = job.status === "done"
  const failed = ["failed", "interrupted", "cancelled"].includes(job.status)
  const err = job.error as { code?: string; message?: string; hint?: string } | null

  return (
    <Page className="max-w-[780px] pt-10">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <div className="eyebrow mb-2 flex items-center gap-2">
            {kind === "render" ? "Render" : "Claude"} · {project.name}
          </div>
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">{done ? copy.done : copy.title}</h1>
        </div>
        {elapsed && (
          <div className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] px-2.5 py-1.5 font-mono text-[12px] text-muted-foreground">
            <Clock className="size-3.5" /> {elapsed}
          </div>
        )}
      </div>

      <div className="panel relative overflow-hidden p-8">
        <div className={cn("pointer-events-none absolute -top-24 left-1/2 h-56 w-[520px] -translate-x-1/2 rounded-full blur-3xl transition-opacity duration-700", brain ? "bg-primary/20 opacity-100" : "bg-info/10 opacity-60", failed && "bg-destructive/10")} />

        <AnimatePresence mode="wait">
          {failed ? (
            <motion.div key="failed" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="relative flex flex-col items-center py-4 text-center">
              <div className="mb-4 grid size-12 place-items-center rounded-full bg-destructive/15 text-destructive">
                <AlertTriangle className="size-5" />
              </div>
              <div className="text-[16px] font-semibold">{err?.message ?? `This ${kind} job ${job.status}`}</div>
              {err?.hint && <div className="mt-1.5 max-w-md text-[13px] text-muted-foreground">{err.hint}</div>}
              <div className="mt-6 flex gap-2">
                <Button variant="outline" asChild>
                  <Link to={base}>
                    <ArrowLeft /> Back to the project
                  </Link>
                </Button>
                <Button
                  disabled={retry.isPending}
                  onClick={() => retry.mutate(job.id, { onSuccess: (j) => navigate(`${base}/jobs/${j.id}${search.toString() ? `?${search}` : ""}`, { replace: true }) })}
                >
                  {retry.isPending ? <Loader2 className="animate-spin" /> : <RotateCw />} Try again
                </Button>
              </div>
            </motion.div>
          ) : brain ? (
            <motion.div key="brain" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="relative flex flex-col items-center py-2 text-center">
              <BrainOrb />
              <div className="shimmer-text mt-5 text-[20px] font-semibold tracking-[-0.01em]">{copy.brain}</div>
              <p className="mt-2 max-w-md text-[13.5px] leading-relaxed text-muted-foreground">{BRAIN_SUB[kind]}</p>
            </motion.div>
          ) : done ? (
            <motion.div key="done" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="relative flex flex-col items-center py-6 text-center">
              <motion.div initial={{ scale: 0.6 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 300, damping: 18 }} className="grid size-14 place-items-center rounded-full bg-ok/15 text-ok shadow-[0_0_40px_-6px_rgb(61_220_151/0.6)]">
                <Check className="size-6" />
              </motion.div>
              <div className="mt-4 text-[16px] font-semibold">{copy.done}</div>
              <div className="mt-1 text-[13px] text-muted-foreground">Opening it…</div>
            </motion.div>
          ) : (
            <motion.div key="progress" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="relative">
              <div className="flex items-end justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-[13px] text-muted-foreground">{job.status === "queued" ? "In the queue" : "Now"}</div>
                  <div className="mt-1 truncate text-[17px] font-semibold first-letter:uppercase">
                    {job.status === "queued" ? (job.position && job.position > 1 ? `Waiting its turn: #${job.position} in the render queue` : "Starting…") : job.step ?? "Starting…"}
                  </div>
                </div>
                <div className="font-mono text-[34px] leading-none font-semibold tracking-tight tabular-nums">
                  {Math.round(job.progress)}
                  <span className="text-[18px] text-muted-foreground">%</span>
                </div>
              </div>
              <div className="mt-5 h-2 overflow-hidden rounded-full bg-white/[0.06]">
                <motion.div
                  className={cn("relative h-full rounded-full", kind === "render" ? "bg-gradient-to-r from-[#3aa8ff] to-info" : "bg-gradient-to-r from-[#6d4aff] to-[#a78bfa]")}
                  initial={false}
                  animate={{ width: `${Math.max(2, job.progress)}%` }}
                  transition={{ ease: "easeOut", duration: 0.5 }}
                >
                  <div className="absolute inset-0 animate-shimmer bg-[linear-gradient(90deg,transparent,rgb(255_255_255/0.35),transparent)] bg-[length:200%_100%]" />
                </motion.div>
              </div>
              {job.status === "queued" && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-4"
                  disabled={cancelling}
                  onClick={async () => {
                    setCancelling(true)
                    await call(api.DELETE("/jobs/{job_id}", { params: { path: { job_id: job.id } } })).catch(() => null)
                    navigate(base, { replace: true })
                  }}
                >
                  <X /> Cancel
                </Button>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {!failed && stages.length > 0 && (
          <ol className="relative mt-8 grid gap-1 border-t border-white/[0.05] pt-6">
            {stages.map((s, i) => {
              // stages before the first one this page saw happened before it opened: count them as done
              const first = seen.size ? Math.min(...seen) : Math.max(current, 0)
              const reached = done ? stages.length : current
              const state = i < reached ? (seen.has(i) || i < first ? "done" : "skipped") : i === current ? "active" : "pending"
              return (
                <li key={s.id} className="flex items-center gap-3 py-1 text-[13.5px]">
                  <span className="grid size-5 place-items-center">
                    {state === "done" && <Check className="size-4 text-ok" />}
                    {state === "skipped" && <Minus className="size-4 text-subtle" />}
                    {state === "active" && <Loader2 className={cn("size-4 animate-spin", isBrainStep(job.step) ? "text-primary" : "text-info")} />}
                    {state === "pending" && <Circle className="size-3 text-subtle/60" />}
                  </span>
                  <span className={cn(state === "active" ? "font-medium text-foreground" : state === "done" ? "text-zinc-300" : "text-subtle")}>
                    {s.label}
                  </span>
                  {state === "skipped" && <span className="text-[11.5px] text-subtle">not needed</span>}
                </li>
              )
            })}
          </ol>
        )}
      </div>

      <Log lines={job.log ?? []} />
    </Page>
  )
}
