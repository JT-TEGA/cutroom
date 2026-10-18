import { useDraggable } from "@dnd-kit/core"
import { AudioLines, Pause, Play } from "lucide-react"
import { useRef, useState } from "react"
import { mediaUrl } from "@/api/client"
import { useVoiceover } from "@/api/queries"
import type { ProjectFile } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { clock } from "@/lib/format"
import { cn } from "@/lib/utils"

export function BinTile({ file, pid, used, overlay }: { file: ProjectFile; pid: string; used?: boolean; overlay?: boolean }) {
  const d = useDraggable({ id: `bin-${file.id}`, data: { type: "bin", fileId: file.id }, disabled: overlay })
  return (
    <div
      ref={overlay ? undefined : d.setNodeRef}
      {...(overlay ? {} : d.listeners)}
      {...(overlay ? {} : d.attributes)}
      className={cn("group cursor-grab active:cursor-grabbing", d.isDragging && !overlay && "opacity-40", overlay && "w-[72px] rotate-3")}
      title={`${file.name}: drag onto a shot to swap it in`}
    >
      <div className={cn("relative aspect-[9/16] overflow-hidden rounded-lg border border-white/[0.08] transition group-hover:border-white/25", overlay && "border-info shadow-2xl")}>
        <Thumb path={`${pid}/${file.path}`} w={160} className="absolute inset-0" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent" />
        {file.kind === "clip" && <span className="absolute right-1 bottom-1 font-mono text-[9.5px] text-white/80">{clock(file.duration)}</span>}
        {used && <span className="absolute top-1 left-1 size-1.5 rounded-full bg-ok shadow-[0_0_6px_var(--ok)]" title="in the plan" />}
      </div>
      {!overlay && <div className="mt-1 truncate text-[10.5px] text-muted-foreground">{file.name.replace(/\.[^.]+$/, "")}</div>}
    </div>
  )
}

function VoicePlayer({ path, name, stats }: { path: string; name: string; stats?: Record<string, unknown> | null }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(0)
  const num = (k: string) => (typeof stats?.[k] === "number" ? (stats[k] as number) : null)
  const before = num("lufs_before")
  const after = num("lufs_after")
  const snrA = num("snr_before")
  const snrB = num("snr_after")
  return (
    <div className="rounded-xl border border-primary/20 bg-gradient-to-b from-primary/[0.08] to-transparent p-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-[11.5px] font-medium text-violet-100">
        <AudioLines className="size-3.5" /> Voiceover, cleaned + cut
      </div>
      <div className="flex items-center gap-2.5">
        <button
          onClick={() => (audio.current?.paused ? audio.current.play() : audio.current?.pause())}
          className="grid size-8 shrink-0 place-items-center rounded-full bg-primary text-white shadow-[0_0_16px_-2px_rgb(124_92_255/0.8)] transition hover:scale-105"
          aria-label={playing ? "Pause voiceover" : "Play voiceover"}
        >
          {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5 translate-x-px" />}
        </button>
        <div className="min-w-0 flex-1">
          <div
            className="relative h-6 cursor-pointer rounded bg-[repeating-linear-gradient(90deg,rgb(167_139_250/0.35)_0_2px,transparent_2px_4px)]"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect()
              if (audio.current && dur) audio.current.currentTime = ((e.clientX - r.left) / r.width) * dur
            }}
          >
            <div className="absolute inset-y-0 left-0 rounded bg-[repeating-linear-gradient(90deg,rgb(196_181_253)_0_2px,transparent_2px_4px)]" style={{ width: dur ? `${(t / dur) * 100}%` : 0 }} />
          </div>
          <div className="mt-1 flex justify-between gap-2 font-mono text-[10.5px] text-muted-foreground">
            <span className="truncate" title={name}>
              {name}
            </span>
            <span className="shrink-0">
              {clock(t)}/{clock(dur)}
            </span>
          </div>
        </div>
      </div>
      <audio
        ref={audio}
        src={mediaUrl(path)}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
      />
      {before != null && after != null && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-[10.5px] text-zinc-300">
          <span className="rounded bg-white/[0.05] px-1.5 py-0.5">
            {before.toFixed(0)} → {after.toFixed(0)} LUFS
          </span>
          {snrA != null && snrB != null && snrB > snrA && (
            <span className="rounded bg-white/[0.05] px-1.5 py-0.5">
              noise {snrA.toFixed(0)} → {snrB.toFixed(0)} dB down
            </span>
          )}
          <span className="rounded bg-white/[0.05] px-1.5 py-0.5">de-essed</span>
        </div>
      )}
    </div>
  )
}

export function MediaBin({ files, pid, used }: { files: ProjectFile[]; pid: string; used: Set<string> }) {
  const vo = useVoiceover(pid, true)
  const visual = files.filter((f) => f.kind === "clip" || f.kind === "photo")
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="text-[13px] font-semibold">Media</div>
        <div className="text-[11.5px] text-muted-foreground">drag onto a shot to swap</div>
      </div>
      <div className="grid min-h-0 flex-1 auto-rows-min grid-cols-3 gap-2.5 overflow-y-auto pr-1">
        {visual.map((f) => (
          <BinTile key={f.id} file={f} pid={pid} used={used.has(f.path)} />
        ))}
      </div>
      {(vo.data ?? []).filter((v) => v.preview).length > 0 && (
        <div className="mt-3 grid gap-2">
          {vo.data!
            .filter((v) => v.preview)
            .map((v) => (
              <VoicePlayer key={v.file_id} path={v.preview!} name={v.name} stats={v.stats} />
            ))}
        </div>
      )}
    </div>
  )
}
