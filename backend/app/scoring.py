from dataclasses import dataclass
import re

from app.models import (
    CompanyFitBreakdown,
    CompanyEnrichment,
    CompanyFitLabel,
    LeadInput,
    MarketMetrics,
    ScoreBreakdown,
    ScoreSection,
    SignalAudit,
    MicroSignalClassification,
)
from app.services.company import extract_company_signals


@dataclass(frozen=True)
class _CompanyFitResult:
    section: ScoreSection
    label: CompanyFitLabel
    unrelated: bool
    breakdown: CompanyFitBreakdown


def score_lead(
    lead: LeadInput,
    market_metrics: MarketMetrics,
    company_text: str = "",
    timing_signals: list[str] | None = None,
    company_enrichment: CompanyEnrichment | None = None,
) -> ScoreBreakdown:
    """Compute the deterministic MVP score.

    This initial scaffold uses conservative keyword and metric thresholds. API
    integrations can later replace the empty/default inputs without changing
    the contract consumed by the frontend.
    """

    if company_enrichment is None:
        company_enrichment = extract_company_signals(
            lead=lead,
            website_snippet=company_text,
        )
    timing_inputs = [*(timing_signals or []), *company_enrichment.timing_signals]

    market_fit = _score_market_fit(market_metrics)
    company_fit_result = _score_company_fit(company_enrichment)
    property_fit = _score_property_fit(company_enrichment)
    timing = _score_timing(timing_inputs)

    final_score = (
        market_fit.score
        + company_fit_result.section.score
        + property_fit.score
        + timing.score
    )
    if company_fit_result.unrelated:
        final_score = min(final_score, 60)

    priority = "High" if final_score >= 40 else "Medium" if final_score >= 30 else "Low"
    confidence = _confidence(market_metrics, company_enrichment, timing_inputs)

    return ScoreBreakdown(
        market_fit=market_fit,
        company_fit=company_fit_result.section,
        property_fit=property_fit,
        timing=timing,
        company_fit_breakdown=company_fit_result.breakdown,
        final_score=final_score,
        priority=priority,
        company_fit_label=company_fit_result.label,
        confidence=confidence,
    )


def _score_market_fit(metrics: MarketMetrics) -> ScoreSection:
    score = 0
    reasons: list[str] = []

    city_score, city_reasons = _score_city_momentum(metrics)
    rental_score, rental_reasons = _score_neighborhood_rental_demand(metrics)
    economic_score, economic_reasons = _score_neighborhood_economics(metrics)
    leasing_score, leasing_reasons = _score_leasing_pressure(metrics)
    access_score, access_reasons = _score_access_proxy(metrics)

    score += city_score + rental_score + economic_score + leasing_score + access_score
    reasons.extend(
        city_reasons
        + rental_reasons
        + economic_reasons
        + leasing_reasons
        + access_reasons
    )
    dampener, dampener_reasons = _score_market_dampeners(metrics)
    score -= dampener
    reasons.extend(dampener_reasons)

    return ScoreSection(score=max(0, min(score, 45)), max_score=45, reasons=reasons)


def _score_city_momentum(metrics: MarketMetrics) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if metrics.population is None:
        reasons.append("Population data was unavailable.")
    elif metrics.population >= 1_000_000:
        score += 4
        reasons.append("Large population base supports market scale.")
    elif metrics.population >= 500_000:
        score += 3
        reasons.append("Large city population supports market scale.")
    elif metrics.population >= 150_000:
        score += 2
        reasons.append("Mid-size population base provides some market scale.")
    else:
        score += 1
        reasons.append("Smaller population base provides limited market scale.")

    if metrics.median_gross_rent is None:
        reasons.append("City median gross rent data was unavailable.")
    elif metrics.median_gross_rent > 2_500:
        score += 5
        reasons.append("Very high city median rent indicates strong rental market value.")
    elif metrics.median_gross_rent >= 1_800:
        score += 4
        reasons.append("High city median rent indicates strong rental market value.")
    elif metrics.median_gross_rent >= 1_200:
        score += 3
        reasons.append("Moderate city median rent supports rental market value.")
    else:
        score += 1
        reasons.append("Lower city median rent weakens the rental value signal.")

    if metrics.population_growth_rate is None:
        reasons.append("Population growth data was unavailable.")
    elif metrics.population_growth_rate >= 0.05:
        score += 3
        reasons.append("Strong population growth suggests continued rental demand.")
    elif metrics.population_growth_rate >= 0:
        score += 2
        reasons.append("Stable or moderate population growth supports leasing demand.")
    else:
        score += 1
        reasons.append("Population decline is noted but treated as a light macro signal.")

    return min(score, 12), reasons


