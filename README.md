# Inbound SDR Copilot

**Lead enrichment and scoring for property-management sales teams.** Paste in an inbound lead — a name, a company, a property address — and get back an explainable 0-100 priority score, the evidence behind it, and a personalized outreach email.

Built with FastAPI + Next.js

---

## The problem

Inbound leads arrive as a name, an email, and an address. An SDR has to answer three questions before touching the phone:

- **Who should I prioritize?**
- **Why is this lead worth my time?**
- **What should I say?**

Answering those by hand means tab-hopping through Census data, company websites, and Google. This tool does it in one pass and shows its work.

## How it works

Every lead runs through the same pipeline:

```mermaid
flowchart LR
  lead["Inbound lead"] --> enrich["Enrichment"]
  enrich --> census["Census ACS<br/>tract, place, population"]
  enrich --> geo["Census Geocoder<br/>+ OSM/Nominatim"]
  enrich --> search["Parallel web search"]
  enrich --> site["Company website<br/>Parallel Extract"]
  census & geo & search & site --> llm["LLM: structured<br/>evidence extraction"]
  llm --> score["Deterministic<br/>scoring engine"]
  score --> out["Score · Reasons · Insights · Outreach"]
```

The design decision that matters: **the LLM never picks the score.** It reads source-backed evidence and sorts it into buckets ("leasing volume: High", citing this snippet). Python maps buckets to points. Every number traces to a rule and every rule traces to a citation — and when the model is unavailable, returns malformed JSON, or cites evidence that isn't in the sources, a deterministic rule classifier takes over and the system keeps working.

## Scoring

Final score is out of 100, split across three categories:

| Category | Points | What it estimates |
| --- | --- | --- |
| **Location Fit** | 45 | Leasing demand at neighborhood and city level |
| **Company Fit** | 39 | Leasing volume, operational complexity, product fit |
| **Property Fit** | 16 | Whether the submitted property is a residential leasing asset |

| Final score | Priority |
| --- | --- |
| 75-100 | High |
| 50-74 | Medium |
| 0-49 | Low |

A lead only reaches High with evidence on all three axes: company and property fit alone top out at 55, so a strong operator in a market with no data lands at Medium, not High.

**Location Fit (45)** is mostly address-level, not city-level: tract renter share (10), neighborhood income (8), vacancy as a leasing-pressure proxy (6), and ACS commute/vehicle-access variables as a free stand-in for walkability (9) — with city population, median gross rent and growth contributing the remaining 12.

**Company Fit (39)** scores three micro-signals extracted from company-website content and search snippets — leasing volume, operational complexity, and product fit. Guardrails keep it honest: weak product fit caps the category at 15, no product fit caps it at 5, and unit counts are calibrated in code rather than trusted from the model.

**Property Fit (16)** decides whether the submitted address is actually a residential leasing asset, using OSM/Nominatim property type plus address-matched search evidence. Search snippets are filtered hard before classification — only exact-address, exact-street, or building-name matches survive, so "apartments near X" can't make an office tower look like a lease-up.

Two ideas run through all of it: **missing data lowers confidence, not the score**, and **irrelevant companies get capped regardless of how good their market looks**.

### Address resolution

Real inbound addresses include branded building names and odd local formats, so geography resolution is tracked separately from scoring: exact Census match → coordinate fallback via Nominatim → normalized variant → unresolved. Confidence is surfaced as metadata and never penalizes the score — it explains which geography the neighborhood data came from.

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI, Pydantic, httpx, uv |
| Frontend | Next.js 16, React 19, Tailwind 4, shadcn/ui, zustand |
| Storage | Upstash Redis (shared run dashboard + quota counters) |
| Data | Census ACS, Census Geocoder, OSM/Nominatim, Parallel search + extract |
| LLM | OpenAI, structured outputs only |
| Hosting | Vercel (both halves, free tier) |

### Switching web search from Serper to Parallel

