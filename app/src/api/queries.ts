import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, call, uploadFiles, uploadTake } from "./client"
import type { Brief, Job, JobKind, Project, ProjectFile, Settings, Take, Timeline, TimelineView } from "./types"

export const keys = {
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  timeline: (id: string) => ["timeline", id] as const,
  outputs: (id: string) => ["outputs", id] as const,
  voiceover: (id: string) => ["voiceover", id] as const,
  takes: (id: string) => ["takes", id] as const,
  music: (id: string, fileId?: string) => ["music", id, fileId ?? ""] as const,
  photosStatus: ["photos", "status"] as const,
  photosAlbums: ["photos", "albums"] as const,
  photosItems: (f: PhotoFilter) => ["photos", "items", f] as const,
  jobs: (projectId?: string) => ["jobs", projectId ?? "all"] as const,
  job: (id: string) => ["job", id] as const,
  presets: ["presets"] as const,
  settings: ["settings"] as const,
  status: ["system-status"] as const,
}

const ACTIVE = ["queued", "running"]
export const isActive = (j: Pick<Job, "status">) => ACTIVE.includes(j.status)

// ---------------------------------------------------------------- reads

export function useProjects() {
  return useQuery({
    queryKey: keys.projects,
    queryFn: () => call(api.GET("/projects")),
    refetchInterval: (q) =>
      q.state.data?.some((p) => p.status === "planning" || p.status === "rendering") ? 2000 : false,
  })
}

export function useProject(id: string) {
  return useQuery({ queryKey: keys.project(id), queryFn: () => call(api.GET("/projects/{pid}", { params: { path: { pid: id } } })) })
}

export function useTimeline(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.timeline(id),
    queryFn: () => call(api.GET("/projects/{pid}/timeline", { params: { path: { pid: id } } })),
    enabled,
    retry: (n, e) => (e as { status?: number }).status !== 404 && n < 2,
  })
}

export function useOutputs(id: string) {
  return useQuery({
    queryKey: keys.outputs(id),
    queryFn: () => call(api.GET("/projects/{pid}/outputs", { params: { path: { pid: id } } })),
  })
}

export function useVoiceover(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.voiceover(id),
    queryFn: () => call(api.GET("/projects/{pid}/voiceover", { params: { path: { pid: id } } })),
    enabled,
  })
}

/** The voiceover takes recorded in the app (they're kept in the project, so they're back after a refresh). */
export function useTakes(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.takes(id),
    queryFn: () => call(api.GET("/projects/{pid}/takes", { params: { path: { pid: id } } })),
    enabled,
  })
}

/** The song for the Music step: waveform, BPM, drops, the auto start and the creator's own choices. */
export function useMusic(id: string, fileId: string | undefined) {
  return useQuery({
    queryKey: keys.music(id, fileId),
    queryFn: () => call(api.GET("/projects/{pid}/music", { params: { path: { pid: id } } })),
    enabled: !!fileId,
    retry: (n, e) => (e as { status?: number }).status !== 404 && n < 1,
    staleTime: 30_000,
  })
}

// ---------------------------------------------------------------- the Mac Photos library

export type PhotoFilter = { album?: string; kind: "all" | "photo" | "video"; since?: string; until?: string; favorites?: boolean }
const PHOTO_PAGE = 120

/** Whether the library can be read; polls while it's being read. */
export function usePhotosStatus(enabled: boolean) {
  return useQuery({
    queryKey: keys.photosStatus,
    queryFn: () => call(api.GET("/photos/status")),
    enabled,
    refetchInterval: (q) => (q.state.data?.state === "loading" ? 800 : false),
  })
}

export function usePhotosAlbums(enabled: boolean) {
  return useQuery({ queryKey: keys.photosAlbums, queryFn: () => call(api.GET("/photos/albums")), enabled, staleTime: 60_000 })
}

