import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.services import web_search
from app.services.web_search import clean_excerpt, search_web


def _settings(**overrides) -> Settings:
    values = {
        "PARALLEL_API_KEY": "parallel-test-key",
        "SERPER_API_KEY": "serper-test-key",
        "WEB_SEARCH_PROVIDER": "parallel",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _use_settings(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(web_search, "get_settings", lambda: _settings(**overrides))


def _install_post(monkeypatch, handler) -> list[dict]:
    """Record every outbound POST and answer it with ``handler``."""

    calls: list[dict] = []

    async def fake_post(self, url, *, headers=None, json=None, **kwargs):  # noqa: A002
        calls.append({"url": url, "headers": headers or {}, "json": json})
        return handler(url, json)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


def _response(url: str, payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        request=httpx.Request("POST", url),
    )


def _parallel_payload(results: list[dict], **extra) -> dict:
    payload = {"search_id": "search_1", "results": results, "session_id": None}
    payload.update(extra)
    return payload


def _search(**kwargs):
    defaults = {
        "objective": "Find out how many units Example Residential manages.",
        "queries": ["Example Residential", "Example Residential units managed"],
        "mode": "fast",
        "max_results": 5,
    }
    defaults.update(kwargs)
    return asyncio.run(search_web(**defaults))


def test_parallel_results_are_parsed_into_hits(monkeypatch) -> None:
    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(
            url,
            _parallel_payload(
                [
                    {
                        "url": "https://example.com/about",
                        "title": "About Example Residential",
                        "publish_date": "2025-03-04",
                        "excerpts": [
                            "Example Residential manages 42,000 apartment units across 14 states.",
                            "The company operates 180 communities and a centralized leasing team.",
                        ],
                    },
                    {
                        "url": "https://news.example.com/story",
                        "title": None,
                        "publish_date": None,
                        "excerpts": [
                            "A profile of the firm's multifamily portfolio and leasing operations."
                        ],
                    },
                ]
            ),
        ),
    )

    result = _search()

    assert result.provider == "parallel"
    assert [hit.url for hit in result.hits] == [
        "https://example.com/about",
        "https://news.example.com/story",
    ]
    assert len(result.hits[0].passages) == 2
    assert result.hits[0].publish_date == "2025-03-04"
    assert result.hits[1].title is None
    assert result.hits[1].publish_date is None
    assert result.warnings == []


def test_parallel_warnings_and_empty_results_are_surfaced(monkeypatch) -> None:
    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(
            url,
            _parallel_payload(
                [],
                warnings=[
                    {
                        "type": "query_truncated",
                        "message": "One search query was truncated.",
                        "detail": None,
                    }
                ],
                session_id="session_9",
            ),
        ),
    )

    result = _search()

    assert result.hits == []
    assert result.session_id == "session_9"
    assert result.warnings == ["Web search warning: One search query was truncated."]


def test_parallel_request_body_caps_queries_and_carries_settings(monkeypatch) -> None:
    _use_settings(monkeypatch)
    calls = _install_post(
        monkeypatch,
        lambda url, body: _response(url, _parallel_payload([])),
    )

    _search(
        queries=[f"query {index}" for index in range(8)],
        mode="basic",
        max_results=3,
        location="us",
        after_date="2021-01-01",
    )

    assert len(calls) == 1
    body = calls[0]["json"]
    assert calls[0]["url"] == web_search.PARALLEL_SEARCH_URL
    assert calls[0]["headers"]["x-api-key"] == "parallel-test-key"
    assert body["search_queries"] == [f"query {index}" for index in range(5)]
    assert body["mode"] == "basic"
    assert body["advanced_settings"] == {
        "max_results": 3,
        "location": "us",
        "source_policy": {"after_date": "2021-01-01"},
    }


def test_parallel_http_error_falls_back_to_serper(monkeypatch) -> None:
    _use_settings(monkeypatch)

    def handler(url: str, body: dict) -> httpx.Response:
        if url == web_search.PARALLEL_SEARCH_URL:
            return _response(url, {"detail": "invalid request"}, status_code=422)
        return _response(
            url,
            {
                "organic": [
                    {
                        "title": "Example Residential",
                        "link": "https://example.com",
                        "snippet": "Example Residential manages 42,000 apartment units nationwide.",
                    }
                ]
            },
        )

    calls = _install_post(monkeypatch, handler)

    result = _search()

    assert [call["url"] for call in calls] == [
        web_search.PARALLEL_SEARCH_URL,
        web_search.SERPER_SEARCH_URL,
        web_search.SERPER_SEARCH_URL,
    ]
    assert result.provider == "serper"
    assert len(result.hits) == 1
    assert result.hits[0].passages == [
        "Example Residential manages 42,000 apartment units nationwide."
    ]
    assert "fell back to the secondary provider" in result.warnings[0]
    assert "Serper" not in result.warnings[0]


