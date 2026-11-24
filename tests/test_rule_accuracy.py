"""Rule-accuracy fixes of 20 Nov 2026: one exit level, re-audit trigger, R7 in code, lender exemption, BSE-only checks,
R3 with fewer quarters, Top 10 buckets, T11 after the close, decision ladder order."""
from datetime import date

import numpy as np
import pandas as pd

from narrativ import funnel as FN
from narrativ import republish, technicals, verify
from narrativ.portfolio import top10

TODAY = date(2026, 11, 20)


def frame(closes, start="2025-01-01", end=None):
    c = pd.Series(closes, dtype=float)
    idx = pd.bdate_range(end=end, periods=len(c)) if end else pd.bdate_range(start, periods=len(c))
    return pd.DataFrame({"Close": c.values, "High": c.values + 1, "Low": c.values - 1, "Volume": 1000.0}, index=idx)


# ---------------------------------------------------------------- 1 one exit level: the setup's stop
def test_setup_stop_sits_below_the_buy_zone():
    # pullback to the 10-21 day averages with the 50-day average (old stop 98.3) inside the zone 97.71-98.05 (TALBROAUTO)
    su = FN.setup(frame(list(np.linspace(50, 100, 200)) + [100] * 40 + [90] * 3 + [99] * 5), {"stage": "Extended"}, None)
    assert su["type"] == "Pullback"
    assert su["stop"] < su["lo"] < 99 and "below the zone" in su["note"]
    assert "trail" not in su  # no second exit level


def test_breakout_zone_above_the_price_keeps_the_stop_below_both():
    su = FN.setup(frame(list(np.linspace(50, 100, 240)) + [110] * 5 + [100] * 15), {"stage": "Stage 2"}, None)  # SATIN-like
    assert su["type"] == "Breakout" and su["stop"] < 100 < su["lo"]


def test_dossier_band_is_derived_from_the_setup():
    su = {"type": "Base", "lo": 656.05, "hi": 688.85, "stop": 592.71}
    b = FN.bands(su, 670.0)
    assert b["stop"] == 592.71 and b["buy_low"] == 656.05 and b["stop_pct"] == -11.5
    assert FN.bands({"type": "No setup"}, 670.0) is None
    t = technicals.analyze(frame(list(np.linspace(50, 120, 260))), pd.Series(dtype=float))
    assert not {"stop", "stop_pct", "target", "trail", "exit_below_sma50"} & set(t["bands"])


# ---------------------------------------------------------------- 2 re-audit trigger
def _raw(**kw):
    th = {"updated": "2026-11-16", "audit": {"date": "2026-11-16", "verdict": "pass"},
          "drivers": [{"kind": "order", "text": "order 100 cr", "date": "2026-11-16"}], "story": {"status": "intact", "text": "x"}}
    return {"X.NS": th | kw}


def test_audited_research_changed_after_the_audit_goes_pending():
    stamps = {}
    assert FN.stamp_audits(_raw(), stamps, TODAY) == {}
    assert FN.stamp_audits(_raw(updated="2026-11-19"), stamps, TODAY) == {}  # `updated` alone is not a change
    later = _raw(updated="2026-11-19", drivers=[{"kind": "order", "text": "order 100 cr", "date": "2026-11-19"}])
    assert FN.stamp_audits(later, stamps, TODAY) == {}  # only a date moved
    changed = FN.stamp_audits(_raw(story={"status": "weakening", "text": "y"}), stamps, TODAY)
    assert changed == {"X.NS": ["story"]}
    ver = {"X.NS": {"audit": {"date": "2026-11-16", "verdict": "pass"}}}
    FN.mark_changed(ver, changed)
    v = FN.verification(ver["X.NS"]["audit"], None, TODAY)
    assert v["state"] == "pending" and "story" in v["why"]
    redone = _raw(story={"status": "weakening", "text": "y"}, audit={"date": "2026-11-20", "verdict": "pass"}, updated="2026-11-20")
    assert FN.stamp_audits(redone, stamps, TODAY) == {}  # a new audit is stamped with the research it judged


def test_first_seen_review_with_a_later_updated_date_is_not_a_change():
    stamps = {}  # 23 Nov 2026: rechecks that changed nothing (only `updated`) reset 10 passed reviews
    assert FN.stamp_audits(_raw(updated="2026-11-18"), stamps, TODAY) == {}


