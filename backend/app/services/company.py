import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.models import CompanyEnrichment, LeadInput, SourceSnippet
from app.services.company_classifier import classify_company_signals
from app.services.geocoder import fetch_osm_address_metadata
from app.services.property_classifier import classify_property_signals
from app.services.web_search import WebExtractPage, WebSearchHit, extract_urls, search_web
from app.services.web_search import clean_whitespace as _clean_whitespace

logger = logging.getLogger(__name__)

# Provider-neutral labels: the evidence panel names the kind of source, not
# whichever search vendor happened to answer.
COMPANY_SOURCE_LABEL = "Web search"
PROPERTY_SOURCE_LABEL = "Web search (property)"
# Unit counts in decade-old press releases are usually stale, so the company
# search only looks back this far.
COMPANY_SEARCH_LOOKBACK_YEARS = 5
# How much website text the classifiers read.
WEBSITE_SNIPPET_CHARS = 700
# Path fragments that mark the page on a company site that actually says what
# the company does. A bare homepage is mostly listings and navigation, so these
# are extracted in preference to it.
WEBSITE_PATH_KEYWORDS = (
    "about-us",
    "about",
    "who-we-are",
    "our-company",
    "our-story",
    "company",
    "property-management",
    "management",
    "services",
    "portfolio",
    "communities",
)
# Extracting more than a few pages costs more than it adds: the best evidence is
# almost always on the first about-style page or the homepage.
MAX_WEBSITE_CANDIDATES = 3

BUSINESS_TYPE_TERMS = {
    "property manager",
    "property management",
    "multifamily",
    "apartment",
    "apartments",
    "residential",
    "rental housing",
    "rental homes",
    "single-family rental",
    "real estate",
    "communities",
    "student housing",
    "senior living",
    "developer",
    "develops",
    "operates",
}
LEASING_VOLUME_TERMS = {
    "portfolio",
    "communities",
    "buildings",
    "properties",
    "units",
    "doors",
    "homes",
    "locations",
    "regional",
    "national",
    "nationwide",
    "multiple markets",
    "managed",
    "manages",
    "operates",
}
OPERATIONAL_COMPLEXITY_TERMS = {
    "resident",
    "residents",
    "resident services",
    "resident engagement",
    "resident communication",
    "tenant",
    "tenants",
    "tenant turnover",
    "leasing",
    "lease",
    "seasonal leasing",
    "leasing cycles",
    "leasing teams",
    "tour",
    "tours",
    "maintenance",
    "maintenance operations",
    "maintenance services",
    "renewal",
    "renewals",
    "rent collection",
    "property operations",
    "work orders",
}
PRODUCT_FIT_TERMS = {
    "leasing inquiries",
    "leasing teams",
    "lead management",
    "resident services",
    "resident engagement",
    "resident communication",
    "tour scheduling",
    "maintenance requests",
    "maintenance operations",
    "maintenance services",
    "centralized leasing",
    "contact center",
    "onsite teams",
    "after-hours",
}
RESIDENTIAL_PROPERTY_TERMS = {
    "apartment",
    "apartments",
    "residences",
    "residential",
    "homes",
    "rental homes",
    "single-family rental",
    "lofts",
    "villas",
    "flats",
    "townhomes",
    "community",
    "communities",
}
NON_RESIDENTIAL_PROPERTY_TERMS = {
    "office",
    "office leasing",
    "industrial",
    "warehouse",
    "medical office",
    "retail center",
    "logistics",
    "self storage",
    "commercial property",
}
GEOGRAPHIC_FOOTPRINT_TERMS = {
    "regional",
    "national",
    "states",
    "markets",
    "locations",
    "across",
}


@dataclass(frozen=True)
class CompanyEnrichmentResult:
    enrichment: CompanyEnrichment
    evidence: list[SourceSnippet]
    missing_data: list[str]


@dataclass(frozen=True)
class SearchEvidence:
    """What the company-name search produced, plus the provider session to reuse.

    Threading the session id into the website extract lets the provider bill and
    cache the two calls as one piece of work.
    """

    snippets: list[SourceSnippet]
    missing_data: list[str]
    session_id: str | None = None


@dataclass(frozen=True)
class WebsiteEvidence:
    """Website fields for the enrichment, plus the page date for the citation."""

    enrichment: CompanyEnrichment
    publish_date: str | None = None
    # Why the extraction provider did not supply this evidence, when the raw
    # HTML fallback had to. Surfaced as missing-data so a run shows that the
    # website step degraded even though it produced something.
    warnings: list[str] = field(default_factory=list)


