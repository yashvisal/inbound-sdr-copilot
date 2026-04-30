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

export interface ScoreBreakdown {
  market_fit: ScoreSection;
  company_fit: ScoreSection;
  property_fit: ScoreSection;
  final_score: number;
  priority: Priority;
  company_fit_label: CompanyFitLabel;
  confidence: Confidence;
}

export interface SourceSnippet {
  source: string;
  title: string | null;
  url: string | null;
  snippet: string;
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
  market_metrics: Record<string, unknown>;
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
