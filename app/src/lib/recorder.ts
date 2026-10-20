import { useCallback, useEffect, useRef, useState } from "react"

/** Recording a voiceover in the browser: the mic (getUserMedia), MediaRecorder, a level meter and a timer. Nothing
 * here throws: a mic that can't be opened becomes a `problem` the recorder explains. */

export type MicProblem = "denied" | "denied-system" | "no-mic" | "busy" | "unsupported" | "insecure" | "error"
export type RecorderStatus = "idle" | "asking" | "recording" | "paused" | "blocked"
export type LevelHint = "quiet" | "loud" | "ok" | null
export type Recording = { blob: Blob; ext: string; seconds: number }

// Chrome / Edge / Firefox record WebM Opus, Safari MP4 AAC; the server converts the take to .wav when it's used
const FORMATS = [
  { mime: "audio/webm;codecs=opus", ext: ".webm" },
  { mime: "audio/mp4", ext: ".mp4" },
  { mime: "audio/ogg;codecs=opus", ext: ".ogg" },
  { mime: "audio/webm", ext: ".webm" },
]

// the browser's call-style processing off: Cutroom's own clean-up (noise, de-ess, compression, -16 LUFS) does it
// better, and automatic gain would pump between words
const AUDIO: MediaTrackConstraints = { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 }

export function pickFormat(): { mime: string; ext: string } {
  const ok = (m: string) => {
    try {
      return MediaRecorder.isTypeSupported?.(m) ?? false
    } catch {
      return false
    }
  }
  return FORMATS.find((f) => ok(f.mime)) ?? { mime: "", ext: ".webm" }
}

export const extFor = (type: string) => (type.includes("mp4") ? ".mp4" : type.includes("ogg") ? ".ogg" : ".webm")

/** Why getUserMedia / MediaRecorder failed, in terms of what the creator can do about it. */
export function micProblem(e: unknown): MicProblem {
  const name = (e as { name?: string } | null)?.name ?? ""
  const message = String((e as { message?: string } | null)?.message ?? "")
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError")
    // Chrome says "Permission denied by system" when macOS hasn't given Chrome the microphone
    return /system/i.test(message) ? "denied-system" : "denied"
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") return "no-mic"
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "busy"
  if (name === "NotSupportedError" || name === "TypeError") return "unsupported"
  return "error"
}

/** RMS of a block -> 0..1 on a -60..0 dBFS scale (speech at ~20 cm sits around 0.5-0.7). */
export function levelOf(block: Float32Array): { level: number; peak: number } {
  let sum = 0
  let peak = 0
  for (const v of block) {
    sum += v * v
    peak = Math.max(peak, Math.abs(v))
  }
  const rms = Math.sqrt(sum / Math.max(1, block.length))
  const db = 20 * Math.log10(rms + 1e-9)
  return { level: Math.min(1, Math.max(0, (db + 60) / 60)), peak }
}

type Meter = { ctx: AudioContext; analyser: AnalyserNode; buf: Float32Array<ArrayBuffer> }

