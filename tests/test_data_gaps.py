"""Offline tests: specific Not rated reasons, the Discovery score, the owners'-profit guard and the NSE holiday parser."""
import copy
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from narrativ import funnel as FN  # noqa: E402
from narrativ import holidays, issues  # noqa: E402
from narrativ import metrics as MX  # noqa: E402

CR = 1e7


# ---------------------------------------------------------------- 1. Not rated reasons
def _levels(grey=(), researched=False):
    L = {}
    for k in FN.LEVELS:
        items = [FN.it(f"{k}1", f"{k} item", 2, "x")]
        if k in grey:
            items = [FN.it("Q3", "Revenue growing", None), FN.it("Q1", "ROCE ≥ 10%", None),
                     FN.it("T8", "Guidance raised", None, note="needs research"), FN.pending("D7", "Delivery % trend")]
        L[k] = {"t": 0 if k in grey else 2, "items": items}
    L["out"]["researched"] = researched
    return L


def test_not_rated_not_enough_data_names_the_gaps():
    L = _levels(grey=("surv", "qual", "val", "out"))
    vd = FN.verdict(L)
    assert vd == "Not enough data"
    r = FN.not_rated_reason(L, vd, None, qpos=3, qlen=20)
    assert r.startswith("Not enough filed data: Stability, Quality, Valuation cannot be scored")
    assert "revenue growth" in r and "ROCE" in r
    assert "research" not in r and "Delivery" not in r  # research items and unconnected feeds are not data gaps
    assert "Outlook" not in r  # outlook is grey until research: expected, not a gap


def test_not_rated_not_researched_reports_queue_position_or_not_queued():
    L = _levels()
    vd = FN.verdict(L)
    assert FN.not_rated_reason(L, vd, None, qpos=4, qlen=25) == "Not researched yet: today's research queue position 4 of 25"
    assert FN.not_rated_reason(L, vd, {}, rank=812, n=2365) == "Not researched yet: not in today's research queue (readiness rank 812 of 2365)"
    assert FN.not_rated_reason(L, vd, None, requested=True) == "Not researched yet: requested, waiting for research"


def test_not_rated_researched_without_driver():
    L = _levels(researched=True)
    th = {"updated": "2026-11-02", "promises": [{"status": "met"}]}
    r = FN.not_rated_reason(L, FN.verdict(L), th)
    assert r == "Researched (2026-11-02): no verified forward driver found (guidance, order book or dated promise)"


def test_decision_label_stays_not_rated():
    L = _levels()
    for k in FN.LEVELS:
        L[k].update({"name": "x", "why": None})
    L["mom"]["items"] = [FN.it("P1", "Stage", 1, "Stage 2")]
    d = FN.decision(L, None, {}, None, None, 100.0, None, today=date(2026, 11, 20))
    assert d["d"] == "Not rated"


# ---------------------------------------------------------------- 2. Discovery score
def test_discovery_score_is_set_when_tiered():
    lv = FN.discovery(4.0, 1, None, [], None)
    assert lv["t"] == 1 and lv["s"] is not None and 0 <= lv["s"] <= 100
    crowded = FN.discovery(40.0, 20, None, [], None)
    assert crowded["t"] == 5 and crowded["s"] < lv["s"]
    assert FN.compact({k: (lv if k == "disc" else {"t": 0, "name": "n", "s": None, "why": None}) for k in FN.LEVELS})["disc"]["s"] == lv["s"]


def test_discovery_not_checked_has_no_score():
    lv = FN.discovery(None, None, None, [], None)
    assert lv["t"] == 0 and lv["s"] is None


# ---------------------------------------------------------------- 3. owners' profit guard
ENDS = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]


def _q(pat_cr, owners_cr=None, minority_cr=0.0, eps=None, cap_cr=55.6321, fv=10.0):
    owners_cr = pat_cr - minority_cr if owners_cr is None else owners_cr
    shares = cap_cr * CR / fv
    eps = (pat_cr - minority_cr) * CR / shares if eps is None else eps
    q = {"rev": 520 * CR, "exp": 470 * CR, "pat": pat_cr * CR, "pat_owners": owners_cr * CR, "pat_minority": minority_cr * CR,
         "oi": 1 * CR, "fin": 2 * CR, "dep": 5 * CR, "pbt": pat_cr * 1.3 * CR, "share_cap": cap_cr * CR, "fv": fv, "eps": eps}
    return {"q": q, "ytd": {}, "bs": {}, "shares": shares, "flags": [], "url": "u", "filed": "f", "kind": "general"}


def _fin(bad):
    qs = {e: _q(45 + i) for i, e in enumerate(ENDS)}
    qs["2026-09-30"] = bad
    return {"basis": "Consolidated", "quarters": {qe: {"Consolidated": p} for qe, p in qs.items()}}


