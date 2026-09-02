import asyncio

from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.models import (
    AnalyzeLeadsRequest,
    CompanyEnrichment,
    LeadAnalysis,
    LeadInput,
    MarketMetrics,
    SourceSnippet,
)
from app.scoring import score_lead
from app.services import company as company_service
from app.services import enrichment as enrichment_service
from app.services import lead_processing
from app.services import run_store
from app.services.company import CompanyEnrichmentResult, extract_company_signals
from app.services.enrichment import EnrichmentBundle
from app.services.web_search import (
    WebExtractPage,
    WebExtractResult,
    WebSearchHit,
    WebSearchResult,
)


def _lead() -> LeadInput:
    return LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="The Morrison Apartments, 123 Main St",
        city="Austin",
        state="TX",
        country="US",
    )


def _market_metrics() -> MarketMetrics:
    return MarketMetrics(
        population=979_539,
        population_growth_rate=0.014,
        median_gross_rent=1_850,
        median_income=91_461,
        renter_share=0.55,
        housing_units=465_000,
        vacancy_rate=0.08,
        no_vehicle_household_share=0.12,
        public_transit_commute_share=0.06,
        walking_commute_share=0.10,
    )


def _company_enrichment(lead: LeadInput) -> CompanyEnrichment:
    return extract_company_signals(
        lead=lead,
        website_title="Harbor Residential Property Management",
        website_description=(
            "Multifamily property management for apartment communities with "
            "8,500 units across regional markets."
        ),
        website_snippet=(
            "Our teams manage leasing inquiries, tour scheduling, resident communication, "
            "maintenance requests, renewals, and rent collection."
        ),
        property_search_snippets=[
            SourceSnippet(
                source="Test",
                title="The Morrison Apartments",
                snippet="The Morrison Apartments has 240 apartment units and available floor plans.",
            )
        ],
    )


def test_nested_lead_request_normalizes_to_lead_input() -> None:
    request = AnalyzeLeadsRequest.model_validate(
        {
            "leads": [
                {
                    "person": {
                        "Name": "Maya Chen",
                        "Email Address": "maya@harborresidential.com",
                        "Company": "Harbor Residential",
                    },
                    "building": {
                        "Property Address": "The Morrison Apartments, 123 Main St",
                        "City": "Austin",
                        "State": "TX",
                        "Country": "US",
                    },
                }
            ]
        }
    )

    [lead] = request.to_lead_inputs()

    assert lead == _lead()


