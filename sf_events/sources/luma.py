"""luma events

the map at luma.com/<topic>/map is fed by a public discover endpoint that takes
a bounding box. no auth, no slug needed, so one box over the bay area walks
every discoverable event behind every map dot

    GET https://api.luma.com/discover/get-paginated-events
        ?west=-122.7&east=-121.7&south=37.2&north=38.1
        &pagination_limit=50[&pagination_cursor=...]

response is {"entries": [...], "has_more", "next_cursor"}. pages cap at 50.
entries carry no description, so summary is empty and categories lean on the
name. a cold query can take ~20s on the first page, so timeouts are generous
and transport errors retry. about a quarter of the luma events cerebral valley
lists are not marked discoverable and never show up here, keep both sources
"""

import time
from datetime import datetime

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
