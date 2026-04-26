from dataclasses import dataclass
from typing import Any

import httpx

DATAUSA_BASE_URL = "https://api.datausa.io/tesseract"
POPULATION_CUBE = "acs_yg_total_population_5"


@dataclass(frozen=True)
class PopulationHistory:
    latest_population: int | None
    growth_rate: float | None
    latest_year: int | None
    earliest_year: int | None


async def fetch_population_history(place_id: str) -> PopulationHistory:
    params = {
        "cube": POPULATION_CUBE,
        "drilldowns": "Place,Year",
        "measures": "Population",
        "include": f"Place:{place_id}",
        "time": "Year.latest.5",
        "sort": "Year.desc",
        "limit": "10,0",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{DATAUSA_BASE_URL}/data.jsonrecords",
            params=params,
            headers={"User-Agent": "inbound-sdr-copilot/0.1"},
        )
        response.raise_for_status()
        payload = response.json()

    records = payload.get("data", [])
    return _population_history_from_records(records)


def _population_history_from_records(records: list[dict[str, Any]]) -> PopulationHistory:
    parsed: list[tuple[int, int]] = []
    for record in records:
        year_raw = record.get("Year")
        population_raw = record.get("Population")
        if year_raw is None or population_raw is None:
            continue
        if isinstance(year_raw, str) and not str(year_raw).strip():
            continue
        if isinstance(population_raw, str) and not str(population_raw).strip():
            continue
        try:
            year = int(float(year_raw))
            population = int(float(population_raw))
        except (TypeError, ValueError):
            continue
        parsed.append((year, population))

    parsed.sort(reverse=True)
    if not parsed:
        return PopulationHistory(None, None, None, None)

    latest_year, latest_population = parsed[0]
    earliest_year, earliest_population = parsed[-1]
    growth_rate = None
    if earliest_population:
        growth_rate = (latest_population - earliest_population) / earliest_population

    return PopulationHistory(
        latest_population=latest_population,
        growth_rate=growth_rate,
        latest_year=latest_year,
        earliest_year=earliest_year,
    )
