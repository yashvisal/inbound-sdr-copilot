"use client"

import * as React from "react"
import Link from "next/link"
import {
  Bug,
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  Lightbulb,
  Loader2,
  Plus,
  Sparkles,
  User,
} from "lucide-react"

import { AddLeadDialog } from "@/components/add-lead-dialog"
import { CsvUploadDialog } from "@/components/csv-upload-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { analyzeLeadsWithOutreach } from "@/lib/api/client"
import { getAnalysisId } from "@/lib/api/id"
import type { LeadAnalysis } from "@/lib/api/types"
import { sampleLeads } from "@/lib/sample-leads"
import { useLeadStore } from "@/lib/store"
import { useHasHydrated } from "@/lib/use-hydrated"

function getScoreColor(score: number) {
  if (score >= 80) return "bg-primary/10 text-foreground"
  if (score >= 50) return "bg-muted text-muted-foreground"
  return "bg-muted/50 text-muted-foreground/70"
}

export default function Home() {
  const analyses = useLeadStore((state) => state.analyses)
  const status = useLeadStore((state) => state.status)
  const error = useLeadStore((state) => state.error)
  const setAnalyses = useLeadStore((state) => state.setAnalyses)
  const setStatus = useLeadStore((state) => state.setStatus)

  const hydrated = useHasHydrated()
  const [addOpen, setAddOpen] = React.useState(false)
  const [csvOpen, setCsvOpen] = React.useState(false)

  async function loadSampleData() {
    setStatus("loading")
    try {
      const results = await analyzeLeadsWithOutreach(sampleLeads)
      setAnalyses(results, { personalized: true })
    } catch (err) {
      setStatus(
        "error",
        err instanceof Error ? err.message : "Failed to load sample data."
      )
    }
  }

  const isLoading = status === "loading"
  const showEmpty = hydrated && analyses.length === 0 && !isLoading

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-16 items-center justify-between border-b px-6">
        <h1 className="text-lg font-semibold tracking-tight">
          Inbound SDR Copilot
        </h1>
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

      <main className="mx-auto w-full max-w-7xl flex-1 px-8 py-10">
        <div className="flex flex-col gap-8">
          <div className="flex items-center justify-between">
            <h2 className="text-2xl font-semibold tracking-tight">Leads</h2>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button>
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

          {error && (
            <Alert variant="destructive">
              <AlertTitle>Could not run analysis</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {isLoading && <QueueSkeleton />}

          {showEmpty && (
            <EmptyState onLoadSample={loadSampleData} />
          )}

          {hydrated && analyses.length > 0 && !isLoading && (
            <LeadTable analyses={analyses} />
          )}
        </div>
      </main>

      <AddLeadDialog open={addOpen} onOpenChange={setAddOpen} />
      <CsvUploadDialog open={csvOpen} onOpenChange={setCsvOpen} />
    </div>
  )
}

function LeadTable({ analyses }: { analyses: LeadAnalysis[] }) {
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Company</TableHead>
            <TableHead>Address</TableHead>
            <TableHead className="text-right">Lead Score</TableHead>
            <TableHead className="w-8" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {analyses.map((analysis) => {
            const id = getAnalysisId(analysis)
            const { lead, score } = analysis
            return (
              <TableRow key={id} className="group cursor-pointer">
                <TableCell className="font-medium">
                  <Link href={`/leads/${id}`} className="hover:underline">
                    {lead.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {lead.email}
                </TableCell>
                <TableCell>{lead.company}</TableCell>
                <TableCell className="max-w-[220px] truncate text-muted-foreground">
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
                <TableCell>
                  <Link
                    href={`/leads/${id}`}
                    aria-label={`View ${lead.name}`}
                  >
                    <ChevronRight className="size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </Link>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function QueueSkeleton() {
  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-3 border-b px-4 py-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Analyzing leads and generating outreach...
      </div>
      <div className="grid gap-3 p-4">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="flex items-center justify-between gap-4"
          >
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

function EmptyState({ onLoadSample }: { onLoadSample: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-lg border border-dashed py-16 text-center">
      <div className="flex size-10 items-center justify-center rounded-full bg-muted">
        <Sparkles className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="font-medium">No leads yet</p>
        <p className="text-sm text-muted-foreground">
          Load a curated sample queue or add your own leads to start scoring.
        </p>
      </div>
      <Button onClick={onLoadSample}>
        <Sparkles className="size-4" />
        Load Sample Data
      </Button>
    </div>
  )
}
