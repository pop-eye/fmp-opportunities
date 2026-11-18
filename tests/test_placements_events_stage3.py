"""Unit tests for Stage 3: Placements and Events tools."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from icalendar import Calendar

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.fetcher import PoliteFetcher, parse_ical_feed
from fmp_opportunities.core.filter import assign_discipline_tags, filter_listings
from fmp_opportunities.core.llm import create_llama_cpp_hook
from fmp_opportunities.core.models import Listing
from fmp_opportunities.tools.events import (
    _extract_event_dates,
    event_sort_key,
    parse_homemcr,
    normalise_event,
    parse_beyond_events,
    parse_rts_events,
    parse_ukie_events,
    run_events,
)
from fmp_opportunities.tools.placements import (
    classify_placement_type,
    detect_paid_status,
    parse_creative_access_placements,
    parse_gamesjobs_placements,
    parse_reed_placements,
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


def test_creative_access_nested_cards_extract_real_details(tmp_path: Path) -> None:
    html = """
    <div class="jcl-job-teaser-content">
      <div class="jcl-job-teaser-title"><a href="/job/trainee">Trainee researcher</a></div>
      <div><a href="/organization/bbc">BBC Studios</a></div>
      <span class="jcl-molecules-popover-list__single-item">Bristol, UK</span>
      <div class="jcl-job-teaser-remote">Hybrid</div>
      <div class="jcl-organisms-job-teaser__job-teaser-date">
        <span>Expires</span><span>Expires</span><span>:</span><time>01/12/2099</time>
      </div><div>£20,441 per year</div>
    </div>
    <div class="jcl-job-teaser-content">
      <div><a href="/job/creative">Emerging creative</a></div>
      <div><a href="/organization/walk">Walk the Plank</a></div>
      <span class="jcl-molecules-popover-list__single-item">Salford, UK</span>
      <div>Expires: 26/11/2099</div><div>£29,215 per year</div>
    </div>
    """
    source = SourceConfig(name="Creative Access", type="html", url="https://opportunities.creativeaccess.org.uk/jobs")
    items = parse_creative_access_placements(source, html, StubFetcher({}, tmp_path))
    assert [(item.organisation, item.location) for item in items] == [
        ("BBC Studios", "Bristol, UK"),
        ("Walk the Plank", "Salford, UK"),
    ]
    assert items[0].closing_date == "2099-12-01"
    assert items[0].paid == "paid"
    assert items[0].remote is False
    assert items[1].closing_date == "2099-11-26"


def test_reed_placements_filter_and_national_search(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REED_API_KEY", "test-key")
    payload = json.dumps({"results": [
        {"jobTitle": "Social Media Internship", "employerName": "Studio", "locationName": "Salford",
         "jobDescription": "Social media campaigns", "jobUrl": "https://example.com/1",
         "minimumSalary": 22000},
        {"jobTitle": "Finance Internship", "employerName": "Finance Co", "locationName": "UK",
         "jobDescription": "Accountancy", "jobUrl": "https://example.com/2"},
        {"jobTitle": "Marketing Manager", "employerName": "Studio", "locationName": "UK",
         "jobDescription": "Marketing", "jobUrl": "https://example.com/3"},
    ]})

    class CapturingFetcher(StubFetcher):
        params: dict = {}

        def get_text(self, url: str, **kwargs) -> str:
            self.params = kwargs["params"]
            return super().get_text(url, **kwargs)

    fetcher = CapturingFetcher({"reed.co.uk": payload}, tmp_path)
    source = SourceConfig(name="Reed", type="api", url="https://www.reed.co.uk/api/1.0/search",
                          options={"keywords": "social media internship", "locationName": ""})
    items = parse_reed_placements(source, "", fetcher)
    assert [item.title for item in items] == ["Social Media Internship"]
    assert items[0].type == "short term placement (weeks to months)"
    assert items[0].paid == "paid"
    assert fetcher.params["keywords"] == "social media internship"
    assert "locationName" not in fetcher.params
    assert "distanceFromLocation" not in fetcher.params


def test_gamesjobs_placements_use_employer_location_and_exclude_other_roles(tmp_path: Path) -> None:
    xml = """<rss><channel>
      <item><title>Creative Production Intern — EA Guildford</title>
        <link>https://jobs.ea.com/job/1</link>
        <description>EA Guildford — Manchester, United Kingdom · Product &amp; Publishing</description></item>
      <item><title>Junior Animator – Studio</title><link>https://example.com/2</link>
        <description>Studio – London – Animation</description></item>
      <item><title>Marketing Internship – Studio</title><link>https://www.linkedin.com/jobs/3</link>
        <description>Studio – London – Marketing</description></item>
    </channel></rss>"""
    source = SourceConfig(name="gamesJobs", type="rss", url="https://gamesjobs.co.uk/feed.xml")
    items = parse_gamesjobs_placements(source, xml, StubFetcher({}, tmp_path))
    assert len(items) == 1
    assert (items[0].title, items[0].organisation, items[0].location) == (
        "Creative Production Intern", "EA Guildford", "Manchester, United Kingdom"
    )
    assert items[0].posted_date is None


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


def test_ukie_event_dates_are_isolated_from_neighbouring_cards(tmp_path: Path) -> None:
    html = """
    <div class="event-grid">
      <a class="post-preview event-preview" href="https://www.eventbrite.co.uk/e/drinks">
        <span class="date">December 9, 2026</span><h3>Festive Drinks</h3>
        <p>Drinks in London.</p>
      </a>
      <a class="post-preview event-preview" href="https://www.eventbrite.co.uk/e/workshop">
        <span class="date">February 3, 2027</span><h3>Pitching Skills Workshop with Jon Torrens</h3>
        <p>Join a half-day workshop.</p>
      </a>
      <a class="post-preview event-preview" href="https://www.eventbrite.co.uk/e/conference">
        <span class="date">February 11, 2027</span><h3>Ukie Conference</h3>
      </a>
    </div>
    """
    source = SourceConfig(name="UKIE", type="html", url="https://ukie.org.uk/events")
    items = parse_ukie_events(source, html, StubFetcher({}, tmp_path))
    assert [item.event_start for item in items] == ["2026-12-09", "2027-02-03", "2027-02-11"]
    assert all(item.event_end is None for item in items)
    assert "Festive Drinks" not in items[1].summary
    assert items[1].location == "UK"


def test_ukie_date_field_distinguishes_event_dates_from_description(tmp_path: Path) -> None:
    html = """
    <div class="event-grid">
      <a href="https://www.eventbrite.co.uk/e/exhibition">
        <span class="date">18 Nov - 20 Dec 2026</span><h3>Games Exhibition</h3>
        <p>Registration opens 1 November 2026.</p>
      </a>
      <a href="https://www.eventbrite.co.uk/e/undated"><h3>Undated Workshop</h3></a>
    </div>
    """
    source = SourceConfig(name="UKIE", type="html", url="https://ukie.org.uk/events")
    items = parse_ukie_events(source, html, StubFetcher({}, tmp_path))
    assert (items[0].event_start, items[0].event_end) == ("2026-11-18", "2026-12-20")
    assert (items[1].event_start, items[1].event_end) == (None, None)


def test_ukie_ambiguous_dates_without_date_field_are_not_guessed(tmp_path: Path, caplog) -> None:
    html = """
    <article>
      <a href="https://www.eventbrite.co.uk/e/workshop"><h3>Pitching Workshop</h3></a>
      Registration opens 1 November 2026. Event on 3 February 2027.
    </article>
    """
    source = SourceConfig(name="UKIE", type="html", url="https://ukie.org.uk/events")
    items = parse_ukie_events(source, html, StubFetcher({}, tmp_path))
    assert (items[0].event_start, items[0].event_end) == (None, None)
    assert "Ambiguous UKIE event dates" in caplog.text


def test_ukie_separate_dates_are_not_treated_as_continuous_range(tmp_path: Path, caplog) -> None:
    html = """
    <a href="https://www.eventbrite.co.uk/e/workshop">
      <span class="date">February 3, 2027 and February 11, 2027</span>
      <h3>Pitching Workshop</h3>
    </a>
    """
    source = SourceConfig(name="UKIE", type="html", url="https://ukie.org.uk/events")
    items = parse_ukie_events(source, html, StubFetcher({}, tmp_path))
    assert (items[0].event_start, items[0].event_end) == (None, None)
    assert "Ambiguous UKIE event dates" in caplog.text


def test_ukie_refresh_replaces_old_incorrect_dates_in_state_and_outputs(tmp_path: Path) -> None:
    url = "https://www.eventbrite.co.uk/e/workshop"
    old = Listing(
        title="Pitching Skills Workshop with Jon Torrens", organisation="UKIE (Games & Interactive)",
        location="London", source_url=url, event_start="2026-12-09", event_end="2027-02-11",
        first_seen="2026-11-17T10:00:00Z", last_seen="2026-11-18T10:00:00Z",
    )
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"events": {"items": {old.unique_id: old.to_dict()}}}), encoding="utf-8")
    html = """
    <div class="event-grid">
      <a href="https://www.eventbrite.co.uk/e/workshop">
        <span class="date">February 3, 2027</span><h3>Pitching Skills Workshop with Jon Torrens</h3>
      </a>
    </div>
    """
    source = SourceConfig(
        name="UKIE", type="html", url="https://ukie.org.uk/events",
        parser="fmp_opportunities.tools.events:parse_ukie_events",
    )
    result = run_events(
        [source], KeywordsConfig(include={"workshop": 1.0}), tmp_path / "docs", state_file,
        "https://example.com/events", fetcher=StubFetcher({"ukie.org.uk": html}, tmp_path),
    )
    assert len(result.listings) == 1
    refreshed = result.listings[0]
    assert (refreshed.event_start, refreshed.event_end) == ("2027-02-03", None)
    assert refreshed.unique_id == old.unique_id
    assert refreshed.first_seen == old.first_seen
    output = json.loads((tmp_path / "docs" / "events.json").read_text(encoding="utf-8"))
    assert (output["items"][0]["event_start"], output["items"][0]["event_end"]) == ("2027-02-03", None)
    cal = Calendar.from_ical((tmp_path / "docs" / "events.ics").read_bytes())
    event = next(component for component in cal.walk() if component.name == "VEVENT")
    assert event.decoded("dtstart").isoformat() == "2027-02-03"
    assert event.get("dtend") is None


def test_parse_beyond_event_cards(tmp_path: Path) -> None:
    html = """
    <ul>
      <li class="events-listing__item">
        <h3 class="event__title"><a class="event__link" href="/events/beyond/123">BEYOND 2026</a></h3>
        <span class="event-meta__date">Mon 23 Nov 2026 12:00 PM - Wed 25 Nov 2026 5:00 PM</span>
        <span class="event-meta__location">Lowry, M50 3AZ</span>
        <a href="/checkout/123">GET TICKETS</a>
      </li>
      <li class="events-listing__item">
        <h3 class="event__title"><a class="event__link" href="/events/beyond/456">BEYOND Online</a></h3>
        <span class="event-meta__date">3 Dec 2026</span>
        <span class="event-meta__location">Online</span>
      </li>
      <li class="events-listing__item">
        <h3 class="event__title"><a class="event__link" href="/events/beyond/789">Summer Festival</a></h3>
        <span class="event-meta__date">Mon 5 Jul 2027 1:00 PM - Mon 5 Jul 2027 3:00 PM</span>
      </li>
      <li class="events-listing__item"><a href="/checkout/789">GET TICKETS</a></li>
    </ul>
    """
    source = SourceConfig(name="BEYOND Conference", type="html",
                          url="https://tickets.beyondconference.org/events/beyond/",
                          parser="fmp_opportunities.tools.events:parse_beyond_events")
    items = parse_beyond_events(source, html, StubFetcher({}, tmp_path))
    assert len(items) == 3
    assert items[0].title == "BEYOND 2026"
    assert items[0].source_url == "https://tickets.beyondconference.org/events/beyond/123"
    assert (items[0].event_start, items[0].event_end) == (
        "2026-11-23T12:00:00+00:00", "2026-11-25T17:00:00+00:00"
    )
    assert items[0].location == "Lowry, M50 3AZ"
    assert items[1].event_start == "2026-12-03"
    assert items[1].remote is True
    assert (items[2].event_start, items[2].event_end) == (
        "2027-07-05T13:00:00+01:00", "2027-07-05T15:00:00+01:00"
    )
    result = run_events(
        [source], KeywordsConfig(include={"conference": 1.0}), tmp_path / "docs",
        tmp_path / "state.json", "https://example.com/events",
        fetcher=StubFetcher({"beyondconference.org": html}, tmp_path),
    )
    assert len(result.listings) == 3
    calendar = Calendar.from_ical((tmp_path / "docs" / "events.ics").read_bytes())
    assert len([item for item in calendar.walk() if item.name == "VEVENT"]) == 3


def test_event_posted_date_is_not_treated_as_event_date() -> None:
    event = Listing(title="Workshop", organisation="Studio", location="Manchester", posted_date="2026-11-10")
    assert normalise_event(event).event_start is None
    assert event_sort_key(event)[0] == "9999-12-31"


def test_extract_event_dates_and_llama_cpp_hook(monkeypatch) -> None:
    start, end = _extract_event_dates("Exhibition runs 18 Nov - 20 Dec 2026 at Aviva Studios")
    assert start == "2026-11-18"
    assert end == "2026-12-20"

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"relevant": true, "type": "sandwich year", "reason": "12 month placement"}'
                        }
                    }
                ]
            }

    captured_prompts: list[str] = []

    def fake_post(_url, **kwargs):
        captured_prompts.append(kwargs["json"]["messages"][0]["content"])
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)
    hook = create_llama_cpp_hook("http://localhost:8080/v1/chat/completions")
    result = hook(
        Listing(title="Creative Tech Placement", organisation="BBC", location="Salford"),
        "placements",
    )
    assert result["relevant"] is True
    assert result["type"] == "sandwich year"
    assert "Today's date is " in captured_prompts[0]
    assert "Closing date:" in captured_prompts[0]
    assert "A missing closing date or event date does not mean" in captured_prompts[0]


@pytest.mark.parametrize("reply", ['{"relevant": "false"}', '{}', '{"relevant": null}'])
def test_invalid_llm_relevance_is_logged_and_uses_keyword_fallback(monkeypatch, caplog, reply: str) -> None:
    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: FakeResp())
    listing = Listing(title="Video Editor", organisation="Studio", location="Manchester")
    kept = filter_listings(
        [listing], KeywordsConfig(include={"video": 1.0}), "jobs", create_llama_cpp_hook()
    )
    assert kept == [listing]
    assert "LLM response must contain a boolean 'relevant' field" in caplog.text


def test_llm_boolean_false_rejects_listing(monkeypatch) -> None:
    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"relevant": false}'}}]}

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: FakeResp())
    listing = Listing(title="Video Editor", organisation="Studio", location="Manchester")
    assert filter_listings(
        [listing], KeywordsConfig(include={"video": 1.0}), "jobs", create_llama_cpp_hook()
    ) == []


def test_discipline_tagging_and_new_event_parsers(tmp_path: Path) -> None:
    item = Listing(
        title="Social Media & Content Marketing Assistant",
        organisation="Northern Agency",
        location="Manchester",
        summary="Create TikTok video campaigns and motion graphics.",
        source_url="https://example.com/smm",
    )
    assign_discipline_tags(item)
    assert "Social Media and Marketing" in item.category_tags
    assert "Video and Film" in item.category_tags
    assert "Motion and Animation" in item.category_tags

    fetcher = StubFetcher({}, tmp_path)
    rts_html = """
    <article>
      <a href="/events/north-west-awards-2026">
        <h3>North West Awards 2026</h3>
        <div>Manchester 20 November 2026</div>
      </a>
    </article>
    """
    rts_items = parse_rts_events(
        SourceConfig(name="RTS", type="html", url="https://rts.org.uk/events"),
        rts_html,
        fetcher,
    )
    assert len(rts_items) == 1
    assert rts_items[0].location == "Manchester"
    assert rts_items[0].event_start == "2026-11-20"

    ukie_html = """
    <div>
      <a href="https://www.eventbrite.co.uk/e/pitching-workshop-123">
        <div>February 3, 2027</div>
        <h3>Pitching Skills Workshop</h3>
      </a>
    </div>
    """
    ukie_items = parse_ukie_events(
        SourceConfig(name="UKIE", type="html", url="https://ukie.org.uk/events"),
        ukie_html,
        fetcher,
    )
    assert len(ukie_items) == 1
    assert ukie_items[0].event_start == "2027-02-03"
