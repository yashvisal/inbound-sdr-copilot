import type { LeadAnalysis, LeadInput } from "./types";

export function getAnalysisId(
  analysis: LeadAnalysis | { lead: LeadInput }
): string {
  return getLeadId(analysis.lead);
}

export function getLeadId(lead: LeadInput): string {
  return slugify(`${lead.email}-${lead.address}`);
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