def test_analyze_endpoint_accepts_nested_and_flattened_payloads(monkeypatch) -> None:
    async def fake_enrich_lead(lead: LeadInput) -> EnrichmentBundle:
        return EnrichmentBundle(
            market_metrics=_market_metrics(),
            company_enrichment=_company_enrichment(lead),
            evidence=[
                SourceSnippet(
                    source="Test",
                    title="Source-backed reason",
                    snippet="Evidence was collected once for this lead.",
                )
            ],
            missing_data=[],
            address_resolution=None,
        )

    monkeypatch.setattr(lead_processing, "enrich_lead", fake_enrich_lead)
    client = TestClient(app)

    response = client.post(
        "/api/leads/analyze",
        json={
            "leads": [
                {
                    "person": {
                        "name": "Maya Chen",
                        "email": "maya@harborresidential.com",
                        "company": "Harbor Residential",
                    },
                    "building": {
                        "address": "The Morrison Apartments, 123 Main St",
                        "city": "Austin",
                        "state": "TX",
                        "country": "US",
                    },
                },
                {
                    "name": "Jordan Lee",
                    "email": "jordan@harborresidential.com",
                    "company": "Harbor Residential",
                    "address": "The Morrison Apartments, 123 Main St",
                    "city": "Austin",
                    "state": "TX",
                    "country": "US",
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["leads"]) == 2

    analyzed = body["leads"][0]
    score = analyzed["score"]
    assert isinstance(score["final_score"], int)
    assert score["priority"] in {"High", "Medium", "Low"}
    assert score["confidence"] in {"High", "Medium", "Low"}
    assert score["market_fit"]["reasons"]
    assert score["company_fit"]["reasons"]
    assert score["property_fit"]["reasons"]
    assert score["company_fit_breakdown"]
    assert score["property_fit_breakdown"]
    assert analyzed["why_this_lead"]
    assert analyzed["sales_insights"]
    assert analyzed["evidence"]
    assert "company_fit_breakdown" not in analyzed
    assert "property_fit_breakdown" not in analyzed


def test_enrich_lead_runs_market_and_company_branches_concurrently(monkeypatch) -> None:
    order: list[str] = []

    async def fake_enrich_market(lead: LeadInput):
        order.append("market_start")
        await asyncio.sleep(0.05)
        order.append("market_end")
        return type(
            "MarketResult",
            (),
            {
                "metrics": _market_metrics(),
                "evidence": [],
                "missing_data": [],
                "address_resolution": None,
            },
        )()

    async def fake_enrich_company(lead: LeadInput):
        order.append("company_start")
        await asyncio.sleep(0.01)
        order.append("company_end")
        return CompanyEnrichmentResult(
            enrichment=_company_enrichment(lead),
            evidence=[],
            missing_data=[],
        )

    monkeypatch.setattr(enrichment_service, "enrich_market", fake_enrich_market)
    monkeypatch.setattr(enrichment_service, "enrich_company", fake_enrich_company)

    asyncio.run(enrichment_service.enrich_lead(_lead()))

    assert order.index("company_start") < order.index("market_end")


def test_enrich_lead_preserves_partial_result_when_one_branch_fails(monkeypatch) -> None:
    async def fake_enrich_market(lead: LeadInput):
        return type(
            "MarketResult",
            (),
            {
                "metrics": _market_metrics(),
                "evidence": [SourceSnippet(source="Market", snippet="Market evidence")],
                "missing_data": [],
                "address_resolution": None,
            },
        )()

    async def fake_enrich_company(lead: LeadInput):
        raise RuntimeError("company service unavailable")

    monkeypatch.setattr(enrichment_service, "enrich_market", fake_enrich_market)
    monkeypatch.setattr(enrichment_service, "enrich_company", fake_enrich_company)

    result = asyncio.run(enrichment_service.enrich_lead(_lead()))

    assert result.market_metrics.population == 979_539
    assert result.company_enrichment.source_text
    assert result.evidence[0].source == "Market"
    assert "Company/property enrichment failed unexpectedly." in result.missing_data


def test_company_enrichment_fetches_evidence_once_then_runs_classifiers_concurrently(
    monkeypatch,
) -> None:
    counts = {
        "company_search": 0,
        "property_search": 0,
        "osm": 0,
        "extract": 0,
        "website": 0,
    }
    order: list[str] = []

    async def fake_fetch_search_snippets(lead: LeadInput):
        counts["company_search"] += 1
        return company_service.SearchEvidence(
            snippets=[
                SourceSnippet(
                    source="Serper",
                    title="Harbor Residential",
                    url="https://harbor.example",
                    snippet="Harbor manages apartment communities and leasing operations.",
                )
            ],
            missing_data=[],
            session_id="session_1",
        )

    async def fake_fetch_property_search_snippets(
        lead: LeadInput,
        *,
        osm_display_name: str | None = None,
    ):
        counts["property_search"] += 1
        return [
            SourceSnippet(
                source="Serper Property",
                title="The Morrison Apartments",
                snippet="The Morrison Apartments has available units and floor plans.",
            )
        ], []

    async def fake_fetch_osm_address_metadata(address: str, city: str, state: str):
        counts["osm"] += 1
        return None

    async def fake_extract_urls(**kwargs):
        counts["extract"] += 1
        return WebExtractResult(warnings=["no extraction provider"])

    async def fake_fetch_website_metadata(url: str):
        counts["website"] += 1
        return CompanyEnrichment(
            website_url=url,
            website_title="Harbor Residential",
            website_description="Property management for multifamily apartment communities.",
            website_snippet="Leasing inquiries, resident communication, and maintenance operations.",
        )

    async def fake_classify_company_signals(**kwargs):
        order.append("company_classifier_start")
        await asyncio.sleep(0.05)
        order.append("company_classifier_end")
        return {}, None

    async def fake_classify_property_signals(**kwargs):
        order.append("property_classifier_start")
        await asyncio.sleep(0.01)
        order.append("property_classifier_end")
        return {}, None

    monkeypatch.setattr(company_service, "_fetch_search_snippets", fake_fetch_search_snippets)
    monkeypatch.setattr(
        company_service,
        "_fetch_property_search_snippets",
        fake_fetch_property_search_snippets,
    )
    monkeypatch.setattr(
        company_service,
        "fetch_osm_address_metadata",
        fake_fetch_osm_address_metadata,
    )
    monkeypatch.setattr(company_service, "extract_urls", fake_extract_urls)
    monkeypatch.setattr(
        company_service,
        "_fetch_website_metadata",
        fake_fetch_website_metadata,
    )
    monkeypatch.setattr(
        company_service,
        "classify_company_signals",
        fake_classify_company_signals,
    )
    monkeypatch.setattr(
        company_service,
        "classify_property_signals",
        fake_classify_property_signals,
    )

    asyncio.run(company_service.enrich_company(_lead()))

    assert counts == {
        "company_search": 1,
        "property_search": 1,
        "osm": 1,
        "extract": 1,
        "website": 1,
    }
    assert order.index("property_classifier_start") < order.index("company_classifier_end")


def test_company_search_maps_web_hits_to_provider_neutral_snippets(monkeypatch) -> None:
    """Evidence is labeled by kind, not by whichever vendor answered the search."""

    captured: dict = {}

    async def fake_search_web(**kwargs):
        captured.update(kwargs)
        return WebSearchResult(
            hits=[
                WebSearchHit(
                    url="https://harbor.example/about",
                    title="About Harbor Residential",
                    publish_date="2025-04-01",
                    passages=[
                        "Harbor Residential manages 42,000 apartment units.",
                        "It operates 180 communities across 14 states.",
                    ],
                )
            ],
            provider="parallel",
        )

    monkeypatch.setattr(company_service, "search_web", fake_search_web)

    search = asyncio.run(company_service._fetch_search_snippets(_lead()))
    snippets = search.snippets

    assert search.missing_data == []
    assert [snippet.source for snippet in snippets] == ["Web search"]
    assert snippets[0].url == "https://harbor.example/about"
    assert snippets[0].publish_date == "2025-04-01"
    # The longest passage leads, and every passage survives into the snippet.
    assert snippets[0].snippet == (
        "Harbor Residential manages 42,000 apartment units. "
        "It operates 180 communities across 14 states."
    )
    assert captured["mode"] == "fast"
    assert captured["queries"][0] == "Harbor Residential"


def test_company_search_snippet_skips_page_navigation_for_the_dense_window(monkeypatch) -> None:
    """Whole-page results start with nav, so the snippet must not be the head."""

    nav = "Home Careers Blog Contact us Select Country English Remember this selection. "
    evidence = (
        "Harbor Residential manages 42,000 apartment units and operates 180 "
        "communities for residents across 14 markets. "
    )

    async def fake_search_web(**kwargs):
        return WebSearchResult(
            hits=[
                WebSearchHit(
                    url="https://harbor.example/",
                    title="Harbor Residential",
                    passages=[nav * 6 + evidence + nav * 6],
                )
            ],
            provider="parallel",
        )

    monkeypatch.setattr(company_service, "search_web", fake_search_web)
    snippets = asyncio.run(company_service._fetch_search_snippets(_lead())).snippets

    assert len(snippets) == 1
    assert "42,000 apartment units" in snippets[0].snippet
    assert len(snippets[0].snippet) <= 400


def test_company_search_reports_missing_provider_without_naming_a_vendor(monkeypatch) -> None:
    async def fake_search_web(**kwargs):
        return WebSearchResult(
            warnings=["Web search skipped because no search provider is configured."]
        )

    monkeypatch.setattr(company_service, "search_web", fake_search_web)

    search = asyncio.run(company_service._fetch_search_snippets(_lead()))

    assert search.snippets == []
    assert search.missing_data == [
        "Web search skipped because no search provider is configured."
    ]


def _company_snippet(url: str, *, title: str = "Harbor Residential") -> SourceSnippet:
    return SourceSnippet(
        source="Web search",
        title=title,
        url=url,
        snippet="Harbor Residential manages apartment communities.",
    )


def test_website_candidates_prefer_about_pages_over_the_homepage() -> None:
    """A homepage is listings and nav; the about page says what the company is."""

    candidates = company_service._website_candidate_urls(
        [
            _company_snippet("https://www.linkedin.com/company/harbor", title="LinkedIn"),
            _company_snippet("https://harbor.example/news/q3-results", title="Q3 results"),
            _company_snippet("https://harbor.example/property-management", title="Services"),
            _company_snippet("https://harbor.example/about-us", title="About us"),
        ]
    )

    assert candidates == [
        "https://harbor.example/about-us",
        "https://harbor.example/property-management",
        "https://harbor.example/",
    ]


def test_website_candidates_fall_back_to_the_homepage_and_primary_url() -> None:
    candidates = company_service._website_candidate_urls(
        [
            _company_snippet("https://facebook.com/harbor", title="Facebook"),
            _company_snippet("https://harbor.example/news/q3-results", title="Q3 results"),
        ]
    )

    assert candidates == [
        "https://harbor.example/",
        "https://harbor.example/news/q3-results",
    ]
    assert company_service._website_candidate_urls([]) == []


def test_website_step_uses_the_densest_extracted_page(monkeypatch) -> None:
    captured: dict = {}

    async def fake_extract_urls(**kwargs):
        captured.update(kwargs)
        return WebExtractResult(
            pages=[
                WebExtractPage(
                    url="https://harbor.example/",
                    title="Harbor Residential",
                    passages=["Find your next home. Search apartments by city and price."],
                ),
                WebExtractPage(
                    url="https://harbor.example/about-us",
                    title="About Harbor Residential",
                    publish_date="2025-05-02",
                    passages=[
                        "Harbor Residential is a multifamily property manager.",
                        "Harbor Residential manages 42,000 apartment units across "
                        "180 communities and 14 markets for its residents.",
                    ],
                ),
            ],
            provider="parallel",
        )

    async def fail_fetch_website_metadata(url: str):
        raise AssertionError("extraction succeeded, so the HTML parser must not run")

    monkeypatch.setattr(company_service, "extract_urls", fake_extract_urls)
    monkeypatch.setattr(
        company_service,
        "_fetch_website_metadata",
        fail_fetch_website_metadata,
    )

    evidence = asyncio.run(
        company_service._fetch_website_evidence(
            ["https://harbor.example/about-us", "https://harbor.example/"],
            lead=_lead(),
            primary_url="https://harbor.example/about-us",
            session_id="session_1",
        )
    )

    assert evidence is not None
    assert evidence.enrichment.website_url == "https://harbor.example/about-us"
    assert evidence.enrichment.domain == "harbor.example"
    assert evidence.enrichment.website_title == "About Harbor Residential"
    assert evidence.publish_date == "2025-05-02"
    assert "42,000 apartment units" in evidence.enrichment.website_snippet
    assert captured["session_id"] == "session_1"
    assert captured["urls"] == ["https://harbor.example/about-us", "https://harbor.example/"]
    assert "Harbor Residential" in captured["objective"]


def test_website_step_falls_back_to_the_html_parser_when_extract_is_empty(monkeypatch) -> None:
    fetched: list[str] = []

    async def fake_extract_urls(**kwargs):
        return WebExtractResult(
            errors={"https://harbor.example/about-us": "fetch_failed (HTTP 403)"},
            warnings=["Page content extraction failed; fell back to reading the page directly."],
        )

    async def fake_fetch_website_metadata(url: str):
        fetched.append(url)
        return CompanyEnrichment(
            website_url=url,
            website_title="Harbor Residential",
            website_snippet="Multifamily property management for apartment communities.",
        )

    monkeypatch.setattr(company_service, "extract_urls", fake_extract_urls)
    monkeypatch.setattr(
        company_service,
        "_fetch_website_metadata",
        fake_fetch_website_metadata,
    )

    evidence = asyncio.run(
        company_service._fetch_website_evidence(
            ["https://harbor.example/about-us", "https://harbor.example/"],
            lead=_lead(),
            primary_url="https://harbor.example/",
        )
    )

    assert evidence is not None
    assert fetched == ["https://harbor.example/"]
    assert evidence.enrichment.website_title == "Harbor Residential"
    assert evidence.publish_date is None


def test_website_step_reports_nothing_when_extract_and_the_parser_both_fail(monkeypatch) -> None:
    async def fake_extract_urls(**kwargs):
        return WebExtractResult()

    async def fake_fetch_website_metadata(url: str):
        return None

    monkeypatch.setattr(company_service, "extract_urls", fake_extract_urls)
    monkeypatch.setattr(
        company_service,
        "_fetch_website_metadata",
        fake_fetch_website_metadata,
    )

    assert (
        asyncio.run(
            company_service._fetch_website_evidence(
                ["https://harbor.example/"],
                lead=_lead(),
                primary_url="https://harbor.example/",
            )
        )
        is None
    )


def _lead_payload(index: int) -> dict:
    return {
        "name": f"Lead {index}",
        "email": f"lead{index}@harborresidential.com",
        "company": "Harbor Residential",
        "address": f"{100 + index} Main St",
        "city": "Austin",
        "state": "TX",
        "country": "US",
    }


def test_oversized_batch_is_rejected_before_any_quota_is_spent(monkeypatch) -> None:
    """Sequential enrichment cannot fit an unbounded batch in one request."""

    reserved: list[int] = []

    async def fake_reserve(*, ip: str, count: int):
        reserved.append(count)
        return None

    monkeypatch.setattr(run_store, "reserve_run_slots", fake_reserve)
    client = TestClient(app)

    oversized = [_lead_payload(index) for index in range(main.MAX_LEADS_PER_REQUEST + 1)]
    response = client.post("/api/leads/analyze", json={"leads": oversized})

    assert response.status_code == 413
    assert response.json()["reason"] == "batch_too_large"
    assert reserved == []


def test_failed_analysis_releases_the_reserved_quota(monkeypatch) -> None:
    released: list[int] = []

    async def fake_reserve(*, ip: str, count: int):
        return None

    async def fake_release(*, ip: str, count: int) -> None:
        released.append(count)

    async def exploding_process(leads):
        raise RuntimeError("enrichment blew up")

    monkeypatch.setattr(run_store, "reserve_run_slots", fake_reserve)
    monkeypatch.setattr(run_store, "release_run_slots", fake_release)
    monkeypatch.setattr(main, "process_leads", exploding_process)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/leads/analyze", json={"leads": [_lead_payload(1)]})

    assert response.status_code == 500
    assert released == [1]


def test_stored_contacts_are_served_as_stored(monkeypatch) -> None:
    """Demo leads use invented contacts, so nothing is blurred on the way out."""

    analysis = _analysis_payload()

    async def fake_list_runs(limit: int = 200):
        return [
            {
                "id": "community-run",
                "source": "community",
                "created_at": "2026-08-05T00:00:00+00:00",
                "analysis": analysis,
            },
            {
                "id": "sample-run",
                "source": "sample",
                "created_at": "2026-08-05T00:00:00+00:00",
                "analysis": analysis,
            },
        ]

    monkeypatch.setattr(run_store, "list_runs", fake_list_runs)
    client = TestClient(app)

    runs = client.get("/api/leads").json()["runs"]
    for run in runs:
        assert run["analysis"]["lead"]["email"] == "maya@harborresidential.com"
        assert run["analysis"]["lead"]["address"] == "123 Main St"


def _analysis_payload() -> dict:
    """A minimal stored analysis, shaped like one the run store would hold."""

    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="123 Main St",
        city="Austin",
        state="TX",
        country="US",
    )
    enrichment = _company_enrichment(lead)
    analysis = LeadAnalysis(
        lead=lead,
        score=score_lead(
            lead=lead,
            market_metrics=_market_metrics(),
            company_enrichment=enrichment,
        ),
        market_metrics=_market_metrics(),
        company_enrichment=enrichment,
        outreach_email="",
        follow_ups=[],
    )
    return analysis.model_dump(mode="json")
