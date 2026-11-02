"""Official release and meeting calendars, fetched during the refresh and shown on the page.

Times are only ever what the source printed. If it printed none, the time stays empty,
and the page says "time not published". A page we can't parse raises, so a redesign
reads as "couldn't load", never as "no events".
"""
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import requests

from morning_brief.checks import CheckResult, Status
from morning_brief.moves import is_fetch_stale

log = logging.getLogger(__name__)

USER_AGENT = "morning-brief/1.0 (https://github.com/KC31415/morning-brief)"
KEEP_DAYS_BACK = 7


@dataclass
class Event:
    source: str
    event: str
    date: str          # YYYY-MM-DD
    time: str | None   # HH:MM New York time, exactly as published, or None
    link: str


@dataclass
class Parsed:
    event: str
    date: str
    time: str | None


def parse_time(text: str) -> str | None:
    """"8:30 AM" -> "08:30". Anything else is unknown, not guessed."""
    try:
        return datetime.strptime(text.strip(), "%I:%M %p").strftime("%H:%M")
    except ValueError:
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _require(events: list[Parsed], source: str) -> list[Parsed]:
    if not events:
        raise ValueError(f"no events found on the {source} page; its format may have changed")
    return events


def parse_bea(text: str) -> list[Parsed]:
    year = re.search(r"Year (\d{4})", text)
    events = []
    for row in re.findall(r'(?s)<tr class="scheduled-releases-type-press">.*?</tr>', text):
        day = re.search(r'release-date">([^<]+)<', row)
        title = re.search(r'(?s)release-title[^>]*>(.*?)</td>', row)
        time = re.search(r'text-muted">([^<]+)<', row)
        if year and day and title:
            date = datetime.strptime(f"{_clean(day.group(1))} {year.group(1)}", "%B %d %Y")
            events.append(Parsed(_clean(title.group(1)), date.strftime("%Y-%m-%d"), parse_time(time.group(1)) if time else None))
    return _require(events, "BEA")


