"""tiny web ui over the store

    uv run sf-events-web          # http://127.0.0.1:8765

reads come from sqlite. a background thread rescrapes each source once it
is past its interval, runs the enrich pass on its own shorter cadence, and
the ui can ask for a rescrape right now
"""

import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sf_events import config, jobs, lookup, people, resolve
from sf_events.categorize import FORMATS, TOPICS
from sf_events.merge import dedupe, dedupe_key
from sf_events.models import PACIFIC, Event
from sf_events.sources import SOURCES
from sf_events.store import Store

STATIC = Path(__file__).parent / "static"
# how often the scheduler looks for a source that is due
TICK = 60

store = Store()
# one rescrape at a time per process, the ui button and the scheduler share it
_lock = threading.Lock()


# guest lists whose event page could not be resolved, so we do not refetch them every tick
_unresolvable: set[str] = set()


def adopt_orphans() -> int:
    """give every guest list without an event row a permanent one, pulled from the event page.

    sources drop events once they pass, so a list scraped after you went
    would otherwise point at nothing. rows under the scraped source are
    never replaced by a rescrape, so once adopted they stay
    """
    keys = {dedupe_key(e) for e in store.events()}
    adopted = 0
    for key, g in store.all_guest_analyses().items():
        if key in keys or key in _unresolvable:
            continue
        ev = resolve.resolve(g["event_url"])
        if ev:
            store.add(resolve.SOURCE, [ev])
            adopted += 1
        else:
            _unresolvable.add(key)
    return adopted


def _scheduler(stop: threading.Event) -> None:
    while not stop.is_set():
        with _lock:
            jobs.rescrape_due(store)
            adopt_orphans()
            jobs.enrich_due(store)
            lookup.lookup_due(store)
        stop.wait(TICK)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    threading.Thread(target=_scheduler, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="sf-events", lifespan=lifespan)
# the browser extension posts guest lists from partiful.com and luma.com pages
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/events")
def api_events(days: int | None = Query(default=None, ge=1)):
    # first boot has nothing stored, pull before answering so the page is not empty
    if any(s["last_ok_at"] is None for s in jobs.status(store)):
        with _lock:
            jobs.rescrape_due(store)
    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days) if days else None
    everything = dedupe(store.events())
    events = sorted((e for e in everything if e.start >= start and (end is None or e.start < end)), key=lambda e: (e.start, e.name))
    guests = store.all_guest_analyses()
    saved = store.saved()
    keys = {dedupe_key(e) for e in events}
    rows = [_with_guests(e, guests.get(dedupe_key(e))) for e in events]
    for r in rows:
        r["saved"] = r["key"] in saved
    # rows outside the window that still matter: saved, or carrying a guest list.
    # past events included, that is how a list you scraped after going shows up
    extra = []
    now = datetime.now(PACIFIC)
    for e in everything:
        k = dedupe_key(e)
        if k in keys or (k not in saved and k not in guests):
            continue
        r = _with_guests(e, guests.get(k))
        r["saved"] = k in saved
        r["past"] = e.start < now
        extra.append(r)
        keys.add(k)
    # saved snapshots for events no source has at all
    for k, sv in saved.items():
        if k not in keys:
            snap = dict(sv["event"], saved=True, stale=True, past=sv["event"].get("start", "") < now.isoformat())
            snap["guests"] = None
            extra.append(snap)
            keys.add(k)
    extra.sort(key=lambda r: r["start"])
    return {
        "extra": extra,
        "sources": jobs.status(store),
        "lookup": {"enabled": config.lookup_enabled(), "people": store.people_count(), "pending_lists": len(lookup.lists_with_work(store)) if config.lookup_enabled() else 0},
        # scraped lists whose event is not in this window, so they are not lost
        "orphan_guest_lists": [
            {"key": k, "event_url": g["event_url"], "scraped_at": g["scraped_at"], "summary": g["analysis"]["summary"]}
            for k, g in guests.items() if k not in keys
        ],
        "formats": FORMATS,
        # rule topics first, then whatever tags the sources added
        "topics": TOPICS + sorted({t for e in events for t in e.topics} - set(TOPICS)),
        "events": rows,
    }


def _with_guests(e: Event, g: dict | None) -> dict:
    d = e.to_dict()
    d["key"] = dedupe_key(e)
    if g:
        bonus, reasons = people.score_bonus(g["analysis"])
        d["score"] = min(100, d["score"] + bonus)
        d["score_reasons"] = d["score_reasons"] + reasons
        d["guests"] = {"scraped_at": g["scraped_at"], **g["analysis"]}
    else:
        d["guests"] = None
    return d


class GuestList(BaseModel):
    # the event page the extension was on
    page_url: str
    guests: list[dict]


@app.post("/api/guests")
def api_post_guests(body: GuestList):
    key = _key_for_url(body.page_url)
    # luma rows arrive without bios, the public profile api has them
    guests = people.enrich_luma(body.guests) if key.startswith("luma:") else body.guests
    analysis = people.analyze(guests)
    store.set_guests(key, _event_url(body.page_url), body.page_url, guests, analysis)
    known = any(dedupe_key(e) == key for e in store.events())
    if not known:
        # no source has this event, pull it from its own page so the list has a row
        ev = resolve.resolve(_event_url(body.page_url))
        if ev:
            store.add(resolve.SOURCE, [ev])
            known = True
    return {"key": key, "known_event": known, **analysis}


@app.get("/api/guests/{key:path}")
def api_get_guests(key: str):
    g = store.guests(key)
    if not g:
        raise HTTPException(404, "no guest list for that event")
    g["lookup"] = {"enabled": config.lookup_enabled(), **lookup.progress(store, g["guests"])}
    return g


@app.post("/api/lookup/{key:path}")
def api_lookup(key: str):
    """one bounded lookup pass for this list, right now"""
    if not config.lookup_enabled():
        raise HTTPException(400, "lookup is off: FIRECRAWL_API_KEY and ANTHROPIC_API_KEY are needed in .env")
    if not store.guests(key):
        raise HTTPException(404, "no guest list for that event")
    with _lock:
        run_id = store.start_run(key, job="lookup")
        try:
            r = lookup.lookup_list(store, key)
            store.finish_run(run_id, ok=True, count=r["searched"], added=r["read"])
        except Exception as e:
            store.finish_run(run_id, ok=False, error=f"{type(e).__name__}: {e}")
            raise HTTPException(502, f"lookup failed: {e}")
    return r


def _event_url(page_url: str) -> str:
    # strip query and fragment, keep the canonical event page
    from urllib.parse import urlsplit, urlunsplit
    u = urlsplit(page_url)
    return urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def _key_for_url(page_url: str) -> str:
    # reuse the dedupe key so a scraped list lines up with whichever source has the event
    probe = Event(
        id="probe", source="probe", name="", start=datetime.now(PACIFIC), end=None, url=_event_url(page_url),
        location=None, venue=None, summary=None, kind=None, image_url=None,
    )
    return dedupe_key(probe)


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


class SaveBody(BaseModel):
    # the row as the ui has it, kept as a snapshot
    event: dict


@app.get("/api/saved")
def api_saved():
    return [dict(v["event"], saved_at=v["saved_at"]) for v in store.saved().values()]


@app.put("/api/saved/{key:path}")
def api_save(key: str, body: SaveBody):
    store.save(key, body.event)
    return {"key": key, "saved": True}


@app.delete("/api/saved/{key:path}")
def api_unsave(key: str):
    if not store.unsave(key):
        raise HTTPException(404, "not saved")
    return {"key": key, "saved": False}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("sf_events.web:app", host="127.0.0.1", port=8765, reload=False)
