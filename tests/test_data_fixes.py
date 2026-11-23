"""Offline tests for the data fixes: unit (scale) guard, Reg-33 year-to-date parsing, correction units, ROE n/m,
break-even quarters, implausible share counts and honest multi-year labels."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from narrativ import corrections, filings, issues  # noqa: E402
from narrativ import metrics as MX  # noqa: E402

CR = 1e7
ENDS = ["2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30",
        "2026-09-30"]


def _q(rev_cr, exp_cr=None, pat_cr=None, cap_cr=13.6, fv=5.0, eps=3.0, rounding=None, equity_cr=None):
    exp_cr = rev_cr * 0.85 if exp_cr is None else exp_cr
    pat_cr = rev_cr * 0.12 if pat_cr is None else pat_cr
    q = {"rev": rev_cr * CR, "exp": exp_cr * CR, "pat": pat_cr * CR, "pat_owners": pat_cr * CR, "oi": 1 * CR, "fin": 2 * CR,
         "dep": 5 * CR, "pbt": pat_cr * 1.3 * CR, "share_cap": cap_cr * CR, "fv": fv, "eps": eps}
    p = {"q": q, "ytd": {}, "bs": {}, "shares": cap_cr * CR / fv, "flags": [], "url": "u", "filed": "f", "kind": "general"}
    if equity_cr is not None:
        p["bs"] = {"equity": equity_cr * CR, "equity_owners": equity_cr * CR}
    if rounding:
        p["rounding"] = rounding
    return p


def _fin(quarters: dict) -> dict:
    return {"basis": "Consolidated", "quarters": {qe: {"Consolidated": p} for qe, p in quarters.items()}}


def _metro(bad: dict | None = None, bad_end="2025-09-30") -> dict:
    """METROBRAND-like series: ~₹650-800 cr a quarter, one quarter filed 100x too small."""
    qs = {e: _q(650 + 20 * i, equity_cr=2500 + 50 * i if e[5:7] in ("03", "09") else None) for i, e in enumerate(ENDS)}
    if bad is not None:
        qs[bad_end] = bad
    return _fin(qs)


# ---------------------------------------------------------------- 1. scale guard
def test_scale_error_confirmed_by_paid_up_capital_is_corrected():
    good = _q(651.14, equity_cr=2600)
    bad = copy.deepcopy(good)
    for part in ("q", "bs"):
        bad[part] = {k: (v / 100 if k not in ("fv", "eps") else v) for k, v in bad[part].items()}
    bad["shares"] = good["shares"] / 100
    s = MX.series(_metro(bad))
    p = s["q"]["2025-09-30"]
    assert p["q"]["rev"] == pytest.approx(651.14 * CR)
    assert p["bs"]["equity"] == pytest.approx(2600 * CR)
    assert p["shares"] == pytest.approx(good["shares"])
    assert p["q"]["eps"] == good["q"]["eps"]  # per-share figures are not rescaled
    assert [e["action"] for e in s["scale"]] == ["corrected"]
    assert s["scale"][0]["factor"] == 100


def test_scale_error_confirmed_by_declared_rounding_is_corrected():
    qs = {e: _q(650 + 20 * i, rounding="Crores") for i, e in enumerate(ENDS)}
    bad = _q(6.5, cap_cr=13.6, rounding="Lakhs")  # capital not off (filer typed it right): rounding confirms instead
    qs["2025-09-30"] = bad
    s = MX.series(_fin(qs))
    assert s["scale"][0]["action"] == "corrected"
    assert "Lakhs" in s["scale"][0]["why"]
    assert s["q"]["2025-09-30"]["q"]["rev"] == pytest.approx(650 * CR)


def test_unconfirmed_scale_error_is_excluded_and_metrics_skip_it():
    bad = _q(6.6, cap_cr=13.6)  # rev, costs and profit 100x small, capital normal, no rounding: cannot confirm
    fin = _metro(bad)
    s = MX.series(fin)
    assert "2025-09-30" not in s["q"]
    assert [e["action"] for e in s["scale"]] == ["excluded"]
    M = MX.compute(fin, 1000.0)
    assert MX.val(M, "rev_yoy_pct") is None  # Sep-2026 vs the excluded Sep-2025: no number rather than +11,000%
    assert any("left out of all metrics" in f for f in M["flags"])


def test_genuine_revenue_spike_is_not_touched():
    spike = _q(650 * 100, exp_cr=560, pat_cr=60000)  # a licence fee: revenue 100x, expenses normal
    s = MX.series(_metro(spike))
    assert s["scale"] == []
    assert s["q"]["2025-09-30"]["q"]["rev"] == pytest.approx(65000 * CR)


def test_non_power_of_ten_drop_is_not_touched():
    s = MX.series(_metro(_q(650 / 178, cap_cr=13.6 / 178)))  # 178x off: not a power of ten
    assert s["scale"] == []


def test_level_shift_without_confirmation_is_not_touched():
    # business sold: ~₹250 cr a quarter before, ~₹1.5 cr after; the quarter at the break is not a unit question
    revs = [270, 240, 215, 1.08, 1.4, 2.7, 0.4, 0.8, 1.5]
    qs = {e: _q(r, exp_cr=r * 1.1 + 0.5, pat_cr=0.1) for e, r in zip(ENDS, revs)}
    assert MX.series(_fin(qs))["scale"] == []


def test_scale_events_go_to_the_registry_and_close_when_gone():
    reg = {}
    ev = {"quarter": "2025-09-30", "factor": 100.0, "rev_cr": 6.51, "neighbour_rev_cr": 711.7, "url": "u", "filed": "f",
          "action": "excluded", "why": "below neighbouring quarters by 100x"}
    issues.log_scale(reg, {"METROBRAND.NS": [ev], "OTHER.NS": []}, "2026-11-20")
    (i, r), = reg.items()
    assert r["status"] == "open" and r["scope"] == "stock" and r["kind"] == "scale" and r["found_value"] is None
    issues.log_scale(reg, {"METROBRAND.NS": [{**ev, "action": "corrected"}]}, "2026-11-21")
    assert reg[i]["status"] == "corrected"
    issues.log_scale(reg, {"OTHER.NS": []}, "2026-11-22")  # METROBRAND not evaluated: left alone
    assert reg[i]["status"] == "corrected"
    issues.log_scale(reg, {"METROBRAND.NS": []}, "2026-11-23")
    assert reg[i]["status"] == "fixed"


def test_scale_issues_are_not_patched_by_corrections(monkeypatch, tmp_path):
    reg = {}
    ev = {"quarter": "2025-09-30", "factor": 100.0, "rev_cr": 6.51, "neighbour_rev_cr": 711.7, "url": "u", "filed": "f",
          "action": "excluded", "why": "x"}
    issues.log_scale(reg, {"METROBRAND.NS": [ev]}, "2026-11-20")
    f = tmp_path / "data_issues.json"
    f.write_text(__import__("json").dumps({"issues": reg}))
    monkeypatch.setattr(corrections, "REG", f)
    _, applied, blocking = corrections.apply({})
    assert applied == {} and blocking == {}


# ---------------------------------------------------------------- 1b. parser: declared rounding, Reg-33 year to date
REG33 = """<xbrli:context id="OneD"><xbrli:entity></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-03-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="FourD"><xbrli:entity></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-03-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="OneI"><xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period></xbrli:context>
<in-bse-fin:LevelOfRoundingUsedInFinancialStatements contextRef="OneD">Crores</in-bse-fin:LevelOfRoundingUsedInFinancialStatements>
<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2023-01-01</in-bse-fin:DateOfStartOfReportingPeriod>
<in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-7">5441300000.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:DateOfStartOfReportingPeriod contextRef="FourD">2022-04-01</in-bse-fin:DateOfStartOfReportingPeriod>
<in-bse-fin:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-7">21270960000.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:Equity contextRef="OneI" unitRef="INR" decimals="-7">12000000000</in-bse-fin:Equity>"""


