import { cn } from "@/lib/utils"

/** The Cutroom mark: a 9:16 frame between two cut marks. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "grid size-7 place-items-center rounded-lg bg-gradient-to-br from-[#a78bfa] to-[#6d4aff] shadow-[0_0_0_1px_rgb(255_255_255/0.12)_inset,0_4px_16px_-4px_rgb(124_92_255/0.7)]",
        className,
      )}
    >
      <svg viewBox="0 0 32 32" className="size-[70%]" fill="none" stroke="white" strokeWidth={2.4} strokeLinecap="round">
        <rect x="10" y="7" width="12" height="18" rx="2.5" />
        <path d="M5 13h4M23 13h4M5 19h4M23 19h4" />
      </svg>
    </div>
  )
}
