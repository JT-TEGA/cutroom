import { createBrowserRouter } from "react-router"
import { AppShell } from "@/components/AppShell"
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

export const router = createBrowserRouter([
  {
    element: <AppShell />,
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
      { path: "*", element: <NotFound /> },
    ],
  },
])
