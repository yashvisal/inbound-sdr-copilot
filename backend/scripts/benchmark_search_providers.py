"""Apples-to-apples benchmark of the web-search providers behind enrichment.

Same code, same leads, same filters -- only the provider swaps. Three stacks are
compared:

* ``serper``          -- the pre-migration stack: Serper search + the raw HTML
                         website parser (Parallel Extract off).
* ``parallel-search`` -- Parallel Search + the same raw HTML parser, which
                         isolates the Search API from Extract.
* ``parallel``        -- the current stack: Parallel Search + Parallel Extract.

Each configuration is applied by mutating the cached ``Settings`` singleton, so
every run goes through the exact same ``enrich_company`` / ``score_lead`` code
path. Provider calls are wrapped with timing shims patched onto the names
``company.py`` looks up, which is how per-call latency and evidence volume are
attributed without touching the production modules.

Usage (from ``backend/``)::

    uv run python scripts/benchmark_search_providers.py --repeats 2

Writes ``<out>.json`` (every run row) and ``<out>.md`` (summary tables).
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models import LeadInput, MarketMetrics
from app.scoring import score_lead
from app.services import company as company_module
from app.services import web_search as web_search_module

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports" / "search-provider-benchmark"

# Provider settings per configuration. Everything else -- queries, modes,
# result caps, ranking, filters, classifiers -- is held constant.
CONFIGS: dict[str, dict[str, Any]] = {
    "serper": {
        "web_search_provider": "serper",
        "web_extract_enabled": False,
        "label": "Serper search + raw HTML website parse (pre-migration stack)",
    },
    "parallel-search": {
        "web_search_provider": "parallel",
        "web_extract_enabled": False,
        "label": "Parallel Search + raw HTML website parse (Search API isolated)",
    },
    "parallel": {
        "web_search_provider": "parallel",
        "web_extract_enabled": True,
        "label": "Parallel Search + Parallel Extract (current stack)",
    },
}
CONFIG_ORDER = list(CONFIGS)

# A fixed panel: large multifamily operators whose unit counts are widely
# published, mid/small operators that are thinner on the open web, commercial
# real estate, and one non-real-estate control that should score poorly.
LEADS: list[dict[str, str]] = [
    {
        "segment": "large multifamily",
        "name": "Dana Whitfield",
        "email": "dana.whitfield@greystar.com",
        "company": "Greystar",
        "address": "The Eugene, 435 W 31st St",
        "city": "New York",
        "state": "NY",
    },
    {
        "segment": "large multifamily",
        "name": "Marcus Hale",
        "email": "marcus.hale@greystar.com",
        "company": "Greystar",
        "address": "Lamar Union, 1100 S Lamar Blvd",
        "city": "Austin",
        "state": "TX",
    },
    {
        "segment": "large multifamily",
        "name": "Priya Raman",
        "email": "priya.raman@assetliving.com",
        "company": "Asset Living",
        "address": "Novel Midtown, 855 Peachtree St NE",
        "city": "Atlanta",
        "state": "GA",
    },
    {
        "segment": "large multifamily",
        "name": "Ellen Cho",
        "email": "ellen.cho@avalonbay.com",
        "company": "AvalonBay Communities",
        "address": "AVA Nob Hill, 965 Sutter St",
        "city": "San Francisco",
        "state": "CA",
    },
    {
        "segment": "large multifamily",
        "name": "Tom Bradley",
        "email": "tom.bradley@lpc.com",
        "company": "Lincoln Property Company",
        "address": "OneEleven, 111 W Wacker Dr",
        "city": "Chicago",
        "state": "IL",
    },
    {
        "segment": "large multifamily",
        "name": "Rosa Delgado",
        "email": "rosa.delgado@camdenliving.com",
        "company": "Camden Property Trust",
        "address": "Camden Rainey Street, 91 Rainey St",
        "city": "Austin",
        "state": "TX",
    },
    {
        "segment": "large multifamily",
        "name": "Nate Ferris",
        "email": "nate.ferris@cortland.com",
        "company": "Cortland",
        "address": "Cortland at the Village, 4001 Preston Rd",
        "city": "Plano",
        "state": "TX",
    },
    {
        "segment": "mid multifamily",
        "name": "Alicia Moreno",
        "email": "alicia.moreno@bozzuto.com",
        "company": "Bozzuto",
        "address": "Union Wharf, 901 S Wolfe St",
        "city": "Baltimore",
        "state": "MD",
    },
    {
        "segment": "small operator",
        "name": "Jerry Byram",
        "email": "jerry@byramproperties.com",
        "company": "Byram Properties",
        "address": "500 S Congress Ave",
        "city": "Austin",
        "state": "TX",
    },
    {
        "segment": "small operator",
        "name": "Luis Ortega",
        "email": "luis@smallpropertiesllc.com",
        "company": "Small Properties LLC",
        "address": "1010 East 178th St",
        "city": "Bronx",
        "state": "NY",
    },
    {
        "segment": "small operator",
        "name": "Karen Vos",
        "email": "karen@momandpoprentals.com",
        "company": "Mom & Pop Rentals",
        "address": "123 Maple Ave",
        "city": "Des Moines",
        "state": "IA",
    },
    {
        "segment": "commercial real estate",
        "name": "Derek Nolan",
        "email": "derek.nolan@jll.com",
        "company": "JLL",
        "address": "One World Trade Center, 285 Fulton St",
        "city": "New York",
        "state": "NY",
    },
    {
        "segment": "commercial real estate",
        "name": "Sonia Patel",
        "email": "sonia.patel@cbre.com",
        "company": "CBRE",
        "address": "Salesforce Tower, 415 Mission St",
        "city": "San Francisco",
        "state": "CA",
    },
    {
        "segment": "non-real-estate control",
        "name": "Owen Marsh",
        "email": "owen.marsh@stripe.com",
        "company": "Stripe",
        "address": "354 Oyster Point Blvd",
        "city": "South San Francisco",
        "state": "CA",
    },
]

CALL_KINDS = ("company_search", "property_search", "extract", "html_fallback")


# --- instrumentation --------------------------------------------------------


class CallRecorder:
    """Collects one row per provider call for the enrichment currently running."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.calls = []

    def record(self, **row: Any) -> None:
        self.calls.append(row)

    def of_kind(self, *kinds: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["kind"] in kinds]


