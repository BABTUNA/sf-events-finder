from sf_events.sources import cerebralvalley

# name -> fetch(start, end) -> list[Event]
# luma and x slot in here when they land
SOURCES = {
    "cerebralvalley": cerebralvalley.fetch,
}
