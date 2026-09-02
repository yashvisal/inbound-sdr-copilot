export type Priority = "High" | "Medium" | "Low";
export type Confidence = "High" | "Medium" | "Low";
export type CompanyFitLabel =
  | "Strong fit"
  | "Likely fit"
  | "Unclear fit"
  | "Poor fit";
export type AddressResolutionConfidence =
  | "High"
  | "Medium"
  | "Low"
  | "Unresolved";

export interface LeadInput {
  name: string;
  email: string;
  company: string;
  address: string;
  city: string;
  state: string;
  country: string;
}

export interface ScoreSection {
  score: number;
  max_score: number;
  reasons: string[];
}

/** One audited signal: the evidence and how many points it earned. */
export interface SignalAudit {
  raw_evidence: string;
  evidence_source: string | null;
  parsed_value: string;
  interpreted_bucket: string;
  confidence: Confidence | null;
  classifier: "openai_classifier" | "rule_fallback";
  score_contribution: number;
  max_contribution?: number | null;
}

export interface SignalFitBreakdown {
  score_breakdown: Record<string, number>;
  extraction_audit: Record<string, SignalAudit>;
}

export interface MarketSubScore {
  label: string;
  score: number;
  max_score: number;
  detail: string | null;
}

export interface MarketFitBreakdown {
  score_breakdown: Record<string, MarketSubScore>;
  dampener_penalty: number;
}

export interface ScoreBreakdown {
  market_fit: ScoreSection;
  company_fit: ScoreSection;
  property_fit: ScoreSection;
  // Breakdowns are optional: runs stored before they existed still render,
  // falling back to the reasons list.
  market_fit_breakdown?: MarketFitBreakdown | null;
  company_fit_breakdown?: SignalFitBreakdown | null;
  property_fit_breakdown?: SignalFitBreakdown | null;
  final_score: number;
  priority: Priority;
  company_fit_label: CompanyFitLabel;
  confidence: Confidence;
}

export interface MarketMetrics {
  geography_name?: string | null;
  population?: number | null;
  population_growth_rate?: number | null;
  median_gross_rent?: number | null;
  median_income?: number | null;
  renter_share?: number | null;
  housing_units?: number | null;
  vacancy_rate?: number | null;
  no_vehicle_household_share?: number | null;
  public_transit_commute_share?: number | null;
  walking_commute_share?: number | null;
  multifamily_share?: number | null;
  neighborhood_ratios_blended_with_tract?: boolean;
}

export interface SourceSnippet {
  source: string;
  title: string | null;
  url: string | null;
  snippet: string;
  /** ISO publish date, when the search provider reported one. */
  publish_date?: string | null;
}

export interface AddressResolution {
  confidence: AddressResolutionConfidence;
  method: string;
  input_address: string;
  matched_address: string | null;
  latitude: number | null;
  longitude: number | null;
  explanation: string | null;
}

export interface LeadAnalysis {
  lead: LeadInput;
  score: ScoreBreakdown;
  address_resolution?: AddressResolution | null;
  market_metrics: MarketMetrics;
  company_enrichment?: Record<string, unknown> | null;
  evidence: SourceSnippet[];
  missing_data: string[];
  why_this_lead: string[];
  sales_insights: string[];
  outreach_email: string;
  follow_ups: string[];
}

export interface OutreachGenerationResponse {
  sales_insights: string[];
  personalized_email: string;
}

export interface AnalyzeLeadsResponse {
  leads: LeadAnalysis[];
}

export type RunSource = "sample" | "community";

/** One analysis as stored for the shared dashboard. */
export interface StoredRun {
  id: string;
  source: RunSource;
  created_at: string;
  analysis: LeadAnalysis;
}

export interface StoredRunsResponse {
  runs: StoredRun[];
}

export interface QuotaResponse {
  runs_used: number;
  runs_limit: number;
  runs_remaining: number;
  period_end: string;
  enabled: boolean;
  per_visitor_daily_limit: number;
}

export type QuotaRejectionReason = "quota_exhausted" | "rate_limited";

/** Thrown when the backend rejects a run with HTTP 429. */
export class QuotaError extends Error {
  readonly reason: QuotaRejectionReason;

  constructor(reason: QuotaRejectionReason, message: string) {
    super(message);
    this.name = "QuotaError";
    this.reason = reason;
  }
}
