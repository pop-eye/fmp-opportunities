"""Events tool: industry talks, festivals, screenings, workshops, and open calls."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher
from fmp_opportunities.core.filter import LLMClassifierHook
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.pipeline import PipelineResult, run_tool_pipeline
from fmp_opportunities.tools.jobs import _normalise_uk_date

logger = logging.getLogger(__name__)


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
_US_DATE_PATTERN = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})\b")


def _normalise_any_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    us_match = _US_DATE_PATTERN.search(raw)
    if us_match:
        reordered = f"{us_match.group(2)} {us_match.group(1)} {us_match.group(3)}"
        parsed = _normalise_uk_date(reordered)
        if parsed:
            return parsed
    return _normalise_uk_date(raw)


def _extract_event_dates(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract start and optional end ISO dates from event text."""
    full_dates = _FULL_DATE_PATTERN.findall(text)
    if len(full_dates) >= 2:
        return _normalise_uk_date(full_dates[0]), _normalise_uk_date(full_dates[-1])
    if len(full_dates) == 1:
        end_iso = _normalise_uk_date(full_dates[0])
        year = end_iso[:4] if end_iso else ""
        all_parts = _DATE_PATTERN.findall(text)
        if len(all_parts) >= 2 and year:
            first_part = all_parts[0]
            if not re.search(r"\d{4}", first_part):
                start_iso = _normalise_uk_date(f"{first_part} {year}")
                if start_iso:
                    return start_iso, end_iso
        return end_iso, None

    us_dates = _US_DATE_PATTERN.findall(text)
    if len(us_dates) >= 2:
        first = _normalise_uk_date(f"{us_dates[0][1]} {us_dates[0][0]} {us_dates[0][2]}")
        last = _normalise_uk_date(f"{us_dates[-1][1]} {us_dates[-1][0]} {us_dates[-1][2]}")
        return first, last
    if len(us_dates) == 1:
        first = _normalise_uk_date(f"{us_dates[0][1]} {us_dates[0][0]} {us_dates[0][2]}")
        return first, None
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
    source: SourceConfig, body: str, fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Factory International / Aviva Studios Whats On HTML page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []
    seen_urls: set[str] = set()

    for link in soup.select("a[href*='/whats-on/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 4 or href.rstrip("/") == "/whats-on" or _is_utility_event_link(title, href):
            continue

        full_url = urljoin(source.url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        card = link.find_parent(["article", "li"]) or link.find_parent("div") or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        event_start, event_end = _extract_event_dates(card_text)
        cost = _detect_cost(card_text)

        if event_start is None and source.options.get("fetch_details", True):
            try:
                detail_body = fetcher.get_text(
                    full_url, rate_limit_seconds=source.rate_limit_seconds
                )
                detail_soup = BeautifulSoup(detail_body, "html.parser")
                detail_text = detail_soup.get_text(" ", strip=True)
                event_start, event_end = _extract_event_dates(detail_text[:3000])
                if cost is None:
                    cost = _detect_cost(detail_text[:3000])
            except Exception:
                pass

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
                cost=cost,
                source_name=source.name,
                source_url=full_url,
            )
        )

    return listings


def _beyond_datetime(date: Optional[str], text: str, last: bool = False) -> Optional[str]:
    if not date:
        return None
    pattern = r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\b"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    for match in reversed(matches) if last else matches:
        if _normalise_uk_date(match.group(1)) != date:
            continue
        try:
            time = datetime.strptime(match.group(2).upper(), "%I:%M %p").time()
        except ValueError:
            continue
        return datetime.fromisoformat(date).replace(
            hour=time.hour, minute=time.minute, tzinfo=ZoneInfo("Europe/London")
        ).isoformat()
    return date


