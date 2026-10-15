# sf-events-finder

One list of upcoming AI and tech events in the SF Bay Area. Cerebral Valley and Luma today, X next. Everything defaults to the Bay Area because that is the only place I am looking.

```bash
uv sync
uv run sf-events                       # next 7 days, grouped by day (pulls first if the store is stale)
uv run sf-events rescrape              # pull every source now
uv run sf-events status                # when each source last ran, and whether it failed
uv run sf-events --days 30             # further out
uv run sf-events --search hackathon    # filter by name or summary
uv run sf-events --format talk --topic agents   # categories, see below
uv run sf-events --source cerebralvalley        # only what cerebral valley lists
uv run sf-events --all --json > out.json
```

Output looks like:

```
Thu Oct 15
   8:00 AM  LlamaIndex x Corgi: Doc Chai Launch Party
            Corgi Cafe, San Francisco, CA  ·  https://luma.com/llamai-68ea
   9:00 AM  The Recursive Agents Hackathon [hackathon]
            San Francisco, CA  ·  https://cerebralvalley.ai/e/crusoe-recursive-agents-hackathon
```

## Web UI

```bash
uv run sf-events-web      # http://127.0.0.1:8765
```

One page, same data. Pick a source (both, Luma, Cerebral Valley), a range (7, 14, 30 days or everything), click format and topic chips to narrow. Chip counts show what each click would leave. Every row carries a pill per source that lists it, pink for Luma and blue for Cerebral Valley, and the time column stripe matches. The bars across the top are events per day, click one to jump to that day. Rows link straight to the registration page. The header shows each source with its count and last pull, and the ↻ button rescrapes it right now.

![web ui](docs/web.png)

## Dedupe

Cerebral Valley mostly republishes Luma links, so [sf_events/merge.py](sf_events/merge.py) collapses events across sources at read time. The key is the Luma slug when the URL is a Luma URL, otherwise the URL with tracking stripped. The Luma record wins on fields, Cerebral Valley fills in the summary it wrote, and the merged event carries `also: ["cerebralvalley"]`. In the UI a merged event shows both pills. In the CLI the source column reads `luma`, `cv`, or `luma+cv`. Cerebral Valley listing something is a decent curation signal in a list of 1,200.

## Categories

Cerebral Valley only labels its own hackathons, so categories are keyword rules over the name and summary in [sf_events/categorize.py](sf_events/categorize.py). Two axes:

- **format**, one per event, first matching rule wins and the title is checked before the summary: hackathon, conference, workshop, demo, talk, social, meetup, or other.
- **topics**, any that match: agents, coding, infra, data, robotics, security, founders, research, health, open source, design.

On a 236 event pull, 13 fell through to other. If that gets annoying the next step is a small model pass over the leftovers, not more regex.

## Store and rescrape jobs

Scraped events live in `data/events.db` (SQLite, gitignored, override with `SF_EVENTS_DB`). Each source has its own interval in [sf_events/sources/__init__.py](sf_events/sources/__init__.py), 30 minutes for Cerebral Valley. A rescrape replaces that source's rows with what it returned and logs a row in `runs` with count, added, removed, and any error. A failed pull keeps the old rows.

Three ways a rescrape happens:

- `sf-events rescrape [source]` runs one now.
- `sf-events` (list) first pulls any source past its interval, `--stale` skips that.
- the web server runs a background thread that checks every minute and pulls whatever is due. The ↻ button in the UI calls `POST /api/rescrape/{source}`.

`sf-events status` and `GET /api/status` show per source: count, last successful pull, last error, next due. See [sf_events/store.py](sf_events/store.py) and [sf_events/jobs.py](sf_events/jobs.py).

## Sources

**luma** The map at luma.com/ai/map is fed by a public discover endpoint that takes a bounding box, so one box over the Bay Area walks every discoverable event behind every dot, no slug and no clicking:

```
GET https://api.luma.com/discover/get-paginated-events?west=-122.7&east=-121.7&south=37.2&north=38.1&pagination_limit=50[&pagination_cursor=...]
```

About 1,200 upcoming events, 50 per page, no auth. Entries carry no description, so a second pass fetches `GET https://api.luma.com/url?url=<slug>` for events starting in the next two weeks and keeps the description (clipped to a short summary) and Luma's own category tags, which show up as topics (`ai`, `tech`, `arts & culture`). That endpoint allows about 70 calls before a 429 and then blocks for around five minutes, so each run fetches at most 60, soonest events first, and stops at the first 429. Rows already in the store keep their summary, so each event costs one detail call ever and the two-week window fills in over the hourly runs. Roughly a quarter of the Luma events Cerebral Valley lists are not marked discoverable and never appear here, which is why both sources stay. See [sf_events/sources/luma.py](sf_events/sources/luma.py).

**cerebralvalley** The events page is a Next.js app that fills itself from a public JSON API, so the scraper calls that instead of parsing HTML:

```
GET https://api.cerebralvalley.ai/v1/public/event/pull?approved=true&locations=BAY_AREA&startDateTime=<utc iso>&limit=100&offset=0
```

Pages cap at 100. Timestamps are naive strings in UTC. Most entries are Luma links the Cerebral Valley team approved, a handful are their own hackathons. See [sf_events/sources/cerebralvalley.py](sf_events/sources/cerebralvalley.py).

Adding a source means one module with `fetch(start, end) -> list[Event]` and a `Source(name, fetch, every)` line in [sf_events/sources/__init__.py](sf_events/sources/__init__.py). It gets its own rescrape job, status row, and header chip for free. `Event` is in [sf_events/models.py](sf_events/models.py).

## Tests

```bash
uv run pytest
```
