import type { ProjectStatus } from "@/api/types"

/** What the creator sees: draft / planning / needs review / rendering / done (and error). */
export type Stage = "draft" | "planning" | "review" | "rendering" | "done" | "error"

export const STAGES: Record<Stage, { label: string; dot: string; text: string; pulse?: boolean }> = {
  draft: { label: "Draft", dot: "bg-ink-faint", text: "text-ink-soft" },
  planning: { label: "Planning", dot: "bg-ink", text: "text-foreground", pulse: true },
  review: { label: "Needs review", dot: "bg-warn", text: "text-warn-ink" },
  rendering: { label: "Rendering", dot: "bg-info", text: "text-info-ink", pulse: true },
  done: { label: "Done", dot: "bg-success", text: "text-success-ink" },
  error: { label: "Needs attention", dot: "bg-destructive", text: "text-destructive" },
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
