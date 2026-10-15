"""tiny web ui over the same sources the cli uses

    uv run sf-events-web          # http://127.0.0.1:8765

one json endpoint, one static page. results are cached for ten minutes so
reloading the page does not hammer cerebral valley
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from sf_events.categorize import FORMATS, TOPICS
from sf_events.models import PACIFIC, Event
from sf_events.sources import SOURCES

STATIC = Path(__file__).parent / "static"
CACHE_TTL = 600

app = FastAPI(title="sf-events")

# (fetched_at, events) for the one query we actually make: everything upcoming
_cache: tuple[float, list[Event]] | None = None


def all_upcoming() -> list[Event]:
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < CACHE_TTL:
        return _cache[1]
    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    events: list[Event] = []
    for fetch in SOURCES.values():
        events.extend(fetch(start, None))
    events.sort(key=lambda e: (e.start, e.name))
    _cache = (now, events)
    return events


@app.get("/api/events")
def api_events(days: int | None = Query(default=None, ge=1)):
    try:
        events = all_upcoming()
    except httpx.HTTPError as e:
        # upstream down or no network, say which instead of a traceback
        raise HTTPException(502, f"could not reach a source: {e}")
    if days:
        cutoff = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
        events = [e for e in events if e.start < cutoff]
    return {
        "fetched_at": datetime.fromtimestamp(_cache[0], PACIFIC).isoformat() if _cache else None,
        "formats": FORMATS,
        "topics": TOPICS,
        "events": [e.to_dict() for e in events],
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("sf_events.web:app", host="127.0.0.1", port=8765, reload=False)