def parse_beyond_events(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse BEYOND's public Ticket Tailor event listing."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []
    for card in soup.select("li.events-listing__item"):
        link = card.select_one("h3.event__title a.event__link[href]")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", "")).strip()
        if not title or not href:
            continue
        date_element = card.select_one(".event-meta__date")
        date_text = date_element.get_text(" ", strip=True) if date_element else ""
        event_start, event_end = _extract_event_dates(date_text)
        event_start = _beyond_datetime(event_start, date_text)
        event_end = _beyond_datetime(event_end, date_text, last=True)
        location_element = card.select_one(".event-meta__location")
        location = location_element.get_text(" ", strip=True) if location_element else ""
        listings.append(
            Listing(
                title=title,
                organisation="BEYOND Conference",
                location=location or "Not stated",
                remote="online" in location.lower(),
                type="event",
                summary="Creative industry events from BEYOND Conference.",
                event_start=event_start,
                event_end=event_end,
                source_name=source.name,
                source_url=urljoin(source.url, href),
            )
        )
    return listings


def parse_rts_events(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Royal Television Society events page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("a[href^='/events/']"):
        href = str(link.get("href", ""))
        if href.rstrip("/") == "/events":
            continue
        heading = link.find(["h2", "h3", "h4"])
        title = heading.get_text(" ", strip=True) if heading else link.get_text(" ", strip=True)
        if not title or len(title) < 4 or _is_utility_event_link(title, href):
            continue

        card = link.find_parent(["article", "li", "div"]) or link
        card_text = card.get_text(" ", strip=True)
        event_start, event_end = _extract_event_dates(card_text)

        location = "UK"
        for loc in ("Manchester", "North West", "Salford", "London", "Birmingham", "Bristol", "Online"):
            if loc.lower() in card_text.lower():
                location = loc
                break

        listings.append(
            Listing(
                title=title,
                organisation="Royal Television Society",
                location=location,
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


def parse_creative_uk_events(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse Creative UK public events page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for link in soup.select("h3 a[href], a[href*='eventbrite.co.uk/e/']"):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 6 or _is_utility_event_link(title, href):
            continue

        card = link.find_parent(["article", "li", "div"]) or link.parent
        card_text = card.get_text(" ", strip=True) if card else ""
        event_start, event_end = _extract_event_dates(card_text)

        listings.append(
            Listing(
                title=title,
                organisation="Creative UK",
                location="Online / UK" if "webinar" in card_text.lower() or "online" in card_text.lower() else "UK",
                remote="webinar" in card_text.lower() or "online" in card_text.lower(),
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


def parse_ukie_events(
    source: SourceConfig, body: str, _fetcher: PoliteFetcher
) -> list[Listing]:
    """Parse UKIE games and interactive media events page."""
    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []
    link_selector = "a[href*='eventbrite.co.uk/e/'], a[href*='/events/']"

    for link in soup.select(link_selector):
        href = str(link.get("href", ""))
        heading = link.find(["h2", "h3", "h4"])
        title = heading.get_text(" ", strip=True) if heading else link.get_text(" ", strip=True)
        if not title or len(title) < 6 or _is_utility_event_link(title, href):
            continue

        card = link
        if not link.select_one(".date, time"):
            parent = link.find_parent(["article", "li", "div"])
            if parent and len(parent.select(link_selector)) == 1 and len(parent.select("h2, h3, h4")) <= 1:
                card = parent
        card_text = card.get_text(" ", strip=True)
        date_element = card.select_one(".date, time")
        date_text = date_element.get_text(" ", strip=True) if date_element else card_text
        event_start, event_end = _extract_event_dates(date_text)
        has_range = bool(re.search(r"\s+(?:to|until|through)\s+|\s*[-\u2013\u2014]\s*", date_text, re.I))
        if event_end and (not date_element or not has_range):
            logger.warning("Ambiguous UKIE event dates for '%s'; leaving the date unstated", title)
            event_start, event_end = None, None

        listings.append(
            Listing(
                title=title,
                organisation="UKIE (Games & Interactive)",
                location="London" if "london" in card_text.lower() else "UK",
                remote="online" in card_text.lower() or "webinar" in card_text.lower(),
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
    return listing


def event_sort_key(listing: Listing) -> tuple:
    """Sort upcoming events chronologically by start date ascending."""
    start = listing.event_start or "9999-12-31"
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
            "calls for Future Media Production students."
        ),
        fetcher=fetcher,
        normalise_fn=normalise_event,
        sort_key_fn=event_sort_key,
        llm_hook=llm_hook,
        dry_run=dry_run,
        write_calendar=True,
    )
