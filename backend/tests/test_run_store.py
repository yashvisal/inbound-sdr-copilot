from datetime import datetime, timezone

import pytest

from app.config import Settings, get_settings
from app.models import LeadInput
from app.services import run_store


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _lead() -> LeadInput:
    return LeadInput(
        name="Maya Chen",
        email="maya@harborresidential.com",
        company="Harbor Residential",
        address="The Morrison Apartments, 123 Main St",
        city="Austin",
        state="TX",
        country="US",
    )


def test_run_id_matches_frontend_slug_rules() -> None:
    assert (
        run_store.build_run_id(_lead())
        == "maya-harborresidential-com-the-morrison-apartments-123-main-st"
    )


def test_storage_disabled_without_upstash_credentials() -> None:
    assert Settings(_env_file=None).run_store_enabled is False
    assert (
        Settings(
            _env_file=None,
            UPSTASH_REDIS_REST_URL="https://example.upstash.io",
            UPSTASH_REDIS_REST_TOKEN="token",
        ).run_store_enabled
        is True
    )


@pytest.mark.anyio
async def test_store_operations_are_noops_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(run_store, "get_settings", lambda: Settings(_env_file=None))

    def _fail(*args, **kwargs):
        raise AssertionError("run store must not touch the network when unconfigured")

    monkeypatch.setattr(run_store.httpx, "AsyncClient", _fail)

    # None of these should raise or attempt a network call.
    assert await run_store.list_runs() == []
    assert await run_store.reserve_run_slots(ip="1.2.3.4", count=3) is None
    settings = Settings(_env_file=None)
    assert await run_store.get_monthly_usage() == (0, settings.max_runs_per_month)


class _FakeRedis:
    """Minimal stand-in for the Upstash counters used by reserve_run_slots."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.commands: list[tuple] = []

    async def command(self, *args):
        self.commands.append(args)
        verb = str(args[0]).upper()
        if verb == "INCRBY":
            self.values[args[1]] = self.values.get(args[1], 0) + int(args[2])
            return self.values[args[1]]
        if verb == "DECRBY":
            self.values[args[1]] = self.values.get(args[1], 0) - int(args[2])
            return self.values[args[1]]
        if verb == "GET":
            return self.values.get(args[1])
        return 1

    async def pipeline(self, commands):
        return [await self.command(*command) for command in commands]


@pytest.fixture
def fake_redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        run_store,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            UPSTASH_REDIS_REST_URL="https://example.upstash.io",
            UPSTASH_REDIS_REST_TOKEN="token",
            MAX_RUNS_PER_MONTH=5,
            MAX_RUNS_PER_IP_PER_DAY=3,
        ),
    )
    monkeypatch.setattr(run_store, "_command", fake.command)
    monkeypatch.setattr(run_store, "_pipeline", fake.pipeline)
    return fake


@pytest.mark.anyio
async def test_reserve_allows_runs_within_both_limits(fake_redis) -> None:
    assert await run_store.reserve_run_slots(ip="1.2.3.4", count=2) is None
    assert fake_redis.values[run_store._month_key()] == 2


@pytest.mark.anyio
async def test_reserve_blocks_and_refunds_when_daily_limit_exceeded(fake_redis) -> None:
    assert await run_store.reserve_run_slots(ip="1.2.3.4", count=3) is None
    assert await run_store.reserve_run_slots(ip="1.2.3.4", count=1) == "rate_limited"

    # A rejected request must not consume monthly or daily budget.
    assert fake_redis.values[run_store._month_key()] == 3
    assert fake_redis.values[run_store._day_key("1.2.3.4")] == 3


@pytest.mark.anyio
async def test_reserve_blocks_when_monthly_budget_exhausted(fake_redis) -> None:
    assert await run_store.reserve_run_slots(ip="1.1.1.1", count=3) is None
    assert await run_store.reserve_run_slots(ip="2.2.2.2", count=3) == "quota_exhausted"
    assert fake_redis.values[run_store._month_key()] == 3


@pytest.mark.anyio
async def test_batch_larger_than_monthly_budget_is_rejected_whole(fake_redis) -> None:
    # A CSV upload cannot slip past the cap by arriving as one request.
    assert await run_store.reserve_run_slots(ip="1.2.3.4", count=20) == "quota_exhausted"
    assert fake_redis.values[run_store._month_key()] == 0


def test_month_period_end_rolls_into_january() -> None:
    december = datetime(2026, 12, 14, 9, 30, tzinfo=timezone.utc)
    assert run_store.month_period_end(december) == datetime(
        2027, 1, 1, tzinfo=timezone.utc
    )


def test_seconds_until_tomorrow_is_bounded_by_one_day() -> None:
    moment = datetime(2026, 8, 3, 23, 0, tzinfo=timezone.utc)
    assert run_store.seconds_until_tomorrow(moment) == 3600


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
