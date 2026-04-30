import asyncio
from types import SimpleNamespace

from app.models import CompanyEnrichment, LeadInput, MarketMetrics, MicroSignalClassification, SourceSnippet
from app.scoring import score_lead
from app.services import company_classifier, property_classifier
from app.services.company import (
    _is_usable_property_evidence,
    _rank_property_source_snippets,
    _rank_source_snippets,
)
from app.services.company_classifier import build_evidence_packet, classify_company_signals
from app.services.property_classifier import classify_property_signals


def _lead() -> LeadInput:
    return LeadInput(
        name="Test Contact",
        email="test@example.com",
        company="Example Property Co",
        address="123 Main St",
        city="Austin",
        state="TX",
        country="US",
    )


def _payload(bucket: str = "Very High") -> dict:
    return {
        "leasing_volume": {
            "raw_evidence": "manages 300,000 apartment units",
            "evidence_source": "search_snippets[0]",
            "parsed_value": "300,000 apartment units",
            "interpreted_bucket": bucket,
            "confidence": "High",
            "classifier": "openai_classifier",
        },
        "operational_complexity": {
            "raw_evidence": "leasing and resident communication teams",
            "evidence_source": "search_snippets[0]",
            "parsed_value": "leasing and resident communication teams",
            "interpreted_bucket": "Very High",
            "confidence": "High",
            "classifier": "openai_classifier",
        },
        "product_fit": {
            "raw_evidence": "leasing and resident communication teams",
            "evidence_source": "search_snippets[0]",
            "parsed_value": "leasing and resident communication teams",
            "interpreted_bucket": "Very Strong",
            "confidence": "High",
            "classifier": "openai_classifier",
        },
    }


def _property_payload() -> dict:
    return {
        "property_type": {
            "raw_evidence": "The Morrison Apartments offers apartment homes",
            "evidence_source": "search_snippets[0]",
            "parsed_value": "apartment homes",
            "interpreted_bucket": "Multifamily",
            "confidence": "High",
            "classifier": "openai_classifier",
        },
        "property_scale": {
            "raw_evidence": "240 apartment units",
            "evidence_source": "search_snippets[0]",
            "parsed_value": "240 apartment units",
            "interpreted_bucket": "Large",
            "confidence": "High",
            "classifier": "openai_classifier",
        },
        "leasing_activity": {
            "raw_evidence": "Now leasing with available units and floor plans",
            "evidence_source": "search_snippets[0]",
            "parsed_value": "available units and floor plans",
            "interpreted_bucket": "Active",
            "confidence": "High",
            "classifier": "openai_classifier",
        },
    }


def test_build_evidence_packet_limits_and_dedupes_snippets() -> None:
    snippets = [
        SourceSnippet(source="Serper", title="Same", snippet="Duplicate evidence" * 40),
        SourceSnippet(source="Serper", title="Same", snippet="Duplicate evidence" * 40),
        *[
            SourceSnippet(source="Serper", title=f"Title {index}", snippet=f"Snippet {index}")
            for index in range(10)
        ],
    ]

    evidence = build_evidence_packet(
        website_title="Website",
        website_description=None,
        website_snippet="Website evidence",
        search_snippets=snippets,
    )

    assert len(evidence) == 5
    assert all(len(text) <= 400 for text in evidence.values())


def test_property_evidence_can_match_osm_resolved_property_name() -> None:
    lead = LeadInput(
        name="Test Contact",
        email="test@example.com",
        company="Example Property Co",
        address="214 Barton Springs Rd",
        city="Austin",
        state="TX",
        country="US",
    )

    assert _is_usable_property_evidence(
        "The Catherine Austin has floor plans, amenities, and available units.",
        lead,
        property_aliases=["The Catherine"],
    )