def test_reg33_year_to_date_column_is_read_despite_quarter_dates():
    p = filings.parse_xbrl(REG33)
    assert p["q"]["rev"] == 5441300000.0
    assert p["ytd"]["rev"] == 21270960000.0  # FY23 full year: before the fix this was dropped
    assert p["ytd_start"] == "2022-04-01" and p["q_start"] == "2023-01-01"
    assert p["rounding"] == "Crores" and p["ytd_chk"] == filings.YTD_CHK


def test_old_march_filing_is_reread_once():
    old = {"q": {"rev": 1.0}, "ytd": {}, "url": "x"}
    assert filings.needs_ytd_reread("2023-03-31", old)
    assert not filings.needs_ytd_reread("2023-12-31", old)
    assert not filings.needs_ytd_reread("2023-03-31", {**old, "ytd_chk": filings.YTD_CHK})
    assert not filings.needs_ytd_reread("2023-03-31", {**old, "ytd": {"rev": 4.0}})


# ---------------------------------------------------------------- 2. correction units
@pytest.mark.parametrize("unit,factor", [
    ("₹ cr", 1), ("crore", 1), ("Rs. in Crores", 1), ("lakh", 0.01), ("₹ lakh", 0.01), ("Rs. in lakhs", 0.01),
    ("INR lakhs", 0.01), ("mn", 0.1), ("₹ mn", 0.1), ("INR million", 0.1), ("bn", 100), ("₹ '000", 1e-4),
    ("INR", 1e-7), ("Rs.", 1e-7), ("rupees", 1e-7), ("₹", 1e-7), ("Rs", 1e-7)])
def test_to_cr_units(unit, factor):
    assert corrections.to_cr(100, unit) == pytest.approx(100 * factor)


@pytest.mark.parametrize("unit", ["", None, "  ", "%", "tonnes", "lakh crore"])
def test_to_cr_unreadable_units_return_none(unit):
    assert corrections.to_cr(100, unit) is None  # blank is not silently crore: the issue blocks instead of patching


