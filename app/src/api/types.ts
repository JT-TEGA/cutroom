import type { components } from "./schema"

type S = components["schemas"]

export type Project = S["Project"]
export type ProjectSummary = S["ProjectSummary"]
export type ProjectFile = S["ProjectFile"]
export type Brief = S["BriefData"]
export type Question = S["Question"]
export type Job = S["Job"]
export type Timeline = S["Timeline"]
export type TimelineView = S["TimelineView"]
export type Segment = S["Segment"]
export type Shot = S["Shot"]
export type TextOverlay = S["TextOverlay"]
export type ResolvedShot = S["ResolvedShot"]
export type ResolvedOverlay = S["ResolvedOverlay"]
export type OutputVersion = S["OutputVersion"]
export type Preset = S["Preset"]
export type Settings = S["Settings"]
export type BrandSettings = S["BrandSettings"]
export type AppSettings = S["AppSettings"]
export type SystemStatus = S["SystemStatus"]
export type VoiceoverInfo = S["VoiceoverInfo"]
/** A voiceover recorded in the app, kept until one is used. */
export type Take = S["Take"]
export type MusicInfo = S["MusicInfo"]
export type InAppSound = S["InAppSound"]
export type PhotosStatus = S["PhotosStatus"]
export type PhotoItem = S["PhotoItem"]
export type PhotoAlbum = S["PhotoAlbum"]
export type PhotoPage = S["ItemPage"]

export type ProjectStatus = Project["status"]
export type JobKind = "analyse" | "plan" | "render" | "revise" | "reference" | "photos-import"

/** A job event from WS /ws/jobs/{id}. */
export type JobEvent =
  | { type: "snapshot" | "result"; job: Job }
  | { type: "status"; status: Job["status"]; progress: number; step: string | null; error?: Job["error"] }
  | { type: "step"; status: Job["status"]; progress: number; step: string }
  | { type: "log"; status: Job["status"]; progress: number; step: string | null; line: string }
  | { type: "error"; error: { code: string; message: string; hint?: string | null } }