Company and property evidence originally came from Serper: three Google queries for the company, two for the property, one ~150-character snippet per result, no dates, and a homegrown HTML parser for the company website that any JavaScript-rendered or bot-protected site defeated. The search layer was the weakest part of the pipeline, so it now runs on the [Parallel](https://parallel.ai) Search API (one objective-driven call per company and per property) with the Parallel Extract API reading the company's own site. Serper stays as a fallback behind a provider switch.

Measured on the live enrichment path with the same code, filters and 14 leads, only the provider swapped ([`docs/search-provider-benchmark.md`](docs/search-provider-benchmark.md), reproducible with `uv run python scripts/benchmark_search_providers.py` from `backend/`):

- **Median company-search latency dropped 56%** (2,979 ms → 1,316 ms) and **search time per lead dropped 55%** (5,050 ms → 2,286 ms), on 3 provider requests per lead instead of 6.
- **Roughly 9x more evidence per search** (2,089 → 19,789 characters returned), with the share of snippets carrying a publish date rising from 15% to 56%, which is what lets the pipeline prefer fresh unit counts over decade-old press releases.
- **Company-website evidence went from 71% to 96% of runs** because Extract reads pages the raw HTML parser could not.
- **Median Company Fit rose from 18.5 to 30.0 points**, low-confidence runs fell from 5 to 1 out of 28, and classifier rejections for evidence that wasn't source-backed fell from 3 to 1.

## The demo

The hosted dashboard shows curated sample analyses bundled at build time, so it renders instantly with no cold start. Visitors can also run their own lead live — those results are stored and appear on everyone's dashboard tagged **Community**.

Live runs are capped (100/month globally, 3/day per visitor) to keep the public demo inside free API tiers. When the budget is spent the dashboard stays fully browsable; only new runs pause until the counter resets.

## Running locally

**Backend:**

```bash
cd backend
cp .env.example .env    # add CENSUS_API_KEY at minimum
uv sync
uv run dev              # http://localhost:8000
```

**Frontend:**

```bash
cd frontend
pnpm install
pnpm dev                # http://localhost:3000
```

Only `CENSUS_API_KEY` ([free signup](https://api.census.gov/data/key_signup.html)) is needed for meaningful Location Fit scores. `PARALLEL_API_KEY` ([platform.parallel.ai](https://platform.parallel.ai)) and `OPENAI_API_KEY` unlock live company evidence and LLM-written outreach; `SERPER_API_KEY` is an optional search fallback; without them the system falls back to rule-based classification and template outreach. Upstash credentials are optional locally — without them, run storage and quotas are no-ops.

**Tests and tooling:**

```bash
uv run pytest -q                                  # 132 tests
uv run python scripts/export_sample_analyses.py   # regenerate bundled demo data
uv run python scripts/seed_sample_runs.py         # push samples to the shared dashboard
uv run python scripts/verify_company_fit.py --live --company "Greystar"
```

## Deploying

One Vercel project runs both apps as services (see `vercel.json`): the Next.js
frontend at the root and the FastAPI backend behind `/api/backend` on the same
domain, so browser calls are same-origin and need no CORS.

Environment variables on that project:

| Variable | Value |
| --- | --- |
| `API_ROOT_PATH` | `/api/backend` — the prefix the API is mounted under |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/backend` — relative, so it follows the domain |
| `CENSUS_API_KEY` | Required for meaningful Location Fit scores |
| `PARALLEL_API_KEY`, `OPENAI_API_KEY` | Optional; without them the rule-based fallbacks run |
| `SERPER_API_KEY` | Optional web-search fallback when Parallel is unset or failing |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Shared dashboard and quotas |
| `MAX_RUNS_PER_MONTH`, `MAX_RUNS_PER_IP_PER_DAY` | Spend caps; `100` / `3` in production |

Then run `seed_sample_runs.py` once to populate the shared dashboard.

To deploy the two apps as separate projects instead, set each project's root
directory to `backend/` or `frontend/`, leave `API_ROOT_PATH` empty, and point
`NEXT_PUBLIC_API_BASE_URL` at the backend's absolute URL plus `FRONTEND_ORIGIN`
at the frontend's.

## Limitations

- Free public APIs have rate limits and incomplete coverage, especially for small property managers.
- City and tract data are proxies for property-level opportunity, not proof of account quality.
- Search engines return neighborhood and nearby-building noise; the address filter is strict but not perfect.
- U.S. data sources only — international leads fall back to company-level signals.

## Background

Originally built as a GTM-engineering take-home: automate the inbound lead process with public APIs, produce enriched and scored leads, and describe how the tool would be rolled out to a sales org. It's been reworked since into a hostable demo — precomputed sample data, a shared dashboard, and run quotas — but the scoring engine is the original work.

<details>
<summary>Rollout plan from the original submission</summary>

**Phase 1 — MVP validation (week 1).** Test 20-50 sample leads with 2-3 SDRs and a sales manager; compare model scores against SDR intuition.

**Phase 2 — Pilot (weeks 2-3).** Run daily batches on real inbound leads; SDRs review scores before outreach and use generated emails as a starting point. Track time saved per lead and conversion vs. baseline.

**Phase 3 — Iteration (weeks 3-4).** Refine scoring weights, property classification, and outreach tone against SDR feedback and mis-ranked leads.

**Phase 4 — Org rollout (week 4+).** Integrate into the CRM, auto-trigger enrichment on new inbound leads, and close the feedback loop.

</details>
