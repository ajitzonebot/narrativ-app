"""New free sources (owner, 24 Nov 2026): NSE credit-rating disclosures, IBBI notices, World Bank commodity prices."""
from datetime import date

from narrativ import commodities as CM, ibbi as IB, ratings as RT

TODAY = date(2026, 11, 24)


def _r(sym, d, action, rating="Crisil A+", outlook="Stable", agency="CRISIL Ratings Limited", kind="Bank Facilities", term="Long Term"):
    return {"symbol": sym, "isin": "INE0", "creditAgencyName": agency, "ratingAssigned": kind, "typeOfRating": term, "creditRating": rating,
            "outlook": outlook, "dateOfCurrentCredit": d, "amount": "10", "currentAction": action, "detailsOfRatingLink": f"https://r/{d}"}


def test_rating_summary_and_a5():
    st = {"rows": {str(i): r for i, r in enumerate([
        _r("ABC", "20-Nov-2026", "Re-affirm"), _r("ABC", "10-Mar-2026", "Downgrade", rating="Crisil A"),
        _r("ABC", "05-Nov-2026", "Upgrade", agency="ICRA Limited", rating="[ICRA]AA-"),
        _r("XYZ", "01-Oct-2026", "Re-affirm", outlook="Negative"), _r("OLD", "01-Jan-2025", "Downgrade")])}}
    s = RT.per_stock(st, TODAY)
    assert set(s) == {"ABC.NS", "XYZ.NS"}  # older than 12 months: not counted
    abc = s["ABC.NS"]
    assert abc["downgrades"] == 1 and abc["upgrades"] == 1 and abc["actions"][0]["action"] == "Re-affirm"
    assert len(abc["actions"]) == 2  # latest per agency + instrument kind
    assert RT.a5(abc)[0] == 1 and "downgraded to Crisil A" in RT.a5(abc)[1]
    assert RT.a5(s["XYZ.NS"])[0] == 2 and s["XYZ.NS"]["negative"] == 1
    assert RT.a5(None) is None


def test_ibbi_matching():
    assert IB.norm("Kolkata Metro Networks Limited") == IB.norm("KOLKATA METRO NETWORKS LTD.")
    st = {"rows": {
        "a": {"date": "2026-11-22", "type": "Public Announcement of Corporate Insolvency Resolution Process", "debtor": "Acme Infra Projects Limited",
              "applicant": "Big Bank Limited", "pdf": "/uploads/a.pdf"},
        "b": {"date": "2026-11-21", "type": "Public Announcement of Voluntary Liquidation Process", "debtor": "Acme Infra Projects Ltd",
              "applicant": "Acme Infra Projects Ltd", "pdf": None},
        "c": {"date": "2026-10-01", "type": "Public Announcement of Corporate Insolvency Resolution Process", "debtor": "Tiny Traders Pvt Ltd",
              "applicant": "Cable Makers Limited", "pdf": None}}}
    m = IB.match(st, {"ACME.NS": "Acme Infra Projects Limited", "CABLE.NS": "Cable Makers Ltd", "BIG.NS": "Big Bank Limited"}, TODAY)
    assert [x["type"][:40] for x in m["ACME.NS"]["as_debtor"]][0].startswith("Public Announcement of Corporate")
    assert m["ACME.NS"]["as_applicant"] == []  # its own voluntary liquidation is not a claim against someone
    assert m["CABLE.NS"]["as_applicant"][0]["debtor"] == "Tiny Traders Pvt Ltd" and m["BIG.NS"]["as_applicant"]
    assert IB.a4(m["ACME.NS"])[0] == 1 and IB.a4(m["CABLE.NS"]) is None


def test_commodity_signal():
    pts = [(f"2026M{m:02d}", p) for m, p in zip(range(1, 11), [100, 100, 100, 100, 100, 100, 100, 100, 110, 120])]
    S = {"crude oil, brent": {"name": "Crude oil, Brent", "unit": "$/bbl", "pts": pts},
         "rubber, tsr20": {"name": "Rubber, TSR20", "unit": "$/kg", "pts": [(m, 1.0) for m, _ in pts]}}
    out = CM.build(S)
    tyre = {x["series"]: x for x in out["industries"]["Tyres & Rubber Products"]}
    assert tyre["Crude oil, Brent"]["chg3m"] == 20.0 and tyre["Crude oil, Brent"]["effect"] == "headwind"
    assert tyre["Rubber, TSR20"]["effect"] == "neutral"
    assert out["industries"]["Oil Exploration & Production"][0]["effect"] == "tailwind"
    assert "copper" in out["missing_series"] and out["month"] == "2026M10"


