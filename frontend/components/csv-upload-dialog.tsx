"use client"

import * as React from "react"
import Papa from "papaparse"
import { FileSpreadsheet, Loader2 } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { toast } from "sonner"

import { analyzeLeadsWithOutreach } from "@/lib/api/client"
import { QuotaError, type LeadInput } from "@/lib/api/types"
import { announceCompletedRuns } from "@/lib/run-toast"
import { toRunEntries, useLeadStore } from "@/lib/store"

const HEADER_ALIASES: Record<string, keyof LeadInput> = {
  name: "name",
  email: "email",
  email_address: "email",
  emailaddress: "email",
  company: "company",
  address: "address",
  property_address: "address",
  propertyaddress: "address",
  city: "city",
  state: "state",
  country: "country",
}

const APPROVAL_EMAIL = "yashvisal@gmail.com"

export function CsvUploadDialog({
  open,
  onOpenChange,
  maxLeads = 3,
  onRunSettled,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Rows allowed without approval; matches the per-visitor daily run limit. */
  maxLeads?: number
  /** Fired when a run finishes or fails, so the caller can refresh quota. */
  onRunSettled?: () => void
}) {
  const [file, setFile] = React.useState<File | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [errorTitle, setErrorTitle] = React.useState("Upload failed")
  const [quotaBlocked, setQuotaBlocked] = React.useState(false)
  const mergeRuns = useLeadStore((state) => state.mergeRuns)
  const addPending = useLeadStore((state) => state.addPending)
  const removePending = useLeadStore((state) => state.removePending)

  function reset() {
    setFile(null)
    setError(null)
    setErrorTitle("Upload failed")
    setQuotaBlocked(false)
    setSubmitting(false)
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    onOpenChange(next)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!file) return
    setSubmitting(true)
    setError(null)
    let needsApproval = false
    try {
      const leads = await parseCsv(file)
      if (leads.length === 0) {
        throw new Error(
          "No valid rows found. Required columns: name, email, company, address, city, state."
        )
      }
      // Caught here rather than server-side so an oversized file gets the
      // approval message instead of a bare rate-limit rejection.
      if (leads.length > maxLeads) {
        needsApproval = true
        throw new Error(
          `This file has ${leads.length} leads. Up to ${maxLeads} can be analyzed ` +
            `without approval — email ${APPROVAL_EMAIL} to run a larger batch.`
        )
      }
      // Parsing and limits are validated first; once they pass, close the
      // dialog and let the rows analyze in the background.
      const pendingIds = addPending(leads)
      reset()
      onOpenChange(false)

      analyzeLeadsWithOutreach(leads)
        .then((analyses) => {
          const entries = toRunEntries(
            analyses,
            "community",
            new Date().toISOString()
          )
          mergeRuns(entries, { personalized: true })
          announceCompletedRuns(entries)
        })
        .catch((err) => {
          toast.error(
            err instanceof QuotaError
              ? "Live runs unavailable"
              : "Analysis failed",
            {
              description:
                err instanceof Error ? err.message : "Something went wrong.",
            }
          )
        })
        .finally(() => {
          removePending(pendingIds)
          onRunSettled?.()
        })
      return
    } catch (err) {
      const soft = needsApproval || err instanceof QuotaError
      setQuotaBlocked(soft)
      setErrorTitle(
        needsApproval
          ? "Approval needed"
          : err instanceof QuotaError
            ? "Live runs unavailable"
            : "Upload failed"
      )
      setError(err instanceof Error ? err.message : "Something went wrong.")
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>CSV upload</DialogTitle>
          <DialogDescription>
            Up to {maxLeads} leads per file.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <Input
            id="csv-file"
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
          <div className="rounded-lg border bg-muted/30 px-3 py-2.5">
            <p className="text-xs font-medium text-muted-foreground">
              Required columns
            </p>
            <p className="mt-1 font-mono text-xs text-foreground/80">
              name, email, company, address, city, state
            </p>
            <p className="mt-1.5 text-xs text-muted-foreground/70">
              country optional, defaults to US
            </p>
          </div>
          {error && (
            <Alert variant={quotaBlocked ? "default" : "destructive"}>
              <AlertTitle>{errorTitle}</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!file || submitting}>
              {submitting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="size-4" />
              )}
              {submitting ? "Analyzing..." : "Run analysis"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function parseCsv(file: File): Promise<LeadInput[]> {
  return new Promise((resolve, reject) => {
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      transformHeader: (header) =>
        header.trim().toLowerCase().replace(/\s+/g, "_"),
      complete: (results) => {
        if (results.errors.length > 0) {
          reject(new Error(results.errors[0].message))
          return
        }
        const rows = results.data
          .map(normalizeRow)
          .filter((row): row is LeadInput => row !== null)
        resolve(rows)
      },
      error: (err) => reject(err),
    })
  })
}

function normalizeRow(raw: Record<string, string>): LeadInput | null {
  const lead: Partial<LeadInput> = {}
  for (const [key, value] of Object.entries(raw)) {
    const target = HEADER_ALIASES[key]
    if (!target) continue
    const trimmed = (value ?? "").trim()
    if (trimmed) lead[target] = trimmed
  }
  if (
    !lead.name ||
    !lead.email ||
    !lead.company ||
    !lead.address ||
    !lead.city ||
    !lead.state
  ) {
    return null
  }
  return {
    name: lead.name,
    email: lead.email,
    company: lead.company,
    address: lead.address,
    city: lead.city,
    state: lead.state,
    country: lead.country ?? "US",
  }
}