def test_editing_the_review_record_keeps_the_reviewed_baseline():
    stamps = {}
    FN.stamp_audits(_raw(), stamps, TODAY)
    # research changed and the audit object touched without a new date: still judged against what was reviewed
    edited = _raw(story={"status": "weakening", "text": "y"}, audit={"date": "2026-11-16", "verdict": "pass", "summary": "s"})
    assert FN.stamp_audits(edited, stamps, TODAY) == {"X.NS": ["story"]}


def test_repair_stamps_uses_the_reviewed_version():
    stamps = {"X.NS": {"audit": "a", "audit_date": "2026-11-16", "fields": {}, "edited_after": "2026-11-23"},
              "Y.NS": {"audit": "b", "audit_date": "2026-11-16", "fields": {}, "edited_after": "2026-11-23"}}
    th = _raw()["X.NS"]
    out = FN.repair_stamps(stamps, lambda s, d: th if s == "X.NS" else None)
    assert out == {"X.NS": "baseline from history", "Y.NS": "kept (no history)"}
    assert FN.stamp_audits({"X.NS": th}, stamps, TODAY, ["X.NS"]) == {}  # unchanged since the review: verified again
    changed = {"X.NS": th | {"story": {"status": "broken", "text": "z"}}}
    assert FN.stamp_audits(changed, stamps, TODAY, ["X.NS"]) == {"X.NS": ["story"]}


def test_future_dated_audit_is_not_valid():
    assert FN.verification({"date": "2026-12-01", "verdict": "pass"}, None, TODAY, now=TODAY)["state"] == "pending"
    assert FN.verification({"date": "2026-11-19", "verdict": "pass"}, None, TODAY, now=TODAY)["state"] == "pass"


def test_review_dated_the_calendar_day_after_the_trading_day_is_valid():
    from datetime import timedelta
    nxt = TODAY + timedelta(days=1)  # the run's data date is the last trading day; Claude dates by the calendar
    assert FN.verification({"date": str(nxt), "verdict": "pass"}, None, TODAY, now=nxt)["state"] == "pass"
    assert FN.verification({"date": str(nxt + timedelta(days=1)), "verdict": "pass"}, None, TODAY, now=nxt)["state"] == "pending"


def test_republish_turns_a_buy_with_changed_research_into_a_pending_hold():
    dec = {"d": "Buy", "why": ["Verified by Claude's full review on 2026-11-16"], "missing": []}
    v = {"audit": {"verdict": "pass", "date": "2026-11-19", "changed_after": ["drivers"]}}
    nd = republish.gate(dec, v, "2026-11-01", TODAY)
    assert nd["d"] == "Hold" and nd["candidate"] == "Buy" and nd["verified"] == "pending"
    assert any("drivers" in m for m in nd["missing"])


# ---------------------------------------------------------------- 3 R7 in code
TRIG = {"out": {"triggers": [{"id": "T11"}]}, "val": {"t": 2, "name": "Undervalued"}, "disc": {"t": 1, "name": "Undiscovered"}}
GOOD = {"cfo_to_ebitda_pct": {"v": 80, "exact": 80.0, "in": {"years": 3}}}
DEBT = {"item": "Borrowings and lease liabilities", "rule": "debt_leases", "ok": True}
RP = {"status": "quoted", "text": "purchases 2%", "quote": "q", "source": "u"}


def test_r7_missing_items():
    miss = FN.r7_missing({"verdict": "pass", "checks": []}, GOOD, False, TRIG)
    assert [m[:12] for m in miss] == ["R7 total deb", "R7 related-p"]
    assert FN.r7_missing({"checks": [DEBT], "related_party": RP}, GOOD, False, TRIG) == []
    old_style = [{"item": "Non-current borrowings"}, {"item": "Lease liabilities"}]  # older audits: debt and leases by item name
    assert FN.r7_missing({"checks": old_style, "related_party": RP}, GOOD, False, TRIG) == []
    assert FN.r7_missing({"related_party": RP}, GOOD, "bank", TRIG) == []  # lenders: no debt-with-leases check
    flagged = GOOD | {"pat_yoy_pct": {"v": 60}}
    m = FN.r7_missing({"checks": [DEBT], "related_party": RP}, flagged, False, TRIG)
    assert len(m) == 1 and "(profit_jump)" in m[0]
    assert FN.r7_missing({"checks": [DEBT], "related_party": RP, "flag_notes": [{"flag": "profit_jump"}]}, flagged, False, TRIG) == []


