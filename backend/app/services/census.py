from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.models import MarketMetrics
from app.services.geo import STATE_NAME_BY_FIPS, normalize_place_name, state_fips

ACS_YEAR = "2023"
ACS_BASE_URL = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"

ACS_MARKET_VARIABLES = [
    "NAME",
    "B19013_001E",  # Median household income
    "B25001_001E",  # Housing units
    "B25002_001E",  # Occupancy status: total housing units
    "B25002_003E",  # Vacant housing units
    "B25003_001E",  # Tenure: occupied housing units
    "B25003_003E",  # Renter-occupied housing units
    "B08201_001E",  # Vehicles available: total households
    "B08201_002E",  # No vehicle available
    "B08301_001E",  # Means of transportation to work: total workers
    "B08301_010E",  # Public transportation
    "B08301_019E",  # Walked
]


@dataclass(frozen=True)
class CensusPlaceMarket:
    name: str
    state_fips: str
    place_fips: str
    datausa_place_id: str
    metrics: MarketMetrics


@dataclass(frozen=True)
class CensusNeighborhoodMarket:
    name: str
    state_fips: str
    county_fips: str
    tract: str
    block_group: str | None
    metrics: MarketMetrics


async def fetch_neighborhood_market(
    state_fips: str,
    county_fips: str,
    tract: str,
    block_group: str | None = None,
) -> CensusNeighborhoodMarket | None:
    """Fetch the most granular ACS geography available for the address.

    Block group is preferred when available. Some commute/vehicle variables can
    be sparse at block-group level, so missing access fields are backfilled from
    tract-level ACS data.
    """

    primary = await _fetch_acs_record(state_fips, county_fips, tract, block_group)
    if primary is None:
        primary = await _fetch_acs_record(state_fips, county_fips, tract, None)
        block_group = None
    if primary is None:
        return None

    metrics = _metrics_from_record(primary)

    if block_group and (
        metrics.no_vehicle_household_share is None
        or metrics.public_transit_commute_share is None
        or metrics.walking_commute_share is None
    ):
        tract_record = await _fetch_acs_record(state_fips, county_fips, tract, None)
        if tract_record:
            tract_metrics = _metrics_from_record(tract_record)
            metrics.no_vehicle_household_share = (
                metrics.no_vehicle_household_share
                if metrics.no_vehicle_household_share is not None
                else tract_metrics.no_vehicle_household_share
            )
            metrics.public_transit_commute_share = (
                metrics.public_transit_commute_share
                if metrics.public_transit_commute_share is not None
                else tract_metrics.public_transit_commute_share
            )
            metrics.walking_commute_share = (
                metrics.walking_commute_share
                if metrics.walking_commute_share is not None
                else tract_metrics.walking_commute_share
            )

    metrics.geography_name = str(primary.get("NAME"))
    metrics.state_fips = state_fips
    metrics.county_fips = county_fips
    metrics.tract = tract
    metrics.block_group = block_group

    return CensusNeighborhoodMarket(
        name=metrics.geography_name,
        state_fips=state_fips,
        county_fips=county_fips,
        tract=tract,
        block_group=block_group,
        metrics=metrics,
    )


async def fetch_place_market(city: str, state: str) -> CensusPlaceMarket | None:
    fips = state_fips(state)
    if fips is None:
        return None

    settings = get_settings()
    params: dict[str, str] = {
        "get": ",".join(ACS_MARKET_VARIABLES),
        "for": "place:*",
        "in": f"state:{fips}",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            ACS_BASE_URL,
            params=params,
            headers={"User-Agent": "inbound-sdr-copilot/0.1"},
        )
        response.raise_for_status()
        rows = response.json()

    if len(rows) < 2:
        return None

    headers = rows[0]
    target = normalize_place_name(city)
    state_name = STATE_NAME_BY_FIPS[fips]

    for values in rows[1:]:
        record = dict(zip(headers, values, strict=False))
        name = str(record.get("NAME", ""))
        if normalize_place_name(name) != target:
            continue
        if not name.lower().endswith(f", {state_name.lower()}"):
            continue

        place_fips = str(record["place"])
        metrics = _metrics_from_record(record)
        return CensusPlaceMarket(
            name=name,
            state_fips=fips,
            place_fips=place_fips,
            datausa_place_id=f"16000US{fips}{place_fips}",
            metrics=metrics,
        )

    return None


def _metrics_from_record(record: dict[str, Any]) -> MarketMetrics:
    median_income = _to_int(record.get("B19013_001E"))
    housing_units = _to_int(record.get("B25001_001E"))
    total_occupancy_units = _to_int(record.get("B25002_001E"))
    vacant_units = _to_int(record.get("B25002_003E"))
    tenure_total = _to_int(record.get("B25003_001E"))
    renter_units = _to_int(record.get("B25003_003E"))
    vehicle_households = _to_int(record.get("B08201_001E"))
    no_vehicle_households = _to_int(record.get("B08201_002E"))
    commute_total = _to_int(record.get("B08301_001E"))
    public_transit_commuters = _to_int(record.get("B08301_010E"))
    walking_commuters = _to_int(record.get("B08301_019E"))

    return MarketMetrics(
        median_income=median_income,
        housing_units=housing_units,
        renter_share=_safe_ratio(renter_units, tenure_total),
        vacancy_rate=_safe_ratio(vacant_units, total_occupancy_units),
        no_vehicle_household_share=_safe_ratio(no_vehicle_households, vehicle_households),
        public_transit_commute_share=_safe_ratio(public_transit_commuters, commute_total),
        walking_commute_share=_safe_ratio(walking_commuters, commute_total),
    )


async def _fetch_acs_record(
    state_fips: str,
    county_fips: str,
    tract: str,
    block_group: str | None,
) -> dict[str, Any] | None:
    settings = get_settings()
    params: dict[str, str] = {
        "get": ",".join(ACS_MARKET_VARIABLES),
        "for": f"block group:{block_group}" if block_group else f"tract:{tract}",
        "in": (
            f"state:{state_fips} county:{county_fips} tract:{tract}"
            if block_group
            else f"state:{state_fips} county:{county_fips}"
        ),
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            ACS_BASE_URL,
            params=params,
            headers={"User-Agent": "inbound-sdr-copilot/0.1"},
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        rows = response.json()

    if len(rows) < 2:
        return None
    return dict(zip(rows[0], rows[1], strict=False))


def _to_int(value: Any) -> int | None:
    if value in (None, "", "-666666666"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator
