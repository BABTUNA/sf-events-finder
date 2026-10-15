import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from sf_events.merge import dedupe, dedupe_key
from sf_events.models import Event
from sf_events.sources import luma

FIXTURE = Path(__file__).parent / "fixtures" / "luma_page.json"


def test_parse_shown_and_obfuscated_venues():
    page = json.loads(FIXTURE.read_text())
    shown = luma.parse(page["entries"][0])
    assert shown.id.startswith("luma:evt-")
    assert shown.source == "luma"
    assert shown.url == "https://luma.com/ddp_west_2026"
    assert shown.start == datetime(2026, 10, 15, 15, tzinfo=timezone.utc)
    assert shown.venue == "Embassy Suites by Hilton San Francisco Airport Oyster Point"
    assert shown.host == "DataDriven Pharma"
    assert shown.summary is None

    hidden = luma.parse(page["entries"][1])
    # obfuscated addresses only give the city
    assert hidden.venue is None
    assert hidden.location == "Palo Alto, CA"


def test_fetch_follows_cursor_and_filters_window(monkeypatch):
    page = json.loads(FIXTURE.read_text())
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        second = "pagination_cursor" in request.url.params
        return httpx.Response(200, json=dict(page, has_more=not second, next_cursor=None if second else "abc"))

    monkeypatch.setattr(luma.time, "sleep", lambda s: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    start = datetime(2026, 10, 15, 7, tzinfo=timezone.utc)
    events = luma.fetch(start, client=client)

    assert len(events) == 4
    assert [c.get("pagination_cursor") for c in calls] == [None, "abc"]
    assert calls[0]["west"] == "-122.7" and calls[0]["pagination_limit"] == "50"


def test_fetch_retries_transport_errors(monkeypatch):
    page = json.loads(FIXTURE.read_text())
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        if n["calls"] == 1:
            raise httpx.ConnectError("no route")
        return httpx.Response(200, json=dict(page, has_more=False))

    monkeypatch.setattr(luma.time, "sleep", lambda s: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert len(luma.fetch(datetime(2026, 1, 1, tzinfo=timezone.utc), client=client)) == 2
    assert n["calls"] == 2


def ev(source, url, **kw):
    base = dict(
        id=f"{source}:{url}", source=source, name="n", start=datetime(2026, 10, 20, 1, tzinfo=timezone.utc), end=None,
        url=url, location=None, venue=None, summary=None, kind=None, image_url=None,
    )
    return Event(**{**base, **kw})


def test_dedupe_key_normalizes_luma_urls():
    assert dedupe_key(ev("luma", "https://luma.com/Abc123")) == "luma:abc123"
    assert dedupe_key(ev("cerebralvalley", "https://lu.ma/abc123?utm_source=cv")) == "luma:abc123"
    assert dedupe_key(ev("cerebralvalley", "https://www.eventbrite.com/e/x/")) == "eventbrite.com/e/x"


def test_dedupe_prefers_luma_and_fills_summary():
    cv = ev("cerebralvalley", "https://luma.com/abc", summary="cv wrote this", kind="hackathon")
    lu = ev("luma", "https://luma.com/abc", venue="The Venue", host="Someone")
    other = ev("cerebralvalley", "https://www.meetup.com/x")
    out = {e.url: e for e in dedupe([cv, lu, other])}
    assert len(out) == 2
    m = out["https://luma.com/abc"]
    assert m.source == "luma" and m.venue == "The Venue" and m.host == "Someone"
    assert m.summary == "cv wrote this" and m.kind == "hackathon"
    assert m.also == ("cerebralvalley",)
    assert out["https://www.meetup.com/x"].also == ()


DETAIL = Path(__file__).parent / "fixtures" / "luma_detail.json"


def test_parse_detail_flattens_description_and_tags():
    d = luma.parse_detail(json.loads(DETAIL.read_text()))
    assert d["tags"] == ("ai",)
    assert d["summary"].startswith("Agentic AI is breaking the assumptions")
    assert len(d["summary"]) <= luma.SUMMARY_CHARS + 1
    assert d["summary"].endswith((".", "…"))


def test_enrich_only_near_events_and_reuses_known(monkeypatch):
    detail = json.loads(DETAIL.read_text())
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    soon = ev("luma", "https://luma.com/soon", start=now + luma.DETAIL_WINDOW / 2)
    cached = ev("luma", "https://luma.com/cached", start=now + luma.DETAIL_WINDOW / 2)
    far = ev("luma", "https://luma.com/far", start=now + luma.DETAIL_WINDOW * 2)
    known = {cached.id: Event(**{**cached.__dict__, "summary": "from last run", "tags": ("tech",)})}
    hit = []

    def handler(request):
        hit.append(request.url.params["url"])
        return httpx.Response(200, json=detail)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = {e.url: e for e in luma.enrich([soon, cached, far], known, now=now, client=client)}
    assert hit == ["soon"]
    assert out["https://luma.com/soon"].tags == ("ai",) and out["https://luma.com/soon"].summary
    assert out["https://luma.com/cached"].summary == "from last run" and out["https://luma.com/cached"].tags == ("tech",)
    assert out["https://luma.com/far"].summary is None
    # source tags show up as topics
    assert "ai" in out["https://luma.com/soon"].topics


def test_enrich_stops_at_first_rate_limit(monkeypatch):
    detail = json.loads(DETAIL.read_text())
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    evs = [ev("luma", f"https://luma.com/e{i}", start=now + timedelta(hours=i)) for i in range(6)]
    hit = []

    def handler(request):
        hit.append(request.url.params["url"])
        # first call is fine, the second trips the limit
        return httpx.Response(200, json=detail) if len(hit) == 1 else httpx.Response(429, json={"code": "api/rate-limit"})

    monkeypatch.setattr(luma, "DETAIL_WORKERS", 1)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = luma.enrich(evs, {}, now=now, client=client)
    # one enriched, then the pass stopped instead of hammering the other four
    assert sum(1 for e in out if e.summary) == 1
    assert hit == ["e0", "e1"]


def test_enrich_budget_takes_soonest_first():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    detail = json.loads(DETAIL.read_text())
    # out of order on purpose
    evs = [ev("luma", f"https://luma.com/e{i}", start=now + timedelta(days=d)) for i, d in enumerate([5, 1, 3])]
    hit = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (hit.append(r.url.params["url"]), httpx.Response(200, json=detail))[1]))
    import sf_events.sources.luma as mod
    old = mod.DETAIL_BUDGET
    mod.DETAIL_BUDGET = 2
    try:
        luma.enrich(evs, {}, now=now, client=client)
    finally:
        mod.DETAIL_BUDGET = old
    assert hit == ["e1", "e2"]
