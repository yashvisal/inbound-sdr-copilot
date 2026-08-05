"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import {
  AlertCircle,
  Building2,
  CheckCircle2,
  ChevronRight,
  Copy,
  Loader2,
  Mail,
  MapPin,
  RefreshCw,
} from "lucide-react"

import { SiteHeader } from "@/components/site-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchStoredRuns, generateOutreach } from "@/lib/api/client"
import type {
  LeadAnalysis,
  MarketFitBreakdown,
  ScoreSection,
  SignalAudit,
  SignalFitBreakdown,
} from "@/lib/api/types"
import { fromStoredRuns, useLeadStore } from "@/lib/store"
import { useHasHydrated } from "@/lib/use-hydrated"

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params?.id ?? ""

  const analysis = useLeadStore(
    (state) => state.runs.find((entry) => entry.id === id)?.analysis
  )
  const personalized = useLeadStore((state) =>
    state.personalizedIds.includes(id)
  )
  const updateAnalysis = useLeadStore((state) => state.updateAnalysis)
  const markPersonalized = useLeadStore((state) => state.markPersonalized)

  const mergeRuns = useLeadStore((state) => state.mergeRuns)
  const hydrated = useHasHydrated()
  const [fetchingRun, setFetchingRun] = React.useState(false)
  const fetchAttempted = React.useRef(false)

  // Shared links land here with an empty session store, so pull the run set
  // from the backend once before deciding the lead is missing.
  React.useEffect(() => {
    if (!hydrated || analysis || fetchAttempted.current) return
    fetchAttempted.current = true
    setFetchingRun(true)
    fetchStoredRuns()
      .then((body) => mergeRuns(fromStoredRuns(body.runs)))
      .catch(() => undefined)
      .finally(() => setFetchingRun(false))
  }, [hydrated, analysis, mergeRuns])

  if (!hydrated || (!analysis && fetchingRun)) {
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
        alreadyPersonalized={personalized}
        onUpdate={(patch) => updateAnalysis(id, patch)}
        onMarkPersonalized={() => markPersonalized(id)}
      />
    </DetailShell>
  )
}

function LeadDetail({
  analysis,
  alreadyPersonalized,
  onUpdate,
  onMarkPersonalized,
}: {
  analysis: LeadAnalysis
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
          <h1 className="text-3xl font-semibold tracking-tight">{lead.name}</h1>
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

      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Score Breakdown</h2>
          <p className="text-sm text-muted-foreground">
            Select a component to see every signal, its points, and the evidence
            behind it.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <ScoreCard
            title="Location Fit"
            section={score.market_fit}
            signals={marketSignals(score.market_fit_breakdown)}
            note={dampenerNote(score.market_fit_breakdown)}
          />
          <ScoreCard
            title="Company Fit"
            section={score.company_fit}
            signals={auditSignals(score.company_fit_breakdown, SIGNAL_LABELS)}
          />
          <ScoreCard
            title="Property Fit"
            section={score.property_fit}
            signals={auditSignals(score.property_fit_breakdown, SIGNAL_LABELS)}
          />
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
    </div>
  )
}

/** A normalized row under a score section: one signal, its points, its evidence. */
interface SignalRow {
  key: string
  label: string
  score: number
  maxScore: number | null
  /** Bucket the classifier landed on, e.g. "Very High" / "Multifamily". */
  bucket?: string
  /** Short annotation of the values behind the score. */
  detail?: string | null
  evidence?: SignalAudit
}

const SIGNAL_LABELS: Record<string, string> = {
  leasing_volume: "Leasing volume",
  operational_complexity: "Operational complexity",
  product_fit: "Product fit",
  property_type: "Property type",
  property_scale: "Property scale",
  leasing_activity: "Leasing activity",
}

