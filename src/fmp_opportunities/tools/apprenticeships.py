"""Creative and digital apprenticeships."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher, _strip_html
from fmp_opportunities.core.filter import LLMClassifierHook
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.pipeline import PipelineResult, run_tool_pipeline
from fmp_opportunities.tools.jobs import parse_gamesjobs_feed, parse_reed_api
from fmp_opportunities.tools.placements import detect_paid_status, placement_sort_key

logger = logging.getLogger(__name__)


def _apprenticeship_candidates(listings: list[Listing]) -> list[Listing]:
    candidates = []
    for item in listings:
        if not re.search(r"\bapprentice(?:ship)?s?\b", item.title, re.IGNORECASE):
            logger.info("DROP [apprenticeships] %s: title does not identify an apprenticeship", item.title)
            continue
        item.type = "apprenticeship"
        candidates.append(item)
    return candidates


def parse_reed_apprenticeships(source: SourceConfig, body: str, fetcher: PoliteFetcher) -> list[Listing]:
    return _apprenticeship_candidates(parse_reed_api(source, body, fetcher))


def parse_gamesjobs_apprenticeships(source: SourceConfig, body: str, fetcher: PoliteFetcher) -> list[Listing]:
    return _apprenticeship_candidates(parse_gamesjobs_feed(source, body, fetcher))


def parse_dfe_apprenticeships(source: SourceConfig, _body: str, fetcher: PoliteFetcher) -> list[Listing]:
    """Fetch live vacancies from the official Display Advert API v2."""
    api_key = os.environ.get("DFE_APPRENTICESHIPS_API_KEY", "").strip()
    if not api_key:
        logger.warning("Skipping %s: DFE_APPRENTICESHIPS_API_KEY is not set", source.name)
        return []

    max_pages = int(source.options.get("max_pages", 50))
    if max_pages < 1:
        raise ValueError(f"{source.name}: max_pages must be at least 1")
    params = {
        "Routes": source.options.get("routes", ["Creative and design", "Digital"]),
        "PageSize": source.options.get("page_size", 100),
        "Sort": "AgeDesc",
    }
    listings: list[Listing] = []
    for page in range(1, max_pages + 1):
        response = fetcher.get_text(
            source.url,
            rate_limit_seconds=source.rate_limit_seconds,
            params={**params, "PageNumber": page},
            headers={"Ocp-Apim-Subscription-Key": api_key, "X-Version": "2"},
            check_robots=False,
        )
        data = json.loads(response)
        if not isinstance(data, dict) or not isinstance(data.get("vacancies"), list):
            raise ValueError(f"{source.name}: response has no vacancies list")
        total_pages = data.get("totalPages")
        if not isinstance(total_pages, int) or isinstance(total_pages, bool) or total_pages < 0:
            raise ValueError(f"{source.name}: response has no valid totalPages")
        for vacancy in data["vacancies"]:
            if not isinstance(vacancy, dict):
                raise ValueError(f"{source.name}: invalid vacancy entry")
            title = str(vacancy.get("title") or "").strip()
            url = str(vacancy.get("vacancyUrl") or vacancy.get("applicationUrl") or "").strip()
            if not title or not url:
                logger.warning("Skipping %s vacancy without title or URL", source.name)
                continue
            addresses = vacancy.get("addresses") or []
            if not isinstance(addresses, list) or not all(isinstance(address, dict) for address in addresses):
                raise ValueError(f"{source.name}: invalid vacancy addresses")
            locations = [
                ", ".join(str(address.get(key) or "").strip() for key in
                          ("addressLine1", "addressLine2", "addressLine3", "addressLine4", "postcode")
                          if address.get(key))
                for address in addresses
            ]
            locations = list(dict.fromkeys(location for location in locations if location))
            if vacancy.get("isNationalVacancy"):
                location = "National (see listing)"
            elif len(locations) > 1:
                location = "Multiple locations: " + "; ".join(locations)
            else:
                location = locations[0] if locations else "Not stated"
            course = vacancy.get("course") or {}
            if not isinstance(course, dict):
                raise ValueError(f"{source.name}: invalid vacancy course")
            course_title = str(course.get("title") or "").strip()
            description = _strip_html(str(vacancy.get("description") or ""))
            summary = " ".join(part for part in (course_title, description) if part)
            wage = vacancy.get("wage") or {}
            if not isinstance(wage, dict):
                raise ValueError(f"{source.name}: invalid vacancy wage")
            listings.append(Listing(
                title=title,
                organisation=str(vacancy.get("employerName") or "").strip(),
                location=location,
                type="apprenticeship",
                summary=summary[:500],
                posted_date=str(vacancy.get("postedDate") or "")[:10] or None,
                closing_date=str(vacancy.get("closingDate") or "")[:10] or None,
                paid="paid" if wage.get("wageType") else None,
                source_name=source.name,
                source_url=url,
            ))
        if page >= total_pages:
            break
    else:
        logger.warning("%s: stopped at the configured limit of %d pages; results may be incomplete", source.name, max_pages)
    return listings


def normalise_apprenticeship(listing: Listing) -> Listing:
    listing.type = "apprenticeship"
    if listing.paid is None:
        listing.paid = detect_paid_status(f"{listing.title} {listing.summary}")
    return listing


def run_apprenticeships(
    sources: list[SourceConfig],
    keywords: KeywordsConfig,
    docs_dir: Path,
    state_path: Path,
    channel_link: str,
    fetcher: Optional[PoliteFetcher] = None,
    llm_hook: Optional[LLMClassifierHook] = None,
    dry_run: bool = False,
) -> PipelineResult:
    return run_tool_pipeline(
        tool="apprenticeships",
        sources=sources,
        keywords=keywords,
        docs_dir=docs_dir,
        state_path=state_path,
        channel_title="FMP Opportunities: Apprenticeships",
        channel_link=channel_link,
        channel_description="Creative and digital apprenticeships for Future Media Production students.",
        fetcher=fetcher,
        normalise_fn=normalise_apprenticeship,
        sort_key_fn=placement_sort_key,
        llm_hook=llm_hook,
        dry_run=dry_run,
    )
