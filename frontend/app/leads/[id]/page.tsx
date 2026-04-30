"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import {
  AlertCircle,
  ArrowLeft,
  Bug,
  Building2,
  CheckCircle2,
  Copy,
  Lightbulb,
  Loader2,
  Mail,
  MapPin,
  RefreshCw,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { generateOutreach } from "@/lib/api/client"
import { getAnalysisId } from "@/lib/api/id"
import type { LeadAnalysis } from "@/lib/api/types"
import { useLeadStore } from "@/lib/store"
import { useHasHydrated } from "@/lib/use-hydrated"

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params?.id ?? ""

  const analysis = useLeadStore((state) =>
    state.analyses.find((entry) => getAnalysisId(entry) === id)
  )
  const personalized = useLeadStore((state) =>
    state.personalizedIds.includes(id)
  )
  const updateAnalysis = useLeadStore((state) => state.updateAnalysis)
  const markPersonalized = useLeadStore((state) => state.markPersonalized)

  const hydrated = useHasHydrated()

  if (!hydrated) {
    return <DetailShell><DetailSkeleton /></DetailShell>
  }

  if (!analysis) {
    return (
      <DetailShell>
        <MissingState />
      </DetailShell>
    )
  }

  return (
    <DetailShell>
      <LeadDetail
        analysis={analysis}
        id={id}
        alreadyPersonalized={personalized}
        onUpdate={(patch) => updateAnalysis(id, patch)}
        onMarkPersonalized={() => markPersonalized(id)}
      />
    </DetailShell>
  )
}

