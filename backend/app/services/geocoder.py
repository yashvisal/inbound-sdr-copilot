from dataclasses import dataclass
import re
from typing import Any

import httpx

from app.models import AddressResolution

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
COORDINATES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "inbound-sdr-copilot/0.1"


@dataclass(frozen=True)
class AddressGeography:
    matched_address: str
    latitude: float
    longitude: float
    state_fips: str
    county_fips: str
    tract: str
    block_group: str | None
    place_geoid: str | None
    place_name: str | None
    resolution: AddressResolution


async def geocode_address(address: str, city: str, state: str) -> AddressGeography | None:
    input_address = _full_address(address, city, state)

    async with httpx.AsyncClient(timeout=20) as client:
        exact = await _census_address_match(client, input_address)
        if exact:
            resolution = AddressResolution(
                confidence="High",
                method="census_exact",
                input_address=input_address,
                matched_address=exact.get("matchedAddress"),
                latitude=float(exact.get("coordinates", {}).get("y")),
                longitude=float(exact.get("coordinates", {}).get("x")),
            )
            return _geography_from_match(exact, resolution)

        coordinate_fallback = await _coordinate_fallback(client, input_address)
        if coordinate_fallback:
            return coordinate_fallback

        for query in _variant_queries(input_address):
            match = await _census_address_match(client, query)
            if match:
                resolution = AddressResolution(
                    confidence="Low",
                    method="census_variant",
                    input_address=input_address,
                    matched_address=match.get("matchedAddress"),
                    latitude=float(match.get("coordinates", {}).get("y")),
                    longitude=float(match.get("coordinates", {}).get("x")),
                    explanation=(
                        "We could not find a direct Census match for the submitted address. "
                        "A normalized address variant matched Census, so neighborhood data is "
                        "based on that matched geography. Please review the matched address."
                    ),
                )
                return _geography_from_match(match, resolution)

    return None


async def _census_address_match(
    client: httpx.AsyncClient,
    query: str,
) -> dict[str, Any] | None:
    response = await client.get(
        GEOCODER_URL,
        params={
            "address": query,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    payload = response.json()
    matches = payload.get("result", {}).get("addressMatches", [])
    return matches[0] if matches else None


async def _coordinate_fallback(
    client: httpx.AsyncClient,
    input_address: str,
) -> AddressGeography | None:
    response = await client.get(
        NOMINATIM_URL,
        params={
            "q": input_address,
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "1",
        },
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None

    result = results[0]
    latitude = float(result["lat"])
    longitude = float(result["lon"])
    geo_response = await client.get(
        COORDINATES_URL,
        params={
            "x": longitude,
            "y": latitude,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "format": "json",
        },
        headers={"User-Agent": USER_AGENT},
    )
    geo_response.raise_for_status()
    geographies = geo_response.json().get("result", {}).get("geographies", {})
    resolution = AddressResolution(
        confidence="Medium",
        method="coordinate_fallback",
        input_address=input_address,
        matched_address=result.get("display_name"),
        latitude=latitude,
        longitude=longitude,
        explanation=(
            "We could not find a direct Census match for the submitted address, "
            "so we used coordinate-based resolution. The fallback returned a "
            "location that appears to match the submitted address or property "
            "area, and Census mapped that coordinate to a tract/block group. "
            "The Market Fit score is based on that resolved geography."
        ),
    )
    return _geography_from_geographies(geographies, resolution)


def _geography_from_match(
    match: dict[str, Any],
    resolution: AddressResolution,
) -> AddressGeography | None:
    geographies = match.get("geographies", {})
    return _geography_from_geographies(geographies, resolution)


def _geography_from_geographies(
    geographies: dict[str, Any],
    resolution: AddressResolution,
) -> AddressGeography | None:
    tract = _first(geographies, "Census Tracts")
    block = _first(geographies, "2020 Census Blocks")
    place = _first(geographies, "Incorporated Places")

    if tract is None:
        return None

    state_fips = str(tract.get("STATE", ""))
    county_fips = str(tract.get("COUNTY", ""))
    tract_id = str(tract.get("TRACT", ""))
    if not state_fips or not county_fips or not tract_id:
        return None

    return AddressGeography(
        matched_address=resolution.matched_address or "",
        latitude=resolution.latitude or 0,
        longitude=resolution.longitude or 0,
        state_fips=state_fips,
        county_fips=county_fips,
        tract=tract_id,
        block_group=str(block.get("BLKGRP")) if block else None,
        place_geoid=str(place.get("GEOID")) if place else None,
        place_name=str(place.get("NAME")) if place else None,
        resolution=resolution,
    )


def _first(geographies: dict[str, Any], key: str) -> dict[str, Any] | None:
    values = geographies.get(key) or []
    return values[0] if values else None


def _full_address(address: str, city: str, state: str) -> str:
    normalized = address.strip()
    if city.lower() in normalized.lower() and state.lower() in normalized.lower():
        return normalized
    return ", ".join(part.strip() for part in [address, city, state] if part.strip())


def _variant_queries(input_address: str) -> list[str]:
    variants = {
        re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", input_address, flags=re.IGNORECASE),
        input_address.replace(" Street", " St").replace(" street", " St"),
        input_address.replace(" St,", " Street,"),
        input_address.replace(" Road", " Rd").replace(" road", " Rd"),
        input_address.replace(" Rd,", " Road,"),
    }
    variants.discard(input_address)
    return [variant for variant in variants if variant.strip()]
