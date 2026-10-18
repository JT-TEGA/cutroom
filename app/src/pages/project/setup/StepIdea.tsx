import { AnimatePresence, motion } from "framer-motion"
import { Check, ChevronDown, Cloud, Layers, Link2, Loader2, Mic, MicOff, Type, User, Wand2 } from "lucide-react"
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react"
import { usePatchProject, usePresets } from "@/api/queries"
import type { Brief, Project } from "@/api/types"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { presetDefaults, presetMeta } from "@/lib/presets"
import { cn } from "@/lib/utils"

type Opt = { value: string; label: string; icon?: typeof Mic }

const TALKING: Opt[] = [
  { value: "yes", label: "To camera", icon: User },
  { value: "no", label: "No talking", icon: MicOff },
  { value: "some parts", label: "Some parts", icon: Layers },
  { value: "voiceover", label: "Voiceover", icon: Mic },
  { value: "mixed", label: "Mixed", icon: Wand2 },
]
const PLATFORMS: Opt[] = ["Reels", "TikTok", "both"].map((v) => ({ value: v, label: v === "both" ? "Both" : v }))
const GRADES: Opt[] = ["none", "warm", "clean-editorial", "punchy", "film"].map((v) => ({
  value: v,
  label: v === "clean-editorial" ? "Clean editorial" : v[0].toUpperCase() + v.slice(1),
}))
const BEATS: Opt[] = ["every beat", "every 2 beats", "every 4 beats", "on drops"].map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))
const ONOFF: Opt[] = [
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
]
const GOALS = ["grow followers", "document a day", "show progress", "educate", "build hype"]

