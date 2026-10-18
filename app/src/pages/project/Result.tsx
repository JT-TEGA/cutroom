import { motion } from "framer-motion"
import { AlertTriangle, Download, FolderOpen, Grid3x3, Loader2, Music2, Pencil, Send, Smartphone, Sparkles, Volume1 } from "lucide-react"
import { useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router"
import { contactUrl, postVideoUrl, thumbUrl, videoUrl } from "@/api/client"
import { useOutputs, useReveal, useStartJob } from "@/api/queries"
import type { InAppSound } from "@/api/types"
import { Page } from "@/components/Page"
import { EmptyState, ErrorState } from "@/components/States"
import { VideoPlayer } from "@/components/VideoPlayer"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { bytes, clock, timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useProjectCtx } from "./ProjectLayout"

const IDEAS = ["Open on a stronger shot", "Make it faster", "Add a flash on the drop", "Put the end card on"]

/** Posting with the in-app sound: which song, the second to start it at, and the two files. */
function InAppCard({ card, pid, version }: { card: InAppSound; pid: string; version: number }) {
  return (
    <div className="panel relative overflow-hidden border-primary/35 p-5" data-testid="in-app-card">
      <div className="pointer-events-none absolute -top-20 -right-16 size-56 rounded-full bg-primary/20 blur-3xl" />
      <div className="relative flex flex-wrap items-start gap-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl border border-primary/30 bg-primary/15 text-primary">
          <Smartphone className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="eyebrow mb-1.5">Post with the in-app sound</div>
          <div className="text-[15px] leading-snug text-zinc-200">
            In Instagram/TikTok, pick <b className="text-white">{card.song.replace(/\.[^.]+$/, "")}</b> and start it at
          </div>
          <div className="mt-1 font-mono text-[44px] leading-none font-semibold tracking-tight text-white" data-testid="in-app-start">
            {card.start_label}
          </div>
          <p className="mt-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
            Post the file without music, add the song in the app and move its start to {card.start_label}: the cuts land on
            its beat from there. Use the same version of the song as the one you uploaded.
          </p>
          {card.voice && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-white/[0.07] bg-white/[0.03] px-3 py-2 text-[12.5px] text-zinc-300">
              <Volume1 className="mt-0.5 size-3.5 shrink-0 text-primary" />
              Your voice is in the file to post: turn the song down in the app (about 20%) and keep the original sound at 100%, so it
              sits under what you say.
            </div>
          )}
          {card.warning && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2 text-[12.5px] text-zinc-200">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" />
              {card.warning}
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button asChild>
              <a href={postVideoUrl(pid, version, true)} download>
                <Download /> Video to post (no music)
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href={videoUrl(pid, version, true)} download>
                <Music2 /> Preview with the music
              </a>
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function Result() {
  const { project } = useProjectCtx()
  const pid = project.id
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const outputs = useOutputs(pid)
  const reveal = useReveal(pid)
  const start = useStartJob(pid)
  const [notes, setNotes] = useState("")
  const [sheet, setSheet] = useState(false)
  const [asPosted, setAsPosted] = useState(false)

  if (outputs.isLoading)
    return (
      <Page wide>
        <div className="grid grid-cols-[auto_1fr] gap-10">
          <Skeleton className="aspect-[9/16] h-[640px] rounded-[22px] bg-white/[0.04]" />
          <Skeleton className="h-[640px] rounded-2xl bg-white/[0.04]" />
        </div>
      </Page>
    )
  if (outputs.error) return <Page><ErrorState error={outputs.error} onRetry={() => outputs.refetch()} className="mt-10" /></Page>
  const list = outputs.data ?? []
  if (!list.length)
    return (
      <Page>
        <EmptyState
          className="mt-12"
          icon={<Sparkles className="size-5" />}
          title="Nothing rendered yet"
          description="Approve the plan and the finished video shows up here."
          action={
            <Button asChild>
              <Link to={`/projects/${pid}/plan`}>Review the plan</Link>
            </Button>
          }
        />
      </Page>
    )

  const v = Number(search.get("v")) || list[0].version
  const out = list.find((o) => o.version === v) ?? list[0]
  const info = (project.renders ?? []).find((r) => r.version === out.version)
  const card = out.post_video_url ? (out.in_app ?? info?.in_app ?? null) : null
  const posted = !!card && asPosted
  const audio = (info?.audio ?? {}) as { voice_lufs?: number; ducked?: boolean; music_lufs?: number; sfx?: number; voiceover?: { cleaned?: boolean } }
  const revise = () =>
    notes.trim() &&
    start.mutate({ kind: "revise", notes: notes.trim(), render: true }, { onSuccess: (j) => navigate(`/projects/${pid}/jobs/${j.id}`) })

  return (
    <Page wide className="pt-7">
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-10 max-lg:grid-cols-1">
        <motion.div layout className="flex flex-col items-center">
          <VideoPlayer
            key={`${out.version}-${posted}`}
            src={posted ? postVideoUrl(pid, out.version) : videoUrl(pid, out.version)}
            poster={thumbUrl(`${pid}/${out.video}`, 720, 0.8)}
            className="h-[min(calc(100vh-150px),820px)] min-h-[520px]"
          />
          {card && (
            <div className="mt-3 flex rounded-lg border border-white/[0.07] p-0.5 text-[12.5px]">
              {[
                [false, "With the music"],
                [true, "As posted (no music)"],
              ].map(([v, label]) => (
                <button
                  key={String(v)}
                  onClick={() => setAsPosted(v as boolean)}
                  className={cn(
                    "h-7 rounded-md px-3 font-medium transition",
                    asPosted === v ? "bg-white/[0.09] text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label as string}
                </button>
              ))}
            </div>
          )}
        </motion.div>

        <div className="flex min-w-0 flex-col gap-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="eyebrow mb-2">Your video</div>
              <h1 className="text-[26px] font-semibold tracking-[-0.02em]">
                Version {out.version}
                {out.version === list[0].version && <span className="ml-2.5 align-middle rounded-md bg-ok/15 px-2 py-0.5 text-[12px] font-medium text-emerald-200">latest</span>}
              </h1>
              <div className="mt-1.5 text-[13px] text-muted-foreground">
                {clock(out.duration)} · 9:16 MP4 · {bytes(out.size_bytes)}
                {out.plan_version ? ` · plan v${out.plan_version}` : ""} · {timeAgo(out.created_at as string)}
                {out.draft && " · draft quality"}
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => reveal.mutate(out.version)} disabled={reveal.isPending}>
                <FolderOpen /> Open in Finder
              </Button>
              <Button asChild>
                <a href={videoUrl(pid, out.version, true)} download>
                  <Download /> Download
                </a>
              </Button>
            </div>
          </div>

          {card && <InAppCard card={card} pid={pid} version={out.version} />}

          {list.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {list.map((o) => (
                <button
                  key={o.version}
                  onClick={() => setSearch({ v: String(o.version) }, { replace: true })}
                  className={cn(
                    "flex items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition",
                    o.version === out.version ? "border-primary/60 bg-primary/10" : "border-white/[0.07] hover:border-white/15",
                  )}
                >
                  <span className={cn("font-mono text-[13px] font-semibold", o.version === out.version ? "text-white" : "text-zinc-300")}>v{o.version}</span>
                  <span className="text-[11.5px] leading-tight text-muted-foreground">
                    {clock(o.duration)}
                    <br />
                    {timeAgo(o.created_at as string)}
                  </span>
                </button>
              ))}
            </div>
          )}

          <div className="panel p-5">
            <div className="mb-1 flex items-center gap-2 text-[13.5px] font-semibold">
              <Pencil className="size-4 text-primary" /> Request changes
            </div>
            <p className="mb-3 text-[12.5px] text-muted-foreground">
              Say what to change in plain words. Claude updates the plan, then it renders as version {list[0].version + 1}; unchanged shots are reused.
            </p>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && revise()}
              rows={3}
              placeholder="Open on the bench set, make the sticker say “5AM” and use flash cuts on the training part"
              className="bg-white/[0.025] text-[13.5px] leading-relaxed"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {IDEAS.map((i) => (
                <button
                  key={i}
                  onClick={() => setNotes((n) => (n ? `${n.replace(/\s+$/, "")}, ${i.toLowerCase()}` : i))}
                  className="h-7 rounded-full border border-white/[0.07] px-2.5 text-[12px] text-muted-foreground transition hover:border-white/15 hover:text-foreground"
                >
                  {i}
                </button>
              ))}
              <Button className="ml-auto" disabled={!notes.trim() || start.isPending} onClick={revise}>
                {start.isPending ? <Loader2 className="animate-spin" /> : <Send />} Revise & render
              </Button>
            </div>
          </div>

          <div className="panel p-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                <Grid3x3 className="size-4 text-primary" /> Contact sheet
              </div>
              <span className="text-[12px] text-muted-foreground">six moments, to check at a glance</span>
            </div>
            {out.contact_sheet_url ? (
              <button onClick={() => setSheet(true)} className="block w-full overflow-hidden rounded-lg border border-white/[0.06] transition hover:border-white/20">
                <img src={contactUrl(pid, out.version)} alt={`Contact sheet for version ${out.version}`} className="w-full" />
              </button>
            ) : (
              <div className="text-[13px] text-muted-foreground">No contact sheet for this version.</div>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3 max-xl:grid-cols-1">
            {[
              ["Loudness", "−14 LUFS, ready for Reels / TikTok"],
              ["Voice", audio.voice_lufs ? `${audio.voice_lufs.toFixed(1)} LUFS${audio.voiceover?.cleaned ? ", cleaned" : ""}` : "no talking"],
              [
                "Music",
                card
                  ? "in the preview only: added in the app"
                  : audio.music_lufs != null
                    ? audio.ducked
                      ? "ducked under the voice"
                      : "leads the mix"
                    : "none",
              ],
            ].map(([k, val]) => (
              <div key={k} className="rounded-xl border border-white/[0.05] bg-white/[0.015] px-4 py-3">
                <div className="text-[11.5px] text-muted-foreground">{k}</div>
                <div className="mt-0.5 text-[13px] text-zinc-200">{val}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <Dialog open={sheet} onOpenChange={setSheet}>
        <DialogContent className="max-w-[min(1200px,92vw)] border-white/10 bg-[#0d0d10] p-3 sm:max-w-[min(1200px,92vw)]">
          <DialogTitle className="sr-only">Contact sheet</DialogTitle>
          <img src={contactUrl(pid, out.version)} alt="" className="w-full rounded-lg" />
        </DialogContent>
      </Dialog>
    </Page>
  )
}
