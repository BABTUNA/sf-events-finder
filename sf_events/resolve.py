"""turn an event page url into an Event

used when a guest list arrives for an event no source listed, so the list
has a row to hang off. partiful event pages are server rendered with the
event in __NEXT_DATA__, luma has the public /url endpoint
"""

import json
import re

import httpx

from sf_events.models import Event
from sf_events.sources import luma, partiful

NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
SOURCE = "scraped"


def resolve(url: str, *, client: httpx.Client | None = None) -> Event | None:
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    try:
        if m := re.match(r"https?://(?:www\.)?partiful\.com/e/([^/?#]+)", url):
            return _partiful(client, url)
        if m := re.match(r"https?://(?:www\.)?(?:luma\.com|lu\.ma)/([^/?#]+)", url):
            return _luma(client, m.group(1))
        return None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    finally:
        if own:
            client.close()


def _partiful(client: httpx.Client, url: str) -> Event | None:
    r = client.get(url)
    r.raise_for_status()
    m = NEXT_DATA.search(r.text)
    if not m:
        return None
    ev = json.loads(m.group(1))["props"]["pageProps"].get("event")
    if not ev or "id" not in ev:
        return None
    e = partiful.parse(ev)
    return _as_scraped(e)


def _luma(client: httpx.Client, slug: str) -> Event | None:
    r = client.get(luma.DETAIL_API, params={"url": slug})
    if r.status_code != 200:
        return None
    data = r.json().get("data") or {}
    if not data.get("event"):
        return None
    raw = {k: data.get(k) for k in ("event", "hosts", "calendar", "ticket_info")}
    e = luma.parse(raw)
    detail = luma.parse_detail(r.json())
    from dataclasses import replace
    return _as_scraped(replace(e, summary=detail["summary"], tags=detail["tags"]))


def _as_scraped(e: Event) -> Event:
    # keep the real source's id so dedupe lines up if that source lists it later
    from dataclasses import replace
    return replace(e, source=SOURCE)
