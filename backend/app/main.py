from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models import (
    AnalyzeLeadsRequest,
    AnalyzeLeadsResponse,
    OutreachGenerationRequest,
    OutreachGenerationResponse,
    QuotaResponse,
    StoredRunsResponse,
)
from app.services import run_store
from app.services.lead_processing import process_leads
from app.services.outreach import generate_outreach

settings = get_settings()

app = FastAPI(title=settings.app_name, root_path=settings.api_root_path)

# FRONTEND_ORIGIN accepts a comma-separated list so local dev and the deployed
# frontend can be allowed at the same time.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.frontend_origin.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enrichment runs one lead at a time, at roughly 12-30s each, against a 60s
# serverless function ceiling. Three is what reliably fits, and it matches the
# per-visitor daily allowance the CSV dialog already enforces client-side.
MAX_LEADS_PER_REQUEST = 3

QUOTA_MESSAGES = {
    "quota_exhausted": (
        "This public demo is out of free live runs for the month. "
        "Email yashvisal@gmail.com for a walkthrough with live data."
    ),
    "rate_limited": (
        "You've used your live runs for today. Try again tomorrow, or browse the "
        "existing analyses on the dashboard."
    ),
}


def _client_ip(request: Request) -> str:
    """Best-effort caller identity. Vercel sets x-forwarded-for on every request."""

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/quota", response_model=QuotaResponse)
async def read_quota() -> QuotaResponse:
    used, limit = await run_store.get_monthly_usage()
    return QuotaResponse(
        runs_used=used,
        runs_limit=limit,
        runs_remaining=max(0, limit - used),
        period_end=run_store.month_period_end().isoformat(),
        enabled=settings.run_store_enabled,
        per_visitor_daily_limit=settings.max_runs_per_ip_per_day,
    )


@app.get("/api/leads", response_model=StoredRunsResponse)
async def list_stored_leads() -> StoredRunsResponse:
    runs = await run_store.list_runs()
    return StoredRunsResponse(runs=runs)


@app.post("/api/leads/analyze", response_model=AnalyzeLeadsResponse)
async def analyze_leads(payload: AnalyzeLeadsRequest, request: Request):
    leads = payload.to_lead_inputs()

    # Leads are enriched sequentially inside one synchronous request, so an
    # oversized batch would run past the platform's function timeout rather
    # than returning anything useful. Reject it before spending any budget.
    if len(leads) > MAX_LEADS_PER_REQUEST:
        return JSONResponse(
            status_code=413,
            content={
                "reason": "batch_too_large",
                "message": (
                    f"Up to {MAX_LEADS_PER_REQUEST} leads can be analyzed per request. "
                    "Email yashvisal@gmail.com to run a larger batch."
                ),
            },
        )

    # Reserve budget for every lead in the batch so a large CSV cannot slip past
    # the caps that a series of single-lead requests would hit.
    client_ip = _client_ip(request)
    rejection = await run_store.reserve_run_slots(ip=client_ip, count=len(leads))
    if rejection is not None:
        body = {"reason": rejection, "message": QUOTA_MESSAGES[rejection]}
        if rejection == "rate_limited":
            body["retry_after"] = run_store.seconds_until_tomorrow()
        return JSONResponse(status_code=429, content=body)

    try:
        analyses = await process_leads(leads)
        analyses.sort(key=lambda item: item.score.final_score, reverse=True)
        for analysis in analyses:
            await run_store.save_run(analysis, source="community")
    except Exception:
        # The caller got nothing, so the reservation should not stand. The
        # failure itself still propagates to the error handler.
        await run_store.release_run_slots(ip=client_ip, count=len(leads))
        raise

    return AnalyzeLeadsResponse(leads=analyses)


@app.post("/api/leads/generate-outreach", response_model=OutreachGenerationResponse)
async def generate_lead_outreach(
    payload: OutreachGenerationRequest,
) -> OutreachGenerationResponse:
    result = await generate_outreach(payload.analysis.lead, payload.analysis)
    await run_store.update_run_outreach(
        payload.analysis.lead,
        sales_insights=result.sales_insights,
        outreach_email=result.personalized_email,
    )
    return result
