"use client"

import * as React from "react"

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

const emptyLead: LeadInput = {
  name: "",
  email: "",
  company: "",
  address: "",
  city: "",
  state: "",
  country: "US",
}

export function AddLeadDialog({
  open,
  onOpenChange,
  onRunSettled,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Fired when a run finishes or fails, so the caller can refresh quota. */
  onRunSettled?: () => void
}) {
  const [form, setForm] = React.useState<LeadInput>(emptyLead)
  const mergeRuns = useLeadStore((state) => state.mergeRuns)
  const addPending = useLeadStore((state) => state.addPending)
  const removePending = useLeadStore((state) => state.removePending)

  function update<K extends keyof LeadInput>(key: K, value: LeadInput[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function reset() {
    setForm(emptyLead)
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    onOpenChange(next)
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()

    // Close the dialog right away; the lead shows up in the table as a
    // pending row while the analysis runs in the background.
    const lead = form
    const pendingIds = addPending([lead])
    reset()
    onOpenChange(false)

    analyzeLeadsWithOutreach([lead])
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
          err instanceof QuotaError ? "Live runs unavailable" : "Analysis failed",
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
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Lead</DialogTitle>
          <DialogDescription>
            Submit a single inbound lead and we&apos;ll enrich and score it.
            This is a public demo — runs are visible to other visitors, so
            please don&apos;t enter real contact details.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <Field
            id="lead-name"
            label="Name"
            value={form.name}
            onChange={(value) => update("name", value)}
            placeholder="Maya Chen"
          />
          <Field
            id="lead-email"
            label="Email"
            type="email"
            value={form.email}
            onChange={(value) => update("email", value)}
            placeholder="maya@harborresidential.com"
          />
          <Field
            id="lead-company"
            label="Company"
            value={form.company}
            onChange={(value) => update("company", value)}
            placeholder="Harbor Residential"
          />
          <Field
            id="lead-address"
            label="Property Address"
            value={form.address}
            onChange={(value) => update("address", value)}
            placeholder="The Morrison Apartments, 123 Main St"
          />
          <div className="grid grid-cols-2 gap-3">
            <Field
              id="lead-city"
              label="City"
              value={form.city}
              onChange={(value) => update("city", value)}
              placeholder="Austin"
            />
            <Field
              id="lead-state"
              label="State"
              value={form.state}
              onChange={(value) => update("state", value)}
              placeholder="TX"
            />
          </div>
          <Field
            id="lead-country"
            label="Country"
            value={form.country}
            onChange={(value) => update("country", value)}
            placeholder="US"
          />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit">
              Run analysis
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  placeholder?: string
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        required
      />
    </div>
  )
}