class _HomepageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip_depth = 0
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return

        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        name = attrs_dict.get("name", "").lower()
        prop = attrs_dict.get("property", "").lower()
        if name == "description" or prop == "og:description":
            self.description = attrs_dict.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = _clean_whitespace(data)
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        elif not self._skip_depth:
            self.text_parts.append(text)

    @property
    def visible_text(self) -> str:
        return _clean_whitespace(" ".join(self.text_parts))


async def enrich_company(lead: LeadInput) -> CompanyEnrichmentResult:
    missing_data: list[str] = []
    evidence: list[SourceSnippet] = []

    search = await _fetch_search_snippets(lead)
    search_snippets = search.snippets
    evidence.extend(search_snippets)
    missing_data.extend(search.missing_data)

    osm_metadata = await fetch_osm_address_metadata(lead.address, lead.city, lead.state)
    if osm_metadata is None:
        missing_data.append("OSM property metadata was unavailable from Nominatim.")

    property_search_snippets, property_search_missing = await _fetch_property_search_snippets(
        lead,
        osm_display_name=osm_metadata.display_name if osm_metadata else None,
    )
    evidence.extend(property_search_snippets)
    missing_data.extend(property_search_missing)

    website_url = _website_url_from_search(search_snippets)
    website = None
    if website_url is None:
        missing_data.append("Company website was not inferred from company-name search results.")
    else:
        website_evidence = await _fetch_website_evidence(
            _website_candidate_urls(search_snippets),
            lead=lead,
            primary_url=website_url,
            session_id=search.session_id,
        )
        if website_evidence is None:
            missing_data.append(f"Company website metadata was unavailable for {website_url}.")
        else:
            website = website_evidence.enrichment
            missing_data.extend(website_evidence.warnings)
            evidence.insert(
                0,
                SourceSnippet(
                    source="Company website",
                    title=website.website_title or website.website_url,
                    url=website.website_url,
                    snippet=website.website_snippet
                    or website.website_description
                    or "Website metadata was fetched.",
                    publish_date=website_evidence.publish_date,
                ),
            )

    enrichment = extract_company_signals(
        lead=lead,
        domain=_domain_from_url(website.website_url) if website else None,
        website_url=website.website_url if website else None,
        website_title=website.website_title if website else None,
        website_description=website.website_description if website else None,
        website_snippet=website.website_snippet if website else None,
        search_snippets=search_snippets,
        property_search_snippets=property_search_snippets,
        osm_property_class=osm_metadata.osm_class if osm_metadata else None,
        osm_property_type=osm_metadata.osm_type if osm_metadata else None,
        osm_display_name=osm_metadata.display_name if osm_metadata else None,
    )
    (
        (classifications, classifier_missing),
        (property_classifications, property_classifier_missing),
    ) = await asyncio.gather(
        classify_company_signals(
            lead=lead,
            website_title=website.website_title if website else None,
            website_description=website.website_description if website else None,
            website_snippet=website.website_snippet if website else None,
            search_snippets=search_snippets,
        ),
        classify_property_signals(
            lead=lead,
            search_snippets=property_search_snippets,
        ),
    )
    if classifications:
        enrichment.classifications = classifications
    if classifier_missing:
        missing_data.append(classifier_missing)

    if property_classifications:
        enrichment.property_classifications = property_classifications
    if property_classifier_missing:
        missing_data.append(property_classifier_missing)

    return CompanyEnrichmentResult(
        enrichment=enrichment,
        evidence=evidence,
        missing_data=missing_data,
    )

