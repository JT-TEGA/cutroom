import { AlertTriangle, ArrowLeft, Check, Clapperboard, Loader2, MessageCircleQuestion, Mic, Music2, Pencil, Sparkles } from "lucide-react"
import { useNavigate } from "react-router"
import { useStartJob } from "@/api/queries"
import type { Brief, Project } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { Button } from "@/components/ui/button"
import { clock, pluralize } from "@/lib/format"
import { presetMeta } from "@/lib/presets"
import { cn } from "@/lib/utils"
import type { StepId } from "./Wizard"
import { WizardFooter } from "./Wizard"

const BEAT_CUT = ["photo-dump", "shoot-mashup", "shoot-slideshow", "transformation", "workout-routine", "lifestyle-outing"]

const LABELS: [keyof Brief, string][] = [
  ["talking", "Talking"],
  ["idea", "The idea"],
  ["hook", "Hook"],
  ["script", "Script"],
  ["platform", "Platform"],
  ["target_length", "Length"],
  ["goal", "Goal"],
  ["labels", "Labels & stickers"],
  ["text_on_screen", "Text on screen"],
  ["captions", "Captions"],
  ["visual_cues", "Visual cues"],
  ["colour_grade", "Grade"],
  ["beat_sync", "Beat sync"],
  ["music_vibe", "Music"],
  ["pacing", "Pacing"],
  ["end_card", "End card"],
  ["call_to_action", "Call to action"],
  ["avoid", "Avoid"],
  ["reference_url", "Reference reel"],
]

function Card({ title, onEdit, children, className }: { title: string; onEdit?: () => void; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("panel p-5", className)}>
      <div className="mb-3 flex items-center justify-between">
        <div className="eyebrow">{title}</div>
        {onEdit && (
          <button onClick={onEdit} className="inline-flex items-center gap-1 text-[12px] text-muted-foreground transition hover:text-foreground">
            <Pencil className="size-3" /> Edit
          </button>
        )}
      </div>
      {children}
    </div>
  )
}

export function StepReview({ project, onEdit }: { project: Project; onEdit: (s: StepId) => void }) {
  const navigate = useNavigate()
  const start = useStartJob(project.id)
  const b = project.brief as Brief
  const files = project.files ?? []
  const visual = files.filter((f) => f.kind === "clip" || f.kind === "photo")
  const voice = files.filter((f) => f.kind === "voiceover")
  const music = files.filter((f) => f.kind === "music")
  const meta = presetMeta(b.content_type)
  const talk = b.talking ?? ""

  const checks: { ok: boolean; warn?: boolean; text: string }[] = [
    { ok: !!b.content_type, text: b.content_type ? `${meta.title} preset` : "Pick a content type" },
    { ok: visual.length > 0, text: visual.length ? `${pluralize(visual.length, "clip/photo", "clips & photos")}` : "Add at least one clip or photo" },
  ]
  if ((talk === "voiceover" || talk === "mixed") && !voice.length) checks.push({ ok: false, warn: true, text: "Voiceover mode but no voice memo: Claude will ask" })
  if (b.content_type && BEAT_CUT.includes(b.content_type) && !music.length) checks.push({ ok: false, warn: true, text: "Beat-cut type without music: Claude will ask for a track" })
  if (!b.idea && !b.hook && !b.script) checks.push({ ok: false, warn: true, text: "No idea written yet: the edit follows the preset alone" })
  const blocked = checks.some((c) => !c.ok && !c.warn)

  const filled = LABELS.filter(([k]) => (Array.isArray(b[k]) ? (b[k] as string[]).length : !!b[k]))
  const generate = () =>
    start.mutate({ kind: "analyse" }, { onSuccess: (job) => navigate(`/projects/${project.id}/jobs/${job.id}?then=plan`) })

  return (
    <>
      <div className="grid grid-cols-[1fr_360px] gap-6 max-lg:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-5">
          <Card title="Media" onEdit={() => onEdit("media")}>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {visual.slice(0, 12).map((f) => (
                <Thumb key={f.id} path={`${project.id}/${f.path}`} w={160} className="aspect-[9/16] w-[64px] shrink-0 rounded-lg" />
              ))}
              {visual.length > 12 && (
                <div className="grid aspect-[9/16] w-[64px] shrink-0 place-items-center rounded-lg bg-white/[0.04] text-[12px] text-muted-foreground">
                  +{visual.length - 12}
                </div>
              )}
              {!visual.length && <div className="text-[13px] text-muted-foreground">No clips yet.</div>}
            </div>
            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-[12.5px] text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Clapperboard className="size-3.5 text-primary" /> {pluralize(visual.length, "shot")}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Mic className="size-3.5 text-primary" />
                {voice.length ? voice.map((v) => `${v.name} (${clock(v.duration)})`).join(", ") : "no voiceover"}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Music2 className="size-3.5 text-primary" />
                {music.length ? music.map((m) => m.name).join(", ") : "no music"}
                {music.length > 0 && b.music_start != null && ` · from ${clock(b.music_start)}`}
                {music.length > 0 && b.music_in_app && " · you'll add it in the app when posting"}
              </span>
            </div>
          </Card>

          <Card title="Brief" onEdit={() => onEdit("idea")}>
            {filled.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">Nothing written yet. That's allowed: the preset decides.</p>
            ) : (
              <dl className="grid grid-cols-[150px_1fr] gap-x-6 gap-y-3 text-[13px]">
                {filled.map(([k, label]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="whitespace-pre-wrap text-zinc-200">{Array.isArray(b[k]) ? (b[k] as string[]).join("\n") : String(b[k])}</dd>
                  </div>
                ))}
              </dl>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card title="Content type" onEdit={() => onEdit("type")}>
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-lg bg-primary/15 text-primary">
                <meta.icon className="size-[18px]" />
              </span>
              <div className="text-[14px] font-semibold">{meta.title}</div>
            </div>
          </Card>
          <Card title="Checks">
            <ul className="grid gap-2.5 text-[13px]">
              {checks.map((c) => (
                <li key={c.text} className="flex items-start gap-2.5">
                  {c.ok ? (
                    <Check className="mt-0.5 size-4 shrink-0 text-ok" />
                  ) : (
                    <AlertTriangle className={cn("mt-0.5 size-4 shrink-0", c.warn ? "text-warn" : "text-destructive")} />
                  )}
                  <span className={c.ok ? "text-zinc-300" : "text-zinc-200"}>{c.text}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="What happens next">
            <ol className="grid gap-3 text-[13px] text-zinc-300">
              <li className="flex gap-3">
                <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-primary" />
                Claude reads the brief and asks anything it needs, all at once.
              </li>
              <li className="flex gap-3">
                <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
                Your talking and voice memo are transcribed and cleaned; a rough cut is drafted; Claude turns it into a plan with
                a reason for every cut.
              </li>
              <li className="flex gap-3">
                <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                You review the timeline. Nothing renders until you approve it.
              </li>
            </ol>
          </Card>
        </div>
      </div>

      <WizardFooter
        left={
          <Button variant="ghost" onClick={() => onEdit("idea")}>
            <ArrowLeft /> Back
          </Button>
        }
        hint={blocked ? "Fix the red check first" : "Takes a minute or two"}
        right={
          <Button size="lg" disabled={blocked || start.isPending} onClick={generate} className="px-5">
            {start.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
            Generate plan
          </Button>
        }
      />
    </>
  )
}
