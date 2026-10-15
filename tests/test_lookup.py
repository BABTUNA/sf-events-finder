import httpx

from sf_events import lookup, people
from sf_events.store import Store


def g(name, links=(), bio=""):
    return {"name": name, "bio": bio, "links": list(links)}


def test_person_key_prefers_strongest_anchor():
    assert lookup.person_key(g("Joel Jussila", ["https://luma.com/user/joeljussila", "https://www.linkedin.com/in/Joel-Jussila"])) == "li:joel-jussila"
    assert lookup.person_key(g("Aaron Lin", ["https://luma.com/user/aaronshlin", "https://instagram.com/aaronn_lin"])) == "luma:aaronshlin"
    assert lookup.person_key(g("Daniel Russell", ["https://x.com/dnlRussell"])) == "x:dnlrussell"
    assert lookup.person_key(g("Jane Doe")) == "name:jane doe"
    # a first name alone is not something you can search for
    assert lookup.person_key(g("Aidan")) is None


def fake_search(answers):
    """answers: substring of query -> list of results"""
    def handler(request):
        q = request.read().decode()
        for needle, results in answers.items():
            if needle in q:
                return httpx.Response(200, json={"success": True, "data": {"web": results}})
        return httpx.Response(200, json={"success": True, "data": {"web": []}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tier1_linkedin_slug_must_match_url(monkeypatch):
    monkeypatch.setattr(lookup.config, "FIRECRAWL_API_KEY", "x")
    client = fake_search({
        "site:linkedin.com/in/joel-jussila": [
            {"url": "https://fi.linkedin.com/in/joel-jussila-10427a282", "title": "Joel Jussila - CEO at JPJ-Palvelut Oy - LinkedIn", "description": ""},
            {"url": "https://www.linkedin.com/in/joel-jussila", "title": "Joel Jussila - I run a hacker house in SF - LinkedIn", "description": ""},
        ],
    })
    ev, tier = lookup.find_evidence(g("Joel Jussila", ["https://www.linkedin.com/in/joel-jussila"]), client=client)
    assert tier == "linkedin" and len(ev) == 1 and ev[0]["url"].endswith("/in/joel-jussila")


def test_tier2_keeps_only_anchored_hits(monkeypatch):
    monkeypatch.setattr(lookup.config, "FIRECRAWL_API_KEY", "x")
    client = fake_search({
        "Daniel Russell": [
            {"url": "https://x.com/dnlrussell", "title": "Daniel Russell (@dnlRussell) / X", "description": "investor & lawyer interested in AI infra"},
            {"url": "https://www.linkedin.com/in/apurva-c", "title": "Apurva C - TPM @ Microsoft", "description": "unrelated"},
            {"url": "https://example.com/daniel-russell-chef", "title": "Daniel Russell, pastry chef", "description": "croissants"},
        ],
    })
    ev, tier = lookup.find_evidence(g("Daniel Russell", ["https://x.com/dnlRussell"]), client=client)
    assert tier == "web" and [e["url"] for e in ev] == ["https://x.com/dnlrussell"]
    # nothing to anchor on and a single name: skipped without a search
    assert lookup.find_evidence(g("Aidan"), client=client) == ([], "skipped")


class FakeLLM:
    """stands in for anthropic.Anthropic: returns a read per key based on the evidence"""
    def __init__(self):
        self.messages = self
        self.calls = []

    def parse(self, **kw):
        import json
        self.calls.append(kw)
        payload = json.loads(kw["messages"][0]["content"].split("\n", 1)[1])
        reads = []
        for p in payload:
            blob = " ".join(e["snippet"] + e["title"] for e in p["evidence"]).lower()
            role = "investor" if "investor" in blob else "founder" if "hacker house" in blob or "founder" in blob else "unknown"
            reads.append(lookup.PersonRead(key=p["key"], role=role, company=None, headline=f"{role} read", worth_meeting=role != "unknown", reason="because", confidence="high" if role != "unknown" else "low"))
        class R: pass
        r = R(); r.parsed_output = lookup.BatchRead(people=reads)
        return r


def test_lookup_list_caches_people_and_updates_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(lookup.config, "FIRECRAWL_API_KEY", "x")
    store = Store(tmp_path / "t.db")
    guests = [
        g("Joel Jussila", ["https://www.linkedin.com/in/joel-jussila"]),
        g("Daniel Russell", ["https://x.com/dnlRussell"]),
        g("Aidan"),
        g("Nobody Findable", ["https://instagram.com/nobody"]),
    ]
    store.set_guests("luma:test", "https://luma.com/test", "https://luma.com/test", guests, people.analyze(guests))
    client = fake_search({
        "site:linkedin.com/in/joel-jussila": [{"url": "https://www.linkedin.com/in/joel-jussila", "title": "Joel Jussila - I run a hacker house in SF - LinkedIn", "description": ""}],
        "Daniel Russell": [{"url": "https://x.com/dnlrussell", "title": "Daniel Russell (@dnlRussell) / X", "description": "investor & lawyer"}],
    })
    llm = FakeLLM()
    r = lookup.lookup_list(store, "luma:test", http=client, llm=llm)
    assert r == {"searched": 3, "read": 2, "skipped": 1, "remaining": 0, "pending_read": 0}
    assert store.person("li:joel-jussila")["role"] == "founder"
    assert store.person("x:dnlrussell")["role"] == "investor"
    # the miss is remembered so it is not searched again
    assert store.person("ig:nobody")["role"] == "unknown"
    assert len(llm.calls) == 1

    a = store.guests("luma:test")["analysis"]
    assert a["counts"]["investor"] == 1 and a["counts"]["founder"] == 1 and a["counts"]["looked_up"] == 3
    top = {p["name"]: p for p in a["notable"]}
    assert top["Daniel Russell"]["headline"] == "investor read" and "https://www.linkedin.com/in/joel-jussila" in top["Joel Jussila"]["links"]

    # second pass has nothing left and spends nothing
    r2 = lookup.lookup_list(store, "luma:test", http=client, llm=llm)
    assert r2["searched"] == 0 and len(llm.calls) == 1
    assert lookup.lists_with_work(store) == []


def test_read_failure_keeps_evidence_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(lookup.config, "FIRECRAWL_API_KEY", "x")
    store = Store(tmp_path / "t.db")
    guests = [g("Joel Jussila", ["https://www.linkedin.com/in/joel-jussila"])]
    store.set_guests("luma:t", "https://luma.com/t", "https://luma.com/t", guests, people.analyze(guests))
    client = fake_search({"site:linkedin.com/in/joel-jussila": [{"url": "https://www.linkedin.com/in/joel-jussila", "title": "Joel Jussila - Founder - LinkedIn", "description": ""}]})

    class Broken:
        def __init__(self): self.messages = self
        def parse(self, **kw): raise RuntimeError("workspace header missing")

    r = lookup.lookup_list(store, "luma:t", http=client, llm=Broken())
    assert r["searched"] == 1 and r["read"] == 0 and r["pending_read"] == 1 and "workspace" in r["read_error"]
    assert store.person("li:joel-jussila")["pending"] is True
    # still has work, and the next pass does not search again
    assert lookup.lists_with_work(store) == ["luma:t"]
    r2 = lookup.lookup_list(store, "luma:t", http=client, llm=FakeLLM())
    assert r2["searched"] == 0 and r2["read"] == 1 and store.person("li:joel-jussila")["role"] == "founder"


def test_tier2_first_name_is_a_whole_word(monkeypatch):
    monkeypatch.setattr(lookup.config, "FIRECRAWL_API_KEY", "x")
    client = fake_search({"Bryan Borck": [
        {"url": "https://www.linkedin.com/in/bryantleebrock", "title": "Bryant Brock - AI took my job | LinkedIn", "description": "ai founder"},
    ]})
    assert lookup.find_evidence(g("Bryan Borck"), client=client) == ([], "web")
