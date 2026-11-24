from narrativ import ipo

T = "2026-12-05"


def _i(board="Mainboard", gp=23.3, g=28, peak=30, q=139.7, r=25.4, t=71.3, obs=T + "T15:30+05:30", has_qib=True):
    return {"board": board, "gmp_pct": gp, "gmp_high": g, "gmp_peak": peak, "gmp_observed": obs, "has_qib": has_qib,
            "subscription": {"qib": q, "retail": r, "overall": t}}


def _ids(rules):
    return {x["id"]: x["ok"] for x in rules}


def test_apply_when_all_rules_pass():
    call, rules = ipo.evaluate(_i(), T, final=True)
    assert call == "APPLY" and all(_ids(rules).values()) and set(_ids(rules)) == {"G1", "G2", "S1", "S2", "S3"}


def test_wait_before_final_day_then_avoid_on_it():
    i = _i(q=0.4)
    assert ipo.evaluate(i, T, final=False)[0] == "WAIT"
    assert ipo.evaluate(i, T, final=True)[0] == "AVOID"


def test_unknown_subscription_waits():
    call, rules = ipo.evaluate(_i(q=None, r=None, t=None), T, final=False)
    assert call == "WAIT" and _ids(rules)["S1"] is None


def test_gmp_rules():
    assert _ids(ipo.evaluate(_i(gp=19.9), T, False)[1])["G1"] is False
    assert _ids(ipo.evaluate(_i(g=23, peak=30), T, False)[1])["G2"] is False  # 77% of peak
    assert _ids(ipo.evaluate(_i(obs="2026-12-04T15:30+05:30"), T, False)[1])["G1"] is False  # not seen today
    assert ipo.evaluate(_i(gp=2.0), T, final=False)[0] == "AVOID"  # collapsed: no need to wait


def test_sme_thresholds_and_no_qib_portion():
    rules = _ids(ipo.evaluate(_i(board="SME", t=15), T, True)[1])
    assert rules["S2"] is False and "S3" not in rules
    rules = _ids(ipo.evaluate(_i(board="SME", t=150, has_qib=False), T, True)[1])
    assert "S1" not in rules and rules["S2"] is True


def test_iw_list_and_im_gmp_parsers():
    page = ('<script>self.__next_f.push([1,"{\\"id\\":1,\\"slug\\":\\"abc-ipo-details\\",\\"name\\":\\"Abc\\",\\"type\\":\\"Mainboard\\",'
            '\\"issuePrice\\":120,\\"gmp\\":28,\\"listPrice\\":null}"])</script>')
    lst = ipo.iw_list(page)
    assert lst and lst[0]["slug"] == "abc-ipo-details" and lst[0]["gmp"] == 28
    t = "<table><tr><th>Company</th><th>Open</th><th>Band</th><th>GMP</th></tr><tr><td>Abc Ltd</td><td>3 Dec</td><td>₹114 – ₹120</td><td>₹30</td></tr></table>"
    assert ipo.im_gmp(t) == {"abc": 30.0}


def test_parse_nse_categories():
    x = [{"category": "Qualified Institutional Buyers(QIBs)", "noOfTime": "139.70"}, {"category": "Retail Individual Investors(RIIs)", "noOfTime": "25.4"},
         {"category": "Total", "noOfTime": "71.3"}]
    assert ipo.parse_nse(x) == {"qib": 139.7, "retail": 25.4, "overall": 71.3}
