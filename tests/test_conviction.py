"""Rule-built conviction (narrativ/conviction.py): offline, synthetic inputs only."""
from datetime import date

from narrativ import conviction as CV

TODAY = date(2026, 11, 20)
T = "https://nsearchives.nseindia.com/corporate/X_transcript.pdf"
P = "https://nsearchives.nseindia.com/corporate/X_presentation.pdf"


def levels(d5=2, d6=1, triggers=(), extended=False):
    return {"mom": {"t": 2, "extended": extended},
            "disc": {"items": [{"id": "D5", "m": d5, "v": "12.0% · 1Q +0.8 pts"}, {"id": "D6", "m": d6, "v": "9 mutual fund holder(s)"}]},
            "out": {"triggers": [{"id": t, "n": f"signal {t}"} for t in triggers]}}


def thesis(**kw):
    th = {"drivers": [{"kind": "capex", "due": "2027-03-31", "due_verified": True, "source": T, "text": "plant", "quote": "The new plant will start by March 2027 as planned"},
                      {"kind": "order", "due": "2027-06-30", "due_verified": True, "source": P, "text": "order", "quote": "Order of Rs 500 crore to be executed by June 2027"}],
          "audit": {"verdict": "pass", "date": "2026-11-16",
                    "checks": [{"item": "Revenue", "ok": True}, {"item": "Borrowings and lease liabilities", "ok": True}, {"item": "Equity", "ok": True}],
                    "issues": []},
          "story": {"status": "intact", "date": "2026-11-14", "text": "plant on track"}}
    th.update(kw)
    return th


MX = {"kind": "general", "quarters_available": 12, "rev_cagr_3y_pct": {"v": 18.0}, "pat_cagr_3y_pct": {"v": 22.0},
      "cfo_to_ebitda_pct": {"v": 81.0}}
BUY = {"d": "Buy", "verified": "pass"}
READER = {"model": "gemini", "items": [{"due": "2027-03-31", "quote": "The new plant will start by March 2027 as planned"}]}


def run(dec=BUY, L=None, setup=None, th=None, Mx=MX, **kw):
    return CV.assess(dec, L or levels(), setup or {"type": "Breakout"}, th if th is not None else thesis(), Mx, TODAY,
                     **({"reader": READER} | kw))


def ok(res):
    return {c["id"] for c in res["checks"] if c["ok"]}


def test_never_for_a_non_buy_or_an_unverified_buy():
    assert run(dec={"d": "Hold"}) is None
    assert run(dec={"d": "Hold", "candidate": "Buy"}) is None
    assert run(dec={"d": "Buy", "verified": "pending"}) is None


def test_score_adds_the_proofs():
    # 2 dated targets 20 + checks 15 + quote matched 5 + breakout 10 + institutions 10 = 60: Medium, half position
    r = run()
    assert r["score"] == 60 and r["level"] == "Medium" and r["size"] == "half"
    assert [p["k"] for p in r["proofs"]] == ["management", "checks", "setup", "institutions"]
    assert "No price or earnings signal live" in r["not_yet"]
    assert [c["id"] for c in r["checks"]] == [f"C{i}" for i in range(1, 8)]  # kept for app versions before 2.32


def test_strong_signals_reach_high():
    L = levels(triggers=("T11",))
    L["out"]["triggers"][0]["v"] = "+5.4% vs Nifty in 3 days after 2026-10-28 · profit +231% YoY"
    r = run(L=L)
    assert r["score"] == 72 and r["level"] == "High" and r["size"] == "full"
    assert any(p["t"].startswith("Strong ") and p["pts"] == 12 for p in r["proofs"])


def test_signals_capped_at_25_and_weak_signal_is_8():
    L = levels(triggers=("T11", "T12", "T15", "T14"))
    r = run(L=L)
    assert sum(p["pts"] for p in r["proofs"] if p["k"] == "signal") == 25


def test_no_setup_is_one_statement_and_high_capped_by_incomplete_data():
    r = run(setup={"type": "No setup"})
    assert "No entry setup yet: wait for a breakout, pullback or base" in r["not_yet"]
    L = levels(triggers=("T11", "T12", "T15"))
    r = run(L=L, Mx={"kind": "general", "quarters_available": 4})
    assert r["score"] >= 70 and r["level"] == "Medium" and "capped at Medium" in r["why"]


