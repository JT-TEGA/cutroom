import { AlertTriangle, RotateCw } from "lucide-react"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center overflow-hidden rounded-card border border-dashed border-ink/15 bg-surface/50 px-6 py-16 text-center",
        className,
      )}
    >
      <div className="pointer-events-none absolute -top-10 left-1/2 h-40 w-96 -translate-x-1/2 rounded-full bg-accent/40 blur-3xl" />
      <div className="relative mb-4 grid size-12 place-items-center rounded-2xl bg-surface text-foreground shadow-soft">
        {icon}
      </div>
      <h3 className="relative text-[15px] font-semibold">{title}</h3>
      {description && <p className="relative mt-1.5 max-w-sm text-[13px] text-muted-foreground">{description}</p>}
      {action && <div className="relative mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
}) {
  const e = error as { message?: string; hint?: string | null } | null
  return (
    <div className={cn("flex flex-col items-center rounded-card border border-destructive/20 bg-destructive/[0.04] px-6 py-12 text-center", className)}>
      <AlertTriangle className="mb-3 size-6 text-destructive" />
      <h3 className="text-[15px] font-semibold">{e?.message ?? "Something went wrong"}</h3>
      {e?.hint && <p className="mt-1 max-w-md text-[13px] text-muted-foreground">{e.hint}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          <RotateCw /> Try again
        </Button>
      )}
    </div>
  )
}
