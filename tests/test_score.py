from datetime import datetime, timezone

from sf_events.models import Event


def ev(name, summary=None, **kw):
    base = dict(
        id="t:x", source="luma", name=name, start=datetime(2026, 10, 20, 1, tzinfo=timezone.utc), end=None,
        url="https://luma.com/x", location="San Francisco, CA", venue=None, summary=summary, kind=None, image_url=None,
    )
    return Event(**{**base, **kw})


def test_prize_hackathon_with_investors_scores_high():
    e = ev("Agents Hackathon", "Compete for $25,000 in cash prizes. Judges include investors from a16z and founders.", also=("cerebralvalley",))
    s, why = e.score, e.score_reasons
    assert s >= 85
    assert {"cash prizes", "investors", "founders", "notable host", "hackathon", "cv curated"} <= set(why)
    assert any(r.startswith("$25,000") for r in why)


def test_craft_night_scores_zero():
    e = ev("Spooky craft night: collage & connect", tags=("arts & culture",))
    assert e.score == 0
    assert "tagged arts & culture" in e.score_reasons


def test_sold_out_sinks_a_good_event():
    good = ev("Founder and VC mixer", "investors and founders")
    gone = ev("Founder and VC mixer", "investors and founders", sold_out=True)
    # the clamp at zero eats part of the 40, the point is it drops to the floor
    assert good.score > 0 and gone.score == 0
    assert "sold out" in gone.score_reasons


def test_cash_bar_is_not_a_prize():
    e = ev("Happy hour", "cash bar, come win friends")
    assert "cash prizes" not in e.score_reasons


def test_score_is_in_json():
    d = ev("Demo Day", "startups pitch to investors").to_dict()
    assert isinstance(d["score"], int) and "investors" in d["score_reasons"]
