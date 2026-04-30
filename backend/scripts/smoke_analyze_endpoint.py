import argparse
import json
import sys
from typing import Any

import httpx


DEFAULT_PAYLOAD: dict[str, Any] = {
    "leads": [
        {
            "person": {
                "name": "Avery Smith",
                "email": "avery@assetliving.com",
                "company": "Asset Living",
            },
            "building": {
                "address": "Lamar Union, 1100 S Lamar Blvd",
                "city": "Austin",
                "state": "TX",
                "country": "US",
            },
        }
    ]
}


def _print_score_summary(response_body: dict[str, Any]) -> None:
    leads = response_body.get("leads", [])
    if not leads:
        print(json.dumps(response_body, indent=2))
        return

    lead_analysis = leads[0]
    score = lead_analysis["score"]
    print(
        json.dumps(
            {
                "lead": lead_analysis["lead"],
                "final_score": score["final_score"],
                "priority": score["priority"],
                "confidence": score["confidence"],
                "market_fit": score["market_fit"],
                "company_fit": score["company_fit"],
                "property_fit": score["property_fit"],
                "company_fit_breakdown": score.get("company_fit_breakdown"),
                "property_fit_breakdown": score.get("property_fit_breakdown"),
                "why_this_lead": lead_analysis.get("why_this_lead", []),
                "sales_insights": lead_analysis.get("sales_insights", []),
                "evidence_count": len(lead_analysis.get("evidence", [])),
                "missing_data": lead_analysis.get("missing_data", []),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test /api/leads/analyze with the nested Person/Building payload.",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/api/leads/analyze",
        help="Analyze endpoint URL.",
    )
    parser.add_argument(
        "--print-payload",
        action="store_true",
        help="Print the sample request payload before sending it.",
    )
    args = parser.parse_args()

    if args.print_payload:
        print("Request payload:")
        print(json.dumps(DEFAULT_PAYLOAD, indent=2))
        print()

    try:
        response = httpx.post(args.url, json=DEFAULT_PAYLOAD, timeout=120)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        if getattr(exc, "response", None) is not None:
            print(exc.response.text, file=sys.stderr)
        raise SystemExit(1) from exc

    _print_score_summary(response.json())


if __name__ == "__main__":
    main()
