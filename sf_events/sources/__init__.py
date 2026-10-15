from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from sf_events.models import Event
from sf_events.sources import cerebralvalley, luma


@dataclass(frozen=True)
class Source:
    name: str
    # fetch(start, end) -> every event starting in that window
    fetch: Callable[[datetime, datetime | None], list[Event]]
    # how stale a scrape can get before the next job runs
    every: timedelta
    # optional second pass after fetch: enrich(events, known_by_id) -> events
    # gets the rows already stored so it can skip work it did last time
    enrich: Optional[Callable[[list[Event], dict[str, Event]], list[Event]]] = None
    # how often the enrich step runs on its own, between full scrapes
    enrich_every: timedelta = timedelta(minutes=6)
    # how far ahead enrichment reaches, for the coverage number in status
    enrich_window: timedelta = timedelta(days=14)


# luma and x slot in here when they land, each with its own cadence
SOURCES: dict[str, Source] = {
    s.name: s
    for s in (
        Source("cerebralvalley", cerebralvalley.fetch, timedelta(minutes=30)),
        Source("luma", luma.fetch, timedelta(hours=1), enrich=luma.enrich),
    )
}
