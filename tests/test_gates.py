from datetime import date

from narrativ import funnel as FN
from narrativ import republish

TODAY = date(2026, 11, 20)
TRIG = {"out": {"triggers": [{"id": "T11", "n": "Results beat"}]}, "val": {"t": 2, "name": "Undervalued"}, "disc": {"t": 1, "name": "Undiscovered"}}


def mx(cc=None, oi=None, years=3, exact=True):
    M = {}
    if cc is not None:
        M["cfo_to_ebitda_pct"] = {"v": round(cc), "in": {"cfo_cr": cc, "ebitda_cr": 100.0, "years": years}}
        if exact:
            M["cfo_to_ebitda_pct"]["exact"] = cc
    if oi is not None:
        M["other_income_pct_pbt"] = {"v": oi}
    return M


# ---------------------------------------------------------------- R1 on the unrounded value
def test_r1_needs_positive_operating_cash_flow():
    assert FN.cash_conversion(mx(49.5)) == (49.5, 3)
    assert FN.buy_gates(mx(36.9), False, TRIG, {}, TODAY) == []  # SRM-like: a growing company tying up cash passes since 23 Nov
    g = FN.buy_gates(mx(-3.8), False, TRIG, {}, TODAY)  # ASIANENE-like: operations lost cash
    assert len(g) == 1 and g[0].startswith("R1 operations did not bring in cash: cash conversion -3.8%")
    assert len(FN.buy_gates(mx(0.0), False, TRIG, {}, TODAY)) == 1
    assert FN.buy_gates(mx(0.4), False, TRIG, {}, TODAY) == []  # the unrounded value is compared


def test_r1_falls_back_to_the_inputs_for_older_data_and_marks_two_years():
    assert FN.cash_conversion(mx(49.5, years=2, exact=False)) == (49.5, 2)
    assert "only 2 full years filed" in FN.buy_gates(mx(-5.0, years=2), False, TRIG, {}, TODAY)[0]
    assert FN.buy_gates(mx(-10.0), True, TRIG, {}, TODAY) == []  # lenders exempt


# ---------------------------------------------------------------- shared gates and the data-issue hold
def test_gates_r2_r4_r6():
    L = {"out": {"triggers": [{"id": "T4"}]}, "val": {"t": 3, "name": "Fairly valued"}, "disc": {"t": 4, "name": "Well discovered"}}
    g = FN.buy_gates(mx(80, oi=30), False, L, {}, TODAY)
    assert [x[:2] for x in g] == ["R2", "R4", "R6"]
    th = {"other_income_recurring": {"text": "JV profit"}, "drivers": [{"due": "2027-06-30", "due_verified": True, "text": "plant"}]}
    assert [x[:2] for x in FN.buy_gates(mx(80, oi=30), False, L, th, TODAY)] == ["R6"]


def test_r4_passes_on_top_third_relative_strength():
    L = {"out": {"triggers": []}, "val": {"t": 2}, "disc": {"t": 1},
         "mom": {"items": [{"id": "P2", "pts": [11.5, 15]}]}}  # 77th percentile, read from P2 (older stored levels)
    assert FN.buy_gates(mx(80), False, L, {}, TODAY) == []
    weak = {**L, "mom": {"rs_pct": 0.44, "items": []}}  # DSSL-like
    g = FN.buy_gates(mx(80), False, weak, {}, TODAY)
    assert len(g) == 1 and g[0].startswith("R4") and "44th percentile" in g[0]
    assert FN.rs_pct_of({"mom": {"rs_pct": 0.7}}) == 0.7 and FN.rs_pct_of({}) is None


def test_apply_buy_rules_holds_for_open_issues_and_failed_gates():
    d = FN.apply_buy_rules({"d": "Buy", "why": []}, mx(80), False, TRIG, {}, TODAY, [{"field": "equity_cr"}])
    assert d["d"] == "Hold" and d["candidate"] == "Buy" and "under correction" in d["why"][0]
    d = FN.apply_buy_rules({"d": "Strong Buy", "why": []}, mx(-5), False, TRIG, {}, TODAY, None, 3)
    assert d["d"] == "Hold" and d["gates"][0].startswith("R1") and "Scores say Buy" in d["why"][0]  # R5 capped first
    assert FN.apply_buy_rules({"d": "Hold", "why": []}, mx(-5), False, TRIG, {}, TODAY) == {"d": "Hold", "why": []}


# ---------------------------------------------------------------- republish applies the same rules as the daily run
PASS = {"audit": {"verdict": "pass", "date": "2026-11-19",  # complete for RULES.md R7 (funnel.r7_missing)
                  "checks": [{"item": "Borrowings and lease liabilities", "rule": "debt_leases", "ok": True}],
                  "related_party": {"status": "not disclosed", "checked": "results notes", "source": "u"}}}
CAND = {"d": "Hold", "candidate": "Buy", "why": ["Rules say Buy: waiting for Narrativ.ai's full review"], "missing": ["Verification pending"]}


def test_republish_pass_becomes_buy_when_the_gates_hold():
    nd = republish.gate(CAND, PASS, "2026-11-01", TODAY, mx(80), TRIG, False, [])
    assert nd["d"] == "Buy" and nd["verified"] == "pass"


