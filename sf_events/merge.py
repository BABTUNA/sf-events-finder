"""collapse the same event listed by more than one source

cerebral valley mostly republishes luma links, so the key is the luma slug
when the url is a luma url, else the url itself with tracking stripped.
the luma record wins on fields (venue, coordinates, times come from the
host), cerebral valley fills in the summary it wrote, and `also` records
who else had it
"""

from dataclasses import replace
from urllib.parse import urlsplit

from sf_events.models import Event

# more authoritative first
PREFER = ("luma", "cerebralvalley")


def dedupe_key(e: Event) -> str:
    u = urlsplit(e.url)
    host = u.netloc.lower().removeprefix("www.")
    path = u.path.strip("/")
    if host in ("luma.com", "lu.ma"):
        return f"luma:{path.lower()}"
    return f"{host}/{path.lower()}"


def dedupe(events: list[Event]) -> list[Event]:
    groups: dict[str, list[Event]] = {}
    for e in events:
        groups.setdefault(dedupe_key(e), []).append(e)
    out = []
    for group in groups.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda e: PREFER.index(e.source) if e.source in PREFER else len(PREFER))
        base, *rest = group
        merged = replace(
            base,
            summary=base.summary or next((r.summary for r in rest if r.summary), None),
            kind=base.kind or next((r.kind for r in rest if r.kind), None),
            venue=base.venue or next((r.venue for r in rest if r.venue), None),
            host=base.host or next((r.host for r in rest if r.host), None),
            also=tuple(dict.fromkeys(r.source for r in rest if r.source != base.source)),
        )
        out.append(merged)
    return out
