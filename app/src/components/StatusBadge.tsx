import type { ProjectStatus } from "@/api/types"
import { STAGES, stageOf } from "@/lib/status"
import { cn } from "@/lib/utils"

export function StatusDot({ status, className }: { status: ProjectStatus | string; className?: string }) {
  const s = STAGES[stageOf(status)]
  return (
    <span className={cn("relative inline-flex size-2", className)}>
      {s.pulse && <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", s.dot)} />}
      <span className={cn("relative inline-flex size-2 rounded-full", s.dot)} />
    </span>
  )
}

export function StatusBadge({ status, className }: { status: ProjectStatus | string; className?: string }) {
  const s = STAGES[stageOf(status)]
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-full bg-surface/90 px-2.5 text-[11.5px] font-medium shadow-soft backdrop-blur-md",
        s.text,
        className,
      )}
    >
      <StatusDot status={status} />
      {s.label}
    </span>
  )
}
