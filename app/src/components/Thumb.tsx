import { ImageOff } from "lucide-react"
import { useState } from "react"
import { thumbUrl } from "@/api/client"
import { cn } from "@/lib/utils"

/** A clip / photo thumbnail from the API with a shimmer while it loads. path: <project id>/<file path>. */
export function Thumb({
  path,
  w = 320,
  t,
  className,
  imgClassName,
  alt = "",
}: {
  path: string | null | undefined
  w?: number
  t?: number | null
  className?: string
  imgClassName?: string
  alt?: string
}) {
  const [state, setState] = useState<"loading" | "ok" | "error">("loading")
  return (
    <div className={cn("relative overflow-hidden bg-surface-2", className)}>
      {path && state !== "error" && (
        <img
          src={thumbUrl(path, w, t)}
          alt={alt}
          draggable={false}
          loading="lazy"
          onLoad={() => setState("ok")}
          onError={() => setState("error")}
          className={cn(
            "size-full object-cover transition-opacity duration-500",
            state === "ok" ? "opacity-100" : "opacity-0",
            imgClassName,
          )}
        />
      )}
      {state === "loading" && path && (
        <div className="absolute inset-0 animate-pulse bg-gradient-to-br from-ink/[0.05] to-transparent" />
      )}
      {(!path || state === "error") && (
        <div className="absolute inset-0 grid place-items-center text-subtle">
          <ImageOff className="size-5" />
        </div>
      )}
    </div>
  )
}