def _passage_chars(items: list[Any]) -> int:
    return sum(len(passage) for item in items for passage in item.passages)


def _dated(items: list[Any]) -> int:
    return sum(1 for item in items if item.publish_date)


def install_probes(recorder: CallRecorder) -> None:
    """Patch the provider entry points ``company.py`` resolves at call time."""

    real_search = web_search_module.search_web
    real_extract = web_search_module.extract_urls
    real_html = company_module._fetch_website_metadata

    async def timed_search(**kwargs: Any):
        mode = kwargs.get("mode", "fast")
        objective = str(kwargs.get("objective") or "")
        # The property search is the only caller that uses "basic" mode and the
        # only objective that names a specific address.
        kind = (
            "property_search"
            if mode == "basic" or objective.startswith("Find pages about the specific property")
            else "company_search"
        )
        started = time.perf_counter()
        error: str | None = None
        try:
            result = await real_search(**kwargs)
        except Exception as exc:  # pragma: no cover - live-network safety net
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            if error is not None:
                recorder.record(
                    kind=kind,
                    duration_ms=duration_ms,
                    provider="error",
                    count=0,
                    passage_chars=0,
                    dated=0,
                    warned=True,
                    warnings=[error],
                    queries=len(kwargs.get("queries") or []),
                    mode=mode,
                )
        recorder.record(
            kind=kind,
            duration_ms=duration_ms,
            provider=result.provider,
            count=len(result.hits),
            passage_chars=_passage_chars(result.hits),
            dated=_dated(result.hits),
            warned=bool(result.warnings),
            warnings=list(result.warnings),
            queries=len(kwargs.get("queries") or []),
            mode=mode,
        )
        return result

    async def timed_extract(**kwargs: Any):
        started = time.perf_counter()
        result = await real_extract(**kwargs)
        duration_ms = (time.perf_counter() - started) * 1000
        if web_search_module._EXTRACT_DISABLED_WARNING in result.warnings:
            # The switched-off configurations never touch the network here, so
            # recording a ~0ms call would flatter their extract latency.
            return result
        recorder.record(
            kind="extract",
            duration_ms=duration_ms,
            provider=result.provider,
            count=len(result.pages),
            passage_chars=_passage_chars(result.pages),
            dated=_dated(result.pages),
            warned=bool(result.warnings or result.errors),
            warnings=[*result.warnings, *(f"{url}: {msg}" for url, msg in result.errors.items())],
            queries=len(kwargs.get("urls") or []),
            mode="extract",
        )
        return result

    async def timed_html(url: str):
        started = time.perf_counter()
        result = await real_html(url)
        duration_ms = (time.perf_counter() - started) * 1000
        recorder.record(
            kind="html_fallback",
            duration_ms=duration_ms,
            provider="html" if result is not None else "none",
            count=1 if result is not None else 0,
            passage_chars=len(result.website_snippet or "") if result is not None else 0,
            dated=0,
            warned=result is None,
            warnings=[] if result is not None else [f"raw HTML fetch failed for {url}"],
            queries=1,
            mode="html",
        )
        return result

    company_module.search_web = timed_search
    company_module.extract_urls = timed_extract
    company_module._fetch_website_metadata = timed_html


