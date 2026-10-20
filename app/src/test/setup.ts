// Component tests run in jsdom, which lacks a few things the app uses. The API client keeps the fetch and Request it
// finds when it's created (on import), so both are swapped here, before any app code loads, for ones that answer
// from the test's fake server (src/test/server.ts). Uploads go through XMLHttpRequest, which is faked the same way.
import { cleanup } from "@testing-library/react"
import { afterEach, vi } from "vitest"
import { respond, server } from "./server"

const NodeRequest = globalThis.Request
// the app calls the API at relative URLs (/api/...), which only a browser's Request accepts
globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === "string" ? new URL(input, location.href) : input, init)
  }
} as typeof Request

globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const req = input instanceof Request ? input : new Request(input, init)
  const r = await respond(req.method, new URL(req.url), req.method === "GET" ? null : await req.clone().text())
  // as bytes: Node's Response doesn't take jsdom's Blob
  const body = r.blob ? new Uint8Array(await r.blob.arrayBuffer()) : r.json === undefined ? null : JSON.stringify(r.json)
  return new Response(body, { status: r.status, headers: { "content-type": r.blob ? r.blob.type : "application/json" } })
}

class FakeXHR {
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null }
  status = 0
  statusText = ""
  responseText = ""
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  private method = "GET"
  private url = ""
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  send(body: FormData | null) {
    respond(this.method, new URL(this.url, location.href), body).then(
      (r) => {
        this.status = r.status
        this.responseText = r.json === undefined ? "" : JSON.stringify(r.json)
        this.onload?.()
      },
      () => this.onerror?.(),
    )
  }
}
globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest

// jsdom has <audio> but can't play it
HTMLMediaElement.prototype.play = function () {
  this.dispatchEvent(new Event("play"))
  return Promise.resolve()
}
HTMLMediaElement.prototype.pause = function () {
  this.dispatchEvent(new Event("pause"))
}

afterEach(() => {
  cleanup()
  server.reset()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
