import argparse
import asyncio
import csv
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import CompanyEnrichment, LeadInput, MarketMetrics, SourceSnippet
from app.scoring import score_lead
from app.services.company import enrich_company, extract_company_signals


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_CASES_PATH = ROOT / "tests" / "test_company_fit_golden_cases.py"
DEFAULT_OUTPUT_DIR = ROOT / "reports"
LIVE_COMPANIES = {
    "large_multifamily_operator_ideal_icp": "Greystar",
    "large_operator": "Asset Living",
    "mid_large_operator": "RPM Living",
    "mid_market_operator": "Willow Bridge Property Company",
    "small_operator": "Morrison Apartments",
    "single_family_rental_operator_partial_icp": "Invitation Homes",
    "commercial_real_estate_false_positive": "CBRE",
    "developer_operator_valid_icp": "Mill Creek Residential",
    "student_housing_high_turnover": "American Campus Communities",
    "non_real_estate_hard_fail": "Salesforce",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Company Fit golden-case scoring runs.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use live Serper, website enrichment, and OpenAI classification instead of offline inputs.",
    )
    args = parser.parse_args()
    asyncio.run(_main(live=args.live))


async def _main(*, live: bool) -> None:
    output_dir = DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_golden_cases()
    results = []
    for case in cases:
        results.append(await _run_case(case, live=live))

    mode = "live" if live else "offline"
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "source": str(GOLDEN_CASES_PATH.relative_to(ROOT)),
        "case_count": len(cases),
        "cases": results,
    }
    report["pass_count"] = sum(1 for case in report["cases"] if case["validation"]["passed"])
    report["fail_count"] = report["case_count"] - report["pass_count"]

    suffix = "_live" if live else ""
    json_path = output_dir / f"company_fit_golden_cases_report{suffix}.json"
    csv_path = output_dir / f"company_fit_golden_cases_summary{suffix}.csv"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_csv(csv_path, report["cases"])

    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    print(f"{report['pass_count']}/{report['case_count']} golden cases passed expectations")


def _load_golden_cases() -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("company_fit_golden_cases", GOLDEN_CASES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load golden cases from {GOLDEN_CASES_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.GOLDEN_CASES)


async def _run_case(case: dict[str, Any], *, live: bool) -> dict[str, Any]:
    company = _company_for_case(case, live=live)
    lead = LeadInput(
        name="Golden Contact",
        email=case.get("email", "contact@examplepm.com"),
        company=company,
        address=case.get("address", "123 Main St"),
        city="Austin",
        state="TX",
        country="US",
    )

    evidence: list[SourceSnippet] = []
    missing_data: list[str] = []
    if live:
        company_result = await enrich_company(lead)
        enrichment = company_result.enrichment
        evidence = company_result.evidence
        missing_data = company_result.missing_data
    else:
        enrichment = extract_company_signals(
            lead=lead,
            domain=case.get("domain"),
            website_description=case["input"],
            website_snippet="",
        )

    score = score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=enrichment,
    )

    breakdown = score.company_fit_breakdown
    audit = breakdown.extraction_audit if breakdown else {}
    expected = _expected_for_case(case, live=live)
    validation = _validate_case(expected, score.company_fit.score, audit)

    return {
        "id": case["id"],
        "mode": "live" if live else "offline",
        "input": case["input"],
        "lead": lead.model_dump(),
        "expected": expected,
        "actual": {
            "final_score": score.final_score,
            "priority": score.priority,
            "confidence": score.confidence,
            "company_fit_label": score.company_fit_label,
            "company_fit": score.company_fit.model_dump(),
            "property_fit": score.property_fit.model_dump(),
            "property_fit_breakdown": (
                score.property_fit_breakdown.model_dump()
                if score.property_fit_breakdown
                else None
            ),
            "score_breakdown": breakdown.score_breakdown if breakdown else {},
            "extraction_audit": {
                signal: signal_audit.model_dump()
                for signal, signal_audit in audit.items()
            },
        },
        "company_enrichment": enrichment.model_dump(),
        "evidence": [item.model_dump() for item in evidence],
        "missing_data": missing_data,
        "extracted_signals": {
            "business_type": enrichment.business_type_signals,
            "leasing_volume": enrichment.leasing_volume_signals,
            "operational_complexity": enrichment.operational_complexity_signals,
            "product_fit": enrichment.product_fit_signals,
            "property": enrichment.property_signals,
            "negative_property": enrichment.negative_property_signals,
            "property_classifications": {
                signal: classification.model_dump()
                for signal, classification in enrichment.property_classifications.items()
            },
            "geographic_footprint": enrichment.geographic_footprint_signals,
        },
        "validation": validation,
    }