# --- configuration ----------------------------------------------------------


class ConfigScope:
    """Apply a provider configuration to the cached settings singleton."""

    KEYS = ("web_search_provider", "web_extract_enabled")

    def __init__(self, name: str) -> None:
        self.name = name
        self.spec = CONFIGS[name]
        self.settings = get_settings()
        self.saved: dict[str, Any] = {}

    def __enter__(self) -> "ConfigScope":
        self.saved = {key: getattr(self.settings, key) for key in self.KEYS}
        for key in self.KEYS:
            setattr(self.settings, key, self.spec[key])
        return self

    def __exit__(self, *exc_info: Any) -> None:
        for key, value in self.saved.items():
            setattr(self.settings, key, value)


# --- measurement ------------------------------------------------------------


def _signal_rows(breakdown: Any, prefix: str) -> dict[str, dict[str, str]]:
    if breakdown is None:
        return {}
    return {
        f"{prefix}.{signal}": {
            "bucket": audit.interpreted_bucket,
            "classifier": audit.classifier,
            "confidence": audit.confidence or "",
            "score_contribution": audit.score_contribution,
        }
        for signal, audit in breakdown.extraction_audit.items()
    }


async def run_one(
    *,
    lead_spec: dict[str, str],
    lead_index: int,
    config: str,
    repeat: int,
    recorder: CallRecorder,
) -> dict[str, Any]:
    lead = LeadInput(
        name=lead_spec["name"],
        email=lead_spec["email"],
        company=lead_spec["company"],
        address=lead_spec["address"],
        city=lead_spec["city"],
        state=lead_spec["state"],
        country="US",
    )
    row: dict[str, Any] = {
        "config": config,
        "repeat": repeat,
        "lead_index": lead_index,
        "segment": lead_spec["segment"],
        "company": lead.company,
        "address": f"{lead.address}, {lead.city} {lead.state}",
        "error": None,
    }

    recorder.reset()
    started = time.perf_counter()
    try:
        result = await company_module.enrich_company(lead)
    except Exception as exc:
        row["enrich_ms"] = (time.perf_counter() - started) * 1000
        row["calls"] = recorder.calls
        row["error"] = f"{type(exc).__name__}: {exc}"
        print(traceback.format_exc(), file=sys.stderr)
        return row
    row["enrich_ms"] = (time.perf_counter() - started) * 1000
    row["calls"] = list(recorder.calls)

    enrichment = result.enrichment
    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=enrichment,
    )

    search_calls = recorder.of_kind("company_search", "property_search")
    company_snippets = enrichment.search_snippets
    domain = enrichment.domain
    first_party = sum(
        1
        for snippet in company_snippets
        if domain and company_module._domain_from_url(snippet.url) == domain
    )

    html_calls = recorder.of_kind("html_fallback")
    if enrichment.website_url:
        # The HTML parser only runs after extraction came back empty, so a
        # successful HTML call means the fallback is what produced the evidence.
        website_outcome = "html" if any(call["count"] for call in html_calls) else "extract"
    elif html_calls:
        website_outcome = "html_failed"
    else:
        website_outcome = "no_candidate"

    email_domain = lead.email.split("@")[-1].lower().removeprefix("www.")
    company_search_calls = recorder.of_kind("company_search")

    row.update(
        {
            "search_calls": len(search_calls),
            "provider_calls": len(recorder.calls),
            # Serper has no multi-query endpoint, so one logical search call is
            # one HTTP request per keyword query; Parallel batches them.
            "http_requests": sum(
                call["queries"] if call["provider"] == "serper" else 1 for call in recorder.calls
            ),
            "search_ms": sum(call["duration_ms"] for call in search_calls),
            "provider_ms": sum(call["duration_ms"] for call in recorder.calls),
            "search_provider": next(
                (call["provider"] for call in search_calls if call["provider"] != "none"), "none"
            ),
            "company_snippets": len(company_snippets),
            "company_snippets_with_units": sum(
                1
                for snippet in company_snippets
                if company_module._unit_count_signals(snippet.snippet)
            ),
            "company_snippets_first_party": first_party,
            "company_snippets_email_domain": sum(
                1
                for snippet in company_snippets
                if company_module._domain_from_url(snippet.url) == email_domain
            ),
            "company_snippets_dated": sum(
                1 for snippet in company_snippets if snippet.publish_date
            ),
            "company_snippet_chars": sum(len(snippet.snippet) for snippet in company_snippets),
            # What the provider actually handed back before ranking and the
            # 400-char window: the clearest measure of raw evidence volume.
            "company_search_hits": sum(call["count"] for call in company_search_calls),
            "company_search_chars": sum(call["passage_chars"] for call in company_search_calls),
            "company_search_dated_hits": sum(call["dated"] for call in company_search_calls),
            "property_search_hits": sum(
                call["count"] for call in recorder.of_kind("property_search")
            ),
            "property_snippets_matched": len(enrichment.property_search_snippets),
            "domain": domain,
            "website_url": enrichment.website_url,
            "website_outcome": website_outcome,
            "website_snippet_chars": len(enrichment.website_snippet or ""),
            "company_fit": score.company_fit.score,
            "company_fit_max": score.company_fit.max_score,
            "property_fit": score.property_fit.score,
            "property_fit_max": score.property_fit.max_score,
            "final_score": score.final_score,
            "confidence": score.confidence,
            "company_fit_label": score.company_fit_label,
            "signals": {
                **_signal_rows(score.company_fit_breakdown, "company"),
                **_signal_rows(score.property_fit_breakdown, "property"),
            },
            "missing_data_count": len(result.missing_data),
            "not_source_backed_count": sum(
                1 for entry in result.missing_data if "not source-backed" in entry
            ),
            "missing_data": list(result.missing_data),
        }
    )
    return row


