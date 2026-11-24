from narrativ import funnel as FN
from narrativ import metrics as MX


def _q(qe, ratio, cet1=0.14, adv=None, gnpa=None):
    p = {"end": qe, "url": f"https://x/{qe}", "filed": qe, "q": {"gnpa_ratio": ratio, "cet1_ratio": cet1}, "kind": "bank"}
    if gnpa is not None:
        p["q"]["gnpa"] = gnpa
    if adv:
        p["bs"] = {"advances": adv, "equity": 1.0}
    return p


def _series(ratios, advs):
    qs = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    return {"basis": "Standalone", "q": {qe: _q(qe, r, adv=advs.get(qe)) for qe, r in zip(qs, ratios)}}


def test_gnpa_zero_is_not_reported():
    assert MX._gnpa_pct({"q": {"gnpa": 0.0, "gnpa_ratio": 0.0}, "bs": {"advances": 100.0}}) is None
    assert MX._gnpa_pct({"q": {"gnpa_ratio": 0.0144}}) == 1.44
    assert MX._gnpa_pct({"q": {"gnpa": 3.0}, "bs": {"advances": 100.0}}) == 3.0


def test_lender_metrics_trend_growth_cet1():
    s = _series([0.030, 0.028, 0.026, 0.024, 0.022, 0.020], {"2026-09-30": 112.0, "2025-09-30": 100.0})
    M = {}
    MX._lender_metrics(M, s, "2026-09-30", s["q"]["2026-09-30"], "Standalone")
    assert M["gnpa_pct_advances"]["v"] == 3.0
    assert M["gnpa_rising_q"]["v"] == 5
    assert M["cet1_pct"]["v"] == 14.0
    assert M["advances_yoy_pct"]["v"] == 12.0


def test_lender_checks_scored():
    Mx = {"gnpa_pct_advances": {"v": 3.0}, "cet1_pct": {"v": 6.0}, "advances_yoy_pct": {"v": -2.0}, "gnpa_rising_q": {"v": 4}}
    surv = {i["id"]: i for i in FN.survivability(Mx, True)["items"]}
    assert surv["C1"]["m"] == 2 and surv["C2"]["m"] == 1
    qual = {i["id"]: i for i in FN.quality(Mx, True, None)["items"]}
    assert qual["L2"]["m"] == 0 and qual["L3"]["m"] == 0


def test_lender_checks_pending_without_data():
    surv = {i["id"]: i for i in FN.survivability({}, True)["items"]}
    assert surv["C2"]["note"] == FN.PENDING
    qual = {i["id"]: i for i in FN.quality({}, True, None)["items"]}
    assert qual["L2"]["note"] == FN.PENDING and qual["L3"]["note"] == FN.PENDING
