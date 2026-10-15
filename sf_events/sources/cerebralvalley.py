"""cerebral valley events

the events page at cerebralvalley.ai/events is a next.js app that fills itself
from a public json api, so we skip the html and call that directly

    GET https://api.cerebralvalley.ai/v1/public/event/pull
        ?approved=true&locations=BAY_AREA&startDateTime=<utc iso>&limit=100&offset=0

the response is {"events": [...], "totalCount", "limit", "offset", "lastPage"}.
timestamps come back as naive strings like "2026-10-15 15:00:00" and are utc.
most entries are luma links the cv team approved, a few are cv's own hackathons
"""

from datetime import datetime, timezone

import httpx

from sf_events.models import Event

API = "https://api.cerebralvalley.ai/v1/public/event/pull"
# the server caps pages at 100 no matter what you ask for
PAGE = 100
LOCATION = "BAY_AREA"


def fetch(
    start: datetime,
    end: datetime | None = None,
    *,
    location: str = LOCATION,
    client: httpx.Client | None = None,
) -> list[Event]:
    """every approved event starting at or after `start`, oldest first"""
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        events: list[Event] = []
        offset = 0
        while True:
            params = {
                "approved": "true",
                "locations": location,
                "startDateTime": _to_api(start),
                "limit": PAGE,
                "offset": offset,
            }
            if end:
                params["endDateTime"] = _to_api(end)
            r = client.get(API, params=params)
            r.raise_for_status()
            body = r.json()
            events.extend(parse(e) for e in body["events"])
            if body.get("lastPage") or not body["events"]:
                return events
            offset += PAGE
    finally:
        if own:
            client.close()


def parse(raw: dict) -> Event:
    kind = (raw.get("type") or "").strip().lower() or None
    return Event(
        id=f"cv:{raw['id']}",
        source="cerebralvalley",
        name=raw["name"].strip(),
        start=_from_api(raw["startDateTime"]),
        end=_from_api(raw["endDateTime"]) if raw.get("endDateTime") else None,
        url=raw["url"],
        location=raw.get("location") or None,
        venue=raw.get("venue") or None,
        summary=raw.get("descriptionSummary") or None,
        kind=kind,
        image_url=raw.get("imageUrl") or None,
    )


def _to_api(dt: datetime) -> str:
    # the site sends 2026-10-15T07:00:00.000Z, mirror that exactly
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _from_api(s: str) -> datetime:
    # "2026-10-15 15:00:00" with no zone, verified utc against the rendered page
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
