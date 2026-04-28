from typing import Literal

from pydantic import BaseModel, EmailStr, Field


Priority = Literal["High", "Medium", "Low"]
CompanyFitLabel = Literal["Strong fit", "Likely fit", "Unclear fit", "Poor fit"]
AddressResolutionConfidence = Literal["High", "Medium", "Low", "Unresolved"]


class LeadInput(BaseModel):
    name: str = Field(..., examples=["Jordan Lee"])
    email: EmailStr = Field(..., examples=["jordan@examplepm.com"])
    company: str = Field(..., examples=["Example Property Management"])
    address: str = Field(..., examples=["123 Main St"])
    city: str = Field(..., examples=["Austin"])
    state: str = Field(..., examples=["TX"])
    country: str = Field(default="US", examples=["US"])


class AnalyzeLeadsRequest(BaseModel):
    leads: list[LeadInput]


class SourceSnippet(BaseModel):
    source: str
    title: str | None = None
    url: str | None = None
    snippet: str


class CompanyEnrichment(BaseModel):
    domain: str | None = None
    website_url: str | None = None
    website_title: str | None = None
    website_description: str | None = None
    website_snippet: str | None = None
    search_snippets: list[SourceSnippet] = Field(default_factory=list)
    business_type_signals: list[str] = Field(default_factory=list)
    leasing_volume_signals: list[str] = Field(default_factory=list)
    operational_complexity_signals: list[str] = Field(default_factory=list)
    product_fit_signals: list[str] = Field(default_factory=list)
    property_signals: list[str] = Field(default_factory=list)
    negative_property_signals: list[str] = Field(default_factory=list)
    geographic_footprint_signals: list[str] = Field(default_factory=list)
    timing_signals: list[str] = Field(default_factory=list)
    classifications: dict[str, "MicroSignalClassification"] = Field(default_factory=dict)
    source_text: str = Field(default="", exclude=True)


class AddressResolution(BaseModel):
    confidence: AddressResolutionConfidence
    method: str
    input_address: str
    matched_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    explanation: str | None = None


class MarketMetrics(BaseModel):
    geography_name: str | None = None
    state_fips: str | None = None
    county_fips: str | None = None
    tract: str | None = None
    block_group: str | None = None
    population: int | None = None
    population_growth_rate: float | None = None
    median_gross_rent: int | None = None
    median_income: int | None = None
    renter_share: float | None = None
    housing_units: int | None = None
    vacancy_rate: float | None = None
    no_vehicle_household_share: float | None = None
    public_transit_commute_share: float | None = None
    walking_commute_share: float | None = None
    multifamily_share: float | None = None
    neighborhood_ratios_blended_with_tract: bool = False


class ScoreSection(BaseModel):
    score: int
    max_score: int
    reasons: list[str] = Field(default_factory=list)


class SignalAudit(BaseModel):
    raw_evidence: str
    evidence_source: str | None = None
    parsed_value: str
    interpreted_bucket: str
    confidence: Literal["High", "Medium", "Low"] | None = None
    classifier: Literal["openai_classifier", "rule_fallback"] = "rule_fallback"
    score_contribution: int


class MicroSignalClassification(BaseModel):
    raw_evidence: str
    evidence_source: str
    parsed_value: str
    interpreted_bucket: str
    confidence: Literal["High", "Medium", "Low"]
    classifier: Literal["openai_classifier", "rule_fallback"] = "openai_classifier"


class CompanyFitBreakdown(BaseModel):
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    extraction_audit: dict[str, SignalAudit] = Field(default_factory=dict)


class ScoreBreakdown(BaseModel):
    market_fit: ScoreSection
    company_fit: ScoreSection
    property_fit: ScoreSection
    timing: ScoreSection
    company_fit_breakdown: CompanyFitBreakdown | None = None
    final_score: int
    priority: Priority
    company_fit_label: CompanyFitLabel
    confidence: Literal["High", "Medium", "Low"]


class LeadAnalysis(BaseModel):
    lead: LeadInput
    score: ScoreBreakdown
    address_resolution: AddressResolution | None = None
    market_metrics: MarketMetrics
    company_enrichment: CompanyEnrichment | None = None
    evidence: list[SourceSnippet] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    why_this_lead: list[str] = Field(default_factory=list)
    why_now: str | None = None
    sales_insights: list[str] = Field(default_factory=list)
    outreach_email: str
    follow_ups: list[str]


class AnalyzeLeadsResponse(BaseModel):
    leads: list[LeadAnalysis]
