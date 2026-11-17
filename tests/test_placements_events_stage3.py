"""Unit tests for Stage 3: Placements and Events tools."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from icalendar import Calendar

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher, parse_ical_feed
from fmp_opportunities.tools.events import (
    event_sort_key,
    parse_homemcr,
    run_events,
)
from fmp_opportunities.tools.placements import (
    classify_placement_type,
    detect_paid_status,
    parse_creative_access_placements,
    run_placements,
)


class StubFetcher(PoliteFetcher):
    def __init__(self, responses: dict[str, str], tmp_path: Path) -> None:
        super().__init__(cache_dir=tmp_path / "cache", respect_robots=False)
        self._responses = responses

    def get_text(self, url: str, **_kwargs) -> str:
        for key, body in self._responses.items():
            if key in url:
                return body
        raise RuntimeError(f"Unexpected URL in test: {url}")


def test_placement_classification_and_pay_detection() -> None:
    assert (
        classify_placement_type("Creative Technology Year in Industry", "12 month placement")
        == "sandwich year"
    )
    assert (
        classify_placement_type("BBC Graduate Scheme 2027", "Production traineeship")
        == "graduate scheme or internship (after study)"
    )
    assert (
        classify_placement_type("Summer Video Internship", "6 weeks in Manchester")
        == "short term placement (weeks to months)"
    )

    assert detect_paid_status("£24,000 per year") == "paid"
    assert detect_paid_status("Unpaid volunteer opportunity") == "unpaid"
    assert detect_paid_status("Join our studio team") is None


def test_run_placements_end_to_end(tmp_path: Path) -> None:
    html = """
    <div>
      <a href="/job/emerging-creative-48001">Emerging creative</a>
      <a href="/organization/walk-the-plank">Walk the Plank</a>
      <div>Salford, UK</div>
      <div>Expires: 26/11/2026</div>
      <div>£29,215 per year</div>
    </div>
    """
    fetcher = StubFetcher({"creativeaccess.org.uk": html}, tmp_path)
    sources = [
        SourceConfig(
            name="Creative Access Internships",
            type="html",
            url="https://opportunities.creativeaccess.org.uk/jobs/internship-traineeship",
            parser="fmp_opportunities.tools.placements:parse_creative_access_placements",
        )
    ]
    kw = KeywordsConfig(include={"salford": 1.5, "creative": 1.0}, min_score=1.0)
    docs_dir = tmp_path / "docs"
    state_file = tmp_path / "state.json"

    res = run_placements(
        sources=sources,
        keywords=kw,
        docs_dir=docs_dir,
        state_path=state_file,
        channel_link="https://example.github.io/fmp-opportunities/placements.html",
        fetcher=fetcher,
    )
    assert len(res.listings) == 1
    assert res.listings[0].paid == "paid"
    assert res.listings[0].closing_date == "2026-11-26"
    assert (docs_dir / "placements.xml").exists()
    assert (docs_dir / "placements.json").exists()

    data = json.loads((docs_dir / "placements.json").read_text(encoding="utf-8"))
    assert data["count"] == 1


def test_parse_ical_and_run_events_end_to_end(tmp_path: Path) -> None:
    ics_text = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:evt-1@example.com
DTSTART:20261205T183000Z
DTEND:20261205T203000Z
SUMMARY:Manchester Motion Graphics Meetup
LOCATION:Northern Quarter, Manchester
DESCRIPTION:Free networking night and talks for creative technologists.
URL:https://example.com/events/motion-meetup
END:VEVENT
BEGIN:VEVENT
UID:evt-2@example.com
DTSTART:20261125T190000Z
SUMMARY:Student Short Film Screening
LOCATION:HOME Manchester
DESCRIPTION:Free film screening and Q&A.
URL:https://example.com/events/screening
END:VEVENT
END:VCALENDAR
"""
    fetcher = StubFetcher({"example.com/events.ics": ics_text}, tmp_path)
    sources = [
        SourceConfig(
            name="Manchester Events iCal",
            type="ical",
            url="https://example.com/events.ics",
        )
    ]
    kw = KeywordsConfig(
        include={"motion graphics": 2.0, "screening": 2.0, "manchester": 1.0},
        min_score=1.0,
    )
    docs_dir = tmp_path / "docs"
    state_file = tmp_path / "state.json"

    res = run_events(
        sources=sources,
        keywords=kw,
        docs_dir=docs_dir,
        state_path=state_file,
        channel_link="https://example.github.io/fmp-opportunities/events.html",
        fetcher=fetcher,
    )
    assert len(res.listings) == 2
    # Chronological ascending sort puts 2026-11-25 before 2026-12-05
    assert res.listings[0].title == "Student Short Film Screening"
    assert (docs_dir / "events.xml").exists()
    assert (docs_dir / "events.json").exists()
    assert (docs_dir / "events.ics").exists()

    cal = Calendar.from_ical((docs_dir / "events.ics").read_bytes())
    vevents = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(vevents) == 2

    xml_root = ET.parse(docs_dir / "events.xml").getroot()
    assert len(xml_root.findall("./channel/item")) == 2


def test_parse_homemcr_html(tmp_path: Path) -> None:
    html = """
    <article>
      <a href="/event/digital-art-showcase">Digital Art Showcase</a>
      <div>10 Dec 2026</div>
      <div>Free entry</div>
    </article>
    """
    fetcher = StubFetcher({}, tmp_path)
    src = SourceConfig(name="HOME Manchester", type="html", url="https://homemcr.org/whats-on/")
    items = parse_homemcr(src, html, fetcher)
    assert len(items) == 1
    assert items[0].event_start == "2026-12-10"
    assert items[0].cost == "Free"
    assert event_sort_key(items[0])[0] == "2026-12-10"
