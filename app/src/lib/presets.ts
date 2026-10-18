import {
  Apple,
  CalendarClock,
  Camera,
  Clapperboard,
  Dumbbell,
  Flame,
  GalleryHorizontalEnd,
  Images,
  type LucideIcon,
  MapPin,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react"
import type { Preset } from "@/api/types"

export type Group = { id: string; label: string; blurb: string; presets: string[] }

export const GROUPS: Group[] = [
  { id: "lifestyle", label: "Lifestyle", blurb: "Days out, dumps and hangouts", presets: ["lifestyle-outing", "photo-dump"] },
  {
    id: "fashion",
    label: "Fashion & modelling",
    blurb: "Shoots, behind the scenes, a model's day",
    presets: ["model-ditl", "fashion-bts", "shoot-slideshow", "shoot-mashup"],
  },
  {
    id: "gym",
    label: "Gym & fitness",
    blurb: "Training, progress and food",
    presets: ["gym-vlog", "workout-routine", "transformation", "nutrition-education"],
  },
]

export const PRESET_META: Record<string, { title: string; icon: LucideIcon }> = {
  "lifestyle-outing": { title: "Outing vlog", icon: MapPin },
  "photo-dump": { title: "Photo dump", icon: Images },
  "model-ditl": { title: "Model day in the life", icon: CalendarClock },
  "fashion-bts": { title: "Shoot BTS", icon: Clapperboard },
  "shoot-slideshow": { title: "Shoot slideshow", icon: GalleryHorizontalEnd },
  "shoot-mashup": { title: "Shoot mashup", icon: Zap },
  "gym-vlog": { title: "Gym vlog", icon: Flame },
  "workout-routine": { title: "Workout routine", icon: Dumbbell },
  transformation: { title: "Transformation", icon: TrendingUp },
  "nutrition-education": { title: "Nutrition explainer", icon: Apple },
}

export function presetMeta(name: string | null | undefined): { title: string; icon: LucideIcon } {
  if (!name) return { title: "No type yet", icon: Sparkles }
  return PRESET_META[name] ?? { title: name.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase()), icon: Camera }
}

export function groupOf(name: string | null | undefined): Group | undefined {
  return GROUPS.find((g) => name && g.presets.includes(name))
}

/** The "- **Key:** value" lines of a preset's notes, keyed by lower-case key. */
export function noteFields(notes: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of notes.matchAll(/^-\s+\*\*([^*:]+):?\*\*:?\s*(.+)$/gm)) out[m[1].trim().toLowerCase()] = m[2].trim()
  return out
}

/** Preset defaults written the way a brief field would say them (placeholders in the brief form). */
export function presetDefaults(p: Preset | undefined): Record<string, string> {
  if (!p) return {}
  const s = p.settings as Record<string, unknown>
  const n = noteFields(p.notes ?? "")
  const every = Number(s.beat_every ?? 0)
  const out: Record<string, string> = {}
  if (n["typical length"]) out.target_length = n["typical length"]
  else if (s.target_length) out.target_length = `${s.target_length}s`
  if (s.talk_default) out.talking = String(s.talk_default)
  if (s.grade) out.colour_grade = String(s.grade)
  if (every) out.beat_sync = every === 1 ? "every beat" : `every ${every} beats`
  if (s.captions != null) out.captions = s.captions === "talking" ? "on when talking" : String(s.captions)
  if (s.end_card != null) out.end_card = s.end_card === true || s.end_card === "true" ? "on" : "off"
  if (n.pacing) out.pacing = n.pacing
  if (n["text overlays"]) out.labels = n["text overlays"]
  if (n.music) out.music_vibe = n.music
  if (n.transitions) out.transitions = n.transitions
  return out
}
