import argparse
import json
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def _print_score_summary(
    response_body: dict[str, Any],
    outreach_results: list[dict[str, Any]],
) -> None:
    leads = response_body.get("leads", [])
    if not leads:
        print(json.dumps(response_body, indent=2))
        return

    summaries = []
    for index, lead_analysis in enumerate(leads):
        score = lead_analysis["score"]
        outreach = outreach_results[index] if index < len(outreach_results) else {}
        summaries.append(
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
                "generated_outreach": {
                    "sales_insights": outreach.get("sales_insights", []),
                    "personalized_email": outreach.get("personalized_email", ""),
                },
            }
        )

    print(
        json.dumps(
            {"leads": summaries},
            indent=2,
        )
    )


def _default_outreach_url(analyze_url: str) -> str:
    parts = urlsplit(analyze_url)
    path = parts.path.removesuffix("/api/leads/analyze")
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"{path}/api/leads/generate-outreach",
            "",
            "",
        )
    )


def _generate_outreach_for_leads(
    *,
    client: httpx.Client,
    outreach_url: str,
    analyses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outreach_results = []
    for analysis in analyses:
        response = client.post(
            outreach_url,
            json={
                "lead": analysis["lead"],
                "analysis": analysis,
            },
        )
        response.raise_for_status()
        outreach_results.append(response.json())
    return outreach_results


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test /api/leads/analyze, then generate outreach from the scored leads."
        ),
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/api/leads/analyze",
        help="Analyze endpoint URL.",
    )
    parser.add_argument(
        "--outreach-url",
        default=None,
        help="Outreach endpoint URL. Defaults to the same host as --url.",
    )
    parser.add_argument(
        "--print-payload",
        action="store_true",
        help="Print the sample request payload before sending it.",
    )
    args = parser.parse_args()
    outreach_url = args.outreach_url or _default_outreach_url(args.url)

    if args.print_payload:
        print("Request payload:")
        print(json.dumps(DEFAULT_PAYLOAD, indent=2))
        print()

    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(args.url, json=DEFAULT_PAYLOAD)
            response.raise_for_status()
            analysis_body = response.json()
            outreach_results = _generate_outreach_for_leads(
                client=client,
                outreach_url=outreach_url,
                analyses=analysis_body.get("leads", []),
            )
    except httpx.HTTPError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        if getattr(exc, "response", None) is not None:
            print(exc.response.text, file=sys.stderr)
        raise SystemExit(1) from exc

    _print_score_summary(analysis_body, outreach_results)


if __name__ == "__main__":
    main()
