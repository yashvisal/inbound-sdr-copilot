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
uv run python scripts/export_company_fit_golden_cases.py --live
```

Live company-fit reports are written to `reports/`. Company fit uses source-backed Serper/website evidence, OpenAI for structured interpretation, and deterministic Python scoring for scale calibration, ICP caps, and final points.
