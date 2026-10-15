"""rescrape jobs, one per source

    rescrape(store, "cerebralvalley")   run one now
    rescrape_due(store)                 run whatever is past its interval
    enrich(store, "luma")               one bounded description pass over stored rows
    enrich_due(store)                   same, for every source whose pass is due
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
        if src.enrich:
            known = {e.id: e for e in store.events(name)}
            events = src.enrich(events, known)
        added, removed = store.replace_source(name, events)
        store.finish_run(run_id, ok=True, count=len(events), added=added, removed=removed)
    except Exception as e:
        # keep the old rows, log the failure, let the caller decide how loud to be
        store.finish_run(run_id, ok=False, error=f"{type(e).__name__}: {e}")
    return store.last_run(name)


def enrich(store: Store, name: str) -> dict:
    """one bounded enrich pass over what is already stored, no fetch"""
    src = SOURCES[name]
    run_id = store.start_run(name, job="enrich")
    try:
        before = store.events(name)
        known = {e.id: e for e in before}
        after = src.enrich(before, known)
        changed = [a for a, b in zip(after, before) if a != b]
        store.upsert(changed)
        store.finish_run(run_id, ok=True, count=len(changed), added=len(changed))
    except Exception as e:
        store.finish_run(run_id, ok=False, error=f"{type(e).__name__}: {e}")
    return store.last_run(name, job="enrich")


def is_enrich_due(store: Store, src: Source, now: datetime | None = None) -> bool:
    if not src.enrich:
        return False
    now = now or datetime.now(timezone.utc)
    # nothing to do while every near-term row already has a summary
    done, total = store.enrichment(src.name, now + src.enrich_window)
    if total and done >= total:
        return False
    last = store.last_run(src.name, job="enrich")
    if not last:
        return True
    return now - datetime.fromisoformat(last["finished_at"]) >= src.enrich_every


def enrich_due(store: Store, force: bool = False, log=None) -> list[dict]:
    runs = []
    for src in SOURCES.values():
        if src.enrich and (force or is_enrich_due(store, src)):
            if log:
                print(f"enriching {src.name}...", file=log)
            runs.append(enrich(store, src.name))
    return runs


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
        enr = None
        if src.enrich:
            done, total = store.enrichment(src.name, datetime.now(timezone.utc) + src.enrich_window)
            last_e = store.last_run(src.name, job="enrich")
            enr = {
                "done": done,
                "total": total,
                "every_minutes": int(src.enrich_every.total_seconds() // 60),
                "window_days": src.enrich_window.days,
                "last_run_at": last_e["finished_at"] if last_e else None,
                "last_count": last_e["count"] if last_e else None,
            }
        out.append({
            "source": src.name,
            "enrichment": enr,
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