function LeadDetail({
  analysis,
  id,
  alreadyPersonalized,
  onUpdate,
  onMarkPersonalized,
}: {
  analysis: LeadAnalysis
  id: string
  alreadyPersonalized: boolean
  onUpdate: (patch: Partial<LeadAnalysis>) => void
  onMarkPersonalized: () => void
}) {
  const { lead, score } = analysis
  const [generating, setGenerating] = React.useState(!alreadyPersonalized)
  const [outreachError, setOutreachError] = React.useState<string | null>(null)
  const autoGenerateStarted = React.useRef(alreadyPersonalized)

  const runGenerate = React.useCallback(async () => {
    setGenerating(true)
    setOutreachError(null)
    try {
      const result = await generateOutreach(analysis)
      onUpdate({
        outreach_email: result.personalized_email,
        sales_insights: result.sales_insights,
      })
      onMarkPersonalized()
    } catch (err) {
      setOutreachError(
        err instanceof Error
          ? err.message
          : "Could not generate personalized outreach."
      )
    } finally {
      setGenerating(false)
    }
  }, [analysis, onUpdate, onMarkPersonalized])

  React.useEffect(() => {
    if (alreadyPersonalized || autoGenerateStarted.current) return
    autoGenerateStarted.current = true
    const handle = setTimeout(() => {
      void runGenerate()
    }, 0)
    return () => clearTimeout(handle)
  }, [alreadyPersonalized, runGenerate])

  const addressNote = analysis.address_resolution
  const showAddressNote =
    addressNote &&
    addressNote.confidence !== "High" &&
    addressNote.explanation

  return (
    <div className="space-y-10">
      <section className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-semibold tracking-tight">
              {lead.name}
            </h1>
            <Badge variant="outline">{score.confidence} confidence</Badge>
          </div>
          <p className="text-lg text-muted-foreground">{lead.company}</p>
        </div>
        <div className="text-left md:text-right">
          <div className="text-5xl font-bold tabular-nums">
            {score.final_score}
          </div>
          <p className="text-sm text-muted-foreground">Lead Score</p>
        </div>
      </section>

      <section className="flex flex-wrap gap-x-6 gap-y-3 text-sm">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Mail className="size-4" />
          <span>{lead.email}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Building2 className="size-4" />
          <span>{lead.company}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <MapPin className="size-4" />
          <span>
            {lead.address}, {lead.city}, {lead.state}
          </span>
        </div>
      </section>

      {showAddressNote && (
        <Alert>
          <AlertTitle>Address resolution: {addressNote.confidence}</AlertTitle>
          <AlertDescription>{addressNote.explanation}</AlertDescription>
        </Alert>
      )}

      {analysis.why_this_lead.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Why This Lead</h2>
          <ul className="space-y-2">
            {analysis.why_this_lead.map((reason) => (
              <li key={reason} className="flex items-start gap-2.5">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-foreground/70" />
                <span className="text-muted-foreground">{reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-6 border-t pt-8">
        <h2 className="text-lg font-semibold">Score Breakdown</h2>
        <div className="grid gap-8 md:grid-cols-3">
          <ScoreBlock title="Market Fit" section={score.market_fit} />
          <ScoreBlock title="Company Fit" section={score.company_fit} />
          <ScoreBlock title="Property Fit" section={score.property_fit} />
        </div>
      </section>

      <section className="space-y-4 border-t pt-8">
        <h2 className="text-lg font-semibold">Sales Insights</h2>
        {generating && analysis.sales_insights.length === 0 ? (
          <InsightsSkeleton />
        ) : (
          <div className="grid gap-x-8 gap-y-3 md:grid-cols-2">
            {analysis.sales_insights.map((insight, index) => (
              <div key={insight} className="flex items-start gap-3">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
                  {index + 1}
                </span>
                <span className="text-sm text-muted-foreground">
                  {insight}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4 border-t pt-8">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold">Personalized Outreach</h2>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={runGenerate}
              disabled={generating}
            >
              {generating ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <RefreshCw className="size-3" />
              )}
              {generating ? "Generating..." : "Regenerate"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                navigator.clipboard.writeText(analysis.outreach_email)
              }
              disabled={generating || !analysis.outreach_email}
            >
              <Copy className="size-3" />
              Copy
            </Button>
          </div>
        </div>
        {outreachError && (
          <Alert variant="destructive">
            <AlertTitle>Outreach generation failed</AlertTitle>
            <AlertDescription>{outreachError}</AlertDescription>
          </Alert>
        )}
        <div className="rounded-xl border bg-muted/30 p-5">
          {generating && !analysis.outreach_email ? (
            <OutreachSkeleton />
          ) : (
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-muted-foreground">
              {analysis.outreach_email || "No outreach available yet."}
            </pre>
          )}
        </div>
      </section>

      {analysis.missing_data.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2 text-muted-foreground">
            <AlertCircle className="size-4" />
            <span className="text-sm font-medium">Data Limitations</span>
          </div>
          <ul className="list-disc space-y-1 pl-6">
            {analysis.missing_data.map((item) => (
              <li key={item} className="text-sm text-muted-foreground">
                {item}
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="flex items-center justify-between border-t pt-4 text-xs text-muted-foreground/70">
        <span>Based on {analysis.evidence.length} data points</span>
        <span>ID: {id}</span>
      </footer>
    </div>
  )
}

function ScoreBlock({
  title,
  section,
}: {
  title: string
  section: { score: number; max_score: number; reasons: string[] }
}) {
  const percentage =
    section.max_score > 0 ? (section.score / section.max_score) * 100 : 0
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{title}</span>
        <span className="text-lg font-semibold tabular-nums">
          {section.score}
          <span className="text-sm font-normal text-muted-foreground">
            /{section.max_score}
          </span>
        </span>
      </div>
      <Progress value={percentage} className="h-1.5" />
      <ul className="space-y-1.5">
        {section.reasons.slice(0, 3).map((reason) => (
          <li
            key={reason}
            className="flex items-start gap-2 text-sm text-muted-foreground"
          >
            <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-foreground/50" />
            <span>{reason}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function DetailShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-16 items-center justify-between border-b px-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <Link href="/">
              <ArrowLeft className="size-4" />
            </Link>
          </Button>
          <Link
            href="/"
            className="text-lg font-semibold tracking-tight transition-opacity hover:opacity-80"
          >
            Inbound SDR Copilot
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Lightbulb className="size-4" />
            Feature Request
          </Button>
          <Button variant="outline" size="sm">
            <Bug className="size-4" />
            Report Bug
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-8 py-10">
        {children}
      </main>
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-10">
      <div className="flex items-start justify-between">
        <div className="space-y-3">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-5 w-40" />
        </div>
        <Skeleton className="h-12 w-16" />
      </div>
      <div className="grid gap-8 md:grid-cols-3">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    </div>
  )
}

function InsightsSkeleton() {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-5 w-full" />
      ))}
    </div>
  )
}

function OutreachSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  )
}

function MissingState() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="flex size-10 items-center justify-center rounded-full bg-muted">
        <AlertCircle className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="font-medium">Lead not found in this session</p>
        <p className="max-w-md text-sm text-muted-foreground">
          The lead queue lives in your browser session. Reload sample data or
          add a lead to start a fresh queue.
        </p>
      </div>
      <Button asChild>
        <Link href="/">Back to Leads</Link>
      </Button>
    </div>
  )
}