def test_openai_classifier_valid_payload_is_used(monkeypatch) -> None:
    async def fake_call_openai_classifier(**kwargs):
        return _payload()

    monkeypatch.setattr(
        company_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(company_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_company_signals(
            lead=_lead(),
            website_title=None,
            website_description=None,
            website_snippet=None,
            search_snippets=[
                SourceSnippet(
                    source="Serper",
                    title="Example Property Co",
                    snippet="manages 300,000 apartment units with leasing and resident communication teams",
                )
            ],
        )
    )

    assert missing is None
    assert classifications["leasing_volume"].interpreted_bucket == "Very High"


def test_openai_property_classifier_valid_payload_is_used(monkeypatch) -> None:
    async def fake_call_openai_classifier(**kwargs):
        return _property_payload()

    monkeypatch.setattr(
        property_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(property_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_property_signals(
            lead=_lead(),
            search_snippets=[
                SourceSnippet(
                    source="Serper Property",
                    title="The Morrison Apartments",
                    snippet=(
                        "The Morrison Apartments offers apartment homes with 240 apartment units. "
                        "Now leasing with available units and floor plans."
                    ),
                )
            ],
        )
    )

    assert missing is None
    assert classifications["property_type"].interpreted_bucket == "Multifamily"
    assert classifications["property_scale"].interpreted_bucket == "Large"
    assert classifications["leasing_activity"].interpreted_bucket == "Active"


def test_openai_classifier_normalizes_product_fit_bucket_synonyms(monkeypatch) -> None:
    async def fake_call_openai_classifier(**kwargs):
        payload = _payload()
        payload["product_fit"]["interpreted_bucket"] = "High"
        return payload

    monkeypatch.setattr(
        company_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(company_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_company_signals(
            lead=_lead(),
            website_title=None,
            website_description=None,
            website_snippet=None,
            search_snippets=[
                SourceSnippet(
                    source="Serper",
                    title="Example Property Co",
                    snippet="manages 300,000 apartment units with leasing and resident communication teams",
                )
            ],
        )
    )

    assert missing is None
    assert classifications["product_fit"].interpreted_bucket == "Strong"


def test_openai_classifier_normalizes_large_scale_bucket_synonyms(monkeypatch) -> None:
    async def fake_call_openai_classifier(**kwargs):
        payload = _payload()
        payload["leasing_volume"]["interpreted_bucket"] = "Very Large"
        payload["operational_complexity"]["interpreted_bucket"] = "Large"
        payload["product_fit"]["interpreted_bucket"] = "Huge"
        return payload

    monkeypatch.setattr(
        company_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(company_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_company_signals(
            lead=_lead(),
            website_title=None,
            website_description=None,
            website_snippet=None,
            search_snippets=[
                SourceSnippet(
                    source="Serper",
                    title="Example Property Co",
                    snippet="manages 300,000 apartment units with leasing and resident communication teams",
                )
            ],
        )
    )

    assert missing is None
    assert classifications["leasing_volume"].interpreted_bucket == "Very High"
    assert classifications["operational_complexity"].interpreted_bucket == "High"
    assert classifications["product_fit"].interpreted_bucket == "Very Strong"


def test_source_ranking_prioritizes_explicit_scale_evidence() -> None:
    snippets = [
        SourceSnippet(source="Serper", title="Marketing", snippet="Beautiful apartment communities."),
        SourceSnippet(
            source="Serper",
            title="Greystar portfolio",
            snippet="Greystar manages more than 900,000 apartment units globally.",
            url="https://example.com/scale",
        ),
    ]

    ranked = _rank_source_snippets(snippets)

    assert ranked[0].title == "Greystar portfolio"


def test_property_source_ranking_downweights_nearby_listing_noise() -> None:
    lead = _lead()
    lead.address = "1 Apple Park Way"
    lead.city = "Cupertino"
    lead.state = "CA"
    snippets = [
        SourceSnippet(
            source="Serper Property",
            title="Apartments near Apple Park",
            snippet="Find apartments near 1 Apple Park Way with available units.",
        ),
        SourceSnippet(
            source="Serper Property",
            title="Apple Park",
            snippet="1 Apple Park Way Cupertino CA office campus information.",
        ),
    ]

    ranked = _rank_property_source_snippets(snippets, lead=lead)

    assert ranked[0].title == "Apple Park"


def test_property_evidence_rejects_neighborhood_listing_pages() -> None:
    lead = _lead()
    lead.address = "20 Hudson Yards"
    lead.city = "New York"
    lead.state = "NY"

    assert not _is_usable_property_evidence(
        "Apartments for Rent in Hudson Yards, New York. Browse all 203 apartments.",
        lead,
    )


def test_property_evidence_allows_strong_building_signal_without_address() -> None:
    lead = _lead()
    lead.address = "Lamar Union, 1100 S Lamar Blvd"
    lead.city = "Austin"
    lead.state = "TX"

    assert _is_usable_property_evidence(
        "Lamar Union offers floor plans, amenities, pricing and availability, and schedule a tour.",
        lead,
    )


def test_property_evidence_rejects_strong_signal_without_identity_match() -> None:
    lead = _lead()
    lead.address = "1 Apple Park Way"
    lead.city = "Cupertino"
    lead.state = "CA"

    assert not _is_usable_property_evidence(
        "Cupertino Park Center offers floor plans, amenities, pricing and availability.",
        lead,
    )


def test_property_evidence_rejects_different_address_property_page() -> None:
    lead = _lead()
    lead.address = "1 Apple Park Way"
    lead.city = "Cupertino"
    lead.state = "CA"

    assert not _is_usable_property_evidence(
        "Cupertino Park Center at 20380 Stevens Creek Blvd offers floor plans and available units.",
        lead,
    )


def test_openai_classifier_invalid_payload_falls_back_after_retry(monkeypatch) -> None:
    calls = 0

    async def fake_call_openai_classifier(**kwargs):
        nonlocal calls
        calls += 1
        return {"leasing_volume": {}}

    monkeypatch.setattr(
        company_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(company_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_company_signals(
            lead=_lead(),
            website_title=None,
            website_description=None,
            website_snippet=None,
            search_snippets=[SourceSnippet(source="Serper", snippet="some evidence")],
        )
    )

    assert calls == 2
    assert classifications == {}
    assert missing is not None


def test_openai_classifier_keeps_valid_signals_when_one_signal_is_invalid(monkeypatch) -> None:
    async def fake_call_openai_classifier(**kwargs):
        payload = _payload()
        payload["product_fit"]["evidence_source"] = "bad_source"
        return payload

    monkeypatch.setattr(
        company_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(company_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_company_signals(
            lead=_lead(),
            website_title=None,
            website_description=None,
            website_snippet=None,
            search_snippets=[
                SourceSnippet(
                    source="Serper",
                    title="Example Property Co",
                    snippet="manages 300,000 apartment units with leasing and resident communication teams",
                )
            ],
        )
    )

    assert set(classifications) == {"leasing_volume", "operational_complexity"}
    assert missing is not None


def test_leasing_volume_accepts_aggregated_numeric_evidence(monkeypatch) -> None:
    async def fake_call_openai_classifier(**kwargs):
        payload = _payload()
        payload["leasing_volume"]["raw_evidence"] = (
            "Multiple sources report roughly 900,000 units."
        )
        payload["leasing_volume"]["evidence_source"] = "multiple_sources"
        payload["leasing_volume"]["parsed_value"] = "900,000 units"
        payload["leasing_volume"]["interpreted_bucket"] = "Very High"
        payload["leasing_volume"]["confidence"] = "Medium"
        return payload

    monkeypatch.setattr(
        company_classifier,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_model="test-model"),
    )
    monkeypatch.setattr(company_classifier, "_call_openai_classifier", fake_call_openai_classifier)

    classifications, missing = asyncio.run(
        classify_company_signals(
            lead=_lead(),
            website_title=None,
            website_description=None,
            website_snippet=None,
            search_snippets=[
                SourceSnippet(
                    source="Serper",
                    title="Example Property Co units",
                    snippet=(
                        "Example Property Co manages 900,000 apartment units "
                        "with leasing and resident communication teams."
                    ),
                ),
                SourceSnippet(
                    source="Serper",
                    title="Example Property Co portfolio",
                    snippet="The company portfolio includes more than 900000 units globally.",
                ),
            ],
        )
    )

    assert missing is None
    assert classifications["leasing_volume"].interpreted_bucket == "Very High"
    assert classifications["leasing_volume"].confidence == "High"


def test_classifier_confidence_can_drive_overall_confidence() -> None:
    lead = _lead()
    payload = _payload()
    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in payload.items()
            },
            source_text="source-backed company evidence",
        ),
    )

    assert score.confidence == "High"


def test_large_operator_derives_complexity_when_ops_signal_is_missing() -> None:
    lead = _lead()
    payload = _payload()
    payload["leasing_volume"]["interpreted_bucket"] = "High"
    payload["leasing_volume"]["raw_evidence"] = "RPM Living manages 225,000 units."
    payload["leasing_volume"]["parsed_value"] = "225,000 units"
    payload["operational_complexity"]["interpreted_bucket"] = "None"
    payload["operational_complexity"]["raw_evidence"] = "No explicit workflow evidence found."
    payload["operational_complexity"]["parsed_value"] = "No explicit workflow evidence found."
    payload["product_fit"]["interpreted_bucket"] = "Strong"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in payload.items()
            },
            source_text="RPM Living manages 225,000 units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["operational_complexity"]
    assert audit.interpreted_bucket == "High"
    assert audit.parsed_value == "Large portfolio implies operational complexity."
    assert score.company_fit_breakdown.score_breakdown["operational_complexity"] == 9


def test_scaled_multifamily_operator_derives_product_fit_when_missing() -> None:
    lead = _lead()
    payload = _payload()
    payload["leasing_volume"]["interpreted_bucket"] = "High"
    payload["leasing_volume"]["raw_evidence"] = "RPM Living manages 225,000 multifamily units."
    payload["leasing_volume"]["parsed_value"] = "225,000 multifamily units"
    payload["product_fit"]["interpreted_bucket"] = "None"
    payload["product_fit"]["raw_evidence"] = "No explicit product workflow evidence found."
    payload["product_fit"]["parsed_value"] = "No explicit product workflow evidence found."

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in payload.items()
            },
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            source_text="RPM Living manages 225,000 multifamily units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["product_fit"]
    assert audit.interpreted_bucket == "Strong"
    assert audit.parsed_value == "Strong ICP inferred from residential operator type and portfolio scale."
    assert score.company_fit_breakdown.score_breakdown["product_fit"] == 10


