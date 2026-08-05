"""Seed throwaway runs so the dashboard has enough rows to page through.

The curated sample set is smaller than one page, so pagination never appears.
This clones the exported sample analyses into synthetic leads with distinct ids
and spread-out scores. Nothing here touches the live APIs or the run quota.

Every generated lead uses the TEMP_EMAIL_DOMAIN below, which is what --clear
matches on, so cleanup can never touch a real sample or community run.

    uv run python scripts/seed_temp_runs.py            # add 12 temp runs
    uv run python scripts/seed_temp_runs.py --count 30
    uv run python scripts/seed_temp_runs.py --clear    # remove them all
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.models import LeadAnalysis
from app.services.run_store import build_run_id, delete_run, list_runs, save_run

SAMPLE_PATH = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "sample-analyses.json"

TEMP_EMAIL_DOMAIN = "temp-demo-qa.com"

CITIES = [
    ("Denver", "CO"),
    ("Seattle", "WA"),
    ("Phoenix", "AZ"),
    ("Charlotte", "NC"),
    ("Portland", "OR"),
    ("Nashville", "TN"),
]


def build_temp_analyses(count: int) -> list[LeadAnalysis]:
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    templates = payload["leads"]

    analyses: list[LeadAnalysis] = []
    for index in range(count):
        raw = copy.deepcopy(templates[index % len(templates)])
        number = index + 1
        city, state = CITIES[index % len(CITIES)]

        raw["lead"] = {
            "name": f"Test Lead {number:02d}",
            "email": f"lead{number:02d}@{TEMP_EMAIL_DOMAIN}",
            "company": f"Test Property Group {number:02d}",
            "address": f"{100 + number} Test St",
            "city": city,
            "state": state,
            "country": "US",
        }
        # Spread scores across the priority bands so ordering and rank numbering
        # are obvious while paging. Sub-scores keep their cloned values, so temp
        # rows are for layout testing only — they will not reconcile.
        final_score = max(10, 95 - index * 3)
        raw["score"]["final_score"] = final_score
        # Same thresholds as app.scoring, so the badge matches the number.
        raw["score"]["priority"] = (
            "High" if final_score >= 75 else "Medium" if final_score >= 50 else "Low"
        )
        analyses.append(LeadAnalysis.model_validate(raw))
    return analyses


async def seed(count: int) -> None:
    analyses = build_temp_analyses(count)
    for analysis in analyses:
        await save_run(analysis, source="community")
        print(f"  seeded {analysis.lead.name} ({analysis.score.final_score})")
    print(f"Seeded {len(analyses)} temp runs.")


async def clear() -> None:
    removed = 0
    for record in await list_runs(limit=500):
        lead = record.get("analysis", {}).get("lead", {})
        if not str(lead.get("email", "")).endswith(f"@{TEMP_EMAIL_DOMAIN}"):
            continue
        run_id = build_run_id(LeadAnalysis.model_validate(record["analysis"]).lead)
        await delete_run(run_id)
        removed += 1
        print(f"  removed {lead.get('name')}")
    print(f"Removed {removed} temp runs.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=12, help="How many temp runs to add")
    parser.add_argument("--clear", action="store_true", help="Remove temp runs instead")
    args = parser.parse_args()

    if not get_settings().run_store_enabled:
        print("Upstash is not configured; set UPSTASH_REDIS_REST_* in backend/.env.")
        return
    if not SAMPLE_PATH.exists():
        print(f"No sample data at {SAMPLE_PATH}. Run export_sample_analyses.py first.")
        return

    await (clear() if args.clear else seed(args.count))


if __name__ == "__main__":
    asyncio.run(main())
