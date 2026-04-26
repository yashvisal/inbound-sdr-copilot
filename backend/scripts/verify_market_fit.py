import asyncio
import argparse
import json

from app.models import LeadInput
from app.scoring import score_lead
from app.services.market import enrich_market


async def main() -> None:
    parser = argparse.ArgumentParser(description="Verify live Market Fit enrichment.")
    parser.add_argument("--address", default="301 W 2nd St")
    parser.add_argument("--city", default="Austin")
    parser.add_argument("--state", default="TX")
    parser.add_argument("--company", default="Harbor Residential")
    args = parser.parse_args()

    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company=args.company,
        address=args.address,
        city=args.city,
        state=args.state,
        country="US",
    )
    market = await enrich_market(lead)
    score = score_lead(
        lead=lead,
        market_metrics=market.metrics,
        company_text="Harbor Residential property management apartments leasing communities",
        timing_signals=[],
    )

    print(
        json.dumps(
            {
                "city": lead.city,
                "state": lead.state,
                "market_metrics": market.metrics.model_dump(),
                "address_resolution": (
                    market.address_resolution.model_dump()
                    if market.address_resolution
                    else None
                ),
                "market_fit": score.market_fit.model_dump(),
                "evidence": [item.model_dump() for item in market.evidence],
                "missing_data": market.missing_data,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
