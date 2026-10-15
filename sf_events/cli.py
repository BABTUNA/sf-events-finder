import argparse
import json
import sys
from datetime import datetime, timedelta

from sf_events.categorize import FORMATS, TOPICS
from sf_events.models import PACIFIC, Event
from sf_events.sources import SOURCES


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="sf-events",
        description="upcoming sf bay area ai events, pulled live",
    )
    p.add_argument("--days", type=int, default=7, help="how far ahead to look (default 7)")
    p.add_argument("--all", action="store_true", help="ignore --days, show everything the sources know")
    p.add_argument("--search", help="only events whose name or summary contains this (case-insensitive)")
    p.add_argument("--format", choices=FORMATS, action="append", help="hackathon, talk, social... repeatable")
    p.add_argument("--topic", choices=TOPICS, action="append", help="agents, infra, robotics... repeatable")
    p.add_argument("--source", choices=sorted(SOURCES), action="append", help="limit to a source, repeatable")
    p.add_argument("--json", action="store_true", help="print json instead of the table")
    p.add_argument("--out", help="also write json here")
    args = p.parse_args(argv)

    # match the site: everything from the start of today, pacific
    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = None if args.all else start + timedelta(days=args.days)

    events: list[Event] = []
    for name in args.source or sorted(SOURCES):
        try:
            events.extend(SOURCES[name](start, end))
        except Exception as e:
            print(f"{name}: {e}", file=sys.stderr)

    if args.search:
        q = args.search.lower()
        events = [e for e in events if q in e.name.lower() or q in (e.summary or "").lower()]
    if args.format:
        events = [e for e in events if e.format in args.format]
    if args.topic:
        events = [e for e in events if set(e.topics) & set(args.topic)]
    events.sort(key=lambda e: (e.start, e.name))

    if args.out:
        with open(args.out, "w") as f:
            json.dump([e.to_dict() for e in events], f, indent=1)
    if args.json:
        json.dump([e.to_dict() for e in events], sys.stdout, indent=1)
        print()
    else:
        print_table(events)
    return 0


def print_table(events: list[Event]) -> None:
    if not events:
        print("nothing found")
        return
    day = None
    for e in events:
        d = e.start_local.date()
        if d != day:
            day = d
            print(f"\n{e.start_local:%a %b %-d}")
        t = e.start_local.strftime("%-I:%M %p").rjust(8)
        tags = " ".join(f"#{x}" for x in (e.format, *e.topics) if x != "other")
        print(f"  {t}  {e.name}  {tags}")
        print(f"            {e.where}  ·  {e.url}")
    print(f"\n{len(events)} events")


if __name__ == "__main__":
    sys.exit(main())
