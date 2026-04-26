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
    median_income: int | None = None
    renter_share: float | None = None
    housing_units: int | None = None
    vacancy_rate: float | None = None
    no_vehicle_household_share: float | None = None
    public_transit_commute_share: float | None = None
    walking_commute_share: float | None = None
    multifamily_share: float | None = None


class ScoreSection(BaseModel):
    score: int
    max_score: int
    reasons: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    market_fit: ScoreSection
    company_fit: ScoreSection
    timing: ScoreSection
    final_score: int
    priority: Priority
    company_fit_label: CompanyFitLabel
    confidence: Literal["High", "Medium", "Low"]


class LeadAnalysis(BaseModel):
    lead: LeadInput
    score: ScoreBreakdown
    address_resolution: AddressResolution | None = None
    market_metrics: MarketMetrics
    evidence: list[SourceSnippet] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    why_this_lead: list[str] = Field(default_factory=list)
    why_now: str | None = None
    sales_insights: list[str] = Field(default_factory=list)
    outreach_email: str
    follow_ups: list[str]


class AnalyzeLeadsResponse(BaseModel):
    leads: list[LeadAnalysis]
