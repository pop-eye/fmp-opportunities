"""Placements tool: sandwich year, graduate schemes, and short term placements."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher
from fmp_opportunities.core.filter import LLMClassifierHook
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.pipeline import PipelineResult, run_tool_pipeline
from fmp_opportunities.tools.jobs import NORTH_WEST_TERMS, _normalise_uk_date

PLACEMENT_TYPES = (
    "sandwich year",
    "graduate scheme or internship (after study)",
    "short term placement (weeks to months)",
)


def classify_placement_type(
    title: str, summary: str, default: str = "short term placement (weeks to months)"
) -> str:
    """Classify a placement into one of the three standard categories."""
    text = f"{title} {summary}".lower()

    sandwich_terms = (
        "sandwich",
        "year in industry",
        "industrial placement",
        "placement year",
        "12 month placement",
        "12-month placement",
        "undergraduate placement",
    )
    if any(term in text for term in sandwich_terms):
        return "sandwich year"

    grad_terms = (
        "graduate scheme",
        "graduate programme",
        "graduate program",
        "traineeship",
        "after study",
        "postgraduate",
        "graduate internship",
    )
    if any(term in text for term in grad_terms):
        return "graduate scheme or internship (after study)"

    short_terms = (
        "internship",
        "summer placement",
        "work experience",
        "short term",
        "weeks",
        "months",
        "trainee",
    )
    if any(term in text for term in short_terms):
        return "short term placement (weeks to months)"

    return default


def detect_paid_status(text: str) -> Optional[str]:
    """Detect whether a placement is stated as paid or unpaid."""
    lower = text.lower()
    if any(term in lower for term in ("unpaid", "voluntary", "expenses only")):
        return "unpaid"
    if re.search(r"£\s*\d+", lower) or any(
        term in lower for term in ("paid", "per hour", "per year", "per annum", "salary", "living wage")
    ):
        return "paid"
    return None


def parse_creative_access_placements(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Creative Access internships and traineeships page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href^='/job/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
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
        pay_text = ""

        for line in lines:
            lower = line.lower()
            if lower.startswith("expires:"):
                closing_date = _normalise_uk_date(line.split(":", 1)[1].strip())
            elif "£" in line or "per hour" in lower or "per year" in lower:
                pay_text = line
            elif "remote" in lower:
                remote = True
                if location == "UK":
                    location = line
            elif any(loc in lower for loc in ("uk", "manchester", "salford", "london", "bristol", "leeds", "hybrid")):
                location = line

        summary = f"Creative Access placement. {location}. {pay_text}".strip()
        listings.append(
            Listing(
                title=title,
                organisation=organisation or "Creative Access Employer",
                location=location,
                remote=remote,
                type=classify_placement_type(title, summary),
                summary=summary[:500],
                closing_date=closing_date,
                paid=detect_paid_status(f"{title} {pay_text} {summary}"),
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def parse_prospects(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Prospects work experience or graduate schemes HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href*='/employer-profiles/'], a[href*='/graduate-jobs/'], a[href*='/jobs/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 4 or not href:
            continue
        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        listings.append(
            Listing(
                title=title,
                organisation="Prospects Employer",
                location="UK",
                remote="remote" in card_text.lower(),
                type=classify_placement_type(title, card_text),
                summary=card_text[:400],
                paid=detect_paid_status(card_text),
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def parse_yini(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Year in Industry (EDT) opportunities page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href]"):
        href = str(link.get("href", ""))
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 12:
            continue
        if title.strip().lower() in {"programmes", "employers", "vacancies", "events", "students", "about"}:
            continue
        lower = f"{title} {href}".lower()
        if not any(k in lower for k in ("placement", "vacancy", "role", "opportunity")):
            continue
        if href.startswith("#") or href.startswith("mailto:"):
            continue

        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        listings.append(
            Listing(
                title=title,
                organisation="Year in Industry (EDT)",
                location="UK",
                remote="remote" in card_text.lower(),
                type="sandwich year",
                summary=card_text[:400],
                paid=detect_paid_status(card_text) or "paid",
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def normalise_placement(listing: Listing) -> Listing:
    """Ensure every placement has one of the three standard placement types."""
    if listing.type not in PLACEMENT_TYPES:
        listing.type = classify_placement_type(listing.title, listing.summary)
    if listing.paid is None:
        listing.paid = detect_paid_status(f"{listing.title} {listing.summary}")
    return listing


def placement_sort_key(listing: Listing) -> tuple:
    """Prioritise Manchester and North West, then closing soonest, then newest."""
    loc_lower = listing.location.lower()
    if any(term in loc_lower for term in NORTH_WEST_TERMS):
        geo_rank = 0
    elif listing.remote:
        geo_rank = 1
    else:
        geo_rank = 2

    closing = listing.closing_date or "9999-12-31"
    return (geo_rank, closing, listing.title.lower())


def run_placements(
    sources: list[SourceConfig],
    keywords: KeywordsConfig,
    docs_dir: Path,
    state_path: Path,
    channel_link: str,
    fetcher: Optional[PoliteFetcher] = None,
    llm_hook: Optional[LLMClassifierHook] = None,
    dry_run: bool = False,
) -> PipelineResult:
    """Run the Placements pipeline end to end."""
    return run_tool_pipeline(
        tool="placements",
        sources=sources,
        keywords=keywords,
        docs_dir=docs_dir,
        state_path=state_path,
        channel_title="FMP Opportunities: Placements and Internships",
        channel_link=channel_link,
        channel_description=(
            "Sandwich year placements, graduate schemes, and short term creative "
            "media internships for MMU BA Future Media Production students."
        ),
        fetcher=fetcher,
        normalise_fn=normalise_placement,
        sort_key_fn=placement_sort_key,
        llm_hook=llm_hook,
        dry_run=dry_run,
    )
