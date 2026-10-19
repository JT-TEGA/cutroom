import { AnimatePresence, motion } from "framer-motion"
import { AtSign, Bot, Captions, Check, CircleAlert, KeyRound, Loader2, Music2, Palette, RotateCw, Server, Sparkles, SquareUser } from "lucide-react"
import { type ReactNode, useEffect, useMemo, useState } from "react"
import { useProjects, useSaveSettings, useSettings, useSystemStatus } from "@/api/queries"
import type { AppSettings, BrandSettings } from "@/api/types"
import { CaptionPreview, EndCardPreview } from "@/components/CaptionPreview"
import { Page, PageHeader } from "@/components/Page"
import { ErrorState } from "@/components/States"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"

function Section({ icon: Icon, title, sub, children, id }: { icon: typeof Palette; title: string; sub?: string; children: ReactNode; id?: string }) {
  return (
    <section id={id} className="panel min-w-0 p-6">
      <div className="mb-5 flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-2 text-foreground">
          <Icon className="size-4" />
        </span>
        <div>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
          {sub && <p className="mt-0.5 text-[12.5px] text-muted-foreground">{sub}</p>}
        </div>
      </div>
      <div className="grid gap-5 [&>*]:min-w-0">{children}</div>
    </section>
  )
}

function Line({ label, value, children }: { label: string; value?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[12.5px] font-medium text-foreground">{label}</span>
        {value != null && <span className="font-mono text-[12px] text-muted-foreground">{value}</span>}
      </div>
      {children}
    </div>
  )
}

function ColorField({ label, value, onChange }: { label: string; value: string | null | undefined; onChange: (v: string) => void }) {
  const [text, setText] = useState(value ?? "")
  useEffect(() => {
    setText(value ?? "")
  }, [value])
  return (
    <div className="flex items-center gap-3 rounded-2xl bg-surface-2/60 p-2.5">
      <label className="relative size-9 shrink-0 cursor-pointer overflow-hidden rounded-full shadow-inner ring-1 ring-ink/15" style={{ background: value ?? "#000" }}>
        <input type="color" value={value ?? "#000000"} onChange={(e) => onChange(e.target.value.toUpperCase())} className="absolute inset-0 cursor-pointer opacity-0" aria-label={label} />
      </label>
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] font-medium">{label}</div>
        <input
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) onChange(e.target.value.toUpperCase())
          }}
          className="w-full bg-transparent font-mono text-[11.5px] text-muted-foreground outline-none"
        />
      </div>
    </div>
  )
}

function Chips<T extends string>({ value, options, onChange }: { value: T | null | undefined; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "h-8 rounded-full border px-3.5 text-[12.5px] font-medium transition",
            value === o.v ? "border-transparent bg-accent text-accent-ink" : "border-ink/15 text-ink-soft hover:border-ink/35 hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function BackendCard({
  active,
  onPick,
  icon: Icon,
  title,
  sub,
  status,
  ok,
}: {
  active: boolean
  onPick: () => void
  icon: typeof Bot
  title: string
  sub: string
  status: string
  ok: boolean | null
}) {
  return (
    <button
      onClick={onPick}
      className={cn(
        "relative flex flex-col items-start gap-3 rounded-2xl p-4 text-left transition",
        active ? "bg-accent-soft ring-[1.5px] ring-ink" : "bg-surface-2/50 hover:bg-surface-2",
      )}
    >
      <div className="flex w-full items-center justify-between">
        <span className="grid size-9 place-items-center rounded-full bg-surface text-foreground shadow-soft">
          <Icon className="size-[18px]" />
        </span>
        <span className={cn("grid size-5 place-items-center rounded-full border", active ? "border-control bg-control text-control-ink" : "border-ink/25")}>
          {active && <Check className="size-3" />}
        </span>
      </div>
      <div>
        <div className="text-[14px] font-semibold">{title}</div>
        <div className="mt-0.5 text-[12.5px] text-muted-foreground">{sub}</div>
      </div>
      <div className="flex items-center gap-2 text-[12px]">
        <span className={cn("size-2 rounded-full", ok == null ? "bg-ink-faint" : ok ? "bg-success" : "bg-warn")} />
        <span className={ok ? "text-success-ink" : "text-muted-foreground"}>{status}</span>
      </div>
    </button>
  )
}

