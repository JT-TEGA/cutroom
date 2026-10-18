import { presetMeta } from "@/lib/presets"
import { cn } from "@/lib/utils"

export function TypeBadge({ type, className }: { type: string | null | undefined; className?: string }) {
  const m = presetMeta(type)
  const Icon = m.icon
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-md border border-white/[0.07] bg-white/[0.04] px-2 text-[11.5px] font-medium text-zinc-300",
        className,
      )}
    >
      <Icon className="size-3 text-primary" />
      {m.title}
    </span>
  )
}
