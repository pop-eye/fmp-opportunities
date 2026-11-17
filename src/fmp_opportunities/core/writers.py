"""Output writers for RSS 2.0 XML, iCalendar ICS, and JSON."""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from fmp_opportunities.core.models import Listing, utc_now_iso

UK_TZ = ZoneInfo("Europe/London")
logger = logging.getLogger(__name__)


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 date or datetime string into an aware datetime."""
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        try:
            d = date.fromisoformat(cleaned[:10])
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UK_TZ)
    return dt


def parse_iso_date_or_datetime(value: Optional[str]) -> Optional[date | datetime]:
    """Parse an ISO 8601 string, preserving date only values when no time is present."""
    if not value:
        return None
    cleaned = value.strip()
    if len(cleaned) == 10 and "T" not in cleaned and " " not in cleaned:
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            return None
    return parse_iso_datetime(cleaned)


def _format_rss_description(listing: Listing) -> str:
    parts: list[str] = []
    if listing.organisation:
        parts.append(f"Organisation: {listing.organisation}")
    if listing.location or listing.remote:
        loc = listing.location or "Not specified"
        if listing.remote:
            loc = f"{loc} (Remote)" if listing.location else "Remote"
        parts.append(f"Location: {loc}")
    if listing.type:
        parts.append(f"Type: {listing.type}")
    if listing.category_tags:
        parts.append(f"Disciplines: {', '.join(listing.category_tags)}")
    if listing.paid:
        parts.append(f"Pay: {listing.paid}")
    if listing.event_start:
        parts.append(f"When: {listing.event_start}")
    if listing.cost:
        parts.append(f"Cost: {listing.cost}")
    if listing.closing_date:
        parts.append(f"Closing date: {listing.closing_date}")
    if listing.summary:
        parts.append("")
        parts.append(listing.summary)
    return "\n".join(parts)


def write_rss(
    listings: list[Listing],
    output_path: str | Path,
    channel_title: str,
    channel_link: str,
    channel_description: str,
    build_time: Optional[datetime] = None,
) -> Path:
    """Write listings to a valid RSS 2.0 XML file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    now = build_time or datetime.now(timezone.utc)
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = channel_title
    ET.SubElement(channel, "link").text = channel_link
    ET.SubElement(channel, "description").text = channel_description
    ET.SubElement(channel, "language").text = "en-gb"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(now)

    for listing in listings:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = listing.title
        ET.SubElement(item, "link").text = listing.source_url
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = listing.unique_id

        pub_dt = (
            parse_iso_datetime(listing.posted_date)
            or parse_iso_datetime(listing.first_seen)
            or now
        )
        ET.SubElement(item, "pubDate").text = format_datetime(pub_dt)
        ET.SubElement(item, "description").text = _format_rss_description(listing)

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def write_combined_rss(
    listings_by_tool: dict[str, list[Listing]],
    output_path: str | Path,
    channel_link: str,
    build_time: Optional[datetime] = None,
) -> Path:
    """Combine listings from all tools into a single RSS 2.0 XML feed."""
    combined: list[Listing] = []
    for tool_listings in listings_by_tool.values():
        combined.extend(tool_listings)

    combined.sort(
        key=lambda item: item.posted_date or item.first_seen or "",
        reverse=True,
    )

    return write_rss(
        listings=combined,
        output_path=output_path,
        channel_title="FMP Opportunities (All)",
        channel_link=channel_link,
        channel_description=(
            "Combined jobs, placements, and events for Future Media Production students."
        ),
        build_time=build_time,
    )


def write_ics(
    listings: list[Listing],
    output_path: str | Path,
    calendar_name: str = "FMP Opportunities Events",
    stamp_time: Optional[datetime] = None,
) -> Path:
    """Write event listings to a valid iCalendar (.ics) file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cal = Calendar()
    cal.add("prodid", "-//FMP Opportunities//FMP Opportunities//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", calendar_name)

    dtstamp = stamp_time or datetime.now(timezone.utc)

    for listing in listings:
        start_val = parse_iso_date_or_datetime(listing.event_start)
        if start_val is None:
            logger.warning("Skipping calendar event %r: no valid event start date.", listing.title)
            continue

        event = Event()
        event.add("uid", f"{listing.unique_id}@fmp-opportunities")
        event.add("dtstamp", dtstamp)
        event.add("dtstart", start_val)

        end_val = parse_iso_date_or_datetime(listing.event_end)
        if end_val is not None:
            event.add("dtend", end_val)

        event.add("summary", listing.title)
        if listing.location:
            event.add("location", listing.location)
        if listing.source_url:
            event.add("url", listing.source_url)

        desc_parts = []
        if listing.organisation:
            desc_parts.append(f"Organiser: {listing.organisation}")
        if listing.cost:
            desc_parts.append(f"Cost: {listing.cost}")
        if listing.summary:
            desc_parts.append(listing.summary)
        if listing.source_url:
            desc_parts.append(f"Link: {listing.source_url}")
        if desc_parts:
            event.add("description", "\n".join(desc_parts))

        cal.add_component(event)

    path.write_bytes(cal.to_ical())
    return path


def write_json(
    listings: list[Listing],
    output_path: str | Path,
    tool_name: str,
    updated_at: Optional[str] = None,
) -> Path:
    """Write structured listings to a JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "tool": tool_name,
        "last_updated": updated_at or utc_now_iso(),
        "count": len(listings),
        "items": [item.to_dict() for item in listings],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