def _score_neighborhood_rental_demand(metrics: MarketMetrics) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if metrics.renter_share is None:
        reasons.append("Neighborhood renter-share data was unavailable.")
    elif metrics.renter_share > 0.70:
        score += 10
        reasons.append("Very high neighborhood renter share indicates strong local rental demand.")
    elif metrics.renter_share >= 0.50:
        score += 8
        reasons.append("High neighborhood renter share supports local leasing demand.")
    elif metrics.renter_share >= 0.30:
        score += 5
        reasons.append("Moderate neighborhood renter share suggests some local rental demand.")
    else:
        score += 2
        reasons.append("Lower renter share weakens the neighborhood rental-demand signal.")

    if metrics.neighborhood_ratios_blended_with_tract:
        reasons.append(
            "Neighborhood ratios blend block-group and tract ACS data to reduce small-area noise."
        )

    return min(score, 10), reasons


def _score_neighborhood_economics(metrics: MarketMetrics) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if metrics.median_income is None:
        reasons.append("Neighborhood income data was unavailable.")
    elif (
        metrics.median_income < 25_000
        and metrics.no_vehicle_household_share is not None
        and metrics.no_vehicle_household_share >= 0.40
        and metrics.housing_units is not None
        and metrics.housing_units <= 1_500
    ):
        score += 4
        reasons.append(
            "Neighborhood income appears atypical for a dense urban tract, so it is treated as neutral."
        )
    elif metrics.median_income >= 90_000:
        score += 8
        reasons.append("High neighborhood median income indicates a strong economic base.")
    elif metrics.median_income >= 55_000:
        score += 5
        reasons.append("Neighborhood median income indicates a moderate economic base.")
    else:
        score += 2
        reasons.append("Lower neighborhood median income weakens the economic strength signal.")

    return min(score, 8), reasons


def _score_leasing_pressure(metrics: MarketMetrics) -> tuple[int, list[str]]:
    if metrics.vacancy_rate is None:
        return 0, ["Neighborhood vacancy data was unavailable."]

    if metrics.vacancy_rate < 0.05:
        return 6, ["Low vacancy suggests strong local leasing pressure."]
    if metrics.vacancy_rate <= 0.15:
        return 5, ["Moderate vacancy is treated as a healthy neutral leasing-pressure signal."]
    if metrics.vacancy_rate <= 0.25:
        return 3, ["Elevated vacancy mildly tempers the local leasing-pressure signal."]
    return 2, ["Very high vacancy is treated as supply or churn, not weak demand by itself."]


def _score_access_proxy(metrics: MarketMetrics) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if metrics.no_vehicle_household_share is None:
        reasons.append("No-vehicle household data was unavailable.")
    elif metrics.no_vehicle_household_share >= 0.20:
        score += 4
        reasons.append("High no-vehicle household share suggests urban access and density.")
    elif metrics.no_vehicle_household_share >= 0.10:
        score += 2
        reasons.append("Moderate no-vehicle household share supports urban access.")
    else:
        score += 1
        reasons.append("Low no-vehicle household share weakens the urban-access signal.")

    if metrics.public_transit_commute_share is None:
        reasons.append("Public-transit commute data was unavailable.")
    elif metrics.public_transit_commute_share >= 0.15:
        score += 3
        reasons.append("High public-transit commute share supports access-oriented rental demand.")
    elif metrics.public_transit_commute_share >= 0.05:
        score += 2
        reasons.append("Some public-transit commute share supports access-oriented demand.")

    if metrics.walking_commute_share is None:
        reasons.append("Walking commute data was unavailable.")
    elif metrics.walking_commute_share >= 0.08:
        score += 2
        reasons.append("High walking commute share suggests strong local walkability.")
    elif metrics.walking_commute_share >= 0.03:
        score += 1
        reasons.append("Some walking commute share supports local walkability.")

    if score == 0:
        reasons.append("Access and urban proxy data did not produce a positive signal.")

    return min(score, 9), reasons


def _score_market_dampeners(metrics: MarketMetrics) -> tuple[int, list[str]]:
    if (
        metrics.renter_share is not None
        and metrics.renter_share < 0.40
        and metrics.vacancy_rate is not None
        and metrics.vacancy_rate > 0.20
    ):
        return 2, [
            "Low renter share plus high vacancy suggests a mixed-use or commercial pattern, so Market Fit is lightly dampened."
        ]
    return 0, []