# ---------------------------------------------------------------- 3. ROE on negative or tiny equity
@pytest.mark.parametrize("pat,eq,eq0", [
    (265.79, 749.8, -717.8),    # DIACABS: equity was negative a year ago (1,662%)
    (2131.0, 968.7, -1441.0),   # GAYAPROJ: −902% on a profit
    (-0.05, 1.03, -2.16),       # BLAL: +8% on a loss
    (300.0, 50.0, 60.0),        # tiny equity against profit (545%)
])
def test_roe_not_meaningful(pat, eq, eq0):
    assert MX.roe_nm(pat * CR, eq * CR, eq0 * CR)


def test_roe_meaningful_for_normal_and_high_returns():
    assert MX.roe_nm(4134 * CR, 5600 * CR, 4900 * CR) is None  # Nestle-like 78%
    assert MX.roe_nm(-138 * CR, 650 * CR, 700 * CR) is None    # a loss on positive equity is a real negative return


def test_roe_nm_in_compute():
    qs = {e: _q(100, pat_cr=60, equity_cr=(-700 if e == "2025-09-30" else 750) if e[5:7] in ("03", "09") else None) for e in ENDS}
    M = MX.compute(_fin(qs), 100.0)
    assert M["roe_pct"]["nm"] and MX.val(M, "roe_pct") is None


# ---------------------------------------------------------------- 4. break-even quarter is not a loss
def test_minus_zero_quarter_not_counted_as_loss():
    qs = {e: _q(50) for e in ENDS}
    qs["2026-03-31"]["q"]["pat_owners"] = -92000.0  # NATHBIOGEN: −₹0.9 lakh, shown as −0.0 cr
    qs["2026-06-30"]["q"]["pat_owners"] = -2 * CR
    M = MX.compute(_fin(qs), 100.0)
    assert M["loss_quarters_4"]["v"] == 1.0
    assert "-0.0" not in M["loss_quarters_4"]["in"]["profits_cr"]


# ---------------------------------------------------------------- 5. implausible share count
def test_implausible_share_count_makes_market_cap_not_meaningful():
    p = _q(0.0001, exp_cr=0.0025, pat_cr=-0.0025, cap_cr=0.000001, fv=10, eps=-25.03)  # JKSHAH: ₹10,000 capital, 1,000 shares
    p["shares"] = 1000.0
    M = MX.compute(_fin({"2026-06-30": p}), 197.6)
    assert M["mcap_cr"]["nm"] and MX.val(M, "mcap_cr") is None
    assert "pe" not in M and any("implausible" in f for f in M["flags"])


def test_share_count_falls_back_to_capital_over_face_value():
    p = _q(500, cap_cr=55.63, fv=10)
    p["shares"] = 50000.0  # profit ÷ EPS gone wrong
    sh, note, ok = MX.share_count({"q": {"2026-09-30": p}}, "2026-09-30")
    assert ok and sh == pytest.approx(55.63 * CR / 10) and "paid-up capital" in note


# ---------------------------------------------------------------- 6. multi-year growth says how many years it covers
def _fy_series(with_fy23: bool) -> dict:
    ends = ["2022-12-31", "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30",
            "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
    qs = {e: _q(100 + 5 * i, equity_cr=500 if e[5:7] in ("03", "09") else None) for i, e in enumerate(ends)}
    if with_fy23:
        qs["2023-03-31"]["ytd"] = dict(qs["2023-03-31"]["q"], rev=380 * CR, exp=323 * CR, pat=45 * CR, pat_owners=45 * CR,
                                       dep=20 * CR, fin=8 * CR)
    return _fin(qs)


def test_revenue_growth_is_two_year_and_says_so_without_fy23():
    M = MX.compute(_fy_series(False), 100.0)
    m = M["rev_cagr_3y_pct"]
    assert m["in"]["years"] == 2 and "(2-year growth)" in m["f"] and "FY24" in m["f"]


def test_revenue_growth_is_three_year_when_fy23_is_filed():
    M = MX.compute(_fy_series(True), 100.0)
    m = M["rev_cagr_3y_pct"]
    assert m["in"]["years"] == 3 and "FY23" in m["f"]
    assert M["pat_cagr_3y_pct"]["in"]["years"] == 3
    assert M["roce_3y_avg_pct"]["in"]["years"] == 3 and "3 years" in M["roce_3y_avg_pct"]["f"]


def test_roce_average_names_its_years():
    fin = _fy_series(False)
    fin["quarters"] = {qe: v for qe, v in fin["quarters"].items() if qe >= "2024-06-30"}  # FY25 and FY26 only
    m = MX.compute(fin, 100.0)["roce_3y_avg_pct"]
    assert m["in"]["years"] == 2 and "FY25–FY26" in m["f"] and "2 years" in m["f"]


def test_funnel_labels_use_the_years_covered():
    from narrativ import funnel as FN
    Mx = {"rev_cagr_3y_pct": MX._m(12.0, "f", {"years": 2}, "s"), "rev_ttm_growth_pct": MX._m(15.0, "f", {}, "s"),
          "roce_3y_avg_pct": MX._m(18.0, "f", {"years": 2}, "s"), "quarters_available": 12}
    v = {i["id"]: i.get("v") for i in FN.quality(Mx, False, None)["items"]}
    assert v["Q1"].startswith("2y avg") and v["Q3"].startswith("2y 12.0%")
