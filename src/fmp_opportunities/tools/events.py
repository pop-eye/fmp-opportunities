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


_DATE_PATTERN = re.compile(r"\b(\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{4})?)\b")
_FULL_DATE_PATTERN = re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b")


def _extract_event_dates(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract start and optional end ISO dates from event text."""
    full_dates = _FULL_DATE_PATTERN.findall(text)
    if len(full_dates) >= 2:
        return _normalise_uk_date(full_dates[0]), _normalise_uk_date(full_dates[-1])
    if len(full_dates) == 1:
        end_iso = _normalise_uk_date(full_dates[0])
        # Check for range like "18 Nov - 20 Dec 2026" where start lacks year
        year = end_iso[:4] if end_iso else ""
        all_parts = _DATE_PATTERN.findall(text)
        if len(all_parts) >= 2 and year:
            first_part = all_parts[0]
            if not re.search(r"\d{4}", first_part):
                start_iso = _normalise_uk_date(f"{first_part} {year}")
                if start_iso:
                    return start_iso, end_iso
        return end_iso, None
    return None, None


def _is_utility_event_link(title: str, href: str) -> bool:
    lower_title = title.strip().lower()
    lower_href = href.strip().lower()
    if lower_title in {"add event", "book now", "read more", "find out more", "all events", "what's on", "whats on"}:
        return True
    if any(seg in lower_href for seg in ("/members-area/", "/create", "/login", "/register")):
        return True
    return False


def parse_homemcr(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse HOME Manchester Whats On HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href*='/event/'], a[href*='/film/'], a[href*='/whats-on/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 4 or href.rstrip("/") == "/whats-on" or _is_utility_event_link(title, href):
            continue

        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        event_start, event_end = _extract_event_dates(card_text)

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
                event_end=event_end,
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
        if not title or len(title) < 4 or href.rstrip("/") == "/whats-on" or _is_utility_event_link(title, href):
            continue

        card = link.find_parent(["article", "li"]) or link.find_parent("div") or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        event_start, event_end = _extract_event_dates(card_text)

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
                event_end=event_end,
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
        if not title or len(title) < 4 or href.rstrip("/") == "/events" or _is_utility_event_link(title, href):
            continue

        card = link.find_parent(["article", "li"]) or link.find_parent("div") or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        event_start, event_end = _extract_event_dates(card_text)

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
                event_end=event_end,
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
