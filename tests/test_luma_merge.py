import json
from datetime import datetime, timezone
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