def _score_company_fit(enrichment: CompanyEnrichment) -> _CompanyFitResult:
    reasons: list[str] = []

    leasing_volume_score, leasing_volume_audit = _score_leasing_volume(enrichment, reasons)
    operations_score, operations_audit = _score_operational_complexity(enrichment, reasons)
    product_fit_score, product_fit_audit = _score_product_fit(enrichment, reasons)
    segment = _company_segment(enrichment)
    unit_count = _unit_count_from_audit(enrichment, leasing_volume_audit)

    if (
        leasing_volume_audit.interpreted_bucket == "Very High"
        and operations_audit.interpreted_bucket != "Very High"
    ):
        operations_score = _classified_score("operational_complexity", "Very High")
        operations_audit = _calibrated_audit(
            operations_audit,
            bucket="Very High",
            score=operations_score,
            parsed_value="Very high portfolio scale implies very high operational complexity.",
        )
        reasons.append(
            "Operational complexity is calibrated to Very High because portfolio scale is Very High."
        )
    elif (
        leasing_volume_audit.interpreted_bucket == "High"
        and _is_bucket_below_operational_complexity(
            operations_audit.interpreted_bucket,
            "High",
        )
    ):
        operations_score = _classified_score("operational_complexity", "High")
        operations_audit = _calibrated_audit(
            operations_audit,
            bucket="High",
            score=operations_score,
            parsed_value="Large portfolio implies operational complexity.",
            raw_evidence=leasing_volume_audit.raw_evidence,
            evidence_source=leasing_volume_audit.evidence_source,
            confidence=leasing_volume_audit.confidence,
            classifier=leasing_volume_audit.classifier,
        )
        reasons.append(
            "Operational complexity is derived as High because large portfolio scale implies meaningful leasing operations."
        )

    if segment == "single_family" and _is_bucket_above_operational_complexity(
        operations_audit.interpreted_bucket,
        "Medium",
    ):
        operations_score = _classified_score("operational_complexity", "Medium")
        operations_audit = _calibrated_audit(
            operations_audit,
            bucket="Medium",
            score=operations_score,
            parsed_value="Operational complexity capped at Medium for single-family rental operators.",
        )
        reasons.append("Operational complexity is capped at Medium for single-family rental operators.")

    if (
        leasing_volume_audit.interpreted_bucket == "Low"
        and operations_audit.interpreted_bucket != "Low"
    ):
        operations_score = _classified_score("operational_complexity", "Low")
        operations_audit = _calibrated_audit(
            operations_audit,
            bucket="Low",
            score=operations_score,
            parsed_value="Low leasing volume limits operational complexity.",
        )
        reasons.append("Operational complexity is capped at Low because leasing volume is Low.")

    product_tier = _product_fit_tier(segment, unit_count)
    if product_tier and product_fit_audit.interpreted_bucket != product_tier:
        product_fit_score = _classified_score("product_fit", product_tier)
        product_fit_audit = _calibrated_audit(
            product_fit_audit,
            bucket=product_tier,
            score=product_fit_score,
            parsed_value=f"{product_tier} ICP inferred from residential operator type and portfolio scale.",
            raw_evidence=leasing_volume_audit.raw_evidence,
            evidence_source=leasing_volume_audit.evidence_source,
            confidence=leasing_volume_audit.confidence,
            classifier=leasing_volume_audit.classifier,
        )
        reasons.append(
            f"Product fit is calibrated to {product_tier} because scaled multifamily operators match the core ICP."
        )

    product_cap = _product_fit_cap(segment, leasing_volume_audit.interpreted_bucket)
    if product_cap and _is_bucket_above_product_fit(product_fit_audit.interpreted_bucket, product_cap):
        product_fit_score = _classified_score("product_fit", product_cap)
        product_fit_audit = _calibrated_audit(
            product_fit_audit,
            bucket=product_cap,
            score=product_fit_score,
            parsed_value=f"Product fit capped at {product_cap} for this ICP segment and scale.",
        )
        reasons.append(f"Product fit is capped at {product_cap} based on segment and leasing scale.")

    total = leasing_volume_score + operations_score + product_fit_score
    if product_fit_audit.interpreted_bucket == "None":
        total = min(total, 5)
        reasons.append("Missing product-fit classification caps Company Fit at 5 for non-ICP rejection.")
    elif product_fit_audit.interpreted_bucket == "Weak":
        total = min(total, 15)
        reasons.append("Weak product-fit classification caps Company Fit at 15 to prevent false positives.")
    related_signal_count = (
        len(enrichment.business_type_signals)
        + len(enrichment.leasing_volume_signals)
        + len(enrichment.operational_complexity_signals)
        + len(enrichment.product_fit_signals)
        + len(enrichment.property_signals)
    )
    commercial_mismatch = _is_commercial_mismatch(enrichment)
    unrelated = bool(enrichment.source_text.strip()) and (
        related_signal_count == 0 or commercial_mismatch
    )

    if unrelated:
        label: CompanyFitLabel = "Poor fit"
        reasons.append("Company context was found, but it did not match property management ICP signals.")
    elif total >= 32:
        label = "Strong fit"
    elif total >= 22:
        label = "Likely fit"
    else:
        label = "Unclear fit"

    return _CompanyFitResult(
        section=ScoreSection(score=min(total, 39), max_score=39, reasons=reasons),
        label=label,
        unrelated=unrelated,
        breakdown=CompanyFitBreakdown(
            score_breakdown={
                "leasing_volume": leasing_volume_score,
                "operational_complexity": operations_score,
                "product_fit": product_fit_score,
            },
            extraction_audit={
                "leasing_volume": leasing_volume_audit,
                "operational_complexity": operations_audit,
                "product_fit": product_fit_audit,
            },
        ),
    )


