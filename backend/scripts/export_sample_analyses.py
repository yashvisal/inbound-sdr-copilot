"""Export precomputed analyses for the frontend sample-lead demo.

Runs the full enrichment + scoring + outreach pipeline for the curated sample
leads and writes the results to ``frontend/lib/sample-analyses.json``. The
frontend serves that file statically so "Load Sample Data" is instant and the
hosted demo never depends on API quotas or timeouts.

Run with whatever keys are present in ``backend/.env``; richer keys (Serper,
OpenAI) produce richer precomputed evidence and outreach:

    uv run python scripts/export_sample_analyses.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import LeadInput
from app.services.lead_processing import process_leads
from app.services.outreach import generate_outreach

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "sample-analyses.json"

SAMPLE_LEADS: list[dict[str, str]] = [
    {
        "name": "Megan McCann",
        "email": "m.mccann@greystar.com",
        "company": "Greystar",
        "address": "The Eugene, 435 W 31st St",
        "city": "New York",
        "state": "NY",
        "country": "US",
    },
    {
        "name": "Luis Rodriguez",
        "email": "l.rodriguez@smallprops.com",
        "company": "Small Properties LLC",
        "address": "1010 East 178th St",
        "city": "Bronx",
        "state": "NY",
        "country": "US",
    },
    {
        "name": "Ashley Culpepper",
        "email": "a.culpepper@greystar.com",
        "company": "Greystar",
        "address": "Lamar Union, 1100 S Lamar Blvd",
        "city": "Austin",
        "state": "TX",
        "country": "US",
    },
    {
        "name": "Daniel Kim",
        "email": "d.kim@lincolnapts.com",
        "company": "Lincoln Property Company",
        "address": "OneEleven, 111 W Wacker Dr",
        "city": "Chicago",
        "state": "IL",
        "country": "US",
    },
    {
        "name": "Avery Smith",
        "email": "avery@assetliving.com",
        "company": "Asset Living",
        "address": "Novel Midtown, 855 Peachtree St NE",
        "city": "Atlanta",
        "state": "GA",
        "country": "US",
    },
    {
        "name": "James Wilson",
        "email": "j.wilson@momandpoprentals.com",
        "company": "Mom & Pop Rentals",
        "address": "123 Maple Ave",
        "city": "Des Moines",
        "state": "IA",
        "country": "US",
    },
    {
        "name": "Jordan Lee",
        "email": "jordan.lee@avaloncommunities.com",
        "company": "AvalonBay Communities",
        "address": "AVA Nob Hill, 965 Sutter St",
        "city": "San Francisco",
        "state": "CA",
        "country": "US",
    },
    # Commercial brokerage on an office tower: the ICP miss that Company Fit and
    # Property Fit are supposed to catch, kept as a curated low-score example.
    {
        "name": "Casey Morgan",
        "email": "casey@jll.com",
        "company": "JLL",
        "address": "One World Trade Center, 285 Fulton St",
        "city": "New York",
        "state": "NY",
        "country": "US",
    },
]


async def main() -> None:
    leads = [LeadInput(**raw) for raw in SAMPLE_LEADS]
    print(f"Analyzing {len(leads)} sample leads (this hits live public APIs)...")
    analyses = await process_leads(leads)
    analyses.sort(key=lambda item: item.score.final_score, reverse=True)

    exported: list[dict] = []
    for analysis in analyses:
        print(f"  {analysis.lead.company}: {analysis.score.final_score} — generating outreach...")
        outreach = await generate_outreach(analysis.lead, analysis)
        payload = analysis.model_dump(mode="json")
        payload["sales_insights"] = outreach.sales_insights
        payload["outreach_email"] = outreach.personalized_email
        exported.append(payload)

    OUTPUT_PATH.write_text(json.dumps({"leads": exported}, indent=2), encoding="utf-8")
    print(f"Wrote {len(exported)} analyses to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