def test_same_target_twice_counts_once():
    th = thesis(drivers=[{"due": "2030-03-31", "due_verified": True, "text": "Long-term target of ₹32,000 crore AUM by 2030"}],
                promises=[{"due": "2030-03-31", "due_verified": True, "status": "pending", "promise": "AUM of ₹32,000 crore by 2030, 30% non-MF"}])
    assert len(CV.management_targets(th, TODAY)) == 1


def test_three_or_fewer_is_low():
    r = run(L=levels(d5=0), th=thesis(drivers=[], story={"status": "weakening"}), reader=None)
    assert r["met"] == 3 and r["level"] == "Low" and r["score"] == 25 and r["size"] == "quarter"


def test_dated_triggers_counted_once_per_document_and_within_18_months():
    same_doc = [{"kind": "capex", "due": "2027-03-31", "source": T, "due_verified": True},
                {"kind": "capacity", "due": "2027-05-31", "source": T.replace(".com", ".in"), "due_verified": True},  # same PDF, other host
                {"kind": "demand", "due": "2030-03-31", "source": P, "due_verified": True},  # beyond 18 months
                {"kind": "order", "due": "2026-10-31", "source": P, "due_verified": True}]  # already past
    assert len(CV.dated_evidence({"drivers": same_doc}, levels(triggers=("T4",)), TODAY)) == 1  # T4 never counts (as R4)
    assert len(CV.dated_evidence({"drivers": same_doc}, levels(triggers=("T11",)), TODAY)) == 2
    assert "C1" not in ok(run(th=thesis(drivers=same_doc)))


def test_unverified_promise_dates_do_not_count():
    pr = [{"kind": "results", "due": "2027-03-31", "source": P, "status": "pending", "due_verified": False}]
    assert CV.dated_evidence({"drivers": [], "promises": pr}, levels(), TODAY) == []
    pr[0]["due_verified"] = True
    assert len(CV.dated_evidence({"drivers": [], "promises": pr}, levels(), TODAY)) == 1


def test_clean_review_needs_three_checks_debt_and_no_issues():
    th = thesis()
    th["audit"]["checks"] = th["audit"]["checks"][:1]
    assert "C2" not in ok(run(th=th))
    th = thesis()
    th["audit"]["checks"] = [{"item": "Revenue", "ok": True}, {"item": "Equity", "ok": True}, {"item": "Gross NPA", "ok": True}]
    assert "C2" not in ok(run(th=th))  # no debt / lease check
    assert "C2" in ok(run(th=th, lender=True))  # lenders exempt from the debt check (as R1 / R2)
    th["audit"]["checks"][2] = {"item": "Total financial obligations", "rule": "debt_leases", "ok": True}
    assert "C2" in ok(run(th=th))  # the R7-tagged debt check counts whatever its item text (as funnel.r7_missing)
    th = thesis()
    th["audit"]["issues"] = [{"kind": "contingent", "text": "tax demand"}]
    assert "C2" not in ok(run(th=th))


def test_setup_live_and_not_extended():
    assert "C3" not in ok(run(setup={"type": "No setup"}))
    assert "C3" not in ok(run(L=levels(extended=True)))
    assert "C3" in ok(run(setup={"type": "Base"}))


def test_story_and_integrity():
    assert "C4" not in ok(run(th=thesis(story=None)))
    assert "C4" not in ok(run(dec={**BUY, "integrity": [{"id": "rf0", "status": "open"}]}))


def test_institutional_flow():
    assert "C5" not in ok(run(L=levels(d5=0)))  # holding falling
    assert "C5" not in ok(run(L=levels(d5=1, d6=1)))  # flat
    assert "C5" in ok(run(L=levels(d5=1, d6=1, triggers=("T15",))))  # mutual funds entering
    assert "C5" not in ok(run(shp={"inst_down_q": 2}))  # selling run (R5)


def test_complete_data():
    assert "C6" not in ok(run(Mx={**MX, "rev_cagr_3y_pct": None}))
    assert "C6" not in ok(run(open_issues=1))
    assert "C6" in ok(run(Mx={k: v for k, v in MX.items() if k != "cfo_to_ebitda_pct"}, lender=True))


