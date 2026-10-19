import { FolderKanban, Layers, Plus, Settings2 } from "lucide-react"
import { useEffect, useRef } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router"
import { useProjects, useSystemStatus } from "@/api/queries"
import { ClaudeBanner } from "@/components/ClaudeBanner"
import { LogoMark } from "@/components/Logo"
import { StatusDot } from "@/components/StatusBadge"
import { Thumb } from "@/components/Thumb"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "/", label: "Projects", icon: FolderKanban, end: true },
  { to: "/presets", label: "Presets", icon: Layers },
  { to: "/settings", label: "Settings", icon: Settings2 },
]

function BrainChip() {
  const { data: s, isLoading } = useSystemStatus()
  const cc = (s?.claude_code ?? {}) as { logged_in?: boolean; subscription?: string }
  let dot = "bg-ink-faint"
  let label = "Checking…"
  let sub = ""
  if (s?.demo) {
    dot = "bg-primary"
    label = "Demo brain"
    sub = "scripted answers"
  } else if (s) {
    const ready = !!s.brain?.ready
    dot = ready ? "bg-success" : "bg-warn"
    if (s.brain?.backend === "anthropic-api") {
      label = "Anthropic API"
      sub = ready ? String(s.brain?.model ?? "") : "no API key"
    } else {
      label = "Claude Code"
      sub = ready ? `connected${cc.subscription ? ` · ${cc.subscription}` : ""}` : cc.logged_in === false ? "not logged in" : "not ready"
    }
  } else if (!isLoading) {
    dot = "bg-destructive"
    label = "Server offline"
  }
  return (
    <NavLink
      to="/settings"
      className="group flex items-center gap-2.5 rounded-full bg-surface-2/70 px-3.5 py-2 transition hover:bg-surface-2 max-xl:justify-center max-xl:px-0"
    >
      <span className={cn("size-2 shrink-0 rounded-full", dot)} />
      <span className="min-w-0 leading-tight max-xl:hidden">
        <span className="block text-[12.5px] font-medium">{label}</span>
        {sub && <span className="block truncate text-[11.5px] text-ink-soft">{sub}</span>}
      </span>
    </NavLink>
  )
}

function Sidebar() {
  const navigate = useNavigate()
  const { data: projects } = useProjects()
  const recent = (projects ?? []).slice(0, 5)
  return (
    <aside className="my-3 ml-3 flex h-[calc(100vh-24px)] w-[236px] shrink-0 flex-col rounded-card bg-sidebar px-3 pt-4 pb-3 shadow-soft max-xl:w-[64px] max-xl:px-2">
      <NavLink to="/" className="mb-5 flex items-center gap-2.5 px-1.5 max-xl:justify-center max-xl:px-0">
        <LogoMark />
        <span className="text-[15px] font-semibold tracking-[-0.01em] max-xl:hidden">Cutroom</span>
      </NavLink>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button className="mb-4 w-full justify-start max-xl:justify-center max-xl:px-0" onClick={() => navigate("/new")}>
            <Plus />
            <span className="max-xl:hidden">New video</span>
          </Button>
        </TooltipTrigger>
        <TooltipContent side="right" className="xl:hidden">
          New video
        </TooltipContent>
      </Tooltip>

      <nav className="flex flex-col gap-0.5">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              cn(
                "flex h-9 items-center gap-2.5 rounded-full px-3 text-[13.5px] font-medium text-ink-soft transition-colors hover:bg-ink/[0.05] hover:text-foreground max-xl:justify-center max-xl:px-0",
                isActive && "bg-accent text-accent-ink hover:bg-accent",
              )
            }
          >
            <n.icon className="size-4" />
            <span className="max-xl:hidden">{n.label}</span>
          </NavLink>
        ))}
      </nav>

      {recent.length > 0 && (
        <div className="mt-7 max-xl:hidden">
          <div className="eyebrow mb-2 px-2.5">Recent</div>
          <div className="flex flex-col gap-0.5">
            {recent.map((p) => (
              <NavLink
                key={p.id}
                to={`/projects/${p.id}`}
                className={({ isActive }) =>
                  cn(
                    "group flex items-center gap-2.5 rounded-full py-1.5 pr-3 pl-1.5 text-[13px] text-ink-soft transition-colors hover:bg-ink/[0.05] hover:text-foreground",
                    isActive && "bg-accent text-accent-ink hover:bg-accent",
                  )
                }
              >
                <Thumb path={p.thumbnail} w={96} className="h-7 w-[18px] shrink-0 rounded-[6px]" />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <StatusDot status={p.status} />
              </NavLink>
            ))}
          </div>
        </div>
      )}

      <div className="mt-auto">
        <BrainChip />
      </div>
    </aside>
  )
}

export function AppShell() {
  const main = useRef<HTMLElement>(null)
  const { pathname } = useLocation()
  useEffect(() => {
    // each screen opens at the top (a plain assignment: scrollTo() returns a Promise in newer Chrome, and an effect
    // must never return anything but a cleanup function)
    if (main.current) main.current.scrollTop = 0
  }, [pathname])
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main ref={main} id="main" className="relative min-w-0 flex-1 overflow-y-auto">
        <ClaudeBanner />
        <Outlet />
      </main>
    </div>
  )
}