def test_republish_rechecks_r2_against_the_verified_research():
    nd = republish.gate(CAND, PASS, "2026-11-01", TODAY, mx(80, oi=40), TRIG, False, [])
    assert nd["d"] == "Hold" and nd["gates"][0].startswith("R2")
    th = PASS | {"other_income_recurring": {"text": "JV share of profit", "quote": "q", "source": "u"}}
    assert republish.gate(CAND, th, "2026-11-01", TODAY, mx(80, oi=40), TRIG, False, [])["d"] == "Buy"


def test_republish_rechecks_r4_drivers():
    L = TRIG | {"out": {"triggers": None}}
    assert republish.gate(CAND, PASS, "2026-11-01", TODAY, mx(80), L, False, [])["gates"][0].startswith("R4")
    th = PASS | {"drivers": [{"due": "2027-03-31", "due_verified": True, "text": "new plant"}]}
    assert republish.gate(CAND, th, "2026-11-01", TODAY, mx(80), L, False, [])["d"] == "Buy"


def test_republish_keeps_open_data_issues_at_hold():
    nd = republish.gate(CAND, PASS, "2026-11-01", TODAY, mx(80), TRIG, False, [{"field": "pat_ttm_cr"}])
    assert nd["d"] == "Hold" and nd["candidate"] == "Buy" and "under correction" in nd["why"][0]


def test_republish_pending_review_still_drops_a_failed_gate():
    nd = republish.gate(CAND, {}, "2026-11-01", TODAY, mx(80, oi=40), TRIG, False, [])
    assert nd["d"] == "Hold" and nd["gates"][0].startswith("R2") and "candidate" not in nd
    assert republish.gate(CAND, {}, "2026-11-01", TODAY, mx(80), TRIG, False, []) is None  # nothing changes


# ---------------------------------------------------------------- Outlook removal counts T11-T15
def test_outlook_counts_price_signals_before_removal():
    wind = {"wind": "Headwind", "median": 1.9, "median_prev": 5.5, "breadth": 44, "n": 18}
    lv = {"items": []}
    args = ({}, wind, None, {}, {"checklist": {}}, [], lv, lv, lv)
    assert FN.outlook(*args)["out"] is True
    o = FN.outlook(*args, signals=[("T11", "Results beat", "+6.3% vs Nifty", False), ("T14", "Buyback announced", "filed", True)])
    assert not o.get("out") and o["nlive"] == 2 and [t["id"] for t in o["triggers"]] == ["T11", "T14"]
    assert o["t"] != 5 and o["s"] == 25  # headwind 0 + 10 + 15


# ---------------------------------------------------------------- republish releases a stock the daily run's gates held
def test_gated_stock_keeps_its_label_but_no_candidate():
    d = FN.apply_buy_rules(CAND, mx(80, oi=40), False, TRIG, {}, TODAY)
    assert d["d"] == "Hold" and d["gated_label"] == "Buy" and "candidate" not in d  # no review queued, no candidate call
    assert FN.ungate(d) == CAND  # back to the decision before the gates
    assert FN.apply_buy_rules(d, mx(80, oi=40), False, TRIG, {}, TODAY) == d  # gating again is stable


def test_republish_releases_a_gated_candidate_when_r2_is_answered():
    held = FN.apply_buy_rules(CAND, mx(80, oi=40), False, TRIG, {}, TODAY)  # the daily run: R2 holds, review pending
    assert republish.gate(held, {}, "2026-11-01", TODAY, mx(80, oi=40), TRIG, False, []) is None  # nothing new: no change
    oir = {"other_income_recurring": {"text": "JV share of profit", "quote": "q", "source": "u"}}
    nd = republish.gate(held, PASS | oir, "2026-11-01", TODAY, mx(80, oi=40), TRIG, False, [])
    assert nd["d"] == "Buy" and nd["verified"] == "pass" and "gates" not in nd and "gated_label" not in nd
    assert not any(w.startswith(("Scores say", "R2")) for w in nd["why"])
    # the recurring quote but no review yet: back to a candidate waiting for Claude's review
    nd = republish.gate(held, oir, "2026-11-01", TODAY, mx(80, oi=40), TRIG, False, [])
    assert nd["d"] == "Hold" and nd["candidate"] == "Buy" and "gates" not in nd


def test_republish_releases_a_verified_buy_held_by_r4_once_a_dated_driver_verifies():
    L = TRIG | {"out": {"triggers": None}}
    verified = {"d": "Buy", "verified": "pass", "why": ["Verified by Claude's full review on 2026-11-19"], "missing": []}
    held = FN.apply_buy_rules(verified, mx(80), False, L, PASS, TODAY)
    assert held["d"] == "Hold" and held["gates"][0].startswith("R4") and held["gated_label"] == "Buy"
    assert republish.gate(held, PASS, "2026-11-01", TODAY, mx(80), L, False, [])["d"] == "Hold"  # still no dated driver
    th = PASS | {"drivers": [{"due": "2027-03-31", "due_verified": True, "text": "new plant"}]}
    nd = republish.gate(held, th, "2026-11-01", TODAY, mx(80), L, False, [])
    assert nd["d"] == "Buy" and "gates" not in nd
