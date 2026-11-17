"""Jobs tool: graduate and entry level creative media roles."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher, _strip_html
from fmp_opportunities.core.filter import LLMClassifierHook
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.pipeline import PipelineResult, run_tool_pipeline

logger = logging.getLogger(__name__)

NORTH_WEST_TERMS = (
    "manchester",
    "salford",
    "mediacity",
    "media city",
    "north west",
    "liverpool",
    "lancashire",
    "cheshire",
    "bolton",
    "stockport",
    "preston",
)


def _normalise_uk_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    for fmt in ("%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%a, %d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    if len(cleaned) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned[:10]
    return None


def parse_reed_api(
    source: SourceConfig, _body: str, fetcher: PoliteFetcher
) -> list[Listing]:
    """Fetch and parse listings from the official Reed Jobseeker API."""
    api_key = os.environ.get("REED_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "Skipping Reed API (%s): REED_API_KEY environment variable is not set.",
            source.name,
        )
        return []

    keywords = source.options.get("keywords", "creative media")
    location = source.options.get("locationName", "Manchester")
    distance = source.options.get("distanceFromLocation", 30)
    results_to_take = source.options.get("resultsToTake", 50)

    params = {
        "keywords": keywords,
        "locationName": location,
        "distanceFromLocation": distance,
        "resultsToTake": results_to_take,
    }
    raw_text = fetcher.get_text(
        source.url,
        rate_limit_seconds=source.rate_limit_seconds,
        auth=(api_key, ""),
        params=params,
        check_robots=False,
    )
    data = json.loads(raw_text)
    listings: list[Listing] = []
    for item in data.get("results", []):
        title = str(item.get("jobTitle", "")).strip()
        job_url = str(item.get("jobUrl", "")).strip()
        if not title or not job_url:
            continue
        loc = str(item.get("locationName", "")).strip()
        desc = _strip_html(str(item.get("jobDescription", "")))
        posted = _normalise_uk_date(item.get("date"))
        closing = _normalise_uk_date(item.get("expirationDate"))
        listings.append(
            Listing(
                title=title,
                organisation=str(item.get("employerName", "")).strip(),
                location=loc or "UK",
                remote="remote" in (title + " " + loc + " " + desc).lower(),
                type="job",
                summary=desc[:500],
                posted_date=posted,
                closing_date=closing,
                source_name=source.name,
                source_url=job_url,
            )
        )
    return listings


def parse_adzuna_api(
    source: SourceConfig, _body: str, fetcher: PoliteFetcher
) -> list[Listing]:
    """Fetch and parse listings from the official Adzuna UK API."""
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        logger.warning(
            "Skipping Adzuna API (%s): ADZUNA_APP_ID or ADZUNA_APP_KEY is not set.",
            source.name,
        )
        return []

    params: dict[str, object] = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": source.options.get("results_per_page", 50),
        "where": source.options.get("where", "Manchester"),
        "content-type": "application/json",
    }
    if source.options.get("what_or"):
        params["what_or"] = source.options["what_or"]
    else:
        params["what"] = source.options.get("what", "creative media")
    raw_text = fetcher.get_text(
        source.url,
        rate_limit_seconds=source.rate_limit_seconds,
        params=params,
        check_robots=False,
    )
    data = json.loads(raw_text)
    listings: list[Listing] = []
    for item in data.get("results", []):
        title = str(item.get("title", "")).strip()
        redirect_url = str(item.get("redirect_url", "")).strip()
        if not title or not redirect_url:
            continue
        company = item.get("company", {}) or {}
        loc_obj = item.get("location", {}) or {}
        loc = str(loc_obj.get("display_name", "")).strip()
        desc = _strip_html(str(item.get("description", "")))
        created = str(item.get("created", ""))[:10] or None
        listings.append(
            Listing(
                title=_strip_html(title),
                organisation=str(company.get("display_name", "")).strip(),
                location=loc or "UK",
                remote="remote" in (title + " " + loc + " " + desc).lower(),
                type="job",
                summary=desc[:500],
                posted_date=created,
                source_name=source.name,
                source_url=redirect_url,
            )
        )
    return listings


def parse_creative_access(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Creative Access opportunities HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href^='/job/']"):
        title = link.get_text(" ", strip=True)
        href = link.get("href", "")
        if not title or not href:
            continue
        card = link.find_parent(["article", "div", "li"]) or link.parent
        card_text = card.get_text("\n", strip=True) if card else ""
        lines = [line.strip() for line in card_text.splitlines() if line.strip()]

        org_link = card.select_one("a[href^='/organization/']") if card else None
        organisation = org_link.get_text(" ", strip=True) if org_link else ""

        closing_date = None
        location = "UK"
        remote = False
        for line in lines:
            if line.lower().startswith("expires:"):
                raw_date = line.split(":", 1)[1].strip()
                closing_date = _normalise_uk_date(raw_date)
            elif "remote" in line.lower():
                remote = True
                if location == "UK":
                    location = line
            elif any(uk_loc in line.lower() for uk_loc in ("uk", "manchester", "london", "bristol", "hybrid")):
                location = line

        listings.append(
            Listing(
                title=title,
                organisation=organisation or "Creative Access Employer",
                location=location,
                remote=remote,
                type="job",
                summary=f"Listed on Creative Access. {location}".strip(),
                closing_date=closing_date,
                source_name=source.name,
                source_url=urljoin(source.url, str(href)),
            )
        )

    return listings


def parse_artsjobs(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse ArtsJobs HTML listing page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href^='/jobs/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or not re.match(r"^/jobs/\d+", href):
            continue

        card = link.find_parent(["article", "div", "li"]) or link.parent
        card_text = card.get_text("\n", strip=True) if card else ""
        lines = [line.strip() for line in card_text.splitlines() if line.strip()]

        org_el = card.find(["h3", "h4"]) if card else None
        organisation = org_el.get_text(" ", strip=True) if org_el else ""

        location = "UK"
        closing_date = None
        posted_date = None
        summary_parts: list[str] = []

        for line in lines:
            if line == title or line == organisation:
                continue
            if "published -" in line.lower():
                raw_pub = line.split("-", 1)[1].strip()
                posted_date = _normalise_uk_date(raw_pub)
            elif _normalise_uk_date(line) and closing_date is None:
                closing_date = _normalise_uk_date(line)
            elif any(region in line.lower() for region in ("north west", "manchester", "london", "uk", "england", "remote")):
                location = line
            else:
                summary_parts.append(line)

        listings.append(
            Listing(
                title=title,
                organisation=organisation or "ArtsJobs Employer",
                location=location,
                remote="remote" in (location + " " + " ".join(summary_parts)).lower(),
                type="job",
                summary=" ".join(summary_parts)[:500],
                posted_date=posted_date,
                closing_date=closing_date,
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def normalise_job(listing: Listing) -> Listing:
    """Apply job specific defaults during normalisation."""
    if not listing.type:
        listing.type = "job"
    return listing


def job_sort_key(listing: Listing) -> tuple:
    """Prioritise Manchester and North West, then remote, then newest date."""
    loc_lower = listing.location.lower()
    if any(term in loc_lower for term in NORTH_WEST_TERMS):
        geo_rank = 0
    elif listing.remote:
        geo_rank = 1
    else:
        geo_rank = 2

    date_str = listing.posted_date or listing.first_seen or ""
    # Invert date characters for descending order inside ascending tuple sort
    inv_date = "".join(chr(255 - ord(c)) for c in date_str[:10]) if date_str else "z"
    return (geo_rank, inv_date, listing.title.lower())


def run_jobs(
    sources: list[SourceConfig],
    keywords: KeywordsConfig,
    docs_dir: Path,
    state_path: Path,
    channel_link: str,
    fetcher: Optional[PoliteFetcher] = None,
    llm_hook: Optional[LLMClassifierHook] = None,
    dry_run: bool = False,
) -> PipelineResult:
    """Run the Jobs pipeline end to end."""
    return run_tool_pipeline(
        tool="jobs",
        sources=sources,
        keywords=keywords,
        docs_dir=docs_dir,
        state_path=state_path,
        channel_title="FMP Opportunities: Graduate and Entry Level Jobs",
        channel_link=channel_link,
        channel_description=(
            "Graduate and entry level creative media, digital arts, and creative "
            "technology roles for MMU BA Future Media Production students."
        ),
        fetcher=fetcher,
        normalise_fn=normalise_job,
        sort_key_fn=job_sort_key,
        llm_hook=llm_hook,
        dry_run=dry_run,
    )
