import * as React from "react"
import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-2xl border border-input bg-surface px-4 py-2.5 text-base transition-[color,box-shadow,border-color] outline-none placeholder:text-muted-foreground focus-visible:border-ink/60 focus-visible:ring-[3px] focus-visible:ring-ring/10 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
