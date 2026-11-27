from narrativ.republish import prune_queue


def test_review_after_the_daily_run_leaves_the_queue():
    q = {"items": [{"symbol": "SURAKSHA.NS", "task": "review"}, {"symbol": "X.NS", "task": "review"},
                   {"symbol": "B.NS", "task": "enrich"}, {"symbol": "B.NS", "task": "review_flag"}]}
    done = {"runs": [{"start": "2026-11-26T22:35+00:00", "items": [{"s": "SURAKSHA.NS", "r": "pass"}, {"s": "B.NS", "r": "enrich"}]},
                     {"start": "2026-11-26T10:00+00:00", "items": [{"s": "X.NS", "r": "pass"}]}]}  # before the build: kept
    assert prune_queue(done, "2026-11-26T17:46:41+00:00", q) == 2
    assert [(x["symbol"], x["task"]) for x in q["items"]] == [("X.NS", "review"), ("B.NS", "review_flag")]


def test_infer_due_from_the_quote():
    from narrativ.verify import infer_due
    assert infer_due("hopeful to take this up early next month or probably mid of December.", "2026-11-03")[0] == "2026-12-31"
    assert infer_due("We expect revenue to grow 20% in FY27", "2026-11-03")[0] == "2027-03-31"
    assert infer_due("growth in 2027", "2026-11-03") is None  # calendar or fiscal: two readings, no date
    assert infer_due("coming in from there.", "2026-11-03") is None
