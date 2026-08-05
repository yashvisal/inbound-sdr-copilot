"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  Loader2,
  Plus,
  User,
} from "lucide-react"

import { AddLeadDialog } from "@/components/add-lead-dialog"
import { CsvUploadDialog } from "@/components/csv-upload-dialog"
import { SiteHeader } from "@/components/site-header"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { fetchStoredRuns } from "@/lib/api/client"
import type { LeadAnalysis } from "@/lib/api/types"
import { useQuota } from "@/lib/use-quota"
import sampleAnalyses from "@/lib/sample-analyses.json"
import {
  fromStoredRuns,
  toRunEntries,
  useLeadStore,
  type PendingRun,
  type RunEntry,
} from "@/lib/store"
import { useHasHydrated } from "@/lib/use-hydrated"

// Bundled at build time by backend/scripts/export_sample_analyses.py so the
// dashboard renders instantly, before (or without) any backend round trip.
const SAMPLE_RUNS: RunEntry[] = toRunEntries(
  sampleAnalyses.leads as unknown as LeadAnalysis[],
  "sample"
)

function getScoreColor(score: number) {
  if (score >= 80) return "bg-primary/10 text-foreground"
  if (score >= 50) return "bg-muted text-muted-foreground"
  return "bg-muted/50 text-muted-foreground/70"
}

export default function LeadsPage() {
  const runs = useLeadStore((state) => state.runs)
  const pending = useLeadStore((state) => state.pending)
  const mergeRuns = useLeadStore((state) => state.mergeRuns)
  const setRuns = useLeadStore((state) => state.setRuns)
  const addPending = useLeadStore((state) => state.addPending)

  const hydrated = useHasHydrated()
  const quota = useQuota()
  const [addOpen, setAddOpen] = React.useState(false)
  const [csvOpen, setCsvOpen] = React.useState(false)

  // Dev-only: /leads?preview=pending renders stuck pending rows so the loading
  // state can be styled without spending live runs. Cleared by a plain reload.
  React.useEffect(() => {
    if (process.env.NODE_ENV !== "development" || !hydrated) return
    if (!window.location.search.includes("preview=pending")) return
    addPending([
      {
        name: "Priya Raman",
        email: "p.raman@camdenliving.com",
        company: "Camden Property Trust",
        address: "Camden Music Row, 1310 Adams St",
        city: "Nashville",
        state: "TN",
        country: "US",
      },
      {
        name: "Marcus Webb",
        email: "m.webb@maac.com",
        company: "MAA",
        address: "MAA Park Estate, 960 Catbird Ct",
        city: "Memphis",
        state: "TN",
        country: "US",
      },
    ])
  }, [hydrated, addPending])

  // Seed with the bundled samples for instant paint, then replace with the
  // server's list: it holds the same seeded samples plus community runs, and
  // acts as the source of truth so server-side deletions propagate here.
  React.useEffect(() => {
    if (!hydrated) return
    mergeRuns(SAMPLE_RUNS, { personalized: true })

    let cancelled = false
    fetchStoredRuns()
      .then((body) => {
        if (cancelled) return
        // Rebuild from what the store holds now, not from the bundled snapshot:
        // a run that finished while this request was in flight must survive.
        // Server entries still win for ids they share.
        const byId = new Map(
          [
            ...SAMPLE_RUNS,
            ...useLeadStore.getState().runs,
            ...fromStoredRuns(body.runs),
          ].map((entry) => [entry.id, entry])
        )
        setRuns([...byId.values()], { personalized: true })
      })
      .catch(() => {
        // Backend asleep or unreachable: the bundled samples still render.
      })
    return () => {
      cancelled = true
    }
  }, [hydrated, mergeRuns, setRuns])

  const outOfRuns = quota.loaded && quota.enabled && quota.runs_remaining <= 0

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />

      <main className="mx-auto w-full max-w-7xl flex-1 px-8 py-10">
        <div className="flex flex-col gap-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-1">
              <h2 className="text-2xl font-semibold tracking-tight">Leads</h2>
              <p className="text-sm text-muted-foreground">
                Curated sample analyses plus live runs from other visitors,
                ranked by lead score.
              </p>
            </div>
            <div className="flex flex-col items-end gap-2.5">
              <div className="flex items-center gap-3">
                <QuotaMeter
                  remaining={quota.runs_remaining}
                  limit={quota.runs_limit}
                  ready={quota.loaded && quota.enabled}
                />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button disabled={outOfRuns}>
                      <Plus className="size-4" />
                      Add Lead
                      <ChevronDown className="size-3 opacity-60" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setAddOpen(true)}>
                      <User className="size-4" />
                      Single Lead
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setCsvOpen(true)}>
                      <FileSpreadsheet className="size-4" />
                      CSV Upload
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              {outOfRuns && (
                <p className="max-w-xs text-right text-xs text-muted-foreground">
                  <a
                    href="mailto:yashvisal@gmail.com?subject=Inbound%20SDR%20Copilot%20demo"
                    className="underline underline-offset-2"
                  >
                    Email me
                  </a>{" "}
                  for a live demo.
                </p>
              )}
            </div>
          </div>

          {!hydrated && <QueueSkeleton label="Loading dashboard..." />}

          {hydrated && (runs.length > 0 || pending.length > 0) && (
            <LeadTable runs={runs} pending={pending} />
          )}
        </div>
      </main>

      <AddLeadDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onRunSettled={quota.refresh}
      />
      <CsvUploadDialog
        open={csvOpen}
        onOpenChange={setCsvOpen}
        maxLeads={quota.perVisitorDailyLimit}
        onRunSettled={quota.refresh}
      />
    </div>
  )
}