def test_nsdl_parsers():
    from narrativ import nsdl as N
    latest = ("<p>Daily Trends in FPI Investments on 23-Nov-2026</p><td>Debt/Debt-VRR/Equity/Hybrid</td><td>23-Nov-2026</td><td>Equity</td><td>Stock Exchange</td>"
              "<td>24805.95</td><td>13614.23</td><td>11191.72</td><td>Primary market &amp; others</td><td>772.82</td><td>0.00</td><td>772.82</td>"
              "<td>Sub-total</td><td>25578.77</td><td>13614.23</td><td>11964.54</td><td>Debt-General Limit</td><td>Sub-total</td><td>28.91</td><td>507.08</td><td>(478.17)</td>")
    assert N.parse_latest(latest) == ("2026-11-23", 11964.54)
    yr = "<h3>Monthly FPI Net Investments (Calendar Year - 2025)</h3><tr><td>January</td><td>-35,962</td></tr><tr><td>March</td><td>(1,200)</td></tr>"
    assert N.parse_monthly(yr) == (2025, {"2025-01": -35962.0, "2025-03": -1200.0})
    s = N.summary({"monthly": {"2025-01": -10.0, "2025-02": 5.0, "2025-03": 20.0, "2026-11": 1.0}, "daily": {"2026-11-20": 3.0}}, date(2026, 11, 24))
    assert s["month"] == "2025-03" and s["percentile"] == 100 and s["month_to_date_cr"] == 1.0 and s["last_days_cr"] == 3.0


def test_news_parse_and_match():
    from narrativ import news as N
    xml = b"""<rss><channel><item><title>Polycab India bags &amp; wins order</title><link>https://x.example/a</link>
    <pubDate>Mon, 24 Nov 2026 10:00:00 +0530</pubDate><description>&lt;p&gt;Cables&lt;/p&gt;</description></item>
    <item><title>no link</title></item></channel></rss>"""
    items = N.parse(xml, "ET", "news")
    assert len(items) == 1 and items[0]["title"] == "Polycab India bags & wins order" and items[0]["time"].startswith("2026-11-24T10:00")
    rows = [{"s": "POLYCAB.NS", "n": "Polycab India Limited"}, {"s": "TATASTEEL.NS", "n": "Tata Steel Limited"},
            {"s": "TATAPOWER.NS", "n": "The Tata Power Company Limited"}, {"s": "RELIANCE.NS", "n": "Reliance Industries Limited"},
            {"s": "DALBHARAT.NS", "n": "Dalmia Bharat Limited"}, {"s": "DALMIASUG.NS", "n": "Dalmia Bharat Sugar and Industries Limited"}]
    f = N.matcher(rows)
    assert f("Polycab shares jump") == {"POLYCAB.NS"}
    assert f("Tata Steel to buy APL Apollo") == {"TATASTEEL.NS"}  # not Tata Power
    assert f("helps reduce reliance on imports") == set()  # one-word name only when capitalised
    assert f("Dalmia Bharat approves buyback") == {"DALBHARAT.NS"}  # shared phrase goes to the exact name
    assert N._JUNK.search("ITC Share Price Highlights: ITC Stock Price History")


def test_story_sections():
    from narrativ import story as S
    assert S.going({"pat_yoy_pct": {"v": 230.9}, "rev_yoy_pct": {"v": 17.5}})["text"] == "Profit up 231% and revenue up 18% on the same quarter last year."
    assert S.going({"pat_yoy_pct": {"v": -6.0}})["tone"] == "bad"
    assert S.one_line([1, 2, 1, 1, 2, 1, 5]) == "A strong business at a cheap price, and the market is starting to notice."
    assert S.one_line([4, 4, 3, 3, 5, 3, 5]).startswith("A weak business with a shaky balance sheet at a fair price")
    assert S.one_line([0] * 7) is None
    bad = S.check({"what": "Lends with an AUM of 5,000 crore", "money": "Interest."}, "description 100")
    assert any("jargon" in b for b in bad) and any("5000" in b for b in bad)
    assert S.check({"what": "Makes cables for homes.", "money": "Sells cables to builders.", "plans": ["Grow 20% a year"]}, "grow 20%") == []