export function usePhotoItems(f: PhotoFilter, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.photosItems(f),
    queryFn: ({ pageParam }) =>
      call(api.GET("/photos/items", {
        params: {
          query: {
            album: f.album ?? null,
            kind: f.kind,
            since: f.since || null,
            until: f.until || null,
            favorites: !!f.favorites,
            offset: pageParam,
            limit: PHOTO_PAGE,
          },
        },
      })),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
    enabled,
    staleTime: 60_000,
  })
}

export function useRefreshPhotos() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => call(api.POST("/photos/refresh")),
    onSuccess: (st) => {
      qc.setQueryData(keys.photosStatus, st)
      qc.invalidateQueries({ queryKey: ["photos"] })
    },
  })
}

export function useOpenPrivacySettings() {
  return useMutation({
    mutationFn: (pane: "full_disk_access" | "photos" | "automation" | "microphone") => call(api.POST("/photos/open-settings", { body: { pane } })),
  })
}

/** Import items from Photos into the project: a background job (follow it with useJobStream). */
export function useImportPhotos(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { ids: string[]; live_video: boolean }) =>
      call(api.POST("/projects/{pid}/photos/import", { params: { path: { pid: id }, query: { wait: false } }, body: v })),
    onSuccess: (job) => {
      qc.setQueryData(keys.job(job.id), job)
      qc.invalidateQueries({ queryKey: keys.jobs(id) })
    },
  })
}

export function useJobs(projectId?: string) {
  return useQuery({
    queryKey: keys.jobs(projectId),
    queryFn: () => call(api.GET("/jobs", { params: { query: { project_id: projectId ?? null } } })),
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 1500 : false),
    placeholderData: keepPreviousData,
  })
}

export function usePresets() {
  return useQuery({ queryKey: keys.presets, queryFn: () => call(api.GET("/presets")), staleTime: 60_000 })
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: () => call(api.GET("/settings")) })
}

export function useSystemStatus() {
  return useQuery({
    queryKey: keys.status,
    queryFn: () => call(api.GET("/system/status", { params: { query: { claude: true } } })),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  })
}

// ---------------------------------------------------------------- writes

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name?: string; brief?: Partial<Brief> }) =>
      call(api.POST("/projects", { body: { name: body.name ?? "", brief: (body.brief ?? null) as Brief | null } })),
    onSuccess: (p) => {
      qc.setQueryData(keys.project(p.id), p)
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}

export function usePatchProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name?: string; brief?: Partial<Brief>; answers?: Record<string, string> }) =>
      call(api.PATCH("/projects/{pid}", {
        params: { path: { pid: id } },
        body: { name: body.name ?? null, brief: body.brief ?? null, answers: body.answers ?? null },
      })),
    onSuccess: (p) => {
      qc.setQueryData(keys.project(id), p)
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => call(api.DELETE("/projects/{pid}", { params: { path: { pid: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  })
}

/** Optimistically apply a change to the project's file list. */
function setFiles(qc: ReturnType<typeof useQueryClient>, id: string, fn: (files: ProjectFile[]) => ProjectFile[]) {
  qc.setQueryData<Project>(keys.project(id), (p) => (p ? { ...p, files: fn(p.files ?? []) } : p))
}

export function useUpload(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { files: File[]; kind?: "clip" | "photo" | "voiceover" | "music"; take?: string; onProgress?: (f: number) => void }) =>
      uploadFiles(id, v.files, { kind: v.kind, take: v.take, onProgress: v.onProgress }),
    onSuccess: (added) => setFiles(qc, id, (files) => [...files, ...added]),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.project(id) })
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}

export function useSaveTake(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { recording: Blob; name: string }) => uploadTake(id, v.recording, v.name),
    meta: { silent: true }, // the recorder shows what went wrong, with Try again
    onSuccess: (t) => qc.setQueryData<Take[]>(keys.takes(id), (list) => [...(list ?? []).filter((x) => x.id !== t.id), t]),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.takes(id) }),
  })
}

export function useDeleteTake(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (takeId: string) =>
      call(api.DELETE("/projects/{pid}/takes/{take_id}", { params: { path: { pid: id, take_id: takeId } } })),
    onMutate: (takeId) => qc.setQueryData<Take[]>(keys.takes(id), (list) => list?.filter((t) => t.id !== takeId)),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.takes(id) }),
  })
}