def extract_company_signals(
    *,
    lead: LeadInput,
    domain: str | None = None,
    website_url: str | None = None,
    website_title: str | None = None,
    website_description: str | None = None,
    website_snippet: str | None = None,
    search_snippets: list[SourceSnippet] | None = None,
    property_search_snippets: list[SourceSnippet] | None = None,
    osm_property_class: str | None = None,
    osm_property_type: str | None = None,
    osm_display_name: str | None = None,
) -> CompanyEnrichment:
    snippets = search_snippets or []
    property_snippets = property_search_snippets or []
    matching_property_snippets = [
        snippet
        for snippet in property_snippets
        if _is_usable_property_evidence(
            f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower(),
            lead,
            property_aliases=_property_aliases(lead, osm_display_name),
        )
    ]
    source_text = _clean_whitespace(
        " ".join(
            [
                lead.company,
                lead.address,
                lead.city,
                lead.state,
                domain or "",
                website_title or "",
                website_description or "",
                website_snippet or "",
                *(snippet.title or "" for snippet in snippets),
                *(snippet.snippet for snippet in snippets),
            ]
        )
    )
    property_text = _clean_whitespace(
        " ".join(
            [
                lead.address,
                lead.city,
                lead.state,
                *(snippet.title or "" for snippet in matching_property_snippets),
                *(snippet.snippet for snippet in matching_property_snippets),
            ]
        )
    )

    scale_signals = _matched_terms(source_text, LEASING_VOLUME_TERMS)
    scale_signals.extend(_unit_count_signals(source_text))

    return CompanyEnrichment(
        domain=domain,
        website_url=website_url,
        website_title=website_title,
        website_description=website_description,
        website_snippet=website_snippet,
        search_snippets=snippets,
        property_search_snippets=matching_property_snippets,
        property_search_matches_address=bool(matching_property_snippets),
        osm_property_class=osm_property_class,
        osm_property_type=osm_property_type,
        osm_display_name=osm_display_name,
        business_type_signals=_matched_terms(source_text, BUSINESS_TYPE_TERMS),
        leasing_volume_signals=_dedupe(scale_signals),
        operational_complexity_signals=_matched_terms(source_text, OPERATIONAL_COMPLEXITY_TERMS),
        product_fit_signals=_matched_terms(source_text, PRODUCT_FIT_TERMS),
        property_signals=_matched_terms(property_text, RESIDENTIAL_PROPERTY_TERMS),
        negative_property_signals=_matched_terms(property_text, NON_RESIDENTIAL_PROPERTY_TERMS),
        geographic_footprint_signals=_matched_terms(source_text, GEOGRAPHIC_FOOTPRINT_TERMS),
        source_text=source_text,
    )


async def _fetch_website_evidence(
    candidate_urls: list[str],
    *,
    lead: LeadInput,
    primary_url: str,
    session_id: str | None = None,
) -> WebsiteEvidence | None:
    """Read the company's own site for what it does and how big it is.

    The extraction provider is tried first: it renders JavaScript, reads PDFs,
    and returns excerpts chosen against an objective, which is what turns a
    listings-heavy homepage into usable evidence. When it returns nothing
    usable -- no key, a failed call, or every candidate erroring -- the raw HTML
    parse of the primary URL still runs, so the website step degrades instead of
    disappearing.
    """

    objective = (
        f"Describe what {lead.company} does, whether it manages residential or "
        "multifamily rental housing, and how many apartment units, homes, properties, "
        "or communities it manages and in which markets."
    )
    result = await extract_urls(
        urls=candidate_urls,
        objective=objective,
        queries=["units managed", "property management", "communities"],
        session_id=session_id,
    )
    website = _website_evidence_from_pages(result.pages, lead=lead)
    if website is not None:
        return website

    fallback = await _fetch_website_metadata(primary_url)
    if fallback is None:
        return None
    warnings = list(result.warnings)
    if not warnings and (result.errors or result.provider != "none"):
        warnings.append(
            "Page content extraction returned no usable page; fell back to reading the page directly."
        )
    return WebsiteEvidence(enrichment=fallback, warnings=warnings)


def _website_evidence_from_pages(
    pages: list[WebExtractPage],
    *,
    lead: LeadInput,
) -> WebsiteEvidence | None:
    """Pick the extracted page whose text carries the most scoring signal."""

    best: WebsiteEvidence | None = None
    best_score = 0
    for page in pages:
        text = _clean_whitespace(" ".join(page.passages))
        if not text:
            continue
        bonus_terms = [lead.company]
        window = _best_evidence_window(
            text,
            limit=WEBSITE_SNIPPET_CHARS,
            step=100,
            bonus_terms=bonus_terms,
        )
        score = _evidence_density(window, bonus_terms)
        if best is not None and score <= best_score:
            continue
        best_score = score
        best = WebsiteEvidence(
            enrichment=CompanyEnrichment(
                domain=_domain_from_url(page.url),
                website_url=page.url,
                website_title=page.title,
                website_description=_website_description_from_passages(page.passages),
                website_snippet=window or None,
            ),
            publish_date=page.publish_date,
        )
    return best


