# Inbound SDR Copilot Backend

FastAPI backend for the lead enrichment and scoring MVP.

```bash
cp .env.example .env
uv sync
uv run dev
```

The API runs on `http://localhost:8000`.

Useful verification commands:

```bash
uv run pytest -q
uv run python scripts/verify_company_fit.py --live --company "Greystar"
uv run python scripts/verify_company_fit.py --company "Harbor Residential" --address "The Morrison Apartments, 123 Main St" --property-snippet "The Morrison Apartments has 240 apartment units with available floor plans and now leasing."
uv run python scripts/export_company_fit_golden_cases.py --live
```

Live reports are written to `reports/`. Company Fit uses source-backed Serper/website evidence, OpenAI for structured interpretation, and deterministic Python scoring for scale calibration, ICP caps, and final points.

Property Fit is scored separately out of 16 points using three deterministic sub-signals: property type, property scale, and leasing activity. The pipeline first uses OSM/Nominatim property metadata when it provides a meaningful type, then uses one property-focused Serper query for scale and leasing evidence. Property search snippets are filtered before classification: only exact-address, exact-street, or submitted-building-name matches are used, while neighborhood pages, nearby listings, city-level apartment searches, and different-building results are discarded.
