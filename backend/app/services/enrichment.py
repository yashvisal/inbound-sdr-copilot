import asyncio
import logging

from app.config import get_settings
from app.models import AddressResolution, CompanyEnrichment, LeadInput, MarketMetrics, SourceSnippet
from app.services.company import enrich_company, extract_company_signals
from app.services.market import enrich_market

logger = logging.getLogger(__name__)


class EnrichmentBundle:
    def __init__(
        self,
        market_metrics: MarketMetrics,
        company_enrichment: CompanyEnrichment,
        timing_signals: list[str],
        evidence: list[SourceSnippet],
        missing_data: list[str],
        address_resolution: AddressResolution | None = None,
    ) -> None:
        self.market_metrics = market_metrics
        self.company_enrichment = company_enrichment
        self.timing_signals = timing_signals
        self.evidence = evidence
        self.missing_data = missing_data
        self.address_resolution = address_resolution


async def enrich_lead(lead: LeadInput) -> EnrichmentBundle:
    """Enrich one lead with market and company/property context."""

    market = await enrich_market(lead)
    company = await enrich_company(lead)
    missing_data = [*market.missing_data, *company.missing_data]

    return EnrichmentBundle(
        market_metrics=market.metrics,
        company_enrichment=company.enrichment,
        timing_signals=company.enrichment.timing_signals,
        evidence=[*market.evidence, *company.evidence],
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
                company_enrichment = extract_company_signals(lead=lead)
                return EnrichmentBundle(
                    market_metrics=MarketMetrics(),
                    company_enrichment=company_enrichment,
                    timing_signals=[],
                    evidence=[],
                    missing_data=["Lead enrichment failed unexpectedly."],
                    address_resolution=None,
                )

    return list(await asyncio.gather(*(run_one(lead) for lead in leads)))