def _website_description_from_passages(passages: list[str]) -> str | None:
    """Stand in for the meta description with the first blurb-length passage."""

    for passage in passages:
        if len(passage) <= 300:
            return passage
    return None


async def _fetch_website_metadata(url: str) -> CompanyEnrichment | None:
    urls = _candidate_website_urls(url)
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for url in urls:
            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": "inbound-sdr-copilot/0.1"},
                )
            except httpx.HTTPError:
                continue
            content_type = response.headers.get("content-type", "")
            if response.status_code >= 400 or "html" not in content_type.lower():
                continue

            parser = _HomepageParser()
            parser.feed(response.text[:300_000])
            return CompanyEnrichment(
                domain=_domain_from_url(str(response.url)),
                website_url=str(response.url),
                website_title=_clean_whitespace(parser.title) or None,
                website_description=_clean_whitespace(parser.description) or None,
                website_snippet=_meaningful_website_excerpt(parser.visible_text) or None,
            )

    return None


async def _fetch_search_snippets(lead: LeadInput) -> SearchEvidence:
    """Search the open web for what this company is and how big its portfolio is."""

    objective = (
        f"Determine what {lead.company} does, whether it is a residential/multifamily "
        "property management company, and how many apartment units, homes, properties "
        "or communities it manages and in which markets."
    )
    result = await search_web(
        objective=objective,
        queries=[
            lead.company,
            f"{lead.company} apartment units managed",
            f"{lead.company} property management portfolio",
        ],
        mode="fast",
        max_results=5,
        after_date=_lookback_date(COMPANY_SEARCH_LOOKBACK_YEARS),
    )

    missing_data = list(result.warnings)
    snippets = [
        snippet
        for snippet in (
            _snippet_from_hit(
                hit,
                source=COMPANY_SOURCE_LABEL,
                fallback_title=lead.company,
                bonus_terms=[lead.company],
            )
            for hit in result.hits
        )
        if snippet is not None
    ]

    if not snippets and not missing_data:
        missing_data.append("Search returned no usable company snippets.")

    return SearchEvidence(
        snippets=_dedupe_source_snippets(_rank_source_snippets(snippets), limit=5),
        missing_data=missing_data,
        session_id=result.session_id,
    )


async def _fetch_property_search_snippets(
    lead: LeadInput,
    *,
    osm_display_name: str | None = None,
) -> tuple[list[SourceSnippet], list[str]]:
    queries = [
        _keyword_query(query)
        for query in _property_search_queries(lead, osm_display_name=osm_display_name)
    ]
    objective = (
        f"Find pages about the specific property at {lead.address}, {lead.city}, "
        f"{lead.state}. Only pages about that exact property: its number of units, "
        "floor plans, current availability, and leasing information. Ignore pages "
        "about nearby or city-wide apartment listings."
    )
    result = await search_web(
        objective=objective,
        queries=queries,
        mode="basic",
        max_results=5,
        location="us",
    )

    missing_data = list(result.warnings)
    # Keeping the address and any building alias in the window matters twice
    # over: it is the evidence, and it is what the address filter looks for.
    bonus_terms = _address_match_terms(lead, osm_display_name)
    snippets = [
        snippet
        for snippet in (
            _snippet_from_hit(
                hit,
                source=PROPERTY_SOURCE_LABEL,
                fallback_title=lead.address,
                bonus_terms=bonus_terms,
            )
            for hit in result.hits
        )
        if snippet is not None
    ]

    if not snippets:
        if not missing_data:
            missing_data.append("Property search returned no usable snippets.")
        return [], missing_data

    property_aliases = _property_aliases(lead, osm_display_name)
    ranked = _rank_property_source_snippets(
        _dedupe_source_snippets(snippets, limit=10),
        lead=lead,
        property_aliases=property_aliases,
    )
    matching = [
        snippet
        for snippet in ranked
        if _is_usable_property_evidence(
            f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower(),
            lead,
            property_aliases=property_aliases,
        )
    ]
    if not matching and snippets:
        missing_data.append(
            "Property search returned snippets, but none matched the submitted or resolved property."
        )
    return _dedupe_source_snippets(matching, limit=5), missing_data


def _snippet_from_hit(
    hit: WebSearchHit,
    *,
    source: str,
    fallback_title: str,
    bonus_terms: list[str] | None = None,
) -> SourceSnippet | None:
    """Fold one search hit into a single evidence snippet.

    Passages come back as whole-page text, so the snippet is the densest
    400-char window rather than the top of the page, which is usually
    navigation. 400 chars is what the classifiers read.
    """

    text = _hit_snippet_text(hit, bonus_terms=bonus_terms)
    if not text:
        return None
    return SourceSnippet(
        source=source,
        title=hit.title or fallback_title,
        url=hit.url,
        snippet=text,
        publish_date=hit.publish_date,
    )


def _hit_snippet_text(hit: WebSearchHit, *, bonus_terms: list[str] | None = None) -> str:
    if not hit.passages:
        return ""
    longest = max(hit.passages, key=len)
    ordered = [longest, *(passage for passage in hit.passages if passage != longest)]
    return _best_evidence_window(
        _clean_whitespace(" ".join(ordered)),
        bonus_terms=bonus_terms,
    )


def _best_evidence_window(
    text: str,
    *,
    limit: int = 400,
    step: int = 80,
    bonus_terms: list[str] | None = None,
) -> str:
    """Return the ``limit``-char span of ``text`` richest in scoring signal.

    Search providers return page-length text whose first paragraph is often a
    cookie banner or a nav bar, so slicing the head would hand the classifier
    junk. Sliding a window and keeping the densest one puts the unit counts and
    leasing language in front of it instead.
    """

    text = text.strip()
    if len(text) <= limit:
        return text

    best_start = 0
    best_score = -1
    for start in range(0, len(text) - limit + step, step):
        score = _evidence_density(text[start : start + limit], bonus_terms)
        if score > best_score:
            best_score = score
            best_start = start
    if best_score <= 0:
        best_start = 0

    return _snap_to_words(text, best_start, limit)


def _evidence_density(window: str, bonus_terms: list[str] | None) -> int:
    lowered = window.lower()
    score = 3 * len(_unit_count_signals(lowered))
    score += len(_matched_terms(lowered, LEASING_VOLUME_TERMS))
    score += len(_matched_terms(lowered, BUSINESS_TYPE_TERMS))
    score += len(_matched_terms(lowered, RESIDENTIAL_PROPERTY_TERMS))
    score += 3 * sum(1 for term in bonus_terms or [] if term and term.lower() in lowered)
    return score


def _snap_to_words(text: str, start: int, limit: int) -> str:
    if start > 0:
        space = text.find(" ", start)
        start = start + 1 if space == -1 else space + 1
    window = text[start : start + limit]
    if start + limit < len(text):
        head, _, tail = window.rpartition(" ")
        if head and len(tail) < 40:
            window = head
    return window.strip()


def _keyword_query(query: str, *, max_words: int = 8) -> str:
    """Trim a sentence-style query to the keyword form search APIs prefer."""

    words = _clean_whitespace(query).split()
    return " ".join(words[:max_words])[:200].strip()


def _lookback_date(years: int) -> str:
    return (date.today() - timedelta(days=365 * years)).isoformat()


def _property_search_queries(
    lead: LeadInput,
    *,
    osm_display_name: str | None,
) -> list[str]:
    queries = [
        (
            f"{lead.address} {lead.city} {lead.state} "
            "property apartments units floor plans availability leasing"
        )
    ]
    for alias in _property_aliases(lead, osm_display_name):
        queries.append(f"{alias} {lead.city} {lead.state} number of units apartments")
        queries.append(
            f"{alias} {lead.city} {lead.state} apartments units floor plans availability leasing"
        )
        queries.append(
            f"{alias} {lead.address} {lead.city} {lead.state} floor plans availability"
        )
    return _dedupe(queries)[:2]


def _property_aliases(
    lead: LeadInput,
    osm_display_name: str | None,
) -> list[str]:
    aliases: list[str] = []
    building_name = _building_name_token(lead.address)
    if building_name:
        aliases.append(building_name)

    if osm_display_name:
        first_part = osm_display_name.split(",", maxsplit=1)[0].strip()
        normalized_first_part = _normalize_address_token(first_part)
        normalized_address = _normalize_address_token(lead.address)
        if (
            normalized_first_part
            and normalized_first_part not in normalized_address
            and not re.search(r"\b\d+\b", normalized_first_part)
        ):
            aliases.append(first_part)

    return _dedupe([alias for alias in aliases if len(alias.strip()) >= 5])


def _website_url_from_search(snippets: list[SourceSnippet]) -> str | None:
    for snippet in _rank_source_snippets(snippets):
        if not snippet.url:
            continue
        domain = _domain_from_url(snippet.url)
        if domain is None or _is_low_value_website_domain(domain):
            continue
        return snippet.url
    return None


