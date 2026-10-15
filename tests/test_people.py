from fastapi.testclient import TestClient

from sf_events import people


GUESTS = [
    {"name": "Eda Ciris", "bio": "Founder @ Gemphere\nhttps://www.linkedin.com/in/eda-ciris/", "links": []},
    {"name": "Benjamin Boyarsky", "bio": "Physics & Mathematics @ UC Berkeley\nCEO of PopDrop.ai | Avionics @ SEB", "links": []},
    {"name": "Arjun Desikan", "bio": "18 | AI Safety, Time Series, Physics-ML Researcher @ Theorem, UH, JHU\nPrev. @ MIT CSAIL", "links": []},
    {"name": "Sameer Kashyap", "bio": "diver, surfer, triathlete", "links": ["https://www.instagram.com/sameeerkashyap"]},
    {"name": "Jane Doe", "bio": "Partner at a16z", "links": ["https://www.linkedin.com/in/jane"]},
    {"name": "Zeyuan Zhao", "bio": "eecs @ berkeley", "links": []},
    {"name": "Abe", "bio": "", "links": ["https://www.twitter.com/akarik3873"]},
]


def test_tag_guest_reads_titles_and_orgs():
    t = {g["name"]: people.tag_guest(g) for g in GUESTS}
    assert "founder" in t["Eda Ciris"]["tags"]
    assert "founder" in t["Benjamin Boyarsky"]["tags"] and "student" in t["Benjamin Boyarsky"]["tags"]
    assert "researcher" in t["Arjun Desikan"]["tags"]
    assert t["Sameer Kashyap"]["tags"] == [] and t["Sameer Kashyap"]["weight"] == 0
    assert "investor" in t["Jane Doe"]["tags"] and "@a16z" in t["Jane Doe"]["tags"]
    assert t["Jane Doe"]["weight"] > t["Eda Ciris"]["weight"] > t["Zeyuan Zhao"]["weight"]


def test_analyze_counts_and_notable_order():
    a = people.analyze(GUESTS)
    assert a["counts"]["guests"] == 7 and a["counts"]["with_bio"] == 6
    assert a["counts"]["investor"] == 1 and a["counts"]["founder"] == 2
    assert a["notable"][0]["name"] == "Jane Doe"
    assert all(p["weight"] > 0 for p in a["notable"])
    assert a["summary"].startswith("7 guests · 1 investors · 2 founders")


def test_score_bonus_is_capped():
    bonus, reasons = people.score_bonus({"counts": {"investor": 10, "founder": 40, "exec": 5}})
    assert bonus == 25
    assert any("investors" in r for r in reasons)


def test_post_guests_endpoint(tmp_path):
    from sf_events import web
    from sf_events.store import Store
    web.store = Store(tmp_path / "t.db")
    client = TestClient(web.app)

    r = client.post("/api/guests", json={"page_url": "https://partiful.com/e/STg1eJrPTO14OpwysakA?foo=1", "guests": GUESTS})
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "partiful:STg1eJrPTO14OpwysakA"
    assert body["counts"]["founder"] == 2 and body["known_event"] is False

    r = client.get("/api/guests/partiful:STg1eJrPTO14OpwysakA")
    assert r.status_code == 200 and len(r.json()["guests"]) == 7
    assert r.json()["event_url"] == "https://partiful.com/e/STg1eJrPTO14OpwysakA"


def test_enrich_luma_fills_bio_and_links_from_profile_api():
    import httpx

    profiles = {
        "joeljussila": {"event_hosted_count": 6, "event_attended_count": 90, "user": {"bio_short": "ceo at SILTA", "linkedin_handle": "/in/joel-jussila", "twitter_handle": "JoelJussila", "website": "https://www.siltahouse.com/home"}},
        "aaronshlin": {"event_hosted_count": 0, "event_attended_count": 9, "user": {"bio_short": "", "linkedin_handle": "/in/aaronshlin"}},
    }
    hit = []

    def handler(request):
        u = request.url.params["username"]
        hit.append(u)
        return httpx.Response(200, json=profiles[u]) if u in profiles else httpx.Response(404, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    guests = [
        {"name": "Joel Jussila", "bio": "", "links": ["https://luma.com/user/joeljussila", "https://instagram.com/jussilajoel"]},
        {"name": "Aaron Lin", "bio": "", "links": ["https://luma.com/user/aaronshlin"]},
        {"name": "Already", "bio": "Partner at a16z", "links": ["https://luma.com/user/x"]},
        {"name": "No link", "bio": "", "links": []},
    ]
    out = people.enrich_luma(guests, client=client)
    assert sorted(hit) == ["aaronshlin", "joeljussila"]
    joel = out[0]
    assert joel["bio"] == "ceo at SILTA" and joel["hosted"] == 6
    assert "https://www.linkedin.com/in/joel-jussila" in joel["links"] and "https://x.com/JoelJussila" in joel["links"]
    assert out[2]["bio"] == "Partner at a16z"

    tagged = {t["name"]: t for t in (people.tag_guest(g) for g in out)}
    assert "founder" in tagged["Joel Jussila"]["tags"] and "host" in tagged["Joel Jussila"]["tags"]
    assert tagged["Aaron Lin"]["tags"] == [] and tagged["Aaron Lin"]["weight"] == 1


def test_enrich_luma_stops_at_rate_limit():
    import httpx

    hit = []

    def handler(request):
        hit.append(1)
        return httpx.Response(429, json={"code": "api/rate-limit"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    guests = [{"name": f"g{i}", "bio": "", "links": [f"https://luma.com/user/u{i}"]} for i in range(10)]
    people.PROFILE_WORKERS, saved = 1, people.PROFILE_WORKERS
    try:
        out = people.enrich_luma(guests, client=client)
    finally:
        people.PROFILE_WORKERS = saved
    assert len(hit) == 1 and all(not g["bio"] for g in out)
