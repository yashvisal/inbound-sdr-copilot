"""Shared storage for analysis runs, backed by Upstash Redis over REST.

The hosted demo shows every visitor the same dashboard: curated sample runs plus
whatever other visitors have analyzed live. That needs server-side state, and
Upstash's REST API is the cheapest way to get it from a Vercel serverless
function (plain HTTPS, no driver, no connection pooling).

Every function here degrades to a no-op when Upstash is not configured, so local
development and the test suite run without any external service.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from app.config import get_settings
from app.models import LeadAnalysis, LeadInput

logger = logging.getLogger(__name__)

RunSource = Literal["sample", "community"]

INDEX_KEY = "leads:index"
RECORD_PREFIX = "lead:"
MONTHLY_RUN_PREFIX = "runs:community:"
RATE_LIMIT_PREFIX = "ratelimit:"

# Slightly longer than the longest month so a counter always outlives its period
# but never lingers into the next one's turn.
MONTHLY_TTL_SECONDS = 40 * 24 * 60 * 60
DAILY_TTL_SECONDS = 24 * 60 * 60

_REQUEST_TIMEOUT = 8


def build_run_id(lead: LeadInput) -> str:
    """Mirror of the frontend's getAnalysisId so ids match across the stack."""

    slug = re.sub(r"[^a-z0-9]+", "-", f"{lead.email}-{lead.address}".lower())
    return slug.strip("-")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_key(moment: datetime | None = None) -> str:
    return f"{MONTHLY_RUN_PREFIX}{(moment or _now()):%Y-%m}"


def _day_key(ip: str, moment: datetime | None = None) -> str:
    return f"{RATE_LIMIT_PREFIX}{ip}:{(moment or _now()):%Y-%m-%d}"


def month_period_end(moment: datetime | None = None) -> datetime:
    """First instant of the next month, when the global budget resets."""

    current = moment or _now()
    if current.month == 12:
        return current.replace(
            year=current.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return current.replace(
        month=current.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
    )


async def _command(*args: Any) -> Any:
    """Run one Redis command through the Upstash REST endpoint."""

    settings = get_settings()
    if not settings.run_store_enabled:
        return None

    url = settings.upstash_redis_rest_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
                json=[str(arg) for arg in args],
            )
            response.raise_for_status()
            return response.json().get("result")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Upstash command %s failed: %s", args[0] if args else "?", exc)
        return None


async def _pipeline(commands: list[list[Any]]) -> list[Any]:
    """Run several commands in one round trip."""

    settings = get_settings()
    if not settings.run_store_enabled or not commands:
        return []

    url = f"{settings.upstash_redis_rest_url.rstrip('/')}/pipeline"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
                json=[[str(arg) for arg in command] for command in commands],
            )
            response.raise_for_status()
            return [entry.get("result") for entry in response.json()]
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("Upstash pipeline failed: %s", exc)
        return []


def _record_envelope(
    analysis: LeadAnalysis,
    *,
    source: RunSource,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": build_run_id(analysis.lead),
        "source": source,
        "created_at": created_at or _now().isoformat(),
        "analysis": analysis.model_dump(mode="json"),
    }


async def save_run(analysis: LeadAnalysis, *, source: RunSource = "community") -> None:
    """Persist one analysis and index it by recency."""

    settings = get_settings()
    if not settings.run_store_enabled:
        return

    run_id = build_run_id(analysis.lead)
    envelope = _record_envelope(analysis, source=source)
    # Samples sort below every community run so fresh activity surfaces first
    # while remaining pinned in the index (they are never trimmed).
    score = 0 if source == "sample" else int(_now().timestamp())

    await _pipeline(
        [
            ["SET", f"{RECORD_PREFIX}{run_id}", json.dumps(envelope)],
            ["ZADD", INDEX_KEY, score, run_id],
        ]
    )
    await _trim_community_runs()