def test_serper_provider_setting_skips_parallel(monkeypatch) -> None:
    _use_settings(monkeypatch, WEB_SEARCH_PROVIDER="serper")
    calls = _install_post(
        monkeypatch,
        lambda url, body: _response(url, {"organic": []}),
    )

    result = _search(queries=["only query"])

    assert [call["url"] for call in calls] == [web_search.SERPER_SEARCH_URL]
    assert result.provider == "serper"


def test_missing_parallel_key_uses_serper_and_says_so(monkeypatch) -> None:
    _use_settings(monkeypatch, PARALLEL_API_KEY=None)
    calls = _install_post(
        monkeypatch,
        lambda url, body: _response(url, {"organic": []}),
    )

    result = _search(queries=["only query"])

    assert [call["url"] for call in calls] == [web_search.SERPER_SEARCH_URL]
    assert result.provider == "serper"
    assert result.warnings == [
        "The primary web search provider is not configured; used the fallback provider."
    ]


def test_no_configured_provider_returns_empty_result(monkeypatch) -> None:
    _use_settings(monkeypatch, PARALLEL_API_KEY=None, SERPER_API_KEY=None)

    def fail(*args, **kwargs):
        raise AssertionError("no HTTP call should be made without a provider key")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)

    result = _search()

    assert result.hits == []
    assert result.provider == "none"
    assert result.warnings == [
        "Web search skipped because no search provider is configured."
    ]


def test_empty_query_list_short_circuits(monkeypatch) -> None:
    _use_settings(monkeypatch)

    def fail(*args, **kwargs):
        raise AssertionError("no HTTP call should be made without a query")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)

    result = _search(queries=["", "   "])

    assert result.hits == []
    assert result.warnings == ["Web search skipped because no query was built."]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Harbor <strong>Residential</strong> manages 42,000 apartment units today.",
            "Harbor Residential manages 42,000 apartment units today.",
        ),
        (
            "## About us\n\n- [Our portfolio](https://example.com/portfolio) spans "
            "180 communities in 14 states.",
            "About us Our portfolio spans 180 communities in 14 states.",
        ),
        (
            "Jump to content\nHarbor Residential operates 180 apartment communities.",
            "Harbor Residential operates 180 apartment communities.",
        ),
        (
            "| | |\n| --- | --- |\n|Industry |Real estate |\n|Units |906,604 apartment units |",
            "Industry Real estate Units 906,604 apartment units",
        ),
        (
            "Greystar added 38,000 units to its portfolio. [[ 36 ]]() [[ 37 ]]()",
            "Greystar added 38,000 units to its portfolio.",
        ),
        (
            'Harbor manages 1\\.1 m+ units <a class="link" href="https://www.example.com/'
            + "x" * 300
            + '">nationwide</a>.',
            "Harbor manages 1.1 m+ units nationwide .",
        ),
    ],
)
def test_clean_excerpt_normalizes_markup(raw: str, expected: str) -> None:
    assert clean_excerpt(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Jump to content",
        "Skip to main content",
        "We use cookies to improve your experience on this site.",
        "180 units",
        "",
    ],
)
def test_clean_excerpt_drops_boilerplate_and_stubs(raw: str) -> None:
    assert clean_excerpt(raw) == ""


def test_parallel_hits_without_usable_excerpts_are_dropped(monkeypatch) -> None:
    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(
            url,
            _parallel_payload(
                [
                    {
                        "url": "https://example.com/nav",
                        "title": "Nav",
                        "publish_date": None,
                        "excerpts": ["Jump to content", "Menu"],
                    },
                    {
                        "url": "",
                        "title": "No URL",
                        "excerpts": ["Harbor Residential operates 180 communities."],
                    },
                ]
            ),
        ),
    )

    assert _search().hits == []


# --- extract ---------------------------------------------------------------


def _extract_payload(results: list[dict], **extra) -> dict:
    payload = {"extract_id": "extract_1", "results": results, "session_id": None}
    payload.update(extra)
    return payload


def _extract(**kwargs):
    defaults = {
        "urls": ["https://example.com/about", "https://example.com/"],
        "objective": "Describe what Example Residential does and how many units it manages.",
    }
    defaults.update(kwargs)
    return asyncio.run(web_search.extract_urls(**defaults))


def test_extract_parses_pages_and_reconciles_errors_by_url(monkeypatch) -> None:
    """A 200 can be partial, and neither list is ordered like the request."""

    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(
            url,
            _extract_payload(
                [
                    {
                        "url": "https://example.com/",
                        "title": None,
                        "publish_date": None,
                        "excerpts": [
                            "Example Residential is a national multifamily operator."
                        ],
                        "full_content": None,
                    },
                    {
                        "url": "https://example.com/about",
                        "title": "About Example Residential",
                        "publish_date": "2025-06-01",
                        "excerpts": [
                            "Example Residential manages 42,000 apartment units across 14 states."
                        ],
                    },
                ],
                errors=[
                    {
                        "url": "https://example.com/portfolio",
                        "error_type": "fetch_failed",
                        "http_status_code": 403,
                        "content": None,
                    }
                ],
            ),
        ),
    )

    result = _extract(urls=["https://example.com/portfolio", "https://example.com/about"])

    assert result.provider == "parallel"
    # Reconciled by URL, not by position in the request or the response.
    pages = {page.url: page for page in result.pages}
    assert set(pages) == {"https://example.com/", "https://example.com/about"}
    assert pages["https://example.com/about"].title == "About Example Residential"
    assert pages["https://example.com/about"].publish_date == "2025-06-01"
    assert pages["https://example.com/"].title is None
    assert pages["https://example.com/"].publish_date is None
    assert result.errors == {"https://example.com/portfolio": "fetch_failed (HTTP 403)"}
    assert result.warnings == []


