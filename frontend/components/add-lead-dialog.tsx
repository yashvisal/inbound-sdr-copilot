"use client"

import * as React from "react"
import { Loader2 } from "lucide-react"

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
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [form, setForm] = React.useState<LeadInput>(emptyLead)
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const addAnalyses = useLeadStore((state) => state.addAnalyses)

  function update<K extends keyof LeadInput>(key: K, value: LeadInput[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function reset() {
    setForm(emptyLead)
    setError(null)
    setSubmitting(false)
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    onOpenChange(next)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const analyses = await analyzeLeadsWithOutreach([form])
      addAnalyses(analyses, { personalized: true })
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
          <DialogTitle>Add Lead</DialogTitle>
          <DialogDescription>
            Submit a single inbound lead and we&apos;ll enrich and score it.
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
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Analysis failed</AlertTitle>
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
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="size-4 animate-spin" />}
              {submitting ? "Analyzing..." : "Run Analysis"}
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
