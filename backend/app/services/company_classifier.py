import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.models import LeadInput, MicroSignalClassification, SourceSnippet

logger = logging.getLogger(__name__)

SIGNALS = ("leasing_volume", "operational_complexity", "product_fit")
ALLOWED_BUCKETS = {
    "leasing_volume": {"Very High", "High", "Medium", "Low", "None", "Unknown"},
    "operational_complexity": {"Very High", "High", "Medium", "Low", "None", "Unknown"},
    "product_fit": {"Very Strong", "Strong", "Moderate", "Weak", "None", "Unknown"},
}


async def classify_company_signals(
    *,
    lead: LeadInput,
    website_title: str | None,
    website_description: str | None,
    website_snippet: str | None,
    search_snippets: list[SourceSnippet],
) -> tuple[dict[str, MicroSignalClassification], str | None]:
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "OpenAI classification skipped because OPENAI_API_KEY is not configured."

    evidence = build_evidence_packet(
        website_title=website_title,
        website_description=website_description,
        website_snippet=website_snippet,
        search_snippets=search_snippets,
    )
    if not evidence:
        return {}, "OpenAI classification skipped because no source-backed evidence was available."

    for attempt in range(2):
        try:
            payload = await _call_openai_classifier(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                lead=lead,
                evidence=evidence,
            )
            classifications, errors = _parse_classifier_payload(payload, evidence)
            if classifications:
                message = (
                    f"OpenAI classification used partial results; invalid signals: {', '.join(errors)}."
                    if errors
                    else None
                )
                return classifications, message
            if errors:
                raise ValueError(f"No valid signal classifications: {', '.join(errors)}")
        except (httpx.HTTPError, ValueError, ValidationError, KeyError, TypeError) as exc:
            logger.warning("OpenAI company classifier failed on attempt %s: %s", attempt + 1, exc)

    return {}, "OpenAI classification failed validation; using deterministic rule fallback."


def build_evidence_packet(
    *,
    website_title: str | None,
    website_description: str | None,
    website_snippet: str | None,
    search_snippets: list[SourceSnippet],
) -> dict[str, str]:
    candidates: list[tuple[str, str]] = []
    website_text = _clean_join([website_title, website_description, website_snippet])
    if website_text:
        candidates.append(("website_snippet", website_text))

    for index, snippet in enumerate(search_snippets):
        text = _clean_join([snippet.title, snippet.snippet, snippet.url])
        if text:
            candidates.append((f"search_snippets[{index}]", text))

    seen = set()
    evidence: dict[str, str] = {}
    for source_id, text in candidates:
        fingerprint = text.lower()[:220]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        evidence[source_id] = _trim(text, 400)
        if len(evidence) >= 5:
            break
    return evidence


async def _call_openai_classifier(
    *,
    api_key: str,
    model: str,
    lead: LeadInput,
    evidence: dict[str, str],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _system_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "company": lead.company,
                                "property_address": lead.address,
                                "city": lead.city,
                                "state": lead.state,
                                "evidence": evidence,
                            },
                            indent=2,
                        ),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "company_micro_fit_classification",
                        "strict": True,
                        "schema": _json_schema(),
                    },
                },
            },
        )
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _parse_classifier_payload(
    payload: dict[str, Any],
    evidence: dict[str, str],
) -> tuple[dict[str, MicroSignalClassification], list[str]]:
    classifications: dict[str, MicroSignalClassification] = {}
    errors: list[str] = []
    for signal in SIGNALS:
        try:
            raw = _normalize_signal_payload(signal, payload[signal])
            classification = MicroSignalClassification.model_validate(raw)
            if classification.interpreted_bucket not in ALLOWED_BUCKETS[signal]:
                raise ValueError(
                    f"unsupported bucket {classification.interpreted_bucket}"
                )
            if classification.evidence_source not in evidence and not _allows_aggregate_evidence(
                signal,
                classification,
                evidence,
            ):
                raise ValueError(
                    f"unsupported evidence source {classification.evidence_source}"
                )
            source_text = (
                evidence[classification.evidence_source]
                if classification.evidence_source in evidence
                else " ".join(evidence.values())
            )
            if not _is_source_backed(signal, classification, source_text):
                raise ValueError("not source-backed")
            classification = _adjust_confidence_from_evidence(signal, classification, evidence)
            classifications[signal] = classification
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{signal} ({exc})")
    return classifications, errors


