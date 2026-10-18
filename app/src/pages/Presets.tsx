import { Check, Loader2, Pencil, X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import Markdown from "react-markdown"
import { NavLink, useNavigate, useParams } from "react-router"
import { toast } from "sonner"
import { usePresets, useSavePreset } from "@/api/queries"
import type { Preset } from "@/api/types"
import { Page, PageHeader } from "@/components/Page"
import { ErrorState } from "@/components/States"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { GROUPS, presetMeta } from "@/lib/presets"
import { cn } from "@/lib/utils"

/** What each settings key means, in the creator's words (keys without one show as is). */
const KEY_LABELS: Record<string, string> = {
  target_length: "Target length (s)",
  talk_default: "Talking (default)",
  shot_min: "Shortest shot (s)",
  shot_max: "Longest shot (s)",
  beat_every: "Cut every N beats",
  beat_every_after_drop: "Every N beats after the drop",
  captions: "Captions",
  text_style: "Text style",
  music_mode: "Music role",
  music_under_voice_db: "Music under voice (dB)",
  transition: "Transition",
  transition_location: "Transition between places",
  transition_drop: "Transition on the drop",
  transition_downbeat: "Transition on downbeats",
  grade: "Colour grade",
  end_card: "End card",
  hold_last_beats: "Hold the last shot (beats)",
  kenburns: "Photo push-in",
  ramp_on_drop: "Speed ramp on the drop",
  grain: "Film grain",
  vignette: "Vignette",
  handheld: "Handheld shake",
  photo_fit: "Photo fit",
}

function Value({ v, editing, onChange }: { v: unknown; editing: boolean; onChange: (v: unknown) => void }) {
  if (typeof v === "boolean")
    return editing ? <Switch checked={v} onCheckedChange={onChange} /> : <span className={v ? "text-emerald-200" : "text-muted-foreground"}>{v ? "on" : "off"}</span>
  const text = Array.isArray(v) ? v.join(", ") : String(v)
  if (!editing) return <span className="font-mono text-[12.5px] text-zinc-200">{text}</span>
  return (
    <Input
      defaultValue={text}
      onBlur={(e) => {
        const raw = e.target.value.trim()
        onChange(typeof v === "number" && raw !== "" && !isNaN(Number(raw)) ? Number(raw) : Array.isArray(v) ? raw.split(",").map((x) => x.trim()).filter(Boolean) : raw)
      }}
      className="h-8 w-48 bg-white/[0.03] font-mono text-[12.5px]"
    />
  )
}

function Detail({ preset }: { preset: Preset }) {
  const save = useSavePreset()
  const [editing, setEditing] = useState(false)
  const [desc, setDesc] = useState(preset.description)
  const [notes, setNotes] = useState(preset.notes)
  const [settings, setSettings] = useState<Record<string, unknown>>(preset.settings ?? {})
  useEffect(() => {
    setDesc(preset.description)
    setNotes(preset.notes)
    setSettings(preset.settings ?? {})
    setEditing(false)
  }, [preset])
  const m = presetMeta(preset.name)
  const changed = useMemo(
    () => Object.fromEntries(Object.entries(settings).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify((preset.settings as Record<string, unknown>)[k]))),
    [settings, preset.settings],
  )

  const submit = () =>
    save.mutate(
      {
        name: preset.name,
        description: desc !== preset.description ? desc : undefined,
        notes: notes !== preset.notes ? notes : undefined,
        settings: Object.keys(changed).length ? changed : undefined,
      },
      {
        onSuccess: () => {
          toast.success(`${m.title} saved`)
          setEditing(false)
        },
      },
    )

  return (
    <div className="min-w-0">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-primary/15 text-primary shadow-[0_0_30px_-8px_rgb(124_92_255/0.7)]">
            <m.icon className="size-5" />
          </span>
          <div className="min-w-0">
            <h2 className="text-[21px] font-semibold tracking-[-0.02em]">{m.title}</h2>
            <div className="mt-0.5 font-mono text-[12px] text-subtle">presets/{preset.name}.md</div>
            {editing ? (
              <Input value={desc} onChange={(e) => setDesc(e.target.value)} className="mt-2 w-[460px] max-w-full bg-white/[0.03]" />
            ) : (
              <p className="mt-2 text-[13.5px] text-muted-foreground">{preset.description}</p>
            )}
          </div>
        </div>
        {editing ? (
          <div className="flex shrink-0 gap-2">
            <Button variant="ghost" size="sm" onClick={() => { setDesc(preset.description); setNotes(preset.notes); setSettings(preset.settings ?? {}); setEditing(false) }}>
              <X /> Cancel
            </Button>
            <Button size="sm" onClick={submit} disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : <Check />} Save preset
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            <Pencil /> Edit
          </Button>
        )}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-6 max-xl:grid-cols-1">
        <div className="panel p-6">
          <div className="eyebrow mb-3">How it's edited</div>
          {editing ? (
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={22} className="bg-white/[0.02] font-mono text-[12.5px] leading-relaxed" />
          ) : (
            <div className="text-[13.5px] leading-relaxed text-zinc-300 [&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-[14px] [&_h2]:font-semibold [&_h2]:text-foreground [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:pl-5">
              <Markdown>{preset.notes}</Markdown>
            </div>
          )}
        </div>
        <div className="panel self-start p-6">
          <div className="eyebrow mb-3">Defaults</div>
          <dl className="divide-y divide-white/[0.05]">
            {Object.entries(settings).map(([k, v]) => (
              <div key={k} className={cn("flex items-center justify-between gap-4 py-2.5 text-[13px]", k in changed && "text-violet-100")}>
                <dt className="text-muted-foreground" title={k}>
                  {KEY_LABELS[k] ?? k.replace(/_/g, " ")}
                </dt>
                <dd>
                  <Value v={v} editing={editing} onChange={(nv) => setSettings((s) => ({ ...s, [k]: nv }))} />
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-[11.5px] leading-relaxed text-subtle">These override your brand settings for this content type; a brief overrides them again.</p>
        </div>
      </div>
    </div>
  )
}

export function Presets() {
  const { name } = useParams()
  const navigate = useNavigate()
  const presets = usePresets()
  const list = presets.data ?? []
  const current = list.find((p) => p.name === name) ?? list[0]
  useEffect(() => {
    if (!name && list.length) navigate(`/presets/${list.find((p) => p.name === GROUPS[0].presets[0])?.name ?? list[0].name}`, { replace: true })
  }, [name, list, navigate])

  const known = new Set(GROUPS.flatMap((g) => g.presets))
  const groups = [...GROUPS.map((g) => ({ label: g.label, items: g.presets.filter((n) => list.some((p) => p.name === n)) })), { label: "Your presets", items: list.filter((p) => !known.has(p.name)).map((p) => p.name) }].filter((g) => g.items.length)

  return (
    <Page wide>
      <PageHeader title="Presets" description="Each content type's pacing, structure, text and grade. Edit one and every new video of that type follows it." />
      {presets.error ? (
        <ErrorState error={presets.error} onRetry={() => presets.refetch()} />
      ) : presets.isLoading ? (
        <div className="grid grid-cols-[240px_1fr] gap-8">
          <Skeleton className="h-[520px] rounded-2xl bg-white/[0.04]" />
          <Skeleton className="h-[520px] rounded-2xl bg-white/[0.04]" />
        </div>
      ) : (
        <div className="grid grid-cols-[230px_minmax(0,1fr)] gap-8 max-lg:grid-cols-1">
          <nav className="flex flex-col gap-5">
            {groups.map((g) => (
              <div key={g.label}>
                <div className="eyebrow mb-1.5 px-2.5">{g.label}</div>
                {g.items.map((n) => {
                  const m = presetMeta(n)
                  return (
                    <NavLink
                      key={n}
                      to={`/presets/${n}`}
                      className={({ isActive }) =>
                        cn(
                          "flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-muted-foreground transition hover:bg-white/[0.04] hover:text-foreground",
                          (isActive || (!name && current?.name === n)) && "bg-white/[0.06] text-foreground",
                        )
                      }
                    >
                      <m.icon className="size-4 text-primary" />
                      {m.title}
                    </NavLink>
                  )
                })}
              </div>
            ))}
          </nav>
          {current && <Detail key={current.name} preset={current} />}
        </div>
      )}
    </Page>
  )
}