def _score_leasing_volume(
    enrichment: CompanyEnrichment,
    reasons: list[str],
) -> tuple[int, SignalAudit]:
    classified = enrichment.classifications.get("leasing_volume")
    if classified is not None:
        bucket = _calibrated_leasing_bucket(classified, enrichment)
        score = _classified_score("leasing_volume", bucket)
        reasons.append("Leasing volume is calibrated deterministically from extracted scale evidence.")
        return score, _audit_from_classification(classified, score, bucket)

    text = enrichment.source_text.lower()
    unit_count, unit_phrase = _largest_unit_count(enrichment.source_text)
    volume_terms = [
        *enrichment.leasing_volume_signals,
        *enrichment.geographic_footprint_signals,
    ]
    is_commercial = _is_commercial_mismatch(enrichment) or _is_commercial_company(enrichment)
    has_residential = _has_residential_fit(enrichment)
    parsed_value = unit_phrase or ", ".join(volume_terms) or "No leasing-volume signal found"
    implicit_scale = _implicit_scale_bucket(text)

    if _hard_fail_non_real_estate(enrichment):
        bucket = "None"
        score = 0
        parsed_value = "No leasing-volume signal found"
    elif unit_count:
        bucket = _leasing_bucket_from_units(unit_count, _company_segment(enrichment))
        score = _classified_score("leasing_volume", bucket)
    elif implicit_scale == "Very High" and has_residential:
        bucket = "Very High"
        score = 13
        parsed_value = "implicit global or enterprise scale"
    elif implicit_scale == "High" and has_residential:
        bucket = "High"
        score = 11
        parsed_value = "implicit multi-market or nationwide scale"
    elif unit_count >= 1_000:
        bucket = "Medium"
        score = 8
    elif unit_count > 0 or re.search(r"\b\d+\s+apartment buildings\b", text):
        bucket = "Low"
        score = 4
    elif is_commercial and "leasing" in text:
        bucket = "Medium"
        score = 7
        parsed_value = "commercial office leasing signal"
    elif has_residential and (
        "global markets" in text
        or "nationwide" in text
        or "major u.s. markets" in text
        or "student housing" in text
        or "multiple markets" in text
    ):
        bucket = "High"
        score = 11
    elif has_residential and volume_terms:
        bucket = "Medium"
        score = 8
    elif has_residential:
        bucket = "Low"
        score = 4
    else:
        bucket = "None"
        score = 0

    if bucket in {"Very High", "High"}:
        reasons.append("Company evidence suggests a large residential rental operator.")
    elif bucket == "Medium":
        reasons.append("Company evidence suggests meaningful but not enterprise-scale leasing volume.")
    elif bucket == "Low":
        reasons.append("Company evidence suggests small or local leasing volume.")
    else:
        reasons.append("Company leasing-volume evidence was not found.")

    return score, _audit("leasing_volume", enrichment, volume_terms, parsed_value, bucket, score)


def _score_operational_complexity(
    enrichment: CompanyEnrichment,
    reasons: list[str],
) -> tuple[int, SignalAudit]:
    classified = enrichment.classifications.get("operational_complexity")
    if classified is not None:
        bucket = _boost_classified_bucket("operational_complexity", classified, enrichment)
        score = _classified_score("operational_complexity", bucket)
        reasons.append(_classified_reason("operational_complexity", bucket))
        return score, _audit_from_classification(classified, score, bucket)

    text = enrichment.source_text.lower()
    terms = enrichment.operational_complexity_signals
    is_commercial = _is_commercial_mismatch(enrichment) or _is_commercial_company(enrichment)
    has_residential = _has_residential_fit(enrichment)

    if _hard_fail_non_real_estate(enrichment):
        bucket = "None"
        score = 0
    elif _contains_all(text, ["centralized leasing", "resident", "maintenance"]) or (
        "leasing" in text and "resident" in text and "maintenance" in text
    ) or (
        _largest_unit_count(enrichment.source_text)[0] >= 250_000
        and "leasing" in text
        and "resident" in text
    ):
        bucket = "Very High"
        score = 13
    elif (
        "resident engagement" in text
        or "tenant turnover" in text
        or "seasonal leasing" in text
        or "develops and operates" in text
        or ("leasing" in text and "resident" in text)
    ):
        bucket = "High"
        score = 9
    elif re.search(r"\b\d+\s+apartment buildings\b", text):
        bucket = "Low"
        score = 4
    elif is_commercial and "leasing" in text:
        bucket = "Medium"
        score = 6
    elif "single-family rental" in text or ("multiple" in text and has_residential):
        bucket = "Medium"
        score = 6
    elif len(terms) >= 2:
        bucket = "Medium"
        score = 6
    elif len(terms) == 1:
        bucket = "Low"
        score = 4
    else:
        bucket = "None"
        score = 0

    if bucket in {"Very High", "High"}:
        reasons.append("Company evidence shows multiple leasing, resident, or property operations workflows.")
    elif bucket == "Medium":
        reasons.append("Company evidence shows some operating complexity relevant to leasing or tenants.")
    elif bucket == "Low":
        reasons.append("Company evidence shows a light property operations workflow signal.")
    else:
        reasons.append("Operational workflow evidence was not found.")

    parsed_value = ", ".join(terms) or "No operational-complexity signal found"
    return score, _audit("operational_complexity", enrichment, terms, parsed_value, bucket, score)


