import { motion } from "framer-motion"
import { ArrowRight, Info, Loader2, MessageCircleQuestion } from "lucide-react"
import { useState } from "react"
import { Navigate, useNavigate } from "react-router"
import { usePatchProject, useStartJob } from "@/api/queries"
import type { Brief } from "@/api/types"
import { Page } from "@/components/Page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { WizardFooter } from "./setup/Wizard"
import { useProjectCtx } from "./ProjectLayout"

const BRIEF_FIELDS = new Set([
  "title", "content_type", "talking", "colour_grade", "platform", "target_length", "goal", "mode", "reference_url", "idea",
  "hook", "script", "voiceover_file", "text_on_screen", "labels", "captions", "caption_style", "track", "music_vibe",
  "beat_sync", "sound_effects", "pacing", "call_to_action", "end_card", "avoid",
])

export function Questions() {
  const { project } = useProjectCtx()
  const navigate = useNavigate()
  const patch = usePatchProject(project.id)
  const start = useStartJob(project.id)
  const qs = project.questions ?? []
  const [answers, setAnswers] = useState<Record<string, string>>(() => ({ ...(project.answers ?? {}) }))

  if (!qs.length) return <Navigate replace to={`/projects/${project.id}/setup/review`} />

  const missing = qs.filter((q) => q.blocking && !answers[q.id]?.trim())
  const busy = patch.isPending || start.isPending

  const submit = async () => {
    const given = Object.fromEntries(Object.entries(answers).filter(([, v]) => v.trim()))
    // an answer that fills a brief field (track, end card...) goes into the brief too, so the software sees it
    const brief: Partial<Brief> = {}
    for (const q of qs) if (q.field && BRIEF_FIELDS.has(q.field) && given[q.id]) (brief as Record<string, string>)[q.field] = given[q.id]
    await patch.mutateAsync({ answers: given, brief: Object.keys(brief).length ? brief : undefined })
    const job = await start.mutateAsync({ kind: "plan" })
    navigate(`/projects/${project.id}/jobs/${job.id}`)
  }

  return (
    <Page className="max-w-[860px] pt-10">
      <div className="mb-8 flex items-start gap-4">
        <div className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-accent-ink">
          <MessageCircleQuestion className="size-5" />
        </div>
        <div>
          <div className="eyebrow mb-1.5">Before planning</div>
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">
            {qs.length === 1 ? "One question" : `${qs.length} quick questions`} from Claude
          </h1>
          <p className="mt-1.5 text-muted-foreground">Answer them once and it plans the whole edit. Optional ones can be skipped.</p>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {qs.map((q, i) => {
          const v = answers[q.id] ?? ""
          const custom = v && !q.options?.includes(v)
          return (
            <motion.div
              key={q.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.06 * i }}
              className="panel p-6"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex gap-3">
                  <span className="mt-0.5 font-mono text-[12px] text-subtle">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <div className="text-[15.5px] font-semibold tracking-[-0.01em]">{q.question}</div>
                    {q.why && <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{q.why}</div>}
                  </div>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                    q.blocking ? "bg-control text-control-ink" : "bg-surface-2 text-ink-soft",
                  )}
                >
                  {q.blocking ? "Needed" : "Optional"}
                </span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2 pl-8">
                {(q.options ?? []).map((o) => (
                  <button
                    key={o}
                    onClick={() => setAnswers((a) => ({ ...a, [q.id]: a[q.id] === o ? "" : o }))}
                    className={cn(
                      "h-9 rounded-full border px-4 text-[13px] font-medium transition",
                      v === o
                        ? "border-transparent bg-accent text-accent-ink"
                        : "border-ink/15 bg-surface text-foreground hover:border-ink/35",
                    )}
                  >
                    {o}
                  </button>
                ))}
                <Input
                  value={custom ? v : ""}
                  onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                  placeholder={q.options?.length ? "Or type your own answer" : "Your answer"}
                  className={cn("h-9", q.options?.length ? "w-64" : "w-full", custom && "border-ink/60")}
                />
              </div>
            </motion.div>
          )
        })}
      </div>

      {(project.assumptions ?? []).length > 0 && (
        <div className="mt-6 rounded-card bg-surface-2/60 p-5">
          <div className="mb-2.5 flex items-center gap-2 text-[13px] font-medium text-foreground">
            <Info className="size-4" /> Unless you say otherwise, Claude will assume:
          </div>
          <ul className="grid gap-1.5 pl-6 text-[13px] text-muted-foreground">
            {project.assumptions!.map((a) => (
              <li key={a} className="list-disc">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}

      <WizardFooter
        hint={missing.length ? `${missing.length} needed answer${missing.length > 1 ? "s" : ""} left` : "Then Claude plans the edit"}
        right={
          <Button size="lg" disabled={!!missing.length || busy} onClick={submit} className="px-5">
            {busy ? <Loader2 className="animate-spin" /> : null}
            Plan the edit <ArrowRight />
          </Button>
        }
      />
    </Page>
  )
}
