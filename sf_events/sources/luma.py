"""luma events

the map at luma.com/<topic>/map is fed by a public discover endpoint that takes
a bounding box. no auth, no slug needed, so one box over the bay area walks
every discoverable event behind every map dot

    GET https://api.luma.com/discover/get-paginated-events
        ?west=-122.7&east=-121.7&south=37.2&north=38.1
        &pagination_limit=50[&pagination_cursor=...]

response is {"entries": [...], "has_more", "next_cursor"}. pages cap at 50.
entries carry no description, so a second pass (`enrich`) hits
GET https://api.luma.com/url?url=<slug> for events in the next two weeks and
pulls the description and luma's own category tags. a cold query can take ~20s on the first page, so timeouts are generous
and transport errors retry. about a quarter of the luma events cerebral valley
lists are not marked discoverable and never show up here, keep both sources
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx

from sf_events.models import Event

API = "https://api.luma.com/discover/get-paginated-events"
PAGE = 50
# the whole bay, marin to san jose, pacifica to livermore
BAY_AREA = {"west": -122.7, "east": -121.7, "south": 37.2, "north": 38.1}
RETRIES = 3


def fetch(
    start: datetime,
    end: datetime | None = None,
    *,
    bbox: dict[str, float] = BAY_AREA,
    client: httpx.Client | None = None,
) -> list[Event]:
    """every discoverable event in the box starting in [start, end), oldest first"""
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60, connect=15), headers={"User-Agent": "Mozilla/5.0"})
    try:
        events: list[Event] = []
        cursor = None
        while True:
            params: dict = {**bbox, "pagination_limit": PAGE}
            if cursor:
                params["pagination_cursor"] = cursor
            body = _get(client, params)
            for raw in body["entries"]:
                ev = parse(raw)
                if ev.start < start or (end and ev.start >= end):
                    continue
                events.append(ev)
            # entries come back in start order, so once past `end` there is nothing left to page
            if not body.get("has_more") or not body.get("next_cursor"):
                return events
            if end and body["entries"] and _ts(body["entries"][-1]["start_at"]) >= end:
                return events
            cursor = body["next_cursor"]
    finally:
        if own:
            client.close()


def _get(client: httpx.Client, params: dict) -> dict:
    for attempt in range(RETRIES):
        try:
            r = client.get(API, params=params)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except httpx.TransportError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def parse(raw: dict) -> Event:
    ev = raw["event"]
    geo = ev.get("geo_address_info") or {}
    hosts = [h.get("name") for h in raw.get("hosts") or [] if h.get("name")]
    cal = (raw.get("calendar") or {}).get("name")
    # a personal calendar is just the host again, a community calendar is worth naming
    host = ", ".join(hosts) or (cal if cal and cal != "Personal" else None)
    return Event(
        id=f"luma:{ev['api_id']}",
        source="luma",
        name=ev["name"].strip(),
        start=_ts(ev["start_at"]),
        end=_ts(ev["end_at"]) if ev.get("end_at") else None,
        url=f"https://luma.com/{ev['url']}",
        location=geo.get("city_state") or geo.get("city"),
        # obfuscated venues only carry the city, address is absent
        venue=geo.get("address") if geo.get("mode") == "shown" else None,
        summary=None,
        kind=None,
        image_url=ev.get("cover_url"),
        host=host,
    )


def _ts(s: str) -> datetime:
    # "2026-10-15T16:00:00.000Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---- second pass: descriptions and luma's own category tags

DETAIL_API = "https://api.luma.com/url"
# how far ahead to bother fetching a description for
DETAIL_WINDOW = timedelta(days=14)
# the detail endpoint 429s fast, a few workers with a real backoff beats many
DETAIL_WORKERS = 3
DETAIL_RETRIES = 5
SUMMARY_CHARS = 400


def enrich(events: list[Event], known: dict[str, Event], *, now: datetime | None = None, client: httpx.Client | None = None) -> list[Event]:
    """fill summary and tags for events starting within DETAIL_WINDOW

    rows already in the store keep what they had, so each event costs one
    detail call ever. the rest of the list goes back untouched
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now + DETAIL_WINDOW
    todo = []
    out = list(events)
    for i, e in enumerate(events):
        if e.start >= cutoff:
            continue
        k = known.get(e.id)
        if k and (k.summary or k.tags):
            out[i] = replace(e, summary=k.summary, tags=k.tags)
        else:
            todo.append(i)
    if not todo:
        return out
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=15), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with ThreadPoolExecutor(DETAIL_WORKERS) as pool:
            for i, detail in zip(todo, pool.map(lambda i: _detail(client, events[i]), todo)):
                if detail:
                    out[i] = replace(events[i], **detail)
    finally:
        if own:
            client.close()
    return out


def _detail(client: httpx.Client, e: Event) -> dict | None:
    """one event's description and tags, or None. never raises: a miss here
    just leaves the row without a summary until the next run"""
    slug = e.url.rsplit("/", 1)[-1]
    for attempt in range(DETAIL_RETRIES):
        try:
            r = client.get(DETAIL_API, params={"url": slug})
        except httpx.TransportError:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                return parse_detail(r.json())
            except (ValueError, KeyError, TypeError):
                return None
        if r.status_code == 429 or r.status_code >= 500:
            # honour retry-after when given, otherwise back off hard: 5, 10, 20, 40s
            wait = float(r.headers.get("retry-after") or 0) or 5 * 2**attempt
            time.sleep(min(wait, 60))
            continue
        return None
    return None


def parse_detail(body: dict) -> dict:
    data = body.get("data") or {}
    text = _doc_text(data.get("description_mirror"))
    return {
        "summary": _clip(text, SUMMARY_CHARS) or None,
        "tags": tuple(c["name"].lower() for c in data.get("categories") or [] if c.get("name")),
    }


_BLOCKS = {"paragraph", "heading", "listItem", "bulletList", "orderedList", "blockquote"}


def _doc_text(node) -> str:
    # description_mirror is a tiptap document, walk it and keep block breaks
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        inner = "".join(_doc_text(c) for c in node.get("content", []))
        return inner + ("\n" if node.get("type") in _BLOCKS else "")
    if isinstance(node, list):
        return "".join(_doc_text(c) for c in node)
    return ""


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    # cut at the last sentence end before the limit, else at a word
    cut = max(text.rfind(". ", 0, n), text.rfind("! ", 0, n), text.rfind("? ", 0, n))
    if cut < n // 2:
        cut = text.rfind(" ", 0, n)
    return text[: cut + 1].rstrip() + ("" if text[cut] in ".!?" else "…")
