"""Transparent keyword relevance filtering and optional LLM classification hook."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fmp_opportunities.core.config import KeywordsConfig
from fmp_opportunities.core.models import Listing

logger = logging.getLogger(__name__)

LLMClassifierHook = Callable[[Listing, str], dict[str, Any]]


@dataclass
class FilterDecision:
    """Outcome of evaluating a single listing for relevance."""

    kept: bool
    score: float
    matched_include: list[str]
    matched_exclude: list[str]
    reason: str


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term.strip().lower())
    pattern = rf"(?<!\w){escaped}(?!\w)"
    return re.search(pattern, text) is not None


def score_listing(listing: Listing, keywords: KeywordsConfig) -> FilterDecision:
    """Score a listing against include and exclude keyword rules."""
    searchable = " ".join(
        [
            listing.title,
            listing.summary,
            listing.organisation,
            listing.location,
            " ".join(listing.category_tags),
        ]
    ).lower()

    matched_exclude = [
        term for term in keywords.exclude if _contains_term(searchable, term)
    ]
    if matched_exclude:
        return FilterDecision(
            kept=False,
            score=0.0,
            matched_include=[],
            matched_exclude=matched_exclude,
            reason=f"excluded by term(s): {', '.join(matched_exclude)}",
        )

    score = 0.0
    matched_include: list[str] = []
    for term, weight in keywords.include.items():
        if _contains_term(searchable, term):
            score += weight
            matched_include.append(f"{term} (+{weight:g})")

    if score >= keywords.min_score:
        return FilterDecision(
            kept=True,
            score=score,
            matched_include=matched_include,
            matched_exclude=[],
            reason=f"score {score:g} >= {keywords.min_score:g} ({', '.join(matched_include)})",
        )

    return FilterDecision(
        kept=False,
        score=score,
        matched_include=matched_include,
        matched_exclude=[],
        reason=f"score {score:g} < {keywords.min_score:g}",
    )


def filter_listings(
    listings: list[Listing],
    keywords: KeywordsConfig,
    tool: str,
    llm_hook: Optional[LLMClassifierHook] = None,
) -> list[Listing]:
    """Filter listings for relevance and log the reason each item was kept or dropped."""
    kept: list[Listing] = []
    for listing in listings:
        decision = score_listing(listing, keywords)
        if not decision.kept:
            logger.info("DROP [%s] %s (%s): %s", tool, listing.title, listing.organisation, decision.reason)
            continue

        if llm_hook is not None:
            try:
                hook_result = llm_hook(listing, tool)
                if hook_result.get("relevant") is False:
                    reason = hook_result.get("reason", "rejected by LLM hook")
                    logger.info("DROP [%s] %s (%s): %s", tool, listing.title, listing.organisation, reason)
                    continue
                if hook_result.get("type"):
                    listing.type = str(hook_result["type"])
            except Exception as exc:
                logger.warning("LLM hook failed for '%s': %s", listing.title, exc)

        logger.info("KEEP [%s] %s (%s): %s", tool, listing.title, listing.organisation, decision.reason)
        kept.append(listing)

    return kept
