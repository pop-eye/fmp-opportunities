"""Unit tests for Stage 1: data model, config loading, RSS and ICS writers."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest
from icalendar import Calendar

from fmp_opportunities.core.config import (
    ConfigError,
    load_keywords,
    load_sources,
)
from fmp_opportunities.core.models import Listing, compute_unique_id
from fmp_opportunities.core.writers import (
    write_combined_rss,
    write_ics,
    write_json,
    write_rss,
)


def test_listing_unique_id_and_roundtrip() -> None:
    item = Listing(
        title="  Junior Motion Designer ",
        organisation="Northern Lights Studio",
        location="Manchester",
        remote=False,
        type="job",
        category_tags=["motion graphics", "design"],
        summary="Create motion graphics for broadcast.",
        posted_date="2026-11-10",
        closing_date="2026-12-01",
        source_name="Test Board",
        source_url="https://example.com/jobs/123",
    )
    assert item.title == "Junior Motion Designer"
    assert len(item.unique_id) == 16
    assert item.unique_id == compute_unique_id(
        "https://example.com/jobs/123",
        "junior motion designer",
        "northern lights studio",
    )

    restored = Listing.from_dict(item.to_dict())
    assert restored == item


def test_load_sources_valid_and_invalid(tmp_path: Path) -> None:
    sources_file = tmp_path / "sources.yaml"
    sources_file.write_text(
        """
jobs:
  - name: Sample RSS
    type: rss
    url: https://example.com/feed.xml
    enabled: true
  - name: Sample HTML
    type: html
    url: https://example.com/jobs
    enabled: false
    selectors:
      item: .job-card
      title: h2
placements: []
events: []
""",
        encoding="utf-8",
    )
    loaded = load_sources(sources_file)
    assert len(loaded["jobs"]) == 2
    assert loaded["jobs"][0].type == "rss"
    assert loaded["jobs"][1].enabled is False
    assert loaded["jobs"][1].selectors["item"] == ".job-card"

    bad_file = tmp_path / "bad_sources.yaml"
    bad_file.write_text(
        """
jobs:
  - name: Broken Source
    type: ftp
    url: ftp://example.com/file
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_sources(bad_file)


def test_load_keywords_merges_global_and_tool(tmp_path: Path) -> None:
    kw_file = tmp_path / "keywords.yaml"
    kw_file.write_text(
        """
global:
  min_score: 1.0
  include:
    video production: 2.0
  exclude:
    - senior
placements:
  min_score: 1.5
  include:
    sandwich year: 3.0
  exclude:
    - unpaid volunteer
""",
        encoding="utf-8",
    )
    kw = load_keywords(kw_file, tool="placements")
    assert kw.min_score == 1.5
    assert kw.include["video production"] == 2.0
    assert kw.include["sandwich year"] == 3.0
    assert "senior" in kw.exclude
    assert "unpaid volunteer" in kw.exclude


def test_write_rss_and_combined_rss(tmp_path: Path) -> None:
    job = Listing(
        title="Junior Video Editor",
        organisation="Salford Media",
        location="Salford",
        remote=True,
        type="job",
        summary="Edit short form documentaries.",
        posted_date="2026-11-12T09:00:00Z",
        closing_date="2026-11-30",
        source_name="Sample Board",
        source_url="https://example.com/jobs/1",
    )
    event = Listing(
        title="Manchester Creative Tech Night",
        organisation="MMU Digital",
        location="Manchester",
        type="event",
        summary="Talks and networking.",
        posted_date="2026-11-15T18:00:00Z",
        event_start="2026-11-25T18:30:00+00:00",
        cost="Free",
        source_name="Events Feed",
        source_url="https://example.com/events/1",
    )

    rss_path = tmp_path / "jobs.xml"
    fixed_now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    write_rss(
        listings=[job],
        output_path=rss_path,
        channel_title="FMP Jobs",
        channel_link="https://example.com/jobs.html",
        channel_description="Graduate and entry level jobs.",
        build_time=fixed_now,
    )

    tree = ET.parse(rss_path)
    root = tree.getroot()
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    items = root.findall("./channel/item")
    assert len(items) == 1
    assert items[0].findtext("title") == "Junior Video Editor"
    assert items[0].findtext("link") == "https://example.com/jobs/1"
    assert items[0].findtext("guid") == job.unique_id
    desc = items[0].findtext("description") or ""
    assert "Organisation: Salford Media" in desc
    assert "Location: Salford (Remote)" in desc
    assert "Closing date: 2026-11-30" in desc

    all_path = tmp_path / "all.xml"
    write_combined_rss(
        {"jobs": [job], "events": [event]},
        output_path=all_path,
        channel_link="https://example.com/index.html",
        build_time=fixed_now,
    )
    all_tree = ET.parse(all_path)
    all_items = all_tree.findall("./channel/item")
    assert len(all_items) == 2
    assert all_items[0].findtext("title") == "Manchester Creative Tech Night"


def test_write_ics_valid_vevent(tmp_path: Path) -> None:
    event = Listing(
        title="Northern Film Screening",
        organisation="HOME Manchester",
        location="2 Tony Wilson Place, Manchester",
        type="event",
        summary="Student short film showcase.",
        event_start="2026-11-28T19:00:00+00:00",
        event_end="2026-11-28T21:00:00+00:00",
        cost="Free",
        source_name="HOME",
        source_url="https://example.com/events/screening",
    )

    ics_path = tmp_path / "events.ics"
    write_ics([event], ics_path)

    cal = Calendar.from_ical(ics_path.read_bytes())
    assert str(cal.get("version")) == "2.0"
    vevents = [comp for comp in cal.walk() if comp.name == "VEVENT"]
    assert len(vevents) == 1
    vevent = vevents[0]
    assert str(vevent.get("summary")) == "Northern Film Screening"
    assert str(vevent.get("location")) == "2 Tony Wilson Place, Manchester"
    assert str(vevent.get("url")) == "https://example.com/events/screening"
    assert str(vevent.get("uid")) == f"{event.unique_id}@fmp-opportunities"
    assert "Cost: Free" in str(vevent.get("description"))


def test_write_json(tmp_path: Path) -> None:
    job = Listing(
        title="UX Designer",
        organisation="Studio North",
        location="Manchester",
        source_url="https://example.com/ux",
    )
    json_path = tmp_path / "jobs.json"
    write_json([job], json_path, tool_name="jobs", updated_at="2026-11-17T12:00:00Z")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["tool"] == "jobs"
    assert data["last_updated"] == "2026-11-17T12:00:00Z"
    assert data["count"] == 1
    assert data["items"][0]["title"] == "UX Designer"