def _website_candidate_urls(
    snippets: list[SourceSnippet],
    *,
    limit: int = MAX_WEBSITE_CANDIDATES,
) -> list[str]:
    """Order the company's own pages worth extracting, best first.

    A homepage is mostly navigation and property listings; the "about" or
    "property management" page is where a company states what it does and how
    many units it runs. So any about-style page found on the company's own
    domain leads, then the bare homepage, then whatever the search ranked first.
    """

    primary = _website_url_from_search(snippets)
    if primary is None:
        return []

    domain = _domain_from_url(primary)
    parsed = urlparse(primary if "://" in primary else f"https://{primary}")
    homepage = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else primary

    same_domain = [
        snippet.url
        for snippet in _rank_source_snippets(snippets)
        if snippet.url and _domain_from_url(snippet.url) == domain
    ]
    about_pages = sorted(
        (url for url in same_domain if _website_path_rank(url) is not None),
        key=lambda url: _website_path_rank(url) or 0,
    )
    return _dedupe([*about_pages, homepage, primary])[:limit]


def _website_path_rank(url: str) -> int | None:
    """Rank a URL by how "about"-ish its path is; ``None`` when it is not."""

    path = urlparse(url if "://" in url else f"https://{url}").path.lower()
    if not path.strip("/"):
        return None
    for index, keyword in enumerate(WEBSITE_PATH_KEYWORDS):
        if keyword in path:
            return index
    return None


def _candidate_website_urls(url: str) -> list[str]:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.netloc:
        return [url if "://" in url else f"https://{url}"]
    return [f"https://{url}", f"https://www.{url}", f"http://{url}"]


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or None


def _is_low_value_website_domain(domain: str) -> bool:
    blocked = {
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "yelp.com",
        "bloomberg.com",
        "crunchbase.com",
        "wikipedia.org",
    }
    return any(domain == item or domain.endswith(f".{item}") for item in blocked)


def _rank_source_snippets(snippets: list[SourceSnippet]) -> list[SourceSnippet]:
    return sorted(snippets, key=_source_priority)


def _rank_property_source_snippets(
    snippets: list[SourceSnippet],
    *,
    lead: LeadInput | None = None,
    property_aliases: list[str] | None = None,
) -> list[SourceSnippet]:
    return sorted(
        snippets,
        key=lambda snippet: _property_source_priority(
            snippet,
            lead=lead,
            property_aliases=property_aliases,
        ),
    )


def _source_priority(snippet: SourceSnippet) -> tuple[int, int, int]:
    text = f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower()
    domain = _domain_from_url(snippet.url)
    recency = _recency_key(snippet)
    if _has_scale_number(text):
        return (0, recency, -len(snippet.snippet))
    if domain and any(domain == item or domain.endswith(f".{item}") for item in ["wikipedia.org", "linkedin.com"]):
        return (1, recency, -len(snippet.snippet))
    if "about" in text or "portfolio" in text or "communities" in text:
        return (2, recency, -len(snippet.snippet))
    return (3, recency, -len(snippet.snippet))


def _recency_key(snippet: SourceSnippet) -> int:
    """Sort newer pages first within a tier; undated pages sort last.

    Portfolio sizes go stale, so between two equally relevant sources the fresher
    one should be the evidence the classifier reads.
    """

    if not snippet.publish_date:
        return 0
    try:
        return -date.fromisoformat(snippet.publish_date[:10]).toordinal()
    except ValueError:
        return 0


def _property_source_priority(
    snippet: SourceSnippet,
    *,
    lead: LeadInput | None = None,
    property_aliases: list[str] | None = None,
) -> tuple[int, int]:
    text = f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower()
    noise_penalty = 5 if _is_nearby_property_noise(text) or _is_neighborhood_listing_page(text) else 0
    exact_bonus = -2 if lead and _mentions_submitted_property(
        text,
        lead,
        property_aliases=property_aliases,
    ) else 0
    property_level_bonus = -1 if lead and _has_strong_property_level_signal(text) else 0
    if any(term in text for term in ["now leasing", "available units", "apartments for rent", "schedule a tour"]):
        return (max(0, 0 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))
    if _has_scale_number(text):
        return (max(0, 1 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))
    if any(term in text for term in ["apartments", "floor plans", "availability", "leasing"]):
        return (max(0, 2 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))
    return (max(0, 3 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))


