from collections import Counter
from datetime import datetime

from narrativ import next as NX

NOW = datetime(2026, 11, 28, 10, 0, tzinfo=NX.IST)
TODAY = "2026-11-28"


def it(s, task, pos, **k):
    return {"symbol": s, "task": task, "pos": pos, **k}


def run(queue, backlog=None, theses=None, claims=None, packs=None, task="catalyst"):
    q = {"date": "2026-11-27", "items": queue}
    b = {"date": "2026-11-27", "items": backlog or []}
    items, sk = NX.ladder(q, b, theses or {}, claims or {}, (packs or {}).get, task, TODAY, NOW)
    return [x["symbol"] for x in items], sk


READY = {"docs_checked": True, "readable_docs": 1}
NONE = {"docs_checked": True, "readable_docs": 0}


def test_first_studies_after_rechecks_before_no_driver_hunts():
    q = [it("A", "enrich", "no_driver"), it("B", "recheck", "stale"), it("C", "recheck", "bad_news")]
    b = [it("F", "enrich", "first_study")]
    got, _ = run(q, b, packs={"A": READY, "F": READY})
    assert got == ["C", "B", "F", "A"]


def test_catalyst_skips_reviews_review_takes_them_first():
    q = [it("R", "recheck", "bad_news"), it("V", "review", "candidate"), it("G", "review_flag", "flag")]
    assert run(q)[0] == ["R"]
    assert run(q, task="review")[0] == ["V", "G", "R"]


def test_skips_done_claimed_and_unreadable():
    q = [it("D", "recheck", "news"), it("C", "recheck", "news"), it("H", "enrich", "near")]
    b = [it("F", "enrich", "first_study"), it("S", "enrich", "first_study"), it("N", "enrich", "first_study"),
         it("Y", "recheck", "news")]
    th = {"D": {"updated": TODAY}, "S": {"updated": "2026-11-20"}, "Y": {"updated": "2026-11-27"}}
    cl = {"items": {"C": {"run": "review", "at": "2026-11-28T09:30+05:30"}}}
    got, sk = run(q, b, th, cl, {"H": NONE, "F": READY, "N": None})
    assert got == ["F"]
    assert sum(sk.values()) == 6


def test_old_claim_expires_and_stale_queue_serves_nothing():
    cl = {"items": {"C": {"run": "review", "at": "2026-11-28T07:00+05:30"}}}
    assert run([it("C", "recheck", "news")], claims=cl)[0] == ["C"]
    items, sk = NX.ladder({"date": "2026-11-20", "items": [it("C", "recheck", "news")]}, {}, {}, {}, {}.get, "catalyst", TODAY, NOW)
    assert items == [] and isinstance(sk, Counter)


def test_claim_prunes_old():
    c = NX.claim({"items": {"OLD": {"at": "2026-11-28T05:00+05:30"}}}, "NEW", "review", NOW)
    assert list(c["items"]) == ["NEW"]
