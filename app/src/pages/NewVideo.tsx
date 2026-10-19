import { ArrowRight, Loader2 } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router"
import { useCreateProject } from "@/api/queries"
import { Page } from "@/components/Page"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ContentTypePicker, Stepper, WizardFooter } from "@/pages/project/setup/Wizard"
import { presetMeta } from "@/lib/presets"

/** Step 1 of the wizard before the project exists: picking a type (and a name) creates it. */
export function NewVideo() {
  const navigate = useNavigate()
  const create = useCreateProject()
  const [type, setType] = useState<string | null>(null)
  const [name, setName] = useState("")

  const go = () =>
    type &&
    create.mutate(
      { name: name.trim(), brief: { content_type: type, title: name.trim() } },
      { onSuccess: (p) => navigate(`/projects/${p.id}/setup/media`) },
    )

  return (
    <Page wide>
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="eyebrow mb-2">New video</div>
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">What are you making?</h1>
          <p className="mt-1.5 text-muted-foreground">
            The type sets the pacing, structure, text style and grade. Everything can be changed later.
          </p>
        </div>
        <Stepper current="type" />
      </div>

      <div className="mb-8 max-w-md">
        <label className="mb-1.5 block text-[12.5px] font-medium text-muted-foreground" htmlFor="video-name">
          Name it (optional)
        </label>
        <Input
          id="video-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()}
          placeholder="e.g. 5AM chest day"
          className="h-10 border-transparent shadow-soft"
        />
      </div>

      <ContentTypePicker value={type} onChange={setType} />

      <WizardFooter
        left={
          <Button variant="ghost" onClick={() => navigate("/")}>
            Cancel
          </Button>
        }
        hint={type ? `${presetMeta(type).title} — next, your clips and audio` : "Pick a content type to continue"}
        right={
          <Button disabled={!type || create.isPending} onClick={go}>
            {create.isPending ? <Loader2 className="animate-spin" /> : null}
            Continue <ArrowRight />
          </Button>
        }
      />
    </Page>
  )
}
