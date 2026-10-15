"""derive categories from an event's name and summary

cerebral valley only types its own hackathons, everything else comes back
blank, so categories are keyword rules over the text. two axes:

    format  one per event, the first rule that matches wins
    topics  zero or more, every rule that matches

rules are ordered so the more specific format beats the more generic one,
a "fireside chat at the kickoff party" is a talk, not a social
"""

import re

FORMAT_RULES: list[tuple[str, str]] = [
    ("hackathon", r"hackathon|hack ?day|build ?day|buildathon|field day|genjam|game jam"),
    ("conference", r"\bconference|\bsummit\b|\bexpo\b|\bforum\b|\bdevworld|\bsymposium|ai week\b|\bfest\b|\b\w+con\b"),
    ("workshop", r"workshop|hands-on|bootcamp|office hours|tutorial|masterclass|\btraining\b|\bclass\b|\bmastering\b"),
    ("demo", r"demo ?day|demo ?night|\bdemos\b|\bpitch|showcase|\blaunch|opening night|showdown|\bmem-off"),
    ("talk", r"fireside|\bpanel|\btalks?\b|keynote|speaker|lecture|seminar|discussion|conversations?\b|q&a|dialogue|\binside the\b|\bw/ |\bwith (dr\.|[A-Z][a-z]+ [A-Z])"),
    ("social", r"\bparty|after ?hours|afterparty|\bdinner|\bbrunch|\blunch|breakfast|happy hour|\bdrinks\b|\bmixer|trivia|\bnight\b|coffee|\brun\b|celebration|\bsocial\b"),
    ("meetup", r"meet-?up|networking|open house|gathering|exchange|working group|\bcommunity\b"),
]

TOPIC_RULES: list[tuple[str, str]] = [
    ("agents", r"\bagents?\b|agentic|mcp\b"),
    ("coding", r"claude code|coding|\bcode\b|developer|dev ?tools|cursor|copilot|software"),
    ("infra", r"inference|\bgpus?\b|compute|infra|kubernetes|scal(e|ing)|cloud|nvidia|reliability|\bops\b"),
    ("data", r"\bdata\b|database|analytics|\bsql\b|snowflake|tidb|pytorch"),
    ("robotics", r"robot|humanoid|hardware|embodied|\bdrones?\b"),
    ("security", r"security|privacy|zero trust|cyber|\btrust\b"),
    ("founders", r"founders?|startups?|\bvcs?\b|investors?|fundrais|venture|seed|series a|pitch"),
    ("research", r"research|\bpaper|neurips|superintelligence|scientific|science|\bphd\b|lab\b"),
    ("health", r"health|medic|\bbio\b|biology|clinic|patient"),
    ("open source", r"open[- ]source|\boss\b|llama\b|hugging ?face"),
    ("design", r"design|creativ|\bart\b|artist|film|music"),
]

_FORMAT = [(f, re.compile(rx, re.I)) for f, rx in FORMAT_RULES]
_TOPIC = [(t, re.compile(rx, re.I)) for t, rx in TOPIC_RULES]

FORMATS = [f for f, _ in FORMAT_RULES] + ["other"]
TOPICS = [t for t, _ in TOPIC_RULES]


def event_format(name: str, summary: str | None, kind: str | None) -> str:
    # the source's own label wins when it has one
    if kind in dict(FORMAT_RULES):
        return kind
    # the title is the strongest signal, summaries mention everything
    for text in (name, summary or ""):
        for fmt, rx in _FORMAT:
            if rx.search(text):
                return fmt
    return "other"


def event_topics(name: str, summary: str | None) -> tuple[str, ...]:
    text = f"{name} {summary or ''}"
    return tuple(t for t, rx in _TOPIC if rx.search(text))
