import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from sf_events.sources import cerebralvalley

FIXTURE = Path(__file__).parent / "fixtures" / "cerebralvalley_page.json"


def test_parse_normalizes_fields():
    raw = json.loads(FIXTURE.read_text())["events"]
    cv = cerebralvalley.parse(raw[0])
    assert cv.id == "cv:4b97e076-eeed-4b34-9b28-1820cbb08958"
    assert cv.source == "cerebralvalley"
    assert cv.kind == "hackathon"
    # naive api string is utc, 16:00Z is 9am pacific
    assert cv.start == datetime(2026, 10, 17, 16, tzinfo=timezone.utc)
    assert cv.start_local.hour == 9

    luma = cerebralvalley.parse(raw[1])
    assert luma.url.startswith("https://luma.com/")
    assert luma.venue and luma.where.startswith(luma.venue)

    untyped = cerebralvalley.parse(raw[2])
    assert untyped.kind is None


def test_fetch_pages_until_last(monkeypatch):
    page = json.loads(FIXTURE.read_text())
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        offset = int(request.url.params["offset"])
        # two pages, the second is marked last
        body = dict(page, offset=offset, lastPage=offset > 0)
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    start = datetime(2026, 10, 15, 7, tzinfo=timezone.utc)
    events = cerebralvalley.fetch(start, client=client)

    assert len(events) == 6
    assert [c["offset"] for c in calls] == ["0", "100"]
    assert calls[0]["locations"] == "BAY_AREA"
    assert calls[0]["startDateTime"] == "2026-10-15T07:00:00.000Z"