export function useReorderFiles(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (order: string[]) =>
      call(api.PATCH("/projects/{pid}/files", { params: { path: { pid: id } }, body: { order } })),
    onMutate: (order) =>
      setFiles(qc, id, (files) => order.map((fid) => files.find((f) => f.id === fid)).filter(Boolean) as ProjectFile[]),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.project(id) }),
  })
}

export function usePatchFile(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { fileId: string; name?: string }) =>
      call(api.PATCH("/projects/{pid}/files/{file_id}", {
        params: { path: { pid: id, file_id: v.fileId } },
        body: { name: v.name ?? null, clear_trim: false },
      })),
    onSuccess: (f) => setFiles(qc, id, (files) => files.map((x) => (x.id === f.id ? f : x))),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.project(id) }),
  })
}

export function useDeleteFile(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) =>
      call(api.DELETE("/projects/{pid}/files/{file_id}", { params: { path: { pid: id, file_id: fileId } } })),
    onMutate: (fileId) => setFiles(qc, id, (files) => files.filter((f) => f.id !== fileId)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.project(id) })
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}

/** Start an editing job (analyse / plan / render / revise). Returns the job. */
export function useStartJob(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { kind: Exclude<JobKind, "photos-import">; notes?: string; render?: boolean; draft?: boolean }): Promise<Job> => {
      const path = { params: { path: { pid: id }, query: { wait: false } } }
      switch (v.kind) {
        case "analyse":
          return call(api.POST("/projects/{pid}/analyse", path))
        case "plan":
          return call(api.POST("/projects/{pid}/plan", path))
        case "render":
          return call(api.POST("/projects/{pid}/render", { ...path, body: { draft: !!v.draft } }))
        case "revise":
          return call(api.POST("/projects/{pid}/revise", { ...path, body: { notes: v.notes ?? "", render: !!v.render } }))
        case "reference":
          return call(api.POST("/projects/{pid}/reference", { ...path, body: {} }))
      }
    },
    onSuccess: (job) => {
      qc.setQueryData(keys.job(job.id), job)
      qc.invalidateQueries({ queryKey: keys.jobs(id) })
      qc.invalidateQueries({ queryKey: keys.project(id) })
      qc.invalidateQueries({ queryKey: keys.projects })
    },
  })
}

export function useRetryJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => call(api.POST("/jobs/{job_id}/retry", { params: { path: { job_id: jobId } } })),
    onSuccess: (job) => {
      qc.setQueryData(keys.job(job.id), job)
      if (job.project_id) qc.invalidateQueries({ queryKey: keys.jobs(job.project_id) })
    },
  })
}

export function useSaveTimeline(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (tl: Timeline) =>
      call(api.PUT("/projects/{pid}/timeline", { params: { path: { pid: id } }, body: tl })),
    onSuccess: (view: TimelineView) => {
      qc.setQueryData(keys.timeline(id), view)
      qc.invalidateQueries({ queryKey: keys.project(id) })
    },
  })
}

export function useReveal(id: string) {
  return useMutation({
    mutationFn: (version?: number) =>
      call(api.POST("/projects/{pid}/reveal", { params: { path: { pid: id } }, body: { version: version ?? null } })),
  })
}

export function useSaveSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { brand?: Partial<Settings["brand"]>; app?: Partial<Settings["app"]> }) =>
      call(api.PUT("/settings", { body: { brand: body.brand ?? null, app: body.app ?? null } })),
    onSuccess: (s) => {
      qc.setQueryData(keys.settings, s)
      qc.invalidateQueries({ queryKey: keys.status })
    },
  })
}

export function useSavePreset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { name: string; description?: string; notes?: string; settings?: Record<string, unknown> }) =>
      call(api.PUT("/presets/{name}", {
        params: { path: { name: v.name } },
        body: { description: v.description ?? null, notes: v.notes ?? null, settings: v.settings ?? null },
      })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.presets }),
  })
}
