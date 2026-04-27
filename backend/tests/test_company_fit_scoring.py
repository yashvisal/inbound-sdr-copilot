from app.models import LeadInput, MarketMetrics, SourceSnippet
from app.scoring import score_lead
from app.services.company import extract_company_signals


def _lead(
    company: str = "Harbor Residential",
    email: str = "maya@harborresidential.com",
    address: str = "The Morrison Apartments, 123 Main St",
) -> LeadInput:
    return LeadInput(
        name="Maya Chen",
        email=email,
        company=company,
        address=address,
        city="Austin",
        state="TX",
        country="US",
    )


def _strong_market() -> MarketMetrics:
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


def test_property_operator_with_volume_and_workflow_signals_scores_high() -> None:
    lead = _lead()
    enrichment = extract_company_signals(
        lead=lead,
        domain="harborresidential.com",
        website_title="Harbor Residential Property Management",
        website_description=(
            "Multifamily property management for apartment communities with "
            "8,500 units across regional markets."
        ),
        website_snippet=(
            "Our onsite teams manage leasing inquiries, tour scheduling, "
            "resident communication, maintenance requests, renewals, and rent collection."
        ),
    )

    score = score_lead(
        lead=lead,
        market_metrics=_strong_market(),
        company_enrichment=enrichment,
        timing_signals=[],
    )

    assert score.company_fit.score >= 13
    assert score.property_fit.score == 6
    assert score.company_fit_label == "Unclear fit"
    assert score.company_fit_breakdown is not None
    assert score.company_fit_breakdown.score_breakdown["leasing_volume"] == 4
    assert score.company_fit_breakdown.score_breakdown["operational_complexity"] == 4
    assert score.company_fit_breakdown.score_breakdown["product_fit"] == 5
    assert set(score.company_fit_breakdown.extraction_audit) == {
        "leasing_volume",
        "operational_complexity",
        "product_fit",
    }
    assert all(
        audit.raw_evidence for audit in score.company_fit_breakdown.extraction_audit.values()
    )


def test_recent_activity_improves_timing_not_company_fit() -> None:
    lead = _lead()
    base_enrichment = extract_company_signals(
        lead=lead,
        website_description=(
            "Multifamily property management for apartment communities with resident "
            "communication and leasing operations."
        ),
    )
    active_enrichment = extract_company_signals(
        lead=lead,
        website_description=(
            "Multifamily property management for apartment communities with resident "
            "communication and leasing operations. Recently announced a new acquisition."
        ),
    )

    base_score = score_lead(lead, _strong_market(), company_enrichment=base_enrichment)
    active_score = score_lead(lead, _strong_market(), company_enrichment=active_enrichment)

    assert active_score.company_fit.score == base_score.company_fit.score
    assert active_score.timing.score > base_score.timing.score


def test_unrelated_company_is_capped_despite_strong_market() -> None:
    lead = _lead(
        company="Atlas DevTools",
        email="maya@atlasdevtools.com",
        address="100 Office Park Dr",
    )
    enrichment = extract_company_signals(
        lead=lead,
        domain="atlasdevtools.com",
        website_description="Developer productivity software for enterprise engineering teams.",
    )

    score = score_lead(
        lead=lead,
        market_metrics=_strong_market(),
        company_enrichment=enrichment,
        timing_signals=[],
    )

    assert score.final_score <= 60
    assert score.company_fit_label == "Poor fit"


def test_missing_company_data_defaults_to_neutral_property_fit() -> None:
    lead = _lead(company="Unknown Co", email="maya@gmail.com", address="123 Main St")
    enrichment = extract_company_signals(lead=lead)

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=enrichment,
        timing_signals=[],
    )

    assert score.property_fit.score == 3
    assert "neutral" in score.property_fit.reasons[0]


def test_search_snippets_feed_extracted_signals_for_offline_edge_cases() -> None:
    lead = _lead()
    enrichment = extract_company_signals(
        lead=lead,
        search_snippets=[
            SourceSnippet(
                source="Test",
                title="Harbor Residential portfolio",
                snippet=(
                    "Harbor Residential manages apartment communities and 12,000 units "
                    "with centralized leasing and resident communication teams."
                ),
            )
        ],
    )

    assert "12,000 units" in enrichment.leasing_volume_signals
    assert "centralized leasing" in enrichment.product_fit_signals
    assert "resident" in enrichment.operational_complexity_signals


def test_implicit_global_scale_scores_large_operator_without_unit_count() -> None:
    lead = _lead(company="Greystar", address="Sample Apartments, 123 Main St")
    enrichment = extract_company_signals(
        lead=lead,
        website_description=(
            "Greystar is a multifamily apartment operator with a global portfolio "
            "across markets and centralized leasing operations."
        ),
    )

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    audit = score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.interpreted_bucket == "Very High"
    assert score.company_fit_breakdown.score_breakdown["leasing_volume"] == 13


def test_company_level_office_language_does_not_pollute_property_fit() -> None:
    lead = _lead(company="Mixed Portfolio PM", address="Sample Apartments, 123 Main St")
    enrichment = extract_company_signals(
        lead=lead,
        website_description=(
            "Property management company with office staff supporting apartment communities."
        ),
    )

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert "office" not in enrichment.negative_property_signals
    assert score.property_fit.score == 6
