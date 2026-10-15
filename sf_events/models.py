from dataclasses import dataclass, asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from sf_events.categorize import event_format, event_topics

# everything is for the bay area, so display times are always pacific
PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class Event:
    # stable id from the source, prefixed so ids never collide across sources
    id: str
    source: str
    name: str
    # tz-aware utc
    start: datetime
    end: datetime | None
    url: str
    location: str | None
    venue: str | None
    summary: str | None
    # hackathon, conference, meetup, or None when the source does not say
    kind: str | None
    image_url: str | None

    @property
    def start_local(self) -> datetime:
        return self.start.astimezone(PACIFIC)

    @property
    def end_local(self) -> datetime | None:
        return self.end.astimezone(PACIFIC) if self.end else None

    @property
    def format(self) -> str:
        # hackathon, conference, workshop, demo, talk, social, meetup, other
        return event_format(self.name, self.summary, self.kind)

    @property
    def topics(self) -> tuple[str, ...]:
        return event_topics(self.name, self.summary)

    @property
    def where(self) -> str:
        # "Corgi Cafe, San Francisco, CA" or just the city when there is no venue
        parts = [p for p in (self.venue, self.location) if p]
        return ", ".join(dict.fromkeys(parts))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat() if self.end else None
        d["start_local"] = self.start_local.isoformat()
        d["where"] = self.where
        d["format"] = self.format
        d["topics"] = list(self.topics)
        return d
