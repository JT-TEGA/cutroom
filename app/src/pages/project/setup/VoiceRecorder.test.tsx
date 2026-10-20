// The voiceover recorder with a fake microphone: getUserMedia, MediaRecorder and the Web Audio meter are mocked, the
// API is the fake server from src/test. Covers the blocked mic, record / pause / stop, takes that come back after a
// refresh, Re-record and Delete, and "Use this" going through the files endpoint like an imported voice memo.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { Project, ProjectFile, Take } from "@/api/types"
import { levelOf, micProblem } from "@/lib/recorder"
import { server } from "@/test/server"
import { StepMedia } from "./StepMedia"
import { takeFile, VoiceRecorder } from "./VoiceRecorder"

// ---------------------------------------------------------------- the fake mic

class FakeRecorder {
  static isTypeSupported = (m: string) => m === "audio/webm;codecs=opus"
  static last: FakeRecorder | null = null
  state: RecordingState = "inactive"
  mimeType: string
  options?: MediaRecorderOptions
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: ((e: Event) => void) | null = null
  constructor(_stream: MediaStream, options?: MediaRecorderOptions) {
    this.options = options
    this.mimeType = options?.mimeType ?? "audio/webm"
    FakeRecorder.last = this
  }
  start() {
    this.state = "recording"
  }
  pause() {
    this.state = "paused"
  }
  resume() {
    this.state = "recording"
  }
  stop() {
    this.state = "inactive"
    // like the real thing: the last data and the stop event arrive after stop() returns
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(["opus frames"], { type: this.mimeType }) })
      this.onstop?.()
    })
  }
}

let loudness = 0.2 // the fake mic's input, as a sine amplitude
class FakeAudioContext {
  createAnalyser() {
    return {
      fftSize: 2048,
      getFloatTimeDomainData(b: Float32Array) {
        for (let i = 0; i < b.length; i++) b[i] = loudness * Math.sin(i / 4)
      },
    }
  }
  createMediaStreamSource() {
    return { connect() {} }
  }
  close() {
    return Promise.resolve()
  }
}

let now = 0 // performance.now(), moved by the tests: the timer reads it
function installMic() {
  const track = { stop: vi.fn() }
  const getUserMedia = vi.fn(async (_c: MediaStreamConstraints) => ({ getTracks: () => [track] }) as unknown as MediaStream)
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true })
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true })
  vi.stubGlobal("MediaRecorder", FakeRecorder)
  vi.stubGlobal("AudioContext", FakeAudioContext)
  vi.spyOn(performance, "now").mockImplementation(() => now)
  return { getUserMedia, track }
}

// ---------------------------------------------------------------- the fake API

const take = (n: number, ext = "webm"): Take => ({
  id: `take-${n}`,
  number: n,
  path: `inputs/voiceover/takes/take-${n}.${ext}`,
  duration: 4.2 + n,
  size: 2048,
  peaks: Array.from({ length: 120 }, (_, i) => Math.abs(Math.sin(i / 7))),
  created_at: new Date().toISOString(),
})

const clip: ProjectFile = { id: "c1", name: "incline-bench.mp4", path: "inputs/clips/incline-bench.mp4", kind: "clip", duration: 6, size: 1 } as ProjectFile

function fakeProject(files: ProjectFile[] = [clip]): Project {
  return { id: "p1", name: "5AM chest day", status: "new", brief: { content_type: "gym-vlog", talking: "voiceover" }, files } as Project
}

/** Takes kept on the "server": POST adds the next one, DELETE removes it, the media route plays it back. */
function takesApi(initial: Take[] = []) {
  const takes = [...initial]
  server
    .on("GET /api/projects/p1/takes", () => ({ status: 200, json: takes }))
    .on("POST /api/projects/p1/takes", ({ body }) => {
      const file = (body as FormData).get("file") as File
      const t = take(Math.max(0, ...takes.map((x) => x.number)) + 1, file.name.split(".").pop())
      takes.push(t)
      return { status: 201, json: t }
    })
    .on("GET /api/media/file", ({ url }) => ({ status: 200, blob: new Blob([`audio of ${url.searchParams.get("path")}`], { type: "audio/webm" }) }))
  for (const t of [...initial, take(initial.length + 1), take(initial.length + 2)])
    server.on(`DELETE /api/projects/p1/takes/${t.id}`, () => {
      takes.splice(
        takes.findIndex((x) => x.id === t.id),
        1,
      )
      return { status: 204 }
    })
  return takes
}

function wrap(ui: ReactNode, project?: Project) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  if (project) qc.setQueryData(["project", project.id], project) // what the project screen has loaded
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const dialog = () => screen.getByRole("dialog")
const button = (name: string | RegExp) => within(dialog()).getByRole("button", { name })

