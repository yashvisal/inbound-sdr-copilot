import asyncio

from app.config import get_settings
from app.models import LeadAnalysis, LeadInput
from app.outreach import attach_sales_outputs
from app.scoring import score_lead
from app.services.enrichment import enrich_lead


async def process_lead(lead: LeadInput) -> LeadAnalysis:
    """Run the full backend lead analysis pipeline for one normalized lead."""

    enrichment = await enrich_lead(lead)
    score = score_lead(
        lead=lead,
        market_metrics=enrichment.market_metrics,
        company_enrichment=enrichment.company_enrichment,
    )
    analysis = LeadAnalysis(
        lead=lead,
        score=score,
        address_resolution=enrichment.address_resolution,
        market_metrics=enrichment.market_metrics,
        company_enrichment=enrichment.company_enrichment,
        evidence=enrichment.evidence,
        missing_data=enrichment.missing_data,
        outreach_email="",
        follow_ups=[],
    )
    return attach_sales_outputs(analysis)


async def process_leads(
    leads: list[LeadInput],
    *,
    max_concurrency: int | None = None,
) -> list[LeadAnalysis]:
    """Process many leads with bounded concurrent per-lead orchestration."""

    if max_concurrency is None:
        max_concurrency = get_settings().enrichment_max_concurrency
    if not leads:
        return []

    if max_concurrency <= 1:
        results: list[LeadAnalysis] = []
        for lead in leads:
            results.append(await process_lead(lead))
        return results

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run_one(lead: LeadInput) -> LeadAnalysis:
        async with semaphore:
            return await process_lead(lead)

    return list(await asyncio.gather(*(run_one(lead) for lead in leads)))
