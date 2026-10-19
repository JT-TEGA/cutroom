import { presetMeta } from "@/lib/presets"
import { cn } from "@/lib/utils"

export function TypeBadge({ type, className }: { type: string | null | undefined; className?: string }) {
  const m = presetMeta(type)
  const Icon = m.icon
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-full bg-surface-2 px-2.5 text-[11.5px] font-medium text-foreground",
        className,
      )}
    >
      <Icon className="size-3 text-ink-soft" />
      {m.title}
    </span>
  )
}
