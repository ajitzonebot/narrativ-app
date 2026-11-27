"""Forward ledger stage 1: classification, figures, sizing against filed numbers as of the statement date, lineage."""
from datetime import date

from narrativ import ledger as LG

CR = 1e7


def fin(rev_by_fy: dict, margin=0.2, pat_share=0.1, filed_lag=45):
    """Quarters for fiscal years {2024: 400, ...} (crore, split evenly), EBITDA at `margin`, PAT at `pat_share` of revenue."""
    q = {}
    for fy, rev in rev_by_fy.items():
        for qe in (f"{fy - 1}-06-30", f"{fy - 1}-09-30", f"{fy - 1}-12-31", f"{fy}-03-31"):
            r = rev / 4 * CR
            d = date.fromisoformat(qe)
            filed = date.fromordinal(d.toordinal() + filed_lag)
            q[qe] = {"Consolidated": {"q": {"rev": r, "exp": r * (1 - margin), "fin": 0.0, "dep": 0.0, "pat": r * pat_share, "eps": 1.0},
                                      "end": qe, "filed": str(filed), "flags": []}}
    return {"basis": "Consolidated", "quarters": q}


B = LG.Bases({"ACME.NS": fin({2023: 400, 2024: 440, 2025: 484, 2026: 532.4})})  # 10% a year


def size(text, due=None, made="2026-06-01", kind=None, value=None, unit=None, target=None):
    return LG.size_item("ACME.NS", kind, text, value, unit, due, made, B, target)


def test_figures_and_periods():
    assert LG.rupees_cr("FY27 total income of INR1,400 crores to INR1,500 crores") == 1450
    assert LG.rupees_cr("capex of INR 625-700 crore") == 662.5
    assert LG.rupees_cr("an order of Rs 50 lakh") == 0.5
    assert LG.percent("revenue growth of 18% to 20%") == 19
    assert LG.fiscal_end("to be completed during FY 2026-27", None, None) == date(2027, 3, 31)
    assert LG.fiscal_end("by FY29/30", None, None) == date(2030, 3, 31)
    assert LG.fiscal_end("plant by December", "2026-12-31", None) == date(2027, 3, 31)


def test_classify():
    assert LG.classify("Full-year revenue about ₹800 crore and PAT around ₹125 crore", None, None) == ("financial", "revenue")
    assert LG.classify("Order book of ₹2,843 crore", None, None) == ("financial", "order_book")
    assert LG.classify("Bidding pipeline of ₹6,650 crore", None, None)[1] == "pipeline"
    assert LG.classify("Debt guided to a range by March 2027", "capex", "cr")[1] == "debt"
    assert LG.classify("EBITDA margin expected to hold around 25%", None, "%")[1] == "margin"
    assert LG.classify("Consolidated AUM growth guided at 20% to 25%", None, "%")[1] == "growth:aum"
    assert LG.classify("Pregabalin CEP approval expected by March", "product", None)[0] == "event"


def test_revenue_target_sized_against_last_filed_year_and_own_trend():
    r = size("FY27 revenue of ₹650 crore")  # vs FY26 532.4: +22%; trend 10% -> 15%+ and 5+ pts above trend
    assert r["measure"] == "revenue" and r["base"] == 532.4 and 21 < r["size_pct"] < 23 and r["trend_pct"] == 10.0 and r["est_material"] == 1
    r = size("FY27 revenue of ₹590 crore")  # +10.8%: below the 15% floor
    assert r["est_material"] == 0


def test_only_filings_filed_before_the_statement_count():
    r = size("FY27 revenue of ₹650 crore", made="2026-04-01")  # FY26's March quarter not filed yet (filed 15 May)
    assert r["base"] == 484.0


def test_fast_grower_guiding_below_its_trend_is_not_material():
    b = LG.Bases({"FAST.NS": fin({2023: 100, 2024: 140, 2025: 196, 2026: 274.4})})  # 40% a year
    r = LG.size_item("FAST.NS", None, "Revenue growth of 25% to 30% in FY27", None, "%", None, "2026-06-01", b)
    assert r["measure"] == "growth:revenue" and r["size_pct"] == 27.5 and r["trend_pct"] == 40.0 and r["est_material"] == 0


