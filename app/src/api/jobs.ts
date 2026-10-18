import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { reportBrainIssue } from "@/lib/brain-issue"
import { api, call, jobSocketUrl } from "./client"
import { keys } from "./queries"
import type { Job, JobEvent, JobKind } from "./types"

export const FINISHED = ["done", "failed", "cancelled", "interrupted"]

export const JOB_COPY: Record<JobKind, { title: string; brain: string; done: string }> = {
  analyse: { title: "Reading your brief", brain: "Claude is reading your brief…", done: "Brief checked" },
  plan: { title: "Planning the edit", brain: "Claude is planning…", done: "Plan ready" },
  render: { title: "Rendering", brain: "", done: "Render finished" },
  revise: { title: "Applying your notes", brain: "Claude is revising the plan…", done: "Plan updated" },
  reference: { title: "Studying the reference reel", brain: "Claude is studying the reel…", done: "Style spec ready" },
}

export const isBrainStep = (step: string | null | undefined) => !!step && /^(brain|ask the brain)/i.test(step)

export type Stage = { id: string; label: string; match: RegExp }

/** The stages each job goes through, in order, matched against its step names. */
export const JOB_STAGES: Record<JobKind, Stage[]> = {
  analyse: [
    { id: "check", label: "Check the brief", match: /check the brief/ },
    { id: "brain", label: "Claude reads it", match: /ask the brain/ },
  ],
  plan: [
    { id: "check", label: "Check the brief", match: /check the brief|reference/ },
    { id: "transcribe", label: "Transcribe what's said to camera", match: /^transcribe/ },
    { id: "voice", label: "Clean up and transcribe the voiceover", match: /clean the voiceover/ },
    { id: "match", label: "Look at the B-roll", match: /match b-roll/ },
    { id: "draft", label: "Rough cut", match: /^draft|^analyse |lay b-roll/ },
    { id: "brain", label: "Claude plans the edit", match: /brain: build/ },
    { id: "save", label: "Save the plan", match: /^save|^done/ },
  ],
  revise: [
    { id: "brain", label: "Claude applies your notes", match: /brain: apply/ },
    { id: "save", label: "Save the plan", match: /^save|^done/ },
  ],
  render: [
    { id: "prepare", label: "Prepare", match: /^prepare/ },
    { id: "shots", label: "Frame and cut every shot", match: /^shot / },
    { id: "broll", label: "B-roll", match: /^b-roll/ },
    { id: "overlay", label: "Captions and text", match: /^overlay/ },
    { id: "audio", label: "Mix the sound", match: /^audio/ },
    { id: "export", label: "Export", match: /^export/ },
    { id: "contact", label: "Contact sheet", match: /^contact sheet|^done/ },
  ],
  reference: [
    { id: "download", label: "Download the reel", match: /download/ },
    { id: "analyse", label: "Measure it", match: /analyse|transcribe|sheets/ },
    { id: "brain", label: "Claude writes the style spec", match: /brain/ },
  ],
}

export function stageIndex(kind: JobKind, step: string | null | undefined): number {
  if (!step) return -1
  return JOB_STAGES[kind]?.findIndex((s) => s.match.test(step)) ?? -1
}

export type JobStream = { job: Job | null; seen: Set<number>; error: { code: string; message: string } | null }

/** Live job state from WS /ws/jobs/{id} (reconnects; the first message is always a full snapshot). */
export function useJobStream(jobId: string | undefined): JobStream {
  const qc = useQueryClient()
  const [job, setJob] = useState<Job | null>(() => (jobId ? (qc.getQueryData<Job>(keys.job(jobId)) ?? null) : null))
  const [seen, setSeen] = useState<Set<number>>(new Set())
  const [error, setError] = useState<JobStream["error"]>(null)
  const finished = useRef(false)

  useEffect(() => {
    if (!jobId) return
    finished.current = false
    let ws: WebSocket | null = null
    let stop = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let fails = 0

    const mark = (j: Pick<Job, "kind" | "step">) => {
      const i = stageIndex(j.kind as JobKind, j.step)
      if (i >= 0) setSeen((s) => (s.has(i) ? s : new Set(s).add(i)))
    }
    const finish = (j: Job) => {
      if (finished.current) return
      finished.current = true
      if (j.error) reportBrainIssue(j.error as { code?: string; message?: string; hint?: string })
      const pid = j.project_id
      if (pid) {
        for (const k of [keys.project(pid), keys.timeline(pid), keys.outputs(pid), keys.voiceover(pid), keys.jobs(pid)])
          qc.invalidateQueries({ queryKey: k })
      }
      qc.invalidateQueries({ queryKey: keys.projects })
    }
    const poll = async () => {
      try {
        const j = await call(api.GET("/jobs/{job_id}", { params: { path: { job_id: jobId } } }))
        setJob(j)
        mark(j)
        if (FINISHED.includes(j.status)) return finish(j)
      } catch (e) {
        setError(e as { code: string; message: string })
      }
      if (!stop) timer = setTimeout(poll, 1500)
    }
    const connect = () => {
      ws = new WebSocket(jobSocketUrl(jobId))
      ws.onopen = () => (fails = 0)
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data) as JobEvent
        if (ev.type === "snapshot" || ev.type === "result") {
          setJob(ev.job)
          mark(ev.job)
          qc.setQueryData(keys.job(jobId), ev.job)
          if (FINISHED.includes(ev.job.status)) finish(ev.job)
        } else if (ev.type === "error") {
          setError(ev.error)
        } else {
          const e = ev as Extract<JobEvent, { type: "status" | "step" | "log" }>
          setJob((j) => {
            if (!j) return j
            const next: Job = { ...j, status: e.status, progress: e.progress ?? j.progress, step: e.step ?? j.step }
            if (e.type === "log") next.log = [...(j.log ?? []), e.line].slice(-400)
            if (e.type === "status" && e.error) next.error = e.error
            mark(next)
            return next
          })
        }
      }
      ws.onclose = () => {
        if (stop || finished.current) return
        fails += 1
        timer = fails > 3 ? setTimeout(poll, 500) : setTimeout(connect, 800 * fails)
      }
    }
    connect()
    return () => {
      stop = true
      clearTimeout(timer)
      ws?.close()
    }
  }, [jobId, qc])

  return { job, seen, error }
}
