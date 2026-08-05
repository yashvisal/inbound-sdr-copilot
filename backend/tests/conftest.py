import pytest

from app.config import Settings
from app.services import run_store


@pytest.fixture
def anyio_backend() -> str:
    """Single async backend for every anyio test module in the suite."""

    return "asyncio"


@pytest.fixture(autouse=True)
def disable_run_store(monkeypatch):
    """Keep the test suite off the shared run store.

    backend/.env carries real Upstash credentials, so without this every test
    that exercises /api/leads/analyze would write to the live dashboard and
    burn the public demo's monthly run budget.
    """

    monkeypatch.setattr(
        run_store,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            UPSTASH_REDIS_REST_URL=None,
            UPSTASH_REDIS_REST_TOKEN=None,
        ),
    )
