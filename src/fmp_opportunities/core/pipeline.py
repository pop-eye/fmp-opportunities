"""Shared execution pipeline for jobs, placements, and events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from fmp_opportunities.core.config import KeywordsConfig, SourceConfig
from fmp_opportunities.core.dedup import deduplicate_listings
from fmp_opportunities.core.fetcher import PoliteFetcher, fetch_source_listings
from fmp_opportunities.core.filter import (
    LLMClassifierHook,
    assign_discipline_tags,
    filter_listings,
)
from fmp_opportunities.core.models import Listing, utc_now_iso
from fmp_opportunities.core.state import (
    is_suspicious_drop,
    load_state,
    reconcile_state,
    save_state,
)
from fmp_opportunities.core.writers import write_ics, write_json, write_rss

logger = logging.getLogger(__name__)

SortKeyFunc = Callable[[Listing], tuple]
NormaliseFunc = Callable[[Listing], Listing]


@dataclass
class PipelineResult:
    """Summary of running one tool's pipeline."""

    tool: str
    listings: list[Listing] = field(default_factory=list)
    failed_sources: list[str] = field(default_factory=list)
    added_count: int = 0
    removed_count: int = 0
    kept_previous_due_to_drop: bool = False


def run_tool_pipeline(
    tool: str,
    sources: list[SourceConfig],
    keywords: KeywordsConfig,
    docs_dir: Path,
    state_path: Path,
    channel_title: str,
    channel_link: str,
    channel_description: str,
    fetcher: Optional[PoliteFetcher] = None,
    normalise_fn: Optional[NormaliseFunc] = None,
    sort_key_fn: Optional[SortKeyFunc] = None,
    llm_hook: Optional[LLMClassifierHook] = None,
    dry_run: bool = False,
    write_calendar: bool = False,
) -> PipelineResult:
    """Execute the full fetch, filter, deduplicate, state, and output pipeline."""
    active_fetcher = fetcher or PoliteFetcher()
    raw_listings: list[Listing] = []
    failed_sources: list[str] = []

    for source in sources:
        if not source.enabled:
            logger.info("Skipping disabled source: %s", source.name)
            continue
        try:
            items = fetch_source_listings(source, active_fetcher)
            logger.info("Fetched %d raw items from %s", len(items), source.name)
            raw_listings.extend(items)
        except Exception as exc:
            logger.error("Source '%s' failed: %s", source.name, exc)
            failed_sources.append(source.name)

    normalised = [
        assign_discipline_tags(normalise_fn(item) if normalise_fn else item)
        for item in raw_listings
    ]
    filtered = filter_listings(normalised, keywords=keywords, tool=tool, llm_hook=llm_hook)
    deduped = deduplicate_listings(filtered)

    state = load_state(state_path)
    prev_count = len(state.get(tool, {}).get("items", {}))

    if is_suspicious_drop(prev_count, len(deduped)) and prev_count > 0:
        logger.warning(
            "Suspicious drop for %s: fresh count %d is under half of previous %d. "
            "Keeping previous outputs.",
            tool,
            len(deduped),
            prev_count,
        )
        previous_items = [
            Listing.from_dict(raw) for raw in state[tool]["items"].values()
        ]
        return PipelineResult(
            tool=tool,
            listings=previous_items,
            failed_sources=failed_sources,
            kept_previous_due_to_drop=True,
        )

    now_iso = utc_now_iso()
    final_listings, stats = reconcile_state(
        tool=tool,
        fresh_listings=deduped,
        state=state,
        now_iso=now_iso,
    )

    if sort_key_fn:
        final_listings.sort(key=sort_key_fn)
    else:
        final_listings.sort(
            key=lambda x: (x.posted_date or x.first_seen or ""),
            reverse=True,
        )

    if not dry_run:
        state[tool] = {
            "last_updated": now_iso,
            "items": {item.unique_id: item.to_dict() for item in final_listings},
        }
        save_state(state_path, state)

        write_rss(
            listings=final_listings,
            output_path=docs_dir / f"{tool}.xml",
            channel_title=channel_title,
            channel_link=channel_link,
            channel_description=channel_description,
        )
        write_json(
            listings=final_listings,
            output_path=docs_dir / f"{tool}.json",
            tool_name=tool,
            updated_at=now_iso,
        )
        if write_calendar:
            write_ics(
                listings=final_listings,
                output_path=docs_dir / f"{tool}.ics",
            )

    return PipelineResult(
        tool=tool,
        listings=final_listings,
        failed_sources=failed_sources,
        added_count=stats["added_count"],
        removed_count=stats["removed_count"],
    )
