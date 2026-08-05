import Link from "next/link"
import { ArrowRight, Building2, ChevronDown, MapPin, Sparkles } from "lucide-react"

import { SiteHeader } from "@/components/site-header"
import { Button } from "@/components/ui/button"

const QUESTIONS = [
  {
    index: "Q1",
    question: "Who do I prioritize?",
    answer:
      "Inbound leads arrive in whatever order the form sends them. The copilot scores every one on the same 100-point rubric, so the queue is ranked by opportunity — not by arrival time.",
  },
  {
    index: "Q2",
    question: "Why is this lead worth my time?",
    answer:
      "A number alone isn't an argument. Every score comes with its reasons: the market signals, the company evidence, the property classification — each traced to the source it came from.",
  },
  {
    index: "Q3",
    question: "What do I say?",
    answer:
      "The first email writes itself from the verified enrichment: the market insight, the company's actual operations, the property context. Facts the rep can stand behind, not filler.",
  },
]

const CATEGORIES = [
  {
    title: "Location Fit",
    points: 45,
    icon: MapPin,
    summary:
      "Leasing demand where the property actually sits — renter share, income, vacancy and transit access at the block-group level, on top of city population, rent and growth.",
    sources: "Census ACS · Census Geocoder",
  },
  {
    title: "Company Fit",
    points: 39,
    icon: Building2,
    summary:
      "Whether this is a buyer at all: leasing volume, operational complexity and product fit, read from website metadata and search evidence.",
    sources: "Company website · Serper",
  },
  {
    title: "Property Fit",
    points: 16,
    icon: Sparkles,
    summary:
      "Whether the submitted address is a residential leasing asset, using OSM property type plus search results filtered to that exact building.",
    sources: "OSM / Nominatim · Serper",
  },
]

