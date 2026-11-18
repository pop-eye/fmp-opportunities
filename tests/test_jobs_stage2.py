"""Unit tests for Stage 2: Jobs tool end to end, filtering, deduplication, and state."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig, load_keywords
from fmp_opportunities.core.dedup import deduplicate_listings
from fmp_opportunities.core.fetcher import PoliteFetcher
from fmp_opportunities.core.filter import filter_listings
from fmp_opportunities.core.models import Listing, utc_now_iso
from fmp_opportunities.core.state import is_suspicious_drop, reconcile_state
from fmp_opportunities.tools.jobs import (
    job_sort_key,
    parse_adzuna_api,
    parse_artsjobs,
    parse_creative_access,
    parse_gamesjobs_feed,
    parse_reed_api,
    run_jobs,
)


class StubFetcher(PoliteFetcher):
    """In memory fetcher stub for deterministic unit tests."""

    def __init__(self, responses: dict[str, str], tmp_path: Path) -> None:
        super().__init__(cache_dir=tmp_path / "cache", respect_robots=False)
        self._responses = responses

    def get_text(self, url: str, **_kwargs) -> str:
        for key, body in self._responses.items():
            if key in url:
                return body
        raise RuntimeError(f"Unexpected URL in test: {url}")


def test_parse_reed_and_adzuna_api(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REED_API_KEY", "test-reed-key")
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")

    reed_payload = json.dumps(
        {
            "results": [
                {
                    "jobTitle": "Junior Video Producer",
                    "employerName": "Dock10",
                    "locationName": "Salford",
                    "jobDescription": "<p>Entry level video production role.</p>",
                    "jobUrl": "https://www.reed.co.uk/jobs/123",
                    "date": "10/11/2026",
                    "expirationDate": "30/11/2026",
                }
            ]
        }
    )
    adzuna_payload = json.dumps(
        {
            "results": [
                {
                    "title": "Graduate Motion Designer",
                    "company": {"display_name": "Manchester Studio"},
                    "location": {"display_name": "Manchester"},
                    "description": "Motion graphics and animation.",
                    "redirect_url": "https://www.adzuna.co.uk/jobs/456",
                    "created": "2026-11-12T10:00:00Z",
                }
            ]
        }
    )

    fetcher = StubFetcher(
        {"reed.co.uk": reed_payload, "adzuna.com": adzuna_payload},
        tmp_path,
    )
    reed_src = SourceConfig(name="Reed API", type="api", url="https://www.reed.co.uk/api/1.0/search")
    adzuna_src = SourceConfig(name="Adzuna API", type="api", url="https://api.adzuna.com/v1/api/jobs/gb/search/1")

    reed_items = parse_reed_api(reed_src, "", fetcher)
    adzuna_items = parse_adzuna_api(adzuna_src, "", fetcher)

    assert len(reed_items) == 1
    assert reed_items[0].organisation == "Dock10"
    assert reed_items[0].closing_date == "2026-11-30"

    assert len(adzuna_items) == 1
    assert adzuna_items[0].location == "Manchester"
    assert adzuna_items[0].posted_date == "2026-11-12"


def test_parse_creative_access_and_artsjobs(tmp_path: Path) -> None:
    ca_html = """
    <div class="job-card">
      <a href="/job/junior-video-producer-48000">Junior video producer</a>
      <a href="/organization/bbc">BBC Studios</a>
      <div>Manchester, UK</div>
      <div>Remote</div>
      <div>Expires: 30/11/2026</div>
    </div>
    """
    aj_html = """
    <article class="job-row">
      <h2><a href="/jobs/87578">Digital Content Assistant</a></h2>
      <h3>HOME Manchester</h3>
      <div>North West</div>
      <div>26 Nov 2026</div>
      <div>published - 17 Nov 2026</div>
      <div>Support creative digital campaigns.</div>
    </article>
    """
    fetcher = StubFetcher({}, tmp_path)

    ca_items = parse_creative_access(
        SourceConfig(name="Creative Access", type="html", url="https://opportunities.creativeaccess.org.uk/jobs/united-kingdom"),
        ca_html,
        fetcher,
    )
    assert len(ca_items) == 1
    assert ca_items[0].title == "Junior video producer"
    assert ca_items[0].organisation == "BBC Studios"
    assert ca_items[0].remote is True
    assert ca_items[0].closing_date == "2026-11-30"

    aj_items = parse_artsjobs(
        SourceConfig(name="ArtsJobs", type="html", url="https://www.artsjobs.org.uk/jobs"),
        aj_html,
        fetcher,
    )
    assert len(aj_items) == 1
    assert aj_items[0].organisation == "HOME Manchester"
    assert aj_items[0].location == "North West"
    assert aj_items[0].posted_date == "2026-11-17"


def test_gamesjobs_entry_level_filter(tmp_path: Path) -> None:
    xml = """<rss><channel>
      <item><title>Junior Animator — Studio</title><link>https://example.com/1</link>
        <description>Studio — Manchester · Animation</description></item>
      <item><title>Animator — Studio</title><link>https://example.com/2</link>
        <description>Studio — Manchester · Animation</description></item>
    </channel></rss>"""
    source = SourceConfig(name="gamesJobs", type="rss", url="https://gamesjobs.co.uk/feed.xml",
                          options={"entry_level_only": True})
    items = parse_gamesjobs_feed(source, xml, StubFetcher({}, tmp_path))
    assert [item.title for item in items] == ["Junior Animator"]
    assert items[0].organisation == "Studio"


def test_filter_dedup_and_sort() -> None:
    kw = KeywordsConfig(
        include={"video production": 2.0, "manchester": 1.5, "junior": 1.0},
        exclude=["senior"],
        min_score=1.5,
    )
    items = [
        Listing(
            title="Senior Video Producer",
            organisation="Big Agency",
            location="Manchester",
            summary="Video production lead.",
            source_url="https://example.com/1",
        ),
        Listing(
            title="Junior Video Production Assistant",
            organisation="Media Co",
            location="London",
            remote=False,
            summary="Entry level video production.",
            source_url="https://example.com/2?utm_source=feed",
        ),
        Listing(
            title="Junior Video Production Assistant",
            organisation="Media Co",
            location="London",
            summary="Duplicate via different URL.",
            source_url="https://otherboard.com/2",
        ),
        Listing(
            title="Junior Content Creator",
            organisation="North Studio",
            location="Manchester",
            summary="Video production in Manchester.",
            source_url="https://example.com/3",
        ),
    ]

    filtered = filter_listings(items, kw, tool="jobs")
    assert len(filtered) == 3

    deduped = deduplicate_listings(filtered)
    assert len(deduped) == 2

    deduped.sort(key=job_sort_key)
    assert deduped[0].location == "Manchester"


def test_job_relevance_requires_actual_role_evidence() -> None:
    keywords = load_keywords("keywords.yaml", tool="jobs")
    items = [
        Listing(title="Qualified Joiner", organisation="Creative Support", location="Manchester",
                summary="Property maintenance across the North West."),
        Listing(title="Digital Counsellor", organisation="The Portfolio Group", location="Manchester",
                summary="Qualified counsellor providing health and wellbeing support."),
        Listing(title="Customer Service Support Rep", organisation="Dream Digital", location="Manchester",
                summary="Customer support representative."),
        Listing(title="Social Media Assistant", organisation="Studio", location="Manchester",
                summary="Create campaigns for social media."),
        Listing(title="Trainee Researcher", organisation="BBC Studios", location="Bristol",
                summary="Listed on Creative Access."),
        Listing(title="Video Editor", organisation="Studio", location="London",
                summary="Edit video programmes."),
        Listing(title="Editorial assistant", organisation="Publisher", location="London",
                summary="Listed on Creative Access."),
        Listing(title="UX Designer", organisation="Studio", location="Manchester",
                summary="Design user experiences."),
        Listing(title="Junior Animator", organisation="Games Studio", location="Manchester",
                summary="Animation for games."),
    ]
    kept = filter_listings(items, keywords, "jobs")
    assert [item.title for item in kept] == [
        "Social Media Assistant", "Trainee Researcher", "Video Editor",
        "Editorial assistant", "UX Designer", "Junior Animator",
    ]


@pytest.mark.parametrize("rejection", ["keywords", "llm"])
def test_observed_rejected_job_is_not_restored_from_state(tmp_path: Path, rejection: str) -> None:
    now = utc_now_iso()
    good = Listing(title="Junior Video Editor", organisation="Studio", location="Manchester",
                   source_url="https://example.com/good", first_seen=now, last_seen=now)
    rejected = Listing(title="Qualified Joiner", organisation="Creative Support", location="Manchester",
                       source_url="https://example.com/bad", first_seen=now, last_seen=now)
    unseen = Listing(title="Junior Camera Assistant", organisation="Another Studio", location="Manchester",
                     source_url="https://example.com/unseen", source_name="Failed Board",
                     first_seen=now, last_seen=now)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"jobs": {"items": {
        item.unique_id: item.to_dict() for item in (good, rejected, unseen)
    }}}), encoding="utf-8")
    feed = """<rss><channel>
      <item><title>Junior Video Editor</title><link>https://example.com/good</link>
        <description>Video production</description></item>
      <item><title>Qualified Joiner</title><link>https://example.com/bad</link>
        <description>Property maintenance</description></item>
    </channel></rss>"""
    source = SourceConfig(name="Test", type="rss", url="https://example.com/feed.xml",
                          options={"default_location": "Manchester"})
    failed_source = SourceConfig(name="Failed Board", type="rss", url="https://example.com/failed.xml")
    keywords = KeywordsConfig(
        include={"manchester": 1.5}, min_score=1.0,
        required_any=["video"] if rejection == "keywords" else [],
    )
    hook = (lambda item, _: {"relevant": item.title != "Qualified Joiner"}) if rejection == "llm" else None
    result = run_jobs([source, failed_source], keywords, tmp_path / "docs", state_file, "https://example.com/jobs",
                      fetcher=StubFetcher({"feed.xml": feed}, tmp_path),
                      llm_hook=hook)
    assert {item.title for item in result.listings} == {"Junior Video Editor", "Junior Camera Assistant"}
    assert result.removed_count == 1
    assert result.failed_sources == ["Failed Board"]


def test_suspicious_drop_keeps_previous_outputs_even_if_rejected(tmp_path: Path) -> None:
    now = utc_now_iso()
    previous = [
        Listing(title=f"Old role {index}", organisation="Studio", location="Manchester",
                source_url=f"https://example.com/{index}", first_seen=now, last_seen=now)
        for index in range(4)
    ]
    state_file = tmp_path / "state.json"
    original_state = json.dumps({"jobs": {"items": {item.unique_id: item.to_dict() for item in previous}}})
    state_file.write_text(original_state, encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    output = docs_dir / "jobs.json"
    output.write_text("previous output", encoding="utf-8")
    feed = """<rss><channel>
      <item><title>Old role 0</title><link>https://example.com/0</link><description>Property maintenance</description></item>
      <item><title>Video Editor</title><link>https://example.com/new</link><description>Video</description></item>
    </channel></rss>"""
    source = SourceConfig(name="Test", type="rss", url="https://example.com/feed.xml",
                          options={"default_location": "Manchester"})
    keywords = KeywordsConfig(include={"manchester": 1.5}, required_any=["video"])
    result = run_jobs([source], keywords, docs_dir, state_file, "https://example.com/jobs",
                      fetcher=StubFetcher({"feed.xml": feed}, tmp_path))
    assert result.kept_previous_due_to_drop is True
    assert output.read_text(encoding="utf-8") == "previous output"
    assert state_file.read_text(encoding="utf-8") == original_state


def test_state_reconcile_expiry_and_suspicious_drop() -> None:
    fresh = [
        Listing(
            title="Junior Motion Designer",
            organisation="Studio A",
            location="Manchester",
            closing_date="2026-12-10",
            source_url="https://example.com/a",
        ),
        Listing(
            title="Expired Role",
            organisation="Studio B",
            location="Manchester",
            closing_date="2026-11-01",
            source_url="https://example.com/b",
        ),
    ]
    merged, stats = reconcile_state(
        tool="jobs",
        fresh_listings=fresh,
        state={},
        now_iso="2026-11-17T12:00:00Z",
    )
    assert len(merged) == 1
    assert merged[0].is_new is True
    assert stats["added_count"] == 2

    assert is_suspicious_drop(previous_count=10, fresh_count=3) is True
    assert is_suspicious_drop(previous_count=10, fresh_count=5) is False
    assert is_suspicious_drop(previous_count=10, fresh_count=6) is False


def test_refreshed_expired_listing_does_not_restore_old_state() -> None:
    previous = Listing(
        title="Video placement",
        organisation="Studio",
        location="Manchester",
        source_url="https://example.com/placement",
        first_seen="2026-11-10T12:00:00Z",
        last_seen="2026-11-16T12:00:00Z",
    )
    refreshed = Listing.from_dict(previous.to_dict())
    refreshed.closing_date = "2026-11-16"
    state = {"jobs": {"items": {previous.unique_id: previous.to_dict()}}}
    result, stats = reconcile_state("jobs", [refreshed], state, now_iso="2026-11-17T12:00:00Z")
    assert result == []
    assert stats["removed_count"] == 1


def test_refreshed_employer_preserves_saved_id_and_does_not_duplicate() -> None:
    previous = Listing(
        title="Trainee researcher", organisation="Creative Access Employer",
        location="UK", source_url="https://example.com/job/1",
        first_seen="2026-11-10T12:00:00Z", last_seen="2026-11-16T12:00:00Z",
    )
    refreshed = Listing(
        title="Trainee researcher", organisation="BBC Studios",
        location="Bristol", source_url="https://example.com/job/1",
        closing_date="2026-12-01",
    )
    state = {"placements": {"items": {previous.unique_id: previous.to_dict()}}}
    result, stats = reconcile_state("placements", [refreshed], state, now_iso="2026-11-17T12:00:00Z")
    assert len(result) == 1
    assert result[0].organisation == "BBC Studios"
    assert result[0].unique_id == previous.unique_id
    assert result[0].first_seen == previous.first_seen
    assert stats["added_count"] == 0
    refreshed.closing_date = "2026-11-16"
    expired, _ = reconcile_state("placements", [refreshed], state, now_iso="2026-11-17T12:00:00Z")
    assert expired == []


def test_run_jobs_end_to_end(tmp_path: Path) -> None:
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Creative Board</title>
        <item>
          <title>Junior Motion Graphics Designer</title>
          <link>https://example.com/jobs/motion-1</link>
          <description>Motion graphics and video production in Manchester.</description>
          <pubDate>Tue, 17 Nov 2026 09:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    fetcher = StubFetcher({"example.com/feed.xml": rss_xml}, tmp_path)
    sources = [
        SourceConfig(
            name="Example RSS",
            type="rss",
            url="https://example.com/feed.xml",
            options={"default_location": "Manchester"},
        )
    ]
    kw = KeywordsConfig(include={"motion graphics": 2.0, "manchester": 1.0}, min_score=1.5)

    docs_dir = tmp_path / "docs"
    state_file = tmp_path / "state.json"

    res = run_jobs(
        sources=sources,
        keywords=kw,
        docs_dir=docs_dir,
        state_path=state_file,
        channel_link="https://example.github.io/fmp-opportunities/jobs.html",
        fetcher=fetcher,
    )
    assert len(res.listings) == 1
    assert (docs_dir / "jobs.xml").exists()
    assert (docs_dir / "jobs.json").exists()

    json_data = json.loads((docs_dir / "jobs.json").read_text(encoding="utf-8"))
    assert json_data["count"] == 1
    assert json_data["items"][0]["is_new"] is True

    xml_root = ET.parse(docs_dir / "jobs.xml").getroot()
    assert len(xml_root.findall("./channel/item")) == 1
