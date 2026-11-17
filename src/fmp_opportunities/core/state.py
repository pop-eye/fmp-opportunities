"""Persistent JSON state management, expiry filtering, and safety checks."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fmp_opportunities.core.models import Listing, utc_now_iso
from fmp_opportunities.core.writers import parse_iso_datetime


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    dt = parse_iso_datetime(value)
    if dt is not None:
        return dt.date()
    return None


def is_expired(listing: Listing, today: Optional[date] = None) -> bool:
    """Return True if a listing's closing date or event date has passed."""
    ref_today = today or datetime.now(timezone.utc).date()

    closing = _parse_date(listing.closing_date)
    if closing is not None and closing < ref_today:
        return True

    event_end = _parse_date(listing.event_end)
    if event_end is not None and event_end < ref_today:
        return True

    event_start = _parse_date(listing.event_start)
    if listing.event_end is None and event_start is not None and event_start < ref_today:
        return True

    return False


def load_state(state_path: str | Path) -> dict[str, dict]:
    """Load persisted state dictionary keyed by tool name."""
    path = Path(state_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state_path: str | Path, state: dict[str, dict]) -> None:
    """Persist state dictionary to disk."""
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def reconcile_state(
    tool: str,
    fresh_listings: list[Listing],
    state: dict[str, dict],
    now_iso: Optional[str] = None,
    stale_after_days: int = 14,
    new_window_days: int = 7,
) -> tuple[list[Listing], dict[str, int]]:
    """Merge fresh listings with persisted state, drop expired items, and mark new items."""
    timestamp = now_iso or utc_now_iso()
    now_dt = parse_iso_datetime(timestamp) or datetime.now(timezone.utc)
    today = now_dt.date()

    tool_state = state.get(tool, {})
    previous_items_raw = tool_state.get("items", {})
    previous_by_id: dict[str, Listing] = {
        uid: Listing.from_dict(raw) for uid, raw in previous_items_raw.items()
    }

    merged_by_id: dict[str, Listing] = {}
    added_count = 0

    for item in fresh_listings:
        uid = item.unique_id
        prev = previous_by_id.get(uid)
        if prev is not None:
            item.first_seen = prev.first_seen or timestamp
        else:
            item.first_seen = timestamp
            added_count += 1
        item.last_seen = timestamp

        first_dt = parse_iso_datetime(item.first_seen) or now_dt
        item.is_new = (now_dt - first_dt) <= timedelta(days=new_window_days)

        if not is_expired(item, today=today):
            merged_by_id[uid] = item

    # Retain unexpired previous items that were not seen in this run up to stale_after_days
    for uid, prev in previous_by_id.items():
        if uid in merged_by_id:
            continue
        if is_expired(prev, today=today):
            continue
        last_dt = parse_iso_datetime(prev.last_seen) or now_dt
        if (now_dt - last_dt) <= timedelta(days=stale_after_days):
            first_dt = parse_iso_datetime(prev.first_seen) or now_dt
            prev.is_new = (now_dt - first_dt) <= timedelta(days=new_window_days)
            merged_by_id[uid] = prev

    removed_count = max(0, len(previous_by_id) - len([u for u in previous_by_id if u in merged_by_id]))

    result_list = list(merged_by_id.values())
    stats = {
        "previous_count": len(previous_by_id),
        "fresh_count": len(fresh_listings),
        "final_count": len(result_list),
        "added_count": added_count,
        "removed_count": removed_count,
    }
    return result_list, stats


def is_suspicious_drop(previous_count: int, fresh_count: int, min_baseline: int = 4) -> bool:
    """Return True if fresh_count is under half of previous_count when baseline is meaningful."""
    if previous_count < min_baseline:
        return False
    return fresh_count < (previous_count * 0.5)