def test_conflicting_evidence_can_return_unknown_without_overclaiming() -> None:
    lead = _lead()
    classifications = _payload(bucket="Unknown")
    classifications["leasing_volume"]["raw_evidence"] = "conflicting residential and commercial evidence"
    classifications["leasing_volume"]["parsed_value"] = "insufficient evidence"
    enrichment_score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            source_text="conflicting residential and commercial evidence",
        ),
    )

    audit = enrichment_score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.interpreted_bucket == "Unknown"
    assert audit.score_contribution == 0


def test_source_backed_scale_boost_lifts_greystar_like_classification() -> None:
    lead = _lead()
    classifications = _payload(bucket="High")
    classifications["operational_complexity"]["interpreted_bucket"] = "High"
    classifications["product_fit"]["interpreted_bucket"] = "Strong"
    for value in classifications.values():
        value["raw_evidence"] = (
            "Greystar manages more than 900,000 apartment units globally with "
            "centralized leasing and resident operations."
        )
        value["parsed_value"] = value["raw_evidence"]

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            source_text=(
                "Greystar manages more than 900,000 apartment units globally with "
                "centralized leasing and resident operations."
            ),
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit
    assert audit["leasing_volume"].interpreted_bucket == "Very High"
    assert audit["operational_complexity"].interpreted_bucket == "Very High"
    assert audit["product_fit"].interpreted_bucket == "Very Strong"
    assert score.company_fit.score == 39


