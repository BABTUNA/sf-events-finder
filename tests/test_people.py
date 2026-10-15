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
