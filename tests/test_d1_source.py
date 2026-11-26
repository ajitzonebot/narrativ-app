from narrativ import funnel as FN


def _d1(lv):
    return next(i for i in lv["items"] if i["id"] == "D1")


def test_d1_uses_nse_shareholding_when_loaded():
    nse = {"shp": {"inst": 7.8, "mf": 3.0, "fii": 2.0, "inst_1q": 0.2, "inst_4q": None, "mf_n": 4, "mf_n_1q": 1, "asof": "Sep 2026"}}
    d1 = _d1(FN.discovery(12.0, 3, None, [], nse))  # Yahoo says 12%, the filing 7.8%
    assert d1["m"] == 2 and d1["v"].startswith("7.8") and d1["note"].startswith("NSE")


def test_d1_falls_back_to_yahoo_labelled():
    d1 = _d1(FN.discovery(12.0, 3, None, [], None))
    assert d1["m"] == 1 and d1["note"].startswith("Yahoo")


def test_nse_holding_without_any_yahoo_record_does_not_crash():
    # run of 26 Nov 2026: Yahoo had no record (holding and analysts None) but NSE's filing had the holding
    nse = {"shp": {"inst": 4.0, "mf": 1.0, "fii": 1.0, "inst_1q": 0.1, "inst_4q": None, "mf_n": 2, "mf_n_1q": 0, "asof": "Sep 2026"}}
    lv = FN.discovery(None, None, None, [], nse)
    assert _d1(lv)["m"] == 2 and "analysts not known" in (lv.get("why") or "")
