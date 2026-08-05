import {
  QuotaError,
  type AnalyzeLeadsResponse,
  type LeadAnalysis,
  type LeadInput,
  type OutreachGenerationResponse,
  type QuotaRejectionReason,
  type QuotaResponse,
  type StoredRunsResponse,
} from "./types";

const baseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

async function request<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 429) throw await toQuotaError(res);
    const text = await res.text().catch(() => "");
    throw new Error(
      `Request to ${path} failed: ${res.status}${text ? ` - ${text}` : ""}`
    );
  }
  return (await res.json()) as T;
}

async function toQuotaError(res: Response): Promise<Error> {
  try {
    const body = (await res.json()) as {
      reason?: QuotaRejectionReason;
      message?: string;
    };
    return new QuotaError(
      body.reason ?? "quota_exhausted",
      body.message ?? "This demo is out of free live runs."
    );
  } catch {
    return new QuotaError(
      "quota_exhausted",
      "This demo is out of free live runs."
    );
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`);
  if (!res.ok) throw new Error(`Request to ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export async function analyzeLeads(
  leads: LeadInput[]
): Promise<LeadAnalysis[]> {
  const body = await request<AnalyzeLeadsResponse>("/api/leads/analyze", {
    leads,
  });
  return body.leads;
}

export async function analyzeLeadsWithOutreach(
  leads: LeadInput[]
): Promise<LeadAnalysis[]> {
  const analyses = await analyzeLeads(leads);
  const enriched: LeadAnalysis[] = [];
  for (const analysis of analyses) {
    const outreach = await generateOutreach(analysis);
    enriched.push({
      ...analysis,
      sales_insights: outreach.sales_insights,
      outreach_email: outreach.personalized_email,
    });
  }
  return enriched;
}

export async function generateOutreach(
  analysis: LeadAnalysis
): Promise<OutreachGenerationResponse> {
  return request<OutreachGenerationResponse>("/api/leads/generate-outreach", {
    lead: analysis.lead,
    analysis,
  });
}

/** Runs stored server-side: curated samples plus other visitors' live runs. */
export async function fetchStoredRuns(): Promise<StoredRunsResponse> {
  return get<StoredRunsResponse>("/api/leads");
}

export async function fetchQuota(): Promise<QuotaResponse> {
  return get<QuotaResponse>("/api/quota");
}
