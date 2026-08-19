import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { REPO_URL } from "@/lib/landing-content"

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
      {children}
    </p>
  )
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mt-4 text-3xl font-semibold tracking-tight">{children}</h2>
  )
}

export function HeroActions() {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button size="lg" asChild>
        <Link href="/leads">
          Open the dashboard
          <ArrowRight className="size-4" />
        </Link>
      </Button>
      <Button size="lg" variant="outline" asChild>
        <a href={REPO_URL} target="_blank" rel="noreferrer">
          Read the code
        </a>
      </Button>
    </div>
  )
}

export function ClosingCta({ title, body }: { title: string; body: string }) {
  return (
    <section className="border-t">
      <div className="mx-auto w-full max-w-6xl px-8 py-24 text-center">
        <h2 className="text-3xl font-semibold tracking-tight">{title}</h2>
        <p className="mx-auto mt-4 max-w-xl leading-relaxed text-muted-foreground">
          {body}
        </p>
        <Button size="lg" className="mt-9" asChild>
          <Link href="/leads">
            View leads
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </div>
    </section>
  )
}

export function LandingFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-8 py-6 text-sm text-muted-foreground">
        <span>Built by Yash Visal</span>
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="transition-colors hover:text-foreground"
        >
          GitHub
        </a>
      </div>
    </footer>
  )
}

export function priorityClass(priority: string) {
  if (priority === "High") return "bg-primary/10 text-foreground"
  if (priority === "Medium") return "bg-muted text-muted-foreground"
  return "bg-muted/50 text-muted-foreground/70"
}
