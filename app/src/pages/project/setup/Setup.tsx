import { ArrowLeft, ArrowRight } from "lucide-react"
import { Navigate, useNavigate, useParams } from "react-router"
import { usePatchProject } from "@/api/queries"
import { Page } from "@/components/Page"
import { Button } from "@/components/ui/button"
import { useProjectCtx } from "../ProjectLayout"
import { StepIdea } from "./StepIdea"
import { StepMedia } from "./StepMedia"
import { StepReview } from "./StepReview"
import { ContentTypePicker, STEPS, type StepId, Stepper, WizardFooter } from "./Wizard"

const COPY: Record<StepId, { title: string; sub: string }> = {
  type: { title: "What are you making?", sub: "The type sets the pacing, structure, text style and grade." },
  media: {
    title: "Add your media",
    sub: "Clips and photos in the order you want them, your voice memo and a track. Names help Claude match clips to what you say.",
  },
  idea: { title: "Describe the video", sub: "As messy as you like. Anything you leave empty falls back to the preset." },
  review: { title: "Ready to plan", sub: "Claude checks the brief, asks anything it needs once, then plans the edit for you to review." },
}

export function Setup() {
  const { step = "type" } = useParams()
  const { project } = useProjectCtx()
  const navigate = useNavigate()
  const patch = usePatchProject(project.id)
  const at = STEPS.findIndex((s) => s.id === step)
  if (at < 0) return <Navigate replace to={`/projects/${project.id}/setup/type`} />
  const id = STEPS[at].id
  const go = (s: StepId) => navigate(`/projects/${project.id}/setup/${s}`)
  const visual = (project.files ?? []).filter((f) => f.kind === "clip" || f.kind === "photo").length

  const done: StepId[] = []
  if (project.brief?.content_type) done.push("type")
  if (visual) done.push("media")
  if (project.brief?.idea || project.brief?.hook || project.brief?.script) done.push("idea")

  return (
    <Page wide className="pt-7">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow mb-2">
            Step {at + 1} of {STEPS.length}
          </div>
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">{COPY[id].title}</h1>
          <p className="mt-1.5 max-w-2xl text-muted-foreground">{COPY[id].sub}</p>
        </div>
        <Stepper current={id} onPick={go} done={done} />
      </div>

      {id === "type" && (
        <ContentTypePicker
          value={project.brief?.content_type}
          onChange={(name) => patch.mutate({ brief: { content_type: name } })}
        />
      )}
      {id === "media" && <StepMedia project={project} />}
      {id === "idea" && <StepIdea project={project} />}
      {id === "review" && <StepReview project={project} onEdit={go} />}

      {id !== "review" && (
        <WizardFooter
          left={
            at > 0 && (
              <Button variant="ghost" onClick={() => go(STEPS[at - 1].id)}>
                <ArrowLeft /> Back
              </Button>
            )
          }
          hint={id === "media" && !visual ? "Add at least one clip or photo" : undefined}
          right={
            <Button disabled={(id === "type" && !project.brief?.content_type) || (id === "media" && !visual)} onClick={() => go(STEPS[at + 1].id)}>
              Continue <ArrowRight />
            </Button>
          }
        />
      )}
    </Page>
  )
}
