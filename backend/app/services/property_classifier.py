import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.models import LeadInput, MicroSignalClassification, SourceSnippet
from app.services.company_classifier import build_evidence_packet

logger = logging.getLogger(__name__)

SIGNALS = ("property_type", "property_scale", "leasing_activity")
ALLOWED_BUCKETS = {
    "property_type": {
        "Multifamily",
        "Residential",
        "Single-Family Rental",
        "Student Housing",
        "Senior Living",
        "Mixed Use",
        "Commercial",
        "Non-Residential",
        "None",
        "Unknown",
    },
    "property_scale": {"Large", "Medium", "Small", "Single Property", "None", "Unknown"},
    "leasing_activity": {"Active", "Moderate", "None", "Unknown"},
}


async def classify_property_signals(
    *,
    lead: LeadInput,
    search_snippets: list[SourceSnippet],
) -> tuple[dict[str, MicroSignalClassification], str | None]:
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "OpenAI property classification skipped because OPENAI_API_KEY is not configured."

    evidence = build_evidence_packet(
        website_title=None,
        website_description=None,
        website_snippet=None,
        search_snippets=search_snippets,
    )
    if not evidence:
        return {}, "OpenAI property classification skipped because no property evidence was available."

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
                    f"OpenAI property classification used partial results; invalid signals: {', '.join(errors)}."
                    if errors
                    else None
                )
                return classifications, message
            if errors:
                raise ValueError(f"No valid property classifications: {', '.join(errors)}")
        except (httpx.HTTPError, ValueError, ValidationError, KeyError, TypeError) as exc:
            logger.warning("OpenAI property classifier failed on attempt %s: %s", attempt + 1, exc)

    return {}, "OpenAI property classification failed validation; using deterministic fallback."


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
                        "name": "property_fit_classification",
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
                raise ValueError(f"unsupported bucket {classification.interpreted_bucket}")
            if classification.evidence_source not in evidence:
                raise ValueError(f"unsupported evidence source {classification.evidence_source}")
            if not _is_source_backed(classification, evidence[classification.evidence_source]):
                raise ValueError("not source-backed")
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

    synonyms = {
        "property_type": {
            "Apartment": "Multifamily",
            "Apartments": "Multifamily",
            "Multifamily Residential": "Multifamily",
            "Single Family": "Single-Family Rental",
            "SFR": "Single-Family Rental",
            "Commercial Real Estate": "Commercial",
        },
        "property_scale": {
            "Very Large": "Large",
            "High": "Large",
            "Moderate": "Medium",
            "Low": "Small",
            "Single": "Single Property",
        },
        "leasing_activity": {
            "High": "Active",
            "Strong": "Active",
            "Some": "Moderate",
            "Low": "Moderate",
            "No": "None",
        },
    }
    normalized["interpreted_bucket"] = synonyms.get(signal, {}).get(bucket, bucket)
    return normalized


def _is_source_backed(classification: MicroSignalClassification, source_text: str) -> bool:
    if classification.interpreted_bucket == "Unknown":
        return bool(classification.raw_evidence.strip())
    raw = classification.raw_evidence.strip()
    parsed = classification.parsed_value.strip()
    if not raw or not parsed:
        return False
    source_lower = source_text.lower()
    return (
        raw.lower() in source_lower
        or parsed.lower() in source_lower
        or _shares_meaningful_token(parsed, source_lower)
    )


def _shares_meaningful_token(parsed: str, source_lower: str) -> bool:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]+", parsed.lower())
        if len(token) >= 5
    ]
    return any(token in source_lower for token in tokens)


def _system_prompt() -> str:
    return (
        "You classify bounded search-result evidence for a single submitted property. "
        "Do not browse or infer beyond the provided evidence. Return JSON only. "
        "For each signal, cite one evidence source exactly as provided. If the evidence "
        "does not clearly support a bucket, return interpreted_bucket='Unknown'. "
        "Do not calculate scores. Preserve explicit unit, apartment, home, bedroom, or "
        "community counts in parsed_value whenever they appear. Only use these exact buckets. "
        "property_type buckets: Multifamily, Residential, Single-Family Rental, Student Housing, "
        "Senior Living, Mixed Use, Commercial, Non-Residential, None, Unknown. "
        "property_scale buckets: Large, Medium, Small, Single Property, None, Unknown. "
        "leasing_activity buckets: Active, Moderate, None, Unknown. "
        "Property type should describe the submitted property, not the management company. "
        "Use Multifamily for apartments or apartment communities, Student Housing for student "
        "apartments, Senior Living for senior housing, Commercial or Non-Residential for office, "
        "retail, industrial, warehouse, self-storage, medical office, or other non-residential assets. "
        "Use Active leasing for source-backed availability, now-leasing, apartments for rent, "
        "floor plans with availability, schedule-a-tour, or leasing-office evidence. Use Moderate "
        "for weaker rental or floor-plan evidence. Use Unknown when the search result is unclear."
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
