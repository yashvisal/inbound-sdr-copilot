import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.models import (
    AddressResolution,
    CompanyEnrichment,
    LeadAnalysis,
    LeadInput,
    MarketMetrics,
    OutreachGenerationResponse,
    ScoreBreakdown,
    ScoreSection,
    SourceSnippet,
)
from app.outreach import build_outreach_email
from app.services import outreach as outreach_service


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


def _analysis(priority: str = "High", final_score: int = 88) -> LeadAnalysis:
    lead = _lead()
    score = ScoreBreakdown(
        market_fit=ScoreSection(
            score=28,
            max_score=30,
            reasons=[
                "Austin has strong renter demand and elevated multifamily activity.",
                "The submarket shows healthy rent levels for leasing automation ROI.",
            ],
        ),
        company_fit=ScoreSection(
            score=32,
            max_score=40,
            reasons=[
                "Harbor Residential manages multifamily communities at regional scale.",
                "The company signals leasing, resident communication, and renewals workload.",
            ],
        ),
        property_fit=ScoreSection(
            score=28,
            max_score=30,
            reasons=[
                "The Morrison Apartments appears to be a multifamily asset with active floor plans.",
                "The property context supports a concrete leasing operations pitch.",
            ],
        ),
        final_score=final_score,
        priority=priority,
        company_fit_label="Strong fit" if priority == "High" else "Unclear fit",
        confidence="High" if priority == "High" else "Medium",
    )
    return LeadAnalysis(
        lead=lead,
        score=score,
        address_resolution=AddressResolution(
            confidence="High",
            method="test",
            input_address=lead.address,
            matched_address=lead.address,
        ),
        market_metrics=MarketMetrics(
            population=979_539,
            median_gross_rent=1_850,
            renter_share=0.55,
            vacancy_rate=0.08,
            multifamily_share=0.42,
        ),
        company_enrichment=CompanyEnrichment(
            website_title="Harbor Residential",
            website_description="Regional multifamily property management.",
            leasing_volume_signals=["8,500 managed units", "active apartment floor plans"],
            operational_complexity_signals=[
                "leasing inquiries",
                "tour scheduling",
                "resident communication",
            ],
            product_fit_signals=["multifamily property management"],
            property_signals=["240-unit apartment community"],
        ),
        evidence=[
            SourceSnippet(
                source="Test",
                title="Harbor Residential overview",
                url="https://example.com/harbor",
                snippet="Harbor Residential manages apartment communities with leasing teams.",
            )
        ],
        missing_data=[],
        why_this_lead=["High leasing volume makes response speed a likely pain point."],
        sales_insights=["Regional multifamily scale creates repeatable leasing workflows."],
        outreach_email=build_outreach_email(lead, score),
        follow_ups=[],
    )


def test_generate_outreach_endpoint_returns_model_payload(monkeypatch) -> None:
    async def fake_generate_outreach(
        lead: LeadInput,
        analysis: LeadAnalysis,
    ) -> OutreachGenerationResponse:
        return OutreachGenerationResponse(
            sales_insights=[
                "Insight one",
                "Insight two",
                "Insight three",
                "Insight four",
            ],
            personalized_email=f"Hi {lead.name}, this is a relevant note for {analysis.lead.company}.",
        )

    monkeypatch.setattr(main, "generate_outreach", fake_generate_outreach)
    lead = _lead()
    analysis = _analysis()
    client = TestClient(app)

    response = client.post(
        "/api/leads/generate-outreach",
        json={
            "lead": lead.model_dump(mode="json"),
            "analysis": analysis.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["sales_insights"]) == 4
    assert body["personalized_email"]
    assert "persona" not in body


def test_generate_outreach_parses_responses_payload(monkeypatch) -> None:
    async def fake_call_openai_outreach(**kwargs):
        return {
            "sales_insights": [
                "Prioritize leasing speed because renter demand is strong.",
                "Frame ROI around reducing repetitive inquiry follow-up.",
                "Use the apartment context to make the note concrete.",
                "Connect resident communication workload to onsite team capacity.",
            ],
            "personalized_email": "Hi Maya,\n\nHarbor Residential looks like a strong fit.\n\nBest,",
        }

    monkeypatch.setattr(
        outreach_service,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_outreach_model="gpt-5.5"),
    )
    monkeypatch.setattr(outreach_service, "_call_openai_outreach", fake_call_openai_outreach)

    result = asyncio.run(outreach_service.generate_outreach(_lead(), _analysis()))

    assert len(result.sales_insights) == 4
    assert result.personalized_email.startswith("Hi Maya")


@pytest.mark.parametrize(
    ("priority", "final_score"),
    [("High", 88), ("Low", 42)],
)
def test_generate_outreach_falls_back_for_high_and_low_scores(
    monkeypatch,
    priority: str,
    final_score: int,
) -> None:
    async def fake_call_openai_outreach(**kwargs):
        raise ValueError("model unavailable")

    monkeypatch.setattr(
        outreach_service,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_outreach_model="gpt-5.5"),
    )
    monkeypatch.setattr(outreach_service, "_call_openai_outreach", fake_call_openai_outreach)

    result = asyncio.run(
        outreach_service.generate_outreach(
            _lead(),
            _analysis(priority=priority, final_score=final_score),
        )
    )

    assert 4 <= len(result.sales_insights) <= 5
    assert result.personalized_email
    assert "Hi Maya Chen" in result.personalized_email
