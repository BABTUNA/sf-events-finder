"""sqlite store for scraped events and the runs that produced them

one file at data/events.db (override with SF_EVENTS_DB). events are kept as
json blobs keyed by id, with first_seen so "new since yesterday" is possible
later. runs is the job log, one row per rescrape per source
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sf_events.models import Event

DEFAULT_DB = Path(os.environ.get("SF_EVENTS_DB") or Path(__file__).resolve().parent.parent / "data" / "events.db")

SCHEMA = """
create table if not exists events (
    id text primary key,
    source text not null,
    data text not null,
    first_seen text not null,
    last_seen text not null
);
create index if not exists events_source on events(source);
create table if not exists runs (
    id integer primary key,
    source text not null,
    started_at text not null,
    finished_at text,
    ok integer,
    count integer,
    added integer,
    removed integer,
    error text
);
create index if not exists runs_source on runs(source, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # events

    def replace_source(self, source: str, events: list[Event]) -> tuple[int, int]:
        """make the store match what the source just returned, returns (added, removed)"""
        now = _now()
        with self._conn() as c:
            before = {r["id"] for r in c.execute("select id from events where source = ?", (source,))}
            ids = {e.id for e in events}
            c.executemany(
                """insert into events (id, source, data, first_seen, last_seen) values (?, ?, ?, ?, ?)
                   on conflict(id) do update set data = excluded.data, last_seen = excluded.last_seen""",
                [(e.id, source, json.dumps(e.to_dict()), now, now) for e in events],
            )
            gone = before - ids
            if gone:
                c.executemany("delete from events where id = ?", [(i,) for i in gone])
        return len(ids - before), len(gone)

    def events(self, source: str | None = None) -> list[Event]:
        q = "select data from events" + (" where source = ?" if source else "")
        with self._conn() as c:
            rows = c.execute(q, (source,) if source else ()).fetchall()
        return [Event.from_dict(json.loads(r["data"])) for r in rows]

    # runs

    def start_run(self, source: str) -> int:
        with self._conn() as c:
            cur = c.execute("insert into runs (source, started_at) values (?, ?)", (source, _now()))
            return cur.lastrowid

    def finish_run(self, run_id: int, *, ok: bool, count: int = 0, added: int = 0, removed: int = 0, error: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "update runs set finished_at = ?, ok = ?, count = ?, added = ?, removed = ?, error = ? where id = ?",
                (_now(), int(ok), count, added, removed, error, run_id),
            )

    def last_run(self, source: str, ok_only: bool = False) -> dict | None:
        q = "select * from runs where source = ? and finished_at is not null" + (" and ok = 1" if ok_only else "") + " order by id desc limit 1"
        with self._conn() as c:
            r = c.execute(q, (source,)).fetchone()
        return dict(r) if r else None

    def count(self, source: str) -> int:
        with self._conn() as c:
            return c.execute("select count(*) from events where source = ?", (source,)).fetchone()[0]
