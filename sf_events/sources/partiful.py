"""partiful events

partiful.com/events needs a login, but partiful.com/explore/sf is a public
server-rendered page with every curated bay area event embedded in its
__NEXT_DATA__ json: a trending carousel plus themed sections ("Meet New
People!", "Good Eats") plus a short feed. about 75 events, no pagination,
and the category query params all return the same set. the section an
event appears in becomes its tags
"""

import json
import re
from datetime import datetime, timedelta

import httpx

from sf_events.models import Event

PAGE = "https://partiful.com/explore/sf"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
SUMMARY_CHARS = 400


def fetch(
    start: datetime,
    end: datetime | None = None,
    *,
    client: httpx.Client | None = None,
) -> list[Event]:
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    try:
        r = client.get(PAGE)
        r.raise_for_status()
        events = parse_page(r.text)
        return sorted(
            (e for e in events if e.start >= start and (end is None or e.start < end)),
            key=lambda e: e.start,
        )
    finally:
        if own:
            client.close()


def parse_page(html: str) -> list[Event]:
    m = NEXT_DATA.search(html)
    if not m:
        raise ValueError("no __NEXT_DATA__ on the explore page, layout changed?")
    props = json.loads(m.group(1))["props"]["pageProps"]
    # the same event can sit in several sections, collect the section names per id
    found: dict[str, tuple[dict, list[str]]] = {}
    for section in [props.get("trendingSection"), *props.get("sections", []), {"title": None, "items": props.get("feedItems", [])}]:
        if not section:
            continue
        for item in section.get("items") or []:
            ev = item.get("event") if isinstance(item, dict) else None
            if not ev or "id" not in ev:
                continue
            raw, tags = found.setdefault(ev["id"], (ev, []))
            if section.get("title") and section["title"] not in tags:
                tags.append(section["title"])
    return [parse(raw, tags) for raw, tags in found.values()]


def parse(raw: dict, tags: list[str] = ()) -> Event:
    loc = raw.get("locationInfo") or {}
    maps = loc.get("mapsInfo") or {}
    lines = loc.get("displayAddressLines") or []
    city = maps.get("approximateLocation") or (lines[-1] if lines else None)
    venue = maps.get("name") or loc.get("text")
    if venue and city and venue.strip().lower() == city.strip().lower():
        venue = None
    return Event(
        id=f"partiful:{raw['id']}",
        source="partiful",
        name=raw["title"].strip(),
        start=_ts(raw["startDate"]),
        end=_ts(raw["endDate"]) if raw.get("endDate") else None,
        url=f"https://partiful.com/e/{raw['id']}",
        location=city,
        venue=venue,
        summary=_clip(raw.get("description") or "", SUMMARY_CHARS) or None,
        kind=None,
        image_url=((raw.get("image") or {}).get("upload") or {}).get("url"),
        host=None,
        tags=tuple(_tag(t) for t in tags),
    )


def _tag(title: str) -> str:
    # "Meet New People!" -> "meet new people", "Curated by Jess @x" -> "curated"
    t = title.lower().strip().rstrip("!.")
    return "curated" if t.startswith("curated by") else t


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    cut = max(text.rfind(". ", 0, n), text.rfind("! ", 0, n), text.rfind("? ", 0, n))
    if cut < n // 2:
        cut = text.rfind(" ", 0, n)
    return text[: cut + 1].rstrip() + ("" if text[cut] in ".!?" else "…")
