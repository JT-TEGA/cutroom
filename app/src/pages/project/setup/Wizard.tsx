import { motion } from "framer-motion"
import { Check } from "lucide-react"
import type { ReactNode } from "react"
import { usePresets } from "@/api/queries"
import { Skeleton } from "@/components/ui/skeleton"
import { GROUPS, presetMeta } from "@/lib/presets"
import { cn } from "@/lib/utils"

export const STEPS = [
  { id: "type", label: "Content type" },
  { id: "media", label: "Media" },
  { id: "idea", label: "The idea" },
  { id: "review", label: "Review" },
] as const
export type StepId = (typeof STEPS)[number]["id"]

export function Stepper({ current, onPick, done }: { current: StepId; onPick?: (s: StepId) => void; done?: StepId[] }) {
  const at = STEPS.findIndex((s) => s.id === current)
  return (
    <ol className="flex items-center gap-2">
      {STEPS.map((s, i) => {
        const active = i === at
        const complete = done ? done.includes(s.id) && !active : i < at
        const clickable = !!onPick && !active
        return (
          <li key={s.id} className="flex items-center gap-2">
            {i > 0 && <span className={cn("h-px w-8 bg-ink/15 max-lg:w-4", i <= at && "bg-ink/60")} />}
            <button
              disabled={!clickable}
              onClick={() => onPick?.(s.id)}
              className={cn(
                "flex items-center gap-2 rounded-full py-1 pr-3.5 pl-1 text-[13px] font-medium transition-colors",
                active ? "bg-accent text-accent-ink" : "text-ink-soft",
                clickable && "hover:text-foreground",
              )}
            >
              <span
                className={cn(
                  "grid size-6 place-items-center rounded-full border text-[11.5px] tabular-nums",
                  active && "border-control bg-control text-control-ink",
                  complete && "border-ink/70 bg-surface text-foreground",
                  !active && !complete && "border-ink/20",
                )}
              >
                {complete ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span className="max-md:hidden">{s.label}</span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

/** Step 1: one card per preset, grouped Lifestyle / Fashion / Gym. */
export function ContentTypePicker({ value, onChange }: { value: string | null | undefined; onChange: (name: string) => void }) {
  const presets = usePresets()
  if (presets.isLoading)
    return (
      <div className="grid grid-cols-3 gap-6 max-lg:grid-cols-1">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-72 rounded-card" />
        ))}
      </div>
    )
  const all = presets.data ?? []
  const known = new Set(GROUPS.flatMap((g) => g.presets))
  const groups = [
    ...GROUPS.map((g) => ({ ...g, items: g.presets.map((n) => all.find((p) => p.name === n)).filter((p) => !!p) })),
    { id: "other", label: "Your presets", blurb: "Made in the Presets page", items: all.filter((p) => !known.has(p.name)) },
  ].filter((g) => g.items.length)

  return (
    <div className="grid grid-cols-3 gap-6 max-lg:grid-cols-1">
      {groups.map((g, gi) => (
        <section key={g.id}>
          <div className="mb-3 px-1">
            <div className="text-[13.5px] font-semibold">{g.label}</div>
            <div className="text-[12.5px] text-muted-foreground">{g.blurb}</div>
          </div>
          <div className="flex flex-col gap-2.5">
            {g.items.map((p, i) => {
              const m = presetMeta(p.name)
              const sel = value === p.name
              return (
                <motion.button
                  key={p.name}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.03 * (gi * 4 + i) }}
                  onClick={() => onChange(p.name)}
                  className={cn(
                    "group relative flex items-start gap-3.5 overflow-hidden rounded-2xl bg-card p-3.5 text-left shadow-soft transition",
                    sel ? "bg-accent-soft ring-[1.5px] ring-ink" : "hover:-translate-y-px hover:shadow-lift",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-10 shrink-0 place-items-center rounded-full transition",
                      sel ? "bg-accent text-accent-ink" : "bg-surface-2 text-foreground",
                    )}
                  >
                    <m.icon className="size-[18px]" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-semibold">{m.title}</span>
                    <span className="mt-0.5 block text-[12.5px] leading-snug text-muted-foreground">{p.description}</span>
                  </span>
                  <span
                    className={cn(
                      "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border transition",
                      sel ? "border-control bg-control text-control-ink" : "border-ink/25 opacity-0 group-hover:opacity-100",
                    )}
                  >
                    {sel && <Check className="size-3" />}
                  </span>
                </motion.button>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}

/** The wizard's sticky footer: back, a hint, continue. */
export function WizardFooter({ left, hint, right }: { left?: ReactNode; hint?: ReactNode; right?: ReactNode }) {
  return (
    <div className="sticky bottom-0 z-20 -mx-8 mt-10 border-t border-border bg-background/85 px-8 py-4 backdrop-blur-xl max-xl:-mx-6 max-xl:px-6">
      <div className="flex items-center gap-4">
        <div className="flex-1">{left}</div>
        {hint && <div className="text-[12.5px] text-muted-foreground max-md:hidden">{hint}</div>}
        <div className="flex items-center gap-2">{right}</div>
      </div>
    </div>
  )
}