def test_second_read():
    assert "C7" not in ok(run(reader=None))
    assert "C7" not in ok(run(reader={"items": [{"due": "2027-03-31", "quote": "Something else entirely was said here"}]}))
    assert "C7" in ok(run())


def test_calls_store_rule_conviction_and_keep_claudes_apart():
    from narrativ.calls import set_conviction
    calls = [{"symbol": "A.NS", "kind": "verified", "conviction": "medium"},  # open, Claude typed medium
             {"symbol": "B.NS", "kind": "verified", "conviction": None, "ended": "2026-11-19"},  # ended before the rule
             {"symbol": "C.NS", "kind": "candidate", "conviction": None}]
    set_conviction(calls, {"A.NS": "High", "B.NS": "Low"}, TODAY)
    a, b, c = calls
    assert a["conviction"] == "high" and a["claude_conviction"] == "medium" and a["conviction_rule"] and a["conviction_date"] == "2026-11-20"
    assert b["conviction"] is None and b["conviction_rule"] is False
    assert c["conviction"] is None and c["conviction_rule"] is False
    set_conviction(calls, {"A.NS": "Low"}, TODAY)  # set once, at entry: later levels never rewrite it
    assert a["conviction"] == "high"


def test_replay_conviction_split_compares_met_and_not_met():
    from narrativ.replay import CV_CODE, conviction_split
    gates = {g: True for g in ("eligible", "mos", "trend", "driver", "fwd", "R1", "R2", "R4", "R6")}
    res = [{"T": "2025-01-31", "rows": {"A": {**gates, "cv": {k: True for k in CV_CODE}}, "B": {**gates, "cv": {k: False for k in CV_CODE}}},
            "fwd": {"A": {"3m": (10.0, 5.0)}, "B": {"3m": (-4.0, -6.0)}}}]
    out = conviction_split(res, {"2025-01-31": ["A", "B"]})
    first = out["top10"]["inputs"][CV_CODE[0]]
    assert first["met"]["3m"]["win_pct"] == 100 and first["not met"]["3m"]["win_pct"] == 0
    assert out["top10"]["code_checks_met"][str(len(CV_CODE))]["3m"]["n"] == 1
    assert out["candidates"]["code_checks_met"]["0"]["3m"]["n"] == 1


def test_unverified_driver_dates_do_not_count():
    from datetime import date
    from narrativ import conviction as CV
    th = {"drivers": [{"kind": "capex", "due": "2027-03-31", "source": "https://a/x.pdf"}]}
    assert CV.dated_evidence(th, {"out": {}}, date(2026, 11, 20)) == []
    th["drivers"][0]["due_verified"] = True
    assert len(CV.dated_evidence(th, {"out": {}}, date(2026, 11, 20))) == 1


def test_integrity_word_in_a_passing_story_does_not_cap():
    L = levels(triggers=("T11", "T12", "T15"))
    r = run(L=L, th=thesis(story={"status": "intact", "date": "2026-11-14", "text": "no management integrity concerns"}))
    assert r["score"] >= 70 and r["level"] == "High"


def test_beat_and_delivered_targets_count_with_bonus():
    th = thesis(drivers=[], promises=[{"due": "2027-06-30", "due_verified": True, "status": "beat", "promise": "Margin of 18% by June 2027"},
                                      {"due": "2027-09-30", "due_verified": True, "status": "pending", "promise": "Plant of 500 tonnes by Sep 2027"}])
    t = CV.management_targets(th, TODAY)
    assert len(t) == 2 and [x["better"] for x in t] == [True, False]


def _tg(*rows):
    """Drivers (text, due) as verified management targets."""
    return CV.management_targets(thesis(drivers=[{"due": d, "due_verified": True, "text": t} for t, d in rows], promises=[]), TODAY)