def _score_product_fit(
    enrichment: CompanyEnrichment,
    reasons: list[str],
) -> tuple[int, SignalAudit]:
    classified = enrichment.classifications.get("product_fit")
    if classified is not None:
        bucket = _boost_classified_bucket("product_fit", classified, enrichment)
        if _company_segment(enrichment) == "single_family" and bucket == "Very Strong":
            bucket = "Strong"
        score = _classified_score("product_fit", bucket)
        reasons.append(_classified_reason("product_fit", bucket))
        return score, _audit_from_classification(classified, score, bucket)

    text = enrichment.source_text.lower()
    product_terms = enrichment.product_fit_signals
    is_commercial = _is_commercial_mismatch(enrichment) or _is_commercial_company(enrichment)
    has_residential = _has_residential_fit(enrichment)

    if _hard_fail_non_real_estate(enrichment):
        bucket = "None"
        score = 0
    elif is_commercial:
        bucket = "Weak"
        score = 1
    elif (
        "centralized leasing" in text
        or ("resident communication" in text and "leasing" in text)
        or ("resident services" in text and "leasing" in text)
    ):
        bucket = "Very Strong"
        score = 13
    elif re.search(r"\b\d+\s+apartment buildings\b", text):
        bucket = "Moderate"
        score = 5
    elif (
        "multifamily" in text
        or "student housing" in text
        or "apartment communities" in text
        or ("leasing" in text and has_residential)
    ):
        bucket = "Strong"
        score = 10
    elif has_residential:
        bucket = "Moderate"
        score = 5
    else:
        bucket = "None"
        score = 0

    if bucket in {"Very Strong", "Strong"}:
        reasons.append("Company evidence maps to EliseAI use cases like leasing or resident operations.")
    elif bucket == "Moderate":
        reasons.append("Company evidence suggests partial EliseAI product fit.")
    elif bucket == "Weak":
        reasons.append("Company evidence is real-estate related but weak for residential leasing automation.")
    else:
        reasons.append("Product-fit evidence was not found.")

    parsed_value = ", ".join(product_terms or enrichment.business_type_signals) or "No product-fit signal found"
    return score, _audit("product_fit", enrichment, product_terms, parsed_value, bucket, score)


def _score_property_fit(enrichment: CompanyEnrichment) -> ScoreSection:
    positive = len(enrichment.property_signals)
    negative = len(enrichment.negative_property_signals)
    reasons: list[str] = []
    clear_residential_terms = {
        "apartment",
        "apartments",
        "communities",
        "community",
        "residences",
        "residential",
        "rental homes",
        "single-family rental",
    }

    if set(enrichment.property_signals) & clear_residential_terms and negative == 0:
        reasons.append("Submitted property context has clear residential rental signals.")
        return ScoreSection(score=6, max_score=6, reasons=reasons)
    if positive and negative == 0:
        reasons.append("Submitted property context has a likely residential rental signal.")
        return ScoreSection(score=4, max_score=6, reasons=reasons)
    if positive and negative:
        reasons.append("Property context has mixed residential and commercial signals, so fit is treated cautiously.")
        return ScoreSection(score=3, max_score=6, reasons=reasons)
    if negative:
        reasons.append("Property context appears more commercial than residential rental.")
        return ScoreSection(score=1, max_score=6, reasons=reasons)

    reasons.append("Property relevance evidence was unavailable, so this subscore is neutral.")
    return ScoreSection(score=3, max_score=6, reasons=reasons)


def _is_commercial_mismatch(enrichment: CompanyEnrichment) -> bool:
    return bool(enrichment.negative_property_signals) and not _has_residential_fit(enrichment)