def _fmgoetze():
    """Sep-2026 as filed: owners ₹0.53 cr, minority ₹0.07 cr, total ₹37.25 cr; profit ÷ EPS gave 822,840 shares."""
    bad = _q(37.2515, owners_cr=0.5332, minority_cr=0.0705, eps=6.48)
    bad["ytd"] = {"pat": 82.58 * CR, "pat_owners": 0.5332 * CR, "pat_minority": 0.0705 * CR, "eps": 14.29}
    bad["shares"] = 0.5332 * CR / 6.48
    bad["flags"] = ["share capital/face value gives 55,632,100 shares but profit/EPS gives 822,840; using profit/EPS"]
    return bad


def test_owners_profit_far_below_total_is_rebuilt_from_total():
    fin = _fin(_fmgoetze())
    raw = copy.deepcopy(fin)
    s = MX.series(fin)
    p = s["q"]["2026-09-30"]
    assert p["q"]["pat_owners"] == pytest.approx((37.2515 - 0.0705) * CR)
    assert p["ytd"]["pat_owners"] == pytest.approx((82.58 - 0.0705) * CR)
    assert p["shares"] == pytest.approx(55.6321 * CR / 10)  # paid-up capital ÷ face value restored
    assert not any("using profit/EPS" in f for f in p["flags"])
    assert fin == raw  # stored filings are not modified
    [e] = s["owners"]
    assert e["kind"] == "owners" and e["fix"] == "replaced" and e["parts"] == ["q", "ytd"]
    M = MX.compute(fin, 380.0)
    assert MX.val(M, "pat_ttm_cr") == pytest.approx(46 + 47 + 48 + 37.18, abs=0.1)
    assert MX.val(M, "pe") == pytest.approx(380 * 55632100 / CR / (46 + 47 + 48 + 37.18), abs=0.1)


def test_owners_off_by_exact_power_of_ten_is_rescaled():
    bad = _q(40.0, owners_cr=0.398, minority_cr=0.2)
    s = MX.series(_fin(bad))
    assert s["owners"][0]["fix"] == "rescaled" and s["owners"][0]["factor"] == 100
    assert s["q"]["2026-09-30"]["q"]["pat_owners"] == pytest.approx(39.8 * CR)


def test_owners_explained_by_minority_or_backed_by_eps_is_left_alone():
    real_split = _q(40.0, owners_cr=2.0, minority_cr=38.0)  # a subsidiary-heavy group: minority takes most of the profit
    assert MX.series(_fin(real_split))["owners"] == []
    big_minority = _q(40.0, owners_cr=2.0, minority_cr=12.0)  # gap not explained, but minority is not small: not this guard
    assert MX.series(_fin(big_minority))["owners"] == []
    eps_backed = _q(40.0, owners_cr=2.0, minority_cr=0.1, eps=2.0 * CR / (55.6321 * CR / 10))  # EPS agrees with owners
    assert MX.series(_fin(eps_backed))["owners"] == []
    modest = _q(40.0, owners_cr=30.0, minority_cr=0.0)  # 1.3x gap: not a tagging error of this kind
    assert MX.series(_fin(modest))["owners"] == []


def test_owners_event_logged_in_issues_registry_and_closed_when_gone():
    reg = {}
    ev = MX.scale_issues(_fin(_fmgoetze()))
    assert [e.get("kind") for e in ev] == ["owners"]
    issues.log_scale(reg, {"FMGOETZE.NS": ev}, date(2026, 11, 20))
    [(i, r)] = reg.items()
    assert r["kind"] == "owners" and r["status"] == "corrected" and r["symbol"] == "FMGOETZE.NS"
    assert "0.53" in r["app"] and "37.25" in r["found"]
    issues.log_scale(reg, {"FMGOETZE.NS": []}, date(2026, 11, 21))
    assert reg[i]["status"] == "fixed"


# ---------------------------------------------------------------- 5. NSE trading holidays
NSE_SAMPLE = {"CM": [{"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
                     {"tradingDate": "25-Dec-2026", "weekDay": "Friday", "description": "Christmas"},
                     {"tradingDate": "15-Jan-2026", "weekDay": "Thursday", "description": "Municipal Corporation Election"},
                     {"tradingDate": "not a date"}],
              "FO": [{"tradingDate": "19-Feb-2026"}]}


def test_holiday_parser_reads_equity_segment_as_iso_dates():
    assert holidays.parse(NSE_SAMPLE) == ["2026-01-15", "2026-01-26", "2026-12-25"]
    assert holidays.parse({}) == []


def test_holiday_merge_keeps_other_years_and_replaces_covered_years():
    assert holidays.merge(["2025-10-21", "2026-03-31"], ["2026-01-26"]) == ["2025-10-21", "2026-01-26"]


class _Sess:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, params=None, as_json=True, tries=3):
        return self.payload


def test_holiday_update_writes_format_and_keeps_file_when_unreachable(tmp_path):
    out = tmp_path / "holidays.json"
    rec = holidays.update(date(2026, 11, 20), _Sess(NSE_SAMPLE), out)
    assert json.loads(out.read_text()) == rec
    assert rec == {"source": holidays.URL, "updated": "2026-11-20", "trading_holidays": ["2026-01-15", "2026-01-26", "2026-12-25"]}
    assert holidays.update(date(2026, 11, 21), _Sess(None), out) is None
    assert json.loads(out.read_text())["updated"] == "2026-11-20"