def test_same_target_in_other_words_counts_once():
    # owner, 27 Nov 2026: each pair below was counted twice
    assert len(_tg(("Shahpur West coal mine commissioning targeted before the end of the current financial year", "2027-03-31"),
                   ("Shahpur West coal mine commissioned before the end of the current financial year", "2027-03-31"))) == 1
    assert len(_tg(("COL-II sterile facility construction to complete by Aug '27, housing 5 injectable lines", "2027-08-31"),
                   ("COL-II sterile facility at Gummidipoondi completed by August 2027", "2027-08-31"))) == 1
    assert len(_tg(("FY27 revenue growth guidance kept at high single digits", "2027-03-31"),
                   ("Yearly growth guidance kept at high single digits", "2027-03-31"))) == 1


def test_same_target_at_period_end_and_results_date_counts_once():
    assert len(_tg(("FY27 EBITDA floor raised to at least INR 310 crores", "2027-03-31"),
                   ("FY27 EBITDA of at least INR 310 crores", "2027-05-31"))) == 1
    assert len(_tg(("Q3 FY27 expected to be significantly better than Q3 of last year", "2026-12-31"),
                   ("Q3 significantly better than Q3 of the previous year", "2027-02-14"))) == 1


def test_different_targets_stay_apart():
    assert len(_tg(("50 MW captive solar plant commissioned", "2027-03-31"), ("100 MW captive solar plant commissioned", "2027-03-31"))) == 2
    assert len(_tg(("Shahpur West coal mine commissioning", "2027-03-31"), ("50 MW captive solar project commissioned", "2027-03-31"))) == 2
    assert len(_tg(("Plant A commissioning by March", "2027-03-31"), ("Plant A commissioning by March", "2027-12-31"))) == 2  # 9 months apart


def test_restated_target_keeps_raised_bonus():
    th = thesis(drivers=[{"due": "2027-03-31", "due_verified": True, "text": "FY27 EBITDA of at least INR 310 crores"}],
                promises=[{"due": "2027-05-31", "due_verified": True, "status": "raised", "promise": "FY27 EBITDA floor raised to at least INR 310 crores"}])
    t = CV.management_targets(th, TODAY)
    assert len(t) == 1 and t[0]["better"]


# ---------- v3: the forward ledger in conviction (stage 4) ----------
def _led(materials=(None, None), signals=(), cred=None):
    from narrativ.ledger import item_id
    th = thesis()
    ids = [item_id("X.NS", "claude", [d["text"], d["due"]]) for d in th["drivers"]]
    return {"items": {i: {"material": m} for i, m in zip(ids, materials)}, "signals": list(signals), "cred": cred}


def test_targets_count_by_their_size():
    base = run(sym="X.NS", led=_led())["score"]                                    # two targets of unknown size: 10 + 10
    assert run(sym="X.NS", led=_led((1, 1)))["score"] == base + 10                  # 15 + 15
    assert run(sym="X.NS", led=_led((0, 0)))["score"] == base - 10                  # 5 + 5


def test_credibility_scales_target_points():
    r = run(sym="X.NS", led=_led((1, 1), cred={"pct": 0, "n": 3}))                 # 30 x 0.5 = 15
    assert next(p for p in r["proofs"] if p["k"] == "management")["pts"] == 15


def test_material_good_signals_add_and_bad_ones_cap_or_subtract():
    good = [{"dir": "good", "material": 1, "status": "ahead", "text": "FY27 EBITDA floor"}] * 3
    r = run(sym="X.NS", led=_led(signals=good))
    assert next(p for p in r["proofs"] if p["k"] == "delivering")["pts"] == 10      # max 10
    L = levels(triggers=("T11", "T12", "T15"))
    hi = run(L=L, sym="X.NS", led=_led((1, 1)))
    assert hi["level"] == "High"
    bad = [{"dir": "bad", "material": 1, "status": "behind", "text": "FY27 revenue"}]
    capped = run(L=L, sym="X.NS", led=_led((1, 1), signals=bad))
    assert capped["level"] == "Medium" and "forward target behind" in capped["why"]
    red = [{"dir": "bad", "material": 0, "status": "red filing", "detail": {"filing": "CFO resigned"}}]
    assert run(L=L, sym="X.NS", led=_led((1, 1), signals=red))["level"] == "Medium"
    small = [{"dir": "bad", "material": 0, "status": "lowered", "text": "capex"}] * 3
    assert run(sym="X.NS", led=_led(signals=small))["score"] == run(sym="X.NS", led=_led())["score"] - 10   # max -10
