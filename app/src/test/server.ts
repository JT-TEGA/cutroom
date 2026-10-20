// The fake Cutroom API for component tests: each test registers handlers ("POST /api/projects/p1/takes"), every
// request is recorded, and anything unhandled is a 404 the test can see in `server.calls`.

export type Reply = { status: number; json?: unknown; blob?: Blob }
type Body = FormData | string | null
type Handler = (req: { url: URL; body: Body }) => Reply | Promise<Reply>

export const server = {
  routes: new Map<string, Handler>(),
  calls: [] as { method: string; path: string; body: Body }[],
  on(route: string, handler: Handler) {
    this.routes.set(route, handler)
    return this
  },
  reset() {
    this.routes.clear()
    this.calls = []
  },
}

export async function respond(method: string, url: URL, body: Body): Promise<Reply> {
  server.calls.push({ method, path: url.pathname, body })
  const handler = server.routes.get(`${method} ${url.pathname}`)
  if (!handler) return { status: 404, json: { error: { code: "not_found", message: `no fake for ${method} ${url.pathname}` } } }
  return handler({ url, body })
}
