from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import AnalyzeLeadsRequest, AnalyzeLeadsResponse
from app.services.lead_processing import process_leads

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
    analyses = await process_leads(payload.to_lead_inputs())
    analyses.sort(key=lambda item: item.score.final_score, reverse=True)
    return AnalyzeLeadsResponse(leads=analyses)
