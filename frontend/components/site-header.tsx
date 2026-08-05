"use client"

import Link from "next/link"
import { ArrowLeft, Code2 } from "lucide-react"

import { Button } from "@/components/ui/button"

const REPO_URL = "https://github.com/yashvisal/inbound-sdr-copilot"

export function SiteHeader({
  showBack = false,
  backHref = "/leads",
  /** Landing page points into the app; app pages don't need the CTA. */
  showAppLink = false,
}: {
  showBack?: boolean
  backHref?: string
  showAppLink?: boolean
}) {
  return (
    <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b bg-background/80 px-6 backdrop-blur">
      <div className="flex items-center gap-3">
        {showBack && (
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <Link href={backHref} aria-label="Back to leads">
              <ArrowLeft className="size-4" />
            </Link>
          </Button>
        )}
        <Link
          href="/"
          className="text-lg font-semibold tracking-tight transition-opacity hover:opacity-80"
        >
          Inbound SDR Copilot
        </Link>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            <Code2 className="size-4" />
            GitHub
          </a>
        </Button>
        {showAppLink && (
          <Button size="sm" asChild>
            <Link href="/leads">View leads</Link>
          </Button>
        )}
      </div>
    </header>
  )
}