def _is_commercial_company(enrichment: CompanyEnrichment) -> bool:
    text = enrichment.source_text.lower()
    return any(
        phrase in text
        for phrase in [
            "commercial real estate",
            "office leasing",
            "office brokerage",
            "industrial brokerage",
            "commercial brokerage",
        ]
    ) and not _has_residential_fit(enrichment)


def _is_strong_icp_from_scale(
    enrichment: CompanyEnrichment,
    leasing_volume_audit: SignalAudit,
) -> bool:
    return (
        leasing_volume_audit.interpreted_bucket in {"High", "Very High"}
        and _has_residential_fit(enrichment)
        and not _is_commercial_mismatch(enrichment)
    )


def _calibrated_audit(
    audit: SignalAudit,
    *,
    bucket: str,
    score: int,
    parsed_value: str,
    raw_evidence: str | None = None,
    evidence_source: str | None = None,
    confidence: str | None = None,
    classifier: str | None = None,
) -> SignalAudit:
    return SignalAudit(
        raw_evidence=raw_evidence if raw_evidence is not None else audit.raw_evidence,
        evidence_source=evidence_source if evidence_source is not None else audit.evidence_source,
        parsed_value=parsed_value,
        interpreted_bucket=bucket,
        confidence=confidence if confidence is not None else audit.confidence,
        classifier=classifier if classifier is not None else audit.classifier,
        score_contribution=score,
    )


def _product_fit_cap(segment: str, leasing_volume_bucket: str) -> str | None:
    if segment == "single_family":
        return "Moderate"
    if leasing_volume_bucket == "Low":
        return "Moderate"
    return None


def _product_fit_tier(segment: str, unit_count: int) -> str | None:
    if segment == "multifamily" and unit_count >= 250_000:
        return "Very Strong"
    if unit_count >= 500_000:
        return "Very Strong"
    if unit_count >= 100_000:
        return "Strong"
    return None


def _unit_count_from_audit(enrichment: CompanyEnrichment, audit: SignalAudit) -> int:
    text = f"{audit.raw_evidence} {audit.parsed_value} {enrichment.source_text}"
    return _largest_unit_count(text)[0]


def _is_bucket_below_product_fit(bucket: str, floor: str) -> bool:
    return _product_fit_rank(bucket) < _product_fit_rank(floor)


def _is_bucket_above_product_fit(bucket: str, cap: str) -> bool:
    return _product_fit_rank(bucket) > _product_fit_rank(cap)


def _is_bucket_below_operational_complexity(bucket: str, floor: str) -> bool:
    return _operational_complexity_rank(bucket) < _operational_complexity_rank(floor)


def _is_bucket_above_operational_complexity(bucket: str, cap: str) -> bool:
    return _operational_complexity_rank(bucket) > _operational_complexity_rank(cap)


def _product_fit_rank(bucket: str) -> int:
    ranks = {
        "None": 0,
        "Unknown": 1,
        "Weak": 2,
        "Moderate": 3,
        "Strong": 4,
        "Very Strong": 5,
    }
    return ranks.get(bucket, 0)


def _operational_complexity_rank(bucket: str) -> int:
    ranks = {
        "None": 0,
        "Unknown": 1,
        "Low": 2,
        "Medium": 3,
        "High": 4,
        "Very High": 5,
    }
    return ranks.get(bucket, 0)


def _company_segment(enrichment: CompanyEnrichment) -> str:
    text = enrichment.source_text.lower()
    signals = set(enrichment.business_type_signals + enrichment.property_signals)
    if "single-family rental" in signals or "single-family rental" in text:
        return "single_family"
    if _is_commercial_mismatch(enrichment) or _is_commercial_company(enrichment):
        return "commercial"
    if signals & {
        "apartment",
        "apartments",
        "communities",
        "multifamily",
        "property manager",
        "property management",
        "residential",
        "student housing",
    }:
        return "multifamily"
    return "unknown"


def _calibrated_leasing_bucket(
    classification: MicroSignalClassification,
    enrichment: CompanyEnrichment,
) -> str:
    bucket = classification.interpreted_bucket

    text = f"{classification.raw_evidence} {classification.parsed_value} {enrichment.source_text}"
    unit_count, _ = _largest_unit_count(text)
    segment = _company_segment(enrichment)
    if unit_count:
        return _leasing_bucket_from_units(unit_count, segment)

    if bucket in {"None", "Unknown"}:
        return bucket

    if segment == "commercial":
        return "Medium" if bucket in {"Medium", "High", "Very High"} else bucket

    implicit_scale = _implicit_scale_bucket(text.lower())
    if implicit_scale == "Very High" and segment == "multifamily":
        return "High"
    if implicit_scale == "High" and segment in {"multifamily", "single_family"}:
        return "Medium"
    return bucket


def _leasing_bucket_from_units(unit_count: int, segment: str) -> str:
    if segment == "single_family":
        if unit_count >= 50_000:
            return "Medium"
        return "Low"

    if segment == "commercial":
        if unit_count >= 100_000:
            return "Medium"
        if unit_count >= 20_000:
            return "Low"
        return "Low"

    if unit_count >= 250_000:
        return "Very High"
    if unit_count >= 100_000:
        return "High"
    if unit_count >= 20_000:
        return "Medium"
    return "Low"


def _hard_fail_non_real_estate(enrichment: CompanyEnrichment) -> bool:
    text = enrichment.source_text.lower()
    if "no property or leasing operations" in text:
        return True
    return (
        not enrichment.business_type_signals
        and not enrichment.property_signals
        and not enrichment.negative_property_signals
    )


def _has_residential_fit(enrichment: CompanyEnrichment) -> bool:
    residential_terms = {
        "apartment",
        "apartments",
        "communities",
        "multifamily",
        "property manager",
        "property management",
        "residential",
        "rental homes",
        "single-family rental",
        "student housing",
    }
    return bool(
        set(enrichment.business_type_signals + enrichment.property_signals) & residential_terms
    )


def _contains_all(text: str, terms: list[str]) -> bool:
    return all(term in text for term in terms)


def _implicit_scale_bucket(text: str) -> str | None:
    if any(
        phrase in text
        for phrase in [
            "global markets",
            "global portfolio",
            "international portfolio",
            "largest property manager",
            "largest apartment operator",
        ]
    ):
        return "Very High"
    if any(
        phrase in text
        for phrase in [
            "nationwide",
            "across markets",
            "across major markets",
            "across u.s. markets",
            "major u.s. markets",
            "multiple markets",
            "national portfolio",
        ]
    ):
        return "High"
    return None


def _largest_unit_count(text: str) -> tuple[int, str | None]:
    candidates = _scale_candidates(text)
    if not candidates:
        return 0, None
    count, phrase = max(candidates, key=lambda candidate: candidate[0])
    return count, phrase


def _scale_candidates(text: str) -> list[tuple[int, str]]:
    matches = re.finditer(
        r"\b((?:over|more than|approximately|about|around|nearly)?\s*"
        r"\d+(?:[,.]\d{3})*(?:\.\d+)?\s*[km]?)\+?\s+"
        r"((?:(?:apartment|multifamily)\s+)?units|(?:single-family rental\s+)?homes|apartments|beds|buildings|communities|properties)\b",
        text,
        flags=re.IGNORECASE,
    )
    candidates: list[tuple[int, str]] = []
    for match in matches:
        raw_number = match.group(1)
        noun = match.group(2)
        context = text[max(0, match.start() - 45) : min(len(text), match.end() + 45)]
        if _is_bad_scale_context(context):
            continue
        phrase = f"{raw_number.strip()} {noun}".strip()
        count = _parse_scale_number(raw_number)
        if count:
            candidates.append((count, phrase))
    return candidates


def _is_bad_scale_context(context: str) -> bool:
    normalized = context.lower()
    bad_terms = [
        "acquired",
        "acquisition",
        "sold",
        "disposed",
        "purchased",
        "showing",
        "available",
        "listings",
        "out of",
    ]
    return any(term in normalized for term in bad_terms)


def _parse_scale_number(value: str) -> int:
    match = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*([km])?", value.lower())
    if match is None:
        return 0
    raw_number = match.group(1)
    if "," not in raw_number and re.search(r"\.\d{3}$", raw_number):
        raw_number = raw_number.replace(".", ",")
    number = float(raw_number.replace(",", ""))
    suffix = match.group(2)
    if suffix == "m":
        number *= 1_000_000
    elif suffix == "k":
        number *= 1_000
    return int(number)


def _audit(
    signal: str,
    enrichment: CompanyEnrichment,
    terms: list[str],
    parsed_value: str,
    bucket: str,
    score: int,
) -> SignalAudit:
    return SignalAudit(
        raw_evidence=_raw_evidence(enrichment, terms),
        evidence_source=None,
        parsed_value=parsed_value,
        interpreted_bucket=bucket,
        confidence=None,
        classifier="rule_fallback",
        score_contribution=score,
    )


def _audit_from_classification(
    classification: MicroSignalClassification,
    score: int,
    bucket: str | None = None,
) -> SignalAudit:
    interpreted_bucket = bucket or classification.interpreted_bucket
    return SignalAudit(
        raw_evidence=classification.raw_evidence,
        evidence_source=classification.evidence_source,
        parsed_value=classification.parsed_value,
        interpreted_bucket=interpreted_bucket,
        confidence=classification.confidence,
        classifier=classification.classifier,
        score_contribution=score,
    )