function marketSignals(
  breakdown: MarketFitBreakdown | null | undefined
): SignalRow[] {
  if (!breakdown) return []
  return Object.entries(breakdown.score_breakdown).map(([key, sub]) => ({
    key,
    label: sub.label,
    score: sub.score,
    maxScore: sub.max_score,
    detail: sub.detail,
  }))
}

function dampenerNote(
  breakdown: MarketFitBreakdown | null | undefined
): string | null {
  if (!breakdown?.dampener_penalty) return null
  return `−${breakdown.dampener_penalty} dampener applied for a mixed-use or commercial pattern.`
}

function auditSignals(
  breakdown: SignalFitBreakdown | null | undefined,
  labels: Record<string, string>
): SignalRow[] {
  if (!breakdown) return []
  return Object.entries(breakdown.extraction_audit).map(([key, audit]) => ({
    key,
    label: labels[key] ?? key,
    score: breakdown.score_breakdown[key] ?? audit.score_contribution,
    maxScore: audit.max_contribution ?? null,
    bucket: audit.interpreted_bucket,
    evidence: audit,
  }))
}

/** Highlights for the card face: what carried the score and what held it back. */
function summarize(signals: SignalRow[]) {
  const ranked = signals.filter((signal) => signal.maxScore)
  if (ranked.length === 0) return null
  const ratio = (signal: SignalRow) => signal.score / (signal.maxScore || 1)
  const strongest = ranked.reduce((best, signal) =>
    ratio(signal) > ratio(best) ? signal : best
  )
  // Never report the same signal as both highlights: when ties make the
  // strongest also the largest gap, fall through to the next-biggest gap.
  const gaps = ranked.filter(
    (signal) => (signal.maxScore ?? 0) - signal.score > 0 && signal !== strongest
  )
  const weakest = gaps.length
    ? gaps.reduce((worst, signal) =>
        (signal.maxScore ?? 0) - signal.score >
        (worst.maxScore ?? 0) - worst.score
          ? signal
          : worst
      )
    : null
  return { strongest, weakest }
}

