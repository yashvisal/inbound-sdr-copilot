from app.models import LeadInput, MarketMetrics
from app.scoring import score_lead
from app.services.datausa import _population_history_from_records
from app.services.geo import normalize_place_name


def test_austin_like_market_metrics_score_strong_market_fit() -> None:
    metrics = MarketMetrics(
        population=979_539,
        population_growth_rate=0.014,
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

    assert score.market_fit.score == 37
    assert (
        "High neighborhood median income indicates a strong economic base."
        in score.market_fit.reasons
    )
    assert (
        "Very high neighborhood renter share indicates strong local rental demand."
        in score.market_fit.reasons
    )
    assert (
        "High walking commute share suggests strong local walkability."
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


def test_place_name_normalization_handles_census_suffixes() -> None:
    assert normalize_place_name("Austin city, Texas") == "austin"
    assert normalize_place_name("Austin") == "austin"
