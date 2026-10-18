import { Compass } from "lucide-react"
import { Link } from "react-router"
import { Page } from "@/components/Page"
import { EmptyState } from "@/components/States"
import { Button } from "@/components/ui/button"

export function NotFound() {
  return (
    <Page>
      <EmptyState
        className="mt-16"
        icon={<Compass className="size-5" />}
        title="Nothing here"
        description="This page doesn't exist, or the project was deleted."
        action={
          <Button asChild variant="outline">
            <Link to="/">Back to projects</Link>
          </Button>
        }
      />
    </Page>
  )
}