def _company_for_case(case: dict[str, Any], *, live: bool) -> str:
    if live:
        return case.get("live_company") or case.get("company") or LIVE_COMPANIES[case["id"]]
    return case.get("company", case["id"].replace("_", " ").title())


def _expected_for_case(case: dict[str, Any], *, live: bool) -> dict[str, Any]:
    if live and "live_expected" in case:
        return case["live_expected"]
    return case["expected"]


def _validate_case(
    expected: dict[str, Any],
    company_fit_score: int,
    audit: dict[str, Any],
) -> dict[str, Any]:
    min_score, max_score = expected["company_fit_range"]
    checks = {
        "company_fit_range": min_score <= company_fit_score <= max_score,
        "leasing_volume": (
            audit.get("leasing_volume")
            and _bucket_matches(
                audit["leasing_volume"].interpreted_bucket,
                expected["leasing_volume"],
            )
        ),
        "operational_complexity": (
            audit.get("operational_complexity")
            and _bucket_matches(
                audit["operational_complexity"].interpreted_bucket,
                expected["operational_complexity"],
            )
        ),
        "product_fit": (
            audit.get("product_fit")
            and _bucket_matches(
                audit["product_fit"].interpreted_bucket,
                expected["product_fit"],
            )
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
    }


def _bucket_matches(actual: str, expected: Any) -> bool:
    if isinstance(expected, list | tuple | set):
        return actual in expected
    return actual == expected


def _write_csv(path: Path, cases: list[dict[str, Any]]) -> None:
    rows = [_csv_row(case) for case in cases]
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _csv_row(case: dict[str, Any]) -> dict[str, Any]:
    actual = case["actual"]
    expected = case["expected"]
    audit = actual["extraction_audit"]
    scores = actual["score_breakdown"]
    min_score, max_score = expected["company_fit_range"]
    return {
        "id": case["id"],
        "passed": case["validation"]["passed"],
        "input": case["input"],
        "company_fit_score": actual["company_fit"]["score"],
        "company_fit_expected_min": min_score,
        "company_fit_expected_max": max_score,
        "company_fit_label": actual["company_fit_label"],
        "final_score": actual["final_score"],
        "priority": actual["priority"],
        "confidence": actual["confidence"],
        "property_fit_score": actual["property_fit"]["score"],
        "leasing_volume_bucket": audit["leasing_volume"]["interpreted_bucket"],
        "leasing_volume_expected": expected["leasing_volume"],
        "leasing_volume_score": scores["leasing_volume"],
        "leasing_volume_evidence": audit["leasing_volume"]["raw_evidence"],
        "operational_complexity_bucket": audit["operational_complexity"]["interpreted_bucket"],
        "operational_complexity_expected": expected["operational_complexity"],
        "operational_complexity_score": scores["operational_complexity"],
        "operational_complexity_evidence": audit["operational_complexity"]["raw_evidence"],
        "product_fit_bucket": audit["product_fit"]["interpreted_bucket"],
        "product_fit_expected": expected["product_fit"],
        "product_fit_score": scores["product_fit"],
        "product_fit_evidence": audit["product_fit"]["raw_evidence"],
        "company_fit_reasons": " | ".join(actual["company_fit"]["reasons"]),
        "property_fit_reasons": " | ".join(actual["property_fit"]["reasons"]),
    }


if __name__ == "__main__":
    main()
