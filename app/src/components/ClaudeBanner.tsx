import { AnimatePresence, motion } from "framer-motion"
import { Check, Copy, KeyRound, PlugZap, RotateCw, ServerOff, TimerReset, X } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"
import { useSystemStatus } from "@/api/queries"
import { Button } from "@/components/ui/button"
import { clearBrainIssue, useBrainIssue } from "@/lib/brain-issue"

type Problem = {
  key: string
  icon: typeof PlugZap
  title: string
  body: string
  command?: string
  settingsLink?: boolean
}

function CopyCommand({ command }: { command: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(command)
        setDone(true)
        setTimeout(() => setDone(false), 1500)
      }}
      className="inline-flex h-7 items-center gap-2 rounded-md border border-amber-200/15 bg-black/40 px-2.5 font-mono text-[12px] text-amber-50 transition hover:bg-black/60"
    >
      <span className="text-amber-200/50">$</span>
      {command}
      {done ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5 opacity-60" />}
    </button>
  )
}

/** Tells the creator, in plain words, when the editing brain can't work and what to do about it. */
export function ClaudeBanner() {
  const status = useSystemStatus()
  const issue = useBrainIssue()
  const [dismissed, setDismissed] = useState<string | null>(null)

  const s = status.data
  let p: Problem | null = null
  if (status.error && (status.error as { code?: string }).code === "offline") {
    p = {
      key: "offline",
      icon: ServerOff,
      title: "The Cutroom server isn't running",
      body: "Nothing can be saved or rendered until it's back. Start it from the Cutroom folder:",
      command: "./cutroom",
    }
  } else if (issue?.code === "usage_limit") {
    p = {
      key: `limit-${issue.at}`,
      icon: TimerReset,
      title: issue.message || "You've reached your Claude usage limit",
      body: "Planning and revisions pause until it resets. Uploads, timeline edits and renders keep working. Have an API key? Switch the brain in Settings.",
      settingsLink: true,
    }
  } else if (s && !s.demo) {
    const cc = s.claude_code as { installed?: boolean; logged_in?: boolean | null; hint?: string }
    const backend = s.brain?.backend
    if (backend === "claude-code" && (cc.installed === false || issue?.code === "claude_not_installed")) {
      p = {
        key: "not-installed",
        icon: PlugZap,
        title: "Claude Code isn't installed",
        body: "Cutroom plans your edits with your own Claude Code: no API key needed. Install it, run claude once to log in, then check again.",
        command: "npm install -g @anthropic-ai/claude-code",
      }
    } else if (backend === "claude-code" && (cc.logged_in === false || issue?.code === "claude_not_logged_in")) {
      p = {
        key: "logged-out",
        icon: KeyRound,
        title: "Claude Code isn't logged in",
        body: "Open a terminal, run this, log in with your Claude account, then check again.",
        command: "claude",
      }
    } else if (backend === "anthropic-api" && s.brain && s.brain.ready === false) {
      p = {
        key: "api-key",
        icon: KeyRound,
        title: "The Anthropic API brain has no key",
        body: "Add ANTHROPIC_API_KEY to the .env file in the Cutroom folder, or switch back to Claude Code in Settings.",
        settingsLink: true,
      }
    }
  } else if (s?.demo && issue?.code === "claude_not_logged_in") {
    p = {
      key: "logged-out",
      icon: KeyRound,
      title: "Claude Code isn't logged in",
      body: "Open a terminal, run this, log in with your Claude account, then check again.",
      command: "claude",
    }
  }

  const show = p && dismissed !== p.key
  return (
    <AnimatePresence initial={false}>
      {show && p && (
        <motion.div
          key={p.key}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden"
        >
          <div className="mx-6 mt-4 flex items-start gap-3 rounded-xl border border-amber-300/15 bg-gradient-to-r from-amber-400/[0.09] to-amber-400/[0.03] px-4 py-3">
            <p.icon className="mt-0.5 size-4.5 shrink-0 text-warn" />
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-semibold text-amber-50">{p.title}</div>
              <div className="mt-0.5 text-[13px] text-amber-100/70">{p.body}</div>
              {(p.command || p.settingsLink) && (
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  {p.command && <CopyCommand command={p.command} />}
                  {p.settingsLink && (
                    <Button asChild size="xs" variant="outline" className="border-amber-200/15">
                      <Link to="/settings">Open Settings</Link>
                    </Button>
                  )}
                </div>
              )}
            </div>
            <Button
              size="xs"
              variant="ghost"
              className="text-amber-100/80"
              onClick={() => {
                clearBrainIssue()
                status.refetch()
              }}
            >
              <RotateCw className={status.isFetching ? "animate-spin" : ""} /> Check again
            </Button>
            <button
              aria-label="Dismiss"
              onClick={() => setDismissed(p.key)}
              className="rounded p-1 text-amber-100/50 hover:bg-white/5 hover:text-amber-50"
            >
              <X className="size-3.5" />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
