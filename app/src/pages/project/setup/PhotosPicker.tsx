import { useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  Clock,
  Cloud,
  Film,
  FolderLock,
  Heart,
  ImageIcon,
  Images,
  Loader2,
  RotateCw,
  Settings2,
  X,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { photoThumbUrl } from "@/api/client"
import { useJobStream } from "@/api/jobs"
import {
  keys,
  type PhotoFilter,
  useImportPhotos,
  useOpenPrivacySettings,
  usePhotoItems,
  usePhotosAlbums,
  usePhotosStatus,
  useRefreshPhotos,
} from "@/api/queries"
import type { PhotoItem, PhotosStatus, ProjectFile } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { clock, pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

type Source = { id: string; title: string; album?: string; favorites?: boolean; videos?: boolean }

const KINDS = [
  { value: "all", label: "All" },
  { value: "photo", label: "Photos" },
  { value: "video", label: "Videos" },
] as const

/** A thumbnail from the Photos library, square, with a shimmer while it loads. */
function PhotoThumb({ id, w = 240, className }: { id: string | null | undefined; w?: number; className?: string }) {
  const [state, setState] = useState<"loading" | "ok" | "error">("loading")
  return (
    <div className={cn("relative overflow-hidden bg-surface-2", className)}>
      {id && state !== "error" && (
        <img
          src={photoThumbUrl(id, w)}
          alt=""
          draggable={false}
          loading="lazy"
          onLoad={() => setState("ok")}
          onError={() => setState("error")}
          className={cn("size-full object-cover transition-opacity duration-300", state === "ok" ? "opacity-100" : "opacity-0")}
        />
      )}
      {state === "loading" && id && <div className="absolute inset-0 animate-pulse bg-gradient-to-br from-ink/[0.05] to-transparent" />}
      {(!id || state === "error") && (
        <div className="absolute inset-0 grid place-items-center text-subtle">
          <ImageIcon className="size-4" />
        </div>
      )}
    </div>
  )
}

/** macOS hasn't let Cutroom read the library (or it can't be read): what to do, step by step. */
function AccessHelp({ st, onCheck, checking }: { st: PhotosStatus; onCheck: () => void; checking: boolean }) {
  const open = useOpenPrivacySettings()
  const app = st.app ?? "Terminal"
  const where = app === "Terminal" ? "Applications → Utilities" : "Applications"
  const denied = st.state === "no_access"
  return (
    <div className="mx-auto flex max-w-[560px] flex-col items-center py-8 text-center" data-testid="photos-access">
      <span className="mb-4 grid size-12 place-items-center rounded-full bg-accent text-accent-ink">
        {denied ? <FolderLock className="size-5" /> : <AlertTriangle className="size-5" />}
      </span>
      <h2 className="text-[19px] font-semibold tracking-[-0.01em]">
        {denied ? "Let Cutroom see your Photos library" : st.message || "Photos isn't available"}
      </h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
        {denied
          ? "macOS keeps the Photos library private until you allow it. Cutroom only reads it: nothing in your library changes."
          : st.hint}
      </p>
      {denied && (
        <ol className="mt-6 grid w-full gap-3 text-left text-[13px] leading-relaxed">
          {[
            <>
              Open <b>System Settings → Privacy &amp; Security → Full Disk Access</b>.{" "}
              <button onClick={() => open.mutate("full_disk_access")} className="font-medium text-foreground underline decoration-ink/30 underline-offset-2 hover:decoration-ink">
                Open it for me
              </button>
            </>,
            <>
              Turn on <b>{app}</b>. If it isn't in the list, click <b>+</b> and pick it from {where}.
            </>,
            <>
              Quit <b>{app}</b> completely (<kbd className="rounded-md bg-surface-2 px-1.5 font-mono text-[11.5px]">⌘Q</kbd>), open it again and
              start Cutroom again with <code className="rounded-md bg-surface-2 px-1.5 font-mono text-[11.5px]">./cutroom</code>.
            </>,
            <>
              If <b>{app}</b> is listed under <b>Privacy &amp; Security → Photos</b>, turn it on there too. Photos that are only in iCloud are
              downloaded through the Photos app: the first time, macOS asks to let {app} control Photos. Click <b>OK</b>.
            </>,
          ].map((step, i) => (
            <li key={i} className="flex gap-3 rounded-2xl bg-surface-2/60 px-4 py-3">
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-control font-mono text-[11px] text-control-ink">{i + 1}</span>
              <span className="text-foreground">{step}</span>
            </li>
          ))}
        </ol>
      )}
      <Button className="mt-6" onClick={onCheck} disabled={checking}>
        {checking ? <Loader2 className="animate-spin" /> : <RotateCw />} Check again
      </Button>
      {st.library && <div className="mt-3 font-mono text-[11px] text-subtle">{st.library}</div>}
    </div>
  )
}

function Tile({ item, selected, onClick }: { item: PhotoItem; selected: number; onClick: (e: React.MouseEvent) => void }) {
  return (
    <button
      onClick={onClick}
      data-photo={item.id}
      title={item.name}
      className={cn(
        "group relative aspect-square overflow-hidden rounded-xl outline-none transition",
        selected ? "ring-[2.5px] ring-ink ring-offset-2 ring-offset-surface" : "hover:brightness-105",
      )}
    >
      <PhotoThumb id={item.id} className={cn("absolute inset-0 transition-transform", selected && "scale-[0.94] rounded-lg")} />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-ink/25 via-transparent to-ink/35" />
      {item.live && (
        <span className="absolute top-1.5 left-1.5 rounded-full bg-control/70 px-1.5 text-[9.5px] font-semibold tracking-wider text-control-ink backdrop-blur">
          LIVE
        </span>
      )}
      {!item.local && (
        <Cloud className="absolute bottom-1.5 left-1.5 size-3.5 text-control-ink drop-shadow" aria-label="in iCloud: downloaded when you import it" />
      )}
      {item.kind === "video" && (
        <span className="absolute right-1.5 bottom-1.5 inline-flex items-center gap-1 rounded-full bg-control/70 px-1.5 font-mono text-[10.5px] text-control-ink backdrop-blur">
          <Film className="size-2.5" />
          {clock(item.duration)}
        </span>
      )}
      <span
        className={cn(
          "absolute top-1.5 right-1.5 grid size-5 place-items-center rounded-full border text-[10.5px] font-semibold transition",
          selected ? "border-accent bg-accent text-accent-ink" : "border-control-ink/80 bg-control/20 opacity-0 group-hover:opacity-100",
        )}
      >
        {selected ? selected : ""}
      </span>
    </button>
  )
}

function Browser({ onPicked, picked, toggle }: { picked: Map<string, PhotoItem>; onPicked: (m: Map<string, PhotoItem>) => void; toggle: (it: PhotoItem) => void }) {
  const albums = usePhotosAlbums(true)
  const status = usePhotosStatus(true).data
  const [source, setSource] = useState<Source>({ id: "recents", title: "Recents" })
  const [kind, setKind] = useState<PhotoFilter["kind"]>("all")
  const [since, setSince] = useState("")
  const [until, setUntil] = useState("")
  const filter: PhotoFilter = {
    album: source.album,
    favorites: source.favorites,
    kind: source.videos ? "video" : kind,
    since: since || undefined,
    until: until || undefined,
  }
  const items = usePhotoItems(filter, true)
  const list = useMemo(() => items.data?.pages.flatMap((p) => p.items) ?? [], [items.data])
  const total = items.data?.pages[0]?.total ?? 0
  const last = useRef<number | null>(null)
  const grid = useRef<HTMLDivElement>(null)
  const more = useRef<HTMLDivElement>(null)
  const order = useMemo(() => [...picked.keys()], [picked])

  // load the next page when the end of the grid scrolls into view
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = items
  useEffect(() => {
    const el = more.current
    if (!el || !hasNextPage) return
    const io = new IntersectionObserver(
      (e) => {
        if (e[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage()
      },
      { root: grid.current, rootMargin: "400px" },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, list.length])

  const pick = (it: PhotoItem, i: number, e: React.MouseEvent) => {
    if (e.shiftKey && last.current != null) {
      const [a, b] = [Math.min(last.current, i), Math.max(last.current, i)]
      const next = new Map(picked)
      for (const x of list.slice(a, b + 1)) next.set(x.id, x)
      onPicked(next)
    } else toggle(it)
    last.current = i
  }

  const sources: (Source & { count?: number; icon: typeof Clock })[] = [
    { id: "recents", title: "Recents", icon: Clock, count: (status?.photos ?? 0) + (status?.videos ?? 0) },
    { id: "favorites", title: "Favourites", favorites: true, icon: Heart, count: status?.favorites },
    { id: "videos", title: "Videos", videos: true, icon: Film, count: status?.videos },
  ]
  const dated = !!(since || until)

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[230px_minmax(0,1fr)] max-md:grid-cols-1">
      <aside className="min-h-0 overflow-y-auto border-r border-border p-3 max-md:hidden">
        <div className="eyebrow mb-1.5 px-2">Library</div>
        {sources.map((s) => (
          <button
            key={s.id}
            onClick={() => setSource(s)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-full px-3 py-1.5 text-left text-[13px] transition",
              source.id === s.id ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-ink/[0.05] hover:text-foreground",
            )}
          >
            <s.icon className="size-4" />
            <span className="flex-1">{s.title}</span>
            <span className={cn("font-mono text-[11px]", source.id === s.id ? "text-accent-ink" : "text-subtle")}>{s.count ?? ""}</span>
          </button>
        ))}
        <div className="eyebrow mt-4 mb-1.5 px-2">Albums</div>
        {albums.isLoading &&
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="mb-1.5 h-10 rounded-lg" />)}
        {albums.data?.length === 0 && <div className="px-2 text-[12.5px] text-subtle">No albums</div>}
        {albums.data?.map((a) => (
          <button
            key={a.id}
            onClick={() => setSource({ id: a.id, title: a.title, album: a.id })}
            data-album={a.title}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-2xl px-2 py-1.5 text-left transition",
              source.id === a.id ? "bg-accent text-accent-ink" : "hover:bg-ink/[0.05]",
            )}
          >
            <PhotoThumb id={a.cover} w={96} className="size-9 shrink-0 rounded-xl" />
            <span className="min-w-0 flex-1">
              <span className={cn("block truncate text-[13px]", source.id === a.id ? "text-accent-ink" : "text-foreground")}>{a.title}</span>
              <span className={cn("block truncate text-[11px]", source.id === a.id ? "text-accent-ink" : "text-subtle")}>
                {a.folder ? `${a.folder} · ` : ""}
                {a.count}
              </span>
            </span>
          </button>
        ))}
      </aside>

      <section className="flex min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-semibold">{source.title}</div>
            <div className="text-[12px] text-muted-foreground">{items.isLoading ? "…" : pluralize(total, "item")}</div>
          </div>
          {!source.videos && (
            <div className="flex rounded-full bg-surface-2 p-0.5">
              {KINDS.map((k) => (
                <button
                  key={k.value}
                  onClick={() => setKind(k.value)}
                  className={cn(
                    "h-7 rounded-full px-3 text-[12.5px] font-medium transition",
                    kind === k.value ? "bg-accent text-accent-ink" : "text-ink-soft hover:text-foreground",
                  )}
                >
                  {k.label}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <label htmlFor="photos-since">From</label>
            <input
              id="photos-since"
              type="date"
              value={since}
              max={until || undefined}
              onChange={(e) => setSince(e.target.value)}
              className="h-8 rounded-full border border-input bg-surface px-3 text-[12.5px] text-foreground"
            />
            <label htmlFor="photos-until">to</label>
            <input
              id="photos-until"
              type="date"
              value={until}
              min={since || undefined}
              onChange={(e) => setUntil(e.target.value)}
              className="h-8 rounded-full border border-input bg-surface px-3 text-[12.5px] text-foreground"
            />
            {dated && (
              <button
                onClick={() => {
                  setSince("")
                  setUntil("")
                }}
                className="rounded p-1 text-muted-foreground hover:text-foreground"
                aria-label="Clear the dates"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
        </div>

        <div ref={grid} className="min-h-0 flex-1 overflow-y-auto p-4">
          {items.isLoading ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-2">
              {Array.from({ length: 24 }).map((_, i) => (
                <Skeleton key={i} className="aspect-square rounded-lg" />
              ))}
            </div>
          ) : items.error ? (
            <div className="grid h-full place-items-center text-[13px] text-muted-foreground">{(items.error as Error).message}</div>
          ) : !list.length ? (
            <div className="grid h-full place-items-center text-center text-[13px] text-muted-foreground">
              <div>
                <Images className="mx-auto mb-2 size-5 text-subtle" />
                Nothing here{dated ? " between those dates" : ""}.
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-2">
                {list.map((it, i) => (
                  <Tile key={it.id} item={it} selected={picked.has(it.id) ? order.indexOf(it.id) + 1 : 0} onClick={(e) => pick(it, i, e)} />
                ))}
              </div>
              <div ref={more} className="py-4 text-center text-[12px] text-subtle">
                {items.isFetchingNextPage ? <Loader2 className="mx-auto size-4 animate-spin" /> : items.hasNextPage ? "" : `${pluralize(total, "item")}`}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}

/** "Import from Photos": albums, recents, multi-select, a date filter, then an import job with progress. */
export function PhotosPicker({ pid, open, onOpenChange }: { pid: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const status = usePhotosStatus(open)
  const refresh = useRefreshPhotos()
  const start = useImportPhotos(pid)
  const [picked, setPicked] = useState<Map<string, PhotoItem>>(new Map())
  const [liveVideo, setLiveVideo] = useState(false)
  const [jobId, setJobId] = useState<string>()
  const { job } = useJobStream(jobId)
  const st = status.data
  const live = [...picked.values()].filter((p) => p.live).length
  const running = !!jobId && (!job || job.id !== jobId || job.status === "queued" || job.status === "running")

  const toggle = (it: PhotoItem) =>
    setPicked((m) => {
      const next = new Map(m)
      if (next.has(it.id)) next.delete(it.id)
      else next.set(it.id, it)
      return next
    })

  // the import finished: say what came in (and what didn't), refresh the edit order, close
  useEffect(() => {
    if (!job || job.id !== jobId) return
    if (job.status === "done") {
      const res = job.result as { added?: ProjectFile[]; skipped?: { name: string; reason: string }[] } | null
      const added = res?.added?.length ?? 0
      const skipped = res?.skipped ?? []
      toast.success(`Imported ${pluralize(added, "item")} from Photos`, {
        description: skipped.length ? `Skipped ${skipped.map((s) => `${s.name} (${s.reason})`).join("; ")}` : undefined,
      })
      qc.invalidateQueries({ queryKey: keys.project(pid) })
      qc.invalidateQueries({ queryKey: keys.projects })
      setJobId(undefined)
      setPicked(new Map())
      onOpenChange(false)
    } else if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      const err = job.error as { message?: string; hint?: string } | null
      toast.error(err?.message ?? "The import didn't work", { description: err?.hint ?? undefined })
      setJobId(undefined)
    }
  }, [job, jobId, pid, qc, onOpenChange])

  const doImport = () =>
    start.mutate(
      { ids: [...picked.keys()], live_video: liveVideo },
      { onSuccess: (j) => setJobId(j.id), onError: (e) => toast.error((e as Error).message) },
    )

  const ready = st?.state === "ready"
  return (
    <Dialog open={open} onOpenChange={(o) => !running && onOpenChange(o)}>
      <DialogContent
        className="flex h-[min(780px,90vh)] max-w-[min(1180px,94vw)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[min(1180px,94vw)]"
        showCloseButton={!running}
      >
        <div className="flex items-center gap-3 border-b border-border px-5 py-3.5">
          <Images className="size-4" />
          <DialogTitle className="text-[15px]">Import from Photos</DialogTitle>
          <DialogDescription className="sr-only">Pick photos and videos from your Mac's Photos library</DialogDescription>
        </div>

        {!st || st.state === "loading" || st.state === "idle" ? (
          <div className="grid flex-1 place-items-center text-center" data-testid="photos-loading">
            <div>
              <Loader2 className="mx-auto mb-3 size-5 animate-spin" />
              <div className="text-[14px] font-medium">Reading your Photos library…</div>
              <div className="mt-1 text-[12.5px] text-muted-foreground">The first time takes a little while on a big library.</div>
            </div>
          </div>
        ) : !ready ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-6">
            <AccessHelp st={st} onCheck={() => refresh.mutate()} checking={refresh.isPending} />
          </div>
        ) : (
          <Browser picked={picked} onPicked={setPicked} toggle={toggle} />
        )}

        {ready && (
          <div className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-3">
            <div className="text-[13px]" data-testid="photos-selected">
              <span className="font-semibold">{picked.size}</span> <span className="text-muted-foreground">selected</span>
            </div>
            {picked.size > 0 && !running && (
              <button onClick={() => setPicked(new Map())} className="text-[12.5px] text-muted-foreground hover:text-foreground">
                Clear
              </button>
            )}
            {live > 0 && !running && (
              <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                <span>{pluralize(live, "Live Photo")}:</span>
                <div className="flex rounded-full bg-surface-2 p-0.5">
                  {[
                    [false, "Still"],
                    [true, "Video"],
                  ].map(([v, label]) => (
                    <button
                      key={String(label)}
                      onClick={() => setLiveVideo(v as boolean)}
                      className={cn(
                        "h-6 rounded-full px-2.5 text-[12px] font-medium transition",
                        liveVideo === v ? "bg-accent text-accent-ink" : "text-ink-soft hover:text-foreground",
                      )}
                    >
                      {label as string}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {running && job && (
              <div className="flex min-w-[240px] flex-1 items-center gap-3" data-testid="photos-progress">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink/10">
                  <div className="h-full rounded-full bg-ink transition-all" style={{ width: `${Math.max(4, job.progress)}%` }} />
                </div>
                <span className="max-w-[260px] truncate text-[12px] text-muted-foreground">{job.step ?? "Starting…"}</span>
              </div>
            )}
            <div className="ml-auto flex items-center gap-2">
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={running}>
                Cancel
              </Button>
              <Button onClick={doImport} disabled={!picked.size || running || start.isPending}>
                {running || start.isPending ? <Loader2 className="animate-spin" /> : <Check />}
                {running ? "Importing…" : `Import ${picked.size || ""}`.trim()}
              </Button>
            </div>
          </div>
        )}
        {!ready && st && st.state !== "loading" && (
          <div className="flex items-center gap-2 border-t border-border px-5 py-3 text-[12px] text-subtle">
            <Settings2 className="size-3.5" /> Nothing in your Photos library is ever changed: Cutroom copies the originals into this project.
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
