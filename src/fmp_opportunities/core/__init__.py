"""Shared core modules for FMP Opportunities."""

from fmp_opportunities.core.config import (
    ConfigError,
    KeywordsConfig,
    SourceConfig,
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

__all__ = [
    "ConfigError",
    "KeywordsConfig",
    "Listing",
    "SourceConfig",
    "compute_unique_id",
    "load_keywords",
    "load_sources",
    "write_combined_rss",
    "write_ics",
    "write_json",
    "write_rss",
]
