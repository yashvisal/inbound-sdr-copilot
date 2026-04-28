import logging
import re
import html
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.models import CompanyEnrichment, LeadInput, SourceSnippet
from app.services.company_classifier import classify_company_signals
from app.services.geocoder import fetch_osm_address_metadata
from app.services.property_classifier import classify_property_signals

logger = logging.getLogger(__name__)

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

    search_snippets, search_missing = await _fetch_search_snippets(lead)
    evidence.extend(search_snippets)
    missing_data.extend(search_missing)

    property_search_snippets, property_search_missing = await _fetch_property_search_snippets(lead)
    evidence.extend(property_search_snippets)
    missing_data.extend(property_search_missing)

    osm_metadata = await fetch_osm_address_metadata(lead.address, lead.city, lead.state)
    if osm_metadata is None:
        missing_data.append("OSM property metadata was unavailable from Nominatim.")

    website_url = _website_url_from_search(search_snippets)
    website = None
    if website_url is None:
        missing_data.append("Company website was not inferred from company-name search results.")
    else:
        website = await _fetch_website_metadata(website_url)
        if website is None:
            missing_data.append(f"Company website metadata was unavailable for {website_url}.")
        else:
            evidence.insert(
                0,
                SourceSnippet(
                    source="Company website",
                    title=website.website_title or website.website_url,
                    url=website.website_url,
                    snippet=website.website_snippet
                    or website.website_description
                    or "Website metadata was fetched.",
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
    classifications, classifier_missing = await classify_company_signals(
        lead=lead,
        website_title=website.website_title if website else None,
        website_description=website.website_description if website else None,
        website_snippet=website.website_snippet if website else None,
        search_snippets=search_snippets,
    )
    if classifications:
        enrichment.classifications = classifications
    if classifier_missing:
        missing_data.append(classifier_missing)

    property_classifications, property_classifier_missing = await classify_property_signals(
        lead=lead,
        search_snippets=property_search_snippets,
    )
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


async def _fetch_search_snippets(lead: LeadInput) -> tuple[list[SourceSnippet], list[str]]:
    settings = get_settings()
    if not settings.serper_api_key:
        return [], ["Serper search skipped because SERPER_API_KEY is not configured."]

    queries = [
        lead.company,
        f"{lead.company} real estate portfolio units",
        f"{lead.company} apartment units manages",
        f"{lead.company} property management portfolio size",
        f"{lead.company} units portfolio",
        f"{lead.company} number of units",
        f"{lead.company} portfolio size",
        f"{lead.company} number of properties",
        f"{lead.company} property management scale",
        f"{lead.company} recent expansion acquisition new development",
    ]
    snippets: list[SourceSnippet] = []
    missing_data: list[str] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for query in queries:
            try:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": settings.serper_api_key,
                        "Content-Type": "application/json",
                        "User-Agent": "inbound-sdr-copilot/0.1",
                    },
                    json={"q": query, "num": 3},
                )
                response.raise_for_status()
            except httpx.HTTPError:
                logger.exception("Serper search failed for query %s", query)
                missing_data.append(f"Search snippets were unavailable for query: {query}")
                continue

            for item in response.json().get("organic", [])[:3]:
                snippet_text = _clean_whitespace(str(item.get("snippet", "")))
                if not snippet_text:
                    continue
                snippets.append(
                    SourceSnippet(
                        source="Serper",
                        title=str(item.get("title") or query),
                        url=str(item.get("link") or ""),
                        snippet=snippet_text,
                    )
                )

    if not snippets and not missing_data:
        missing_data.append("Search returned no usable company snippets.")

    return _dedupe_source_snippets(_rank_source_snippets(snippets), limit=5), missing_data


async def _fetch_property_search_snippets(lead: LeadInput) -> tuple[list[SourceSnippet], list[str]]:
    settings = get_settings()
    if not settings.serper_api_key:
        return [], ["Property search skipped because SERPER_API_KEY is not configured."]

    query = (
        f"{lead.address} {lead.city} {lead.state} "
        "property apartments units floor plans availability leasing"
    )
    snippets: list[SourceSnippet] = []
    missing_data: list[str] = []
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "inbound-sdr-copilot/0.1",
                },
                json={"q": query, "num": 5},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Serper property search failed for query %s", query)
            return [], [f"Property search snippets were unavailable for query: {query}"]

    for item in response.json().get("organic", [])[:5]:
        snippet_text = _clean_whitespace(str(item.get("snippet", "")))
        if not snippet_text:
            continue
        snippets.append(
            SourceSnippet(
                source="Serper Property",
                title=str(item.get("title") or query),
                url=str(item.get("link") or ""),
                snippet=snippet_text,
            )
        )

    if not snippets:
        missing_data.append("Property search returned no usable snippets.")

    ranked = _rank_property_source_snippets(snippets, lead=lead)
    matching = [
        snippet
        for snippet in ranked
        if _is_usable_property_evidence(
            f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower(),
            lead,
        )
    ]
    if not matching and snippets:
        missing_data.append("Property search returned snippets, but none matched the submitted address.")
    return _dedupe_source_snippets(matching, limit=5), missing_data


