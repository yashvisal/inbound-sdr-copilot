from app.models import LeadInput, MarketMetrics
from app.scoring import score_lead
from app.services.datausa import _population_history_from_records
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
        timing_signals=[],
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
        timing_signals=[],
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
        timing_signals=[],
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
        timing_signals=[],
    )

    assert (
        "Low renter share plus high vacancy suggests a mixed-use or commercial pattern, so Market Fit is lightly dampened."
        in score.market_fit.reasons
    )


def test_population_history_computes_growth_from_latest_window() -> None:
    history = _population_history_from_records(
        [
            {"Year": 2024, "Population": 979539.0},
            {"Year": 2023, "Population": 967862.0},
            {"Year": 2022, "Population": 958202.0},
        ]
    )

    assert history.latest_population == 979_539
    assert history.latest_year == 2024
    assert history.earliest_year == 2022
    assert history.growth_rate is not None
    assert round(history.growth_rate, 4) == 0.0223


def test_population_history_skips_malformed_rows() -> None:
    history = _population_history_from_records(
        [
            {"Year": 2024, "Population": 979539.0},
            {"Year": "", "Population": 1},
            {"Year": 2023, "Population": "N/A"},
            {"Year": 2022, "Population": 958202.0},
        ]
    )

    assert history.latest_population == 979_539
    assert history.latest_year == 2024
    assert history.earliest_year == 2022
    assert history.growth_rate is not None


def test_place_name_normalization_handles_census_suffixes() -> None:
    assert normalize_place_name("Austin city, Texas") == "austin"
    assert normalize_place_name("Austin") == "austin"
