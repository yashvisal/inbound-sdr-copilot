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
        final_score = min(final_score, 50)

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

    if metrics.population is None:
        reasons.append("Population data was unavailable.")
    elif metrics.population >= 1_000_000:
        score += 10
        reasons.append("Large population base suggests meaningful renter demand.")
    elif metrics.population >= 250_000:
        score += 6
        reasons.append("Mid-size population base suggests a moderate demand pool.")
    else:
        score += 3
        reasons.append("Smaller population base limits the estimated demand pool.")

    if metrics.population_growth_rate is None:
        reasons.append("Population growth data was unavailable.")
    elif metrics.population_growth_rate >= 0.05:
        score += 10
        reasons.append("Strong population growth suggests continued rental demand.")
    elif metrics.population_growth_rate >= 0:
        score += 6
        reasons.append("Stable or moderate population growth supports leasing demand.")
    else:
        score += 2
        reasons.append("Declining population lowers the market momentum signal.")

    if metrics.median_income is None:
        reasons.append("Income data was unavailable.")
    elif metrics.median_income >= 90_000:
        score += 10
        reasons.append("High median income indicates a strong economic base.")
    elif metrics.median_income >= 55_000:
        score += 6
        reasons.append("Median income indicates a moderate economic base.")
    else:
        score += 3
        reasons.append("Lower median income weakens the economic strength signal.")

    if metrics.renter_share is None:
        reasons.append("Renter-share data was unavailable.")
    elif metrics.renter_share >= 0.45:
        score += 10
        reasons.append("High renter share indicates a leasing-heavy market.")
    elif metrics.renter_share >= 0.30:
        score += 6
        reasons.append("Moderate renter share supports rental-market relevance.")
    else:
        score += 3
        reasons.append("Lower renter share weakens the rental intensity signal.")

    return ScoreSection(score=min(score, 40), max_score=40, reasons=reasons)


def _score_company_fit(company_text: str) -> tuple[ScoreSection, CompanyFitLabel, bool]:
    normalized = company_text.lower()
    keyword_hits = [keyword for keyword in REAL_ESTATE_KEYWORDS if keyword in normalized]
    reasons: list[str] = []

    if len(keyword_hits) >= 3:
        business_type_score = 18
        label: CompanyFitLabel = "Strong fit"
        reasons.append("Public company text strongly matches property management ICP keywords.")
    elif keyword_hits:
        business_type_score = 12
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

    scale_score = 6 if any(term in normalized for term in ["portfolio", "properties", "units", "locations"]) else 2
    complexity_score = 6 if any(term in normalized for term in ["resident", "tenant", "tour", "maintenance", "renewal"]) else 2
    activity_score = 4 if any(term in normalized for term in ["new", "expansion", "growth", "hiring", "acquisition"]) else 1

    if scale_score > 2:
        reasons.append("Company text suggests multiple properties, units, or locations.")
    if complexity_score > 2:
        reasons.append("Company text references resident, tenant, leasing, or operations workflows.")
    if activity_score > 1:
        reasons.append("Company text suggests recent activity or growth.")

    total = business_type_score + scale_score + complexity_score + activity_score
    unrelated = bool(normalized.strip()) and not keyword_hits
    if unrelated:
        label = "Poor fit"

    return ScoreSection(score=min(total, 50), max_score=50, reasons=reasons), label, unrelated


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
    signals += sum(
        value is not None
        for value in [
            metrics.population,
            metrics.population_growth_rate,
            metrics.median_income,
            metrics.renter_share,
        ]
    )
    signals += 1 if company_text.strip() else 0
    signals += 1 if timing_signals else 0

    if signals >= 5:
        return "High"
    if signals >= 3:
        return "Medium"
    return "Low"