def parse_census(text: str) -> list[Parsed]:
    events = []
    for row in re.findall(r"(?is)<tr[^>]*>.*?</tr>", text):
        cells = [_clean(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
        if len(cells) < 4:
            continue
        try:
            date = datetime.strptime(cells[1], "%B %d, %Y")
        except ValueError:
            continue
        events.append(Parsed(f"{cells[0]}, {cells[3]}", date.strftime("%Y-%m-%d"), parse_time(cells[2])))
    return _require(events, "Census")


def _month_number(name: str) -> int:
    return datetime.strptime(name[:3], "%b").month


def parse_fomc(text: str) -> list[Parsed]:
    events = []
    parts = re.split(r"(\d{4}) FOMC Meetings", text)
    for year, panel in zip(parts[1::2], parts[2::2]):
        rows = re.findall(r'(?s)fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>\s*([^<]+?)\s*<', panel)
        for months, days in rows:
            match = re.fullmatch(r"(\d+)-(\d+)(\*?)", days.strip())
            if not match:  # e.g. an unscheduled conference call: nothing we can date with certainty
                continue
            first, second, projections = match.groups()
            names = months.split("/")
            suffix = " (with economic projections)" if projections else ""
            for day_number, (month, day) in enumerate([(names[0], first), (names[-1], second)], start=1):
                date = f"{year}-{_month_number(month):02d}-{int(day):02d}"
                events.append(Parsed(f"FOMC meeting, day {day_number}{suffix if day_number == 2 else ''}", date, None))
    return _require(events, "FOMC")


def parse_ecb(text: str) -> list[Parsed]:
    events = []
    for day, what in re.findall(r"(?s)<dt>\s*(\d{2}/\d{2}/\d{4})\s*</dt>\s*<dd>(.*?)</dd>", text):
        name = _clean(what)
        if "monetary policy meeting" in name.lower() and "non-monetary" not in name.lower():
            events.append(Parsed(name, datetime.strptime(day, "%d/%m/%Y").strftime("%Y-%m-%d"), None))
    return _require(events, "ECB")


def parse_treasury(text: str) -> list[Parsed]:
    """An empty list is valid JSON, but it still means something is wrong: bills auction every week."""
    events = []
    for item in json.loads(text):
        day = item.get("competitiveAuctionCloseDate", "")[:10]
        if day:
            name = f"{item['securityTerm']} {item['securityType']} auction"
            events.append(Parsed(name, day, parse_time(item.get("competitiveAuctionCloseTime", ""))))
    return _require(events, "Treasury")


PARSERS = {"bea": parse_bea, "census": parse_census, "fomc": parse_fomc, "ecb": parse_ecb, "treasury": parse_treasury}


def _fetch_source(source: dict, now: pd.Timestamp, http) -> list[Event]:
    """Sources can span year pages, so one good page is enough. The stale check catches a missing year."""
    parsed, errors = {}, []
    for url in source["urls"]:
        try:
            response = http(url.format(year=now.year), timeout=30, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            for p in PARSERS[source["parser"]](response.text):
                parsed[(p.event, p.date)] = p
        except Exception as exc:
            errors.append(str(exc))
    if not parsed:
        raise ValueError("; ".join(errors) or "no events")
    cutoff = (now - pd.Timedelta(days=KEEP_DAYS_BACK)).strftime("%Y-%m-%d")
    return [Event(source["name"], p.event, p.date, p.time, source["link"]) for p in parsed.values() if p.date >= cutoff]


def fetch_all(sources: list[dict], now, http=requests.get) -> tuple[list[Event], dict[str, str | None]]:
    """All events, plus each source's error (None if it loaded). One bad source never stops the others."""
    now = pd.Timestamp(now)
    events, status = [], {}
    for source in sources:
        try:
            events += _fetch_source(source, now, http)
            status[source["name"]] = None
        except Exception as exc:
            log.warning("schedule source %s failed: %s", source["name"], exc)
            status[source["name"]] = str(exc)[:200]
    log.info("collected %d scheduled events", len(events))
    return events, status


def check_schedules(status: pd.DataFrame, events: pd.DataFrame, sources: list[dict], now) -> list[CheckResult]:
    """One result per source. Warnings, not failures: the market data itself is unaffected."""
    now = pd.Timestamp(now)
    rows = status.set_index("source") if not status.empty else status
    today = today_new_york(now)
    out = []
    for source in sources:
        name = source["name"]
        if name not in rows.index:
            out.append(CheckResult("schedule", name, Status.WARN, "calendar has never loaded"))
            continue
        row = rows.loc[name]
        if pd.notna(row["error"]):
            when = f"last loaded {row['last_success']}" if pd.notna(row["last_success"]) else "never loaded"
            out.append(CheckResult("schedule", name, Status.WARN, f"couldn't fetch: {row['error']} ({when})"))
        elif is_fetch_stale(row["last_success"], now):
            out.append(CheckResult("schedule", name, Status.WARN, f"stale: last loaded {row['last_success']}"))
        else:
            days = source.get("max_days_to_next", 45)
            limit = (now + pd.Timedelta(days=days)).strftime("%Y-%m-%d")
            mine = events[(events["source"] == name) & (events["event_date"] >= today) & (events["event_date"] <= limit)]
            if mine.empty:
                out.append(CheckResult("schedule", name, Status.WARN, f"stale: no event in the next {days} days"))
            else:
                out.append(CheckResult("schedule", name, Status.OK, f"{len(mine)} events in the next {days} days"))
    return out


def today_new_york(now) -> str:
    return pd.Timestamp(now).tz_convert("America/New_York").strftime("%Y-%m-%d")


def next_business_days(now, n: int) -> list[str]:
    today = pd.Timestamp(today_new_york(now))
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(today + pd.Timedelta(days=1), periods=n)]


def _time_label(hhmm) -> str:
    if pd.isna(hhmm):
        return "time not published"
    return f"{datetime.strptime(hhmm, '%H:%M'):%-I:%M %p} ET"


def _rows_for(events: pd.DataFrame, day: str) -> list[dict]:
    """A day's events sorted by time, unpublished times last. A joint release is one row with both links."""
    merged = {}
    for _, e in events[events["event_date"] == day].iterrows():
        time = None if pd.isna(e["event_time"]) else e["event_time"]
        row = merged.setdefault((e["event"], time), {"event": e["event"], "time": _time_label(time), "sort": time or "99:99", "sources": []})
        row["sources"].append((e["source"], e["link"]))
    return sorted(merged.values(), key=lambda r: (r["sort"], r["event"]))


@dataclass
class View:
    state: str              # events, no_events, partial or not_loaded
    today: list[dict]
    upcoming: dict[str, list[dict]]
    failed: list[str]


def build_view(status: pd.DataFrame, events: pd.DataFrame, sources: list[dict], now) -> View:
    results = check_schedules(status, events, sources, now)
    failed = [r.ticker for r in results if r.status != Status.OK and "no event in the next" not in r.detail]
    today = _rows_for(events, today_new_york(now))
    upcoming = {d: _rows_for(events, d) for d in next_business_days(now, 5)}
    if sources and len(failed) == len(sources) and events.empty:
        state = "not_loaded"
    elif failed:
        state = "partial"
    else:
        state = "events" if today else "no_events"
    return View(state, today, upcoming, failed)