def test_extract_cleans_markdown_excerpts_and_drops_empty_pages(monkeypatch) -> None:
    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(
            url,
            _extract_payload(
                [
                    {
                        "url": "https://example.com/about",
                        "excerpts": [
                            "## About us\n\n- [Our portfolio](https://example.com/p) spans "
                            "180 communities in 14 states."
                        ],
                    },
                    {
                        "url": "https://example.com/nav",
                        "excerpts": ["Jump to content", "Menu"],
                    },
                ]
            ),
        ),
    )

    result = _extract()

    assert [page.url for page in result.pages] == ["https://example.com/about"]
    assert result.pages[0].passages == [
        "About us Our portfolio spans 180 communities in 14 states."
    ]


def test_extract_request_body_carries_objective_queries_and_session(monkeypatch) -> None:
    _use_settings(monkeypatch)
    calls = _install_post(
        monkeypatch,
        lambda url, body: _response(url, _extract_payload([])),
    )

    _extract(
        urls=["https://example.com/about", "https://example.com/about", " "],
        queries=["units managed", "property management"],
        session_id="session_7",
        max_chars_total=8000,
    )

    assert len(calls) == 1
    assert calls[0]["url"] == web_search.PARALLEL_EXTRACT_URL
    assert calls[0]["headers"]["x-api-key"] == "parallel-test-key"
    body = calls[0]["json"]
    assert body["urls"] == ["https://example.com/about"]
    assert body["search_queries"] == ["units managed", "property management"]
    assert body["session_id"] == "session_7"
    assert body["max_chars_total"] == 8000
    assert body["advanced_settings"]["excerpt_settings"]["max_chars_per_result"] == (
        web_search.EXTRACT_MAX_CHARS_PER_RESULT
    )


def test_extract_caps_urls_at_the_provider_limit(monkeypatch) -> None:
    _use_settings(monkeypatch)
    calls = _install_post(
        monkeypatch,
        lambda url, body: _response(url, _extract_payload([])),
    )

    _extract(urls=[f"https://example.com/page-{index}" for index in range(30)])

    assert len(calls[0]["json"]["urls"]) == web_search.MAX_EXTRACT_URLS


def test_extract_without_a_key_returns_an_empty_result(monkeypatch) -> None:
    """No key means the caller has to fall back, so say so instead of raising."""

    _use_settings(monkeypatch, PARALLEL_API_KEY=None)

    def fail(*args, **kwargs):
        raise AssertionError("no HTTP call should be made without a key")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)

    result = _extract()

    assert result.pages == []
    assert result.provider == "none"
    assert result.warnings == [
        "Page content extraction was skipped because no extraction provider is configured."
    ]


def test_extract_http_error_returns_an_empty_result_with_a_warning(monkeypatch) -> None:
    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(url, {"detail": "invalid request"}, status_code=422),
    )

    result = _extract()

    assert result.pages == []
    assert result.provider == "none"
    assert result.warnings == [
        "Page content extraction failed; fell back to reading the page directly."
    ]


def test_extract_without_urls_short_circuits(monkeypatch) -> None:
    _use_settings(monkeypatch)

    def fail(*args, **kwargs):
        raise AssertionError("no HTTP call should be made without a URL")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)

    result = _extract(urls=["", "   "])

    assert result.pages == []
    assert result.warnings == [
        "Page content extraction was skipped because no URL was supplied."
    ]


def test_extract_surfaces_provider_warnings(monkeypatch) -> None:
    _use_settings(monkeypatch)
    _install_post(
        monkeypatch,
        lambda url, body: _response(
            url,
            _extract_payload(
                [],
                warnings=[{"type": "url_truncated", "message": "One URL was dropped."}],
            ),
        ),
    )

    assert _extract().warnings == ["Page extraction warning: One URL was dropped."]


def test_extract_disabled_short_circuits_before_the_network(monkeypatch) -> None:
    """WEB_EXTRACT_ENABLED=false has to skip the call, not just discard it."""

    _use_settings(monkeypatch, WEB_EXTRACT_ENABLED=False)

    def fail(*args, **kwargs):
        raise AssertionError("no HTTP call should be made when extraction is disabled")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)

    result = _extract()

    assert result.pages == []
    assert result.errors == {}
    assert result.provider == "none"
    assert result.warnings == ["Page content extraction is disabled."]
