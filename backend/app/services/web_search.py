"""Provider boundary for web search and page extraction.

Lead enrichment asks this module for evidence about a company or a property and
gets back provider-neutral hits. Parallel (https://platform.parallel.ai) is the
primary provider; Serper is kept as a fallback for when no Parallel key is
configured or a Parallel call fails, so enrichment degrades instead of dying.

:func:`extract_urls` is the second half of the boundary: given a handful of URLs
it returns objective-focused excerpts from those exact pages. Only Parallel
implements it, so a missing key or a failed call returns an empty result with a
warning and the caller falls back to its own HTML parsing.

Callers never see provider payloads: they get :class:`WebSearchHit` and
:class:`WebExtractPage` objects with already-cleaned plain-text passages,
because the downstream OpenAI classifiers require cited evidence to be a literal
substring of the snippet text.
"""

import asyncio
import html
import logging
import re
import unicodedata
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

PARALLEL_SEARCH_URL = "https://api.parallel.ai/v1/search"
PARALLEL_EXTRACT_URL = "https://api.parallel.ai/v1/extract"
SERPER_SEARCH_URL = "https://google.serper.dev/search"

_TIMEOUT_SECONDS = 15
# Extract fetches whole pages rather than serving an index, so it needs a
# longer leash than search: a warm fetch comes back in about 1s, but a cold
# fetch of two uncached pages was measured at 25s. The budget stops short of
# that on purpose. The analyze endpoint runs up to three leads inside one 60s
# Vercel function, so a slow extract has to give up and let the raw HTML
# fallback run rather than eat the whole request.
_EXTRACT_TIMEOUT_SECONDS = 20
_USER_AGENT = "inbound-sdr-copilot/0.1"
# Parallel accepts 1-5 keyword queries per request.
MAX_QUERIES = 5
# Excerpts below this length are navigation crumbs, not evidence.
MIN_PASSAGE_CHARS = 40
# Parallel accepts at most 20 URLs per extract request.
MAX_EXTRACT_URLS = 20
# Enough page text for the caller to slide an evidence window over it without
# paying for whole-site dumps.
EXTRACT_MAX_CHARS_PER_RESULT = 6000

_NO_PROVIDER_WARNING = "Web search skipped because no search provider is configured."
_FALLBACK_WARNING = (
    "The primary web search provider failed; fell back to the secondary provider."
)
_MISSING_PRIMARY_KEY_WARNING = (
    "The primary web search provider is not configured; used the fallback provider."
)
_NO_EXTRACT_PROVIDER_WARNING = (
    "Page content extraction was skipped because no extraction provider is configured."
)
_EXTRACT_FAILED_WARNING = "Page content extraction failed; fell back to reading the page directly."
_NO_EXTRACT_URL_WARNING = "Page content extraction was skipped because no URL was supplied."
_EXTRACT_DISABLED_WARNING = "Page content extraction is disabled."


@dataclass(frozen=True)
class WebSearchHit:
    """One result page, with its usable text already cleaned."""

    url: str
    title: str | None = None
    publish_date: str | None = None
    passages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebSearchResult:
    hits: list[WebSearchHit] = field(default_factory=list)
    provider: str = "none"
    session_id: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebExtractPage:
    """One requested page, with its usable text already cleaned."""

    url: str
    title: str | None = None
    publish_date: str | None = None
    passages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebExtractResult:
    pages: list[WebExtractPage] = field(default_factory=list)
    # Keyed by the URL that failed, so callers can reconcile a partial response
    # against the URLs they asked for.
    errors: dict[str, str] = field(default_factory=dict)
    provider: str = "none"
    warnings: list[str] = field(default_factory=list)


async def search_web(
    *,
    objective: str,
    queries: list[str],
    mode: str = "fast",
    max_results: int = 5,
    location: str | None = "us",
    after_date: str | None = None,
    session_id: str | None = None,
) -> WebSearchResult:
    """Run one web search through the configured provider.

    Returns an empty result with a descriptive warning rather than raising, so a
    missing key or a provider outage only costs the caller its evidence.
    """

    settings = get_settings()
    cleaned_queries = _prepare_queries(queries)
    if not cleaned_queries:
        return WebSearchResult(warnings=["Web search skipped because no query was built."])

    provider = (settings.web_search_provider or "parallel").strip().lower()
    warnings: list[str] = []

    if provider != "serper":
        if settings.parallel_api_key:
            try:
                return await _search_parallel(
                    api_key=settings.parallel_api_key,
                    objective=objective,
                    queries=cleaned_queries,
                    mode=mode,
                    max_results=max_results,
                    location=location,
                    after_date=after_date,
                    session_id=session_id,
                )
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                # Never log the key: only the exception type and message.
                logger.warning("Parallel search failed (%s: %s)", type(exc).__name__, exc)
                warnings.append(_FALLBACK_WARNING)
        else:
            warnings.append(_MISSING_PRIMARY_KEY_WARNING)

    if settings.serper_api_key:
        result = await _search_serper(queries=cleaned_queries, max_results=max_results)
        return WebSearchResult(
            hits=result.hits,
            provider=result.provider,
            session_id=result.session_id,
            warnings=[*warnings, *result.warnings],
        )

    if warnings == [_MISSING_PRIMARY_KEY_WARNING]:
        warnings = []
    warnings.append(_NO_PROVIDER_WARNING)
    return WebSearchResult(warnings=warnings)


