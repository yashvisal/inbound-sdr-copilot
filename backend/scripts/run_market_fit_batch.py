import argparse
import asyncio
import json
from dataclasses import dataclass

from app.models import LeadInput
from app.scoring import score_lead
from app.services.market import enrich_market


@dataclass(frozen=True)
class TestAddress:
    street: str
    city: str
    state: str
    zip_code: str
    country: str = "US"

    @property
    def label(self) -> str:
        base = f"{self.street}, {self.city}, {self.state} {self.zip_code}"
        return base if self.country == "US" else f"{base}, {self.country}"


BASELINE_ADDRESSES = [
    TestAddress("20 Hudson Yards", "New York", "NY", "10001"),
    TestAddress("11-24 Beach 21st St", "Far Rockaway", "NY", "11691"),
    TestAddress("1201 S Joyce St", "Arlington", "VA", "22202"),
    TestAddress("5801 Tennyson Pkwy", "Plano", "TX", "75024"),
    TestAddress("310 E 3rd St", "Flint", "MI", "48502"),
    TestAddress("2100 Rideout Rd SW", "Huntsville", "AL", "35808"),
    TestAddress("315 N 7th Ave", "Bozeman", "MT", "59715"),
    TestAddress("1100 S Lamar Blvd", "Austin", "TX", "78704"),
    TestAddress("233 S Wacker Dr", "Chicago", "IL", "60606"),
    TestAddress("1100 S University Ave", "Ann Arbor", "MI", "48104"),
]

ROBUSTNESS_ADDRESSES = [
    TestAddress("701 Brickell Ave", "Miami", "FL", "33131"),
    TestAddress("55 E Monroe St", "Chicago", "IL", "60603"),
    TestAddress("1600 Amphitheatre Pkwy", "Mountain View", "CA", "94043"),
    TestAddress("400 S Hope St", "Los Angeles", "CA", "90071"),
    TestAddress("1 Infinite Loop", "Cupertino", "CA", "95014"),
    TestAddress("3500 Deer Creek Rd", "Palo Alto", "CA", "94304"),
    TestAddress("600 Montgomery St", "San Francisco", "CA", "94111"),
    TestAddress("2000 McKinney Ave", "Dallas", "TX", "75201"),
    TestAddress("1000 N West St", "Wilmington", "DE", "19801"),
    TestAddress("2500 University Dr NW", "Calgary", "AB", "T2N 1N4", "Canada"),
]

ADDRESS_SETS = {
    "baseline": BASELINE_ADDRESSES,
    "robustness": ROBUSTNESS_ADDRESSES,
}


async def analyze_address(address: TestAddress) -> dict:
    lead = LeadInput(
        name="Test Contact",
        email="test@example-property-management.com",
        company="Example Property Management",
        address=address.label,
        city=address.city,
        state=address.state,
        country=address.country,
    )
    market = await enrich_market(lead)
    score = score_lead(
        lead=lead,
        market_metrics=market.metrics,
        company_text=(
            "Example Property Management apartments leasing communities "
            "resident tenant operations"
        ),
        timing_signals=[],
    )

    return {
        "input_address": address.label,
        "geography": {
            "name": market.metrics.geography_name,
            "state_fips": market.metrics.state_fips,
            "county_fips": market.metrics.county_fips,
            "tract": market.metrics.tract,
            "block_group": market.metrics.block_group,
        },
        "address_resolution": (
            market.address_resolution.model_dump() if market.address_resolution else None
        ),
        "market_metrics": {
            "population": market.metrics.population,
            "population_growth_rate": market.metrics.population_growth_rate,
            "median_gross_rent": market.metrics.median_gross_rent,
            "median_income": market.metrics.median_income,
            "renter_share": market.metrics.renter_share,
            "housing_units": market.metrics.housing_units,
            "vacancy_rate": market.metrics.vacancy_rate,
            "no_vehicle_household_share": market.metrics.no_vehicle_household_share,
            "public_transit_commute_share": market.metrics.public_transit_commute_share,
            "walking_commute_share": market.metrics.walking_commute_share,
        },
        "market_fit": score.market_fit.model_dump(),
        "final_score_with_test_company": score.final_score,
        "priority_with_test_company": score.priority,
        "evidence": [item.model_dump() for item in market.evidence],
        "missing_data": market.missing_data,
    }


def format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_int(value: int | None) -> str:
    return "n/a" if value is None else f"{value:,}"


def print_human_readable(results: list[dict]) -> None:
    for index, result in enumerate(results, start=1):
        metrics = result["market_metrics"]
        market_fit = result["market_fit"]
        geography = result["geography"]
        resolution = result["address_resolution"]

        print("=" * 100)
        print(f"{index}. {result['input_address']}")
        print("-" * 100)
        print(f"Geography: {geography['name'] or 'n/a'}")
        print(f"Tract / Block Group: {geography['tract'] or 'n/a'} / {geography['block_group'] or 'n/a'}")
        if resolution:
            print(
                "Address Resolution: "
                f"{resolution['confidence']} via {resolution['method']}"
            )
            if resolution["matched_address"]:
                print(f"Matched Address: {resolution['matched_address']}")
            if resolution["explanation"]:
                print(f"Resolution Note: {resolution['explanation']}")
        print(f"Market Fit: {market_fit['score']} / {market_fit['max_score']}")
        print(
            "Metrics: "
            f"population={format_int(metrics['population'])}, "
            f"growth={format_pct(metrics['population_growth_rate'])}, "
            f"gross_rent={format_int(metrics['median_gross_rent'])}, "
            f"income={format_int(metrics['median_income'])}, "
            f"renter_share={format_pct(metrics['renter_share'])}, "
            f"housing_units={format_int(metrics['housing_units'])}, "
            f"vacancy={format_pct(metrics['vacancy_rate'])}, "
            f"no_vehicle={format_pct(metrics['no_vehicle_household_share'])}, "
            f"transit={format_pct(metrics['public_transit_commute_share'])}, "
            f"walking={format_pct(metrics['walking_commute_share'])}"
        )
        print("Reasons:")
        for reason in market_fit["reasons"]:
            print(f"  - {reason}")
        if result["missing_data"]:
            print("Missing data:")
            for item in result["missing_data"]:
                print(f"  - {item}")
        print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Market Fit V2 on sample property addresses.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON instead of a human-readable report.",
    )
    parser.add_argument(
        "--set",
        choices=sorted(ADDRESS_SETS),
        default="baseline",
        help="Address set to run.",
    )
    args = parser.parse_args()

    results = []
    for address in ADDRESS_SETS[args.set]:
        results.append(await analyze_address(address))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_human_readable(results)


if __name__ == "__main__":
    asyncio.run(main())