def test_leasing_volume_uses_deterministic_unit_thresholds() -> None:
    lead = _lead()
    classifications = _payload(bucket="Very High")
    classifications["leasing_volume"]["raw_evidence"] = "RPM Living manages 225,000 multifamily units."
    classifications["leasing_volume"]["parsed_value"] = "225,000 multifamily units"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            source_text="RPM Living manages 225,000 multifamily units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.interpreted_bucket == "High"
    assert audit.score_contribution == 11


def test_classifier_bucket_is_ignored_when_unit_count_is_extractable() -> None:
    lead = _lead()
    classifications = _payload(bucket="Unknown")
    classifications["leasing_volume"]["raw_evidence"] = "Asset Living manages more than 450,000 units."
    classifications["leasing_volume"]["parsed_value"] = "450,000 units"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            source_text="Asset Living manages more than 450,000 units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.interpreted_bucket == "Very High"
    assert audit.score_contribution == 13


def test_scale_extraction_ignores_transaction_noise_and_selects_max_portfolio_value() -> None:
    lead = _lead()
    classifications = _payload(bucket="Unknown")
    classifications["leasing_volume"]["raw_evidence"] = (
        "UDR disposed 8 communities, comprising 1,755 homes. "
        "As of December 31, 2024, UDR owned 169 apartment communities containing "
        "55,696 apartment units."
    )
    classifications["leasing_volume"]["parsed_value"] = "55,696 apartment units"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["apartments"],
            property_signals=["apartments"],
            source_text=classifications["leasing_volume"]["raw_evidence"],
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.parsed_value == "55,696 apartment units"
    assert audit.interpreted_bucket == "Medium"
    assert audit.score_contribution == 8


