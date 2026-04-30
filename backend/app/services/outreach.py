import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.models import LeadAnalysis, LeadInput, OutreachGenerationResponse
from app.outreach import build_outreach_email, build_sales_insights

logger = logging.getLogger(__name__)


async def generate_outreach(
    lead: LeadInput,
    analysis: LeadAnalysis,
) -> OutreachGenerationResponse:
    settings = get_settings()
    fallback = _build_fallback_outreach(lead, analysis)
    if not settings.openai_api_key:
        return fallback

    for attempt in range(2):
        try:
            payload = await _call_openai_outreach(
                api_key=settings.openai_api_key,
                model=settings.openai_outreach_model,
                lead=lead,
                analysis=analysis,
            )
            return _parse_outreach_payload(payload, fallback)
        except (httpx.HTTPError, ValueError, ValidationError, KeyError, TypeError) as exc:
            logger.warning("OpenAI outreach generation failed on attempt %s: %s", attempt + 1, exc)

    return fallback


async def _call_openai_outreach(
    *,
    api_key: str,
    model: str,
    lead: LeadInput,
    analysis: LeadAnalysis,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "reasoning": {"effort": "low"},
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "input": [
                    {"role": "developer", "content": _developer_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            _build_context(lead, analysis),
                            indent=2,
                        ),
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "outreach_generation",
                        "strict": True,
                        "schema": _json_schema(),
                    }
                },
            },
        )
        response.raise_for_status()
    return json.loads(_extract_output_text(response.json()))


def _parse_outreach_payload(
    payload: dict[str, Any],
    fallback: OutreachGenerationResponse,
) -> OutreachGenerationResponse:
    result = OutreachGenerationResponse.model_validate(payload)
    insights = _clean_items(result.sales_insights)
    if len(insights) < 4:
        insights = _clean_items([*insights, *fallback.sales_insights])
    insights = insights[:5]
    if len(insights) < 4:
        raise ValueError("outreach response did not include enough insights")

    email = result.personalized_email.strip()
    if not email:
        email = fallback.personalized_email

    return OutreachGenerationResponse(
        sales_insights=insights,
        personalized_email=email,
    )


def _build_context(lead: LeadInput, analysis: LeadAnalysis) -> dict[str, Any]:
    score = analysis.score
    company = analysis.company_enrichment
    return {
        "lead": {
            "name": lead.name,
            "company": lead.company,
            "email": str(lead.email),
            "property_address": lead.address,
            "city": lead.city,
            "state": lead.state,
            "country": lead.country,
        },
        "score": {
            "final_score": score.final_score,
            "priority": score.priority,
            "confidence": score.confidence,
            "company_fit_label": score.company_fit_label,
            "market_reasons": score.market_fit.reasons[:3],
            "company_reasons": score.company_fit.reasons[:3],
            "property_reasons": score.property_fit.reasons[:3],
        },
        "property_context": {
            "osm_property_class": company.osm_property_class if company else None,
            "osm_property_type": company.osm_property_type if company else None,
            "osm_display_name": company.osm_display_name if company else None,
            "leasing_volume_signals": company.leasing_volume_signals[:5] if company else [],
            "operational_complexity_signals": (
                company.operational_complexity_signals[:5] if company else []
            ),
            "product_fit_signals": company.product_fit_signals[:5] if company else [],
            "property_signals": company.property_signals[:5] if company else [],
        },
        "market_context": analysis.market_metrics.model_dump(exclude_none=True),
        "existing_sales_context": {
            "why_this_lead": analysis.why_this_lead[:3],
            "sales_insights": analysis.sales_insights[:5],
        },
        "evidence_snippets": [
            {
                "source": snippet.source,
                "title": snippet.title,
                "url": snippet.url,
                "snippet": _trim(snippet.snippet, 260),
            }
            for snippet in analysis.evidence[:5]
        ],
    }


def _developer_prompt() -> str:
    return (
        "Generate sales-ready outreach for a GTM engineer from an already-scored "
        "property management lead. Produce only practical insights and a concise "
        "personalized email. Tie the output to leasing volume, operational complexity, "
        "property scale, ROI, or onsite workload. Avoid generic macro statements, "
        "persona inference, raw research, citations, and source lists. Web search is "
        "optional; use it only for light company or property context. If using search, "
        "prefer LinkedIn, the company site, and credible business sources, and avoid "
        "generic listing sites, directories, or irrelevant results."
    )


def _json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sales_insights": {
                "type": "array",
                "minItems": 4,
                "maxItems": 5,
                "items": {"type": "string", "minLength": 1},
            },
            "personalized_email": {"type": "string", "minLength": 1},
        },
        "required": ["sales_insights", "personalized_email"],
    }


def _extract_output_text(body: dict[str, Any]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]

    raise ValueError("OpenAI response did not include output text")


def _build_fallback_outreach(
    lead: LeadInput,
    analysis: LeadAnalysis,
) -> OutreachGenerationResponse:
    insights = _clean_items(
        [
            *build_sales_insights(analysis.score),
            *analysis.why_this_lead,
            *analysis.sales_insights,
            f"{lead.company} is worth prioritizing at a {analysis.score.priority.lower()} priority score.",
            (
                f"{lead.address} gives the outreach a concrete property context "
                "for discussing leasing responsiveness and onsite workload."
            ),
            (
                "The score breakdown creates a direct path to frame ROI around "
                "speed-to-lead and reduced manual follow-up."
            ),
        ]
    )[:5]

    while len(insights) < 4:
        insights.append(
            "Use the existing fit signals to anchor the conversation in leasing workload and operational efficiency."
        )

    return OutreachGenerationResponse(
        sales_insights=insights,
        personalized_email=build_outreach_email(lead, analysis.score),
    )


def _clean_items(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(item.strip().split())
        if not text:
            continue
        fingerprint = text.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        cleaned.append(text)
    return cleaned


def _trim(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."
