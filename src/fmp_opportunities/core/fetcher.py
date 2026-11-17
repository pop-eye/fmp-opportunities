"""Polite HTTP fetching, robots.txt checking, caching, and base parsers."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar

from fmp_opportunities.core.config import SourceConfig
from fmp_opportunities.core.models import Listing

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "FMP-Opportunities/0.1 (+https://github.com/mmu-fmp/fmp-opportunities; "
    "educational opportunities aggregator)"
)

ParserFunc = Callable[[SourceConfig, str, "PoliteFetcher"], list[Listing]]


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def _parse_rss_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    try:
        dt = parsedate_to_datetime(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return cleaned[:10] if len(cleaned) >= 10 else cleaned


class PoliteFetcher:
    """HTTP client with User-Agent, robots.txt compliance, rate limiting, and disk cache."""

    def __init__(
        self,
        cache_dir: str | Path = "state/cache",
        cache_ttl_seconds: int = 21600,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: int = 20,
        respect_robots: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.respect_robots = respect_robots
        self._last_request_by_host: dict[str, float] = {}
        self._robots_cache: dict[str, Optional[RobotFileParser]] = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> Optional[str]:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            age = time.time() - float(payload.get("fetched_at", 0))
            if age <= self.cache_ttl_seconds:
                logger.debug("Cache hit for %s (age %.0fs)", url, age)
                return str(payload["body"])
        except (OSError, ValueError, KeyError):
            return None
        return None

    def _write_cache(self, url: str, body: str) -> None:
        path = self._cache_path(url)
        payload = {"url": url, "fetched_at": time.time(), "body": body}
        path.write_text(json.dumps(payload), encoding="utf-8")

    def is_allowed_by_robots(self, url: str) -> bool:
        """Check robots.txt for the target URL."""
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots_cache:
            robots_url = f"{base}/robots.txt"
            rp = RobotFileParser()
            try:
                resp = self.session.get(robots_url, timeout=10)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots_cache[base] = rp
                else:
                    self._robots_cache[base] = None
            except requests.RequestException:
                self._robots_cache[base] = None

        cached_rp = self._robots_cache[base]
        if cached_rp is None:
            return True
        return cached_rp.can_fetch(self.user_agent, url)

    def get_text(
        self,
        url: str,
        rate_limit_seconds: float = 1.5,
        auth: Optional[tuple[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        use_cache: bool = True,
        check_robots: bool = True,
    ) -> str:
        """Fetch URL text politely, using cache when fresh."""
        cache_key = url
        if params:
            sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            cache_key = f"{url}?{sorted_params}"

        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        if check_robots and not self.is_allowed_by_robots(url):
            raise PermissionError(f"Blocked by robots.txt: {url}")

        host = urlparse(url).netloc
        last_time = self._last_request_by_host.get(host)
        if last_time is not None:
            elapsed = time.monotonic() - last_time
            if elapsed < rate_limit_seconds:
                time.sleep(rate_limit_seconds - elapsed)

        resp = self.session.get(
            url,
            auth=auth,
            params=params,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        self._last_request_by_host[host] = time.monotonic()
        resp.raise_for_status()

        if use_cache:
            self._write_cache(cache_key, resp.text)
        return resp.text


def parse_rss_feed(source: SourceConfig, body: str, _fetcher: PoliteFetcher) -> list[Listing]:
    """Parse an RSS 2.0 or Atom feed into Listing objects."""
    root = ET.fromstring(body)
    listings: list[Listing] = []

    # RSS 2.0
    items = root.findall("./channel/item")
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        desc = _strip_html(item.findtext("description") or "")
        pub_date = _parse_rss_date(item.findtext("pubDate"))
        author = (item.findtext("author") or "").strip()
        categories = [c.text.strip() for c in item.findall("category") if c.text]
        listings.append(
            Listing(
                title=title,
                organisation=author or source.name,
                location=str(source.options.get("default_location", "UK")),
                remote="remote" in (title + " " + desc).lower(),
                type=str(source.options.get("default_type", "")),
                category_tags=categories,
                summary=desc[:500],
                posted_date=pub_date,
                source_name=source.name,
                source_url=urljoin(source.url, link),
            )
        )

    if listings:
        return listings

    # Atom fallback
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("atom:link", ns)
        link = (link_el.attrib.get("href", "") if link_el is not None else "").strip()
        if not title or not link:
            continue
        summary_raw = (
            entry.findtext("atom:summary", default="", namespaces=ns)
            or entry.findtext("atom:content", default="", namespaces=ns)
            or ""
        )
        desc = _strip_html(summary_raw)
        updated = entry.findtext("atom:updated", default="", namespaces=ns) or entry.findtext(
            "atom:published", default="", namespaces=ns
        )
        author_el = entry.find("atom:author/atom:name", ns)
        author = author_el.text.strip() if author_el is not None and author_el.text else ""
        listings.append(
            Listing(
                title=title,
                organisation=author or source.name,
                location=str(source.options.get("default_location", "UK")),
                remote="remote" in (title + " " + desc).lower(),
                type=str(source.options.get("default_type", "")),
                summary=desc[:500],
                posted_date=updated[:10] if updated else None,
                source_name=source.name,
                source_url=urljoin(source.url, link),
            )
        )

    return listings


def parse_ical_feed(source: SourceConfig, body: str, _fetcher: PoliteFetcher) -> list[Listing]:
    """Parse an iCalendar (.ics) feed into Listing objects."""
    cal = Calendar.from_ical(body)
    listings: list[Listing] = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        title = str(component.get("summary", "")).strip()
        if not title:
            continue

        dtstart_prop = component.get("dtstart")
        dtend_prop = component.get("dtend")
        event_start = dtstart_prop.dt.isoformat() if dtstart_prop else None
        event_end = dtend_prop.dt.isoformat() if dtend_prop else None

        location = str(component.get("location", "")).strip() or str(
            source.options.get("default_location", "Manchester")
        )
        description = _strip_html(str(component.get("description", "")))
        url = str(component.get("url", "")).strip() or source.url
        organiser = str(component.get("organizer", "")).replace("mailto:", "").strip()

        listings.append(
            Listing(
                title=title,
                organisation=organiser or source.name,
                location=location,
                remote="online" in (title + " " + location + " " + description).lower()
                or "remote" in (title + " " + location).lower(),
                type="event",
                summary=description[:500],
                posted_date=event_start[:10] if event_start else None,
                event_start=event_start,
                event_end=event_end,
                source_name=source.name,
                source_url=url,
            )
        )

    return listings


def parse_html_selectors(source: SourceConfig, body: str, _fetcher: PoliteFetcher) -> list[Listing]:
    """Generic CSS selector based HTML parser configured via sources.yaml."""
    selectors = source.selectors
    item_sel = selectors.get("item")
    if not item_sel:
        raise ValueError(f"HTML source '{source.name}' requires 'selectors.item' or a custom parser")

    soup = BeautifulSoup(body, "html.parser")
    listings: list[Listing] = []

    for node in soup.select(item_sel):
        title_sel = selectors.get("title", "a")
        title_el = node.select_one(title_sel)
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)

        link_sel = selectors.get("link", title_sel)
        link_el = node.select_one(link_sel)
        href = link_el.get("href", "") if link_el else ""
        if not href and title_el.name == "a":
            href = title_el.get("href", "")
        full_url = urljoin(source.url, str(href))
        if not title or not full_url:
            continue

        def _text(key: str, default: str = "") -> str:
            sel = selectors.get(key)
            if not sel:
                return default
            el = node.select_one(sel)
            return el.get_text(" ", strip=True) if el else default

        location = _text("location", str(source.options.get("default_location", "UK")))
        summary = _text("summary", "")
        organisation = _text("organisation", source.name)
        closing = _text("closing_date", "") or None
        posted = _text("posted_date", "") or None
        combined_text = f"{title} {location} {summary}".lower()

        listings.append(
            Listing(
                title=title,
                organisation=organisation,
                location=location,
                remote="remote" in combined_text,
                type=str(source.options.get("default_type", "")),
                summary=summary[:500],
                posted_date=posted,
                closing_date=closing,
                source_name=source.name,
                source_url=full_url,
            )
        )

    return listings


def resolve_parser(parser_path: str) -> ParserFunc:
    """Import a custom parser function from a dotted module:func or module.func path."""
    if ":" in parser_path:
        mod_name, func_name = parser_path.split(":", 1)
    else:
        mod_name, func_name = parser_path.rsplit(".", 1)
    module = importlib.import_module(mod_name)
    func = getattr(module, func_name)
    return func


def fetch_source_listings(source: SourceConfig, fetcher: PoliteFetcher) -> list[Listing]:
    """Fetch and parse listings from a single SourceConfig."""
    if source.parser:
        parser_func = resolve_parser(source.parser)
        # Custom API/HTML parsers may handle their own HTTP parameters or auth
        if source.type == "api":
            return parser_func(source, "", fetcher)
        body = fetcher.get_text(source.url, rate_limit_seconds=source.rate_limit_seconds)
        return parser_func(source, body, fetcher)

    body = fetcher.get_text(source.url, rate_limit_seconds=source.rate_limit_seconds)
    if source.type == "rss":
        return parse_rss_feed(source, body, fetcher)
    if source.type == "ical":
        return parse_ical_feed(source, body, fetcher)
    if source.type == "html":
        return parse_html_selectors(source, body, fetcher)
    raise ValueError(f"No parser configured for source '{source.name}' (type={source.type})")