def test_scale_extraction_ignores_listing_subset_counts() -> None:
    lead = _lead()
    classifications = _payload(bucket="Unknown")
    classifications["leasing_volume"]["raw_evidence"] = (
        "Showing 25 out of 172 properties. "
        "Bridge Property Management manages over 60,000 units across its portfolio."
    )
    classifications["leasing_volume"]["parsed_value"] = "60,000 units"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["property management"],
            property_signals=["apartments"],
            source_text=classifications["leasing_volume"]["raw_evidence"],
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.parsed_value == "60,000 units"
    assert audit.interpreted_bucket == "Medium"
    assert audit.score_contribution == 8


def test_multifamily_scale_floors_product_fit_by_unit_count() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "High"
    classifications["leasing_volume"]["raw_evidence"] = "Asset Living manages more than 300,000 units."
    classifications["leasing_volume"]["parsed_value"] = "300,000 units"
    classifications["product_fit"]["interpreted_bucket"] = "Moderate"
    classifications["product_fit"]["raw_evidence"] = "Asset Living is a multifamily property manager."
    classifications["product_fit"]["parsed_value"] = "Multifamily property manager"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            source_text="Asset Living manages more than 300,000 units as a multifamily property manager.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["product_fit"]
    assert audit.interpreted_bucket == "Very Strong"
    assert audit.score_contribution == 13


def test_multifamily_mid_large_scale_caps_product_fit_at_strong() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "High"
    classifications["leasing_volume"]["raw_evidence"] = "RPM Living manages 225,000 multifamily units."
    classifications["leasing_volume"]["parsed_value"] = "225,000 multifamily units"
    classifications["product_fit"]["interpreted_bucket"] = "Very Strong"
    classifications["product_fit"]["raw_evidence"] = "RPM Living manages 225,000 multifamily units."
    classifications["product_fit"]["parsed_value"] = "Large multifamily property manager"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            source_text="RPM Living manages 225,000 multifamily units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["product_fit"]
    assert audit.interpreted_bucket == "Strong"
    assert audit.score_contribution == 10


def test_single_family_product_fit_is_capped_below_very_strong() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "Very High"
    classifications["leasing_volume"]["raw_evidence"] = "Invitation Homes owns 80,000 single-family rental homes."
    classifications["leasing_volume"]["parsed_value"] = "80,000 single-family rental homes"
    classifications["product_fit"]["interpreted_bucket"] = "Very Strong"
    classifications["product_fit"]["raw_evidence"] = "Invitation Homes owns 80,000 single-family rental homes."
    classifications["product_fit"]["parsed_value"] = "Large single-family rental operator"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["single-family rental"],
            property_signals=["single-family rental"],
            source_text="Invitation Homes owns 80,000 single-family rental homes.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["product_fit"]
    assert audit.interpreted_bucket == "Moderate"
    assert audit.score_contribution == 5


def test_single_family_leasing_volume_is_capped_at_medium() -> None:
    lead = _lead()
    classifications = _payload(bucket="Very High")
    classifications["leasing_volume"]["raw_evidence"] = (
        "Invitation Homes owns 250,000 single-family rental homes."
    )
    classifications["leasing_volume"]["parsed_value"] = "250,000 single-family rental homes"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["single-family rental"],
            property_signals=["single-family rental"],
            source_text="Invitation Homes owns 250,000 single-family rental homes.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["leasing_volume"]
    assert audit.interpreted_bucket == "Medium"
    assert audit.score_contribution == 8


