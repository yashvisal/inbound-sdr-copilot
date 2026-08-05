"""Push the precomputed sample analyses into the shared run store.

Run once after ``export_sample_analyses.py`` (and any time the sample set
changes) so the hosted dashboard shows curated runs alongside community ones.
Requires UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN in backend/.env.

    uv run python scripts/seed_sample_runs.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.models import LeadAnalysis
from app.services.run_store import save_run

SAMPLE_PATH = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "sample-analyses.json"


async def main() -> None:
    settings = get_settings()
    if not settings.run_store_enabled:
        print(
            "Upstash is not configured. Set UPSTASH_REDIS_REST_URL and "
            "UPSTASH_REDIS_REST_TOKEN in backend/.env, then re-run."
        )
        return

    if not SAMPLE_PATH.exists():
        print(f"No sample data at {SAMPLE_PATH}. Run export_sample_analyses.py first.")
        return

    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    analyses = [LeadAnalysis.model_validate(raw) for raw in payload["leads"]]

    for analysis in analyses:
        await save_run(analysis, source="sample")
        print(f"  seeded {analysis.lead.company} ({analysis.score.final_score})")

    print(f"Seeded {len(analyses)} sample runs.")


if __name__ == "__main__":
    asyncio.run(main())
