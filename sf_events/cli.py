import argparse
import json
import sys
from datetime import datetime, timedelta

from sf_events import jobs
from sf_events.categorize import FORMATS, TOPICS
from sf_events.models import PACIFIC, Event
from sf_events.sources import SOURCES
from sf_events.store import Store

COMMANDS = ("list", "rescrape", "status")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `sf-events` alone lists, so the subcommand is optional
    cmd = argv.pop(0) if argv and argv[0] in COMMANDS else "list"
    store = Store()
    return {"list": cmd_list, "rescrape": cmd_rescrape, "status": cmd_status}[cmd](store, argv)


def cmd_rescrape(store: Store, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sf-events rescrape", description="pull a source again now")
    p.add_argument("source", nargs="*", choices=sorted(SOURCES), help="default: every source")
    args = p.parse_args(argv)
    ok = True
    for name in args.source or sorted(SOURCES):
        run = jobs.rescrape(store, name)
        ok &= bool(run["ok"])
        print(_run_line(run))
    return 0 if ok else 1


def cmd_status(store: Store, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sf-events status", description="when each source last ran")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    st = jobs.status(store)
    if args.json:
        json.dump(st, sys.stdout, indent=1)
        print()
        return 0
    for s in st:
        when = _local(s["last_ok_at"]) if s["last_ok_at"] else "never"
        line = f"{s['source']:16} {s['count']:4} events   last ok {when}   every {s['every_minutes']}m"
        if s["due"]:
            line += "   due"
        if s["last_run_ok"] is False:
            line += f"\n{'':16} last run failed: {s['last_error']}"
        print(line)
    return 0


def cmd_list(store: Store, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sf-events", description="upcoming sf bay area ai events")
    p.add_argument("--days", type=int, default=7, help="how far ahead to look (default 7)")
    p.add_argument("--all", action="store_true", help="ignore --days, show everything the sources know")
    p.add_argument("--search", help="only events whose name or summary contains this (case-insensitive)")
    p.add_argument("--format", choices=FORMATS, action="append", help="hackathon, talk, social... repeatable")
    p.add_argument("--topic", choices=TOPICS, action="append", help="agents, infra, robotics... repeatable")
    p.add_argument("--source", choices=sorted(SOURCES), action="append", help="limit to a source, repeatable")
    p.add_argument("--stale", action="store_true", help="read what is stored even if a source is past its interval")
    p.add_argument("--json", action="store_true", help="print json instead of the table")
    p.add_argument("--out", help="also write json here")
    args = p.parse_args(argv)

    # sources past their interval get pulled first unless told not to
    if not args.stale:
        for run in jobs.rescrape_due(store, log=sys.stderr):
            if not run["ok"]:
                print(f"{run['source']}: {run['error']} (showing what was stored)", file=sys.stderr)

    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = None if args.all else start + timedelta(days=args.days)
    events: list[Event] = []
    for name in args.source or sorted(SOURCES):
        events.extend(e for e in store.events(name) if e.start >= start and (end is None or e.start < end))

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


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(PACIFIC).strftime("%a %-I:%M %p")


def _run_line(run: dict) -> str:
    if run["ok"]:
        return f"{run['source']}: {run['count']} events, +{run['added']} -{run['removed']}"
    return f"{run['source']}: failed, {run['error']}"


if __name__ == "__main__":
    sys.exit(main())
