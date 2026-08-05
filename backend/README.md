# Inbound SDR Copilot Backend

FastAPI backend for the lead enrichment and scoring MVP.

```bash
cp .env.example .env
uv sync
uv run dev
```

The API runs on `http://localhost:8000`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check |
| `GET` | `/api/leads` | Stored runs for the shared dashboard (samples + community) |
| `GET` | `/api/quota` | Remaining monthly budget, plus the per-visitor daily limit |
| `POST` | `/api/leads/analyze` | Enrich and score leads; 413 above `MAX_LEADS_PER_REQUEST`, 429 when a quota is hit |
| `POST` | `/api/leads/generate-outreach` | Sales insights + personalized email for one analysis |

Run storage and quotas live in Upstash Redis (`app/services/run_store.py`). When
`UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` are unset, both degrade to
no-ops so local development needs no external services.

Two independent quotas guard the analyze endpoint, and either one can reject a
request on its own: a global monthly budget (`MAX_RUNS_PER_MONTH`) that resets
on the 1st, and a per-visitor daily allowance (`MAX_RUNS_PER_IP_PER_DAY`). A
visitor who has spent today's allowance gets a 429 even when the month still has
capacity left, so `GET /api/quota` reports both numbers. Slots are reserved for
every lead in a batch up front and released again if the run fails.

Useful verification commands:

```bash
uv run pytest -q
uv run python scripts/export_sample_analyses.py
uv run python scripts/seed_sample_runs.py
uv run python scripts/verify_company_fit.py --live --company "Greystar"
uv run python scripts/verify_company_fit.py --company "Harbor Residential" --address "The Morrison Apartments, 123 Main St" --property-snippet "The Morrison Apartments has 240 apartment units with available floor plans and now leasing."
uv run python scripts/export_company_fit_golden_cases.py --live
```

Live reports are written to `reports/`. Company Fit uses source-backed Serper/website evidence, OpenAI for structured interpretation, and deterministic Python scoring for scale calibration, ICP caps, and final points.

Property Fit is scored separately out of 16 points using three deterministic sub-signals: property type, property scale, and leasing activity. The pipeline first uses OSM/Nominatim property metadata when it provides a meaningful type, then uses one property-focused Serper query for scale and leasing evidence. Property search snippets are filtered before classification: only exact-address, exact-street, or submitted-building-name matches are used, while neighborhood pages, nearby listings, city-level apartment searches, and different-building results are discarded.