/**
 * Remaining live runs, shown next to the Add Lead button at matching height.
 * Hidden until the quota is known (cached values appear immediately); no
 * entrance animation.
 */
function QuotaMeter({
  remaining,
  limit,
  ready,
}: {
  remaining: number
  limit: number
  ready: boolean
}) {
  const percentRemaining =
    limit > 0 ? Math.max(0, Math.min(100, (remaining / limit) * 100)) : 0

  if (!ready) return null

  return (
    <div
      className="hidden h-8 items-center gap-2.5 rounded-lg border bg-card/40 px-3 sm:flex"
      title={`${remaining} of ${limit} free monthly runs remaining`}
    >
      <div
        className="h-1.5 w-14 overflow-hidden rounded-full bg-foreground/12"
        aria-hidden
      >
        <div
          className="h-full rounded-full bg-foreground/85"
          style={{ width: `${percentRemaining}%` }}
        />
      </div>
      <span className="text-xs whitespace-nowrap text-muted-foreground">
        <span className="font-medium tabular-nums text-foreground">
          {remaining}
        </span>
        <span className="tabular-nums">/{limit}</span> free monthly runs left
      </span>
    </div>
  )
}

const PAGE_SIZE = 10

function LeadTable({
  runs,
  pending,
}: {
  runs: RunEntry[]
  pending: PendingRun[]
}) {
  const router = useRouter()
  const [page, setPage] = React.useState(0)

  // Pending rows only ever sit on the first page, above the ranked results.
  const pageCount = Math.max(1, Math.ceil(runs.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount - 1)
  const start = currentPage * PAGE_SIZE
  const visible = runs.slice(start, start + PAGE_SIZE)
  const visiblePending = currentPage === 0 ? pending : []

  return (
    <div className="space-y-3">
      {/* Height follows the rows on this page — no fixed frame, no scrolling.
          The first and last columns carry extra edge padding so content
          doesn't hug the table border. */}
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-16 pl-5 text-center">Rank</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Company</TableHead>
              <TableHead>Address</TableHead>
              <TableHead className="text-right">Lead Score</TableHead>
              <TableHead className="w-10 pr-4" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {/* In-flight leads sit at the top until their score arrives. The
                tinted band marks them as not-yet-real rows. */}
            {visiblePending.map(({ id, lead }) => (
              <TableRow
                key={`pending-${id}`}
                className="border-l-2 border-l-foreground/40 bg-muted/40 hover:bg-muted/40"
              >
                <TableCell className="pl-5 text-center text-muted-foreground/50">
                  —
                </TableCell>
                <TableCell className="font-medium text-muted-foreground">
                  {lead.name}
                  <div className="text-xs text-muted-foreground/60">
                    {lead.email}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {lead.company}
                </TableCell>
                <TableCell className="max-w-[260px] truncate text-muted-foreground">
                  {lead.address}, {lead.city}, {lead.state}
                </TableCell>
                <TableCell className="text-right">
                  {/* Same box as the score chip so the spinner lands on the
                      numbers' centre line rather than the cell's right edge. */}
                  <span className="inline-flex items-center justify-center rounded-md bg-muted px-2.5 py-1">
                    <Loader2
                      className="size-4 animate-spin text-foreground/70"
                      aria-label={`Analyzing ${lead.name}`}
                    />
                  </span>
                </TableCell>
                <TableCell className="pr-4" />
              </TableRow>
            ))}
            {visible.map((entry, index) => {
              const { lead, score } = entry.analysis
              const href = `/leads/${entry.id}`
              const rank = start + index + 1
              return (
                // The whole row is the click target; the name stays a real link
                // so keyboard users and "open in new tab" still work.
                <TableRow
                  key={entry.id}
                  className="group cursor-pointer"
                  onClick={() => router.push(href)}
                >
                  <TableCell className="pl-5 text-center font-semibold tabular-nums text-foreground">
                    {rank}
                  </TableCell>
                  <TableCell className="font-medium">
                    <Link
                      href={href}
                      className="hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {lead.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      {lead.email}
                    </div>
                  </TableCell>
                  <TableCell>{lead.company}</TableCell>
                  <TableCell className="max-w-[260px] truncate text-muted-foreground">
                    {lead.address}, {lead.city}, {lead.state}
                  </TableCell>
                  <TableCell className="text-right">
                    <span
                      className={`inline-flex items-center justify-center rounded-md px-2.5 py-1 text-sm font-medium tabular-nums ${getScoreColor(
                        score.final_score
                      )}`}
                    >
                      {score.final_score}
                    </span>
                  </TableCell>
                  <TableCell className="pr-4">
                    <ChevronRight
                      className="size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                      aria-hidden
                    />
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-between px-1">
          <p className="text-xs text-muted-foreground">
            Showing{" "}
            <span className="tabular-nums text-foreground">
              {start + 1}–{start + visible.length}
            </span>{" "}
            of <span className="tabular-nums">{runs.length}</span>
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage(currentPage - 1)}
              disabled={currentPage === 0}
            >
              <ChevronLeft className="size-4" />
              Previous
            </Button>
            <span className="px-1 text-xs tabular-nums text-muted-foreground">
              {currentPage + 1} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage(currentPage + 1)}
              disabled={currentPage >= pageCount - 1}
            >
              Next
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function QueueSkeleton({
  label = "Analyzing leads and generating outreach...",
}: {
  label?: string
}) {
  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-3 border-b px-4 py-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        {label}
      </div>
      <div className="grid gap-3 p-4">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="flex items-center justify-between gap-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-56" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-5 w-12 rounded-full" />
            <Skeleton className="h-6 w-12 rounded-md" />
          </div>
        ))}
      </div>
    </div>
  )
}