export function SettingsPage() {
  const settings = useSettings()
  const status = useSystemStatus()
  const projects = useProjects()
  const save = useSaveSettings()
  const [brand, setBrand] = useState<BrandSettings | null>(null)
  const [app, setApp] = useState<AppSettings | null>(null)

  useEffect(() => {
    if (settings.data && !brand) {
      setBrand(settings.data.brand)
      setApp(settings.data.app)
    }
  }, [settings.data, brand])

  const dirtyBrand = useMemo(() => {
    if (!brand || !settings.data) return {}
    const out: Partial<BrandSettings> = {}
    for (const [k, v] of Object.entries(brand)) if ((settings.data.brand as Record<string, unknown>)[k] !== v && v != null && v !== "") (out as Record<string, unknown>)[k] = v
    return out
  }, [brand, settings.data])
  const dirtyApp = useMemo(() => {
    if (!app || !settings.data) return {}
    const out: Partial<AppSettings> = {}
    for (const [k, v] of Object.entries(app)) if ((settings.data.app as Record<string, unknown>)[k] !== v) (out as Record<string, unknown>)[k] = v
    return out
  }, [app, settings.data])
  const dirty = Object.keys(dirtyBrand).length + Object.keys(dirtyApp).length

  if (settings.error) return <Page><ErrorState error={settings.error} onRetry={() => settings.refetch()} className="mt-10" /></Page>
  if (!brand || !app || !settings.data)
    return (
      <Page>
        <Skeleton className="mb-8 h-10 w-60" />
        <div className="grid grid-cols-[1fr_340px] gap-6">
          <Skeleton className="h-[900px] rounded-2xl" />
          <Skeleton className="h-[600px] rounded-2xl" />
        </div>
      </Page>
    )

  const b = <K extends keyof BrandSettings>(k: K, v: BrandSettings[K]) => setBrand((x) => ({ ...x!, [k]: v }))
  const s = status.data
  const cc = (s?.claude_code ?? {}) as { installed?: boolean; logged_in?: boolean | null; version?: string; subscription?: string; hint?: string }
  const apiReady = s?.brain?.backend === "anthropic-api" ? !!s.brain.ready : null
  const backdrop = projects.data?.find((p) => p.thumbnail)?.thumbnail
  const fonts = settings.data.fonts_available ?? []

  return (
    <Page>
      <PageHeader title="Settings" description="Your look, captions and sound defaults (saved to brand.md, so the command line uses them too), and which brain plans the edits." />

      <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-6 max-lg:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-6">
          <Section icon={SquareUser} title="You" sub="Shown on the end card">
            <Line label="Handle">
              <div className="relative max-w-xs">
                <AtSign className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
                <Input value={(brand.handle ?? "").replace(/^@/, "")} onChange={(e) => b("handle", e.target.value ? `@${e.target.value.replace(/^@/, "")}` : null)} className="pl-9" />
              </div>
            </Line>
          </Section>

          <Section icon={Palette} title="Colours" sub="One emphasis colour, used sparingly: write *word* in any text to use it">
            <div className="grid grid-cols-2 gap-3 max-xl:grid-cols-1">
              <ColorField label="Emphasis" value={brand.emphasis_color} onChange={(v) => b("emphasis_color", v)} />
              <ColorField label="Accent (stickers, cards)" value={brand.accent_color} onChange={(v) => b("accent_color", v)} />
              <ColorField label="Captions" value={brand.caption_color} onChange={(v) => b("caption_color", v)} />
              <ColorField label="Word being said" value={brand.caption_highlight_color} onChange={(v) => b("caption_highlight_color", v)} />
            </div>
          </Section>

          <Section icon={Captions} title="Captions" sub="Only on talking and voiceover parts">
            {fonts.length > 0 && (
              <Line label="Font">
                <Chips value={brand.caption_font ?? undefined} options={fonts.map((f) => ({ v: f, label: f.replace(/([a-z])([A-Z])/g, "$1 $2") }))} onChange={(v) => b("caption_font", v)} />
              </Line>
            )}
            <div className="grid grid-cols-2 gap-x-8 gap-y-5 max-xl:grid-cols-1">
              <Line label="Size" value={`${brand.caption_size ?? 64}px`}>
                <Slider min={24} max={160} step={2} value={[brand.caption_size ?? 64]} onValueChange={([v]) => b("caption_size", v)} />
              </Line>
              <Line label="Weight" value={brand.caption_weight ?? 700}>
                <Slider min={100} max={900} step={100} value={[brand.caption_weight ?? 700]} onValueChange={([v]) => b("caption_weight", v)} />
              </Line>
              <Line label="Height in frame" value={`${Math.round((brand.caption_position ?? 0.7) * 100)}%`}>
                <Slider min={0.08} max={0.8} step={0.01} value={[brand.caption_position ?? 0.7]} onValueChange={([v]) => b("caption_position", Math.round(v * 100) / 100)} />
              </Line>
              <Line label="Words at a time" value={brand.caption_max_words ?? 4}>
                <Slider min={1} max={12} step={1} value={[brand.caption_max_words ?? 4]} onValueChange={([v]) => b("caption_max_words", v)} />
              </Line>
              <Line label="Words not yet said" value={`${Math.round((brand.caption_inactive_opacity ?? 0.6) * 100)}%`}>
                <Slider min={0} max={1} step={0.05} value={[brand.caption_inactive_opacity ?? 0.6]} onValueChange={([v]) => b("caption_inactive_opacity", Math.round(v * 100) / 100)} />
              </Line>
              <Line label="Case">
                <Chips
                  value={brand.caption_case}
                  options={[
                    { v: "as-is", label: "As said" },
                    { v: "sentence", label: "Sentence" },
                    { v: "upper", label: "UPPER" },
                    { v: "lower", label: "lower" },
                  ]}
                  onChange={(v) => b("caption_case", v)}
                />
              </Line>
            </div>
            <Line label="Animation">
              <Chips
                value={brand.caption_animation}
                options={[
                  { v: "pop", label: "Pop" },
                  { v: "fade", label: "Fade" },
                  { v: "none", label: "None" },
                ]}
                onChange={(v) => b("caption_animation", v)}
              />
            </Line>
          </Section>

          <Section icon={Music2} title="Sound" sub="Everything is normalised to −14 LUFS for Reels and TikTok">
            <div className="grid grid-cols-2 gap-x-8 gap-y-5 max-xl:grid-cols-1">
              <Line label="Music under your voice" value={`${brand.music_under_voice_db ?? -14} dB`}>
                <Slider min={-40} max={0} step={1} value={[brand.music_under_voice_db ?? -14]} onValueChange={([v]) => b("music_under_voice_db", v)} />
                <div className="mt-1.5 flex justify-between text-[11px] text-subtle">
                  <span>barely there</span>
                  <span>as loud as you</span>
                </div>
              </Line>
              <Line label="Music on its own" value={`${brand.music_alone_lufs ?? -16} LUFS`}>
                <Slider min={-30} max={-8} step={1} value={[brand.music_alone_lufs ?? -16]} onValueChange={([v]) => b("music_alone_lufs", v)} />
                <div className="mt-1.5 flex justify-between text-[11px] text-subtle">
                  <span>gentle</span>
                  <span>loud</span>
                </div>
              </Line>
            </div>
          </Section>

          <Section icon={Sparkles} title="End card" sub="Presets and briefs can still switch it on or off">
            <div className="flex items-center justify-between gap-6 rounded-2xl bg-surface-2/60 p-4">
              <div>
                <div className="text-[13.5px] font-medium">On by default</div>
                <div className="text-[12.5px] text-muted-foreground">Your handle over a blurred last frame</div>
              </div>
              <Switch checked={!!brand.end_card} onCheckedChange={(v) => b("end_card", v)} />
            </div>
            <Line label="Length" value={`${(brand.end_card_seconds ?? 1.5).toFixed(1)}s`}>
              <Slider min={0.5} max={5} step={0.1} value={[brand.end_card_seconds ?? 1.5]} onValueChange={([v]) => b("end_card_seconds", Math.round(v * 10) / 10)} />
            </Line>
          </Section>

          <Section id="brain" icon={Bot} title="Brain" sub="Who makes the editing decisions. Everything mechanical runs on your Mac either way.">
            {s?.demo && (
              <div className="flex items-start gap-2.5 rounded-2xl bg-accent-soft p-3.5 text-[12.5px] text-foreground">
                <Sparkles className="mt-0.5 size-4 shrink-0" />
                Demo mode: brain calls get scripted answers (CUTROOM_BRAIN=demo). Start without --demo to use the backend picked here.
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 max-xl:grid-cols-1">
              <BackendCard
                active={app.brain_backend === "claude-code"}
                onPick={() => setApp({ ...app, brain_backend: "claude-code" })}
                icon={Bot}
                title="Claude Code"
                sub="Your logged-in Claude subscription. No API key."
                ok={s ? cc.installed === true && cc.logged_in === true : null}
                status={
                  !s ? "Checking…" : !cc.installed ? "Not installed" : cc.logged_in ? `Connected${cc.subscription ? ` · ${cc.subscription}` : ""}${cc.version ? ` · v${cc.version}` : ""}` : "Installed, not logged in"
                }
              />
              <BackendCard
                active={app.brain_backend === "anthropic-api"}
                onPick={() => setApp({ ...app, brain_backend: "anthropic-api" })}
                icon={KeyRound}
                title="Anthropic API"
                sub="Pay-as-you-go with ANTHROPIC_API_KEY in .env"
                ok={apiReady}
                status={apiReady == null ? (app.brain_backend === "anthropic-api" ? "Save to check" : "Not in use") : apiReady ? `Ready · ${s?.brain?.model}` : "No API key in .env"}
              />
            </div>
            {app.brain_backend === "claude-code" ? (
              <Line label="Model">
                <Chips
                  value={(app.brain_model ?? "") as string}
                  options={[
                    { v: "sonnet", label: "Sonnet (easier on usage)" },
                    { v: "opus", label: "Opus" },
                    { v: "", label: "CLI default" },
                  ]}
                  onChange={(v) => setApp({ ...app, brain_model: v || null })}
                />
              </Line>
            ) : (
              <Line label="Model">
                <Input value={app.anthropic_model ?? ""} onChange={(e) => setApp({ ...app, anthropic_model: e.target.value })} className="max-w-xs font-mono text-[12.5px]" />
              </Line>
            )}
            {cc.hint && app.brain_backend === "claude-code" && !cc.logged_in && <p className="text-[12.5px] text-warn-ink">{cc.hint}</p>}
          </Section>

          <Section icon={Server} title="This Mac" sub="What the pipeline needs to plan and render">
            <div className="flex items-center justify-between">
              <span className={cn("text-[13px]", s?.can_render ? "text-success-ink" : "text-warn-ink")}>
                {!s ? "Checking…" : s.can_render ? (s.can_plan ? "Ready to plan and render" : "Ready to render; the brain needs attention") : "Something needed for rendering is missing"}
              </span>
              <Button variant="ghost" size="sm" onClick={() => status.refetch()}>
                <RotateCw className={status.isFetching ? "animate-spin" : ""} /> Check again
              </Button>
            </div>
            <ul className="divide-y divide-border overflow-hidden rounded-2xl bg-surface-2/40 ring-1 ring-border">
              {(s?.checks ?? []).map((c) => (
                <li key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-[12.5px]">
                  {c.ok ? <Check className="size-4 shrink-0 text-success-ink" /> : <CircleAlert className={cn("size-4 shrink-0", c.required ? "text-warn-ink" : "text-subtle")} />}
                  <span className="w-48 shrink-0 font-medium text-foreground max-xl:w-36">{c.label}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground" title={c.detail}>
                    {c.ok ? c.detail : (c.hint ?? c.detail)}
                  </span>
                </li>
              ))}
              {!s && <li className="px-4 py-3"><Skeleton className="h-4 w-1/2" /></li>}
            </ul>
          </Section>
        </div>

        <aside className="max-lg:order-first">
          <div className="sticky top-6 flex flex-col gap-4">
            <div className="eyebrow">Live preview</div>
            <CaptionPreview brand={brand} fontFiles={settings.data.font_files ?? {}} backdrop={backdrop} className="w-full" />
            <div className="grid grid-cols-[96px_1fr] items-center gap-4">
              <EndCardPreview handle={brand.handle ?? ""} backdrop={backdrop} on={!!brand.end_card} />
              <div className="text-[12.5px] text-muted-foreground">
                <div className="font-medium text-foreground">End card</div>
                {brand.end_card ? `${(brand.end_card_seconds ?? 1.5).toFixed(1)}s at the end of every video` : "Off unless a preset or brief turns it on"}
              </div>
            </div>
          </div>
        </aside>
      </div>

      <AnimatePresence>
        {dirty > 0 && (
          <motion.div initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }} className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2">
            <div className="flex items-center gap-4 rounded-full bg-control py-2 pr-2 pl-5 text-control-ink shadow-lift">
              <span className="text-[13px]">
                {dirty} unsaved change{dirty > 1 ? "s" : ""}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="text-control-ink/80 hover:bg-control-ink/10 hover:text-control-ink"
                onClick={() => {
                  setBrand(settings.data!.brand)
                  setApp(settings.data!.app)
                }}
              >
                Discard
              </Button>
              <Button
                size="sm"
                variant="accent"
                disabled={save.isPending}
                onClick={() =>
                  save.mutate(
                    { brand: Object.keys(dirtyBrand).length ? dirtyBrand : undefined, app: Object.keys(dirtyApp).length ? dirtyApp : undefined },
                    {
                      onSuccess: (n) => {
                        setBrand(n.brand)
                        setApp(n.app)
                      },
                    },
                  )
                }
              >
                {save.isPending ? <Loader2 className="animate-spin" /> : <Check />} Save
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Page>
  )
}
