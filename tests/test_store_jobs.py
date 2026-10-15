from datetime import datetime, timedelta, timezone

import pytest

from sf_events import jobs
from sf_events.models import Event
from sf_events.sources import SOURCES, Source
from sf_events.store import Store


def ev(i: str, name: str = "x") -> Event:
    return Event(
        id=f"t:{i}", source="test", name=name, start=datetime(2026, 10, 20, 1, tzinfo=timezone.utc), end=None,
        url="https://example.com", location="San Francisco, CA", venue=None, summary=None, kind=None, image_url=None,
    )


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "e.db")


@pytest.fixture
def fake_source(monkeypatch):
    calls = {"fail": False, "events": [ev("a"), ev("b")]}

    def fetch(start, end):
        if calls["fail"]:
            raise RuntimeError("upstream down")
        return calls["events"]

    monkeypatch.setitem(SOURCES, "test", Source("test", fetch, timedelta(minutes=30)))
    return calls


def test_replace_source_adds_removes_and_roundtrips(store):
    assert store.replace_source("test", [ev("a"), ev("b")]) == (2, 0)
    # b dropped, c appeared, a kept
    assert store.replace_source("test", [ev("a", "renamed"), ev("c")]) == (1, 1)
    got = {e.id: e for e in store.events("test")}
    assert set(got) == {"t:a", "t:c"}
    assert got["t:a"].name == "renamed"
    assert got["t:a"].start.tzinfo is not None


def test_rescrape_logs_runs_and_keeps_rows_on_failure(store, fake_source):
    run = jobs.rescrape(store, "test")
    assert run["ok"] and run["count"] == 2 and run["added"] == 2
    assert not jobs.is_due(store, SOURCES["test"])

    fake_source["fail"] = True
    run = jobs.rescrape(store, "test")
    assert not run["ok"] and "upstream down" in run["error"]
    # old rows survive a failed pull
    assert store.count("test") == 2

    st = {s["source"]: s for s in jobs.status(store)}["test"]
    assert st["last_run_ok"] is False and st["last_ok_at"] is not None and not st["due"]


def test_due_after_interval(store, fake_source):
    jobs.rescrape(store, "test")
    later = datetime.now(timezone.utc) + timedelta(minutes=31)
    assert jobs.is_due(store, SOURCES["test"], now=later)


def test_enrich_job_upserts_and_tracks_coverage(store, monkeypatch):
    from dataclasses import replace

    def fetch(start, end):
        return [ev("a"), ev("b")]

    passes = {"n": 0}

    def enrich(events, known):
        # first pass describes one row, second pass the other, like a budget would
        passes["n"] += 1
        target = events[passes["n"] - 1]
        return [replace(e, summary="described") if e.id == target.id else e for e in events]

    src = Source("test", fetch, timedelta(minutes=30), enrich=enrich, enrich_every=timedelta(minutes=6))
    monkeypatch.setitem(SOURCES, "test", src)
    # scrape runs enrich once too, so one row is already described
    jobs.rescrape(store, "test")
    far = datetime.now(timezone.utc) + timedelta(days=30)
    assert store.enrichment("test", far) == (1, 2)
    assert jobs.is_enrich_due(store, src)

    run = jobs.enrich(store, "test")
    assert run["ok"] and run["count"] == 1 and run["job"] == "enrich"
    assert store.enrichment("test", far) == (2, 2)
    # everything described, nothing left to do
    assert not jobs.is_enrich_due(store, src)
    # the scrape log is untouched by enrich runs
    assert store.last_run("test")["job"] == "scrape"


def test_enrich_due_respects_interval(store, monkeypatch):
    def fetch(start, end):
        return [ev("a")]

    src = Source("test", fetch, timedelta(minutes=30), enrich=lambda evs, known: evs, enrich_every=timedelta(minutes=6))
    monkeypatch.setitem(SOURCES, "test", src)
    store.replace_source("test", [ev("a")])
    jobs.enrich(store, "test")
    assert not jobs.is_enrich_due(store, src)
    assert jobs.is_enrich_due(store, src, now=datetime.now(timezone.utc) + timedelta(minutes=7))