async def _search_parallel(
    *,
    api_key: str,
    objective: str,
    queries: list[str],
    mode: str,
    max_results: int,
    location: str | None,
    after_date: str | None,
    session_id: str | None,
) -> WebSearchResult:
    advanced_settings: dict[str, object] = {"max_results": max_results}
    if location:
        advanced_settings["location"] = location
    if after_date:
        advanced_settings["source_policy"] = {"after_date": after_date}

    body: dict[str, object] = {
        "objective": objective or None,
        "search_queries": queries,
        "mode": mode,
        "advanced_settings": advanced_settings,
    }
    if session_id:
        body["session_id"] = session_id

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(
            PARALLEL_SEARCH_URL,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("Parallel search returned a non-object payload")

    hits: list[WebSearchHit] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = clean_whitespace(str(item.get("url") or ""))
        if not url:
            continue
        passages = clean_passages(item.get("excerpts") or [])
        if not passages:
            continue
        hits.append(
            WebSearchHit(
                url=url,
                title=clean_whitespace(str(item.get("title") or "")) or None,
                publish_date=clean_whitespace(str(item.get("publish_date") or "")) or None,
                passages=passages,
            )
        )

    return WebSearchResult(
        hits=hits,
        provider="parallel",
        session_id=payload.get("session_id"),
        warnings=_parallel_warnings(payload.get("warnings")),
    )


async def _search_serper(*, queries: list[str], max_results: int) -> WebSearchResult:
    """Fallback provider: one request per keyword query, organic results only.

    Serper has no multi-query endpoint, so the queries fan out as concurrent
    requests sharing one client. That bounds the whole fallback to a single
    request timeout instead of one per query, which matters because this path
    usually runs after the primary provider has already spent its own timeout.

    Serper also has no equivalent of the primary provider's ``after_date``
    filter and reports dates as free text, so the freshness window is not
    enforced here; callers still rank dated hits newest-first.
    """

    settings = get_settings()
    hits: dict[str, WebSearchHit] = {}
    warnings: list[str] = []

    async def fetch(client: httpx.AsyncClient, query: str) -> dict | None:
        try:
            response = await client.post(
                SERPER_SEARCH_URL,
                headers={
                    "X-API-KEY": settings.serper_api_key or "",
                    "Content-Type": "application/json",
                    "User-Agent": _USER_AGENT,
                },
                json={"q": query, "num": max_results},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Fallback search failed for query %s (%s)", query, type(exc).__name__)
            return None
        return payload if isinstance(payload, dict) else None

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        payloads = await asyncio.gather(*(fetch(client, query) for query in queries))

    for query, payload in zip(queries, payloads):
        if payload is None:
            warnings.append(f"Search results were unavailable for query: {query}")
            continue

        for item in (payload.get("organic") or [])[:max_results]:
                if not isinstance(item, dict):
                    continue
                url = clean_whitespace(str(item.get("link") or ""))
                passage = clean_whitespace(str(item.get("snippet") or ""))
                if not url or not passage:
                    continue
                existing = hits.get(url)
                if existing is None:
                    hits[url] = WebSearchHit(
                        url=url,
                        title=clean_whitespace(str(item.get("title") or "")) or None,
                        publish_date=clean_whitespace(str(item.get("date") or "")) or None,
                        passages=[passage],
                    )
                elif passage not in existing.passages:
                    existing.passages.append(passage)

    return WebSearchResult(hits=list(hits.values()), provider="serper", warnings=warnings)


async def extract_urls(
    *,
    urls: list[str],
    objective: str,
    queries: list[str] | None = None,
    session_id: str | None = None,
    max_chars_total: int | None = None,
) -> WebExtractResult:
    """Pull objective-focused excerpts out of specific pages.

    Unlike :func:`search_web` this reads URLs the caller already chose, which is
    how enrichment gets at JS-rendered and PDF pages a plain HTML parse cannot
    read. Only Parallel implements extraction, so a missing key or a failed call
    returns an empty result with a warning instead of raising: the caller then
    falls back to fetching and parsing the page itself. Setting
    ``WEB_EXTRACT_ENABLED=false`` takes the same route without any network call,
    which is how the provider benchmark reproduces the pre-Parallel stack.
    """

    settings = get_settings()
    if not settings.web_extract_enabled:
        return WebExtractResult(warnings=[_EXTRACT_DISABLED_WARNING])

    prepared_urls = _prepare_urls(urls)
    if not prepared_urls:
        return WebExtractResult(warnings=[_NO_EXTRACT_URL_WARNING])

    if not settings.parallel_api_key:
        return WebExtractResult(warnings=[_NO_EXTRACT_PROVIDER_WARNING])

    try:
        return await _extract_parallel(
            api_key=settings.parallel_api_key,
            urls=prepared_urls,
            objective=objective,
            queries=_prepare_queries(queries or []),
            session_id=session_id,
            max_chars_total=max_chars_total,
        )
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        # Never log the key: only the exception type and message.
        logger.warning("Parallel extract failed (%s: %s)", type(exc).__name__, exc)
        return WebExtractResult(warnings=[_EXTRACT_FAILED_WARNING])


async def _extract_parallel(
    *,
    api_key: str,
    urls: list[str],
    objective: str,
    queries: list[str],
    session_id: str | None,
    max_chars_total: int | None,
) -> WebExtractResult:
    body: dict[str, object] = {
        "urls": urls,
        "objective": objective or None,
        "advanced_settings": {
            "excerpt_settings": {"max_chars_per_result": EXTRACT_MAX_CHARS_PER_RESULT},
        },
    }
    if queries:
        body["search_queries"] = queries
    if session_id:
        body["session_id"] = session_id
    if max_chars_total:
        body["max_chars_total"] = max_chars_total

    async with httpx.AsyncClient(timeout=_EXTRACT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            PARALLEL_EXTRACT_URL,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("Parallel extract returned a non-object payload")

    # A 200 can still be partial: any requested URL may land in "errors"
    # instead of "results", and neither list is ordered like the request. Both
    # are reconciled by URL rather than by position.
    pages: list[WebExtractPage] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = clean_whitespace(str(item.get("url") or ""))
        if not url:
            continue
        passages = clean_passages(item.get("excerpts") or [])
        full_content = clean_excerpt(str(item.get("full_content") or ""))
        if full_content and full_content not in passages:
            passages.append(full_content)
        if not passages:
            continue
        pages.append(
            WebExtractPage(
                url=url,
                title=clean_whitespace(str(item.get("title") or "")) or None,
                publish_date=clean_whitespace(str(item.get("publish_date") or "")) or None,
                passages=passages,
            )
        )

    errors: dict[str, str] = {}
    for item in payload.get("errors") or []:
        if not isinstance(item, dict):
            continue
        url = clean_whitespace(str(item.get("url") or ""))
        if not url:
            continue
        errors[url] = _extract_error_message(item)

    return WebExtractResult(
        pages=pages,
        errors=errors,
        provider="parallel",
        warnings=_parallel_warnings(payload.get("warnings"), prefix="Page extraction warning"),
    )


def _extract_error_message(item: dict) -> str:
    detail = clean_whitespace(str(item.get("error_type") or "")) or "extract_failed"
    status = item.get("http_status_code")
    if isinstance(status, int):
        return f"{detail} (HTTP {status})"
    return detail


def _prepare_urls(urls: list[str]) -> list[str]:
    prepared: list[str] = []
    for url in urls:
        cleaned = clean_whitespace(str(url or ""))
        if cleaned and cleaned not in prepared:
            prepared.append(cleaned)
    return prepared[:MAX_EXTRACT_URLS]


def _prepare_queries(queries: list[str]) -> list[str]:
    prepared: list[str] = []
    for query in queries:
        cleaned = clean_whitespace(str(query or ""))[:200].strip()
        if cleaned and cleaned not in prepared:
            prepared.append(cleaned)
    return prepared[:MAX_QUERIES]


def _parallel_warnings(raw_warnings: object, *, prefix: str = "Web search warning") -> list[str]:
    if not isinstance(raw_warnings, list):
        return []
    messages: list[str] = []
    for warning in raw_warnings:
        if isinstance(warning, dict):
            text = clean_whitespace(str(warning.get("message") or warning.get("type") or ""))
        else:
            text = clean_whitespace(str(warning))
        if text:
            messages.append(f"{prefix}: {text}")
    return messages


# --- excerpt cleaning -------------------------------------------------------

# Tags carry long hrefs, so the bound has to be generous; excluding "<" and ">"
# from the body keeps the match linear.
_HTML_TAG_RE = re.compile(r"<[^<>]{0,2000}>")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Reference markers such as Wikipedia's "[[ 36 ]]()" and the empty parens they
# leave behind once the link text is gone.
_CITATION_MARKER_RE = re.compile(r"\[+\s*\d{1,4}\s*\]+")
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_BULLET_RE = re.compile(r"^\s{0,3}(?:[-*+•]|\d{1,2}[.)])\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_EMPHASIS_RE = re.compile(r"(?:\*\*|__|~~|`+)")
# Markdown tables (infobox rows on Wikipedia, for example) arrive as pipes and
# dash rules; the cells are real evidence but the scaffolding is not.
_TABLE_SEPARATOR_RE = re.compile(r"^[\s|:-]*\|[\s|:-]*$")
_TABLE_PIPE_RE = re.compile(r"\s*\|+\s*")
_DASH_RUN_RE = re.compile(r"(?:(?<=\s)|^)[-:]{2,}(?=\s|$)")
# Markdown escapes punctuation, so "1\.1 m+" has to become "1.1 m+" before a
# classifier can read the number.
_MARKDOWN_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")

_BOILERPLATE_PREFIXES = (
    "jump to content",
    "jump to navigation",
    "skip to content",
    "skip to main content",
    "toggle navigation",
    "main menu",
    "main navigation",
    "table of contents",
    "back to top",
    "share this",
    "read more",
    "sign in",
    "log in",
    "subscribe",
    "advertisement",
    "cookie",
)
_BOILERPLATE_PHRASES = (
    "we use cookies",
    "accept all cookies",
    "cookie policy",
    "cookie preferences",
    "enable javascript",
    "javascript is disabled",
    "all rights reserved",
    "privacy policy",
    "terms of service",
)


def clean_passages(excerpts: object) -> list[str]:
    """Clean provider excerpts down to usable plain-text passages."""

    if not isinstance(excerpts, list):
        return []
    passages: list[str] = []
    for excerpt in excerpts:
        passage = clean_excerpt(str(excerpt or ""))
        if passage and passage not in passages:
            passages.append(passage)
    return passages


def clean_excerpt(excerpt: str) -> str:
    """Strip markup and boilerplate from one excerpt; return "" if unusable.

    Excerpts arrive as markdown and can carry literal HTML tags, links, heading
    markers, list bullets and navigation chrome. Whatever survives has to be
    quotable verbatim, because the classifiers reject evidence they cannot find
    as a literal substring.
    """

    kept_lines: list[str] = []
    for raw_line in excerpt.replace("\r\n", "\n").split("\n"):
        line = _clean_line(raw_line)
        if not line or _is_boilerplate(line):
            continue
        kept_lines.append(line)

    text = clean_whitespace(" ".join(kept_lines))
    if len(text) < MIN_PASSAGE_CHARS or _is_boilerplate(text):
        return ""
    return text


def _clean_line(line: str) -> str:
    text = _HTML_TAG_RE.sub(" ", line)
    text = _MARKDOWN_IMAGE_RE.sub(r"\1", text)
    # Twice, because links nest: "[[ 36 ]](url)" only unwraps one layer a pass.
    text = _MARKDOWN_LINK_RE.sub(r"\1", _MARKDOWN_LINK_RE.sub(r"\1", text))
    text = _CITATION_MARKER_RE.sub(" ", text)
    text = _EMPTY_PARENS_RE.sub(" ", text)
    if _HORIZONTAL_RULE_RE.match(text) or _TABLE_SEPARATOR_RE.match(text):
        return ""
    text = _TABLE_PIPE_RE.sub(" ", text)
    text = _DASH_RUN_RE.sub(" ", text)
    text = _HEADING_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _EMPHASIS_RE.sub("", text)
    text = _MARKDOWN_ESCAPE_RE.sub(r"\1", text)
    text = clean_whitespace(text)
    # A line with no letters or digits left is pure layout.
    return text if re.search(r"[A-Za-z0-9]", text) else ""


def _is_boilerplate(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith(_BOILERPLATE_PREFIXES):
        return True
    # Only short fragments are judged by phrase: a real paragraph that happens
    # to mention a cookie banner is still evidence.
    return len(lowered) < 200 and any(phrase in lowered for phrase in _BOILERPLATE_PHRASES)


def clean_whitespace(value: str) -> str:
    """Normalize entities, unicode and whitespace into flat plain text."""

    normalized = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", normalized)
    replacements = {
        " ": " ",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "•": " ",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return re.sub(r"\s+", " ", normalized).strip()
