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
        evidence: list[SourceSnippet],
        missing_data: list[str],
        address_resolution: AddressResolution | None = None,
    ) -> None:
        self.market_metrics = market_metrics
        self.company_enrichment = company_enrichment
        self.evidence = evidence
        self.missing_data = missing_data
        self.address_resolution = address_resolution


async def enrich_lead(lead: LeadInput) -> EnrichmentBundle:
    """Enrich one lead with market and company/property context."""

    market_result, company_result = await asyncio.gather(
        enrich_market(lead),
        enrich_company(lead),
        return_exceptions=True,
    )

    if isinstance(market_result, Exception):
        logger.error(
            "Market enrichment failed for %s",
            lead.email,
            exc_info=(type(market_result), market_result, market_result.__traceback__),
        )
        market_metrics = MarketMetrics()
        market_evidence: list[SourceSnippet] = []
        market_missing = ["Market enrichment failed unexpectedly."]
        address_resolution = AddressResolution(
            confidence="Unresolved",
            method="failed",
            input_address=", ".join(
                part for part in [lead.address, lead.city, lead.state, lead.country] if part
            ),
            explanation="Market enrichment failed, so address resolution was unavailable.",
        )
    else:
        market_metrics = market_result.metrics
        market_evidence = market_result.evidence
        market_missing = market_result.missing_data
        address_resolution = market_result.address_resolution

    if isinstance(company_result, Exception):
        logger.error(
            "Company enrichment failed for %s",
            lead.email,
            exc_info=(type(company_result), company_result, company_result.__traceback__),
        )
        company_enrichment = extract_company_signals(lead=lead)
        company_evidence: list[SourceSnippet] = []
        company_missing = ["Company/property enrichment failed unexpectedly."]
    else:
        company_enrichment = company_result.enrichment
        company_evidence = company_result.evidence
        company_missing = company_result.missing_data

    missing_data = [*market_missing, *company_missing]

    return EnrichmentBundle(
        market_metrics=market_metrics,
        company_enrichment=company_enrichment,
        evidence=[*market_evidence, *company_evidence],
        missing_data=missing_data,
        address_resolution=address_resolution,
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
                    evidence=[],
                    missing_data=["Lead enrichment failed unexpectedly."],
                    address_resolution=None,
                )

    return list(await asyncio.gather(*(run_one(lead) for lead in leads)))