beforeEach(() => {
  now = 0
  loudness = 0.2
  FakeRecorder.last = null
})

// ---------------------------------------------------------------- tests

describe("VoiceRecorder", () => {
  it("explains a blocked mic in Chrome, and Try again records once it's allowed", async () => {
    const mic = installMic()
    mic.getUserMedia.mockRejectedValueOnce(new DOMException("Permission denied", "NotAllowedError"))
    takesApi()
    wrap(<VoiceRecorder project={fakeProject()} open onOpenChange={() => {}} onUse={async () => true} />)

    expect(within(dialog()).getByTestId("record-tip")).toHaveProperty("textContent", "Record in a quiet room, phone/mic ~20cm away.")
    fireEvent.click(button("Record"))
    const help = await within(dialog()).findByTestId("mic-help")
    expect(help.dataset.problem).toBe("denied")
    expect(help.textContent).toContain("Let Cutroom use your microphone")
    expect(help.textContent).toContain("left end of the address bar")
    expect(help.textContent).toContain("chrome://settings/content/microphone")

    fireEvent.click(button(/Try again/))
    await waitFor(() => expect(within(dialog()).getByTestId("recorder").dataset.status).toBe("recording"))
    expect(mic.getUserMedia).toHaveBeenCalledTimes(2)
    // the browser's call processing is off: Cutroom's own clean-up does it
    expect(mic.getUserMedia.mock.calls[1][0]).toEqual({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    })
  })

  it("tells macOS, no mic, a busy mic and an old browser apart, and never crashes", async () => {
    expect(micProblem(new DOMException("Permission denied by system", "NotAllowedError"))).toBe("denied-system")
    expect(micProblem(new DOMException("Requested device not found", "NotFoundError"))).toBe("no-mic")
    expect(micProblem(new DOMException("Could not start audio source", "NotReadableError"))).toBe("busy")
    expect(micProblem("weird")).toBe("error")

    const mic = installMic()
    mic.getUserMedia.mockRejectedValueOnce(new DOMException("Permission denied by system", "NotAllowedError"))
    takesApi()
    const { unmount } = wrap(<VoiceRecorder project={fakeProject()} open onOpenChange={() => {}} onUse={async () => true} />)
    fireEvent.click(button("Record"))
    expect((await within(dialog()).findByTestId("mic-help")).textContent).toContain("Privacy & Security → Microphone")
    unmount()

    vi.stubGlobal("MediaRecorder", undefined)
    wrap(<VoiceRecorder project={fakeProject()} open onOpenChange={() => {}} onUse={async () => true} />)
    fireEvent.click(button("Record"))
    expect((await within(dialog()).findByTestId("mic-help")).textContent).toContain("This browser can't record audio")
  })

  it("records with a live level and timer, pauses, stops and keeps the take", async () => {
    const mic = installMic()
    const takes = takesApi()
    wrap(<VoiceRecorder project={fakeProject()} open onOpenChange={() => {}} onUse={async () => true} />)

    fireEvent.click(button("Record"))
    const rec = await within(dialog()).findByTestId("recorder")
    await waitFor(() => expect(rec.dataset.status).toBe("recording"))
    expect(FakeRecorder.last?.options?.mimeType).toBe("audio/webm;codecs=opus")

    act(() => void (now = 2_300))
    await waitFor(() => expect(within(dialog()).getByTestId("rec-timer").textContent).toBe("0:02.3"))
    await waitFor(() => expect(Number(within(dialog()).getByTestId("level-meter").dataset.level)).toBeGreaterThan(0.5))
    expect(within(dialog()).getByTestId("level-hint").textContent).toBe("Good level")
    act(() => void (loudness = 0.004))
    act(() => void (now = 4_600))
    await waitFor(() => expect(within(dialog()).getByTestId("level-hint").textContent).toMatch(/move a little closer/))

    fireEvent.click(button(/Pause/))
    await waitFor(() => expect(rec.dataset.status).toBe("paused"))
    expect(FakeRecorder.last?.state).toBe("paused")
    act(() => void (now = 9_000)) // paused time doesn't count
    fireEvent.click(button(/Resume/))
    act(() => void (now = 10_000))
    await waitFor(() => expect(within(dialog()).getByTestId("rec-timer").textContent).toBe("0:05.6"))

    fireEvent.click(button(/Stop/))
    const review = await within(dialog()).findByTestId("take-review")
    expect(review.dataset.take).toBe("take-1")
    expect(mic.track.stop).toHaveBeenCalled() // the mic is let go between takes
    const upload = server.calls.find((c) => c.method === "POST" && c.path === "/api/projects/p1/takes")!
    const sent = (upload.body as FormData).get("file") as File
    expect([sent.name, sent.type]).toEqual(["take.webm", "audio/webm;codecs=opus"])
    expect(takes.map((t) => t.id)).toEqual(["take-1"])
    expect(within(review).getByTestId("take-player")).toBeTruthy()
    for (const name of [/Use this/, /Re-record/, /Delete/]) expect(button(name)).toBeTruthy()
  })

  it("keeps several takes across a refresh: Re-record adds one, Delete removes one, Use this picks one", async () => {
    installMic()
    const takes = takesApi([take(1)]) // recorded before the page was reloaded
    const onUse = vi.fn(async () => true)
    const onOpenChange = vi.fn()
    wrap(<VoiceRecorder project={fakeProject()} open onOpenChange={onOpenChange} onUse={onUse} />)

    expect((await within(dialog()).findByTestId("take-review")).dataset.take).toBe("take-1")
    fireEvent.click(button(/Re-record/))
    await waitFor(() => expect(within(dialog()).getByTestId("recorder").dataset.status).toBe("recording"))
    fireEvent.click(button(/Stop/))
    await waitFor(() => expect(within(dialog()).getByTestId("take-review").dataset.take).toBe("take-2"))
    expect(within(within(dialog()).getByTestId("takes")).getAllByRole("button").map((b) => b.textContent?.trim())).toEqual([
      "Take 10:05",
      "Take 20:06",
      "New take",
    ])

    fireEvent.click(within(dialog()).getByRole("button", { name: /Take 1/ }))
    await waitFor(() => expect(within(dialog()).getByTestId("take-review").dataset.take).toBe("take-1"))
    fireEvent.click(button(/Delete/))
    await waitFor(() => expect(takes.map((t) => t.id)).toEqual(["take-2"]))
    await waitFor(() => expect(within(dialog()).getByTestId("take-review").dataset.take).toBe("take-2"))

    fireEvent.click(button(/Use this/))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(onUse).toHaveBeenCalledWith(expect.objectContaining({ id: "take-2" }), undefined)
  })

  it("fetches a stored take back as a file to upload", async () => {
    takesApi([take(3)])
    const f = await takeFile("p1", take(3))
    expect([f.name, f.type, await f.text()]).toEqual(["take-3.webm", "audio/webm", "audio of p1/inputs/voiceover/takes/take-3.webm"])
  })

  it("puts the meter on a dBFS scale", () => {
    expect(levelOf(new Float32Array(512)).level).toBe(0)
    const loud = levelOf(Float32Array.from({ length: 512 }, (_, i) => (i % 2 ? 1 : -1)))
    expect(loud.level).toBeCloseTo(1)
    expect(loud.peak).toBe(1)
  })
})

