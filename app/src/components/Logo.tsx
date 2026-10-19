import { cn } from "@/lib/utils"

/** The Cutroom mark: a 9:16 frame between two cut marks. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "grid size-7 place-items-center rounded-[10px] bg-accent text-accent-ink ring-1 ring-ink/10 ring-inset",
        className,
      )}
    >
      <svg viewBox="0 0 32 32" className="size-[70%]" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round">
        <rect x="10" y="7" width="12" height="18" rx="2.5" />
        <path d="M5 13h4M23 13h4M5 19h4M23 19h4" />
      </svg>
    </div>
  )
}
