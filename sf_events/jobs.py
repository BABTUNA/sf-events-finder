"""rescrape jobs, one per source

    rescrape(store, "cerebralvalley")   run one now
    rescrape_due(store)                 run whatever is past its interval
    status(store)                       what the ui and `sf-events status` show
"""

import sys
from datetime import datetime, timedelta, timezone

from sf_events.models import PACIFIC
from sf_events.sources import SOURCES, Source
from sf_events.store import Store


def rescrape(store: Store, name: str) -> dict:
    src = SOURCES[name]
    run_id = store.start_run(name)
    # everything from the start of today pacific, same window the site uses
    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        events = src.fetch(start, None)
        added, removed = store.replace_source(name, events)
        store.finish_run(run_id, ok=True, count=len(events), added=added, removed=removed)
    except Exception as e:
        # keep the old rows, log the failure, let the caller decide how loud to be
        store.finish_run(run_id, ok=False, error=f"{type(e).__name__}: {e}")
    return store.last_run(name)


def is_due(store: Store, src: Source, now: datetime | None = None) -> bool:
    last = store.last_run(src.name, ok_only=True)
    if not last:
        return True
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(last["finished_at"]) >= src.every


def rescrape_due(store: Store, force: bool = False, log=None) -> list[dict]:
    runs = []
    for src in SOURCES.values():
        if force or is_due(store, src):
            if log:
                print(f"rescraping {src.name}...", file=log)
            runs.append(rescrape(store, src.name))
    return runs


def status(store: Store) -> list[dict]:
    out = []
    for src in SOURCES.values():
        last = store.last_run(src.name)
        last_ok = store.last_run(src.name, ok_only=True)
        next_due = None
        if last_ok:
            next_due = (datetime.fromisoformat(last_ok["finished_at"]) + src.every).isoformat()
        out.append({
            "source": src.name,
            "every_minutes": int(src.every.total_seconds() // 60),
            "count": store.count(src.name),
            "last_ok_at": last_ok["finished_at"] if last_ok else None,
            "last_run_at": last["finished_at"] if last else None,
            "last_run_ok": bool(last["ok"]) if last else None,
            "last_error": last["error"] if last else None,
            "last_added": last_ok["added"] if last_ok else None,
            "last_removed": last_ok["removed"] if last_ok else None,
            "next_due": next_due,
            "due": is_due(store, src),
        })
    return out
