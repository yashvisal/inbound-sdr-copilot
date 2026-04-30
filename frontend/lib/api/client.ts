import type {
  AnalyzeLeadsResponse,
  LeadAnalysis,
  LeadInput,
  OutreachGenerationResponse,
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
    const text = await res.text().catch(() => "");
    throw new Error(
      `Request to ${path} failed: ${res.status}${text ? ` - ${text}` : ""}`
    );
  }
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
