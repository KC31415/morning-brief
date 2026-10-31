"""Pull recent headlines from public RSS feeds."""
import logging
from datetime import datetime, timezone

import feedparser
import pandas as pd

from morning_brief.checks import expected_session

log = logging.getLogger(__name__)


def _timestamp(entry):
    return entry.get("published_parsed") or entry.get("updated_parsed")


def previous_close(now) -> pd.Timestamp:
    """4pm New York on the prior business day, so Monday's run reaches back to Friday's close."""
    return (expected_session(now) + pd.Timedelta(hours=16)).tz_localize("America/New_York")


def fetch_headlines(feeds: list[dict], per_feed: int = 15, now=None) -> list[dict]:
    """Return items since the previous US close as dicts with id, source, title, summary, link, published."""
    cutoff = previous_close(now if now is not None else datetime.now(timezone.utc))
    items = []
    for feed in feeds:
        try:
            parsed = feedparser.parse(feed["url"])
            if parsed.bozo and not parsed.entries:
                log.warning("feed %s could not be parsed: %s", feed["name"], parsed.bozo_exception)
                continue
            # Feeds aren't always newest-first; undated items sort last
            entries = sorted(parsed.entries, key=lambda e: tuple(_timestamp(e) or ()), reverse=True)
            for e in entries[:per_feed]:
                ts = _timestamp(e)
                published = datetime(*ts[:6], tzinfo=timezone.utc) if ts else None
                if published and published < cutoff:
                    continue
                items.append({
                    "source": feed["name"],
                    "title": e.get("title", "").strip(),
                    "summary": e.get("summary", "")[:500],
                    "link": e.get("link", ""),
                    "published": published.isoformat() if published else None,
                })
        except Exception:
            log.exception("feed %s failed", feed["name"])
    for i, item in enumerate(items, start=1):
        item["id"] = i
    log.info("collected %d headlines", len(items))
    return items
