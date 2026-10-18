import type { ProjectStatus } from "@/api/types"

/** What the creator sees: draft / planning / needs review / rendering / done (and error). */
export type Stage = "draft" | "planning" | "review" | "rendering" | "done" | "error"

export const STAGES: Record<Stage, { label: string; dot: string; text: string; pulse?: boolean }> = {
  draft: { label: "Draft", dot: "bg-zinc-500", text: "text-zinc-300" },
  planning: { label: "Planning", dot: "bg-primary", text: "text-violet-200", pulse: true },
  review: { label: "Needs review", dot: "bg-warn", text: "text-amber-200" },
  rendering: { label: "Rendering", dot: "bg-info", text: "text-sky-200", pulse: true },
  done: { label: "Done", dot: "bg-ok", text: "text-emerald-200" },
  error: { label: "Needs attention", dot: "bg-destructive", text: "text-red-200" },
}

export function stageOf(status: ProjectStatus | string): Stage {
  switch (status) {
    case "planning":
      return "planning"
    case "planned":
      return "review"
    case "rendering":
      return "rendering"
    case "rendered":
      return "done"
    case "error":
      return "error"
    default:
      return "draft"
  }
}
