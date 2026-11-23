import json

import pandas as pd

from narrativ import calls as CALLS
from narrativ.calls import _close_date, _held, _ret


def series():
    idx = pd.to_datetime(["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"])
    return pd.Series([100.0, 110.0, 99.0, 121.0], index=idx)


def test_return_measured_from_entry_close():
    c = series()
    assert _ret(c, "2026-11-10", 1) == 10.0  # first close after entry
    assert _ret(c, "2026-11-10", None) == 21.0  # latest
    assert _ret(c, "2026-11-10", 5) is None  # not enough closes yet


def test_return_uses_entry_price_when_given():
    assert _ret(series(), "2026-11-11", None, base=110.0) == 10.0


def test_close_date_finds_entry_close():
    assert _close_date(series(), 110.0, "2026-11-13") == "2026-11-11"
    assert _close_date(series(), 105.0, "2026-11-13") is None


def test_portfolio_daily_returns_equal_weight_from_entry_price():
    from narrativ.calls import daily_returns
    idx = pd.to_datetime(["2026-11-10", "2026-11-11", "2026-11-12"])
    px = {"A.NS": pd.DataFrame({"Close": [100.0, 110.0, 121.0]}, index=idx),
          "B.NS": pd.DataFrame({"Close": [50.0, 50.0, 45.0]}, index=idx)}
    bench = pd.Series([1000.0, 1010.0, 1010.0], index=idx)
    calls = [{"symbol": "A.NS", "kind": "verified", "date": "2026-11-10", "price": 100.0},
             {"symbol": "B.NS", "kind": "verified", "date": "2026-11-11", "price": 50.0, "ended": "2026-11-12"},
             {"symbol": "B.NS", "kind": "candidate", "date": "2026-11-10", "price": 50.0}]
    port, b = daily_returns(calls, px, bench)
    assert [round(x, 4) for x in port] == [0.10, 0.0]  # day 1: A +10%; day 2: A +10%, B -10% -> 0
    assert [round(x, 4) for x in b] == [0.01, 0.0]


# ---------------------------------------------------------------- call lifecycle (update): exits, cooldown, frozen returns
def run_update(tmp_path, monkeypatch, closes, calls, dec, stops, today):
    monkeypatch.setattr(CALLS, "OUT", tmp_path / "calls.json")
    (tmp_path / "calls.json").write_text(json.dumps({"calls": calls}))
    idx = pd.bdate_range("2026-11-02", periods=len(closes))
    px = {"A.NS": pd.DataFrame({"Close": closes}, index=idx)}
    bench = pd.Series([1000.0] * len(closes), index=idx)
    return CALLS.update(dec, px, bench, {}, pd.Timestamp(today).date(), stops)["calls"]


def call(**k):
    return {"symbol": "A.NS", "kind": "verified", "decision": "Buy", "date": "2026-11-02", "run": "2026-11-02", "price": 100.0} | k


def test_exit_level_break_does_not_reopen_while_price_stays_below(tmp_path, monkeypatch):
    calls = run_update(tmp_path, monkeypatch, [100.0, 93.0, 94.0], [call(stop=95.0)], {"A.NS": {"d": "Buy"}}, {"A.NS": 90.0}, "2026-11-04")
    assert len(calls) == 1 and calls[0]["ended"] == "2026-11-03" and calls[0]["end_decision"].startswith("Exit level")
    # a close back above the old exit level: the still-Buy stock is a new call again
    calls = run_update(tmp_path, monkeypatch, [100.0, 93.0, 96.0], [call(stop=95.0)], {"A.NS": {"d": "Buy"}}, {"A.NS": 90.0}, "2026-11-04")
    assert len(calls) == 2 and not calls[1].get("ended") and calls[1]["price"] == 96.0


def test_exit_level_cooldown_ends_after_ten_trading_days(tmp_path, monkeypatch):
    closes = [100.0, 93.0] + [90.0] * 9
    calls = run_update(tmp_path, monkeypatch, closes, [call(stop=95.0)], {"A.NS": {"d": "Buy"}}, {"A.NS": 85.0}, "2026-11-16")
    assert len(calls) == 1  # 9 closes after the exit, all below it
    calls = run_update(tmp_path, monkeypatch, closes + [90.0], [call(stop=95.0)], {"A.NS": {"d": "Buy"}}, {"A.NS": 85.0}, "2026-11-17")
    assert len(calls) == 2 and calls[1]["price"] == 90.0


def test_stop_attached_later_is_tested_only_from_when_it_was_set(tmp_path, monkeypatch):
    calls = run_update(tmp_path, monkeypatch, [100.0, 90.0, 120.0], [call(stop=None)], {"A.NS": {"d": "Buy"}}, {"A.NS": 110.0}, "2026-11-04")
    assert calls[0]["stop"] == 110.0 and calls[0]["stop_from"] == "2026-11-04"
    assert not calls[0].get("ended")  # the 90 close came before the exit level existed


def test_no_call_opens_with_exit_level_at_or_above_price_and_such_calls_are_dropped(tmp_path, monkeypatch):
    bad = call(price=254.55, stop=260.8, ended="2026-11-03", end_decision="Exit level ₹260.80 broken")
    calls = run_update(tmp_path, monkeypatch, [254.55, 250.0, 251.0], [bad], {"A.NS": {"d": "Buy"}}, {"A.NS": 255.0}, "2026-11-04")
    assert calls == []


def test_returns_freeze_at_the_end_of_a_call(tmp_path, monkeypatch):
    closes = [100.0] * 3 + [110.0] * 2 + [200.0] * 20  # the stock doubles after the call ended on its 5th close
    calls = run_update(tmp_path, monkeypatch, closes, [call(ended="2026-11-06", end_decision="Hold")], {"A.NS": {"d": "Hold"}}, {}, "2026-12-04")
    c = calls[0]
    assert c["to_end"] == 10.0 and c["1m"] == 10.0 and c["now"] == 10.0  # not +100%: the holder had exited
    assert c["1m_vs_nifty"] == 10.0 and c.get("3m") is None  # 3 months not reached yet


def test_held_return_freezes_after_the_end():
    c = series()
    assert _held(c, "2026-11-10", 1, None, "2026-11-12") == 10.0
    assert _held(c, "2026-11-10", 3, None, "2026-11-12") == -1.0  # past the end: the 2026-11-12 close
    assert _held(c, "2026-11-10", 5, None, "2026-11-12") is None
