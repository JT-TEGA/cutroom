import { useSyncExternalStore } from "react"

/** The last Claude problem a job ran into (usage limit, logged out...), for the banner. Lives for the session. */
export type BrainIssue = { code: string; message: string; hint?: string | null; at: number }

export const BRAIN_CODES = ["usage_limit", "claude_not_logged_in", "claude_not_installed", "api_key_missing", "sdk_missing"]

let current: BrainIssue | null = null
const listeners = new Set<() => void>()

export function reportBrainIssue(err: { code?: string; message?: string; hint?: string | null } | null | undefined) {
  if (!err?.code || !BRAIN_CODES.includes(err.code)) return
  current = { code: err.code, message: err.message ?? "", hint: err.hint, at: Date.now() }
  listeners.forEach((l) => l())
}

export function clearBrainIssue() {
  current = null
  listeners.forEach((l) => l())
}

export function useBrainIssue(): BrainIssue | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => current,
  )
}
