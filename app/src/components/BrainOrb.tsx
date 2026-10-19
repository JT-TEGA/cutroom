import { motion } from "framer-motion"
import { cn } from "@/lib/utils"

/** The "Claude is thinking" visual: a soft, slowly moving butter glow around a black orb with a spark in the middle. */
export function BrainOrb({ className, active = true }: { className?: string; active?: boolean }) {
  return (
    <div className={cn("relative grid size-28 place-items-center", className)}>
      <div className={cn("absolute inset-0 rounded-full bg-accent/80 blur-2xl", active && "animate-orb")} />
      <div
        className={cn("absolute inset-3 rounded-full bg-warn/30 blur-xl", active && "animate-orb")}
        style={{ animationDelay: "-2s" }}
      />
      <motion.div
        className="relative grid size-14 place-items-center rounded-full bg-control shadow-lift"
        animate={active ? { scale: [1, 1.06, 1] } : undefined}
        transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
      >
        <svg viewBox="0 0 24 24" className="size-6 text-accent" fill="currentColor">
          <path d="M12 2.5c.4 3.9 1.6 6.3 3.4 7.6 1.4 1 3.3 1.5 6.1 1.9-2.8.4-4.7.9-6.1 1.9-1.8 1.3-3 3.7-3.4 7.6-.4-3.9-1.6-6.3-3.4-7.6-1.4-1-3.3-1.5-6.1-1.9 2.8-.4 4.7-.9 6.1-1.9 1.8-1.3 3-3.7 3.4-7.6Z" />
        </svg>
      </motion.div>
    </div>
  )
}