def test_passed_review_without_r7_items_is_verification_pending():
    d0 = {"d": "Buy", "why": ["Verified by Claude's full review on 2026-11-19"], "verified": "pass"}
    d = FN.apply_buy_rules(d0, GOOD, False, TRIG, {"audit": {"verdict": "pass", "checks": [DEBT]}}, TODAY)
    assert d["d"] == "Hold" and d["candidate"] == "Buy" and d["verified"] == "pending"
    assert any(m.startswith("Verification pending: R7 related-party") for m in d["missing"])
    ok = FN.apply_buy_rules(d0, GOOD, False, TRIG, {"audit": {"verdict": "pass", "checks": [DEBT], "related_party": RP}}, TODAY)
    assert ok["d"] == "Buy"


def test_verifier_keeps_quoted_r7_items(monkeypatch):
    monkeypatch.setattr(verify, "fetch_text", lambda src: "Purchases from related parties were 12.5 crore in the half year.")
    rej = []
    out = verify.audit_r7({"related_party": {"status": "quoted", "text": "purchases 12.5 crore", "quote": "Purchases from related parties were 12.5 crore",
                                             "source": "https://x"},
                           "flag_notes": [{"flag": "profit_jump", "note": "base quarter was weak", "quote": "Purchases from related parties", "source": "https://x"},
                                          {"flag": "cheap", "note": "made up 99", "quote": "not in the filing", "source": "https://x"}],
                           "bse_only_note": {"text": "BSE shareholding pattern read", "source": "https://bse"}}, rej)
    assert out["related_party"]["status"] == "quoted" and [f["flag"] for f in out["flag_notes"]] == ["profit_jump"]
    assert out["bse_only_note"]["text"].startswith("BSE") and len(rej) == 1
    rej = []
    assert verify.audit_r7({"related_party": {"status": "not disclosed", "source": "https://x"}}, rej) == {} and rej  # needs `checked`


# ---------------------------------------------------------------- 4 lender exemption and BSE-only checks
def test_lender_type():
    assert FN.lender_type("bank", "NSE filing", "Financial Services", "Banks", "Private Sector Bank") == "bank"
    assert FN.lender_type("nbfc", "NSE filing", "Financial Services", "Finance", "Housing Finance Company") == "hfc"
    assert FN.lender_type(None, "Yahoo statements", "Financial Services", "Insurance", "Life Insurance") == "insurer"
    assert FN.lender_type(None, "BSE results summary", "Financial Services", "Capital Markets", "Stockbroking & Allied") == ""
    assert FN.lender_type("nbfc", "NSE filing", "Financial Services", "Capital Markets", "Asset Management Company") == ""
    assert FN.lender_type(None, "BSE results summary", "Financial Services", "Finance", "Non Banking Financial Company (NBFC)") == "nbfc"
    assert FN.lender_type("general", "NSE filing", "Industrials", "Construction", float("nan")) == ""


def test_insurer_exempt_with_label_and_broker_gated():
    d = FN.apply_buy_rules({"d": "Hold", "candidate": "Buy", "why": []}, {"cfo_to_ebitda_pct": {"v": -20, "exact": -20.0, "in": {}}}, "insurer", TRIG, {}, TODAY)
    assert "gates" not in d and any("not applied: insurer" in w for w in d["why"])
    d = FN.apply_buy_rules({"d": "Hold", "candidate": "Buy", "why": []}, {"cfo_to_ebitda_pct": {"v": -20, "exact": -20.0, "in": {}}}, "", TRIG, {}, TODAY)
    assert d["gates"][0].startswith("R1")


def test_bse_only_buy_needs_the_review_to_note_unevaluated_checks():
    L = TRIG | {"out": {"triggers": [{"id": "T11"}], "not_evaluated": FN.BSE_NOT_EVALUATED}}
    d0 = {"d": "Buy", "why": [], "verified": "pass"}
    th = {"audit": {"verdict": "pass", "checks": [DEBT], "related_party": RP}}
    d = FN.apply_buy_rules(d0, GOOD, False, L, th, TODAY)
    assert d["d"] == "Hold" and any("BSE-only" in m for m in d["missing"])
    assert any(w.startswith("Not evaluated (BSE-only") for w in d["why"])
    th["audit"]["bse_only_note"] = {"text": "BSE shareholding read", "source": "u"}
    assert FN.apply_buy_rules(d0, GOOD, False, L, th, TODAY)["d"] == "Buy"


# ---------------------------------------------------------------- 5 R3 with 8 to 11 quarters
def _val(qs):
    Mx = {"quarterly": qs}
    return FN.valuation(Mx, "Standard", "pe", 10.0, [{"pe": 20.0}] * 8, {"n": 6, "median": 20.0, "scope": "peers"}, False)