function ScoreCard({
  title,
  section,
  signals,
  note,
}: {
  title: string
  section: ScoreSection
  signals: SignalRow[]
  note?: string | null
}) {
  const percentage =
    section.max_score > 0 ? (section.score / section.max_score) * 100 : 0
  const summary = summarize(signals)

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          className="group w-full space-y-3 rounded-xl border p-5 text-left transition-colors hover:border-foreground/25 hover:bg-muted/30 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
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

          {summary ? (
            // Both rows always render — a missing gap becomes "N/A" so cards
            // keep the same height instead of shifting.
            <dl className="space-y-1 text-xs text-muted-foreground">
              <SummaryLine
                term="Strongest"
                signal={summary.strongest}
                highlight
              />
              <SummaryLine term="Biggest gap" signal={summary.weakest} />
            </dl>
          ) : (
            // Runs stored before breakdowns existed have reasons only.
            <p className="line-clamp-2 text-xs text-muted-foreground">
              {section.reasons[0]}
            </p>
          )}

          <span className="flex items-center gap-1 text-xs text-muted-foreground transition-colors group-hover:text-foreground">
            View breakdown
            <ChevronRight className="size-3" />
          </span>
        </button>
      </DialogTrigger>

      {/* Header stays pinned and only the signal list scrolls, so the close
          button can never sit on top of (or scroll away from) the content. */}
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="shrink-0 gap-3 border-b px-6 pt-6 pb-4">
          {/* pr-8 keeps the score clear of the close button. */}
          <DialogTitle className="flex items-baseline justify-between gap-4 pr-8">
            <span>{title}</span>
            <span className="text-lg tabular-nums">
              {section.score}
              <span className="text-sm font-normal text-muted-foreground">
                /{section.max_score}
              </span>
            </span>
          </DialogTitle>
          <Progress value={percentage} className="h-1.5" />
          <DialogDescription>
            {signals.length > 0
              ? "Each signal below shows the bucket it landed in and the evidence behind it."
              : "Scoring notes for this run."}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
          {signals.length > 0 ? (
            <div className="divide-y divide-border/60">
              {signals.map((signal) => (
                <SignalRowItem key={signal.key} signal={signal} />
              ))}
            </div>
          ) : (
            <ul className="space-y-1.5">
              {section.reasons.map((reason, index) => (
                <li
                  key={index}
                  className="flex items-start gap-2 text-sm text-muted-foreground"
                >
                  <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-foreground/50" />
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          )}

          {note && <p className="text-xs text-muted-foreground">{note}</p>}

          {signals.length > 0 && section.reasons.length > 0 && (
            <Disclosure summary="Scoring notes">
              <ul className="space-y-1.5">
                {section.reasons.map((reason, index) => (
                  <li key={index} className="text-xs text-muted-foreground">
                    {reason}
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SummaryLine({
  term,
  signal,
  highlight = false,
}: {
  term: string
  /** Null when there is nothing to report, e.g. every signal already maxed. */
  signal: SignalRow | null
  highlight?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="shrink-0">{term}</dt>
      <dd
        className={`truncate ${highlight ? "text-foreground/80" : "text-muted-foreground"}`}
      >
        {signal ? (
          <>
            {signal.label}{" "}
            <span className="tabular-nums">
              {signal.score}/{signal.maxScore}
            </span>
          </>
        ) : (
          "N/A"
        )}
      </dd>
    </div>
  )
}

function SignalRowItem({ signal }: { signal: SignalRow }) {
  const percentage =
    signal.maxScore && signal.maxScore > 0
      ? Math.min(100, (signal.score / signal.maxScore) * 100)
      : 0
  const evidence = signal.evidence

  return (
    <div className="space-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-sm font-medium">{signal.label}</span>
          {signal.bucket && (
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {signal.bucket}
            </span>
          )}
          {signal.detail && (
            <span className="text-xs text-muted-foreground">
              {signal.detail}
            </span>
          )}
        </div>
        <span className="text-sm tabular-nums text-muted-foreground">
          <span className="font-medium text-foreground">{signal.score}</span>
          {signal.maxScore !== null && `/${signal.maxScore}`}
        </span>
      </div>

      {signal.maxScore !== null && (
        <div className="h-1 w-full overflow-hidden rounded-full bg-foreground/10">
          <div
            className="h-full rounded-full bg-foreground/60"
            style={{ width: `${percentage}%` }}
          />
        </div>
      )}

      {evidence && (
        <Disclosure summary="Evidence">
          <div className="space-y-2">
            <p className="rounded-md bg-muted/50 p-2.5 font-mono text-xs leading-relaxed text-muted-foreground">
              {evidence.raw_evidence}
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>
                Parsed:{" "}
                <span className="text-foreground/80">
                  {evidence.parsed_value}
                </span>
              </span>
              {evidence.evidence_source && (
                <span>Source: {evidence.evidence_source}</span>
              )}
              {evidence.confidence && (
                <span>Confidence: {evidence.confidence}</span>
              )}
              <span>
                {evidence.classifier === "openai_classifier"
                  ? "LLM extraction"
                  : "Rule fallback"}
              </span>
            </div>
          </div>
        </Disclosure>
      )}
    </div>
  )
}

/** Native disclosure so evidence stays collapsed without extra dependencies. */
function Disclosure({
  summary,
  children,
}: {
  summary: string
  children: React.ReactNode
}) {
  return (
    <details className="group">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight className="size-3 transition-transform group-open:rotate-90" />
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}

function DetailShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader showBack />
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
        <p className="font-medium">Lead not found</p>
        <p className="max-w-md text-sm text-muted-foreground">
          This analysis is no longer on the dashboard. Older community runs are
          rotated out as new ones come in.
        </p>
      </div>
      <Button asChild>
        <Link href="/leads">Back to Leads</Link>
      </Button>
    </div>
  )
}
