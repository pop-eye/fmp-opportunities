"""Tests for apprenticeship sources and feed integration."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fmp_opportunities.core.config import SourceConfig, load_keywords, load_sources
from fmp_opportunities.core.fetcher import PoliteFetcher
from fmp_opportunities.core.models import Listing
from fmp_opportunities.core.pipeline import PipelineResult
from fmp_opportunities.tools.apprenticeships import (
    parse_dfe_apprenticeships,
    parse_gamesjobs_apprenticeships,
    parse_reed_apprenticeships,
    run_apprenticeships,
)


class StubFetcher(PoliteFetcher):
    def __init__(self, tmp_path: Path, responses: list[dict]) -> None:
        super().__init__(cache_dir=tmp_path / "cache", respect_robots=False)
        self.responses = responses
        self.calls: list[dict] = []

    def get_text(self, _url: str, **kwargs) -> str:
        self.calls.append(kwargs)
        return json.dumps(self.responses[len(self.calls) - 1])


def test_official_api_paginates_and_maps_vacancies(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DFE_APPRENTICESHIPS_API_KEY", "test-key")
    fetcher = StubFetcher(tmp_path, [
        {"totalPages": 2, "vacancies": [{
            "title": "Content Creator", "description": "Create video and social media",
            "employerName": "Studio", "vacancyUrl": "https://example.com/vacancy/1",
            "course": {"title": "Content creator (level 3)", "level": 3},
            "addresses": [{"addressLine3": "Manchester", "postcode": "M1 1AA"},
                          {"addressLine3": "Liverpool", "postcode": "L1 1AA"}],
            "wage": {"wageType": "Custom"}, "closingDate": "2099-12-01T23:59:59Z",
        }]},
        {"totalPages": 2, "vacancies": [{
            "title": "Digital Media Apprentice", "vacancyUrl": "https://example.com/vacancy/2",
            "isNationalVacancy": True, "course": {"title": "Digital media", "level": 6},
        }]},
    ])
    source = SourceConfig(name="DfE", type="api", url="https://example.com/vacancy",
                          options={"routes": ["Creative and design", "Digital"]})
    items = parse_dfe_apprenticeships(source, "", fetcher)
    assert len(items) == 2
    assert [call["params"]["PageNumber"] for call in fetcher.calls] == [1, 2]
    assert fetcher.calls[0]["params"]["Routes"] == ["Creative and design", "Digital"]
    assert fetcher.calls[0]["headers"] == {"Ocp-Apim-Subscription-Key": "test-key", "X-Version": "2"}
    assert items[0].location == "Multiple locations: Manchester, M1 1AA; Liverpool, L1 1AA"
    assert (items[0].type, items[0].paid, items[0].closing_date) == ("apprenticeship", "paid", "2099-12-01")
    assert [item.apprenticeship_level for item in items] == [3, 6]
    assert items[1].location == "National (see listing)"
    assert items[1].paid is None


def test_official_api_surfaces_invalid_response_and_page_limit(monkeypatch, tmp_path: Path, caplog) -> None:
    monkeypatch.setenv("DFE_APPRENTICESHIPS_API_KEY", "test-key")
    source = SourceConfig(name="DfE", type="api", url="https://example.com/vacancy",
                          options={"max_pages": 1})
    with pytest.raises(ValueError, match="vacancies list"):
        parse_dfe_apprenticeships(source, "", StubFetcher(tmp_path, [{"error": "bad response"}]))
    parse_dfe_apprenticeships(source, "", StubFetcher(tmp_path, [{"vacancies": [], "totalPages": 2}]))
    assert "results may be incomplete" in caplog.text


def test_official_api_without_key_is_skipped_with_warning(monkeypatch, tmp_path: Path, caplog) -> None:
    monkeypatch.delenv("DFE_APPRENTICESHIPS_API_KEY", raising=False)
    fetcher = StubFetcher(tmp_path, [])
    source = SourceConfig(name="DfE", type="api", url="https://example.com/vacancy")
    assert parse_dfe_apprenticeships(source, "", fetcher) == []
    assert fetcher.calls == []
    assert "DFE_APPRENTICESHIPS_API_KEY is not set" in caplog.text


def test_games_feed_only_keeps_apprentice_titles(tmp_path: Path) -> None:
    source = SourceConfig(name="gamesJobs", type="rss", url="https://gamesjobs.co.uk/feed.xml")
    body = """<rss><channel>
      <item><title>Apprentice Games Artist — Studio</title><link>https://example.com/1</link>
        <description>Studio — Manchester · Animation</description></item>
      <item><title>Game Designer — Studio</title><link>https://example.com/2</link>
        <description>Studio — London · Design</description></item>
      <item><title>Apprentice Animator — Studio</title><link>https://www.linkedin.com/jobs/3</link>
        <description>Studio — London · Animation</description></item>
    </channel></rss>"""
    items = parse_gamesjobs_apprenticeships(source, body, StubFetcher(tmp_path, []))
    assert [item.title for item in items] == ["Apprentice Games Artist"]
    assert items[0].organisation == "Studio"


def test_reed_apprenticeships_require_apprenticeship_title(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REED_API_KEY", "test-key")
    fetcher = StubFetcher(tmp_path, [{"results": [
        {"jobTitle": "Level 4 Video Production Apprentice", "jobUrl": "https://example.com/1",
         "jobDescription": "Film and video production", "locationName": "Manchester"},
        {"jobTitle": "Media Apprentice", "jobUrl": "https://example.com/3",
         "jobDescription": "Requires level 2 English", "locationName": "Manchester"},
        {"jobTitle": "Video Editor", "jobUrl": "https://example.com/2",
         "jobDescription": "Help supervise our apprentices", "locationName": "Manchester"},
    ]}])
    source = SourceConfig(name="Reed", type="api", url="https://example.com/search",
                          options={"keywords": "video apprentice", "locationName": ""})
    items = parse_reed_apprenticeships(source, "", fetcher)
    assert [item.title for item in items] == ["Level 4 Video Production Apprentice", "Media Apprentice"]
    assert [item.apprenticeship_level for item in items] == [4, None]
    assert "locationName" not in fetcher.calls[0]["params"]


def test_apprenticeships_feed_filters_irrelevant_and_writes_outputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DFE_APPRENTICESHIPS_API_KEY", "test-key")
    fetcher = StubFetcher(tmp_path, [{"totalPages": 1, "vacancies": [
        {"title": "Content Creator", "vacancyUrl": "https://example.com/creative",
         "course": {"title": "Content creator (level 3)"}, "description": "Create posts"},
        {"title": "Digital Learning Designer Apprentice", "vacancyUrl": "https://example.com/learning",
         "course": {"title": "Digital learning designer", "level": 5}, "description": "Design learning"},
        {"title": "Video Apprentice", "vacancyUrl": "https://example.com/video",
         "course": {"title": "Video", "level": True}, "description": "Video editing"},
        {"title": "Electrical Apprentice", "vacancyUrl": "https://example.com/electrical",
         "course": {"title": "Electrician"}, "description": "Electrical installation"},
    ]}])
    source = SourceConfig(name="DfE", type="api", url="https://example.com/vacancy",
                          parser="fmp_opportunities.tools.apprenticeships:parse_dfe_apprenticeships")
    result = run_apprenticeships(
        [source], load_keywords("keywords.yaml", "apprenticeships"), tmp_path / "docs",
        tmp_path / "state.json", "https://example.com/apprenticeships", fetcher=fetcher,
    )
    assert [item.title for item in result.listings] == [
        "Digital Learning Designer Apprentice", "Video Apprentice", "Content Creator",
    ]
    data = json.loads((tmp_path / "docs" / "apprenticeships.json").read_text(encoding="utf-8"))
    assert data["items"][0]["type"] == "apprenticeship"
    assert [item["apprenticeship_level"] for item in data["items"]] == [5, None, 3]
    feed = ET.parse(tmp_path / "docs" / "apprenticeships.xml")
    assert feed.find("./channel/item/title").text == "Digital Learning Designer Apprentice"
    assert "Apprenticeship level: 5" in feed.find("./channel/item/description").text
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert Listing.from_dict(next(iter(state["apprenticeships"]["items"].values()))).apprenticeship_level == 5
    assert "apprenticeships" in load_sources("sources.yaml")


def test_single_tool_run_keeps_other_feeds_in_combined_rss(monkeypatch, tmp_path: Path) -> None:
    import run

    docs = tmp_path / "docs"
    docs.mkdir()
    existing = Listing(title="Video Editor", organisation="Studio", location="Manchester",
                       source_url="https://example.com/job")
    (docs / "jobs.json").write_text(json.dumps({"items": [existing.to_dict()]}), encoding="utf-8")
    apprenticeship = Listing(title="Content Apprentice", organisation="Studio", location="Manchester",
                             source_url="https://example.com/apprenticeship", type="apprenticeship")
    monkeypatch.setattr(run, "load_dotenv_if_present", lambda: None)
    monkeypatch.setattr(run, "setup_logging", lambda **kwargs: None)
    monkeypatch.setattr(run, "run_apprenticeships", lambda **kwargs: PipelineResult(
        tool="apprenticeships", listings=[apprenticeship]
    ))
    result = run.main([
        "--tool", "apprenticeships", "--no-push", "--docs-dir", str(docs),
        "--state-file", str(tmp_path / "state.json"), "--log-dir", str(tmp_path / "logs"),
    ])
    assert result == 0
    titles = {item.findtext("title") for item in ET.parse(docs / "all.xml").findall("./channel/item")}
    assert titles == {"Video Editor", "Content Apprentice"}
