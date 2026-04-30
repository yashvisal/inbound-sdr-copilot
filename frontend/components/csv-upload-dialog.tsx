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
import { analyzeLeadsWithOutreach } from "@/lib/api/client"
import type { LeadInput } from "@/lib/api/types"
import { useLeadStore } from "@/lib/store"

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

export function CsvUploadDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [file, setFile] = React.useState<File | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const setAnalyses = useLeadStore((state) => state.setAnalyses)

  function reset() {
    setFile(null)
    setError(null)
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
    try {
      const leads = await parseCsv(file)
      if (leads.length === 0) {
        throw new Error(
          "No valid rows found. Required columns: name, email, company, address, city, state."
        )
      }
      const analyses = await analyzeLeadsWithOutreach(leads)
      setAnalyses(analyses, { personalized: true })
      reset()
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.")
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>CSV Upload</DialogTitle>
          <DialogDescription>
            Upload a CSV with columns: name, email, company, address, city, state, and optionally country.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <div className="grid gap-1.5">
            <label htmlFor="csv-file" className="text-sm font-medium">
              CSV file
            </label>
            <Input
              id="csv-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) =>
                setFile(event.target.files?.[0] ?? null)
              }
              required
            />
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Upload failed</AlertTitle>
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
              {submitting ? "Analyzing..." : "Run Analysis"}
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
