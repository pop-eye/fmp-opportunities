"""Configuration loading and validation for sources and keywords."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

VALID_SOURCE_TYPES = {"api", "rss", "ical", "html"}
VALID_TOOLS = {"jobs", "placements", "apprenticeships", "events"}


class ConfigError(ValueError):
    """Raised when configuration files are missing or invalid."""


@dataclass
class SourceConfig:
    """Configuration for a single opportunity source."""

    name: str
    type: str
    url: str
    enabled: bool = True
    selectors: dict[str, str] = field(default_factory=dict)
    parser: Optional[str] = None
    rate_limit_seconds: float = 1.5
    options: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class KeywordsConfig:
    """Relevance filtering configuration for a tool."""

    include: dict[str, float] = field(default_factory=dict)
    exclude: list[str] = field(default_factory=list)
    min_score: float = 1.0
    required_any: list[str] = field(default_factory=list)
    required_title_any: list[str] = field(default_factory=list)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a YAML mapping at top level in {path}")
    return data


def load_sources(path: str | Path) -> dict[str, list[SourceConfig]]:
    """Load and validate sources.yaml into per tool SourceConfig lists."""
    data = _read_yaml(Path(path))
    result: dict[str, list[SourceConfig]] = {tool: [] for tool in VALID_TOOLS}

    for tool, entries in data.items():
        if tool not in VALID_TOOLS:
            raise ConfigError(
                f"Unknown tool section '{tool}' in {path}. Expected one of: {sorted(VALID_TOOLS)}"
            )
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise ConfigError(f"Section '{tool}' in {path} must be a list of sources")

        for idx, item in enumerate(entries):
            if not isinstance(item, dict):
                raise ConfigError(f"Entry {idx} in '{tool}' must be a mapping")
            for required in ("name", "type", "url"):
                if not item.get(required):
                    raise ConfigError(
                        f"Source entry {idx} in '{tool}' is missing required field '{required}'"
                    )
            source_type = str(item["type"]).strip().lower()
            if source_type not in VALID_SOURCE_TYPES:
                raise ConfigError(
                    f"Source '{item['name']}' has invalid type '{source_type}'. "
                    f"Expected one of: {sorted(VALID_SOURCE_TYPES)}"
                )

            selectors = item.get("selectors") or {}
            if not isinstance(selectors, dict):
                raise ConfigError(
                    f"Source '{item['name']}' selectors must be a mapping"
                )

            options = item.get("options") or {}
            if not isinstance(options, dict):
                raise ConfigError(
                    f"Source '{item['name']}' options must be a mapping"
                )

            result[tool].append(
                SourceConfig(
                    name=str(item["name"]).strip(),
                    type=source_type,
                    url=str(item["url"]).strip(),
                    enabled=bool(item.get("enabled", True)),
                    selectors={str(k): str(v) for k, v in selectors.items()},
                    parser=item.get("parser"),
                    rate_limit_seconds=float(item.get("rate_limit_seconds", 1.5)),
                    options=options,
                    notes=str(item.get("notes", "")),
                )
            )

    return result


def load_keywords(path: str | Path, tool: Optional[str] = None) -> KeywordsConfig:
    """Load keywords.yaml, merging global rules with optional tool specific overrides."""
    data = _read_yaml(Path(path))

    include: dict[str, float] = {}
    exclude: list[str] = []
    required_any: list[str] = []
    required_title_any: list[str] = []
    min_score = float(data.get("min_score", 1.0))

    def _merge_section(section: dict[str, Any]) -> None:
        nonlocal min_score
        if "min_score" in section:
            min_score = float(section["min_score"])
        raw_include = section.get("include") or {}
        if not isinstance(raw_include, dict):
            raise ConfigError(f"'include' must be a mapping of term to weight in {path}")
        for term, weight in raw_include.items():
            include[str(term).strip().lower()] = float(weight)
        raw_exclude = section.get("exclude") or []
        if not isinstance(raw_exclude, list):
            raise ConfigError(f"'exclude' must be a list of terms in {path}")
        for term in raw_exclude:
            normalised = str(term).strip().lower()
            if normalised and normalised not in exclude:
                exclude.append(normalised)
        for key, target in (
            ("required_any", required_any),
            ("required_title_any", required_title_any),
        ):
            terms = section.get(key, [])
            if not isinstance(terms, list):
                raise ConfigError(f"'{key}' must be a list of terms in {path}")
            for term in terms:
                if not isinstance(term, str) or not term.strip():
                    raise ConfigError(f"'{key}' must contain non-empty strings in {path}")
                normalised = term.strip().lower()
                if normalised and normalised not in target:
                    target.append(normalised)

    global_section = data.get("global")
    if isinstance(global_section, dict):
        _merge_section(global_section)
    elif any(key in data for key in ("include", "exclude", "required_any", "required_title_any")):
        _merge_section(data)

    if tool:
        if tool not in VALID_TOOLS:
            raise ConfigError(
                f"Unknown tool '{tool}'. Expected one of: {sorted(VALID_TOOLS)}"
            )
        tool_section = data.get(tool)
        if isinstance(tool_section, dict):
            _merge_section(tool_section)

    return KeywordsConfig(
        include=include,
        exclude=exclude,
        min_score=min_score,
        required_any=required_any,
        required_title_any=required_title_any,
    )