def _is_usable_property_evidence(
    text: str,
    lead: LeadInput,
    *,
    property_aliases: list[str] | None = None,
) -> bool:
    text = text.lower()
    if _is_nearby_property_noise(text) or _is_neighborhood_listing_page(text):
        return False
    if _contains_different_street_address(text, lead):
        return False
    if _mentions_submitted_property(text, lead, property_aliases=property_aliases):
        return True
    return False


def _mentions_submitted_property(
    text: str,
    lead: LeadInput,
    *,
    property_aliases: list[str] | None = None,
) -> bool:
    if _is_nearby_property_noise(text) or _is_neighborhood_listing_page(text):
        return False
    normalized_address = _normalize_address_token(lead.address)
    normalized_text = _normalize_address_token(text)
    street_number = _house_number(lead.address)
    street_name = _street_name_token(lead.address)
    address_match = bool(normalized_address and normalized_address in normalized_text)
    street_match = bool(street_number and street_name and street_number in text and street_name in normalized_text)
    building_name = _building_name_token(lead.address)
    building_match = bool(building_name and building_name in normalized_text)
    alias_match = any(
        _normalize_address_token(alias) in normalized_text
        for alias in property_aliases or []
        if _normalize_address_token(alias)
    )
    return address_match or street_match or building_match or alias_match


def _normalize_address_token(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"\b(street|st)\b", "st", normalized)
    normalized = re.sub(r"\b(avenue|ave)\b", "ave", normalized)
    normalized = re.sub(r"\b(road|rd)\b", "rd", normalized)
    normalized = re.sub(r"\b(parkway|pkwy)\b", "pkwy", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _street_name_token(address: str) -> str:
    normalized = _normalize_address_token(address)
    parts = normalized.split()
    # The street name starts after the house number, wherever that sits: a
    # unit or suite prefix ("Suite 200, 500 Main St") must not be mistaken
    # for the street.
    house_number = _house_number(address)
    if house_number and house_number in parts:
        parts = parts[parts.index(house_number) + 1 :]
    elif parts and parts[0].isdigit():
        parts = parts[1:]
    stop_tokens = {"new", "york", "ny", "tx", "il", "mi", "al", "ca", "fl", "austin", "plano", "chicago"}
    tokens = [part for part in parts if part not in stop_tokens and not part.isdigit()]
    return " ".join(tokens[:3])


def _building_name_token(address: str) -> str:
    first_part = address.split(",", maxsplit=1)[0].strip()
    normalized = _normalize_address_token(first_part)
    if not normalized or re.search(r"\b\d+\b", normalized):
        return ""
    street_suffixes = {"st", "street", "ave", "avenue", "rd", "road", "pkwy", "parkway", "blvd", "drive", "dr", "way", "lane", "ln"}
    if set(normalized.split()) & street_suffixes:
        return ""
    return normalized if len(normalized) >= 5 else ""


def _is_nearby_property_noise(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "apartments near",
            "apartment near",
            "nearby apartments",
            "nearby rentals",
            "near ",
            "close to",
        ]
    )


def _is_neighborhood_listing_page(text: str) -> bool:
    return bool(
        re.search(
            r"\b(apartments|condos|homes|rentals)\s+"
            r"(?:for\s+rent\s+)?(?:in|near)\s+[^|,]+",
            text,
        )
    ) or bool(
        re.search(
            r"\b\d+\s+(?:apartments|condos|homes|rentals)"
            r"(?:\s+and\s+homes)?\s+for\s+rent\s+in\b",
            text,
        )
    )


def _has_strong_property_level_signal(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "floor plans",
            "floorplans",
            "unit pricing",
            "pricing & floor plans",
            "pricing and availability",
            "square feet",
            "sq ft",
            "sqft",
            "amenities",
            "available units",
            "now leasing",
            "schedule a tour",
            "leasing office",
        ]
    )


_STREET_SUFFIX = r"(?:st|street|ave|avenue|rd|road|pkwy|parkway|blvd|boulevard|drive|dr|way|lane|ln)"
# A street address is a house number followed by a short run of name words and
# a street suffix: "20380 Stevens Creek Blvd". Anything looser (a zip code, a
# phone number, "14 units available" sitting a few words before "Rd") is not.
_STREET_ADDRESS_RE = re.compile(
    rf"\b(\d{{1,6}})\s+(?:[a-z][a-z.'-]*\s+){{1,4}}{_STREET_SUFFIX}\b"
)


