import logging
from dataclasses import dataclass

from app.models import AddressResolution, LeadInput, MarketMetrics, SourceSnippet
from app.services.census import (
    ACS_YEAR,
    fetch_neighborhood_market,
    fetch_place_market,
    fetch_place_market_by_geoid,
)
from app.services.datausa import fetch_population_history
from app.services.geocoder import geocode_address

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketEnrichment:
    metrics: MarketMetrics
    evidence: list[SourceSnippet]
    missing_data: list[str]
    address_resolution: AddressResolution | None = None


async def enrich_market(lead: LeadInput) -> MarketEnrichment:
    if lead.country.strip().upper() not in {"US", "USA", "UNITED STATES"}:
        return MarketEnrichment(
            metrics=MarketMetrics(),
            evidence=[],
            missing_data=["Market enrichment currently supports U.S. leads only."],
            address_resolution=AddressResolution(
                confidence="Unresolved",
                method="unsupported_country",
                input_address=", ".join(
                    part for part in [lead.address, lead.city, lead.state, lead.country] if part
                ),
                explanation="Address resolution currently supports U.S. addresses only.",
            ),
        )

    missing_data: list[str] = []
    evidence: list[SourceSnippet] = []

    geography = None
    try:
        geography = await geocode_address(lead.address, lead.city, lead.state)
    except Exception:
        logger.exception("Census geocoder request failed")
        missing_data.append("Census Geocoder request failed; address was not resolved.")

    address_resolution = geography.resolution if geography else AddressResolution(
        confidence="Unresolved",
        method="failed",
        input_address=", ".join(part for part in [lead.address, lead.city, lead.state] if part),
        explanation=(
            "We could not resolve this address to a Census tract or block group. "
            "Please confirm the street address, city, state, and ZIP."
        ),
    )
    place = None
    if geography:
        neighborhood = None
        try:
            neighborhood = await fetch_neighborhood_market(
                state_fips=geography.state_fips,
                county_fips=geography.county_fips,
                tract=geography.tract,
                block_group=geography.block_group,
            )
        except Exception:
            logger.exception("Neighborhood ACS request failed")
            missing_data.append("Neighborhood ACS request failed.")

        if neighborhood is None:
            metrics = MarketMetrics()
            if "Neighborhood ACS request failed." not in missing_data:
                missing_data.append("Neighborhood ACS enrichment was unavailable.")
        else:
            metrics = neighborhood.metrics
            evidence.append(
                SourceSnippet(
                    source="Census Geocoder + ACS 5-Year",
                    title=f"{neighborhood.name} ACS {ACS_YEAR} neighborhood profile",
                    url=f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5",
                    snippet=(
                        f"Resolved address to tract {geography.tract}"
                        f"{f', block group {geography.block_group}' if geography.block_group else ''}; "
                        f"loaded local renter share, income, housing units, vacancy, "
                        f"and urban access proxy metrics."
                    ),
                )
            )
            if geography.resolution.explanation:
                evidence.append(
                    SourceSnippet(
                        source="Address Resolution",
                        title=f"{geography.resolution.confidence} confidence address match",
                        snippet=geography.resolution.explanation,
                    )
                )
    else:
        metrics = MarketMetrics()
        if not any("Census Geocoder request failed" in msg for msg in missing_data):
            missing_data.append("Census Geocoder could not resolve the property address.")

    if geography and geography.place_geoid:
        datausa_place_id = f"16000US{geography.place_geoid}"
        place_name = geography.place_name or f"{lead.city}, {lead.state}"
        try:
            place = await fetch_place_market_by_geoid(geography.place_geoid)
        except Exception:
            logger.exception("Place-level ACS fetch by GEOID failed")
            place = None
            missing_data.append("Place-level ACS request failed for resolved geography.")
    else:
        datausa_place_id = None
        place_name = f"{lead.city}, {lead.state}"
        try:
            place = await fetch_place_market(lead.city, lead.state)
        except Exception:
            logger.exception("Place-level ACS fetch failed for %s, %s", lead.city, lead.state)
            place = None
            missing_data.append(f"Place-level ACS request failed for {lead.city}, {lead.state}.")

    if place is None:
        if datausa_place_id is None:
            missing_data.append(f"Could not resolve Census place for {lead.city}, {lead.state}.")
    else:
        datausa_place_id = place.datausa_place_id
        place_name = place.name
        metrics.median_gross_rent = place.metrics.median_gross_rent

    if datausa_place_id:
        try:
            population_history = await fetch_population_history(datausa_place_id)
        except Exception:
            population_history = None
            missing_data.append("Data USA population history was unavailable.")
    else:
        population_history = None

    if population_history is None or population_history.latest_population is None:
        missing_data.append("Population data was unavailable from Data USA.")
    else:
        metrics.population = population_history.latest_population
        metrics.population_growth_rate = population_history.growth_rate
        evidence.append(
            SourceSnippet(
                source="Data USA",
                title=f"{place_name} population trend",
                url="https://api.datausa.io/tesseract/data.jsonrecords",
                snippet=(
                    f"Latest population was {population_history.latest_population:,} "
                    f"in {population_history.latest_year}; growth is calculated across "
                    f"available history since {population_history.earliest_year}."
                ),
            )
        )

    for field_name, label in [
        ("median_gross_rent", "Median gross rent"),
        ("median_income", "Median income"),
        ("housing_units", "Housing units"),
        ("renter_share", "Renter share"),
        ("vacancy_rate", "Vacancy rate"),
        ("no_vehicle_household_share", "No-vehicle household share"),
        ("public_transit_commute_share", "Public transit commute share"),
        ("walking_commute_share", "Walking commute share"),
    ]:
        if getattr(metrics, field_name) is None:
            missing_data.append(f"{label} was unavailable from ACS.")

    return MarketEnrichment(
        metrics=metrics,
        evidence=evidence,
        missing_data=missing_data,
        address_resolution=address_resolution,
    )
