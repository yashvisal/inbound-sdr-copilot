import re

from app.models import CompanyFitLabel, LeadInput, MarketMetrics, ScoreBreakdown, ScoreSection


REAL_ESTATE_KEYWORDS = {
    "apartment",
    "apartments",
    "community",
    "communities",
    "leasing",
    "multifamily",
    "property management",
    "real estate",
    "rental",
    "residential",
}


def score_lead(
    lead: LeadInput,
    market_metrics: MarketMetrics,
    company_text: str,
    timing_signals: list[str],
) -> ScoreBreakdown:
    """Compute the deterministic MVP score.

    This initial scaffold uses conservative keyword and metric thresholds. API
    integrations can later replace the empty/default inputs without changing
    the contract consumed by the frontend.
    """

    market_fit = _score_market_fit(market_metrics)
    company_fit, company_fit_label, unrelated = _score_company_fit(company_text)
    timing = _score_timing(timing_signals)

    final_score = market_fit.score + company_fit.score + timing.score
    if unrelated:
        final_score = min(final_score, 60)

    priority = "High" if final_score >= 80 else "Medium" if final_score >= 55 else "Low"
    confidence = _confidence(market_metrics, company_text, timing_signals)

    return ScoreBreakdown(
        market_fit=market_fit,
        company_fit=company_fit,
        timing=timing,
        final_score=final_score,
        priority=priority,
        company_fit_label=company_fit_label,
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


def _score_company_fit(company_text: str) -> tuple[ScoreSection, CompanyFitLabel, bool]:
    normalized = company_text.lower()
    tokens = set(re.findall(r"\b\w+\b", normalized))
    keyword_hits = [keyword for keyword in REAL_ESTATE_KEYWORDS if keyword in normalized]
    reasons: list[str] = []

    if len(keyword_hits) >= 3:
        business_type_score = 16
        label: CompanyFitLabel = "Strong fit"
        reasons.append("Public company text strongly matches property management ICP keywords.")
    elif keyword_hits:
        business_type_score = 10
        label = "Likely fit"
        reasons.append("Public company text has some real estate or residential fit signals.")
    elif normalized.strip():
        business_type_score = 4
        label = "Unclear fit"
        reasons.append("Company context was found, but ICP fit remains unclear.")
    else:
        business_type_score = 3
        label = "Unclear fit"
        reasons.append("Company context was unavailable, so fit confidence is limited.")

    scale_score = (
        9 if any(term in tokens for term in ["portfolio", "properties", "units", "locations"]) else 2
    )
    complexity_score = (
        8
        if any(term in tokens for term in ["resident", "tenant", "tour", "maintenance", "renewal"])
        else 2
    )
    activity_phrase_hits = bool(
        re.search(r"\bnew\s+expansion\b", normalized)
        or re.search(r"\bnew\s+development\b", normalized)
        or re.search(r"\bnew\s+acquisition\b", normalized)
    )
    activity_core_tokens = ("expansion", "growth", "hiring", "acquisition", "development")
    new_activity_adjacent = bool(
        re.search(
            r"\bnew\s+(expansion|development|acquisition|growth|hiring|hire|hires)\b",
            normalized,
        )
    )
    activity_token_hits = any(term in tokens for term in activity_core_tokens) or new_activity_adjacent
    activity_score = 6 if activity_phrase_hits or activity_token_hits else 1
    property_relevance_score = 3

    if scale_score > 2:
        reasons.append("Company text suggests multiple properties, units, or locations.")
    if complexity_score > 2:
        reasons.append("Company text references resident, tenant, leasing, or operations workflows.")
    if activity_score > 1:
        reasons.append("Company text suggests recent activity or growth.")
    reasons.append("Property relevance scoring is not connected yet; neutral score applied.")

    total = business_type_score + scale_score + complexity_score + activity_score + property_relevance_score
    unrelated = bool(normalized.strip()) and not keyword_hits
    if unrelated:
        label = "Poor fit"

    return ScoreSection(score=min(total, 45), max_score=45, reasons=reasons), label, unrelated


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
    company_text: str,
    timing_signals: list[str],
) -> str:
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
    signals += 1 if company_text.strip() else 0
    signals += 1 if timing_signals else 0

    total_signal_slots = len(metric_values) + 2
    coverage = signals / float(total_signal_slots)
    if coverage >= 0.7:
        return "High"
    if coverage >= 0.4:
        return "Medium"
    return "Low"
