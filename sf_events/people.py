"""who is in the room

guests come from the browser extension as {name, bio, links}. bios are
free text people wrote about themselves ("Founder @ Gemphere", "eecs @
berkeley", "CEO of PopDrop.ai"), so this is keyword rules again. each
guest gets tags and a weight, the event gets counts and a notable list
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from sf_events.score import NOTABLE

# (tag, weight, pattern over the bio)
ROLE_RULES: list[tuple[str, int, str]] = [
    ("investor", 10, r"\binvestor|\bvc\b|venture|\bangel\b|\bpartner\b|\bgp\b|general partner|\bprincipal\b|\bfund\b|capital\b|\bLP\b"),
    ("founder", 6, r"\bfounder|co-?founder|\bceo\b|\bbuilding\b|\bstealth\b|\byc\b|\bstartup\b"),
    ("exec", 5, r"\bcto\b|\bcoo\b|\bcpo\b|\bcfo\b|\bvp\b|\bhead of\b|\bdirector\b|\bchief\b|managing director"),
    ("researcher", 3, r"\bresearch|\bphd\b|\bprofessor|\bscientist|\bbair\b|\bcsail\b|\bpostdoc"),
    ("engineer", 1, r"\bengineer|\bswe\b|\bmts\b|\bdeveloper\b|\beng\b"),
    # no \b before @, there is no word boundary between a space and a symbol
    ("student", 0, r"\bstudent|\bundergrad|@ ?(uc )?berkeley\b|\bstanford\b|\bmit\b|\bcs @|\beecs\b|\bclass of\b"),
]

# a linkedin link in the bio or links usually means they want to be found
LINKEDIN = re.compile(r"linkedin\.com/in/", re.I)
TOP_N = 12
# someone who has hosted this many luma events is a connector worth knowing
HOST_MIN = 3

# luma's guest modal has no bios, but its public profile api does
LUMA_PROFILE = "https://api.luma.com/user/profile"
LUMA_USER = re.compile(r"https?://(?:www\.)?(?:luma\.com|lu\.ma)/user/([^/?#]+)", re.I)
PROFILE_WORKERS = 3
PROFILE_BUDGET = 250


# what a search-backed read adds, on top of the bio rules
LOOKUP_WEIGHT = {"investor": 12, "founder": 8, "exec": 6, "researcher": 4, "engineer": 1, "operator": 1, "student": 0, "unknown": 0}


def tag_guest(g: dict, lookup: dict | None = None) -> dict:
    bio = (g.get("bio") or "").strip()
    links = [l for l in (g.get("links") or []) if l]
    text = f"{bio} {' '.join(links)}"
    tags, weight = [], 0
    for tag, w, rx in ROLE_RULES:
        if re.search(rx, text, re.I):
            tags.append(tag)
            weight += w
    org = re.search(NOTABLE, text, re.I)
    if org:
        tags.append(f"@{org.group(0).lower()}")
        weight += 4
    if LINKEDIN.search(text):
        weight += 1
    if (g.get("hosted") or 0) >= HOST_MIN:
        tags.append("host")
        weight += 3
    out = {"name": g.get("name", "").strip(), "bio": bio, "links": links, "tags": tags, "weight": weight, "hosted": g.get("hosted")}
    if lookup and lookup.get("pending"):
        lookup = None
    if lookup and lookup.get("role") and lookup["role"] != "unknown":
        role = lookup["role"]
        if role not in tags:
            tags.append(role)
        w = LOOKUP_WEIGHT.get(role, 0) + (4 if lookup.get("worth_meeting") else 0)
        if lookup.get("confidence") == "low":
            w //= 2
        weight += w
        if lookup.get("company"):
            tags.append("@" + lookup["company"].lower())
        out.update(weight=weight, headline=lookup.get("headline") or "", reason=lookup.get("reason") or "",
                   confidence=lookup.get("confidence"), evidence=[e.get("url") for e in lookup.get("evidence") or []][:3])
        # a search hit with a linkedin url is a link worth having
        for e in lookup.get("evidence") or []:
            if e.get("url") and e["url"] not in out["links"] and "linkedin.com/in/" in e["url"]:
                out["links"].append(e["url"])
    elif lookup:
        out.update(confidence=lookup.get("confidence"), reason=lookup.get("reason") or "")
    return out


def enrich_luma(guests: list[dict], *, client: httpx.Client | None = None) -> list[dict]:
    """fill bio and links for guests whose only link is a luma profile

    one call per guest to the public profile api, a few wide, stop at the
    first 429. guests that already have a bio are left alone
    """
    todo = []
    for i, g in enumerate(guests):
        if g.get("bio"):
            continue
        user = next((m.group(1) for l in g.get("links") or [] if (m := LUMA_USER.match(l))), None)
        if user:
            todo.append((i, user))
    todo = todo[:PROFILE_BUDGET]
    if not todo:
        return guests
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20, connect=10), headers={"User-Agent": "Mozilla/5.0"})
    limited = threading.Event()
    out = [dict(g) for g in guests]
    try:
        with ThreadPoolExecutor(PROFILE_WORKERS) as pool:
            for (i, _), prof in zip(todo, pool.map(lambda t: _profile(client, t[1], limited), todo)):
                if prof:
                    extra = prof.pop("profile_links", [])
                    out[i].update(prof)
                    out[i]["links"] = list(dict.fromkeys((out[i].get("links") or []) + extra))
    finally:
        if own:
            client.close()
    return out


def _profile(client: httpx.Client, user: str, limited: threading.Event) -> dict | None:
    if limited.is_set():
        return None
    for attempt in range(3):
        try:
            r = client.get(LUMA_PROFILE, params={"username": user})
        except httpx.TransportError:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            limited.set()
            return None
        if r.status_code != 200:
            return None
        try:
            return parse_profile(r.json())
        except (ValueError, KeyError, TypeError):
            return None
    return None


def parse_profile(body: dict) -> dict:
    u = body.get("user") or {}
    links = []
    li = u.get("linkedin_handle")
    if li:
        links.append(li if li.startswith("http") else "https://www.linkedin.com" + (li if li.startswith("/") else "/in/" + li))
    if u.get("twitter_handle"):
        links.append("https://x.com/" + u["twitter_handle"].lstrip("@"))
    if u.get("website"):
        links.append(u["website"])
    return {
        "bio": (u.get("bio_short") or "").strip(),
        "profile_links": links,
        "hosted": body.get("event_hosted_count") or 0,
        "attended": body.get("event_attended_count") or 0,
    }


def analyze(guests: list[dict], lookups: dict[str, dict] | None = None) -> dict:
    """lookups: person_key -> what the search layer found, see sf_events.lookup"""
    from sf_events.lookup import person_key

    lookups = lookups or {}
    tagged = [tag_guest(g, lookups.get(person_key(g) or "")) for g in guests if g.get("name")]
    counts = {"guests": len(tagged), "with_bio": sum(1 for t in tagged if t["bio"]),
              "looked_up": sum(1 for g in guests if (person_key(g) or "") in lookups),
              "identified": sum(1 for t in tagged if t.get("headline"))}
    for tag in ("investor", "founder", "exec", "researcher", "engineer", "student", "host"):
        counts[tag] = sum(1 for t in tagged if tag in t["tags"])
    notable = sorted((t for t in tagged if t["weight"] > 0), key=lambda t: -t["weight"])[:TOP_N]
    return {"counts": counts, "notable": notable, "summary": _summary(counts)}


def _summary(c: dict) -> str:
    parts = [f"{c['guests']} guests"]
    for tag, label in (("investor", "investors"), ("founder", "founders"), ("exec", "execs"), ("researcher", "researchers"), ("host", "hosts")):
        if c.get(tag):
            parts.append(f"{c[tag]} {label}")
    return " · ".join(parts)


def score_bonus(analysis: dict) -> tuple[int, list[str]]:
    """what the guest mix adds to the event score, capped so it cannot outvote the event itself"""
    c = analysis.get("counts") or {}
    bonus = min(25, c.get("investor", 0) * 6 + c.get("founder", 0) * 2 + c.get("exec", 0) * 3)
    reasons = []
    if c.get("investor"):
        reasons.append(f"{c['investor']} investors in the room")
    if c.get("founder"):
        reasons.append(f"{c['founder']} founders in the room")
    if c.get("exec") and not c.get("investor"):
        reasons.append(f"{c['exec']} execs in the room")
    return bonus, reasons