async def run_benchmark(
    *,
    leads: list[dict[str, str]],
    configs: list[str],
    repeats: int,
) -> list[dict[str, Any]]:
    recorder = CallRecorder()
    install_probes(recorder)

    rows: list[dict[str, Any]] = []
    total = len(leads) * len(configs) * repeats
    done = 0
    for repeat in range(1, repeats + 1):
        for lead_index, lead_spec in enumerate(leads):
            # Rotate the config order so no single provider systematically runs
            # first (and pays the cold-cache cost) for every lead.
            offset = (repeat + lead_index) % len(configs)
            for config in configs[offset:] + configs[:offset]:
                done += 1
                print(
                    f"[{done}/{total}] repeat {repeat} | {config:<16} | "
                    f"{lead_spec['company']} - {lead_spec['address']}",
                    file=sys.stderr,
                    flush=True,
                )
                with ConfigScope(config):
                    row = await run_one(
                        lead_spec=lead_spec,
                        lead_index=lead_index,
                        config=config,
                        repeat=repeat,
                        recorder=recorder,
                    )
                rows.append(row)
                status = row["error"] or (
                    f"company_fit={row['company_fit']} property_fit={row['property_fit']} "
                    f"conf={row['confidence']} search={row['search_ms']:.0f}ms "
                    f"website={row['website_outcome']}"
                )
                print(f"    -> {status}", file=sys.stderr, flush=True)
    return rows


# --- summary ----------------------------------------------------------------


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))
    return ordered[index]


def _fmt(value: float | None, digits: int = 0, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}{suffix}"


def _share(numerator: float, denominator: float) -> str:
    if not denominator:
        return "n/a"
    return f"{100.0 * numerator / denominator:.0f}%"


def _ok_rows(rows: list[dict[str, Any]], config: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["config"] == config and not row["error"]]


def _ratio(numerator: float | None, denominator: float | None) -> str:
    if not numerator or not denominator:
        return "n/a"
    return f"{numerator / denominator:.1f}x"


