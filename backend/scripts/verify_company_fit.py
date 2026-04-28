import argparse
import asyncio
import json

from app.models import LeadInput, MarketMetrics, SourceSnippet
from app.scoring import score_lead
from app.services.company import enrich_company, extract_company_signals


async def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Company / Property Fit on a sample lead.")
    parser.add_argument("--company", default="Harbor Residential")
    parser.add_argument("--email", default="maya@harborresidential.com")
    parser.add_argument("--address", default="The Morrison Apartments, 123 Main St")
    parser.add_argument("--city", default="Austin")
    parser.add_argument("--state", default="TX")
    parser.add_argument("--country", default="US")
    parser.add_argument(
        "--website-snippet",
        default=(
            "Multifamily property management for apartment communities with "
            "resident communication, leasing inquiries, tours, and maintenance requests."
        ),
        help="Offline website text to score without live HTTP/search.",
    )
    parser.add_argument(
        "--search-snippet",
        action="append",
        default=[],
        help="Offline search snippet. Can be passed multiple times.",
    )
    parser.add_argument(
        "--property-snippet",
        action="append",
        default=[],
        help="Offline property search snippet. Can be passed multiple times.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Search the company name with Serper, fetch the discovered website, and score live evidence.",
    )
    args = parser.parse_args()

    lead = LeadInput(
        name="Test Contact",
        email=args.email,
        company=args.company,
        address=args.address,
        city=args.city,
        state=args.state,
        country=args.country,
    )

    if args.live:
        company_result = await enrich_company(lead)
        enrichment = company_result.enrichment
        evidence = company_result.evidence
        missing_data = company_result.missing_data
    else:
        search_snippets = [
            SourceSnippet(source="Manual sample", title=f"{args.company} sample", snippet=snippet)
            for snippet in args.search_snippet
        ]
        property_search_snippets = [
            SourceSnippet(source="Manual property sample", title=args.address, snippet=snippet)
            for snippet in args.property_snippet
        ]
        enrichment = extract_company_signals(
            lead=lead,
            website_snippet=args.website_snippet,
            search_snippets=search_snippets,
            property_search_snippets=property_search_snippets,
        )
        evidence = [*search_snippets, *property_search_snippets]
        missing_data = []

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=enrichment,
    )

    print(
        json.dumps(
            {
                "lead": lead.model_dump(),
                "company_enrichment": enrichment.model_dump(),
                "company_fit": score.company_fit.model_dump(),
                "company_fit_breakdown": (
                    score.company_fit_breakdown.model_dump()
                    if score.company_fit_breakdown
                    else None
                ),
                "property_fit": score.property_fit.model_dump(),
                "property_fit_breakdown": (
                    score.property_fit_breakdown.model_dump()
                    if score.property_fit_breakdown
                    else None
                ),
                "company_fit_label": score.company_fit_label,
                "confidence": score.confidence,
                "evidence": [item.model_dump() for item in evidence],
                "missing_data": missing_data,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