def test_single_family_complexity_is_capped_at_medium() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "Very High"
    classifications["leasing_volume"]["raw_evidence"] = (
        "Invitation Homes owns 80,000 single-family rental homes."
    )
    classifications["leasing_volume"]["parsed_value"] = "80,000 single-family rental homes"
    classifications["operational_complexity"]["interpreted_bucket"] = "Very High"
    classifications["operational_complexity"]["raw_evidence"] = (
        "Invitation Homes owns 80,000 single-family rental homes."
    )
    classifications["operational_complexity"]["parsed_value"] = "Large single-family rental operator"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["single-family rental"],
            property_signals=["single-family rental"],
            source_text="Invitation Homes owns 80,000 single-family rental homes.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["operational_complexity"]
    assert audit.interpreted_bucket == "Medium"
    assert audit.score_contribution == 6


def test_low_leasing_volume_caps_complexity_at_low() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "Low"
    classifications["leasing_volume"]["raw_evidence"] = "Small operator has 140 apartment units."
    classifications["leasing_volume"]["parsed_value"] = "140 apartment units"
    classifications["operational_complexity"]["interpreted_bucket"] = "Medium"
    classifications["operational_complexity"]["raw_evidence"] = "Small operator has 140 apartment units."
    classifications["operational_complexity"]["parsed_value"] = "Some apartment operations"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["property management"],
            property_signals=["apartments"],
            source_text="Small operator has 140 apartment units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["operational_complexity"]
    assert audit.interpreted_bucket == "Low"
    assert audit.score_contribution == 4


def test_priority_uses_gtm_thresholds() -> None:
    lead = _lead()
    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            leasing_volume_signals=["over 900,000 apartment units"],
            operational_complexity_signals=["centralized leasing", "resident services"],
            product_fit_signals=["centralized leasing"],
            source_text=(
                "Multifamily operator with over 900,000 apartment units, centralized leasing, "
                "resident services, and apartment operations."
            ),
        ),
    )

    assert score.final_score >= 40
    assert score.priority == "High"


def test_very_high_volume_enforces_very_high_complexity() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "Very High"
    classifications["leasing_volume"]["raw_evidence"] = "Greystar manages over 900,000 apartment units."
    classifications["leasing_volume"]["parsed_value"] = "900,000 apartment units"
    classifications["operational_complexity"]["interpreted_bucket"] = "Medium"
    classifications["operational_complexity"]["raw_evidence"] = "No workflow detail beyond portfolio scale."
    classifications["operational_complexity"]["parsed_value"] = "Limited explicit workflow detail"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            source_text="Greystar manages over 900,000 apartment units.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["operational_complexity"]
    assert audit.interpreted_bucket == "Very High"
    assert audit.score_contribution == 13


def test_fallback_scale_rules_lift_complexity_and_product_fit() -> None:
    lead = _lead()
    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            business_type_signals=["multifamily"],
            property_signals=["apartments"],
            leasing_volume_signals=["240,000 units"],
            operational_complexity_signals=["resident"],
            source_text="Willow Bridge manages 240,000 units and supports residents.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit
    assert audit["leasing_volume"].interpreted_bucket == "High"
    assert audit["operational_complexity"].interpreted_bucket == "High"
    assert audit["product_fit"].interpreted_bucket == "Strong"


def test_low_volume_operator_caps_product_fit_at_moderate() -> None:
    lead = _lead()
    classifications = _payload()
    classifications["leasing_volume"]["interpreted_bucket"] = "Low"
    classifications["leasing_volume"]["raw_evidence"] = "Local operator manages 3 apartment buildings."
    classifications["leasing_volume"]["parsed_value"] = "3 apartment buildings"
    classifications["product_fit"]["interpreted_bucket"] = "Very Strong"
    classifications["product_fit"]["raw_evidence"] = "Local operator handles apartment leasing."
    classifications["product_fit"]["parsed_value"] = "Apartment leasing operator"

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=CompanyEnrichment(
            classifications={
                key: MicroSignalClassification.model_validate(value)
                for key, value in classifications.items()
            },
            business_type_signals=["property management"],
            property_signals=["apartments"],
            source_text="Local operator manages 3 apartment buildings and handles apartment leasing.",
        ),
    )

    audit = score.company_fit_breakdown.extraction_audit["product_fit"]
    assert audit.interpreted_bucket == "Moderate"
    assert audit.score_contribution == 5