def test_division_figure_is_a_part_of_the_business():
    r = size("Forging revenue of ₹200 crore by year-end", due="2027-03-31")  # 38% of company revenue, not a company target
    assert r["measure"] == "part" and r["est_material"] == 1


def test_capex_orders_and_margins():
    assert size("Capex of about ₹60 crore by March 2027")["est_material"] == 1      # 11% of revenue
    assert size("Capex of about ₹20 crore by March 2027")["est_material"] == 0
    assert size("Order book of ₹600 crore")["est_material"] == 1                     # 1.1x revenue
    assert size("Order of ₹30 crore from a utility", kind="order")["est_material"] == 0   # 5.6%
    r = size("EBITDA margin of 23% to 24%", unit="%")
    assert r["measure"] == "margin" and r["base"] == 20.0 and r["size_pct"] == 3.5 and r["est_material"] == 1


def test_unknown_base_is_said_not_guessed():
    r = size("Management aims for 100 centres by end FY28", kind="capacity")
    assert r["size_pct"] is None and r["material"] is None and "base" in r["why"]


def test_parsed_size_is_never_material():
    r = size("FY27 revenue of ₹650 crore")
    assert r["src"] == "parsed" and r["material"] is None and r["est_material"] == 1


def test_verified_target_is_sized_from_its_own_figures():
    t = {"measure": "revenue", "of": "company", "low": 640, "high": 660, "unit": "cr", "fy": "FY27"}
    r = size("We expect the year to close well ahead", due=None, target=t)   # text has no figure: the target's are used
    assert r["src"] == "narrativ" and r["amount"] == 650 and r["period"] == "2027-03-31" and r["material"] == 1
    r = size("Forging revenue of 345 crores", target={"measure": "revenue", "of": "part: forging", "low": 345, "high": 345, "unit": "cr"})
    assert r["measure"] == "part"
    r = size("Capacity to 600 MW", target={"measure": "capacity", "low": 600, "high": 600, "unit": "MW", "now": 450})
    assert r["measure"] == "capacity" and r["size_pct"] == 33.3 and r["material"] == 1
    r = size("Adding 50 MW", target={"measure": "capacity", "low": 50, "high": 50, "unit": "MW", "now": 450, "adds": True})
    assert r["size_pct"] == 11.1 and r["material"] == 0


def test_target_check_against_the_quote():
    from narrativ import verify as V
    q = "For FY27 we expect total income of INR1,400 crores to INR1,500 crores."
    ok, why = V.target_check({"measure": "revenue", "of": "company", "low": 1400, "high": 1500, "unit": "cr", "fy": "FY27"}, q, None, q)
    assert ok and why is None
    bad, why = V.target_check({"measure": "revenue", "low": 1400, "high": 1600, "unit": "cr", "fy": "FY27"}, q, None, q)
    assert bad is None and "high" in why
    bad, why = V.target_check({"measure": "revenue", "low": 1400, "high": 1500, "unit": "cr", "fy": "FY28"}, q, None, q)
    assert bad is None and "fy" in why
    bad, why = V.target_check({"measure": "sales", "low": 1400, "unit": "cr"}, q, None, q)
    assert bad is None and "measure" in why
    bad, why = V.target_check({"measure": "capacity", "low": 600, "unit": "MW", "now": 450}, "Capacity to 600 MW by March 2027.", None,
                              "Capacity to 600 MW by March 2027.")
    assert bad is None and "now" in why


def test_link_restated_target_raised():
    rows = [{"id": "a", "sym": "ACME.NS", "made": "2026-05-20", "text": "FY27 EBITDA of ₹120 crore", "due": "2027-03-31"},
            {"id": "b", "sym": "ACME.NS", "made": "2026-08-10", "text": "FY27 EBITDA floor raised to ₹130 crore", "due": "2027-03-31"}]
    for r in rows:
        r.update(LG.size_item(r["sym"], None, r["text"], None, None, r["due"], r["made"], B))
    LG.link(rows)
    assert rows[1]["prev"] == "a" and rows[1]["change"] == "raised" and rows[0]["prev"] is None
