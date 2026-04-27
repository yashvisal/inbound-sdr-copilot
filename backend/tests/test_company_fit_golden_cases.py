import pytest

from app.models import LeadInput, MarketMetrics
from app.scoring import score_lead
from app.services.company import extract_company_signals


def _score_case(case: dict):
    lead = LeadInput(
        name="Golden Contact",
        email=case.get("email", "contact@examplepm.com"),
        company=case.get("company", "Golden Property Co"),
        address=case.get("address", "123 Main St"),
        city="Austin",
        state="TX",
        country="US",
    )
    enrichment = extract_company_signals(
        lead=lead,
        domain=case.get("domain"),
        website_description=case["input"],
        website_snippet="",
    )
    return score_lead(
        lead=lead,
        market_metrics=MarketMetrics(),
        company_enrichment=enrichment,
        timing_signals=[],
    )


GOLDEN_CASES = [
    {
        "id": "large_multifamily_operator_ideal_icp",
        "input": (
            "Greystar manages over 900,000 apartment units across global markets "
            "with centralized leasing, resident services, and maintenance operations."
        ),
        "expected": {
            "leasing_volume": "Very High",
            "operational_complexity": "Very High",
            "product_fit": "Very Strong",
            "company_fit_range": (35, 39),
        },
    },
    {
        "id": "large_operator",
        "input": (
            "Asset Living manages more than 300,000 units across multifamily communities "
            "nationwide with leasing and resident communication teams."
        ),
        "expected": {
            "leasing_volume": "Very High",
            "operational_complexity": "Very High",
            "product_fit": "Very Strong",
            "company_fit_range": (34, 39),
        },
    },
    {
        "id": "mid_large_operator",
        "input": (
            "RPM Living operates over 200,000 units across 900 apartment communities "
            "with leasing teams and resident engagement workflows."
        ),
        "expected": {
            "leasing_volume": "High",
            "operational_complexity": "High",
            "product_fit": "Strong",
            "company_fit_range": (30, 36),
        },
    },
    {
        "id": "mid_market_operator",
        "input": (
            "Property management firm managing 8,000 apartment units across multiple "
            "communities with leasing and maintenance services."
        ),
        "expected": {
            "leasing_volume": "Low",
            "operational_complexity": "Low",
            "product_fit": "Moderate",
            "company_fit_range": (12, 20),
        },
        "live_expected": {
            "leasing_volume": "High",
            "operational_complexity": "High",
            "product_fit": "Strong",
            "company_fit_range": (28, 35),
        },
    },
    {
        "id": "small_operator",
        "input": "Local property manager handling 3 apartment buildings and tenant leasing.",
        "expected": {
            "leasing_volume": "Low",
            "operational_complexity": "Low",
            "product_fit": "Moderate",
            "company_fit_range": (12, 20),
        },
    },
    {
        "id": "single_family_rental_operator_partial_icp",
        "input": "Manages 20,000 single-family rental homes across multiple U.S. markets.",
        "expected": {
            "leasing_volume": "Low",
            "operational_complexity": "Low",
            "product_fit": "Moderate",
            "company_fit_range": (12, 20),
        },
        "live_expected": {
            "leasing_volume": "Medium",
            "operational_complexity": "Medium",
            "product_fit": "Moderate",
            "company_fit_range": (18, 25),
        },
    },
    {
        "id": "commercial_real_estate_false_positive",
        "input": "Commercial real estate firm focused on office leasing and brokerage services.",
        "expected": {
            "leasing_volume": "Medium",
            "operational_complexity": "Medium",
            "product_fit": "Weak",
            "company_fit_range": (5, 15),
        },
        "live_expected": {
            "leasing_volume": "Unknown",
            "operational_complexity": "Unknown",
            "product_fit": "None",
            "company_fit_range": (0, 5),
        },
    },
    {
        "id": "developer_operator_valid_icp",
        "input": "Develops and operates multifamily apartment communities across major U.S. markets.",
        "expected": {
            "leasing_volume": "High",
            "operational_complexity": "High",
            "product_fit": "Strong",
            "company_fit_range": (28, 35),
        },
        "live_expected": {
            "leasing_volume": "Low",
            "operational_complexity": ["None", "Low"],
            "product_fit": "Moderate",
            "company_fit_range": (8, 18),
        },
    },
    {
        "id": "student_housing_high_turnover",
        "input": "Manages student housing communities with seasonal leasing cycles and high tenant turnover.",
        "expected": {
            "leasing_volume": "High",
            "operational_complexity": "High",
            "product_fit": "Strong",
            "company_fit_range": (28, 35),
        },
        "live_expected": {
            "leasing_volume": ["Low", "High"],
            "operational_complexity": ["Low", "High"],
            "product_fit": ["Moderate", "Strong"],
            "company_fit_range": (12, 35),
        },
    },
    {
        "id": "non_real_estate_hard_fail",
        "input": "SaaS company providing healthcare CRM software with no property or leasing operations.",
        "expected": {
            "leasing_volume": "None",
            "operational_complexity": "None",
            "product_fit": "None",
            "company_fit_range": (0, 5),
        },
        "live_expected": {
            "leasing_volume": "Unknown",
            "operational_complexity": "Unknown",
            "product_fit": "None",
            "company_fit_range": (0, 5),
        },
    },
]


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[case["id"] for case in GOLDEN_CASES])
def test_company_fit_golden_cases_classify_expected_buckets(case: dict) -> None:
    score = _score_case(case)
    expected = case["expected"]
    min_company, max_company = expected["company_fit_range"]

    assert min_company <= score.company_fit.score <= max_company
    assert score.company_fit_breakdown is not None

    audit = score.company_fit_breakdown.extraction_audit
    assert audit["leasing_volume"].interpreted_bucket == expected["leasing_volume"]
    assert audit["operational_complexity"].interpreted_bucket == expected["operational_complexity"]
    assert audit["product_fit"].interpreted_bucket == expected["product_fit"]