async def update_run_outreach(
    lead: LeadInput,
    *,
    sales_insights: list[str],
    outreach_email: str,
) -> None:
    """Patch a stored record after outreach is generated for it."""

    settings = get_settings()
    if not settings.run_store_enabled:
        return

    run_id = build_run_id(lead)
    raw = await _command("GET", f"{RECORD_PREFIX}{run_id}")
    if not raw:
        return
    try:
        envelope = json.loads(raw)
        envelope["analysis"]["sales_insights"] = sales_insights
        envelope["analysis"]["outreach_email"] = outreach_email
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Could not patch stored run %s: %s", run_id, exc)
        return

    await _command("SET", f"{RECORD_PREFIX}{run_id}", json.dumps(envelope))


async def list_runs(limit: int = 200) -> list[dict[str, Any]]:
    """Return stored runs, newest community runs first."""

    settings = get_settings()
    if not settings.run_store_enabled:
        return []

    ids = await _command("ZRANGE", INDEX_KEY, 0, limit - 1, "REV")
    if not ids:
        return []

    raw_records = await _pipeline([["GET", f"{RECORD_PREFIX}{run_id}"] for run_id in ids])
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return records


async def _trim_community_runs() -> None:
    """Drop the oldest community runs beyond the display limit.

    Sample runs carry score 0, so trimming from the low end would evict them
    first. They are filtered out of the deletion set explicitly instead.
    """

    settings = get_settings()
    limit = settings.community_run_limit
    if limit <= 0:
        return

    # Everything with a real timestamp score is a community run.
    community_ids = await _command("ZRANGEBYSCORE", INDEX_KEY, 1, "+inf")
    if not community_ids or len(community_ids) <= limit:
        return

    stale = community_ids[: len(community_ids) - limit]
    await _pipeline(
        [["ZREM", INDEX_KEY, run_id] for run_id in stale]
        + [["DEL", f"{RECORD_PREFIX}{run_id}"] for run_id in stale]
    )


async def get_monthly_usage() -> tuple[int, int]:
    """Return (runs_used, runs_limit) for the current month."""

    settings = get_settings()
    limit = settings.max_runs_per_month
    if not settings.run_store_enabled:
        return 0, limit

    used = await _command("GET", _month_key())
    try:
        return int(used or 0), limit
    except (TypeError, ValueError):
        return 0, limit


async def reserve_run_slots(*, ip: str, count: int) -> str | None:
    """Reserve capacity for ``count`` runs.

    Returns ``None`` when the run may proceed, otherwise a reason string:
    ``"quota_exhausted"`` (monthly budget spent) or ``"rate_limited"`` (this
    visitor's daily allowance spent). Counters are rolled back when a check
    fails so a rejected request never consumes budget.
    """

    settings = get_settings()
    if not settings.run_store_enabled or count <= 0:
        return None

    month_key = _month_key()
    monthly_total = await _command("INCRBY", month_key, count)
    if monthly_total is None:
        # Storage is unreachable; fail open rather than blocking the demo.
        return None
    await _command("EXPIRE", month_key, MONTHLY_TTL_SECONDS, "NX")

    if settings.max_runs_per_month >= 0 and int(monthly_total) > settings.max_runs_per_month:
        await _command("DECRBY", month_key, count)
        return "quota_exhausted"

    day_key = _day_key(ip)
    daily_total = await _command("INCRBY", day_key, count)
    if daily_total is None:
        return None
    await _command("EXPIRE", day_key, DAILY_TTL_SECONDS, "NX")

    if settings.max_runs_per_ip_per_day >= 0 and int(daily_total) > settings.max_runs_per_ip_per_day:
        await _pipeline([["DECRBY", day_key, count], ["DECRBY", month_key, count]])
        return "rate_limited"

    return None


def seconds_until_tomorrow(moment: datetime | None = None) -> int:
    current = moment or _now()
    tomorrow = (current + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - current).total_seconds()))
