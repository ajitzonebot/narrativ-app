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


def test_every_item_says_why_it_sits_where_it_does(monkeypatch):
    monkeypatch.setattr(requeue, "_fin", lambda s: {"decision": {"incomplete": ["No outlook scan"]}} if s in ("I.NS", "J.NS") else {})
    q = {"items": [{"symbol": "B.NS", "task": "recheck", "pos": "bad_news", "reason": "bad news filed since the last research"},
                   {"symbol": "E.NS", "task": "enrich", "priority": 71.2, "reason": "one forward driver away from a Buy/Hold call (priority 71.2)"},
                   {"symbol": "O.NS", "task": "recheck", "reason": "overdue: 1 kill switch past due",
                    "overdue": [{"kind": "kill_switch", "days_late": 12}, {"kind": "promise", "days_late": 40}]}]}
    picks = {"picks": [{"s": "J.NS", "dc": "Buy", "ic": 1, "rk": 9}, {"s": "I.NS", "dc": "Buy", "ic": 1, "rk": 3},
                       {"s": "N.NS", "dc": "Hold", "cand": "Strong Buy"}]}
    requeue.resort(q, picks, {}, [{"symbol": "Q.NS", "via": "issue #9", "date": "2026-11-27"}], cap=10)
    got = {x["symbol"]: x["why_pos"] for x in q["items"]}
    assert [x["symbol"] for x in q["items"][:4]] == ["Q.NS", "I.NS", "J.NS", "N.NS"]   # unfinished Buys by readiness (rk)
    assert got["Q.NS"] == "You asked for this review. Your requests go first."
    assert got["I.NS"].startswith("A Buy whose research is not complete") and "1 of 2 in this group, by how ready it is to buy" in got["I.NS"]
    assert "2 of 2" in got["J.NS"] and "Comes after your requests, before new Buy candidates" in got["J.NS"]
    assert got["N.NS"].startswith("Rules say Strong Buy: a full review is needed before it is shown as buyable")
    assert "Comes after other overdue items, before missed forward targets" in got["B.NS"]
    assert got["E.NS"].endswith("Priority 71.2, highest first.") and got["E.NS"].startswith("Forward-driver hunt: one driver away")
    assert "Oldest item 40 days late" in got["O.NS"]   # no `pos` (an older queue file): the group is read from the reason
    import re
    assert not any(re.search(r"\b[RTKAG]\d+\b|RULES", w) for w in got.values())   # plain words, no internal rule ids


def test_last_group_and_unknown_items():
    items = [{"symbol": "S.NS", "task": "recheck", "pos": "stale"}, {"symbol": "X.NS", "task": "scan", "reason": "something else"}]
    requeue.label_positions(items)
    assert items[0]["why_pos"].endswith("Comes after other forward-driver hunts; last in the order.")
    assert "why_pos" not in items[1]
