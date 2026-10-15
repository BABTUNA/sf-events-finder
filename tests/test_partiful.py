from datetime import datetime, timezone
from pathlib import Path

import httpx

from sf_events.merge import dedupe_key
from sf_events.models import Event
from sf_events.sources import partiful

FIXTURE = Path(__file__).parent / "fixtures" / "partiful_explore.html"


def test_parse_page_merges_sections_into_tags():
    events = {e.name: e for e in partiful.parse_page(FIXTURE.read_text())}
    assert len(events) == 2
    a = events["Date My Ex ❤️‍🔥"]
    assert a.id == "partiful:inL3CAQCBCPIwQvOjKYa"
    assert a.url == "https://partiful.com/e/inL3CAQCBCPIwQvOjKYa"
    assert a.start == datetime(2026, 10, 18, 2, tzinfo=timezone.utc)
    assert a.venue == "Kilowatt" and a.location == "San Francisco, CA"
    assert a.summary and len(a.summary) <= partiful.SUMMARY_CHARS + 1
    # it sits in trending and in a themed section, both become tags
    assert a.tags == ("trending in the bay", "meet new people")
    assert a.image_url and a.image_url.startswith("https://")


def test_fetch_filters_window_and_uses_browser_ua():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text=FIXTURE.read_text())

    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "Mozilla/5.0"})
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert len(partiful.fetch(start, client=client)) == 2
    assert len(partiful.fetch(datetime(2027, 1, 1, tzinfo=timezone.utc), client=client)) == 0
    assert seen["ua"].startswith("Mozilla")


def test_parse_page_without_next_data_raises():
    try:
        partiful.parse_page("<html>nope</html>")
    except ValueError as e:
        assert "layout changed" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_dedupe_key_matches_cv_partiful_links():
    cv = Event(
        id="cv:1", source="cerebralvalley", name="x", start=datetime(2026, 10, 20, tzinfo=timezone.utc), end=None,
        url="https://partiful.com/e/STg1eJrPTO14OpwysakA", location=None, venue=None, summary=None, kind=None, image_url=None,
    )
    assert dedupe_key(cv) == "partiful:STg1eJrPTO14OpwysakA"