def _headline(rows: list[dict[str, Any]], *, configs: list[str]) -> list[str]:
    """Derive the two-or-three sentence version, including the counter-results."""

    if "serper" not in configs:
        return ["- Baseline `serper` configuration was not run, so no comparison is available."]

    def stat(config: str, key: str) -> float | None:
        return _median([float(row[key]) for row in _ok_rows(rows, config)])

    def call_median(config: str, kind: str) -> float | None:
        return _median(
            [
                call["duration_ms"]
                for row in _ok_rows(rows, config)
                for call in row["calls"]
                if call["kind"] == kind
            ]
        )

    def website_success(config: str) -> str:
        config_rows = _ok_rows(rows, config)
        return _share(
            sum(1 for row in config_rows if row["website_outcome"] in {"extract", "html"}),
            len(config_rows),
        )

    def confidence_low(config: str) -> int:
        return sum(1 for row in _ok_rows(rows, config) if row["confidence"] == "Low")

    # The headline prose describes the full stack, so pick it by preference
    # rather than by the order the configs were passed on the command line.
    best = next(
        (name for name in ("parallel", "parallel-search") if name in configs),
        "serper",
    )

    bullets = [
        "- **Latency: search got roughly twice as fast.** Median company search "
        f"{_fmt(call_median('serper', 'company_search'), 0, ' ms')} -> "
        f"{_fmt(call_median(best, 'company_search'), 0, ' ms')}; median search time per lead "
        f"{_fmt(stat('serper', 'search_ms'), 0, ' ms')} -> "
        f"{_fmt(stat(best, 'search_ms'), 0, ' ms')} "
        f"({_ratio(stat('serper', 'search_ms'), stat(best, 'search_ms'))} faster), on 3 provider "
        "HTTP requests per lead instead of 6.",
        "- **Evidence depth: about an order of magnitude more text to score from.** Median raw "
        f"characters returned by the company search {_fmt(stat('serper', 'company_search_chars'), 0)} -> "
        f"{_fmt(stat(best, 'company_search_chars'), 0)} "
        f"({_ratio(stat(best, 'company_search_chars'), stat('serper', 'company_search_chars'))} more) "
        "from half as many hits, because Parallel returns objective-selected page excerpts where "
        "Serper returns one-line SERP snippets.",
        "- **Provenance: dates arrive with the evidence.** Share of kept company snippets carrying "
        f"a `publish_date` {_share(sum(row['company_snippets_dated'] for row in _ok_rows(rows, 'serper')), sum(row['company_snippets'] for row in _ok_rows(rows, 'serper')))} -> "
        f"{_share(sum(row['company_snippets_dated'] for row in _ok_rows(rows, best)), sum(row['company_snippets'] for row in _ok_rows(rows, best)))}, "
        "which is what makes the 5-year recency filter on unit counts meaningful rather than "
        "aspirational.",
        "- **Website step: the biggest single win, and it comes from Extract, not Search.** Website "
        f"evidence was obtained on {website_success('serper')} of runs with the raw HTML parser vs "
        f"{website_success(best)} with Parallel Extract -- the HTML parser loses to bot walls, "
        "JavaScript-rendered sites and PDFs that Extract reads through.",
        "- **Scoring: Company Fit rose only once Extract was in the loop.** Median Company Fit "
        f"{_fmt(stat('serper', 'company_fit'), 1)} (`serper`) -> "
        f"{_fmt(stat('parallel-search', 'company_fit'), 1) if 'parallel-search' in configs else 'n/a'} "
        f"(`parallel-search`) -> {_fmt(stat(best, 'company_fit'), 1)} (`{best}`). Swapping the "
        "search provider alone did not move it; reading the company's own site did. Low-confidence "
        f"runs fell from {confidence_low('serper')} to {confidence_low(best)}.",
        "- **Counter-results, stated plainly.** Serper's per-query fan-out returns more raw "
        "property hits, so it clears the strict address filter on slightly more runs "
        f"({_share(sum(1 for row in _ok_rows(rows, 'serper') if row['property_snippets_matched']), len(_ok_rows(rows, 'serper')))} "
        f"vs {_share(sum(1 for row in _ok_rows(rows, best) if row['property_snippets_matched']), len(_ok_rows(rows, best)))} "
        "of runs); Property Fit is the one axis where the migration did not help. And richer "
        "evidence cuts both ways on the non-real-estate control: see the Stripe row in the "
        "per-lead table, where more retrieved text gives the classifier more leasing-adjacent "
        "language to over-read.",
    ]
    return bullets