def _normalize_signal_payload(signal: str, raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    bucket = normalized.get("interpreted_bucket")
    if not isinstance(bucket, str):
        return normalized

    bucket = bucket.strip()
    if bucket in ALLOWED_BUCKETS[signal]:
        normalized["interpreted_bucket"] = bucket
        return normalized

    if signal == "product_fit":
        product_synonyms = {
            "Very Large": "Very Strong",
            "Huge": "Very Strong",
            "Massive": "Very Strong",
            "Very High": "Very Strong",
            "Large": "Strong",
            "High": "Strong",
            "Moderate": "Moderate",
            "Small": "Weak",
            "Low": "Weak",
            "very large": "Very Strong",
            "huge": "Very Strong",
            "massive": "Very Strong",
            "Very high": "Very Strong",
            "large": "Strong",
            "high": "Strong",
            "small": "Weak",
            "low": "Weak",
        }
        normalized["interpreted_bucket"] = product_synonyms.get(bucket, bucket)
    else:
        signal_synonyms = {
            "Very Large": "Very High",
            "Huge": "Very High",
            "Massive": "Very High",
            "Very Strong": "Very High",
            "Large": "High",
            "Strong": "High",
            "Moderate": "Medium",
            "Small": "Low",
            "Weak": "Low",
            "very large": "Very High",
            "huge": "Very High",
            "massive": "Very High",
            "large": "High",
            "very strong": "Very High",
            "strong": "High",
            "moderate": "Medium",
            "small": "Low",
            "weak": "Low",
        }
        normalized["interpreted_bucket"] = signal_synonyms.get(bucket, bucket)
    return normalized


def _allows_aggregate_evidence(
    signal: str,
    classification: MicroSignalClassification,
    evidence: dict[str, str],
) -> bool:
    if signal != "leasing_volume":
        return False
    if classification.evidence_source not in {"multiple", "multiple_sources", "aggregated_evidence"}:
        return False
    return _has_numeric_scale_evidence(classification, evidence)


def _is_source_backed(
    signal: str,
    classification: MicroSignalClassification,
    source_text: str,
) -> bool:
    if classification.interpreted_bucket == "Unknown":
        return bool(classification.raw_evidence.strip())
    raw = classification.raw_evidence.strip()
    parsed = classification.parsed_value.strip()
    if not raw or not parsed:
        return False
    source_lower = source_text.lower()
    if raw.lower() in source_lower or parsed.lower() in source_lower:
        return True
    if signal == "leasing_volume":
        return bool(_extract_scale_numbers(parsed)) and any(
            _source_contains_number(source_lower, number)
            for number in _extract_scale_numbers(parsed)
        )
    return False


def _adjust_confidence_from_evidence(
    signal: str,
    classification: MicroSignalClassification,
    evidence: dict[str, str],
) -> MicroSignalClassification:
    if signal != "leasing_volume":
        return classification
    if _numeric_scale_source_count(classification, evidence) >= 2:
        classification.confidence = "High"
    return classification


def _has_numeric_scale_evidence(
    classification: MicroSignalClassification,
    evidence: dict[str, str],
) -> bool:
    parsed_numbers = _extract_scale_numbers(classification.parsed_value)
    if not parsed_numbers:
        return False
    combined = " ".join(evidence.values()).lower()
    return any(_source_contains_number(combined, number) for number in parsed_numbers)


def _numeric_scale_source_count(
    classification: MicroSignalClassification,
    evidence: dict[str, str],
) -> int:
    parsed_numbers = _extract_scale_numbers(classification.parsed_value)
    if not parsed_numbers:
        return 0
    count = 0
    for text in evidence.values():
        source_lower = text.lower()
        if any(_source_contains_number(source_lower, number) for number in parsed_numbers):
            count += 1
    return count


def _extract_scale_numbers(value: str) -> list[str]:
    matches = re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{5,}\b", value)
    numbers: list[str] = []
    for match in matches:
        numbers.append(match)
        numbers.append(match.replace(",", ""))
    return numbers


def _source_contains_number(source: str, number: str) -> bool:
    return number in source or number.replace(",", "") in source.replace(",", "")


def _system_prompt() -> str:
    return (
        "You classify bounded source evidence for a property-management sales lead. "
        "Do not browse or infer beyond the provided evidence. Return JSON only. "
        "For each signal, cite one evidence source exactly as provided. If the evidence "
        "does not clearly support a bucket, return interpreted_bucket='Unknown'. "
        "Do not calculate scores. Preserve explicit unit/property/home counts in parsed_value "
        "whenever they appear; the application will deterministically calibrate leasing-volume "
        "magnitude from those extracted values. Only use these exact buckets. "
        "leasing_volume and operational_complexity buckets: Very High, High, Medium, Low, None, Unknown. "
        "product_fit buckets: Very Strong, Strong, Moderate, Weak, None, Unknown. "
        "Do not output synonyms. If you would say Very Large, Huge, or Massive, use Very High "
        "for leasing_volume or operational_complexity and Very Strong for product_fit. "
        "If you would say Large, use High or Strong as appropriate. "
        "For leasing_volume only, you may use evidence_source='multiple_sources' when numeric "
        "scale evidence is repeated across snippets; otherwise cite one exact source. "
        "For operational_complexity, very large residential portfolios may be classified as High "
        "when scale evidence strongly implies leasing, resident, or property operations even if a "
        "workflow phrase is not explicit. Evaluate product_fit relative to EliseAI's ICP: "
        "residential property management companies, especially multifamily operators, with large "
        "portfolios across multiple properties or markets. Product fit is Very Strong or Strong "
        "when the company clearly matches this ICP, even if the source does not explicitly mention "
        "leasing automation or resident communication workflows. Product fit is Moderate for partial "
        "residential operators such as smaller or single-family rental operators, Weak for commercial-only "
        "real estate, and None for non-real-estate companies."
    )


def _json_schema() -> dict[str, Any]:
    signal_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "raw_evidence",
            "evidence_source",
            "parsed_value",
            "interpreted_bucket",
            "confidence",
            "classifier",
        ],
        "properties": {
            "raw_evidence": {"type": "string"},
            "evidence_source": {"type": "string"},
            "parsed_value": {"type": "string"},
            "interpreted_bucket": {"type": "string"},
            "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "classifier": {"type": "string", "enum": ["openai_classifier"]},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(SIGNALS),
        "properties": {signal: signal_schema for signal in SIGNALS},
    }


def _clean_join(values: list[str | None]) -> str:
    return " ".join(value.strip() for value in values if value and value.strip())


def _trim(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3].rstrip()}..."
