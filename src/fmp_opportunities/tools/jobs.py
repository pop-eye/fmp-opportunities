"""Jobs tool: graduate and entry level creative media roles."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher, _strip_html, parse_rss_feed
from fmp_opportunities.core.filter import LLMClassifierHook
from fmp_opportunities.core.models import Listing, compute_unique_id
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
        "resultsToTake": results_to_take,
    }
    if location:
        params["locationName"] = location
        params["distanceFromLocation"] = distance
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
        salary_stated = any(
            isinstance(item.get(key), (int, float))
            and not isinstance(item.get(key), bool)
            and item[key] > 0
            for key in ("minimumSalary", "maximumSalary")
        )
        unpaid = re.search(r"\b(?:unpaid|voluntary|expenses only)\b", desc, re.IGNORECASE)
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
                paid="paid" if salary_stated and not unpaid else None,
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


def _creative_access_details(link: Tag) -> tuple[str, str, bool, Optional[str], str]:
    card = link.find_parent(class_="jcl-job-teaser-content")
    if not isinstance(card, Tag):
        card = next(
            (
                parent for parent in link.parents
                if isinstance(parent, Tag)
                and len(parent.select("a[href^='/job/']")) == 1
                and parent.select_one("a[href^='/organization/']")
            ),
            link.parent,
        )
    if not isinstance(card, Tag):
        return "", "", False, None, ""

    org_link = card.select_one("a[href^='/organization/']")
    organisation = org_link.get_text(" ", strip=True) if org_link else ""
    location_node = card.select_one(".jcl-molecules-popover-list__single-item")
    location = location_node.get_text(" ", strip=True) if location_node else ""
    lines = [line.strip() for line in card.get_text("\n", strip=True).splitlines() if line.strip()]
    remote = False
    closing_date = None
    date_node = card.select_one(".jcl-organisms-job-teaser__job-teaser-date")
    if date_node:
        date_match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", date_node.get_text(" ", strip=True))
        closing_date = _normalise_uk_date(date_match.group()) if date_match else None
        if closing_date is None:
            logger.warning("Could not extract closing date for Creative Access listing %r", link.get_text(" ", strip=True))
    pay_text = ""
    for line in lines:
        lower = line.lower()
        expiry = re.match(r"^expires\s*:\s*(.+)$", line, re.IGNORECASE)
        if expiry:
            closing_date = _normalise_uk_date(expiry.group(1))
        elif "£" in line or "per hour" in lower or "per year" in lower:
            pay_text = line
        elif lower == "remote":
            remote = True
            if not location:
                location = line
        elif not location and any(
            loc in lower for loc in ("uk", "manchester", "salford", "london", "bristol", "leeds")
        ) and line != organisation:
            location = line
    return organisation, location, remote, closing_date, pay_text


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
        organisation, location, remote, closing_date, _ = _creative_access_details(link)

        listings.append(
            Listing(
                title=title,
                organisation=organisation,
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


def parse_gamesjobs_feed(
    source: SourceConfig, body: str, fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse gamesJobs RSS descriptions while retaining direct employer links."""
    listings = parse_rss_feed(source, body, fetcher)
    parsed: list[Listing] = []
    for item in listings:
        host = (urlparse(item.source_url).hostname or "").lower()
        if any(host == domain or host.endswith("." + domain) for domain in ("linkedin.com", "indeed.com", "indeed.co.uk")):
            logger.info("Skipping %s: excluded source domain %s", item.title, host)
            continue
        parts = [part.strip() for part in re.split(r"\s+[–—]\s+|\s+·\s+", item.summary)]
        if len(parts) >= 3:
            organisation, location = parts[:2]
            for separator in (" – ", " — "):
                suffix = f"{separator}{organisation}"
                if item.title.endswith(suffix):
                    item.title = item.title[:-len(suffix)]
                    break
            item.organisation = organisation
            item.location = location
            item.remote = "remote" in location.lower()
            item.unique_id = compute_unique_id(item.source_url, item.title, item.organisation)
        else:
            logger.warning("Could not extract employer and location from gamesJobs listing %r", item.title)
            item.organisation = ""
            item.location = ""
            item.unique_id = compute_unique_id(item.source_url, item.title, item.organisation)
        if source.options.get("entry_level_only") and not re.search(
            r"\b(junior|graduate|intern(?:ship)?|placement|trainee|traineeship|apprentice|assistant|entry[ -]level)\b",
            item.title,
            re.IGNORECASE,
        ):
            logger.info("DROP [jobs] %s: no entry level role indicated in the title", item.title)
            continue
        parsed.append(item)
    return parsed


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
            "technology roles for Future Media Production students."
        ),
        fetcher=fetcher,
        normalise_fn=normalise_job,
        sort_key_fn=job_sort_key,
        llm_hook=llm_hook,
        dry_run=dry_run,
    )
