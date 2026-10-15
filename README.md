# sf-events-finder

One list of upcoming AI events in the SF Bay Area, pulled live. Cerebral Valley today, Luma and X next. Everything defaults to the Bay Area because that is the only place I am looking.

```bash
uv sync
uv run sf-events                       # next 7 days, grouped by day
uv run sf-events --days 30             # further out
uv run sf-events --search hackathon    # filter by name or summary
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

## Sources

**cerebralvalley** The events page is a Next.js app that fills itself from a public JSON API, so the scraper calls that instead of parsing HTML:

```
GET https://api.cerebralvalley.ai/v1/public/event/pull?approved=true&locations=BAY_AREA&startDateTime=<utc iso>&limit=100&offset=0
```

Pages cap at 100. Timestamps are naive strings in UTC. Most entries are Luma links the Cerebral Valley team approved, a handful are their own hackathons. See [sf_events/sources/cerebralvalley.py](sf_events/sources/cerebralvalley.py).

Adding a source means one module with `fetch(start, end) -> list[Event]` and a line in [sf_events/sources/__init__.py](sf_events/sources/__init__.py). `Event` is in [sf_events/models.py](sf_events/models.py).

## Tests

```bash
uv run pytest
```