def test_r3_margin_peak_with_fewer_than_12_quarters():
    q = lambda m: ["2025-01-01", 100, 10, m]  # noqa: E731
    assert _val([q(5)] * 6 + [q(15)] * 4)["t"] == 3  # 10 quarters: last 4 vs the 6 before
    assert any("in the 6 before" in (i.get("v") or "") for i in _val([q(5)] * 6 + [q(15)] * 4)["items"])
    assert _val([q(5)] * 3 + [q(15)] * 4)["t"] == 2  # 7 quarters: not enough history


# ---------------------------------------------------------------- 6 Top 10 without an industry
def test_top10_stocks_without_industry_do_not_share_one_bucket():
    rows = [{"s": f"S{k}", "rk": k, "i": None, "sec": f"X{k}", "mc": 10000, "dc": "Buy", "vf": "pass"} for k in range(1, 4)]
    assert top10(rows) == ["S1", "S2", "S3"]  # used to stop at 2 ("?" industry)
    rows = [{"s": f"S{k}", "rk": k, "i": None, "sec": "Same", "mc": 10000, "dc": "Buy", "vf": "pass"} for k in range(1, 4)]
    assert top10(rows) == ["S1", "S2"]  # the sector stands in for the industry
    rows = [{"s": f"S{k}", "rk": k, "mc": 10000, "dc": "Buy", "vf": "pass"} for k in range(1, 5)]
    assert top10(rows) == ["S1", "S2", "S3", "S4"]  # nothing known: each stock its own bucket


# ---------------------------------------------------------------- 7 T11 window after an after-close filing
def _t11(time_):
    closes = [100.0] * 20 + [106.0] + [108.0] * 3  # filing day 2026-11-05 closes at 106 (before the results)
    df = frame(closes, end="2026-11-10")
    assert str(df.index[20].date()) == "2026-11-05"
    Mx = {"filed": "2026-11-05", "filed_time": time_, "pat_yoy_pct": {"v": 30}}
    return [x[0] for x in FN.signal_triggers(df, None, Mx, None, None, [], date(2026, 11, 12), 1000)]


def test_t11_window_starts_next_day_after_a_late_filing():
    assert _t11("11:00") == ["T11"]  # filed in market hours: +8% from the day before
    assert _t11("16:05") == []  # filed after the close: +1.9% from the filing day's close


def test_filing_time_from_the_exchange_api_only():
    from narrativ.filings import _hm
    assert _hm("05-Nov-2026 18:43:22") == "18:43" and _hm("05-Nov-2026") is None
    url = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1754357_05112026064322_WEB.xml"
    assert FN.filed_time({"filed": "2026-11-05", "pat_ttm_cr": {"v": 1, "url": url}}) is None  # 12-hour file-name clock: not used
    assert FN.filed_time({"filed_time": "18:43"}) == "18:43"


# ---------------------------------------------------------------- 8 decision ladder
def _L(stage="Stage 2", mom_t=3):
    L = {k: {"t": 2, "name": "x", "items": []} for k in FN.LEVELS}
    L["mom"] = {"t": mom_t, "name": "x", "items": [{"id": "P1", "v": stage}]}
    return L


def test_code_trigger_counts_as_forward_driver():  # owner, 24 Nov 2026 (idea 1)
    L = _L()
    L["out"]["triggers"] = [{"id": "T4", "n": "Capacity coming"}]
    assert FN.decision(L, None, {}, None, None, 100, None, today=TODAY)["why"][0].startswith("No trigger yet")  # T4 alone is not one
    L["out"]["triggers"].append({"id": "T2", "n": "Results beat"})
    d = FN.decision(L, None, {}, None, None, 100, None, today=TODAY)
    assert d["d"] != "Not rated" and not d["why"][0].startswith("No trigger yet")
    assert any(w == "Signal: T2 Results beat" for w in d["why"])


def test_sell_reasons_come_before_not_rated():
    d = FN.decision(_L(), None, {"story": {"status": "broken", "text": "Main contract cancelled"}}, None, None, 100, None, today=TODAY)
    assert d["d"] == "Sell" and d["why"][0].startswith("Story broken")


def test_story_weakening_in_a_downtrend_is_sell_without_momentum_tier_5():
    th = {"story": {"status": "weakening", "text": "orders slowing"}, "drivers": [{"kind": "order", "text": "order"}]}
    assert FN.decision(_L("Downtrend", 4), None, th, None, None, 100, None, today=TODAY)["d"] == "Sell"
    assert FN.decision(_L("Stage 2", 4), None, th, None, None, 100, None, today=TODAY)["d"] != "Sell"
