"""Events tool: industry talks, festivals, screenings, workshops, and open calls."""

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
from fmp_opportunities.tools.jobs import _normalise_uk_date


def _detect_cost(text: str) -> Optional[str]:
    lower = text.lower()
    if "free" in lower:
        return "Free"
    match = re.search(r"£\s*\d+(?:\.\d{2})?", text)
    if match:
        return match.group(0).replace(" ", "")
    return None


def parse_homemcr(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse HOME Manchester Whats On HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href*='/event/'], a[href*='/film/'], a[href*='/whats-on/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 4 or href.rstrip("/") == "/whats-on":
            continue

        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        date_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", card_text)
        event_start = _normalise_uk_date(date_match.group(0)) if date_match else None

        listings.append(
            Listing(
                title=title,
                organisation="HOME Manchester",
                location="Manchester",
                remote=False,
                type="event",
                summary=card_text[:400],
                posted_date=event_start,
                event_start=event_start,
                cost=_detect_cost(card_text),
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def parse_factory_international(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Factory International / Aviva Studios Whats On HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href*='/whats-on/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 4 or href.rstrip("/") == "/whats-on":
            continue

        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        date_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", card_text)
        event_start = _normalise_uk_date(date_match.group(0)) if date_match else None

        listings.append(
            Listing(
                title=title,
                organisation="Factory International (Aviva Studios)",
                location="Manchester",
                remote=False,
                type="event",
                summary=card_text[:400],
                posted_date=event_start,
                event_start=event_start,
                cost=_detect_cost(card_text),
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def parse_manchester_digital(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Manchester Digital events HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href*='/events/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 4 or href.rstrip("/") == "/events":
            continue

        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        date_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", card_text)
        event_start = _normalise_uk_date(date_match.group(0)) if date_match else None

        listings.append(
            Listing(
                title=title,
                organisation="Manchester Digital",
                location="Manchester",
                remote="online" in card_text.lower(),
                type="event",
                summary=card_text[:400],
                posted_date=event_start,
                event_start=event_start,
                cost=_detect_cost(card_text),
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )

    return listings


def normalise_event(listing: Listing) -> Listing:
    """Apply event defaults during normalisation."""
    if not listing.type:
        listing.type = "event"
    if not listing.event_start and listing.posted_date:
        listing.event_start = listing.posted_date
    return listing


def event_sort_key(listing: Listing) -> tuple:
    """Sort upcoming events chronologically by start date ascending."""
    start = listing.event_start or listing.posted_date or "9999-12-31"
    return (start, listing.title.lower())


def run_events(
    sources: list[SourceConfig],
    keywords: KeywordsConfig,
    docs_dir: Path,
    state_path: Path,
    channel_link: str,
    fetcher: Optional[PoliteFetcher] = None,
    llm_hook: Optional[LLMClassifierHook] = None,
    dry_run: bool = False,
) -> PipelineResult:
    """Run the Events pipeline end to end, including .ics calendar output."""
    return run_tool_pipeline(
        tool="events",
        sources=sources,
        keywords=keywords,
        docs_dir=docs_dir,
        state_path=state_path,
        channel_title="FMP Opportunities: Creative and Digital Events",
        channel_link=channel_link,
        channel_description=(
            "Upcoming industry talks, festivals, screenings, workshops, and open "
            "calls for MMU BA Future Media Production students."
        ),
        fetcher=fetcher,
        normalise_fn=normalise_event,
        sort_key_fn=event_sort_key,
        llm_hook=llm_hook,
        dry_run=dry_run,
        write_calendar=True,
    )
