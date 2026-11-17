"""Deduplication by normalised title plus organisation and by URL."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fmp_opportunities.core.models import Listing

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}


def normalise_key_text(value: str) -> str:
    """Normalise text for duplicate comparison."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", value.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def canonicalise_url(url: str) -> str:
    """Normalise a URL by stripping trailing slashes and tracking parameters."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(query_pairs),
            "",
        )
    )


def deduplicate_listings(listings: list[Listing]) -> list[Listing]:
    """Remove duplicates by canonical URL and by normalised title plus organisation."""
    seen_urls: set[str] = set()
    seen_title_org: set[tuple[str, str]] = set()
    unique: list[Listing] = []

    for item in listings:
        canon_url = canonicalise_url(item.source_url)
        title_org = (
            normalise_key_text(item.title),
            normalise_key_text(item.organisation),
        )

        if canon_url and canon_url in seen_urls:
            continue
        if title_org[0] and title_org in seen_title_org:
            continue

        if canon_url:
            seen_urls.add(canon_url)
        if title_org[0]:
            seen_title_org.add(title_org)
        unique.append(item)

    return unique
