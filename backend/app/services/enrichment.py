from app.models import LeadInput, MarketMetrics, SourceSnippet


class EnrichmentBundle:
    def __init__(
        self,
        market_metrics: MarketMetrics,
        company_text: str,
        timing_signals: list[str],
        evidence: list[SourceSnippet],
        missing_data: list[str],
    ) -> None:
        self.market_metrics = market_metrics
        self.company_text = company_text
        self.timing_signals = timing_signals
        self.evidence = evidence
        self.missing_data = missing_data


async def enrich_lead(lead: LeadInput) -> EnrichmentBundle:
    """Placeholder enrichment pipeline.

    The next implementation step will call DataUSA, Census/ACS, NewsAPI, and
    company website metadata here. For now, return a deterministic empty bundle
    so the API contract and frontend can be developed before API keys are added.
    """

    company_text = f"{lead.company} {lead.email.split('@')[-1]}"
    missing_data = [
        "Market enrichment not connected yet.",
        "Company website metadata not connected yet.",
        "News timing enrichment not connected yet.",
    ]

    return EnrichmentBundle(
        market_metrics=MarketMetrics(),
        company_text=company_text,
        timing_signals=[],
        evidence=[],
        missing_data=missing_data,
    )
