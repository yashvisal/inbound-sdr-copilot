from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import AnalyzeLeadsRequest, AnalyzeLeadsResponse, LeadAnalysis
from app.outreach import attach_sales_outputs
from app.scoring import score_lead
from app.services.enrichment import enrich_lead

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.post("/api/leads/analyze", response_model=AnalyzeLeadsResponse)
async def analyze_leads(payload: AnalyzeLeadsRequest) -> AnalyzeLeadsResponse:
    analyses: list[LeadAnalysis] = []

    for lead in payload.leads:
        enrichment = await enrich_lead(lead)
        score = score_lead(
            lead=lead,
            market_metrics=enrichment.market_metrics,
            company_text=enrichment.company_text,
            timing_signals=enrichment.timing_signals,
        )
        analysis = LeadAnalysis(
            lead=lead,
            score=score,
            address_resolution=enrichment.address_resolution,
            market_metrics=enrichment.market_metrics,
            evidence=enrichment.evidence,
            missing_data=enrichment.missing_data,
            outreach_email="",
            follow_ups=[],
        )
        analyses.append(attach_sales_outputs(analysis))

    analyses.sort(key=lambda item: item.score.final_score, reverse=True)
    return AnalyzeLeadsResponse(leads=analyses)
