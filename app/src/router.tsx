import { createBrowserRouter } from "react-router"
import { AppShell } from "@/components/AppShell"
import { RouteError } from "@/components/ErrorScreen"
import { Home } from "@/pages/Home"
import { NewVideo } from "@/pages/NewVideo"
import { NotFound } from "@/pages/NotFound"
import { Presets } from "@/pages/Presets"
import { JobView } from "@/pages/project/JobView"
import { ProjectIndex } from "@/pages/project/ProjectIndex"
import { ProjectLayout } from "@/pages/project/ProjectLayout"
import { Questions } from "@/pages/project/Questions"
import { Result } from "@/pages/project/Result"
import { Setup } from "@/pages/project/setup/Setup"
import { TimelineReview } from "@/pages/project/timeline/TimelineReview"
import { SettingsPage } from "@/pages/Settings"

/** Dev only: a screen that throws while rendering, so the error screen can be seen and tested (/__crash). */
function Crash(): never {
  throw new Error("Test crash: /__crash throws on purpose to show the error screen")
}

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError fullPage />, // the shell itself broke: full-page error
    children: [
      {
        errorElement: <RouteError />, // a screen broke: the error shows inside the shell, sidebar still there
        children: [
          { index: true, element: <Home /> },
          { path: "new", element: <NewVideo /> },
          {
            path: "projects/:pid",
            element: <ProjectLayout />,
            children: [
              { index: true, element: <ProjectIndex /> },
              { path: "setup/:step", element: <Setup /> },
              { path: "questions", element: <Questions /> },
              { path: "jobs/:jobId", element: <JobView /> },
              { path: "plan", element: <TimelineReview /> },
              { path: "video", element: <Result /> },
            ],
          },
          { path: "presets", element: <Presets /> },
          { path: "presets/:name", element: <Presets /> },
          { path: "settings", element: <SettingsPage /> },
          ...(import.meta.env.DEV ? [{ path: "__crash", element: <Crash /> }] : []),
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
])

// The walkthrough scripts navigate like a user does (client-side, so screens really unmount)
if (import.meta.env.DEV) Object.assign(window, { __cutroom: { navigate: router.navigate } })
