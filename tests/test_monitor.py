"""Forward ledger stage 2: progress against filed quarters, resolution, restatements and targets not restated."""
from datetime import date

from narrativ import ledger as LG
from narrativ import monitor as MO

CR = 1e7


def fin(quarters: dict, margin=0.2):
    """{quarter end: revenue crore}; EBITDA at `margin`; filed 45 days after the quarter."""
    q = {}
    for qe, rev in quarters.items():
        r = rev * CR
        d = date.fromisoformat(qe)
        q[qe] = {"Consolidated": {"q": {"rev": r, "exp": r * (1 - margin), "fin": 0.0, "dep": 0.0, "pat": r * 0.1, "eps": 1.0},
                                  "end": qe, "filed": str(date.fromordinal(d.toordinal() + 45)), "flags": []}}
    return {"basis": "Consolidated", "quarters": q}


# FY26: 100 a quarter (400); FY27 H1: 120 + 130 (last year's H1 share 50%, so 500 projected)
FIN = fin({"2024-06-30": 90, "2024-09-30": 90, "2024-12-31": 90, "2025-03-31": 90,
           "2025-06-30": 100, "2025-09-30": 100, "2025-12-31": 100, "2026-03-31": 100,
           "2026-06-30": 120, "2026-09-30": 130})
TODAY = date(2026, 11, 30)


def item(low, high, measure="revenue", unit="cr", fy="FY27", src="narrativ", of="company", growth_of=None):
    t = {"measure": measure, "of": of, "low": low, "high": high, "unit": unit, "fy": fy}
    if growth_of:
        t["growth_of"] = growth_of
    m = f"growth:{growth_of}" if growth_of else measure
    return {"src": src, "measure": m, "period": "2027-03-31", "target": t}


def series():
    return LG.Bases({"ACME.NS": FIN}).series("ACME.NS")


def status(it, today=TODAY):
    r = MO.check_progress(it, series(), today)
    return r and r["status"]


def test_progress_projects_with_last_years_seasonality():
    r = MO.check_progress(item(480, 520), series(), TODAY)
    assert r["k"] == 2 and r["projected"] == 500.0 and r["share_ly"] == 0.5 and r["status"] == "on track"
    assert status(item(600, 650)) == "behind"
    assert status(item(400, 420)) == "ahead"


def test_growth_and_margin_targets():
    assert status(item(20, 25, measure="growth", unit="%", growth_of="revenue")) == "on track"   # 500 / 400 = +25%
    assert status(item(35, 40, measure="growth", unit="%", growth_of="revenue")) == "behind"
    assert status(item(19, 21, measure="margin", unit="%")) == "on track"                         # 20% filed
    assert status(item(24, 25, measure="margin", unit="%")) == "behind"


def test_one_quarter_is_too_early_to_judge():
    assert status(item(600, 650), today=date(2026, 9, 1)) == "early"   # only Jun-26 filed by then


def test_only_verified_company_targets_with_a_named_year_are_tracked():
    assert MO.check_progress(item(480, 520, src="parsed"), series(), TODAY) is None
    assert MO.check_progress(item(480, 520, fy=None), series(), TODAY) is None
    assert MO.check_progress(item(200, 220, of="part: forging"), series(), TODAY) is None


def test_resolution_once_the_year_is_filed():
    full = fin({**{k: 100 for k in ("2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31")},
                "2026-06-30": 120, "2026-09-30": 130, "2026-12-31": 130, "2027-03-31": 140})   # FY27 = 520
    s = LG.Bases({"X.NS": full}).series("X.NS")
    assert MO.check_progress(item(480, 500), s, date(2027, 6, 1))["status"] == "beat"
    assert MO.check_progress(item(500, 530), s, date(2027, 6, 1))["status"] == "met"
    assert MO.check_progress(item(560, 600), s, date(2027, 6, 1))["status"] == "missed"


def test_run_signals_restatement_and_target_not_restated(tmp_path, monkeypatch):
    monkeypatch.setattr(MO, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(MO, "SIGNALS", tmp_path / "signals.json")
    q = "We guide FY27 revenue of INR 600 crores."
    th = {"ACME.NS": {"quarter": "Q1 FY27", "drivers": [
        {"text": "FY27 revenue of Rs 600 crore", "due": "2027-03-31", "date": "2026-08-10", "quote": q,
         "target": {"measure": "revenue", "of": "company", "low": 600, "high": 600, "unit": "cr", "fy": "FY27"}}]}}
    out = MO.run(th, TODAY, {"ACME.NS": FIN})
    assert out["bad"] == 1    # 500 projected vs 600: behind
    th2 = {"ACME.NS": {"quarter": "Q2 FY27", "drivers": [
        {"text": "Plant to start by March 2027", "due": "2027-03-31", "date": "2026-11-12", "quote": "Plant by March 2027."}]}}
    out = MO.run(th2, date(2026, 12, 1), {"ACME.NS": FIN})
    assert out["flags"] == 1  # the FY27 revenue target of the Q1 call is not in the Q2 research
