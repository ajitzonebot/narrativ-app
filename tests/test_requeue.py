"""Light re-sort of the research queue between daily runs (narrativ/requeue.py, 27 Nov 2026)."""
from narrativ import requeue


def test_requests_then_incomplete_buys_then_new_candidates_lead(monkeypatch):
    monkeypatch.setattr(requeue, "_fin", lambda s: {"decision": {"incomplete": ["R8 no outlook scan"]}} if s == "I.NS" else {})
    q = {"date": "2026-11-27", "items": [{"symbol": "E.NS", "task": "enrich"}, {"symbol": "R.NS", "task": "recheck"},
                                         {"symbol": "C.NS", "task": "review", "reason": "rules say Buy"}]}
    picks = {"picks": [{"s": "I.NS", "dc": "Buy", "vf": "pass", "ic": 1, "n": "Inc"},
                       {"s": "N.NS", "dc": "Hold", "cand": "Buy", "vf": None, "n": "New"},
                       {"s": "C.NS", "dc": "Hold", "cand": "Buy", "vf": None},
                       {"s": "V.NS", "dc": "Buy", "vf": "pass"}]}
    reqs = [{"symbol": "Q.NS", "via": "issue #9", "date": "2026-11-27"},
            {"symbol": "D.NS", "via": "issue #8", "date": "2026-11-20"}]      # worked on since the request: not again
    th = {"D.NS": {"updated": "2026-11-25"}}
    added = requeue.resort(q, picks, th, reqs, cap=5)
    assert [(x["symbol"], x["task"]) for x in q["items"]] == [("Q.NS", "review"), ("I.NS", "review"), ("N.NS", "review"),
                                                              ("R.NS", "recheck"), ("C.NS", "review")]   # cap 5: the enrich item goes
    assert added == ["Q.NS", "I.NS", "N.NS"] and q["items"][0]["requested"] and q["items"][1]["complete"] == ["R8 no outlook scan"]


def test_queue_kept_at_its_cap_from_the_end(monkeypatch):
    monkeypatch.setattr(requeue, "_fin", lambda s: {})
    q = {"items": [{"symbol": f"S{i}.NS", "task": "enrich"} for i in range(4)]}
    requeue.resort(q, {"picks": [{"s": "N.NS", "dc": "Hold", "cand": "Buy"}]}, {}, [], cap=4)
    assert [x["symbol"] for x in q["items"]] == ["N.NS", "S0.NS", "S1.NS", "S2.NS"]   # the last enrich item goes