export function useRecorder(onRecording: (r: Recording) => void) {
  const [status, setStatus] = useState<RecorderStatus>("idle")
  const [problem, setProblem] = useState<{ kind: MicProblem; detail: string } | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0)
  const [hint, setHint] = useState<LevelHint>(null)

  const stream = useRef<MediaStream | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const meter = useRef<Meter | null>(null)
  const frame = useRef(0)
  const clock = useRef<{ since: number | null; before: number }>({ since: null, before: 0 }) // running since (ms), seconds banked before the last pause
  const recent = useRef<{ t: number; level: number; peak: number }[]>([])
  const alive = useRef(true)
  const done = useRef(onRecording)
  done.current = onRecording

  const seconds = () => clock.current.before + (clock.current.since != null ? (performance.now() - clock.current.since) / 1000 : 0)

  const release = useCallback(() => {
    cancelAnimationFrame(frame.current)
    frame.current = 0
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    meter.current?.ctx.close().catch(() => undefined)
    meter.current = null
    recent.current = []
  }, [])

  // one loop for the timer, the meter and the level hint (from the loudest moment of the last two seconds)
  const tick = useCallback(() => {
    const now = performance.now()
    setElapsed(Math.floor(seconds() * 10) / 10)
    const m = meter.current
    if (m) {
      m.analyser.getFloatTimeDomainData(m.buf)
      const { level: l, peak } = levelOf(m.buf)
      setLevel((prev) => Math.round(Math.max(l, prev * 0.88) * 100) / 100)
      if (clock.current.since != null) {
        recent.current = [...recent.current.filter((x) => now - x.t < 2000), { t: now, level: l, peak }]
        const loudest = Math.max(...recent.current.map((x) => x.level))
        const clipped = recent.current.some((x) => x.peak >= 0.99)
        if (seconds() >= 1.5) setHint(clipped ? "loud" : loudest < 0.35 ? "quiet" : "ok")
      }
    }
    frame.current = requestAnimationFrame(tick)
  }, [])

  const start = useCallback(async () => {
    setProblem(null)
    if (typeof window !== "undefined" && window.isSecureContext === false) {
      setProblem({ kind: "insecure", detail: "" })
      return setStatus("blocked")
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setProblem({ kind: "unsupported", detail: "" })
      return setStatus("blocked")
    }
    setStatus("asking")
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: AUDIO })
      if (!alive.current) return s.getTracks().forEach((t) => t.stop())
      stream.current = s
      const fmt = pickFormat()
      const rec = new MediaRecorder(s, fmt.mime ? { mimeType: fmt.mime, audioBitsPerSecond: 128_000 } : undefined)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      rec.onstop = () => {
        const took = seconds()
        clock.current = { since: null, before: 0 }
        release()
        recorder.current = null
        if (!alive.current) return
        setStatus("idle")
        setLevel(0)
        setHint(null)
        const type = rec.mimeType || fmt.mime || "audio/webm"
        const blob = new Blob(chunks, { type })
        if (blob.size) done.current({ blob, ext: extFor(type), seconds: took })
      }
      rec.onerror = (e) => {
        rec.onstop = null
        clock.current = { since: null, before: 0 }
        release()
        recorder.current = null
        if (!alive.current) return
        setProblem({ kind: "error", detail: String((e as unknown as { error?: Error }).error?.message ?? "") })
        setStatus("blocked")
      }
      try {
        const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        if (AC) {
          const ctx = new AC()
          const analyser = ctx.createAnalyser()
          analyser.fftSize = 2048
          ctx.createMediaStreamSource(s).connect(analyser)
          meter.current = { ctx, analyser, buf: new Float32Array(analyser.fftSize) }
        }
      } catch {
        meter.current = null // no meter is better than no recording
      }
      recorder.current = rec
      rec.start(250)
      clock.current = { since: performance.now(), before: 0 }
      recent.current = []
      setElapsed(0)
      setHint(null)
      setStatus("recording")
      cancelAnimationFrame(frame.current)
      frame.current = requestAnimationFrame(tick)
    } catch (e) {
      release()
      recorder.current = null
      if (!alive.current) return
      setProblem({ kind: micProblem(e), detail: String((e as Error)?.message ?? e) })
      setStatus("blocked")
    }
  }, [release, tick])

  const pause = useCallback(() => {
    const rec = recorder.current
    if (rec?.state !== "recording") return
    rec.pause()
    clock.current = { since: null, before: seconds() }
    setStatus("paused")
  }, [])

  const resume = useCallback(() => {
    const rec = recorder.current
    if (rec?.state !== "paused") return
    rec.resume()
    clock.current = { since: performance.now(), before: clock.current.before }
    setStatus("recording")
  }, [])

  /** Finish the take: onRecording gets it once MediaRecorder has handed over the last of the data. */
  const stop = useCallback(() => {
    const rec = recorder.current
    if (!rec || rec.state === "inactive") return
    clock.current = { since: null, before: seconds() }
    rec.stop()
  }, [])

  // leaving the screen mid-take: drop it and let go of the mic
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      const rec = recorder.current
      if (rec && rec.state !== "inactive") {
        rec.onstop = null
        try {
          rec.stop()
        } catch {
          /* already stopped */
        }
      }
      recorder.current = null
      release()
    }
  }, [release])

  return { status, problem, elapsed, level, hint, start, pause, resume, stop, active: status === "recording" || status === "paused" }
}