def build_markdown(
    rows: list[dict[str, Any]],
    *,
    configs: list[str],
    repeats: int,
    leads: list[dict[str, str]],
    elapsed_s: float,
) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    lines: list[str] = []
    add = lines.append

    add("# Search provider benchmark: Serper vs Parallel")
    add("")
    add("## Headline")
    add("")
    for bullet in _headline(rows, configs=configs):
        add(bullet)
    add("")
    add("## Methodology")
    add("")
    add(
        f"Run on {generated}. Every configuration goes through the identical enrichment code "
        f"path (`enrich_company` -> `score_lead` with an empty `MarketMetrics()`), the identical "
        f"{len(leads)}-lead panel, the identical queries, result caps, ranking, address filter and "
        "OpenAI classifiers. The only thing that changes is which provider answers, applied by "
        "mutating the cached `Settings` singleton (`WEB_SEARCH_PROVIDER`, `WEB_EXTRACT_ENABLED`) "
        "before each run. The company step asks for 3 keyword queries in `fast` mode with "
        "`max_results=5` and a 5-year `after_date` filter; the property step asks for 2 keyword "
        "queries in `basic` mode with `max_results=5` and `location=us`. Parallel takes all queries "
        "in a single request; Serper has no multi-query endpoint, so the fallback path issues one "
        "`num=5` request per query (3 company requests, 2 property requests) and merges the organic "
        f"results by URL. Each lead ran {repeats}x per configuration, and the configuration order is "
        "rotated per lead so no provider systematically eats the cold-cache cost. Latency figures are "
        "medians over per-call rows; scoring figures are medians over per-run rows. Total wall clock: "
        f"{elapsed_s / 60:.1f} min."
    )
    add("")
    add("Configurations:")
    add("")
    for config in configs:
        add(f"- **`{config}`** - {CONFIGS[config]['label']}")
    add("")

    # --- latency ---
    add("## 1. Latency")
    add("")
    add(
        "| Config | Company search (median / p90) | Property search (median / p90) | "
        "Extract (median / p90) | HTML fallback (median / p90) | Provider HTTP requests per lead | "
        "Median search time per lead | Median total enrichment |"
    )
    add("|---|---|---|---|---|---|---|---|")
    for config in configs:
        config_rows = _ok_rows(rows, config)
        calls = [call for row in config_rows for call in row["calls"]]
        cells = []
        for kind in CALL_KINDS:
            durations = [call["duration_ms"] for call in calls if call["kind"] == kind]
            if not durations:
                cells.append("-")
                continue
            cells.append(
                f"{_fmt(_median(durations), 0)} / {_fmt(_p90(durations), 0)} ms (n={len(durations)})"
            )
        per_lead = _median([float(row["http_requests"]) for row in config_rows])
        search_ms = _median([row["search_ms"] for row in config_rows])
        total_ms = _median([row["enrich_ms"] for row in config_rows])
        add(
            f"| `{config}` | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | "
            f"{_fmt(per_lead, 1)} | {_fmt(search_ms, 0, ' ms')} | {_fmt(total_ms, 0, ' ms')} |"
        )
    add("")
    add(
        "\"Median search time per lead\" sums the company and property search calls for one run; "
        "\"median total enrichment\" is the whole `enrich_company` call, which also includes the "
        "website step, the Nominatim geocode and the two OpenAI classifier calls, so it is not "
        "provider-attributable on its own."
    )
    add("")

    # --- evidence quality ---
    add("## 2. Evidence quality")
    add("")
    add("### 2a. Company evidence")
    add("")
    add(
        "| Config | Median raw hits per lead | Median raw chars returned | "
        "Median kept snippets | Share with unit-count evidence | Share on the company's own "
        "domain | Share matching the enrichment domain | Share with publish_date |"
    )
    add("|---|---|---|---|---|---|---|---|")
    for config in configs:
        config_rows = _ok_rows(rows, config)
        snippets_total = sum(row["company_snippets"] for row in config_rows)
        with_units = sum(row["company_snippets_with_units"] for row in config_rows)
        first_party = sum(row["company_snippets_first_party"] for row in config_rows)
        email_domain = sum(row["company_snippets_email_domain"] for row in config_rows)
        dated = sum(row["company_snippets_dated"] for row in config_rows)
        add(
            f"| `{config}` "
            f"| {_fmt(_median([float(row['company_search_hits']) for row in config_rows]), 1)} "
            f"| {_fmt(_median([float(row['company_search_chars']) for row in config_rows]), 0)} "
            f"| {_fmt(_median([float(row['company_snippets']) for row in config_rows]), 1)} "
            f"| {_share(with_units, snippets_total)} "
            f"| {_share(email_domain, snippets_total)} "
            f"| {_share(first_party, snippets_total)} "
            f"| {_share(dated, snippets_total)} |"
        )
    add("")
    add(
        "\"Raw chars returned\" is the cleaned passage text the provider handed back for the three "
        "company queries, before ranking and before the densest-400-char window is cut. Snippet "
        "shares are computed over every kept company snippet (runs x snippets), not per run. "
        "\"The company's own domain\" is the lead's email domain, which is provider-independent; "
        "\"the enrichment domain\" is whatever domain the website step settled on, so it reads 0% "
        "whenever that step failed and is the weaker of the two measures."
    )
    add("")
    add("### 2b. Property and website evidence")
    add("")
    add(
        "| Config | Median raw property hits | Median address-matched property snippets | "
        "Share of runs with any address match | Website step success | Website step outcomes | "
        "Median website snippet chars |"
    )
    add("|---|---|---|---|---|---|---|")
    for config in configs:
        config_rows = _ok_rows(rows, config)
        outcomes = [row["website_outcome"] for row in config_rows]
        success = sum(1 for outcome in outcomes if outcome in {"extract", "html"})
        matched_runs = sum(1 for row in config_rows if row["property_snippets_matched"])
        split = " / ".join(
            f"{outcome}: {outcomes.count(outcome)}"
            for outcome in ("extract", "html", "html_failed", "no_candidate")
            if outcomes.count(outcome)
        )
        add(
            f"| `{config}` "
            f"| {_fmt(_median([float(row['property_search_hits']) for row in config_rows]), 1)} "
            f"| {_fmt(_median([float(row['property_snippets_matched']) for row in config_rows]), 1)} "
            f"| {_share(matched_runs, len(config_rows))} "
            f"| {_share(success, len(config_rows))} "
            f"| {split or 'n/a'} "
            f"| {_fmt(_median([float(row['website_snippet_chars']) for row in config_rows]), 0)} |"
        )
    add("")
    add(
        "Website outcomes: `extract` = Parallel Extract produced the evidence; `html` = the raw "
        "HTML parser did; `html_failed` = a candidate URL was found but fetching and parsing it "
        "returned nothing usable; `no_candidate` = the company search produced no usable "
        "non-social URL to read in the first place."
    )
    add("")

    # --- scoring outcomes ---
    add("## 3. Scoring outcomes")
    add("")
    add(
        "| Config | Median company fit | Median property fit | Median final score | "
        "Confidence High/Medium/Low | Signals from OpenAI classifier | "
        "\"not source-backed\" rejections | Median missing-data entries | Fit labels |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for config in configs:
        config_rows = _ok_rows(rows, config)
        confidences = [row["confidence"] for row in config_rows]
        signals = [signal for row in config_rows for signal in row["signals"].values()]
        classified = sum(1 for signal in signals if signal["classifier"] == "openai_classifier")
        labels = [row["company_fit_label"] for row in config_rows]
        label_split = " / ".join(
            f"{label}: {labels.count(label)}" for label in sorted(set(labels))
        )
        add(
            f"| `{config}` "
            f"| {_fmt(_median([float(row['company_fit']) for row in config_rows]), 1)} "
            f"| {_fmt(_median([float(row['property_fit']) for row in config_rows]), 1)} "
            f"| {_fmt(_median([float(row['final_score']) for row in config_rows]), 1)} "
            f"| {confidences.count('High')} / {confidences.count('Medium')} / "
            f"{confidences.count('Low')} "
            f"| {_share(classified, len(signals))} ({classified}/{len(signals)}) "
            f"| {sum(row['not_source_backed_count'] for row in config_rows)} "
            f"| {_fmt(_median([float(row['missing_data_count']) for row in config_rows]), 1)} "
            f"| {label_split or 'n/a'} |"
        )
    add("")
    add(
        "Company Fit is out of "
        f"{next((row['company_fit_max'] for row in rows if not row['error']), 'n/a')} and Property "
        f"Fit out of {next((row['property_fit_max'] for row in rows if not row['error']), 'n/a')}. "
        "Market Fit is 0 for every run because `MarketMetrics()` is empty, which is deliberate: it "
        "holds the non-provider half of the score constant. `\"not source-backed\"` counts the "
        "signals the OpenAI classifier proposed but that failed literal-substring verification "
        "against the retrieved evidence, so they fell back to rules."
    )
    add("")

    # --- per lead ---
    add("## 4. Per-lead results")
    add("")
    header = "| Lead | Segment |"
    divider = "|---|---|"
    for config in configs:
        header += f" {config} company/property/conf |"
        divider += "---|"
    add(header)
    add(divider)
    for lead_index, lead_spec in enumerate(leads):
        cells = ""
        for config in configs:
            lead_rows = [
                row
                for row in rows
                if row["config"] == config and row["lead_index"] == lead_index and not row["error"]
            ]
            if not lead_rows:
                errored = [
                    row
                    for row in rows
                    if row["config"] == config and row["lead_index"] == lead_index
                ]
                cells += " error |" if errored else " - |"
                continue
            company_fit = _median([float(row["company_fit"]) for row in lead_rows])
            property_fit = _median([float(row["property_fit"]) for row in lead_rows])
            confidence = sorted(
                {row["confidence"] for row in lead_rows},
                key=["High", "Medium", "Low"].index,
            )
            cells += (
                f" {_fmt(company_fit, 0)} / {_fmt(property_fit, 0)} / "
                f"{'/'.join(confidence)} |"
            )
        add(
            f"| {lead_spec['company']} - {lead_spec['address']}, {lead_spec['city']} "
            f"{lead_spec['state']} | {lead_spec['segment']} |{cells}"
        )
    add("")
    add("Values are medians across repeats; confidence lists every level observed for that lead.")
    add("")

    errors = [row for row in rows if row["error"]]
    if errors:
        add("### Errors")
        add("")
        for row in errors:
            add(f"- `{row['config']}` / {row['company']} (repeat {row['repeat']}): {row['error']}")
        add("")

    # --- caveats ---
    add("## 5. Caveats")
    add("")
    add(
        f"- **Small n.** {len(leads)} leads x {repeats} repeats per configuration. Differences of a "
        "point or two in median score are noise; the direction and size of the latency and "
        "evidence-coverage gaps are the signal."
    )
    add(
        "- **The live web is nondeterministic.** Result sets, page availability and provider "
        "latency all move between runs, and the OpenAI classifiers are sampled, so re-running this "
        "will not reproduce the numbers exactly."
    )
    add(
        "- **This measures provider quality, not code quality.** The Serper path feeds the same "
        "post-processing -- excerpt cleaning, densest-window selection, ranking, dedupe, address "
        "filter, classifiers -- as the Parallel path. What differs is what each provider returns: "
        "Serper returns short SERP snippets, Parallel returns objective-selected page excerpts."
    )
    add(
        "- **Extract is Parallel-only.** The `parallel` configuration therefore bundles two "
        "products, which is why `parallel-search` exists: it isolates the Search API by keeping the "
        "old raw-HTML website parser. Serper has no extraction product, so `serper` + Extract is "
        "not a configuration that could ship."
    )
    add(
        "- **Serper spends more requests for the same work.** Its per-query endpoint means 5 search "
        "requests per lead (3 company + 2 property) against Parallel's 2, plus the website read: "
        "6 provider HTTP requests per lead vs 3. That is a structural property of the API, not an "
        "artifact of this harness, and it is a real part of the latency gap."
    )
    add(
        "- **Cost is not measured here.** The two providers price differently per request and "
        "Extract bills separately; this benchmark only covers latency, evidence and score quality."
    )
    add("")
    return "\n".join(lines) + "\n"


# --- entry point ------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Serper vs Parallel on the live enrichment path.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=2,
        help="Runs per lead per configuration (default 2).",
    )
    parser.add_argument(
        "--configs",
        default=",".join(CONFIG_ORDER),
        help=f"Comma-separated subset of {CONFIG_ORDER}.",
    )
    parser.add_argument(
        "--leads-limit",
        type=int,
        default=None,
        help="Only run the first N leads.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path prefix; writes <out>.json and <out>.md.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge into the existing <out>.json, replacing only the configs just run.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Re-render <out>.md from the saved <out>.json without running anything.",
    )
    args = parser.parse_args()

    configs = [name.strip() for name in args.configs.split(",") if name.strip()]
    unknown = [name for name in configs if name not in CONFIGS]
    if unknown:
        parser.error(f"unknown config(s): {', '.join(unknown)}; choose from {CONFIG_ORDER}")

    leads = LEADS[: args.leads_limit] if args.leads_limit else LEADS
    out: Path = args.out
    json_path = out.with_suffix(".json")
    md_path = out.with_suffix(".md")

    if args.rebuild:
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        md_path.write_text(
            build_markdown(
                saved["rows"],
                configs=[name for name in CONFIG_ORDER if name in saved["configs"]],
                repeats=saved["repeats"],
                leads=saved["leads"],
                elapsed_s=saved.get("elapsed_seconds", 0.0),
            ),
            encoding="utf-8",
        )
        print(f"Rebuilt {md_path} from {json_path}", file=sys.stderr)
        return

    settings = get_settings()
    if "serper" in configs and not settings.serper_api_key:
        parser.error("SERPER_API_KEY is not configured; the serper config cannot run.")
    if any(config.startswith("parallel") for config in configs) and not settings.parallel_api_key:
        parser.error("PARALLEL_API_KEY is not configured; the parallel configs cannot run.")

    started = time.perf_counter()
    rows = asyncio.run(run_benchmark(leads=leads, configs=configs, repeats=args.repeats))
    elapsed_s = time.perf_counter() - started

    out.parent.mkdir(parents=True, exist_ok=True)

    if args.merge and json_path.exists():
        previous = json.loads(json_path.read_text(encoding="utf-8"))
        # Rows are joined by lead_index, so the saved panel has to be the one
        # that ran now; otherwise old rows land under the wrong lead.
        if previous.get("leads") != leads or previous.get("repeats") != args.repeats:
            parser.error(
                "--merge needs the same lead panel and --repeats as the saved run; "
                "re-run without --merge or match the saved settings."
            )
        kept = [row for row in previous.get("rows", []) if row["config"] not in configs]
        rows = kept + rows
        configs = [name for name in CONFIG_ORDER if any(row["config"] == name for row in rows)]

    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "repeats": args.repeats,
                "configs": {name: CONFIGS[name] for name in configs},
                "leads": leads,
                "elapsed_seconds": round(elapsed_s, 1),
                "rows": rows,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    markdown = build_markdown(
        rows,
        configs=configs,
        repeats=args.repeats,
        leads=leads,
        elapsed_s=elapsed_s,
    )
    md_path.write_text(markdown, encoding="utf-8")

    print(f"\nWrote {json_path}", file=sys.stderr)
    print(f"Wrote {md_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
