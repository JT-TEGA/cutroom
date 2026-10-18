import { AlertTriangle, ArrowLeft, Check, ChevronDown, Copy, RotateCw } from "lucide-react"
import { Component, type ErrorInfo, type ReactNode, useState } from "react"
import { isRouteErrorResponse, useRouteError } from "react-router"
import { cn } from "@/lib/utils"

function describe(error: unknown): { message: string; details: string } {
  if (isRouteErrorResponse(error)) {
    const data = typeof error.data === "string" ? error.data : JSON.stringify(error.data, null, 2)
    return { message: `${error.status} ${error.statusText}`.trim(), details: data ?? "" }
  }
  if (error instanceof Error) return { message: `${error.name}: ${error.message}`, details: error.stack ?? "" }
  return { message: String(error ?? "Unknown error"), details: "" }
}

function goBack() {
  if (window.history.length > 1) window.history.back()
  else window.location.assign("/")
}

/**
 * What a crash looks like: a calm explanation, Go back / Reload, and the technical details folded away
 * (with a copy button, for a bug report). Works inside the router or outside it.
 */
export function ErrorScreen({ error, componentStack, fullPage }: { error: unknown; componentStack?: string; fullPage?: boolean }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const { message, details } = describe(error)
  const report = [
    message,
    "",
    details,
    componentStack ? `\nComponent stack:${componentStack}` : "",
    `\nURL: ${window.location.href}`,
    `Time: ${new Date().toISOString()}`,
    `Browser: ${navigator.userAgent}`,
  ].join("\n")

  return (
    <div className={cn("grid place-items-center px-6", fullPage ? "min-h-screen bg-background" : "min-h-[calc(100vh-40px)] py-16")}>
      <div className="w-full max-w-[560px]">
        <div className="panel relative overflow-hidden p-8 text-center">
          <div className="pointer-events-none absolute -top-24 left-1/2 h-48 w-96 -translate-x-1/2 rounded-full bg-destructive/10 blur-3xl" />
          <div className="relative mx-auto mb-5 grid size-12 place-items-center rounded-full bg-destructive/15 text-destructive">
            <AlertTriangle className="size-5" />
          </div>
          <h1 className="relative text-[19px] font-semibold tracking-[-0.01em]">Something went wrong on this screen</h1>
          <p className="relative mx-auto mt-2 max-w-sm text-[13.5px] leading-relaxed text-muted-foreground">
            Your projects, uploads and renders are safe: they live on disk, not in this page. Go back, or reload the app.
          </p>
          <div className="relative mt-6 flex justify-center gap-2">
            <button
              onClick={goBack}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-white/[0.02] px-4 text-[13.5px] font-medium transition hover:bg-white/[0.06]"
            >
              <ArrowLeft className="size-4" /> Go back
            </button>
            <button
              onClick={() => window.location.reload()}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-[13.5px] font-medium text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.2)] transition hover:bg-[#8a6dff]"
            >
              <RotateCw className="size-4" /> Reload
            </button>
          </div>
        </div>

        <div className="mt-3 overflow-hidden rounded-xl border border-white/[0.06] bg-[#0b0b0e]">
          <button
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="flex w-full items-center gap-2.5 px-4 py-3 text-left text-[12.5px] text-muted-foreground transition hover:text-foreground"
          >
            <span className="flex-1">Technical details</span>
            <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
          </button>
          {open && (
            <div className="border-t border-white/[0.05] px-4 py-3">
              <div className="mb-2 flex items-start justify-between gap-3">
                <code className="text-[12.5px] [overflow-wrap:anywhere] text-red-200">{message}</code>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(report)
                    setCopied(true)
                    setTimeout(() => setCopied(false), 1500)
                  }}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-white/10 px-2 py-1 text-[11.5px] text-muted-foreground transition hover:text-foreground"
                >
                  {copied ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <pre className="max-h-72 overflow-auto font-mono text-[11px] leading-[1.6] break-all whitespace-pre-wrap text-zinc-500">
                {report.slice(message.length + 1).trim()}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** errorElement for the router: a route that throws while rendering shows this instead of React Router's page. */
export function RouteError({ fullPage }: { fullPage?: boolean }) {
  const error = useRouteError()
  return <ErrorScreen error={error} fullPage={fullPage} />
}

/** Last resort around the whole app (errors outside the router, in providers). */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { error: unknown; stack?: string }> {
  state: { error: unknown; stack?: string } = { error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    this.setState({ error, stack: info.componentStack ?? undefined })
  }

  render() {
    if (this.state.error) return <ErrorScreen error={this.state.error} componentStack={this.state.stack} fullPage />
    return this.props.children
  }
}
