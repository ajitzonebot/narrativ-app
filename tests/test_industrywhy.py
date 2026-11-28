from datetime import date

from narrativ import industrywhy as IW

TODAY = date(2026, 11, 28)
RBI = "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=1"
SRC = {RBI: "The Monetary Policy Committee decided to reduce the policy repo rate by 25 basis points to 5.25 per cent."}


def reason(**k):
    r = {"date": "2026-09-01", "type": "rates", "text": "RBI cut the repo rate by 25 basis points.",
         "mechanism": "cheaper loans -> more home buying -> higher sales", "url": RBI, "source": "RBI",
         "quote": "reduce the policy repo rate by 25 basis points", "lasting": "structural"}
    return {**r, **k}


def chk(r, ok=(), titles=None, start="2026-09-05", text=SRC.get):
    return IW.check_reason(r, set(ok), titles or {}, TODAY, start, text)


def test_primary_source_kept_with_timing():
    k, why = chk(reason())
    assert why is None and k["checked"] and k["timing"] == "before" and k["lasting"] == "structural"
    k, _ = chk(reason(date="2026-10-20"))
    assert k["timing"] == "after"


def test_drops():
    assert chk(reason(type="hype"))[1].startswith("type must be")
    assert chk(reason(mechanism=""))[1].startswith("no mechanism")
    assert chk(reason(date="2027-01-01"))[1].startswith("date")
    assert chk(reason(url="https://example.com/x"))[1].startswith("url not in")
    assert chk(reason(quote="reduce the repo rate by 50 basis points"))[1] == "quote not in the source"
    assert chk(reason(quote=""))[1] == "no quote from the source"


def test_price_move_and_broker_tip_dropped():
    u = "https://www.business-standard.com/x"
    t = {u: "Angel One surges 7% on huge volume; stock nears record high"}
    assert chk(reason(url=u, type="demand"), ok=[u], titles=t, text=lambda _: None)[1] == "the price move is not a reason"
    u2 = "https://www.livemint.com/y"
    t2 = {u2: "Defence stocks set for fresh rally? Motilal Oswal names 3 shares to buy"}
    assert chk(reason(url=u2, type="orders"), ok=[u2], titles=t2, text=lambda _: None)[1] == "a broker's tip is not an event"


def test_unreadable_source_kept_but_not_counted():
    u = "https://economictimes.indiatimes.com/z"
    k, _ = chk(reason(url=u, type="policy"), ok=[u], text=lambda _: None)
    assert k and not k["checked"]
    v = IW.verdict({"members": 10, "above_200_day": 8, "rev_growth_over_10pct": 6, "rev_reported": 10}, [k])
    assert v["tests"]["cause"] is False and v["score"] == 2 and v["verdict"] == "Partly explained"


def test_verdict_labels_and_notes():
    k, _ = chk(reason())
    full = {"members": 10, "above_200_day": 7, "rev_growth_over_10pct": 3, "rev_reported": 10, "profit_growth_over_10pct": 6,
            "profit_reported": 10, "median_ret_3m": 12.0, "move_start": "2026-09-05"}
    v = IW.verdict(full, [k])
    assert v["verdict"] == "Earnings-led" and v["lasting"] == "structural" and v["notes"] == []
    thin = {"members": 10, "above_200_day": 3, "rev_growth_over_10pct": 1, "rev_reported": 10, "median_ret_3m": 9.0}
    v = IW.verdict(thin, [])
    assert v["verdict"] == "Flow or narrative" and v["score"] == 0
    assert any("prices ahead of earnings" in n for n in v["notes"]) and any(n.startswith("narrow") for n in v["notes"])


def test_judge_keeps_best_three_and_lists_drops():
    w = {"date": "2026-11-28", "reasons": [reason(), reason(type="x"), reason(date="2026-10-20")]}
    j = IW.judge("Banks", w, {"facts": {"move_start": "2026-09-05"}}, [], TODAY, SRC.get)
    assert [r["timing"] for r in j["reasons"]] == ["before", "after"] and j["dropped"] == 1
    assert j["dropped_why"][0]["why"].startswith("type must be")


def test_saved_copy_only_for_same_url(tmp_path, monkeypatch):
    monkeypatch.setattr(IW, "SAVED", tmp_path)
    (tmp_path / f"{IW._key(RBI)}.txt").write_text(IW.HEAD.format(RBI) + "text")
    assert IW.saved_text(RBI) == "text"
    (tmp_path / f"{IW._key('https://a/b')}.txt").write_text(IW.HEAD.format("https://other") + "x")
    assert IW.saved_text("https://a/b") is None


def test_numbers_measured_against_the_market():
    f = {"members": 10, "above_200_day": 7, "rev_growth_over_10pct": 9, "rev_reported": 10, "market_revenue_growth_pct": 77}
    assert IW.verdict(f, [])["tests"]["numbers"]
    f["rev_growth_over_10pct"] = 8  # 80% vs a 77% market: under the 5-point edge
    assert not IW.verdict(f, [])["tests"]["numbers"]
