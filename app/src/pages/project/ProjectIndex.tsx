import { Navigate } from "react-router"
import { useJobs } from "@/api/queries"
import { useProjectCtx } from "./ProjectLayout"

/** /projects/:id opens wherever the project is: a running job, its questions, the plan or the video. */
export function ProjectIndex() {
  const { project: p, activeJob } = useProjectCtx()
  const jobs = useJobs(p.id)
  if (jobs.isLoading) return null
  const base = `/projects/${p.id}`
  if (activeJob) return <Navigate replace to={`${base}/jobs/${activeJob.id}`} />
  const files = p.files ?? []
  const open = (p.questions ?? []).some((q) => !p.answers?.[q.id])
  let to = `${base}/setup/review`
  switch (p.status) {
    case "new":
      to = !p.brief?.content_type ? `${base}/setup/type` : !files.length ? `${base}/setup/media` : `${base}/setup/idea`
      break
    case "analysed":
      to = open ? `${base}/questions` : `${base}/setup/review`
      break
    case "planned":
      to = `${base}/plan`
      break
    case "rendered":
      to = `${base}/video`
      break
    default:
      to = p.renders?.length ? `${base}/video` : p.plan_version > 0 ? `${base}/plan` : `${base}/setup/review`
  }
  return <Navigate replace to={to} />
}
