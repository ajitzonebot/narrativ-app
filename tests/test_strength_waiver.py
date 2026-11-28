"""Strength waiver (owner, 25 Nov 2026; RULES.md decision ladder step 3): a scored stock with no forward driver whose
relative strength is in the top third gets "Signal: Price strength" as its driver, which alone is a positive direction.
It is not a dated trigger (conviction C1, MB), and the replay's current rules follow it."""
from datetime import date

from narrativ import conviction as CV
from narrativ import funnel as FN
from narrativ import replay as R

TODAY = date(2026, 11, 25)


def _L(rs, stage="Stage 1"):
    L = {k: {"t": 2, "name": "x", "items": []} for k in FN.LEVELS}
    L["mom"] = {"t": 3, "name": "x", "rs_pct": rs, "items": [{"id": "P1", "v": stage}]}
    return L


def test_top_third_strength_is_the_driver_and_a_positive_direction():
    d = FN.decision(_L(0.8), None, {}, None, None, 100, None, today=TODAY)
    assert d["d"] == "Hold" and d.get("candidate") == "Buy"  # continues down the ladder: a Buy candidate for review
    assert "Signal: Price strength: relative strength in the top third (80th percentile)" in d["why"]
    assert FN.strength_driver(2 / 3)["text"].endswith("(67th percentile)")


def test_below_top_third_stays_no_trigger_yet():
    d = FN.decision(_L(0.6), None, {}, None, None, 100, None, today=TODAY)
    assert d["d"] == "Hold" and not d.get("candidate") and d["why"][0].startswith("No trigger yet")
    d = FN.decision(_L(None), None, {}, None, None, 100, None, today=TODAY)  # relative strength unknown: no waiver
    assert d["why"][0].startswith("No trigger yet")


def test_not_enough_data_stays_not_rated():
    assert FN.decision(_L(0.9), None, {}, None, None, 100, None, today=TODAY, scored=False)["d"] == "Not rated"


def test_strength_is_a_positive_direction_with_one_driver():
    th = {"drivers": [{"kind": "order", "text": "Order win"}]}
    d = FN.decision(_L(0.9), None, th, None, None, 100, None, today=TODAY)  # 1 driver, price not rising, strength top third
    assert not any("Price strength" in w for w in d["why"]) and d.get("candidate") == "Buy"  # as the replayed variant
    d = FN.decision(_L(0.5), None, th, None, None, 100, None, today=TODAY)  # strength below the top third: unchanged
    assert not d.get("candidate") and any(w.startswith("Forward direction not yet positive") for w in d["why"])
    L = _L(0.9)
    L["out"]["triggers"] = [{"id": "T11", "n": "Results beat"}]
    d = FN.decision(L, None, {}, None, None, 100, None, today=TODAY)  # a code trigger is the driver, as before
    assert not any("Price strength" in w for w in d["why"]) and any(w == "Signal: Results beat" for w in d["why"])


def test_strength_is_not_a_dated_trigger():
    assert CV.dated_evidence({}, _L(0.95), TODAY) == []  # conviction C1
    assert FN.code_triggers(_L(0.95)) == []  # MB / R4 first leg (run.py counts code triggers and verified dated drivers)


def test_replay_current_rules_follow_the_waiver():
    t11 = {"id": "T11"}
    assert R.forward_waiver([], "Basing", True) == (True, True)
    assert R.forward_waiver([], "Stage 2", False) == (False, False)
    assert R.forward_waiver([t11], "Basing", True) == (True, True)  # top-third strength is a positive direction
    assert R.forward_waiver([t11], "Basing", False) == (True, False)
    assert R.forward_waiver([t11], "Stage 2", False) == (True, True)
    old = R.VARIANTS["(old) driver rule without strength waiver (24-25 Nov 2026)"][0]
    assert "driver_old" in old and "fwd_old" in old and "driver" not in old
    rows = {s: {"eligible": True, "mos": True, "trend": True, "driver": True, "fwd": True, "driver_old": s == "B",
                "fwd_old": s == "B", "R1": True, "R2": True, "R4": True, "R6": True, "rs": 50, "near": 50, "vs": 50, "pr": 0,
                "setup": 0, "mb": False, "i": s, "sec": s, "mc": 10000} for s in ("A", "B")}
    assert R._pick(rows, *R.VARIANTS["current rules"]) == ["A", "B"]
    assert R._pick(rows, *R.VARIANTS["(old) driver rule without strength waiver (24-25 Nov 2026)"]) == ["B"]
