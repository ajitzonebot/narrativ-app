"""The history replay follows the live rules it can rebuild (25 Nov 2026 audit): the forward-driver step of the decision
ladder (funnel.decision) and the readiness setup tier (run.py readiness, funnel.setup_tier)."""
from narrativ import funnel as FN
from narrativ import replay as R


def _rows(**over):
    base = {"eligible": True, "mos": True, "trend": True, "driver": True, "fwd": True, "R1": True, "R2": True, "R4": True,
            "R6": True, "rs": 50, "near": 50, "vs": 50, "pr": 0, "setup": 0, "mb": False, "i": None, "sec": None, "mc": 10000}
    return {s: {**base, "i": s, "sec": s, **over.get(s, {})} for s in ("A", "B")}


def test_forward_driver_and_direction_from_code_triggers():
    t11, t9, t4 = {"id": "T11"}, {"id": "T9"}, {"id": "T4"}
    assert R.forward([], "Stage 2") == (False, False)  # live: Hold "No trigger yet"
    assert R.forward([t4], "Stage 2") == (False, False)  # T4 alone is no forward driver
    assert R.forward([t11], "Stage 1") == (True, False)  # 1 driver needs a rising price for fwd_pos
    assert R.forward([t11], "Stage 2") == (True, True)
    assert R.forward([t11], "Stage 1→2") == (True, True)
    assert R.forward([t11, t11], "Basing") == (True, False)  # distinct triggers
    assert R.forward([t11, t9], "Basing") == (True, True)


def test_current_rules_require_a_driver_and_old_variant_does_not():
    rows = _rows(A={"driver": False, "fwd": False, "rs": 90})
    assert "driver" in R.CUR and "fwd" in R.CUR and R.VARIANTS["current rules"][0] == R.CUR
    assert R._pick(rows, *R.VARIANTS["current rules"]) == ["B"]
    assert R._pick(rows, *R.VARIANTS["(old) without driver requirement"]) == ["A", "B"]
    assert "R4" not in R.VARIANTS["(old) without driver requirement, without R4 dated trigger"][0]
    for name, (gates, _) in R.VARIANTS.items():  # every variant runs on the current rules unless it says "(old)"
        if not name.startswith(("(old)", "driver:")):  # "driver:" variants replace the driver rule on purpose
            assert "driver" in gates, name


def test_setup_tier_matches_the_live_readiness():
    assert FN.setup_tier({"type": "Breakout"}, False) == 0
    assert FN.setup_tier({"type": "Breakout"}, True) == 2  # extended
    assert FN.setup_tier({"type": "No setup", "note": "No entry: trend broken (below the 200-day average)"}, False) == 2
    assert FN.setup_tier({"type": "No setup", "note": "Extended: wait for a pullback"}, False) == 2
    assert FN.setup_tier({"type": "No setup", "note": "Wait: not at a breakout, pullback or base level"}, False) == 1
    assert FN.setup_tier(None, False) == 1
    rows = _rows(A={"setup": 2, "setup_old": 1, "rs": 90}, B={"setup": 1, "setup_old": 1})
    assert R._pick(rows, R.CUR, R.BASE_W) == ["B", "A"]  # a broken-trend "No setup" ranks last, as live
    assert R._pick(rows, R.CUR, {**R.BASE_W, "_oldsetup": 1}) == ["A", "B"]  # the replay before 25 Nov 2026
