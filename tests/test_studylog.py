from datetime import date

from narrativ import funnel as FN
from narrativ import studylog as SL
from narrativ import verify as V


def test_log_bootstraps_unknown_then_dates_new(tmp_path):
    p = tmp_path / "log.json"
    log = SL.update({"OLD": {}}, date(2026, 11, 28), p)
    assert log == {"OLD": ""}
    log = SL.update({"OLD": {}, "NEW": {}}, date(2026, 11, 29), p)
    assert log == {"OLD": "", "NEW": "2026-11-29"}


def test_stats_week_and_start():
    log = {"OLD": "", "A": "2026-11-29", "B": "2026-11-30", "C": "2026-11-10"}
    th = {"A": {"triage": {"outcome": "no_story"}}, "B": {}, "C": {}, "OLD": {}}
    dec = {"B": {"d": "Buy", "verified": "pass"}, "C": {"d": "Hold", "candidate": "Buy"}}
    st = SL.stats(log, th, date(2026, 12, 1), ["A", "B", "X"], dec)
    assert st["pool"] == 3 and st["studied"] == 2
    assert st["week"] == {"studied": 2, "no_story": 1, "candidates": 1, "verified": 1}
    assert st["start"]["date"] == "2026-11-10" and st["start"]["studied"] == 3 and st["start"]["candidates"] == 2


def test_verify_triage_rules():
    ok = {"triage": {"date": "2026-11-29", "outcome": "no_story", "fails_on": "driver",
                     "story": "No driver in the latest call or results", "read": ["https://nsearchives.nseindia.com/x.pdf"]}}
    v, rep = V.verify_all({"S": ok})
    assert v["S"]["triage"]["fails_on"] == "driver" and not [r for r in rep["S"]["rejected"] if r["id"] == "triage"]
    for bad in ({"outcome": "maybe"}, {"fails_on": "mood"}, {"read": []}, {"story": "Orders of 500 crore"}):
        v, rep = V.verify_all({"S": {"triage": {**ok["triage"], **bad}}})
        assert "triage" not in v["S"] and [r for r in rep["S"]["rejected"] if r["id"] == "triage"]


def test_not_rated_reason_names_the_failed_gate():
    th = {"updated": "2026-11-29", "triage": {"date": "2026-11-29", "outcome": "no_story", "fails_on": "priced"}}
    r = FN.not_rated_reason({}, "Watchlist", th)
    assert r.startswith("Quick check (2026-11-29): no story yet") and "already in the price" in r
    assert FN.not_rated_reason({}, "Watchlist", {**th, "drivers": [{"x": 1}]}).startswith("Researched")