def _boost_classified_bucket(
    signal: str,
    classification: MicroSignalClassification,
    enrichment: CompanyEnrichment,
) -> str:
    bucket = classification.interpreted_bucket
    text = f"{classification.raw_evidence} {classification.parsed_value} {enrichment.source_text}".lower()
    unit_count, _ = _largest_unit_count(text)
    implicit_scale = _implicit_scale_bucket(text)

    if signal == "leasing_volume":
        if bucket == "High" and (unit_count >= 250_000 or implicit_scale == "Very High"):
            return "Very High"
        if bucket == "Medium" and (unit_count >= 20_000 or implicit_scale in {"High", "Very High"}):
            return "High"
    if signal == "operational_complexity":
        has_ops = any(term in text for term in ["leasing", "resident", "maintenance", "operations"])
        if bucket == "High" and has_ops and (unit_count >= 250_000 or implicit_scale == "Very High"):
            return "Very High"
        if bucket == "Medium" and has_ops and implicit_scale in {"High", "Very High"}:
            return "High"
    if signal == "product_fit":
        has_product_fit = any(term in text for term in ["leasing", "resident", "maintenance", "centralized"])
        if bucket == "Strong" and has_product_fit and (unit_count >= 250_000 or implicit_scale == "Very High"):
            return "Very Strong"
    return bucket


def _classified_score(signal: str, bucket: str) -> int:
    maps = {
        "leasing_volume": {
            "Very High": 13,
            "High": 11,
            "Medium": 8,
            "Low": 4,
            "None": 0,
            "Unknown": 0,
        },
        "operational_complexity": {
            "Very High": 13,
            "High": 9,
            "Medium": 6,
            "Low": 4,
            "None": 0,
            "Unknown": 0,
        },
        "product_fit": {
            "Very Strong": 13,
            "Strong": 10,
            "Moderate": 5,
            "Weak": 1,
            "None": 0,
            "Unknown": 0,
        },
    }
    return maps[signal][bucket]


def _classified_reason(signal: str, bucket: str) -> str:
    labels = {
        "leasing_volume": "Leasing volume",
        "operational_complexity": "Operational complexity",
        "product_fit": "Product fit",
    }
    return f"{labels[signal]} classified as {bucket} from source-backed evidence."


def _raw_evidence(enrichment: CompanyEnrichment, terms: list[str]) -> str:
    if not terms:
        return "No matched evidence; neutral fallback applied."

    normalized = enrichment.source_text.lower()
    for term in sorted(terms, key=len, reverse=True):
        index = normalized.find(term.lower())
        if index < 0:
            continue
        start = max(0, index - 80)
        end = min(len(enrichment.source_text), index + len(term) + 80)
        excerpt = enrichment.source_text[start:end].strip()
        return f"Matched terms: {', '.join(terms)}. Evidence excerpt: {excerpt}"

    return ", ".join(terms)


def _score_timing(timing_signals: list[str]) -> ScoreSection:
    if not timing_signals:
        return ScoreSection(
            score=2,
            max_score=10,
            reasons=["No recent timing signal was found."],
        )

    joined = " ".join(timing_signals).lower()
    strong_terms = ["expansion", "acquisition", "development", "launch", "hiring", "funding"]
    if any(term in joined for term in strong_terms):
        return ScoreSection(
            score=8,
            max_score=10,
            reasons=["Recent activity provides a timely reason for outreach."],
        )

    return ScoreSection(
        score=5,
        max_score=10,
        reasons=["Recent company or market activity provides a moderate timing signal."],
    )


def _confidence(
    metrics: MarketMetrics,
    company_enrichment: CompanyEnrichment,
    timing_signals: list[str],
) -> str:
    classifier_confidences = [
        classification.confidence for classification in company_enrichment.classifications.values()
    ]
    if classifier_confidences:
        high_count = classifier_confidences.count("High")
        medium_count = classifier_confidences.count("Medium")
        if high_count >= 2:
            return "High"
        if high_count or medium_count >= 2:
            return "Medium"

    signals = 0
    metric_values = [
        metrics.population,
        metrics.population_growth_rate,
        metrics.median_gross_rent,
        metrics.median_income,
        metrics.renter_share,
        metrics.housing_units,
        metrics.vacancy_rate,
        metrics.no_vehicle_household_share,
        metrics.public_transit_commute_share,
        metrics.walking_commute_share,
    ]
    signals += sum(1 for value in metric_values if value is not None)
    signals += 1 if company_enrichment.source_text.strip() else 0
    signals += 1 if company_enrichment.search_snippets else 0
    signals += 1 if timing_signals else 0

    total_signal_slots = len(metric_values) + 3
    coverage = signals / float(total_signal_slots)
    if coverage >= 0.7:
        return "High"
    if coverage >= 0.4:
        return "Medium"
    return "Low"
