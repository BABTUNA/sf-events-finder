from sf_events.categorize import event_format, event_topics


def test_format_prefers_title_over_summary():
    # the summary mentions a hackathon but the event itself is a party
    assert event_format("The Kickoff Party", "Open Source AI Week kicks off, hackathon teams welcome", None) == "social"


def test_format_rules():
    assert event_format("Crusoe Field Day", None, None) == "hackathon"
    assert event_format("Fireside Chat with Tony Zhao", None, None) == "talk"
    assert event_format("CoreWeave x NVIDIA Dynamo Meetup", None, None) == "meetup"
    assert event_format("Vercel Ship", "a conference for developers", None) == "conference"
    assert event_format("Orkes Shift", None, None) == "other"


def test_source_kind_wins():
    assert event_format("Some Dinner", None, "hackathon") == "hackathon"


def test_topics_are_multi():
    t = event_topics("Zero Trust for AI", "securing models, data, and autonomous agents")
    assert {"security", "agents", "data"} <= set(t)
    assert event_topics("AI trivia night", None) == ()
