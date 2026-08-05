import pytest

from app.models import LeadInput, MarketMetrics
from app.scoring import score_lead
from app.services import census
from app.services.geo import normalize_place_name


def test_austin_like_market_metrics_score_strong_market_fit() -> None:
    metrics = MarketMetrics(
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
    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="123 Main St",
        city="Austin",
        state="TX",
        country="US",
    )

    score = score_lead(
        lead=lead,
        market_metrics=metrics,
        company_text="Harbor Residential property management apartments leasing communities",
    )

    assert score.market_fit.score == 36
    assert (
        "High neighborhood median income indicates a strong economic base."
        in score.market_fit.reasons
    )
    assert (
        "High neighborhood renter share supports local leasing demand."
        in score.market_fit.reasons
    )
    assert (
        "High walking commute share suggests strong local walkability."
        in score.market_fit.reasons
    )


def test_market_fit_breakdown_reconciles_with_section_score() -> None:
    """Sub-scores minus the dampener must equal the reported Location Fit score."""

    metrics = MarketMetrics(
        population=2_711_226,
        population_growth_rate=0.004,
        median_gross_rent=1_900,
        median_income=137_917,
        renter_share=0.372,
        housing_units=1_097,
        vacancy_rate=0.231,
        no_vehicle_household_share=0.328,
        public_transit_commute_share=0.145,
        walking_commute_share=0.410,
    )
    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="55 E Monroe St",
        city="Chicago",
        state="IL",
        country="US",
    )

    score = score_lead(
        lead=lead,
        market_metrics=metrics,
        company_text="Harbor Residential property management apartments leasing communities",
    )

    breakdown = score.market_fit_breakdown
    assert breakdown is not None
    assert set(breakdown.score_breakdown) == {
        "city_momentum",
        "rental_demand",
        "economics",
        "leasing_pressure",
        "access",
    }
    assert sum(sub.max_score for sub in breakdown.score_breakdown.values()) == 45
    subtotal = sum(sub.score for sub in breakdown.score_breakdown.values())
    assert subtotal - breakdown.dampener_penalty == score.market_fit.score
    assert breakdown.dampener_penalty == 2

    # Details carry the real Census values that drove each component.
    assert "renter share 37%" in breakdown.score_breakdown["rental_demand"].detail
    assert "vacancy 23%" in breakdown.score_breakdown["leasing_pressure"].detail


def test_market_fit_breakdown_tolerates_missing_metrics() -> None:
    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="123 Main St",
        city="Nowhere",
        state="XX",
        country="US",
    )

    score = score_lead(lead=lead, market_metrics=MarketMetrics(), company_text="")

    breakdown = score.market_fit_breakdown
    assert breakdown is not None
    assert breakdown.score_breakdown["economics"].detail is None


def test_small_housing_base_does_not_directly_penalize_market_fit() -> None:
    metrics = MarketMetrics(
        population=56_114,
        population_growth_rate=0.161,
        median_gross_rent=1_650,
        median_income=106_625,
        renter_share=0.73,
        housing_units=400,
        vacancy_rate=0.128,
        no_vehicle_household_share=0.052,
        public_transit_commute_share=0,
        walking_commute_share=0.031,
    )
    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="315 N 7th Ave",
        city="Bozeman",
        state="MT",
        country="US",
    )

    score = score_lead(
        lead=lead,
        market_metrics=metrics,
        company_text="Harbor Residential property management apartments leasing communities",
    )

    assert score.market_fit.score >= 30
    assert not any("housing base weakens" in reason for reason in score.market_fit.reasons)


def test_dense_urban_income_anomaly_is_treated_neutral() -> None:
    metrics = MarketMetrics(
        population=830_235,
        population_growth_rate=-0.051,
        median_gross_rent=2_200,
        median_income=14_508,
        renter_share=0.85,
        housing_units=612,
        vacancy_rate=0.133,
        no_vehicle_household_share=0.733,
        public_transit_commute_share=0.374,
        walking_commute_share=0.547,
    )
    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="600 Montgomery St",
        city="San Francisco",
        state="CA",
        country="US",
    )

    score = score_lead(
        lead=lead,
        market_metrics=metrics,
        company_text="Harbor Residential property management apartments leasing communities",
    )

    assert (
        "Neighborhood income appears atypical for a dense urban tract, so it is treated as neutral."
        in score.market_fit.reasons
    )


def test_low_renter_high_vacancy_mixed_use_pattern_gets_light_dampener() -> None:
    metrics = MarketMetrics(
        population=2_711_226,
        population_growth_rate=0.004,
        median_gross_rent=1_900,
        median_income=137_917,
        renter_share=0.372,
        housing_units=1_097,
        vacancy_rate=0.231,
        no_vehicle_household_share=0.328,
        public_transit_commute_share=0.145,
        walking_commute_share=0.410,
    )
    lead = LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="55 E Monroe St",
        city="Chicago",
        state="IL",
        country="US",
    )

    score = score_lead(
        lead=lead,
        market_metrics=metrics,
        company_text="Harbor Residential property management apartments leasing communities",
    )

    assert (
        "Low renter share plus high vacancy suggests a mixed-use or commercial pattern, so Market Fit is lightly dampened."
        in score.market_fit.reasons
    )


def _stub_place_population(monkeypatch, by_year: dict[str, int | None]) -> None:
    async def fake(client, state_fips, place_fips, base_url):
        return by_year.get(base_url)

    monkeypatch.setattr(census, "_fetch_place_population", fake)


@pytest.mark.anyio
async def test_population_history_computes_growth_across_acs_vintages(monkeypatch) -> None:
    _stub_place_population(
        monkeypatch,
        {census.ACS_BASE_URL: 979_539, census.ACS_GROWTH_BASE_URL: 958_202},
    )

    history = await census.fetch_place_population_history("4805000")

    assert history is not None
    assert history.latest_population == 979_539
    assert history.latest_year == int(census.ACS_YEAR)
    assert history.earliest_year == int(census.ACS_GROWTH_BASE_YEAR)
    assert history.growth_rate is not None
    assert round(history.growth_rate, 4) == 0.0223


@pytest.mark.anyio
async def test_population_history_survives_missing_baseline(monkeypatch) -> None:
    """A failed baseline lookup should still yield population, just no growth."""

    _stub_place_population(
        monkeypatch,
        {census.ACS_BASE_URL: 979_539, census.ACS_GROWTH_BASE_URL: None},
    )

    history = await census.fetch_place_population_history("4805000")

    assert history is not None
    assert history.latest_population == 979_539
    assert history.growth_rate is None


@pytest.mark.anyio
async def test_population_history_is_none_without_current_population(monkeypatch) -> None:
    _stub_place_population(monkeypatch, {})

    assert await census.fetch_place_population_history("4805000") is None


def test_place_name_normalization_handles_census_suffixes() -> None:
    assert normalize_place_name("Austin city, Texas") == "austin"
    assert normalize_place_name("Austin") == "austin"
