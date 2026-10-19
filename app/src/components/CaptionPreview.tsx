import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useMemo, useState } from "react"
import { fontUrl } from "@/api/client"
import type { BrandSettings } from "@/api/types"
import { Thumb } from "@/components/Thumb"
import { cn } from "@/lib/utils"

const SAMPLE = "Discipline over *motivation* every single day, even at five thirty"

const loaded = new Set<string>()
/** Load a font from assets/fonts once, under its family name, so the preview uses the real caption font. */
function useFont(family: string | null | undefined, file: string | undefined) {
  const [, bump] = useState(0)
  useEffect(() => {
    if (!family || !file || loaded.has(family)) return
    const face = new FontFace(family, `url(${fontUrl(file)})`, { weight: "100 900" })
    face
      .load()
      .then((f) => {
        document.fonts.add(f)
        loaded.add(family)
        bump((n) => n + 1)
      })
      .catch(() => undefined)
  }, [family, file])
}

function applyCase(t: string, c: string | null | undefined) {
  if (c === "upper") return t.toUpperCase()
  if (c === "lower") return t.toLowerCase()
  if (c === "sentence") return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase()
  return t
}

/** A 9:16 frame showing captions the way the brand settings describe them, word by word. */
export function CaptionPreview({
  brand,
  fontFiles,
  backdrop,
  className,
}: {
  brand: BrandSettings
  fontFiles: Record<string, string>
  backdrop?: string | null
  className?: string
}) {
  const family = brand.caption_font ?? "Inter"
  useFont(family, fontFiles[family])
  const words = useMemo(() => SAMPLE.split(" "), [])
  const per = Math.max(1, brand.caption_max_words ?? 4)
  const [at, setAt] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setAt((a) => (a + 1) % words.length), 420)
    return () => clearInterval(t)
  }, [words.length])
  const page = Math.floor(at / per)
  const shown = words.slice(page * per, page * per + per)
  const anim = brand.caption_animation ?? "pop"
  const size = ((brand.caption_size ?? 64) / 1080) * 100 // cqw: px on a 1080-wide frame
  const pos = (brand.caption_position ?? 0.7) * 100
  const inactive = brand.caption_inactive_opacity ?? 0.6

  return (
    <div className={cn("relative overflow-hidden rounded-card bg-control shadow-lift", className)} style={{ aspectRatio: "9 / 16", containerType: "size" }}>
      {backdrop ? (
        <Thumb path={backdrop} w={540} className="absolute inset-0" imgClassName="brightness-[0.55] saturate-[0.9]" />
      ) : (
        <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_30%_20%,var(--ink-soft)_0%,var(--ink)_60%)]" />
      )}
      <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-transparent to-black/40" />
      <div className="absolute inset-x-[7%] text-center" style={{ top: `${pos}%`, transform: "translateY(-50%)" }}>
        <AnimatePresence mode="wait">
          <motion.div
            key={page}
            initial={anim === "none" ? false : { opacity: 0, y: anim === "pop" ? 6 : 0 }}
            animate={{ opacity: 1, y: 0 }}
            exit={anim === "none" ? undefined : { opacity: 0 }}
            transition={{ duration: 0.15 }}
            style={{
              fontFamily: `"${family}", Inter, sans-serif`,
              fontWeight: brand.caption_weight ?? 700,
              fontSize: `${size}cqw`,
              lineHeight: 1.15,
              textShadow: "0 0.08em 0.4em rgb(0 0 0 / 0.55)",
            }}
          >
            {shown.map((w, i) => {
              const idx = page * per + i
              const emph = w.startsWith("*")
              const text = applyCase(w.replace(/\*/g, ""), brand.caption_case)
              const active = idx === at
              return (
                <motion.span
                  key={idx}
                  className="mx-[0.16em] inline-block origin-bottom"
                  animate={{
                    opacity: idx <= at || inactive >= 1 ? 1 : inactive,
                    scale: active && anim === "pop" ? 1.08 : 1,
                  }}
                  transition={{ duration: 0.12 }}
                  style={{ color: emph ? (brand.emphasis_color ?? "#FFD54A") : active ? (brand.caption_highlight_color ?? "#FFFFFF") : (brand.caption_color ?? "#FFFFFF") }}
                >
                  {text}
                </motion.span>
              )
            })}
          </motion.div>
        </AnimatePresence>
      </div>
      <div className="absolute top-[8%] left-[7%] rounded-[0.35em] px-[0.55em] py-[0.22em] text-[3.4cqw] font-semibold" style={{ background: brand.accent_color ?? "#FFFFFF", color: brand.accent_text_color ?? "#111111" }}>
        Lekki, 7PM
      </div>
      <div className="absolute right-[4%] bottom-[18%] flex flex-col items-center gap-[2.4cqh] opacity-50">
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className="size-[7cqw] rounded-full bg-control-ink/30" />
        ))}
      </div>
    </div>
  )
}

/** The end card: the handle over a blurred last frame. */
export function EndCardPreview({ handle, backdrop, on }: { handle: string; backdrop?: string | null; on: boolean }) {
  return (
    <div className={cn("relative overflow-hidden rounded-2xl shadow-soft transition", !on && "opacity-40 grayscale")} style={{ aspectRatio: "9 / 16", containerType: "size" }}>
      {backdrop ? <Thumb path={backdrop} w={240} className="absolute inset-0" imgClassName="scale-110 blur-md brightness-50" /> : <div className="absolute inset-0 bg-control" />}
      <div className="absolute inset-0 grid place-items-center">
        <span className="text-[11cqw] font-bold text-white">{handle || "@handle"}</span>
      </div>
    </div>
  )
}
