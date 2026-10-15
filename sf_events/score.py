"""how worth going an event looks, 0 to 100, with the reasons

weighted keyword signals over name, summary, host and tags. the point is
to float the hackathons with prize pools, the rooms with investors and
founders, and the curated stuff, and to sink what you cannot attend or
would not learn from. tune the weights, they are the whole model
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sf_events.models import Event

# (reason, weight, pattern)
SIGNALS: list[tuple[str, int, str]] = [
    # "win" and "cash" alone fire on cash bars and winning smiles, keep it to prize words
    ("cash prizes", 30, r"prizes?\b|prize pool|cash prize|\bawards?\b|\bgrants?\b|\bbounty|winners?\b|\bcompete\b"),
    ("investors", 20, r"investors?\b|\bvcs?\b|venture|angels?\b|\bfunds?\b|fundrais|\bLPs?\b|general partners?\b|check ?size"),
    ("founders", 12, r"founders?\b|co-?founders?\b|\bceos?\b|startups?\b|\byc\b|y combinator"),
    ("hiring", 10, r"hiring|recruit|\bcareers?\b|job fair|\btalent\b|\bjobs?\b"),
    ("exclusive", 8, r"invite[- ]only|\bvip\b|\bexclusive|intimate|curated|approval required|\bdinner\b|12-person|\bsalon\b"),
    ("free food", 3, r"free (food|drinks|lunch|dinner|pizza|coffee)|complimentary|\bcatered|food (and|&) drinks"),
    ("remote", -15, r"\bremote\b|\bvirtual\b|\bwebinar|\bzoom\b|\bonline\b"),
    ("not tech", -12, r"\byoga\b|\bmeditation|\bwellness|\bfitness|\bhike\b|\brun club|\btrivia|\bkaraoke|\bbook club|\bsound bath|\bbreathwork|\bpickleball|\bsinging"),
]

# people and orgs whose rooms tend to be worth it
NOTABLE = r"anthropic|openai|deepmind|a16z|andreessen|sequoia|y combinator|\byc\b|nvidia|\bmeta\b|microsoft|\baws\b|google|south park commons|founders inc|\bhf0\b|pear vc|general catalyst|lightspeed|benchmark|khosla|greylock|accel\b|index ventures|first round|bessemer|kleiner|insight partners|thrive capital|techstars|stripe|vercel|cloudflare|modal\b|databricks|snowflake|mistral|cohere|scale ai|perplexity|cursor|replit|hugging ?face|pytorch|linux foundation|cerebral valley|ai engineer|latent space"

FORMAT_BONUS = {"hackathon": 12, "demo": 10, "conference": 4, "talk": 2, "workshop": 2}
MONEY = re.compile(r"\$\s?(\d[\d,]*)(\s?k\b)?", re.I)


def score(e: Event) -> tuple[int, list[str]]:
    text = f"{e.name} {e.summary or ''} {e.host or ''}"
    low = text.lower()
    total, reasons = 0, []

    for reason, weight, rx in SIGNALS:
        if re.search(rx, text, re.I):
            total += weight
            reasons.append(reason)

    # a dollar figure next to prize words is the strongest single signal
    if "cash prizes" in reasons:
        amounts = [_dollars(m) for m in MONEY.finditer(text)]
        if amounts and max(amounts) >= 10_000:
            total += 15
            reasons.append(f"${max(amounts):,.0f} on the table")

    if re.search(NOTABLE, text, re.I):
        total += 10
        reasons.append("notable host")

    if e.format in FORMAT_BONUS:
        total += FORMAT_BONUS[e.format]
        reasons.append(e.format)

    if "cerebralvalley" in (e.source, *e.also):
        total += 10
        reasons.append("cv curated")

    if "ai" in e.tags or "tech" in e.tags:
        total += 3
    elif e.tags:
        # luma tagged it something else entirely and nothing above fired
        total -= 8
        reasons.append("tagged " + ", ".join(e.tags))

    if e.sold_out:
        total -= 40
        reasons.append("sold out")
    if e.free:
        total += 2

    return max(0, min(100, total)), reasons


def _dollars(m: re.Match) -> float:
    n = float(m.group(1).replace(",", ""))
    return n * 1000 if m.group(2) else n
