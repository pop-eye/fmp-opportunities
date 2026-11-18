"""Data model for opportunities listings."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def compute_unique_id(source_url: str, title: str, organisation: str) -> str:
    """Return a stable 16 character hex identifier for a listing."""
    raw = "|".join(
        [
            source_url.strip(),
            _normalise_text(title),
            _normalise_text(organisation),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Listing:
    """Common representation of a job, placement, or event listing."""

    title: str
    organisation: str
    location: str
    remote: bool = False
    type: str = ""
    category_tags: list[str] = field(default_factory=list)
    summary: str = ""
    posted_date: Optional[str] = None
    closing_date: Optional[str] = None
    source_name: str = ""
    source_url: str = ""
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    unique_id: str = ""
    paid: Optional[str] = None
    apprenticeship_level: Optional[int] = None
    event_start: Optional[str] = None
    event_end: Optional[str] = None
    cost: Optional[str] = None
    is_new: bool = False

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        self.organisation = self.organisation.strip()
        self.location = self.location.strip()
        self.summary = self.summary.strip()
        self.source_name = self.source_name.strip()
        self.source_url = self.source_url.strip()
        if not self.unique_id:
            self.unique_id = compute_unique_id(
                self.source_url, self.title, self.organisation
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the listing to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Listing:
        """Construct a Listing from a dictionary."""
        return cls(
            title=data["title"],
            organisation=data.get("organisation", ""),
            location=data.get("location", ""),
            remote=bool(data.get("remote", False)),
            type=data.get("type", ""),
            category_tags=list(data.get("category_tags", [])),
            summary=data.get("summary", ""),
            posted_date=data.get("posted_date"),
            closing_date=data.get("closing_date"),
            source_name=data.get("source_name", ""),
            source_url=data.get("source_url", ""),
            first_seen=data.get("first_seen"),
            last_seen=data.get("last_seen"),
            unique_id=data.get("unique_id", ""),
            paid=data.get("paid"),
            apprenticeship_level=data.get("apprenticeship_level"),
            event_start=data.get("event_start"),
            event_end=data.get("event_end"),
            cost=data.get("cost"),
            is_new=bool(data.get("is_new", False)),
        )