def _website_url_from_search(snippets: list[SourceSnippet]) -> str | None:
    for snippet in _rank_source_snippets(snippets):
        if not snippet.url:
            continue
        domain = _domain_from_url(snippet.url)
        if domain is None or _is_low_value_website_domain(domain):
            continue
        return snippet.url
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
) -> list[SourceSnippet]:
    return sorted(snippets, key=lambda snippet: _property_source_priority(snippet, lead=lead))


def _source_priority(snippet: SourceSnippet) -> tuple[int, int]:
    text = f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower()
    domain = _domain_from_url(snippet.url)
    if _has_scale_number(text):
        return (0, -len(snippet.snippet))
    if domain and any(domain == item or domain.endswith(f".{item}") for item in ["wikipedia.org", "linkedin.com"]):
        return (1, -len(snippet.snippet))
    if "about" in text or "portfolio" in text or "communities" in text:
        return (2, -len(snippet.snippet))
    return (3, -len(snippet.snippet))


def _property_source_priority(
    snippet: SourceSnippet,
    *,
    lead: LeadInput | None = None,
) -> tuple[int, int]:
    text = f"{snippet.title or ''} {snippet.snippet} {snippet.url or ''}".lower()
    noise_penalty = 5 if _is_nearby_property_noise(text) or _is_neighborhood_listing_page(text) else 0
    exact_bonus = -2 if lead and _mentions_submitted_property(text, lead) else 0
    property_level_bonus = -1 if lead and _has_strong_property_level_signal(text) else 0
    if any(term in text for term in ["now leasing", "available units", "apartments for rent", "schedule a tour"]):
        return (max(0, 0 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))
    if _has_scale_number(text):
        return (max(0, 1 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))
    if any(term in text for term in ["apartments", "floor plans", "availability", "leasing"]):
        return (max(0, 2 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))
    return (max(0, 3 + noise_penalty + exact_bonus + property_level_bonus), -len(snippet.snippet))


def _is_usable_property_evidence(text: str, lead: LeadInput) -> bool:
    if _is_nearby_property_noise(text) or _is_neighborhood_listing_page(text):
        return False
    if _contains_different_street_address(text, lead):
        return False
    if _mentions_submitted_property(text, lead):
        return True
    return False


def _mentions_submitted_property(text: str, lead: LeadInput) -> bool:
    if _is_nearby_property_noise(text) or _is_neighborhood_listing_page(text):
        return False
    normalized_address = _normalize_address_token(lead.address)
    normalized_text = _normalize_address_token(text)
    street_number_match = re.search(r"\b\d+\b", lead.address)
    street_number = street_number_match.group(0) if street_number_match else ""
    street_name = _street_name_token(lead.address)
    address_match = bool(normalized_address and normalized_address in normalized_text)
    street_match = bool(street_number and street_name and street_number in text and street_name in normalized_text)
    building_name = _building_name_token(lead.address)
    building_match = bool(building_name and building_name in normalized_text)
    return address_match or street_match or building_match


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
    if parts and parts[0].isdigit():
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


def _contains_different_street_address(text: str, lead: LeadInput) -> bool:
    submitted_number_match = re.search(r"\b\d+\b", lead.address)
    submitted_number = submitted_number_match.group(0) if submitted_number_match else ""
    if not submitted_number:
        return False
    for number in re.findall(r"\b\d{2,6}\b", text):
        if number == submitted_number:
            continue
        nearby = text[max(0, text.find(number) - 40) : text.find(number) + 80]
        if re.search(r"\b(st|street|ave|avenue|rd|road|pkwy|parkway|blvd|drive|dr|way|lane|ln)\b", nearby):
            return True
    return False


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
            )
        )
        if len(result) >= limit:
            break
    return result


def _clean_whitespace(value: str) -> str:
    normalized = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", normalized)
    replacements = {
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": " ",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return re.sub(r"\s+", " ", normalized).strip()


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
