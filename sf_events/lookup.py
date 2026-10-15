"""who is this person, when the bio does not say

three tiers, cheapest first, keyed on anchors we already have for a guest:

    tier 1  linkedin slug in their links -> one search for that exact url,
            the result title is the linkedin headline
    tier 2  full name plus an x or instagram handle -> anchored web search,
            keep results that mention the handle or the name on linkedin
    tier 3  a model reads the evidence and returns role, company, headline,
            whether they are worth meeting, and how sure it is

results live in the people table keyed by the strongest anchor, so a person
seen at three events costs one lookup. firecrawl for search, anthropic for
the read. both off unless the keys are in .env
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel

from sf_events import config
from sf_events.store import Store

FIRECRAWL_SEARCH = "https://api.firecrawl.dev/v2/search"
LINKEDIN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([^/?#]+)", re.I)
X_HANDLE = re.compile(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)", re.I)
IG_HANDLE = re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)", re.I)
LUMA_USER = re.compile(r"https?://(?:www\.)?(?:luma\.com|lu\.ma)/user/([^/?#]+)", re.I)
# words that make a tier 2 hit about the right kind of person
CONTEXT = re.compile(r"\b(ai|ml|founder|startup|investor|venture|engineer|ceo|cto|research|san francisco|sf\b|berkeley|stanford|yc\b)", re.I)
# searches per job tick, 2 firecrawl credits each
SEARCH_BUDGET = 60
CLASSIFY_BATCH = 20

Role = Literal["founder", "investor", "exec", "researcher", "engineer", "student", "operator", "unknown"]
Confidence = Literal["high", "medium", "low"]


class PersonRead(BaseModel):
    key: str
    role: Role
    company: str | None
    headline: str
    worth_meeting: bool
    reason: str
    confidence: Confidence


class BatchRead(BaseModel):
    people: list[PersonRead]


# ---- anchors

def anchors(guest: dict) -> dict:
    links = guest.get("links") or []
    out = {"name": (guest.get("name") or "").strip(), "linkedin": None, "x": None, "instagram": None, "luma": None}
    for l in links:
        if (m := LINKEDIN.match(l)) and not out["linkedin"]:
            out["linkedin"] = m.group(1)
        elif (m := X_HANDLE.match(l)) and not out["x"]:
            out["x"] = m.group(1)
        elif (m := IG_HANDLE.match(l)) and not out["instagram"]:
            out["instagram"] = m.group(1)
        elif (m := LUMA_USER.match(l)) and not out["luma"]:
            out["luma"] = m.group(1)
    return out


def person_key(guest: dict) -> str | None:
    """the strongest stable identity we have, None when a lookup would be a guess"""
    a = anchors(guest)
    if a["linkedin"]:
        return f"li:{a['linkedin'].lower()}"
    if a["luma"]:
        return f"luma:{a['luma']}"
    if a["x"]:
        return f"x:{a['x'].lower()}"
    if a["instagram"]:
        return f"ig:{a['instagram'].lower()}"
    if len(a["name"].split()) >= 2:
        return "name:" + re.sub(r"\s+", " ", a["name"].lower())
    return None


# ---- search

def search(query: str, limit: int = 5, *, client: httpx.Client) -> list[dict]:
    for attempt in range(3):
        try:
            r = client.post(
                FIRECRAWL_SEARCH,
                json={"query": query, "limit": limit},
                headers={"Authorization": f"Bearer {config.FIRECRAWL_API_KEY}"},
            )
        except httpx.TransportError:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            return []
        try:
            body = r.json()
        except ValueError:
            return []
        return [
            {"url": x.get("url", ""), "title": x.get("title") or "", "snippet": x.get("description") or ""}
            for x in (body.get("data") or {}).get("web") or []
        ]
    return []


def find_evidence(guest: dict, *, client: httpx.Client) -> tuple[list[dict], str]:
    """(results that look like this person, tier used). empty list means nothing trustworthy"""
    a = anchors(guest)
    name = a["name"]
    if a["linkedin"]:
        slug = a["linkedin"].lower()
        exact = re.compile(rf"/in/{re.escape(slug)}/?(?:[?#]|$)", re.I)
        hits = [h for h in search(f"site:linkedin.com/in/{slug}", 3, client=client) if exact.search(h["url"])]
        if hits:
            return hits[:1], "linkedin"
    if len(name.split()) < 2 and not (a["x"] or a["instagram"]):
        return [], "skipped"
    handle = a["x"] or a["instagram"]
    q = f'"{name}" {("@" + handle) if handle else "San Francisco"} AI OR founder OR startup OR investor'
    hits = search(q, 5, client=client)
    good = []
    # whole words, so "bryan" does not match "bryant"
    first = re.compile(rf"\b{re.escape(name.split()[0])}\b", re.I)
    full = re.compile(rf"\b{re.escape(name)}\b", re.I)
    for h in hits:
        blob = f"{h['url']} {h['title']} {h['snippet']}"
        if handle and handle.lower() in blob.lower():
            good.append(h)
        elif full.search(blob) and ("linkedin.com/in/" in h["url"].lower() or CONTEXT.search(blob)):
            good.append(h)
        elif first.search(h["title"]) and "linkedin.com/in/" in h["url"].lower() and CONTEXT.search(blob):
            good.append(h)
    return good[:3], "web"


# ---- read

SYSTEM = """You identify who someone is from thin public evidence so a person can decide whether to meet them at a tech event in the SF Bay Area.

