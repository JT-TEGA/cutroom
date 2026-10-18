/** 75.4 -> "1:15" */
export function clock(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "–"
  const t = Math.max(0, Math.round(s))
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`
}

/** 1.234 -> "1.2s" */
export function secs(s: number | null | undefined, digits = 1): string {
  if (s == null || !isFinite(s)) return "–"
  return `${s.toFixed(digits)}s`
}

export function bytes(n: number | null | undefined): string {
  if (!n) return "0 B"
  const u = ["B", "KB", "MB", "GB"]
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i > 1 ? 1 : 0)} ${u[i]}`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  const s = (Date.now() - d.getTime()) / 1000
  if (s < 45) return "just now"
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  if (s < 86400 * 2) return "yesterday"
  if (s < 86400 * 7) return `${Math.round(s / 86400)}d ago`
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
}

/** inputs/clips/incline-bench.mp4 -> "incline-bench.mp4" */
export const basename = (p: string | null | undefined) => (p ? p.split("/").pop() ?? p : "")

/** inputs/clips/incline-bench.mp4 -> "Incline bench" */
export function prettyName(p: string | null | undefined): string {
  const stem = basename(p).replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim()
  return stem ? stem[0].toUpperCase() + stem.slice(1) : ""
}

export const pluralize = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** 64.96 -> "1:05.0" (minutes, seconds and tenths) */
export function tc(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "–"
  const t = Math.round(Math.max(0, s) * 10) / 10
  const m = Math.floor(t / 60)
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`
}