const PIPELINE = [
  {
    step: "01",
    title: "Enrich",
    body: "Resolve the address to census geography, then pull market data, company website metadata and address-matched search results.",
  },
  {
    step: "02",
    title: "Extract",
    body: "An LLM reads that evidence and sorts it into buckets — “leasing volume: High” — citing the snippet it came from.",
  },
  {
    step: "03",
    title: "Score",
    body: "Python maps buckets to points against a fixed rubric, applies caps for weak product fit, and calibrates unit counts in code.",
  },
  {
    step: "04",
    title: "Draft",
    body: "Sales insights and a personalized email, written only from verified enrichment and the score reasoning.",
  },
]

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader showAppLink />

      <main className="flex-1">
        {/* Hero: full viewport, static grid backdrop, room to breathe */}
        <section className="relative flex min-h-[calc(100svh-4rem)] flex-col">
          <div className="hero-grid pointer-events-none absolute inset-0" aria-hidden />
          <div className="hero-glow pointer-events-none absolute inset-0" aria-hidden />

          <div className="relative mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center px-8 text-center">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Lead enrichment &amp; scoring for property management
            </p>
            <h1 className="mt-8 text-balance text-5xl font-semibold leading-[1.06] tracking-tight sm:text-6xl md:text-7xl">
              Know which inbound lead to call first — and why.
            </h1>
            <p className="mt-8 max-w-2xl text-lg leading-relaxed text-muted-foreground">
              An inbound lead arrives as a name, an email and a property
              address. This scores it out of 100 from public data alone, shows
              the evidence behind every point, and drafts the outreach.
            </p>
            <div className="mt-12 flex flex-wrap items-center justify-center gap-3">
              <Button size="lg" asChild>
                <Link href="/leads">
                  View leads
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <a
                  href="https://github.com/yashvisal/inbound-sdr-copilot"
                  target="_blank"
                  rel="noreferrer"
                >
                  Read the code
                </a>
              </Button>
            </div>
          </div>

          <div className="relative flex justify-center pb-10">
            <ChevronDown className="size-5 animate-bounce text-muted-foreground/50" />
          </div>
        </section>

        {/* The problem */}
        <section className="border-t">
          <div className="mx-auto grid w-full max-w-6xl gap-14 px-8 py-24 lg:grid-cols-[2fr_3fr]">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
                The problem
              </p>
              <h2 className="mt-4 text-3xl font-semibold tracking-tight">
                An SDR has to answer three questions before touching the phone.
              </h2>
              <p className="mt-6 leading-relaxed text-muted-foreground">
                Answering them by hand means tab-hopping through census data,
                company websites and Google — for every single lead, before
                knowing whether it deserves the effort. The copilot runs that
                research in one pass, in about twelve seconds, and shows its
                work.
              </p>
            </div>

            <div className="divide-y">
              {QUESTIONS.map(({ index, question, answer }) => (
                <div key={index} className="flex gap-6 py-7 first:pt-0 last:pb-0">
                  <span className="font-mono text-sm text-muted-foreground/50">
                    {index}
                  </span>
                  <div className="space-y-2">
                    <h3 className="text-lg font-medium">{question}</h3>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {answer}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Scoring */}
        <section className="border-t">
          <div className="mx-auto w-full max-w-6xl px-8 py-24">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Methodology
            </p>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">
              One hundred points, across three axes.
            </h2>

            <div className="mt-12 grid gap-6 md:grid-cols-3">
              {CATEGORIES.map(({ title, points, icon: Icon, summary, sources }) => (
                <div
                  key={title}
                  className="flex flex-col gap-4 rounded-xl border bg-card/40 p-6"
                >
                  <div className="flex items-center justify-between">
                    <Icon className="size-5 text-muted-foreground" />
                    <span className="text-2xl font-semibold tabular-nums">
                      {points}
                    </span>
                  </div>
                  <div className="space-y-2">
                    <h3 className="font-medium">{title}</h3>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {summary}
                    </p>
                  </div>
                  <p className="mt-auto font-mono text-[11px] uppercase tracking-wider text-muted-foreground/60">
                    {sources}
                  </p>
                </div>
              ))}
            </div>

            {/* Ascending like a number line: low on the left, high on the right */}
            <div className="mt-8 grid gap-4 sm:grid-cols-3">
              {[
                ["0-49", "Low priority", "bg-card/20"],
                ["50-74", "Medium priority", "bg-card/40"],
                ["75-100", "High priority", "bg-card/70"],
              ].map(([range, label, tone]) => (
                <div
                  key={range}
                  className={`flex items-baseline gap-3 rounded-lg border ${tone} px-4 py-3`}
                >
                  <span className="font-medium tabular-nums">{range}</span>
                  <span className="text-sm text-muted-foreground">{label}</span>
                </div>
              ))}
            </div>
            <p className="mt-8 max-w-4xl leading-relaxed text-muted-foreground">
              Reaching High takes evidence on all three axes: company and
              property fit alone top out at 55, so a strong operator in a market
              with no data lands at Medium. Missing data lowers confidence, not
              the score.
            </p>
          </div>
        </section>

        {/* Pipeline */}
        <section className="border-t">
          <div className="mx-auto w-full max-w-6xl px-8 py-24">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
              How it works
            </p>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">
              The LLM reads the evidence. It never picks the score.
            </h2>
            <div className="mt-12 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
              {PIPELINE.map(({ step, title, body }) => (
                <div key={step} className="border-t pt-4">
                  <div className="flex items-baseline justify-between">
                    <h3 className="font-medium">{title}</h3>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground/60">
                      {step}
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                    {body}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-12 max-w-4xl leading-relaxed text-muted-foreground">
              Scoring stays deterministic Python, so the same evidence always
              produces the same number. If the model is unavailable, returns
              malformed JSON, or cites evidence that isn&apos;t in the sources,
              a rule-based classifier takes over and the system keeps working.
            </p>
          </div>
        </section>

        {/* Closing CTA */}
        <section className="border-t">
          <div className="mx-auto w-full max-w-6xl px-8 py-24 text-center">
            <h2 className="text-3xl font-semibold tracking-tight">
              See it on real leads.
            </h2>
            <p className="mx-auto mt-4 max-w-xl leading-relaxed text-muted-foreground">
              Open the dashboard to browse scored leads, see any lead&apos;s
              full breakdown, or run one of your own against live data.
            </p>
            <Button size="lg" className="mt-9" asChild>
              <Link href="/leads">
                View leads
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-8 py-6 text-sm text-muted-foreground">
          <span>Built by Yash Visal</span>
          <a
            href="https://github.com/yashvisal/inbound-sdr-copilot"
            target="_blank"
            rel="noreferrer"
            className="transition-colors hover:text-foreground"
          >
            GitHub
          </a>
        </div>
      </footer>
    </div>
  )
}