For each person you get a name, maybe a self-written bio, and search results that may or may not be about them. Rules:
- Only use a search result if it clearly refers to the same person (name matches, and the handle, company, or location lines up). If the evidence could be a different person with the same name, answer role "unknown" with low confidence.
- role: founder (started a company, including stealth), investor (VC, angel, fund, scout), exec (C-level, VP, head of, director at a real company), researcher (academic or lab research), engineer, student, operator (everyone else employed in tech), or unknown.
- A founding engineer is an engineer. An ex-founder now employed is their current role. A student who is also a founder is a founder.
- worth_meeting is true for investors, founders of funded or shipping companies, and senior people at notable companies. False for students, unknowns, and people with no professional signal.
- headline is one short line like "Founder & CEO, Svix" or "Investor, TDK Ventures". reason is one short sentence a person could read before walking over.
Return every key you were given exactly once."""


def classify(people: list[dict], *, client=None) -> list[PersonRead]:
    """people: [{key, name, bio, evidence:[{url,title,snippet}]}]"""
    import anthropic

    headers = {"anthropic-workspace-id": config.ANTHROPIC_WORKSPACE_ID} if config.ANTHROPIC_WORKSPACE_ID else None
    client = client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, default_headers=headers)
    payload = json.dumps(people, ensure_ascii=False, indent=1)
    response = client.messages.parse(
        model=config.LOOKUP_MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"People to identify:\n{payload}"}],
        output_format=BatchRead,
    )
    return response.parsed_output.people


# ---- job

SEARCH_WORKERS = 4


def lookup_list(store: Store, list_key: str, *, budget: int = SEARCH_BUDGET, http: httpx.Client | None = None, llm=None) -> dict:
    """one bounded pass over a guest list, in two phases that each persist:

    search: guests with no people row get searched, a few at a time, and the
            evidence is stored right away as a pending read so a failure later
            never wastes the credits
    read:   every pending person on this list goes to the model in batches
    then the list's analysis is recomputed from whatever is known
    """
    from concurrent.futures import ThreadPoolExecutor

    from sf_events import people as people_mod

    g = store.guests(list_key)
    if not g:
        return {"searched": 0, "read": 0, "skipped": 0, "remaining": 0}
    own = http is None
    http = http or httpx.Client(timeout=40)
    skipped = 0
    try:
        pending_search = []
        for guest in g["guests"]:
            k = person_key(guest)
            if not k:
                skipped += 1
            elif store.person(k) is None:
                pending_search.append((k, guest))
        todo = pending_search[:budget]

        def one(item):
            k, guest = item
            evidence, tier = find_evidence(guest, client=http)
            return k, guest, evidence, tier

        with ThreadPoolExecutor(SEARCH_WORKERS) as pool:
            for k, guest, evidence, tier in pool.map(one, todo):
                rec = {"name": guest["name"], "bio": guest.get("bio") or "", "tier": tier, "evidence": evidence,
                       "role": "unknown", "company": None, "headline": "", "worth_meeting": False, "reason": "", "confidence": "low",
                       # a miss is final, a hit waits for the model
                       "pending": bool(evidence)}
                store.set_person(k, rec)

        # read everyone on this list still waiting for the model
        waiting = []
        for guest in g["guests"]:
            k = person_key(guest)
            p = store.person(k) if k else None
            if p and p.get("pending"):
                waiting.append({"key": k, "name": p["name"], "bio": p.get("bio") or "", "evidence": p["evidence"]})
        read = 0
        read_error = None
        for i in range(0, len(waiting), CLASSIFY_BATCH):
            batch = waiting[i : i + CLASSIFY_BATCH]
            try:
                reads = {r.key: r for r in classify(batch, client=llm)}
            except Exception as e:
                # evidence is already stored, the read can happen on a later pass
                read_error = f"{type(e).__name__}: {str(e)[:200]}"
                break
            for p in batch:
                rec = store.person(p["key"])
                r = reads.get(p["key"])
                if r:
                    rec.update(role=r.role, company=r.company, headline=r.headline, worth_meeting=r.worth_meeting, reason=r.reason, confidence=r.confidence)
                    read += 1
                rec["pending"] = False
                rec.pop("looked_up_at", None)
                store.set_person(p["key"], rec)

        lookups = {}
        for guest in g["guests"]:
            k = person_key(guest)
            if k and (p := store.person(k)):
                lookups[k] = p
        store.update_analysis(list_key, people_mod.analyze(g["guests"], lookups=lookups))
        out = {"searched": len(todo), "read": read, "skipped": skipped, "remaining": max(0, len(pending_search) - len(todo)),
               "pending_read": len(waiting) - read}
        if read_error:
            out["read_error"] = read_error
        return out
    finally:
        if own:
            http.close()


def lists_with_work(store: Store) -> list[str]:
    """guest list keys that still have guests without a lookup"""
    out = []
    for key, g in store.all_guest_lists().items():
        for guest in g["guests"]:
            k = person_key(guest)
            if not k:
                continue
            p = store.person(k)
            if p is None or p.get("pending"):
                out.append(key)
                break
    return out


def lookup_due(store: Store, log=None) -> list[dict]:
    if not config.lookup_enabled():
        return []
    runs = []
    for key in lists_with_work(store):
        if log:
            print(f"looking up people for {key}...", file=log)
        run_id = store.start_run(key, job="lookup")
        try:
            r = lookup_list(store, key)
            store.finish_run(run_id, ok=True, count=r["searched"], added=r["read"])
            runs.append({"key": key, **r})
        except Exception as e:
            store.finish_run(run_id, ok=False, error=f"{type(e).__name__}: {e}")
            runs.append({"key": key, "error": str(e)})
        # one list per tick keeps a tick short
        break
    return runs


def progress(store: Store, guests: list[dict]) -> dict:
    keys = [person_key(g) for g in guests]
    want = [k for k in keys if k]
    people = [store.person(k) for k in want]
    done = sum(1 for p in people if p is not None and not p.get("pending"))
    pending = sum(1 for p in people if p is not None and p.get("pending"))
    return {"looked_up": done, "pending_read": pending, "lookable": len(want), "skipped": len(keys) - len(want)}
