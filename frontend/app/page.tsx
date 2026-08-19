import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { SiteHeader } from "@/components/site-header"
import {
  ClosingCta,
  Eyebrow,
  HeroActions,
  LandingFooter,
  SectionTitle,
  priorityClass,
} from "@/components/landing/shared"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  CATEGORIES,
  GUARDRAILS,
  PIPELINE,
  QUESTIONS,
  SAMPLE_LEADS,
} from "@/lib/landing-content"

const RUBRIC_ROWS = [
  { axis: "Location Fit", signal: "Renter share, income, vacancy and transit access; city population, rent and growth", points: 45, source: "Census ACS, Census Geocoder" },
  { axis: "Company Fit", signal: "Leasing volume, operational complexity, product fit", points: 39, source: "Company website, Serper" },
  { axis: "Property Fit", signal: "Residential leasing asset or not, at that exact address", points: 16, source: "OSM / Nominatim, Serper" },
]

export default function LandingPage() {
  const queue = SAMPLE_LEADS.slice(0, 5)

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader showAppLink />

      <main className="flex-1">
        {/* Hero: the ranked queue is the product, so show it */}
        <section className="relative">
          <div className="hero-grid pointer-events-none absolute inset-0" aria-hidden />
          <div className="hero-glow pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative mx-auto w-full max-w-6xl px-8 pt-24 pb-24">
            <div className="max-w-3xl">
              <Eyebrow>Lead enrichment and scoring for property management</Eyebrow>
              <h1 className="mt-7 text-balance text-5xl font-semibold leading-[1.06] tracking-tight sm:text-6xl">
                Rank inbound leads by opportunity, not arrival time.
              </h1>
              <p className="mt-7 max-w-2xl text-lg leading-relaxed text-muted-foreground">
                Paste in a name, a company and a property address. Get back a
                0 to 100 priority score built from public data, the evidence
                behind every point, and a first email that reads like someone
                did the research.
              </p>
              <div className="mt-10">
                <HeroActions />
              </div>
            </div>

            <div className="mt-16 overflow-hidden rounded-xl border bg-card/30">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-16 pl-5">Rank</TableHead>
                    <TableHead>Lead</TableHead>
                    <TableHead>Property</TableHead>
                    <TableHead className="w-24 text-right">Score</TableHead>
                    <TableHead className="w-28 pr-5 text-right">Priority</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {queue.map((lead, index) => (
                    <TableRow key={lead.id} className="hover:bg-transparent">
                      <TableCell className="pl-5 font-semibold tabular-nums">
                        {index + 1}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{lead.name}</div>
                        <div className="text-xs text-muted-foreground">{lead.company}</div>
                      </TableCell>
                      <TableCell className="max-w-[260px] truncate text-muted-foreground">
                        {lead.address}, {lead.city}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {lead.score}
                      </TableCell>
                      <TableCell className="pr-5 text-right">
                        <span className={`inline-block rounded-md px-2 py-0.5 text-xs ${priorityClass(lead.priority)}`}>
                          {lead.priority}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center justify-between border-t px-5 py-3 text-xs text-muted-foreground">
                <span>Every row opens into its full evidence and outreach.</span>
                <Link href="/leads" className="flex items-center gap-1 transition-colors hover:text-foreground">
                  Open the dashboard <ArrowRight className="size-3" />
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* The problem */}
        <section className="border-t">
          <div className="mx-auto grid w-full max-w-6xl gap-14 px-8 py-24 lg:grid-cols-[2fr_3fr]">
            <div>
              <Eyebrow>The problem</Eyebrow>
              <SectionTitle>
                An SDR has to answer three questions before touching the phone.
              </SectionTitle>
              <p className="mt-6 leading-relaxed text-muted-foreground">
                Answering them by hand means tab-hopping through census data,
                company websites and Google for every single lead, before
                knowing whether it deserves the effort. This runs that research
                in one pass and shows its work.
              </p>
            </div>
            <div className="divide-y">
              {QUESTIONS.map(({ question, answer }, index) => (
                <div key={question} className="flex gap-6 py-7 first:pt-0 last:pb-0">
                  <span className="font-mono text-sm text-muted-foreground/50">
                    Q{index + 1}
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

        {/* Methodology */}
        <section className="border-t">
          <div className="mx-auto w-full max-w-6xl px-8 py-24">
            <Eyebrow>Methodology</Eyebrow>
            <SectionTitle>The rubric, in full.</SectionTitle>

            <div className="mt-10 overflow-hidden rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="h-11 w-[140px] pl-5">Axis</TableHead>
                    <TableHead className="h-11">What it reads</TableHead>
                    <TableHead className="h-11 w-[250px]">Sources</TableHead>
                    <TableHead className="h-11 w-[100px] pr-5 text-right">Points</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {RUBRIC_ROWS.map(({ axis, signal, points, source }) => (
                    <TableRow key={axis} className="hover:bg-transparent">
                      <TableCell className="py-4 pl-5 font-medium">{axis}</TableCell>
                      <TableCell className="py-4 whitespace-normal text-muted-foreground">{signal}</TableCell>
                      <TableCell className="py-4 whitespace-normal text-muted-foreground">{source}</TableCell>
                      <TableCell className="py-4 pr-5 text-right font-semibold tabular-nums">{points}</TableCell>
                    </TableRow>
                  ))}
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableCell className="py-3.5 pl-5 font-medium" colSpan={3}>Total</TableCell>
                    <TableCell className="py-3.5 pr-5 text-right font-semibold tabular-nums">100</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-3">
              {CATEGORIES.map(({ key, title, summary }) => (
                <div key={key} className="flex flex-col gap-3 rounded-xl border bg-card/40 p-6">
                  <h3 className="font-medium">{title}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">{summary}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="border-t">
          <div className="mx-auto grid w-full max-w-6xl gap-14 px-8 py-24 lg:grid-cols-[2fr_3fr]">
            <div>
              <Eyebrow>How it works</Eyebrow>
              <SectionTitle>The LLM reads the evidence. It never picks the score.</SectionTitle>
              <div className="mt-8 space-y-5">
                {GUARDRAILS.map(({ title, body }) => (
                  <div key={title} className="border-l-2 border-foreground/40 pl-4">
                    <p className="text-sm font-medium">{title}</p>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{body}</p>
                  </div>
                ))}
              </div>
            </div>
            <ol className="relative space-y-0">
              {PIPELINE.map(({ title, body }, index) => (
                <li key={title} className="relative flex gap-6 pb-10 last:pb-0">
                  {index < PIPELINE.length - 1 && (
                    <span className="absolute top-8 left-[15px] h-[calc(100%-2rem)] w-px bg-border" aria-hidden />
                  )}
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-card font-mono text-xs text-muted-foreground">
                    {index + 1}
                  </span>
                  <div className="pt-1">
                    <h3 className="font-medium">{title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <ClosingCta
          title="See it on real leads."
          body="Browse scored leads, open any breakdown, or run a lead of your own against live data."
        />
      </main>

      <LandingFooter />
    </div>
  )
}
