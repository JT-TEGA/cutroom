import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core"
import { arrayMove, rectSortingStrategy, SortableContext, sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { useQueryClient } from "@tanstack/react-query"
import { AnimatePresence, motion } from "framer-motion"
import { Clapperboard, GripVertical, ImageIcon, Images, Mic, Music2, Pause, Play, Upload, X } from "lucide-react"
import { type ReactNode, useRef, useState } from "react"
import { toast } from "sonner"
import { fileContentUrl } from "@/api/client"
import { keys, useDeleteFile, usePatchFile, useReorderFiles, useUpload } from "@/api/queries"
import type { Project, ProjectFile } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { clock, pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { MusicPanel } from "./MusicPanel"
import { PhotosPicker } from "./PhotosPicker"

type Kind = "clip" | "voiceover" | "music"

/** Extensions for files that arrive without one (drags from some apps, e.g. Photos, can name a file "IMG_0042"). */
const EXT_FOR_TYPE: Record<string, string> = {
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/heic": ".heic",
  "image/heif": ".heif",
  "image/webp": ".webp",
  "image/tiff": ".tiff",
  "video/quicktime": ".mov",
  "video/mp4": ".mp4",
  "video/x-m4v": ".m4v",
  "audio/mpeg": ".mp3",
  "audio/mp4": ".m4a",
  "audio/x-m4a": ".m4a",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/aac": ".aac",
}

function withExtension(f: File): File {
  if (/\.[a-z0-9]{2,5}$/i.test(f.name)) return f
  const ext = EXT_FOR_TYPE[f.type]
  return ext ? new File([f], `${f.name || "item"}${ext}`, { type: f.type, lastModified: f.lastModified }) : f
}

/** The files in a drop: dataTransfer.files, or the file items when an app only fills those in. */
export function droppedFiles(dt: DataTransfer | null): File[] {
  if (!dt) return []
  let files = Array.from(dt.files ?? [])
  if (!files.length)
    files = Array.from(dt.items ?? [])
      .filter((i) => i.kind === "file")
      .map((i) => i.getAsFile())
      .filter((f): f is File => !!f)
  return files.map(withExtension)
}

const ZONES: Record<Kind, { title: string; sub: string; accept: string; icon: typeof Upload }> = {
  clip: {
    title: "Clips & photos",
    sub: "MP4, MOV, JPG, PNG, HEIC: drop a whole shoot",
    accept: "video/*,image/*,.heic,.heif,.mov,.mp4,.m4v",
    icon: Clapperboard,
  },
  voiceover: { title: "Voiceover", sub: "A voice memo: M4A, WAV, MP3", accept: "audio/*,.m4a,.wav,.mp3,.aac,.caf", icon: Mic },
  music: { title: "Music", sub: "The track to cut to", accept: "audio/*,.m4a,.wav,.mp3,.aac,.flac", icon: Music2 },
}

function DropZone({
  kind,
  onFiles,
  progress,
  big,
  action,
  children,
}: {
  kind: Kind
  onFiles: (files: File[]) => void
  progress: number | null
  big?: boolean
  action?: ReactNode
  children?: ReactNode
}) {
  const z = ZONES[kind]
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const depth = useRef(0)
  return (
    <div
      data-testid={`drop-${kind}`}
      onDragEnter={(e) => {
        e.preventDefault()
        depth.current += 1
        setOver(true)
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => {
        depth.current -= 1
        if (depth.current <= 0) setOver(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        depth.current = 0
        setOver(false)
        const files = droppedFiles(e.dataTransfer)
        if (files.length) onFiles(files)
        else
          toast.error("Nothing came through from that drag", {
            description:
              kind === "clip"
                ? "Some apps don't hand their files to the browser. Use Import from Photos, or drag the items to your Desktop first and drop them from there."
                : "Drag the file from Finder, or click Browse.",
          })
      }}
      className={cn(
        "relative flex flex-col overflow-hidden rounded-2xl border border-dashed transition-all",
        over ? "border-primary bg-primary/[0.08] shadow-[0_0_0_4px_rgb(124_92_255/0.12)]" : "border-white/[0.1] bg-white/[0.015]",
      )}
    >
      <div className="flex items-center">
      <button
        type="button"
        onClick={() => input.current?.click()}
        className={cn("group flex min-w-0 flex-1 items-center gap-4 text-left", big ? "px-6 py-6" : "px-5 py-5")}
      >
        <span
          className={cn(
            "grid shrink-0 place-items-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-primary transition group-hover:scale-105 group-hover:border-primary/40",
            big ? "size-12" : "size-10",
          )}
        >
          <z.icon className={big ? "size-5" : "size-[18px]"} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold">{z.title}</span>
          <span className="block text-[12.5px] text-muted-foreground">{over ? "Drop to add" : z.sub}</span>
        </span>
        <span className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-[12.5px] font-medium text-zinc-300 transition group-hover:bg-white/[0.07]">
          <Upload className="size-3.5" /> Browse
        </span>
      </button>
      {action && <div className={cn("shrink-0", big ? "pr-6" : "pr-5")}>{action}</div>}
      </div>
      <input
        ref={input}
        type="file"
        multiple={kind === "clip"}
        accept={z.accept}
        className="hidden"
        data-testid={`upload-${kind}`}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length) onFiles(files)
          e.target.value = ""
        }}
      />
      {children}
      <AnimatePresence>
        {progress != null && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-x-0 bottom-0 h-1 bg-white/5"
          >
            <motion.div className="h-full bg-primary" animate={{ width: `${Math.max(3, progress * 100)}%` }} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function NameEditor({ file, pid }: { file: ProjectFile; pid: string }) {
  const patch = usePatchFile(pid)
  const dot = file.name.lastIndexOf(".")
  const stem = dot > 0 ? file.name.slice(0, dot) : file.name
  const ext = dot > 0 ? file.name.slice(dot) : ""
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(stem)
  const save = () => {
    setEditing(false)
    const v = value.trim()
    if (v && v !== stem) patch.mutate({ fileId: file.id, name: v + ext })
    else setValue(stem)
  }
  if (editing)
    return (
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation()
          if (e.key === "Enter") save()
          if (e.key === "Escape") {
            setValue(stem)
            setEditing(false)
          }
        }}
        className="h-6 w-full rounded border border-primary/60 bg-black/40 px-1.5 text-[12px] outline-none"
      />
    )
  return (
    <button
      onPointerDown={(e) => e.stopPropagation()}
      onClick={() => {
        setValue(stem)
        setEditing(true)
      }}
      title="Rename: a descriptive name helps Claude match the clip to what you say"
      className="block h-6 w-full truncate rounded px-1.5 text-left text-[12px] text-zinc-300 transition hover:bg-white/[0.06]"
    >
      {stem}
      <span className="text-subtle">{ext}</span>
    </button>
  )
}

function Tile({ file, index, pid, onDelete, overlay }: { file: ProjectFile; index: number; pid: string; onDelete?: () => void; overlay?: boolean }) {
  const s = useSortable({ id: file.id, disabled: overlay })
  const style = overlay ? undefined : { transform: CSS.Transform.toString(s.transform), transition: s.transition }
  const voice = file.kind === "voiceover"
  return (
    <div
      ref={overlay ? undefined : s.setNodeRef}
      style={style}
      className={cn("group w-[116px]", s.isDragging && !overlay && "opacity-30", overlay && "rotate-2 cursor-grabbing")}
    >
      <div
        {...(overlay ? {} : s.attributes)}
        {...(overlay ? {} : s.listeners)}
        className={cn(
          "relative aspect-[9/16] cursor-grab overflow-hidden rounded-xl border border-white/[0.08] bg-card shadow-[0_8px_24px_-12px_rgb(0_0_0/0.8)] transition group-hover:border-white/20 active:cursor-grabbing",
          overlay && "border-primary/60 shadow-[0_20px_40px_-12px_rgb(0_0_0/0.9)]",
        )}
      >
        {voice ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-gradient-to-b from-[#2a1f5c] via-[#1a1538] to-[#121018]">
            <Mic className="size-5 text-violet-200" />
            <div className="flex h-8 items-center gap-[3px]">
              {Array.from({ length: 13 }).map((_, i) => (
                <span key={i} className="w-[3px] rounded-full bg-violet-300/70" style={{ height: `${20 + 70 * Math.abs(Math.sin(i * 1.7 + file.size))}%` }} />
              ))}
            </div>
            <span className="text-[11px] font-medium text-violet-100/80">Voiceover</span>
          </div>
        ) : (
          <Thumb path={`${pid}/${file.path}`} w={240} className="absolute inset-0" />
        )}
        <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-transparent to-black/50" />
        <span className="absolute top-1.5 left-1.5 grid h-5 min-w-5 place-items-center rounded-md bg-black/60 px-1 font-mono text-[10.5px] text-zinc-200 backdrop-blur">
          {index + 1}
        </span>
        <span className="absolute right-1.5 bottom-1.5 inline-flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 font-mono text-[10.5px] text-zinc-200 backdrop-blur">
          {file.kind === "photo" ? <ImageIcon className="size-3" /> : clock(file.duration)}
        </span>
        <GripVertical className="absolute top-1.5 right-1 size-4 text-white/0 transition group-hover:text-white/60" />
        {onDelete && (
          <button
            aria-label={`Remove ${file.name}`}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={onDelete}
            className="absolute right-1.5 bottom-7 grid size-6 place-items-center rounded-md bg-black/70 text-zinc-300 opacity-0 backdrop-blur transition group-hover:opacity-100 hover:bg-destructive hover:text-white"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>
      <div className="mt-1.5">{overlay ? <div className="truncate px-1.5 text-[12px]">{file.name}</div> : <NameEditor file={file} pid={pid} />}</div>
    </div>
  )
}

function MusicRow({ file, pid, onDelete }: { file: ProjectFile; pid: string; onDelete: () => void }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  return (
    <div className="flex items-center gap-3 border-t border-white/[0.05] px-5 py-3 first:border-t-0">
      <button
        onClick={() => {
          const a = audio.current
          if (!a) return
          if (a.paused) a.play()
          else a.pause()
        }}
        className="grid size-8 place-items-center rounded-full bg-primary/15 text-primary transition hover:bg-primary/25"
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5 translate-x-px" />}
      </button>
      <audio ref={audio} src={fileContentUrl(pid, file.id)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} preload="none" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium">{file.name}</div>
        <div className="text-[11.5px] text-muted-foreground">{clock(file.duration)}</div>
      </div>
      <button onClick={onDelete} className="rounded p-1.5 text-muted-foreground transition hover:bg-white/5 hover:text-foreground" aria-label="Remove">
        <X className="size-3.5" />
      </button>
    </div>
  )
}

export function StepMedia({ project }: { project: Project }) {
  const pid = project.id
  const qc = useQueryClient()
  const upload = useUpload(pid)
  const reorder = useReorderFiles(pid)
  const del = useDeleteFile(pid)
  const [progress, setProgress] = useState<Record<Kind, number | null>>({ clip: null, voiceover: null, music: null })
  const [dragging, setDragging] = useState<string | null>(null)
  const [photos, setPhotos] = useState(false)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const files = project.files ?? []
  const ordered = files.filter((f) => f.kind !== "music")
  const music = files.filter((f) => f.kind === "music")
  const named = (project.brief?.track ?? "").trim().toLowerCase()
  const song = music.find((f) => named && f.name.toLowerCase() === named) ?? music[music.length - 1]
  const visual = ordered.filter((f) => f.kind !== "voiceover")
  const mixed = (project.brief?.talking ?? "").startsWith("mixed")

  const send = async (kind: Kind, list: File[]) => {
    setProgress((p) => ({ ...p, [kind]: 0 }))
    try {
      const added = await upload.mutateAsync({
        files: list,
        kind: kind === "clip" ? undefined : kind,
        onProgress: (f) => setProgress((p) => ({ ...p, [kind]: f })),
      })
      toast.success(`Added ${pluralize(added.length, "file")}`)
      if (kind === "voiceover" && !mixed) {
        // a voiceover goes first in the edit order: every clip after it plays under it
        const now = qc.getQueryData<Project>(keys.project(pid))?.files ?? []
        const vo = now.filter((f) => added.some((a) => a.id === f.id))
        reorder.mutate([...vo, ...now.filter((f) => !vo.includes(f))].map((f) => f.id))
      }
    } catch {
      /* the toast comes from the mutation */
    } finally {
      setProgress((p) => ({ ...p, [kind]: null }))
    }
  }

  const onDragStart = (e: DragStartEvent) => setDragging(String(e.active.id))
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null)
    if (!e.over || e.active.id === e.over.id) return
    const from = ordered.findIndex((f) => f.id === e.active.id)
    const to = ordered.findIndex((f) => f.id === e.over!.id)
    const next = arrayMove(ordered, from, to)
    reorder.mutate([...next, ...music].map((f) => f.id))
  }
  const active = dragging ? ordered.find((f) => f.id === dragging) : undefined

  return (
    <div className="grid grid-cols-[1fr_340px] gap-6 max-lg:grid-cols-1">
      <div className="flex min-w-0 flex-col gap-5">
        <DropZone
          kind="clip"
          big
          onFiles={(l) => send("clip", l)}
          progress={progress.clip}
          action={
            <button
              type="button"
              onClick={() => setPhotos(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 text-[12.5px] font-medium text-violet-100 transition hover:bg-primary/20"
            >
              <Images className="size-3.5" /> Import from Photos
            </button>
          }
        />
        <PhotosPicker pid={pid} open={photos} onOpenChange={setPhotos} />

        <div className="panel min-h-[300px] p-5">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <div className="text-[14px] font-semibold">Edit order</div>
              <div className="text-[12.5px] text-muted-foreground">
                Drag to reorder. Click a name to rename it: “incline-bench” beats “IMG_4821”.
              </div>
            </div>
            <div className="shrink-0 text-[12.5px] text-muted-foreground">
              {pluralize(visual.length, "shot")}
              {ordered.length > visual.length && ` · ${pluralize(ordered.length - visual.length, "voiceover")}`}
            </div>
          </div>
          {ordered.length === 0 ? (
            <div className="grid h-[220px] place-items-center rounded-xl border border-dashed border-white/[0.07] text-center text-[13px] text-muted-foreground">
              <div>
                <Clapperboard className="mx-auto mb-2 size-5 text-subtle" />
                Your clips appear here, in the order they'll be used.
              </div>
            </div>
          ) : (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
              <SortableContext items={ordered.map((f) => f.id)} strategy={rectSortingStrategy}>
                <div className="flex flex-wrap gap-4">
                  {ordered.map((f, i) => (
                    <Tile key={f.id} file={f} index={i} pid={pid} onDelete={() => del.mutate(f.id)} />
                  ))}
                </div>
              </SortableContext>
              <DragOverlay>{active ? <Tile file={active} index={ordered.indexOf(active)} pid={pid} overlay /> : null}</DragOverlay>
            </DndContext>
          )}
        </div>
        {song && <MusicPanel key={song.id} project={project} file={song} />}
      </div>

      <div className="flex flex-col gap-5">
        <DropZone kind="voiceover" onFiles={(l) => send("voiceover", l)} progress={progress.voiceover}>
          {ordered.some((f) => f.kind === "voiceover") && (
            <div className="border-t border-white/[0.05] px-5 py-3 text-[12.5px] text-muted-foreground">
              <span className="text-foreground">{ordered.filter((f) => f.kind === "voiceover").map((f) => f.name).join(", ")}</span>
              <div className="mt-0.5">
                {mixed ? "Mixed edit: it takes the clips after it in the order." : "It plays over the clips; B-roll follows what you say."}
              </div>
            </div>
          )}
        </DropZone>
        <DropZone kind="music" onFiles={(l) => send("music", l)} progress={progress.music}>
          {music.map((f) => (
            <MusicRow key={f.id} file={f} pid={pid} onDelete={() => del.mutate(f.id)} />
          ))}
          {!music.length && (
            <div className="border-t border-white/[0.05] px-5 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
              Adding the song in Instagram or TikTok when you post? Upload the same song here anyway: it sets the beat and
              the preview, and you'll get a copy without it.
            </div>
          )}
        </DropZone>
        <div className="rounded-2xl border border-white/[0.05] bg-white/[0.015] p-5 text-[12.5px] leading-relaxed text-muted-foreground">
          <div className="mb-1.5 font-medium text-zinc-300">Good to know</div>
          <ul className="list-disc space-y-1 pl-4">
            <li>Phone footage is fine: it's framed to 9:16 around faces automatically.</li>
            <li>Slow-mo and speed ramps look smooth only on 60 fps clips.</li>
            <li>No music? Beat-cut types will ask for a track before planning.</li>
            <li>You can drag photos and videos straight out of the Photos app, or use Import from Photos.</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
