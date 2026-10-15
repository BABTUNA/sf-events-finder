from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sf_events.models import Event
from sf_events.sources import cerebralvalley


@dataclass(frozen=True)
class Source:
    name: str
    # fetch(start, end) -> every event starting in that window
    fetch: Callable[[datetime, datetime | None], list[Event]]
    # how stale a scrape can get before the next job runs
    every: timedelta


# luma and x slot in here when they land, each with its own cadence
SOURCES: dict[str, Source] = {
    s.name: s
    for s in (
        Source("cerebralvalley", cerebralvalley.fetch, timedelta(minutes=30)),
    )
}