function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label className="text-[12.5px] font-medium text-zinc-300">{label}</label>
        {hint && <span className="truncate text-[11.5px] text-subtle">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

/** Chips for a small set of options; the empty choice is "use the preset's default". */
function Chips({ value, onChange, options, preset }: { value: string; onChange: (v: string) => void; options: Opt[]; preset?: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {preset !== undefined && (
        <button
          type="button"
          onClick={() => onChange("")}
          className={cn(
            "h-8 rounded-lg border px-3 text-[12.5px] font-medium transition",
            !value ? "border-primary/60 bg-primary/12 text-violet-100" : "border-white/[0.07] text-muted-foreground hover:text-foreground",
          )}
        >
          Preset{preset ? `: ${preset}` : " default"}
        </button>
      )}
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          onClick={() => onChange(o.value === value ? "" : o.value)}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[12.5px] font-medium transition",
            value === o.value
              ? "border-primary/60 bg-primary/12 text-violet-100"
              : "border-white/[0.07] bg-white/[0.02] text-muted-foreground hover:border-white/15 hover:text-foreground",
          )}
        >
          {o.icon && <o.icon className="size-3.5" />}
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Section({
  title,
  icon: Icon,
  filled,
  children,
  defaultOpen = false,
}: {
  title: string
  icon: typeof Mic
  filled?: number
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="panel overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 px-5 py-4 text-left">
        <Icon className="size-4 text-primary" />
        <span className="flex-1 text-[14px] font-semibold">{title}</span>
        {!!filled && <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-muted-foreground">{filled} set</span>}
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} transition={{ duration: 0.22 }} className="overflow-hidden">
            <div className="grid gap-5 border-t border-white/[0.05] px-5 pt-4 pb-5">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

const inputCls = "bg-white/[0.025] border-white/[0.08] placeholder:text-subtle"

export function StepIdea({ project }: { project: Project }) {
  const patch = usePatchProject(project.id)
  const presets = usePresets()
  const preset = presets.data?.find((p) => p.name === project.brief?.content_type)
  const defaults = useMemo(() => presetDefaults(preset), [preset])
  const [b, setB] = useState<Brief>(() => ({ ...(project.brief as Brief) }))
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle")
  const pending = useRef<Partial<Brief>>({})
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const flush = () => {
    clearTimeout(timer.current)
    const changes = pending.current
    if (!Object.keys(changes).length) return
    pending.current = {}
    setState("saving")
    const title = typeof changes.title === "string" ? changes.title.trim() : ""
    patch.mutate(
      { brief: changes, name: title || undefined },
      { onSuccess: () => setState("saved"), onError: () => setState("idle") },
    )
  }
  useEffect(() => () => flush(), []) // eslint-disable-line react-hooks/exhaustive-deps

  const set = <K extends keyof Brief>(k: K, v: Brief[K]) => {
    setB((x) => ({ ...x, [k]: v }))
    pending.current = { ...pending.current, [k]: v }
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, 700)
  }
  const str = (k: keyof Brief) => ((b[k] as string | null | undefined) ?? "") as string
  const text = (k: keyof Brief, nullable = false) => ({
    name: k,
    value: str(k),
    onChange: (e: { target: { value: string } }) => set(k, (nullable && !e.target.value ? null : e.target.value) as never),
  })
  const voices = (project.files ?? []).filter((f) => f.kind === "voiceover")
  const count = (ks: (keyof Brief)[]) => ks.filter((k) => (Array.isArray(b[k]) ? (b[k] as string[]).length : !!b[k])).length
  const talk = str("talking")
  const meta = presetMeta(project.brief?.content_type)

  return (
    <div className="grid grid-cols-[1fr_300px] gap-6 max-lg:grid-cols-1">
      <div className="flex min-w-0 flex-col gap-5">
        <div className="panel grid gap-5 p-5">
          <div className="grid grid-cols-[1fr_auto] items-end gap-4">
            <Field label="Title">
              <Input {...text("title")} placeholder="e.g. 5AM chest day" className={cn(inputCls, "h-10 text-[15px] font-medium")} />
            </Field>
            <div className="flex h-10 items-center gap-1.5 text-[12px] text-muted-foreground">
              {state === "saving" ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" /> Saving
                </>
              ) : state === "saved" ? (
                <>
                  <Check className="size-3.5 text-ok" /> Saved
                </>
              ) : (
                <>
                  <Cloud className="size-3.5" /> Autosaves
                </>
              )}
            </div>
          </div>
          <Field label="Talking in this video?" hint={defaults.talking ? `${meta.title} default: ${defaults.talking}` : undefined}>
            <Chips value={talk} onChange={(v) => set("talking", v || null)} options={TALKING} />
          </Field>
          <Field label="The idea" hint="your words, as messy as you want">
            <Textarea
              {...text("idea")}
              rows={4}
              placeholder="Early gym morning, chest day, then brunch with the girls. Show the discipline without being preachy."
              className={cn(inputCls, "min-h-28 text-[14px] leading-relaxed")}
            />
          </Field>
          <Field label="Hook (first 2 seconds)" hint="what stops the scroll">
            <Input {...text("hook")} placeholder="Leave empty and Claude opens on the strongest moment" className={inputCls} />
          </Field>
          <Field label="Script / talking points" hint={talk === "voiceover" ? "what the voice memo says, roughly" : "or “use my audio as-is”"}>
            <Textarea {...text("script")} rows={3} placeholder="Bullet points or the full script" className={cn(inputCls, "leading-relaxed")} />
          </Field>
        </div>

        <div className="panel grid grid-cols-3 gap-5 p-5 max-xl:grid-cols-1">
          <Field label="Platform">
            <Chips value={str("platform")} onChange={(v) => set("platform", v || null)} options={PLATFORMS} />
          </Field>
          <Field label="Target length">
            <Input {...text("target_length", true)} placeholder={defaults.target_length ?? "e.g. 30s"} className={inputCls} />
          </Field>
          <Field label="Goal">
            <Input {...text("goal", true)} list="goals" placeholder="grow followers, show progress…" className={inputCls} />
            <datalist id="goals">
              {GOALS.map((g) => (
                <option key={g} value={g} />
              ))}
            </datalist>
          </Field>
        </div>

        <Section title="Text on screen" icon={Type} filled={count(["text_on_screen", "labels", "captions", "caption_style"])}>
          <Field label="Labels & stickers" hint="times, places, sets × reps, macros, credits">
            <Textarea {...text("labels")} rows={2} placeholder={defaults.labels ?? "5:30AM, Incline bench 4x10, Lekki brunch"} className={inputCls} />
          </Field>
          <Field label="Other text on screen" hint="and when it appears">
            <Textarea {...text("text_on_screen")} rows={2} placeholder="0:00 ‘october dump’ small centre / end: ‘part 2 tomorrow’" className={inputCls} />
          </Field>
          <div className="grid grid-cols-2 gap-5 max-xl:grid-cols-1">
            <Field label="Captions">
              <Chips value={str("captions")} onChange={(v) => set("captions", v || null)} options={ONOFF} preset={defaults.captions ?? ""} />
            </Field>
            <Field label="Caption style">
              <Input {...text("caption_style", true)} placeholder="Brand default (Settings)" className={inputCls} />
            </Field>
          </div>
        </Section>

        <Section
          title="Sound, look & pacing"
          icon={Wand2}
          filled={count(["voiceover_file", "visual_cues", "colour_grade", "beat_sync", "music_vibe", "sound_effects", "pacing", "end_card"])}
        >
          {voices.length > 0 && (
            <Field label="Voiceover file">
              <Chips value={str("voiceover_file")} onChange={(v) => set("voiceover_file", v || null)} options={voices.map((v) => ({ value: v.name, label: v.name, icon: Mic }))} preset="" />
            </Field>
          )}
          <Field label="Visual cues" hint="one per line">
            <Textarea
              value={(b.visual_cues ?? []).join("\n")}
              onChange={(e) => set("visual_cues", e.target.value.split("\n").filter((l, i, a) => l.trim() || i === a.length - 1))}
              rows={2}
              placeholder={'when I say "chest day" show incline-bench.mp4'}
              className={cn(inputCls, "font-mono text-[12.5px]")}
            />
          </Field>
          <Field label="Colour grade">
            <Chips value={str("colour_grade")} onChange={(v) => set("colour_grade", v || null)} options={GRADES} preset={defaults.colour_grade ?? ""} />
          </Field>
          <Field label="Beat sync">
            <Chips value={str("beat_sync")} onChange={(v) => set("beat_sync", v || null)} options={BEATS} preset={defaults.beat_sync ?? ""} />
          </Field>
          <div className="grid grid-cols-2 gap-5 max-xl:grid-cols-1">
            <Field label="Music vibe / volume">
              <Input {...text("music_vibe", true)} placeholder={defaults.music_vibe ?? "hard Afrobeats, low under voice"} className={inputCls} />
            </Field>
            <Field label="Sound effects">
              <Input {...text("sound_effects", true)} placeholder="whooshes, bass hits on cuts…" className={inputCls} />
            </Field>
          </div>
          <Field label="Pacing & effects">
            <Textarea {...text("pacing")} rows={2} placeholder={defaults.pacing ?? "fast cuts, zoom-ins on punchlines, slow-mo on fabric"} className={inputCls} />
          </Field>
          <Field label="End card with your handle">
            <Chips value={str("end_card")} onChange={(v) => set("end_card", v || null)} options={ONOFF} preset={defaults.end_card ?? ""} />
          </Field>
        </Section>

        <Section title="Call to action, things to avoid, reference reel" icon={Link2} filled={count(["call_to_action", "avoid", "reference_url"])}>
          <Field label="Call to action">
            <Input {...text("call_to_action")} placeholder="Follow for part 2" className={inputCls} />
          </Field>
          <Field label="Avoid">
            <Textarea {...text("avoid")} rows={2} placeholder="No slow-mo on the walk, no text over my face" className={inputCls} />
          </Field>
          <Field label="Reference reel" hint="copy the pacing, text and grade of a reel you like">
            <Input
              value={str("reference_url")}
              onChange={(e) => {
                set("reference_url", e.target.value || null)
                set("mode", e.target.value ? "REFERENCE" : "ORIGINAL")
              }}
              placeholder="https://www.instagram.com/reel/…"
              className={inputCls}
            />
          </Field>
        </Section>
      </div>

      <aside className="flex flex-col gap-4 max-lg:hidden">
        <div className="panel sticky top-20 p-5">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-lg bg-primary/15 text-primary">
              <meta.icon className="size-4" />
            </span>
            <div>
              <div className="text-[13.5px] font-semibold">{meta.title}</div>
              <div className="text-[11.5px] text-muted-foreground">preset defaults</div>
            </div>
          </div>
          <dl className="grid gap-2.5 text-[12.5px]">
            {[
              ["Length", defaults.target_length],
              ["Talking", defaults.talking],
              ["Pacing", defaults.pacing],
              ["Grade", defaults.colour_grade],
              ["Beat sync", defaults.beat_sync],
              ["Captions", defaults.captions],
              ["End card", defaults.end_card],
            ]
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="text-subtle">{k}</dt>
                  <dd className="mt-0.5 leading-snug text-zinc-300">{v}</dd>
                </div>
              ))}
          </dl>
          <p className="mt-4 border-t border-white/[0.05] pt-3 text-[11.5px] leading-relaxed text-subtle">
            Your brief wins over the preset, and the preset over your brand settings.
          </p>
        </div>
      </aside>
    </div>
  )
}
