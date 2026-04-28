from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import httpx

from app.models import AddressResolution

logger = logging.getLogger(__name__)

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
COORDINATES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "inbound-sdr-copilot/0.1"

_GEOCODER_LOG_EXTRA = {"source": "census_geocoder"}
_COORD_FALLBACK_EXTRA = {"source": "geocoder", "stage": "coordinate_fallback"}


def _safe_float_coord(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AddressGeography:
    matched_address: str
    latitude: float | None
    longitude: float | None
    state_fips: str
    county_fips: str
    tract: str
    block_group: str | None
    place_geoid: str | None
    place_name: str | None
    resolution: AddressResolution


@dataclass(frozen=True)
class OSMAddressMetadata:
    osm_class: str | None
    osm_type: str | None
    display_name: str | None
    latitude: float | None
    longitude: float | None


async def fetch_osm_address_metadata(
    address: str,
    city: str,
    state: str,
) -> OSMAddressMetadata | None:
    input_address = _full_address(address, city, state)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            result = await _nominatim_search(client, input_address)
        except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            logger.warning(
                "Nominatim property metadata request failed: %s",
                type(exc).__name__,
                extra={**_COORD_FALLBACK_EXTRA, "stage_detail": "property_metadata"},
            )
            return None
    if result is None:
        return None
    return OSMAddressMetadata(
        osm_class=str(result.get("class") or "") or None,
        osm_type=str(result.get("type") or "") or None,
        display_name=str(result.get("display_name") or "") or None,
        latitude=_safe_float_coord(result.get("lat")),
        longitude=_safe_float_coord(result.get("lon")),
    )


async def geocode_address(address: str, city: str, state: str) -> AddressGeography | None:
    input_address = _full_address(address, city, state)

    async with httpx.AsyncClient(timeout=20) as client:
        exact = await _census_address_match(client, input_address)
        if exact:
            lat = _safe_float_coord(exact.get("coordinates", {}).get("y"))
            lon = _safe_float_coord(exact.get("coordinates", {}).get("x"))
            if lat is not None and lon is not None:
                resolution = AddressResolution(
                    confidence="High",
                    method="census_exact",
                    input_address=input_address,
                    matched_address=exact.get("matchedAddress"),
                    latitude=lat,
                    longitude=lon,
                )
                geo = _geography_from_match(exact, resolution)
                if geo is not None:
                    return geo
            else:
                logger.warning(
                    "Census address match missing valid coordinates; trying fallbacks.",
                    extra={**_GEOCODER_LOG_EXTRA, "stage": "exact_match_invalid_coords"},
                )

        coordinate_fallback = await _coordinate_fallback(client, input_address)
        if coordinate_fallback:
            return coordinate_fallback

        for query in _variant_queries(input_address):
            match = await _census_address_match(client, query)
            if match:
                lat = _safe_float_coord(match.get("coordinates", {}).get("y"))
                lon = _safe_float_coord(match.get("coordinates", {}).get("x"))
                if lat is None or lon is None:
                    logger.warning(
                        "Census variant match missing valid coordinates; skipping variant.",
                        extra={**_GEOCODER_LOG_EXTRA, "stage": "variant_invalid_coords"},
                    )
                    continue
                resolution = AddressResolution(
                    confidence="Low",
                    method="census_variant",
                    input_address=input_address,
                    matched_address=match.get("matchedAddress"),
                    latitude=lat,
                    longitude=lon,
                    explanation=(
                        "We could not find a direct Census match for the submitted address. "
                        "A normalized address variant matched Census, so neighborhood data is "
                        "based on that matched geography. Please review the matched address."
                    ),
                )
                geo = _geography_from_match(match, resolution)
                if geo is not None:
                    return geo

    return None


async def _census_address_match(
    client: httpx.AsyncClient,
    query: str,
) -> dict[str, Any] | None:
    try:
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
    except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
        logger.warning(
            "Census geocoder request failed: %s",
            type(exc).__name__,
            extra={**_GEOCODER_LOG_EXTRA, "stage": "address_match"},
        )
        return None
    except Exception as exc:
        logger.warning(
            "Census geocoder request failed unexpectedly: %s",
            type(exc).__name__,
            extra={**_GEOCODER_LOG_EXTRA, "stage": "address_match"},
        )
        return None

    matches = payload.get("result", {}).get("addressMatches", [])
    return matches[0] if matches else None


async def _coordinate_fallback(
    client: httpx.AsyncClient,
    input_address: str,
) -> AddressGeography | None:
    try:
        result = await _nominatim_search(client, input_address)
        if result is None:
            return None
        latitude = _safe_float_coord(result.get("lat"))
        longitude = _safe_float_coord(result.get("lon"))
        if latitude is None or longitude is None:
            logger.warning(
                "Nominatim result missing valid lat/lon; coordinate fallback aborted.",
                extra={**_COORD_FALLBACK_EXTRA, "stage_detail": "invalid_nominatim_coords"},
            )
            return None
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
    except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
        logger.warning(
            "Coordinate fallback request failed: %s",
            type(exc).__name__,
            extra=_COORD_FALLBACK_EXTRA,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Coordinate fallback failed unexpectedly: %s",
            type(exc).__name__,
            extra=_COORD_FALLBACK_EXTRA,
        )
        return None


async def _nominatim_search(
    client: httpx.AsyncClient,
    input_address: str,
) -> dict[str, Any] | None:
    response = await client.get(
        NOMINATIM_URL,
        params={
            "q": input_address,
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "1",
            "extratags": "1",
        },
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    results = response.json()
    return results[0] if results else None


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

    block_group: str | None = None
    if block:
        bg = block.get("BLKGRP")
        block_group = str(bg) if bg is not None else None
    place_geoid: str | None = None
    place_name: str | None = None
    if place:
        geoid = place.get("GEOID")
        place_geoid = str(geoid) if geoid is not None else None
        pname = place.get("NAME")
        place_name = str(pname) if pname is not None else None

    return AddressGeography(
        matched_address=resolution.matched_address or "",
        latitude=resolution.latitude,
        longitude=resolution.longitude,
        state_fips=state_fips,
        county_fips=county_fips,
        tract=tract_id,
        block_group=block_group,
        place_geoid=place_geoid,
        place_name=place_name,
        resolution=resolution,
    )


def _first(geographies: dict[str, Any], key: str) -> dict[str, Any] | None:
    values = geographies.get(key) or []
    return values[0] if values else None


def _full_address(address: str, city: str, state: str) -> str:
    normalized = address.strip()
    city_token = city.strip().lower()
    state_token = state.strip().lower()
    norm_lower = normalized.lower()
    if not city_token or not state_token:
        return ", ".join(part.strip() for part in [address, city, state] if part.strip())
    city_pat = re.compile(rf"\b{re.escape(city_token)}\b")
    state_pat = re.compile(rf"\b{re.escape(state_token)}\b")
    if city_pat.search(norm_lower) and state_pat.search(norm_lower):
        return normalized
    return ", ".join(part.strip() for part in [address, city, state] if part.strip())


def _variant_queries(input_address: str) -> list[str]:
    base = input_address.strip()
    transformations = [
        re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", input_address, flags=re.IGNORECASE),
        input_address.replace(" Street", " St").replace(" street", " St"),
        input_address.replace(" St,", " Street,"),
        input_address.replace(" Road", " Rd").replace(" road", " Rd"),
        input_address.replace(" Rd,", " Road,"),
    ]
    seen: set[str] = set()
    variants: list[str] = []
    for candidate in transformations:
        cleaned = candidate.strip()
        if not cleaned or cleaned == base or cleaned in seen:
            continue
        seen.add(cleaned)
        variants.append(cleaned)
    return variants
