"""Unit tests for Stage 2: Jobs tool end to end, filtering, deduplication, and state."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.dedup import deduplicate_listings
from fmp_opportunities.core.fetcher import PoliteFetcher
from fmp_opportunities.core.filter import filter_listings
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.state import is_suspicious_drop, reconcile_state
from fmp_opportunities.tools.jobs import (
    job_sort_key,
    parse_adzuna_api,
    parse_artsjobs,
    parse_creative_access,
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
