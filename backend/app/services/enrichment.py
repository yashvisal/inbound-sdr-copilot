import asyncio
import logging

from app.config import get_settings
from app.models import AddressResolution, LeadInput, MarketMetrics, SourceSnippet
from app.services.market import enrich_market

logger = logging.getLogger(__name__)


class EnrichmentBundle:
    def __init__(
        self,
        market_metrics: MarketMetrics,
        company_text: str,
        timing_signals: list[str],
        evidence: list[SourceSnippet],
        missing_data: list[str],
        address_resolution: AddressResolution | None = None,
    ) -> None:
        self.market_metrics = market_metrics
        self.company_text = company_text
        self.timing_signals = timing_signals
        self.evidence = evidence
        self.missing_data = missing_data
        self.address_resolution = address_resolution


async def enrich_lead(lead: LeadInput) -> EnrichmentBundle:
    """Placeholder enrichment pipeline.

    The next implementation step will call DataUSA, Census/ACS, NewsAPI, and
    company website metadata here. For now, return a deterministic empty bundle
    so the API contract and frontend can be developed before API keys are added.
    """

    market = await enrich_market(lead)
    company_text = f"{lead.company} {lead.email.split('@')[-1]}"
    missing_data = [
        *market.missing_data,
        "Company website metadata not connected yet.",
        "News timing enrichment not connected yet.",
    ]

    return EnrichmentBundle(
        market_metrics=market.metrics,
        company_text=company_text,
        timing_signals=[],
        evidence=market.evidence,
        missing_data=missing_data,
        address_resolution=market.address_resolution,
    )


async def enrich_leads(
    leads: list[LeadInput],
    *,
    max_concurrency: int | None = None,
) -> list[EnrichmentBundle]:
    """Enrich many leads with bounded concurrent market and enrichment I/O."""

    if max_concurrency is None:
        max_concurrency = get_settings().enrichment_max_concurrency
    if not leads:
        return []

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run_one(lead: LeadInput) -> EnrichmentBundle:
        async with semaphore:
            try:
                return await enrich_lead(lead)
            except Exception:
                logger.exception("Lead enrichment failed for %s", lead.email)
                company_text = f"{lead.company} {lead.email.split('@')[-1]}"
                return EnrichmentBundle(
                    market_metrics=MarketMetrics(),
                    company_text=company_text,
                    timing_signals=[],
                    evidence=[],
                    missing_data=["Lead enrichment failed unexpectedly."],
                    address_resolution=None,
                )

    return list(await asyncio.gather(*(run_one(lead) for lead in leads)))
