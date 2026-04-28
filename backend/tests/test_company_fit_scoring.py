from app.models import LeadInput, MarketMetrics, MicroSignalClassification, SourceSnippet
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
    )

    assert score.company_fit.score >= 13
    assert score.property_fit.score == 16
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


def test_recent_activity_does_not_change_fit_scores() -> None:
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
    assert active_score.property_fit.score == base_score.property_fit.score
    assert active_score.final_score == base_score.final_score


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
    )

    assert score.property_fit.score == 8
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
    assert score.property_fit.score == 16


def test_property_fit_uses_structured_property_classifications() -> None:
    lead = _lead(address="The Morrison Apartments, 123 Main St")
    enrichment = extract_company_signals(lead=lead)
    enrichment.property_classifications = {
        "property_type": MicroSignalClassification(
            raw_evidence="The Morrison Apartments offers apartment homes",
            evidence_source="search_snippets[0]",
            parsed_value="apartment homes",
            interpreted_bucket="Multifamily",
            confidence="High",
        ),
        "property_scale": MicroSignalClassification(
            raw_evidence="240 apartment units",
            evidence_source="search_snippets[0]",
            parsed_value="240 apartment units",
            interpreted_bucket="Medium",
            confidence="High",
        ),
        "leasing_activity": MicroSignalClassification(
            raw_evidence="Now leasing with available units",
            evidence_source="search_snippets[0]",
            parsed_value="available units",
            interpreted_bucket="Active",
            confidence="High",
        ),
    }

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert score.property_fit.score == 16
    assert score.property_fit_breakdown is not None
    assert score.property_fit_breakdown.score_breakdown == {
        "property_type": 6,
        "property_scale": 6,
        "leasing_activity": 4,
    }
    assert (
        score.property_fit_breakdown.extraction_audit["property_scale"].interpreted_bucket
        == "Large"
    )


def test_osm_property_type_overrides_noisy_search_classification() -> None:
    lead = _lead(address="1 Apple Park Way, Cupertino, CA 95014")
    enrichment = extract_company_signals(
        lead=lead,
        property_search_snippets=[
            SourceSnippet(
                source="Serper Property",
                title="Apartments near Apple Park",
                snippet="Find apartments near 1 Apple Park Way with available units.",
            )
        ],
        osm_property_type="bench",
        osm_display_name="1, Apple Park Way, Cupertino, California",
    )
    enrichment.property_classifications = {
        "property_type": MicroSignalClassification(
            raw_evidence="Apartments near Apple Park",
            evidence_source="search_snippets[0]",
            parsed_value="apartments",
            interpreted_bucket="Multifamily",
            confidence="High",
        ),
        "property_scale": MicroSignalClassification(
            raw_evidence="500 apartments near Apple Park",
            evidence_source="search_snippets[0]",
            parsed_value="500 apartments",
            interpreted_bucket="Large",
            confidence="High",
        ),
        "leasing_activity": MicroSignalClassification(
            raw_evidence="Apartments near Apple Park are available",
            evidence_source="search_snippets[0]",
            parsed_value="available apartments",
            interpreted_bucket="Active",
            confidence="High",
        ),
    }

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert score.property_fit.score == 8
    assert score.property_fit_breakdown is not None
    assert (
        score.property_fit_breakdown.extraction_audit["property_type"].evidence_source
        is None
    )
    assert (
        score.property_fit_breakdown.extraction_audit["property_type"].interpreted_bucket
        == "Unknown"
    )


def test_validated_commercial_search_overrides_osm_residential_type() -> None:
    lead = _lead(address="5801 Tennyson Pkwy, Plano, TX 75024")
    enrichment = extract_company_signals(
        lead=lead,
        property_search_snippets=[
            SourceSnippet(
                source="Serper Property",
                title="5801 Tennyson Pkwy Plano TX 75024",
                snippet="5801 Tennyson Pkwy is office space available for lease.",
            )
        ],
        osm_property_type="house",
        osm_display_name="5801 Tennyson Parkway, Plano, Texas",
    )
    enrichment.property_classifications = {
        "property_type": MicroSignalClassification(
            raw_evidence="5801 Tennyson Pkwy is office space",
            evidence_source="search_snippets[0]",
            parsed_value="office space",
            interpreted_bucket="Commercial",
            confidence="High",
        ),
        "leasing_activity": MicroSignalClassification(
            raw_evidence="available for lease",
            evidence_source="search_snippets[0]",
            parsed_value="available for lease",
            interpreted_bucket="Active",
            confidence="High",
        ),
    }

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert score.property_fit.score <= 6
    assert score.property_fit_breakdown is not None
    assert (
        score.property_fit_breakdown.extraction_audit["property_type"].evidence_source
        == "search_snippets[0]"
    )
    assert (
        score.property_fit_breakdown.extraction_audit["property_type"].interpreted_bucket
        == "Commercial"
    )


def test_osm_generic_building_falls_back_to_structured_classification() -> None:
    lead = _lead(address="The Morrison Apartments, 123 Main St")
    enrichment = extract_company_signals(
        lead=lead,
        osm_property_class="building",
        osm_property_type="yes",
    )
    enrichment.property_classifications = {
        "property_type": MicroSignalClassification(
            raw_evidence="The Morrison Apartments offers apartment homes",
            evidence_source="search_snippets[0]",
            parsed_value="apartment homes",
            interpreted_bucket="Multifamily",
            confidence="High",
        )
    }

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert score.property_fit_breakdown is not None
    assert (
        score.property_fit_breakdown.extraction_audit["property_type"].evidence_source
        == "search_snippets[0]"
    )
    assert score.property_fit_breakdown.score_breakdown["property_type"] == 6


def test_unclear_property_fit_uses_stable_neutral_defaults() -> None:
    lead = _lead(company="Unknown Co", email="maya@gmail.com", address="123 Main St")
    enrichment = extract_company_signals(lead=lead)

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert score.property_fit.score == 8
    assert score.property_fit_breakdown is not None
    assert score.property_fit_breakdown.score_breakdown == {
        "property_type": 3,
        "property_scale": 3,
        "leasing_activity": 2,
    }


def test_commercial_property_search_evidence_scores_low_property_fit() -> None:
    lead = _lead(address="100 Office Park Dr")
    enrichment = extract_company_signals(
        lead=lead,
        property_search_snippets=[
            SourceSnippet(
                source="Serper Property",
                title="100 Office Park Dr",
                snippet="Class A office building with medical office suites and workplace amenities.",
            )
        ],
    )

    score = score_lead(lead, MarketMetrics(), company_enrichment=enrichment)

    assert score.property_fit.score <= 5
    assert score.property_fit_breakdown is not None
    assert (
        score.property_fit_breakdown.extraction_audit["property_type"].interpreted_bucket
        == "Commercial"
    )