def _house_number(address: str) -> str:
    """The street number of an address, or "" when it has none.

    Taken from the address shape rather than the first digits in the string, so
    "Suite 200, 500 Main St" yields "500". Falls back to the first number only
    when no street-address shape is present.
    """

    lowered = address.lower()
    shaped = _STREET_ADDRESS_RE.search(lowered)
    if shaped:
        return shaped.group(1)
    first = re.search(r"\b\d+\b", lowered)
    return first.group(0) if first else ""


def _contains_different_street_address(text: str, lead: LeadInput) -> bool:
    """True when the text names a street address with a different house number.

    Only a real address shape counts. Search excerpts are long enough that a
    zip code, a phone number or "14 units available" will sit near a street
    suffix by accident, and the digits of the submitted number can appear
    inside a larger number, so matching has to be anchored to the address
    pattern itself rather than to any nearby digits.
    """

    submitted_number = _house_number(lead.address)
    if not submitted_number:
        return False
    lowered = text.lower()
    for match in _STREET_ADDRESS_RE.finditer(lowered):
        if match.group(1) != submitted_number:
            return True
    return False


def _address_match_terms(lead: LeadInput, osm_display_name: str | None) -> list[str]:
    """Phrases whose presence marks text as being about the submitted property.

    Used to steer the evidence window toward the part of a page that names the
    building or street, which is also what the address filter looks for. The
    raw address is not usable as-is: its commas and suffix spelling rarely
    match a page verbatim, so this yields "214 barton springs rd",
    "214 barton springs", "214 barton" and the building name instead.
    """

    terms: list[str] = []
    normalized = _normalize_address_token(lead.address)
    street = re.search(r"\b(\d{1,6})\s+([a-z]+(?:\s+[a-z]+){0,3})", normalized)
    if street:
        number = street.group(1)
        words = street.group(2).split()
        for count in range(len(words), 0, -1):
            terms.append(f"{number} {' '.join(words[:count])}")
    building_name = _building_name_token(lead.address)
    if building_name:
        terms.append(building_name)
    terms.extend(_property_aliases(lead, osm_display_name))
    return _dedupe([term for term in terms if len(term) >= 5])


def _has_scale_number(text: str) -> bool:
    return bool(
        re.search(
            r"\b\d{1,3}(?:,\d{3})?\+?\s+"
            r"(?:(?:apartment\s+)?units|homes|properties|communities|apartments)\b",
            text,
        )
    )


def _matched_terms(text: str, terms: set[str]) -> list[str]:
    normalized = text.lower()
    matches = []
    for term in sorted(terms):
        if re.search(rf"\b{re.escape(term)}\b", normalized):
            matches.append(term)
    return matches


def _unit_count_signals(text: str) -> list[str]:
    matches = re.findall(
        r"\b(?:over|more than|approximately|about)?\s*\d{1,3}(?:,\d{3})?\+?\s+"
        r"(?:(?:apartment\s+)?units|apartments|(?:single-family rental\s+)?homes|doors|properties|communities|buildings)\b",
        text.lower(),
    )
    return [_clean_whitespace(match) for match in matches]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_source_snippets(snippets: list[SourceSnippet], *, limit: int) -> list[SourceSnippet]:
    seen = set()
    result: list[SourceSnippet] = []
    for snippet in snippets:
        fingerprint = _clean_whitespace(f"{snippet.title or ''} {snippet.snippet}").lower()[:220]
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(
            SourceSnippet(
                source=snippet.source,
                title=snippet.title,
                url=snippet.url,
                snippet=_truncate(snippet.snippet, 400),
                publish_date=snippet.publish_date,
            )
        )
        if len(result) >= limit:
            break
    return result


def _meaningful_website_excerpt(value: str) -> str:
    text = _clean_whitespace(value)
    if not text:
        return ""
    chunks = re.split(r"(?<=[.!?])\s+|\s{2,}", text)
    keywords = [
        "about",
        "apartment",
        "communities",
        "management",
        "multifamily",
        "portfolio",
        "resident",
        "units",
    ]
    selected = [
        chunk
        for chunk in chunks
        if 40 <= len(chunk) <= 500 and any(keyword in chunk.lower() for keyword in keywords)
    ]
    if not selected:
        return _truncate(text, 700)
    return _truncate(" ".join(selected[:4]), 700)


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3].rstrip()}..."
