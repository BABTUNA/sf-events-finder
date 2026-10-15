"""who is in the room

guests come from the browser extension as {name, bio, links}. bios are
free text people wrote about themselves ("Founder @ Gemphere", "eecs @
berkeley", "CEO of PopDrop.ai"), so this is keyword rules again. each
guest gets tags and a weight, the event gets counts and a notable list
"""

import re

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


def tag_guest(g: dict) -> dict:
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
    # a founder who is also a student is a student founder, keep both but it reads fine
    return {"name": g.get("name", "").strip(), "bio": bio, "links": links, "tags": tags, "weight": weight}


def analyze(guests: list[dict]) -> dict:
    tagged = [tag_guest(g) for g in guests if g.get("name")]
    counts = {"guests": len(tagged), "with_bio": sum(1 for t in tagged if t["bio"])}
    for tag in ("investor", "founder", "exec", "researcher", "engineer", "student"):
        counts[tag] = sum(1 for t in tagged if tag in t["tags"])
    notable = sorted((t for t in tagged if t["weight"] > 0), key=lambda t: -t["weight"])[:TOP_N]
    return {"counts": counts, "notable": notable, "summary": _summary(counts)}


def _summary(c: dict) -> str:
    parts = [f"{c['guests']} guests"]
    for tag, label in (("investor", "investors"), ("founder", "founders"), ("exec", "execs"), ("researcher", "researchers")):
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
