"""tiny web ui over the store

    uv run sf-events-web          # http://127.0.0.1:8765

reads come from sqlite. a background thread rescrapes each source once it
is past its interval, and the ui can ask for a rescrape right now
"""

import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from sf_events import jobs
from sf_events.categorize import FORMATS, TOPICS
from sf_events.merge import dedupe
from sf_events.models import PACIFIC
from sf_events.sources import SOURCES
from sf_events.store import Store

STATIC = Path(__file__).parent / "static"
# how often the scheduler looks for a source that is due
TICK = 60

store = Store()
# one rescrape at a time per process, the ui button and the scheduler share it
_lock = threading.Lock()


def _scheduler(stop: threading.Event) -> None:
    while not stop.is_set():
        with _lock:
            jobs.rescrape_due(store)
        stop.wait(TICK)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    threading.Thread(target=_scheduler, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="sf-events", lifespan=lifespan)


@app.get("/api/events")
def api_events(days: int | None = Query(default=None, ge=1)):
    # first boot has nothing stored, pull before answering so the page is not empty
    if any(s["last_ok_at"] is None for s in jobs.status(store)):
        with _lock:
            jobs.rescrape_due(store)
    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days) if days else None
    events = dedupe([e for e in store.events() if e.start >= start and (end is None or e.start < end)])
    events.sort(key=lambda e: (e.start, e.name))
    return {
        "sources": jobs.status(store),
        "formats": FORMATS,
        "topics": TOPICS,
        "events": [e.to_dict() for e in events],
    }


@app.get("/api/status")
def api_status():
    return jobs.status(store)


@app.post("/api/rescrape/{source}")
def api_rescrape(source: str):
    if source not in SOURCES:
        raise HTTPException(404, f"no source named {source}")
    with _lock:
        run = jobs.rescrape(store, source)
    if not run["ok"]:
        raise HTTPException(502, run["error"])
    return run


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("sf_events.web:app", host="127.0.0.1", port=8765, reload=False)
