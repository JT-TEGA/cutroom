import createClient from "openapi-fetch"
import type { paths } from "./schema"
import type { ProjectFile } from "./types"

/** Everything goes through /api (Vite proxies it to the FastAPI server, WebSocket included). */
export const API = "/api"

export const api = createClient<paths>({ baseUrl: API })

/** The API's error shape: {"error": {"code", "message", "hint"}}. */
export class ApiError extends Error {
  code: string
  hint: string | null
  status: number

  constructor(message: string, code = "error", status = 0, hint: string | null = null) {
    super(message)
    this.code = code
    this.status = status
    this.hint = hint
  }
}

const OFFLINE = new ApiError(
  "Can't reach the Cutroom server.",
  "offline",
  0,
  "Is it running? Start everything with ./cutroom from the Cutroom folder.",
)

function toApiError(body: unknown, res: Response | undefined): ApiError {
  const err = (body as { error?: { code?: string; message?: string; hint?: string | null } } | undefined)?.error
  if (err?.message) return new ApiError(err.message, err.code ?? "error", res?.status ?? 0, err.hint ?? null)
  const detail = (body as { detail?: { loc?: (string | number)[]; msg?: string }[] } | undefined)?.detail
  if (Array.isArray(detail) && detail.length)
    return new ApiError(
      detail.map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; "),
      "invalid_request",
      res?.status ?? 422,
    )
  if (!res || [502, 503, 504].includes(res.status)) return OFFLINE
  return new ApiError(`Request failed (${res.status} ${res.statusText})`, "http_error", res.status)
}

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function call<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let r: { data?: T; error?: unknown; response: Response }
  try {
    r = await p
  } catch {
    throw OFFLINE
  }
  if (r.error !== undefined || !r.response.ok) throw toApiError(r.error, r.response)
  return r.data as T
}

/** Upload files with progress (fetch can't report upload progress, XHR can). */
export function uploadFiles(
  pid: string,
  files: File[],
  opts: { kind?: "clip" | "photo" | "voiceover" | "music"; onProgress?: (fraction: number) => void } = {},
): Promise<ProjectFile[]> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    for (const f of files) form.append("files", f, f.name)
    if (opts.kind) form.append("kind", opts.kind)
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${API}/projects/${encodeURIComponent(pid)}/files`)
    xhr.upload.onprogress = (e) => e.lengthComputable && opts.onProgress?.(e.loaded / e.total)
    xhr.onerror = () => reject(OFFLINE)
    xhr.onload = () => {
      let body: unknown
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        body = undefined
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as ProjectFile[])
      else reject(toApiError(body, { status: xhr.status, statusText: xhr.statusText } as Response))
    }
    xhr.send(form)
  })
}

// ---------------------------------------------------------------- media URLs

const q = encodeURIComponent

/** A clip or photo thumbnail. path is relative to the workspace (<project id>/<file path>). */
export const thumbUrl = (path: string, w = 320, t?: number | null) =>
  `${API}/media/thumbnail?path=${q(path)}&w=${w}${t != null ? `&t=${Math.max(0, t).toFixed(2)}` : ""}`
export const mediaUrl = (path: string) => `${API}/media/file?path=${q(path)}`
export const fileContentUrl = (pid: string, fileId: string) => `${API}/projects/${q(pid)}/files/${q(fileId)}/content`
export const videoUrl = (pid: string, version: number, download = false) =>
  `${API}/projects/${q(pid)}/outputs/${version}/video${download ? "?download=true" : ""}`
/** The copy without the music (posting with the song added in Instagram/TikTok). */
export const postVideoUrl = (pid: string, version: number, download = false) =>
  `${API}/projects/${q(pid)}/outputs/${version}/post${download ? "?download=true" : ""}`
/** A preview of an item in the Mac Photos library. */
export const photoThumbUrl = (id: string, w = 320) => `${API}/photos/thumbnail/${q(id)}?w=${w}`
export const contactUrl = (pid: string, version: number) => `${API}/projects/${q(pid)}/outputs/${version}/contact`
export const fontUrl = (file: string) => `${API}/fonts/${q(file)}`
export const jobSocketUrl = (jobId: string) =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${API}/ws/jobs/${q(jobId)}`