describe("the Voiceover card", () => {
  it("Record → Use this uploads the take through the files endpoint, as a voiceover, first in the edit order", async () => {
    installMic()
    takesApi()
    let files: ProjectFile[] = [clip]
    server
      .on("GET /api/projects/p1", () => ({ status: 200, json: fakeProject(files) }))
      .on("POST /api/projects/p1/files", ({ body }) => {
        const form = body as FormData
        const vo = { id: "v1", name: "take-1.wav", path: "inputs/voiceover/take-1.wav", kind: "voiceover", take: form.get("take"), size: 9, duration: 5.2 }
        files = [...files, vo as ProjectFile]
        return { status: 201, json: [vo] }
      })
      .on("PATCH /api/projects/p1/files", ({ body }) => {
        const order = JSON.parse(body as string).order as string[]
        files = order.map((id) => files.find((f) => f.id === id)!)
        return { status: 200, json: files }
      })
    wrap(<StepMedia project={fakeProject()} />, fakeProject())

    fireEvent.click(within(screen.getByTestId("drop-voiceover")).getByRole("button", { name: "Record" }))
    fireEvent.click(button("Record"))
    await waitFor(() => expect(within(dialog()).getByTestId("recorder").dataset.status).toBe("recording"))
    fireEvent.click(button(/Stop/))
    await within(dialog()).findByTestId("take-review")
    fireEvent.click(button(/Use this/))

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    const post = server.calls.find((c) => c.method === "POST" && c.path === "/api/projects/p1/files")!
    const form = post.body as FormData
    expect([form.get("kind"), form.get("take"), (form.get("files") as File).name]).toEqual(["voiceover", "take-1", "take-1.webm"])
    // the take was fetched back from the project, not kept in the browser
    expect(server.calls.some((c) => c.path === "/api/media/file")).toBe(true)
    await waitFor(() => expect(files.map((f) => f.id)).toEqual(["v1", "c1"]))
  })
})
