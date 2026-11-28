"""v2 funnel (PLAN.md sections 1-5). Seven levels, each a rubric of items computed from filed numbers, prices,
exchange records or verified research. Rules only: no model writes any value, tier or sentence here.

Item marks: 2 good · 1 watch · 0 bad · None not checked. Items whose data source is not connected yet are listed
with note PENDING and kept out of coverage, so a missing feed never removes a stock.
Tier index: 1 dark green · 2 light green · 3 yellow · 4 light red · 5 red · 0 grey (not enough data).
"""
import math
import re
from datetime import date

import numpy as np
import pandas as pd

from . import metrics as MX

LEVELS = ["surv", "qual", "val", "mgmt", "mom", "disc", "out"]
LEVEL_NAMES = {"surv": "Company stability", "qual": "Business quality", "val": "Business valuation",
               "mgmt": "Management evaluation", "mom": "Momentum analysis", "disc": "Discovery stage", "out": "Future outlook"}
TIERS = {
    "surv": ["Rock solid", "Strong", "Steady", "Fragile", "Distressed"],
    "qual": ["Excellent", "Good", "Average", "Below average", "Poor"],
    "val": ["Deep value", "Undervalued", "Fairly valued", "Rich", "Overvalued"],
    "mgmt": ["Exemplary", "Trustworthy", "Adequate", "Questionable", "Red flag"],
    "mom": ["Surging", "Strong", "Building", "Neutral", "Weak"],
    "disc": ["Undiscovered", "Early discovery", "Being discovered", "Well discovered", "Crowded"],
    "out": ["Very strong", "Strong", "Moderate", "Limited", "No trigger"],
}
PENDING = "source not connected yet"
LENDERS = ("bank", "nbfc", "insurance")
# RULES.md R1 / R2 "Lenders exempt": by BSE basic industry (the 4-level scheme NSE and BSE share)
_LENDER_BASIC = {"Private Sector Bank": "bank", "Public Sector Bank": "bank", "Other Bank": "bank",
                 "Non Banking Financial Company (NBFC)": "nbfc", "Housing Finance Company": "hfc", "Microfinance Institutions": "nbfc",
                 "Financial Institution": "nbfc", "Investment Company": "investment company", "Holding Company": "investment company",
                 "Other Financial Services": "nbfc", "Life Insurance": "insurer", "General Insurance": "insurer"}
# brokers, AMCs, exchanges, depositories, distributors, ratings, fintech: fee businesses with operating cash flow -> R1 / R2 apply
_MARKET_IND = {"Capital Markets", "Financial Technology (Fintech)"}


def lender_type(kind: str | None, source: str | None, sector: str | None, industry: str | None, basic: str | None) -> str:
    """Why R1 / R2 do not apply, or "" when they do. Banks, NBFCs, HFCs (and NBFC-registered investment companies) are
    lenders; insurers are exempt as "insurer" (cash conversion and other income do not measure an insurer). Until Nov 2026
    every Financial Services stock without NSE filings was exempt, brokers and AMCs included."""
    kind, source, sector, industry, basic = (x if isinstance(x, str) and x else None for x in (kind, source, sector, industry, basic))
    if basic == "Insurance Distributors" or industry in _MARKET_IND:
        return ""
    if kind == "bank":
        return "bank"
    if kind == "insurance":
        return "insurer"
    if kind == "nbfc":
        return "hfc" if basic == "Housing Finance Company" else "nbfc"
    if sector != "Financial Services" or source == "NSE filing":
        return ""
    if basic in _LENDER_BASIC:
        return _LENDER_BASIC[basic]
    return {"Banks": "bank", "Insurance": "insurer", "Finance": "nbfc"}.get(industry or "", "financial (unclassified)")

# Business types follow the exchange classification the universe carries since Nov 2026 (NSE / BSE industry, basic industry).
# The Yahoo names before it ("Steel", "Real Estate - Development") matched almost nothing after the switch (audit 26 Nov 2026).
CYCLICAL_IND = {"Ferrous Metals", "Non - Ferrous Metals", "Diversified Metals", "Minerals & Mining", "Consumable Fuels",
                "Cement & Cement Products", "Other Construction Materials", "Paper, Forest & Jute Products",
                "Chemicals & Petrochemicals", "Fertilizers & Agrochemicals"}
CYCLICAL_BASIC = {"Oil Exploration & Production", "Refineries & Marketing", "Other Textile Products", "Shipping",
                  "Iron & Steel Products", "Aluminium, Copper & Zinc Products", "Passenger Cars & Utility Vehicles", "2/3 Wheelers",
                  "Commercial Vehicles"}
ORDER_BOOK_IND = {"Construction", "Aerospace & Defense", "Electrical Equipment", "Industrial Manufacturing", "Transport Infrastructure"}
ORDER_BOOK_BASIC = {"Construction Vehicles", "Tractors", "Compressors, Pumps & Diesel Engines"}
REALTY_IND = {"Realty"}
CYCLICAL = {"Steel", "Aluminum", "Copper", "Other Industrial Metals & Mining", "Other Precious Metals & Mining", "Coking Coal",
            "Thermal Coal", "Oil & Gas E&P", "Oil & Gas Refining & Marketing", "Oil & Gas Integrated", "Building Materials",
            "Paper & Paper Products", "Chemicals", "Agricultural Inputs", "Textile Manufacturing", "Lumber & Wood Production",
            "Marine Shipping", "Auto Manufacturers", "Specialty Chemicals"}
ORDER_BOOK = {"Engineering & Construction", "Aerospace & Defense", "Specialty Industrial Machinery", "Electrical Equipment & Parts",
              "Railroads", "Farm & Heavy Construction Machinery", "Infrastructure Operations", "Industrial Distribution",
              "Utilities - Renewable", "Pollution & Treatment Controls"}
REALTY = {"Real Estate - Development", "Real Estate - Diversified", "Real Estate Services"}
METRIC_OF = {"Bank": "pb", "NBFC": "pb", "Insurer": "pb", "Holding company": "pb", "Real estate developer": "pb",
             "Cyclical": "ev_midcycle_ebitda", "Order-book": "ev_ebitda", "Asset-heavy steady": "ev_ebitda",
             "Loss-making / early": "ev_sales", "Compounder": "pe", "Standard": "pe"}
METRIC_LABEL = {"pb": "P/B", "ev_midcycle_ebitda": "EV / mid-cycle EBITDA", "ev_ebitda": "EV / EBITDA", "ev_sales": "EV / sales", "pe": "P/E"}
HIST_KEY = {"pb": "pb", "ev_midcycle_ebitda": "ev_ebitda", "ev_ebitda": "ev_ebitda", "ev_sales": "ev_sales", "pe": "pe"}
INST_WORDS = ("MUTUAL FUND", " MF", "FUND", "INSURANCE", "ASSET MANAGEMENT", "AMC", "PENSION", "LIFE INSURANCE", "PROVIDENT")


FACT = {"A1": "equity", "B1": "interest cover", "B2": "net debt/EBITDA", "B3": "operating cash flow", "B4": "current ratio",
        "C1": "promoter holding", "C2": "ownership", "C6": "promises kept", "C8": "capital allocation",
        "C3": "loss quarters", "Q1": "ROCE", "Q2": "EBITDA margin", "Q3": "revenue growth", "Q4": "profit growth", "Q5": "margin trend",
        "Q6": "industry", "Q7": "cash backing", "L1": "returns", "G5": "promoter stake", "V1": "vs own history", "V2": "vs peers",
        "V3": "growth priced in", "P1": "stage", "P2": "relative strength", "P4": "52-week high", "F1": "OBV", "F2": "up/down volume",
        "E1": "revenue growth", "E2": "results reaction", "E3": "EPS estimates", "T1": "order book", "T4": "capital work in progress",
        "T7": "acceleration", "T8": "guidance", "T9": "debt cut"}


def fact(i):
    """Short phrase for statements: '<metric> <value>'."""
    return f"{FACT.get(i['id'], i['n'].lower())} {i['v']}" if i.get("v") else FACT.get(i["id"], i["n"].lower())


def it(id_, name, mark, value=None, key=None, note=None, pts=None):
    d = {"id": id_, "n": name, "m": mark}
    if value is not None:
        d["v"] = value
    if key:
        d["k"] = key
    if note:
        d["note"] = note
    if pts is not None:
        d["pts"] = pts
    return d


def pending(id_, name):
    return it(id_, name, None, note=PENDING)


def v(Mx, k):
    return MX.val(Mx, k)


def inp(Mx, k, name):
    m = Mx.get(k)
    return ((m or {}).get("in") or {}).get(name) if isinstance(m, dict) else None


def pc(x, nd=1):
    return None if x is None else f"{x:.{nd}f}%"


def cr(x):
    return None if x is None else f"₹{x:,.0f} cr"


def _level(key, items, tier, score=None, why=None, out=False, rm=None, **extra):
    live = [i for i in items if i.get("note") != PENDING]
    checked = [i for i in items if i["m"] is not None]
    d = {"t": tier, "name": (TIERS[key][tier - 1] if tier else extra.pop("grey", "Not enough data")),
         "s": None if score is None else round(score), "cov": [len(checked), len(items)], "live": len(live),
         "why": why, "items": items}
    if out:
        d["out"] = True
        d["rm"] = rm
    d.update({k: x for k, x in extra.items() if x is not None})
    return d


def _rubric_score(items):
    ch = [i["m"] for i in items if i["m"] is not None]
    return (sum(ch) / (2 * len(ch)) * 100) if ch else None


def _first(items, mark):
    for i in items:
        if i["m"] == mark and i.get("v"):
            return i
    return None


# ------------------------------------------------------------------ L1 Company stability
def _ann_item(id_, name, ann):
    """Subject-line check from narrativ.announcements -> item with filing link, or pending when not covered."""
    r = (ann or {}).get(id_)
    if not r:
        return pending(id_, name)
    d = it(id_, name, r[0], r[1], note=r[2])
    if r[3]:
        d["u"] = r[3]
    return d


def survivability(Mx, lender, ann=None, nse=None):
    items, hard = [], []
    eq = v(Mx, "equity_cr")
    items.append(it("A1", "Shareholders' equity positive", None if eq is None else (2 if eq > 0 else 0), cr(eq), "equity_cr"))
    if eq is not None and eq <= 0:
        hard.append("negative shareholders' equity")
    items.append(_ann_item("A2", "No loan or debt default disclosed (24 months)", ann))
    au = Mx.get("audit") or {}
    A3N = "Clean audit opinion (latest annual results)"
    if au.get("opinion") and not re.search(r"not applicable", au["opinion"], re.I):
        clean = "unmodified" in au["opinion"].lower()
        a3 = it("A3", A3N, 2 if clean else 0, f"{au['opinion']} · year to {au['year_end']}" + (f" · {au['auditors'][0]}" if au.get("auditors") else ""),
                note="auditor's opinion declaration filed with annual results" + ("" if clean else ": modified opinion, read the statement on impact of audit qualifications"))
        if au.get("url"):
            a3["u"] = au["url"]
        items.append(a3)
    elif au.get("opinion"):
        items.append(it("A3", A3N, None, f"declaration filed as '{au['opinion']}' · year to {au['year_end']}", note="no opinion stated in the filing"))
    elif Mx.get("source") == "NSE filing":
        items.append(it("A3", A3N, None, note="annual results declaration not read yet"))
    else:
        items.append(pending("A3", A3N))
    items.append(_ann_item("A4", "No insolvency proceedings (24 months)", ann))
    items.append(_ann_item("A5", "No rating downgrade or withdrawal (12 months)", ann))
    if nse and nse.get("surv_ok"):
        from .nsedaily import a6
        m6, v6 = a6(nse.get("surv"))
        items.append(it("A6", "Not suspended, not in NSE GSM stage II+", m6, v6, note="NSE surveillance lists"))
    else:
        items.append(pending("A6", "Not suspended, not in NSE GSM stage II+"))
    bad_b, bad_c = [], []
    if not lender:
        ic, de = v(Mx, "interest_cover"), v(Mx, "de")
        if ic is None and de is not None and de < 0.05:
            items.append(it("B1", "Interest cover ≥ 1.5", 2, "no material debt", "de"))
        else:
            m = None if ic is None else 0 if ic < 1.5 else 1 if ic < 3 else 2
            items.append(it("B1", "Interest cover ≥ 1.5", m, None if ic is None else f"{ic:.1f}x", "interest_cover"))
            if m == 0:
                bad_b.append(f"interest cover {ic:.1f}x")
        nde = v(Mx, "net_debt_ebitda")
        em = v(Mx, "ebitda_margin_pct")
        if nde is None and em is not None and em <= 0 and (de or 0) > 0.1:
            items.append(it("B2", "Net debt ≤ 5× EBITDA", 0, "EBITDA negative with debt", "ebitda_margin_pct"))
            bad_b.append("negative EBITDA with debt")
        else:
            m = None if nde is None else 0 if nde > 5 else 1 if nde > 3 else 2
            items.append(it("B2", "Net debt ≤ 5× EBITDA", m, None if nde is None else ("net cash" if nde < 0 else f"{nde:.1f}x"), "net_debt_ebitda"))
            if m == 0:
                bad_b.append(f"net debt {nde:.1f}x EBITDA")
        cn = v(Mx, "cfo_negative_years")
        loss = inp(Mx, "cfo_negative_years", "profit_latest_fy_cr")
        if cn is None:
            items.append(it("B3", "Cash from operations positive", None, key="cfo_negative_years"))
        else:
            lossy = loss is not None and loss < 0
            m = 0 if cn >= 2 and lossy else 1 if cn >= 2 or lossy or cn == 1 else 2
            items.append(it("B3", "Cash from operations positive", m, f"{int(cn)} negative year(s) of last 3" + (", latest year loss" if lossy else ""), "cfo_negative_years"))
            if m == 0:
                bad_b.append("negative operating cash flow and a loss")
        crt = v(Mx, "current_ratio")
        if crt is None:
            items.append(it("B4", "Current ratio ≥ 0.8 or short-term debt covered by cash", None, key="current_ratio"))
        else:
            st, cash = inp(Mx, "current_ratio", "short_term_borrowings_cr") or 0, inp(Mx, "current_ratio", "cash_and_bank_cr") or 0
            m = 0 if crt < 0.8 and st > cash else 1 if crt < 1 else 2
            items.append(it("B4", "Current ratio ≥ 0.8 or short-term debt covered by cash", m, f"{crt:.2f}", "current_ratio"))
            if m == 0:
                bad_b.append(f"current ratio {crt:.2f} with short-term debt above cash")
        sp = (nse or {}).get("shp")
        if sp and sp.get("pledge") is not None:
            pl, d1 = sp["pledge"], sp.get("pledge_1q")
            m = 0 if pl > 50 or (d1 or 0) > 10 else 1 if pl > 10 else 2
            items.append(it("B5", "Promoter pledge ≤ 50%, not up > 10 pts", m,
                            f"{pl:.1f}% of promoter shares pledged" + (f" ({d1:+.1f} pts in a quarter)" if d1 else "") + f" · {sp['asof']}",
                            note="NSE shareholding pattern"))
        elif nse and nse.get("shp_ok"):
            items.append(it("B5", "Promoter pledge ≤ 50%, not up > 10 pts", None, note="shareholding filing not loaded yet"))
        else:
            items.append(pending("B5", "Promoter pledge ≤ 50%, not up > 10 pts"))
    else:
        g = v(Mx, "gnpa_pct_advances")
        m = None if g is None else 0 if g > 10 else 1 if g > 5 else 2
        items.append(it("C1", "Gross NPA ≤ 10%", m, pc(g, 2), "gnpa_pct_advances"))
        if m == 0:
            bad_c.append(f"gross NPA {g:.1f}%")
        c1 = v(Mx, "cet1_pct")
        if c1 is None:
            items.append(pending("C2", "Capital adequacy above RBI minimum"))
        else:  # RBI: CET1 5.5% minimum + 2.5% conservation buffer = 8%
            m = 2 if c1 >= 8 else 1 if c1 >= 5.5 else 0
            items.append(it("C2", "Capital adequacy above RBI minimum", m, f"CET1 {c1:.1f}% (RBI minimum with buffer 8%)", "cet1_pct"))
            if m == 0:
                bad_c.append(f"CET1 {c1:.1f}% below RBI minimum")
        lq = v(Mx, "loss_quarters_4")
        m = None if lq is None else 0 if lq >= 2 else 1 if lq == 1 else 2
        items.append(it("C3", "No net loss in 2 of last 4 quarters", m, None if lq is None else f"{int(lq)} loss quarter(s)", "loss_quarters_4"))
        if m == 0:
            bad_c.append(f"{int(lq)} loss quarters of last 4")
    score = _rubric_score(items)
    live = [i for i in items if i.get("note") != PENDING]
    checked = [i for i in live if i["m"] is not None]
    out = bool(hard or len(bad_b) >= 2 or bad_c)
    rm = "; ".join(hard + (bad_b if len(bad_b) >= 2 else []) + bad_c) or None
    if out:
        tier = 5
    elif not live or len(checked) / len(live) < 0.6 or score is None:
        tier = 0
    else:
        tier = 1 if score >= 85 else 2 if score >= 70 else 3 if score >= 55 else 4 if score >= 40 else 5
    worst = _first(items, 0) or _first(items, 1)
    why = rm or (f"{worst['n']}: {worst['v']}" if worst else (f"{len(checked)} checks passed" if checked else None))
    return _level("surv", items, tier, score, why, out, rm)


# ------------------------------------------------------------------ L2 Business quality
def _band(x, cuts):
    """cuts: [(threshold, points), ...] descending; first threshold x >= wins."""
    for th, pts in cuts:
        if x >= th:
            return pts
    return 0


def quality(Mx, lender, ind):
    items, flags = [], []
    nq = Mx.get("quarters_available") or 0
    roce3, roce = v(Mx, "roce_3y_avg_pct"), v(Mx, "roce_pct")
    rc, rg = v(Mx, "rev_cagr_3y_pct"), v(Mx, "rev_ttm_growth_pct")
    pcg, pg = v(Mx, "pat_cagr_3y_pct"), v(Mx, "pat_ttm_growth_pct")
    em, em0, mc = v(Mx, "ebitda_margin_pct"), v(Mx, "ebitda_margin_prev_pct"), v(Mx, "margin_chg_3y_pts")
    cc, oi, rd = v(Mx, "cfo_to_ebitda_pct"), v(Mx, "other_income_pct_pbt"), v(Mx, "receivable_days")

    def yrs(key):  # the span a "_3y" metric actually covers (2 when FY y-3 is not filed): labels say it, never assume 3
        return inp(Mx, key, "years") or 3

    def growth_item(id_, name, cagr, ttm, key, bad_label):
        if cagr is None and ttm is None:
            items.append(it(id_, name, None, key=key))
            return
        if cagr is not None and ttm is not None and cagr < 5 and ttm < 10:
            m = 0
        elif (cagr is not None and cagr < 10) or (ttm is not None and ttm < 10):
            m = 1
        else:
            m = 2
        items.append(it(id_, name, m, " · ".join(x for x in (f"{yrs(key)}y {cagr:.1f}%" if cagr is not None else None,
                                                              f"last 4Q {ttm:+.1f}%" if ttm is not None else None) if x), key))
        if m == 0:
            flags.append(bad_label)

    if not lender:
        r = roce3 if roce3 is not None else roce
        if r is None:
            items.append(it("Q1", "ROCE ≥ 10%", None, key="roce_3y_avg_pct"))
        else:
            bad = r < 10 and (roce is None or roce < 10)
            m = 0 if bad else 1 if min(x for x in (roce3, roce) if x is not None) < 15 else 2
            items.append(it("Q1", "ROCE ≥ 10%", m, " · ".join(x for x in (f"{yrs('roce_3y_avg_pct')}y avg {roce3:.1f}%" if roce3 is not None else None,
                                                                          f"last 4Q {roce:.1f}%" if roce is not None else None) if x),
                            "roce_3y_avg_pct" if roce3 is not None else "roce_pct"))
            if bad:
                flags.append("low return on capital")
        if em is None:
            items.append(it("Q2", "EBITDA margin ≥ 8% or ROCE ≥ 15%", None, key="ebitda_margin_pct"))
        else:
            m = 0 if em < 8 and (roce is None or roce < 15) else 1 if em < 12 else 2
            items.append(it("Q2", "EBITDA margin ≥ 8% or ROCE ≥ 15%", m, pc(em), "ebitda_margin_pct"))
            if m == 0:
                flags.append("thin margin")
    growth_item("Q3", "Revenue growing", rc, rg, "rev_cagr_3y_pct", "stagnant revenue")
    growth_item("Q4", "Profit growing", pcg, pg, "pat_cagr_3y_pct", "stagnant profit")
    if not lender:
        if mc is None and (em is None or em0 is None):
            items.append(it("Q5", "Margins not eroding", None, key="margin_chg_3y_pts"))
        else:
            falling = em is not None and em0 is not None and em < em0
            m = 0 if mc is not None and mc < -5 and falling else 1 if (mc is not None and mc < -2) or falling else 2
            items.append(it("Q5", "Margins not eroding", m, " · ".join(x for x in (f"{yrs('margin_chg_3y_pts')}y {mc:+.1f} pts" if mc is not None else None,
                                                                                   f"last 4Q {em:.1f}% vs {em0:.1f}%" if falling else None) if x) or "stable", "margin_chg_3y_pts"))
            if m == 0:
                flags.append("margins eroding")
        if not ind or ind.get("n", 0) < 5:
            items.append(it("Q6", "Industry not shrinking", None, note="fewer than 5 companies with filings in the industry"))
        else:
            shrinking = ind["median_cagr"] < 5 and ind["share_below"] > 0.35
            m = 0 if shrinking and rc is not None and rc < ind["median_cagr"] else 1 if shrinking else 2
            items.append(it("Q6", "Industry not shrinking", m, f"industry median full-year revenue growth (2–3y CAGR) {ind['median_cagr']:.1f}% ({ind['n']} companies)"))
            if m == 0:
                flags.append("shrinking industry, company below median")
        if cc is None and oi is None and rd is None:
            items.append(it("Q7", "Earnings backed by cash", None, key="cfo_to_ebitda_pct"))
        else:
            m = 0 if (cc is not None and cc < 50) or (oi is not None and oi > 40) else \
                1 if (cc is not None and cc < 70) or (oi is not None and oi > 25) or (rd is not None and rd > 180) else 2
            parts = [f"cash conversion {cc:.0f}%" if cc is not None else None, f"other income {oi:.0f}% of PBT" if oi is not None and oi > 25 else None,
                     f"receivables {rd:.0f} days" if rd is not None and rd > 180 else None]
            items.append(it("Q7", "Earnings backed by cash", m, " · ".join(x for x in parts if x), "cfo_to_ebitda_pct" if cc is not None else "other_income_pct_pbt"))
            if m == 0:
                flags.append("weak cash backing")
    else:
        roe, roa = v(Mx, "roe_pct"), v(Mx, "roa_pct")
        if roe is None:
            items.append(it("L1", "ROE ≥ 10% or ROA ≥ 1%", None, key="roe_pct"))
        else:
            bad = roe < 10 and roa is not None and roa < 1
            m = 0 if bad else 1 if roe < 14 else 2
            items.append(it("L1", "ROE ≥ 10% or ROA ≥ 1%", m, f"ROE {roe:.1f}%" + (f" · ROA {roa:.2f}%" if roa is not None else ""), "roe_pct"))
            if bad:
                flags.append("low returns")
        ag = v(Mx, "advances_yoy_pct")
        if ag is None:
            items.append(pending("L2", "Loan book growing ≥ 5% a year"))
        else:
            items.append(it("L2", "Loan book growing ≥ 5% a year", 2 if ag >= 5 else 1 if ag >= 0 else 0, pc(ag, 1), "advances_yoy_pct"))
        nr = v(Mx, "gnpa_rising_q")
        if nr is None:
            items.append(pending("L3", "Gross NPA not rising 4 quarters in a row"))
        else:
            items.append(it("L3", "Gross NPA not rising 4 quarters in a row", 0 if nr >= 4 else 1 if nr >= 2 else 2,
                            f"rose {int(nr)} quarter{'s' if nr != 1 else ''} in a row", "gnpa_rising_q"))

    r0, r1 = v(Mx, "rev_yoy_pct"), v(Mx, "rev_yoy_prev_pct")
    mq, mqy = v(Mx, "ebitda_margin_q_pct"), v(Mx, "ebitda_margin_q_yago_pct")
    turnaround = bool(r0 is not None and r1 is not None and r0 >= 20 and r1 >= 20 and (lender or (mq is not None and mqy is not None and mq > mqy)))

    # score
    got = avail = 0.0
    def add(x, w, pts):
        nonlocal got, avail
        if x is not None:
            avail += w
            got += pts
    if not lender:
        r = roce3 if roce3 is not None else roce
        add(r, 25, _band(r, [(25, 25), (18, 18), (12, 10)]) if r is not None else 0)
    else:
        roe = v(Mx, "roe_pct")
        add(roe, 25, _band(roe, [(18, 25), (14, 18), (10, 10)]) if roe is not None else 0)
    gr = rc if rc is not None else rg
    add(gr, 20, _band(gr, [(20, 20), (12, 14), (5, 7)]) if gr is not None else 0)
    gp = pcg if pcg is not None else pg
    add(gp, 15, _band(gp, [(20, 15), (12, 10), (5, 5)]) if gp is not None else 0)
    if not lender:
        add(mc, 10, (10 if mc > 2 else 6 if mc >= -2 else 0) if mc is not None else 0)
        add(cc, 15, _band(cc, [(80, 15), (60, 9), (50, 4)]) if cc is not None else 0)
        nde = v(Mx, "net_debt_ebitda")
        add(nde, 15, (15 if nde < 0 else 12 if nde < 1 else 6 if nde < 2 else 0) if nde is not None else 0)
    else:
        roa, g = v(Mx, "roa_pct"), v(Mx, "gnpa_pct_advances")
        add(roa, 15, _band(roa, [(1.5, 15), (1, 9), (0.7, 4)]) if roa is not None else 0)
        add(g, 15, (15 if g < 2 else 10 if g < 4 else 5 if g < 6 else 0) if g is not None else 0)
    score = (got / avail * 100) if avail else None
    if score is not None and turnaround:
        score = min(100, score + 10)
    cov = avail / 100
    out = len(flags) >= 2 and not turnaround and nq >= 8
    if nq < 8:
        tier, grey = 0, "Quality not checked"
    elif len(flags) >= 2 and not turnaround:
        tier, grey = 5, None
    elif cov < 0.6 or score is None:
        tier, grey = 0, "Not enough data"
    else:
        tier, grey = (1 if score >= 80 else 2 if score >= 65 else 3 if score >= 50 else 4 if score >= 35 else 5), None
    # Excellent / Good need full-year history: 2- or 3-year revenue and profit growth (last-4-quarter jumps cannot stand in)
    capped = tier in (1, 2) and (v(Mx, "rev_cagr_3y_pct") is None or v(Mx, "pat_cagr_3y_pct") is None)
    if capped:
        tier = 3
    best, worst = _first(items, 2), _first(items, 0) or _first(items, 1)
    why = ("Turnaround watch: revenue +20% for 2 quarters with better margins" if turnaround and len(flags) >= 2 else
           f"{', '.join(flags)}" if out else
           "Capped at Average: needs 2+ years of full-year growth for Good or Excellent" if capped else
           (f"{worst['n']}: {worst['v']}" if worst and tier >= 3 else (f"{best['n']}: {best['v']}" if best else None)))
    return _level("qual", items, tier, score, why, out, ", ".join(flags) if out else None, grey=grey, turn=turnaround or None,
                  cov_pct=round(cov * 100), flags=flags or None, quarters=nq)


# ------------------------------------------------------------------ L3 Business valuation
def business_type(Mx, industry, kind, basic=None):
    if kind == "bank":
        return "Bank"
    if kind == "nbfc":
        return "NBFC"
    if kind == "insurance":
        return "Insurer"
    if (v(Mx, "investments_pct_assets") or 0) > 50:
        return "Holding company"
    if industry in REALTY or industry in REALTY_IND:
        return "Real estate developer"
    if (industry in CYCLICAL or industry in CYCLICAL_IND or basic in CYCLICAL_BASIC
            or (v(Mx, "margin_range_12q_pts") or 0) > 8):
        return "Cyclical"
    if industry in ORDER_BOOK or industry in ORDER_BOOK_IND or basic in ORDER_BOOK_BASIC:
        return "Order-book"
    at = v(Mx, "asset_turnover")
    pat = v(Mx, "pat_ttm_cr")
    if pat is not None and pat <= 0:
        return "Loss-making / early"
    if at is not None and at < 1.5:
        return "Asset-heavy steady"
    if (v(Mx, "roce_3y_avg_pct") or v(Mx, "roce_pct") or 0) >= 20 and (v(Mx, "capex_pct_rev") if v(Mx, "capex_pct_rev") is not None else 99) < 8:
        return "Compounder"
    return "Standard"


def primary(Mx, btype):
    k = METRIC_OF[btype]
    x = v(Mx, k)
    if (x is None or x <= 0) and btype not in ("Loss-making / early",) and v(Mx, "ev_sales") and (v(Mx, "pat_ttm_cr") or 0) <= 0:
        return "Loss-making / early", "ev_sales", v(Mx, "ev_sales")
    return btype, k, (x if x is not None and x > 0 else None)


def implied_growth(mcap, earnings, r=0.12, tg=0.05, years=10):
    """Growth a year for 10 years that makes discounted earnings (plus a 5%-growth terminal value) equal today's market cap."""
    if not mcap or not earnings or earnings <= 0:
        return None

    def pv(g):
        tot, e = 0.0, earnings
        for t in range(1, years + 1):
            e *= 1 + g
            tot += e / (1 + r) ** t
        return tot + e * (1 + tg) / (r - tg) / (1 + r) ** years
    lo, hi = -0.3, 0.8
    if pv(lo) > mcap:
        return lo * 100
    if pv(hi) < mcap:
        return hi * 100
    for _ in range(60):
        mid = (lo + hi) / 2
        if pv(mid) < mcap:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * 100


def valuation(Mx, btype, mkey, cur, hist, peer, lender):
    items, cheap, exp = [], 0, 0
    label = METRIC_LABEL[mkey]
    # anchor 1: own history
    hk = HIST_KEY[mkey]
    hv = [h[hk] for h in hist if h.get(hk) and h[hk] > 0]
    if cur is not None and len(hv) >= 6:
        pct = sum(1 for x in hv if x < cur) / len(hv) * 100
        m = 2 if pct <= 25 else 0 if pct >= 75 else 1
        cheap += m == 2
        exp += m == 0
        items.append(it("V1", "Cheap vs own history", m, f"{label} {cur:.1f} vs own {min(hv):.1f}–{max(hv):.1f} ({pct:.0f}th percentile, {len(hv)} quarters)"
                        + (" · history is plain EV/EBITDA" if mkey == "ev_midcycle_ebitda" else ""), mkey))
    else:
        items.append(it("V1", "Cheap vs own history", None, note="needs 6+ quarters of filed history" if cur is not None else "metric not computable"))
    # anchor 2: peers
    if cur is not None and peer and peer.get("n", 0) >= 5:
        ratio = cur / peer["median"]
        m = 2 if ratio < 0.8 else 0 if ratio > 1.25 else 1
        cheap += m == 2
        exp += m == 0
        items.append(it("V2", "Cheap vs peers", m, f"{label} {cur:.1f} vs {peer['scope']} median {peer['median']:.1f} ({peer['n']} companies)", mkey))
    else:
        items.append(it("V2", "Cheap vs peers", None, note="fewer than 5 comparable companies"))
    # anchor 3: fundamentals
    if lender:
        roe, pb = v(Mx, "roe_pct"), v(Mx, "pb")
        if roe is not None and pb is not None and roe > 0:
            fair = roe / 13
            m = 2 if pb < 0.8 * fair else 0 if pb > 1.25 * fair else 1
            cheap += m == 2
            exp += m == 0
            items.append(it("V3", "Cheap vs what returns justify", m, f"P/B {pb:.2f} vs fair {fair:.2f} (ROE {roe:.1f}% ÷ 13% cost of equity)", "pb"))
        else:
            items.append(it("V3", "Cheap vs what returns justify", None, key="roe_pct"))
    else:
        mcap, pat = v(Mx, "mcap_cr"), v(Mx, "pat_ttm_cr")
        actual = v(Mx, "pat_cagr_3y_pct")
        if actual is None:
            actual = v(Mx, "rev_cagr_3y_pct")
        ig = implied_growth(mcap, pat)
        if ig is not None and actual is not None:
            capped = min(actual, 25.0)
            m = 2 if ig < capped - 5 else 0 if ig > capped + 5 else 1
            cheap += m == 2
            exp += m == 0
            items.append(it("V3", "Price needs less growth than delivered", m,
                            f"price implies {ig:.1f}% a year for 10 years vs {actual:.1f}% delivered" + (" (capped at 25%)" if actual > 25 else "")
                            + " · 12% discount, 5% terminal growth, on profit of last 4 quarters", "pe"))
        else:
            items.append(it("V3", "Price needs less growth than delivered", None, note="needs positive profit and 2+ years of growth"))
    n = sum(1 for i in items if i["m"] is not None)
    if n < 2:
        tier = 0
    elif cheap == 3:
        tier = 1
    elif cheap >= 2 and exp == 0:
        tier = 2
    elif exp == 3:
        tier = 5
    elif exp >= 2:
        tier = 4
    else:
        tier = 3
    # RULES.md R3: earnings at a margin peak make any multiple look cheap (spread businesses, cyclicals)
    qs = [r for r in (Mx.get("quarterly") or []) if isinstance(r, list) and len(r) > 3 and r[3] is not None]
    # 12 quarters: last 4 vs the 8 before; 8 to 11 quarters: last 4 vs all the (4 to 7) quarters before (a third of stocks
    # have fewer than 12 filed quarters and could never trigger it)
    # consecutive quarter ends only: `quarterly` holds the filed quarters, so a gap stretched both windows (audit 26 Nov 2026)
    from .upside import _run
    qs = next((r for r in (_run(qs, n) for n in range(12, 7, -1)) if r), [])
    if not lender and tier in (1, 2) and len(qs) >= 8:
        base = qs[-12:-4]
        now_m = sum(r[3] for r in qs[-4:]) / 4
        base_m = sum(r[3] for r in base) / len(base)
        if base_m > 0 and now_m > 2 * base_m:
            tier = 3
            items.append(it("V4", "Margins not at a peak", 0, f"last 4 quarters EBITDA margin {now_m:.1f}% vs {base_m:.1f}% in the {len(base)} before "
                            "(more than 2×): valuation capped at Fairly valued until margins hold"))
    sc = {0: 40, 1: 100, 2: 100, 3: 60, 4: 20, 5: 0}[tier]
    best = _first(items, 2) if tier in (1, 2) else _first(items, 0) if tier in (4, 5) else _first(items, 1)
    why = f"{btype} · {label}" + (f": {best['v'].split(' (')[0]}" if best else (f" {cur:.1f}" if cur is not None else ""))
    out = tier == 5
    return _level("val", items, tier, sc, why, out, f"overvalued on all 3 anchors ({label})" if out else None,
                  type=btype, metric=label, mkey=mkey, mval=None if cur is None else round(cur, 2), cheap=cheap, exp=exp)


# ------------------------------------------------------------------ L4 Management evaluation
def management(Mx, prom_hist, research, lender, ann=None, nse=None):
    items = []
    for id_, n in (("G1", "No SEBI/RBI/exchange order or penalty (24 months)"), ("G2", "No search, fraud or forensic audit (24 months)"),
                   ("G3", "Statutory auditor did not resign (24 months)"), ("G4", "No CFO + CEO exits within 12 months")):
        items.append(_ann_item(id_, n, ann))
    flag = None
    h = [x for x in (prom_hist or []) if x.get("promoter_pct") is not None]
    if h and h[-1]["promoter_pct"] <= 0.01:
        items.append(it("G5", "Promoter stake not cut > 5 pts (12 months)", None, "no promoter group", note="not applicable"))
    elif len(h) >= 2:
        now = h[-1]["promoter_pct"]
        then = h[-5]["promoter_pct"] if len(h) >= 5 else h[0]["promoter_pct"]
        d = now - then
        mps = then > 75 and now >= 74  # selling down to the 75% minimum-public-shareholding cap is required by SEBI
        m = 2 if d >= -2 or mps else 1 if d >= -5 else 0
        items.append(it("G5", "Promoter stake not cut > 5 pts (12 months)", m, f"{then:.1f}% → {now:.1f}%" + (" (minimum public shareholding sale)" if mps and d < -2 else "")))
        if m == 0:
            flag = f"promoter stake down {abs(d):.1f} pts in 12 months"
    else:
        items.append(it("G5", "Promoter stake not cut > 5 pts (12 months)", None, note="needs 2+ shareholding filings"))
    cf = (nse or {}).get("cf") or {}
    g = cf.get("gov")
    G6N = "Loans, guarantees, security to promoter group, directors, KMPs"
    if g:
        out_ = sum(g.get(k, 0) for k in ("loan_out", "guarantee_out", "security_out"))
        adv = sum(g.get(k, 0) for k in ("loan_adv", "guarantee_adv", "security_adv"))
        eq = v(Mx, "equity_cr")
        pct = out_ / eq * 100 if eq and eq > 0 else None
        m = 2 if out_ == 0 and adv == 0 else (None if pct is None else 1 if pct <= 5 else 0)
        txt = ("none outstanding" if out_ == 0 else f"₹{out_:,.1f} cr outstanding" + (f" ({pct:.1f}% of net worth)" if pct is not None else "")) + \
              (f" · ₹{adv:,.1f} cr given in 6 months" if adv else "") + f" · half-year to {g['date']}"
        d6 = it("G6", G6N, m, txt, note="NSE integrated governance filing")
        if g.get("src"):
            d6["u"] = g["src"]
        items.append(d6)
    elif cf.get("gov_absent"):
        items.append(it("G6", G6N, None, note=f"not disclosed: the company's last {cf['gov_absent']} NSE governance filing(s) carry no loans / guarantees annexure"))
    elif cf.get("gov_ok"):
        items.append(it("G6", G6N, None, note="no half-yearly governance filing read yet"))
    else:
        items.append(pending("G6", G6N))
    G7N = "Fund use matches stated objects"
    fu = (research or {}).get("fund_use")
    raised = bool(cf.get("pref")) or bool(cf.get("dev_docs"))
    if fu:
        g7 = it("G7", G7N, 2 if fu["status"] == "no deviation" else 0, f"{fu['status']}" + (f" ({fu.get('period')})" if fu.get("period") else "") + f": {fu.get('note') or ''}"[:140],
                note="statement of deviation, quoted")
        if fu.get("source"):
            g7["u"] = fu["source"]
        items.append(g7)
    elif cf.get("dev_docs"):
        items.append(it("G7", G7N, None, note="statement of deviation filed: needs research (in the research pack)"))
    elif cf.get("pref_ok") or cf.get("ca_ok"):
        items.append(it("G7", G7N, None, note="not applicable" if not raised else "needs research"))
    else:
        items.append(pending("G7", G7N))

    got = avail = 0.0
    def add(id_, name, x, w, pts, mark, value, key=None):
        nonlocal got, avail
        if x is None or x is PENDING:
            items.append(it(id_, name, None, key=key, note=PENDING if x is PENDING else None, pts=[0, w]))
            return
        avail += w
        got += pts
        items.append(it(id_, name, mark, value, key, pts=[pts, w]))
    p = h[-1]["promoter_pct"] if h else None
    no_prom = p is not None and p <= 0.01
    na_w = 35 if no_prom else 0  # C1 15 + C3 10 + C4 10 do not apply without a promoter group
    # (no_prom: professionally run / no promoter group (e.g. many banks): promoter checks do not apply
    if no_prom:
        items.append(it("C1", "Promoter holding", None, "no promoter group", note="not applicable"))
    else:
        add("C1", "Promoter holding", p, 15, (15 if p >= 50 else 10 if p >= 35 else 5 if p >= 25 else 0) if p is not None else 0,
            (2 if p >= 50 else 1 if p >= 25 else 0) if p is not None else None, pc(p))
    # C2 ownership (merged: promoter stake trend + share-count dilution, feedback #17)
    dil = v(Mx, "dilution_3y_pct")
    dlt = (h[-1]["promoter_pct"] - h[0]["promoter_pct"]) if len(h) >= 4 and not no_prom else None
    parts, marks = [], []
    if dlt is not None:
        parts.append(f"promoter {dlt:+.1f} pts ({len(h)} quarters)")
        marks.append(2 if dlt > -1 else 1 if dlt >= -5 else 0)
    if dil is not None:
        parts.append(f"shares {dil:+.1f}% (3 years)")
        marks.append(2 if dil < 3 else 1 if dil <= 10 else 0)
    if marks:
        mk = min(marks)
        add("C2", "Ownership: promoter stake held, little dilution", min(marks), 25, {2: 25, 1: 12, 0: 0}[mk], mk, " · ".join(parts), "dilution_3y_pct")
    else:
        add("C2", "Ownership: promoter stake held, little dilution", None, 25, 0, None, None)
    if no_prom:
        items.append(it("C3", "Promoter buying in the open market (12 months)", None, "no promoter group", note="not applicable"))
        items.append(it("C4", "No promoter pledge", None, "no promoter group", note="not applicable"))
    else:
        if cf.get("pit_ok"):
            b_, s_ = cf.get("prom_buy", 0), cf.get("prom_sell", 0)
            net = b_ - s_
            add("C3", "Promoter buying in the open market (12 months)", net, 10, 10 if net > 0 else 5 if net == 0 else 0,
                2 if net > 0 else 1 if net == 0 else 0,
                "no open-market trades by promoters" if not cf.get("prom_trades") else f"bought ₹{b_:,.2f} cr, sold ₹{s_:,.2f} cr ({cf['prom_trades']} trades)")
        else:
            add("C3", "Promoter buying in the open market (12 months)", PENDING, 10, 0, None, None)
        sp = (nse or {}).get("shp")
        if sp and sp.get("pledge") is not None:
            pl = sp["pledge"]
            add("C4", "No promoter pledge", pl, 10, 10 if pl == 0 else 5 if pl <= 10 else 0, 2 if pl == 0 else 1 if pl <= 10 else 0,
                "none pledged" if pl == 0 else f"{pl:.1f}% of promoter shares pledged")
        else:
            add("C4", "No promoter pledge", PENDING if not (nse and nse.get("shp_ok")) else None, 10, 0, None, None)
    cred = (research or {}).get("credibility") or {}
    cp = cred.get("pct") if (cred.get("due") or 0) >= 2 else None
    add("C6", "Promises kept", cp, 15, (15 if cp >= 75 else 8 if cp >= 50 else 0) if cp is not None else 0,
        (2 if cp >= 75 else 1 if cp >= 50 else 0) if cp is not None else None, None if cp is None else f"{cp}% of {cred.get('due')} promises")
    c7 = (ann or {}).get("C7")
    if c7:
        add("C7", "Leadership stable (24 months)", c7[0], 10, {2: 10, 1: 5}.get(c7[0], 0) if "1 CEO" in c7[1] or c7[0] == 2 else 2, c7[0], c7[1])
        items[-1]["note"] = c7[2]
        if c7[3]:
            items[-1]["u"] = c7[3]
    else:
        add("C7", "Leadership stable (24 months)", PENDING, 10, 0, None, None)
    rf = Mx.get("roce_fy") or []
    rc = v(Mx, "rev_cagr_3y_pct")
    if len(rf) >= 2 and rc is not None and not lender:
        d = rf[-1][1] - rf[0][1]
        good = d >= -2 and rc > 5
        add("C8", "Capital allocation: returns held while growing", d, 10, 10 if good else 0, 2 if good else 1 if d >= -5 else 0,
            f"ROCE FY{rf[0][0] % 100} {rf[0][1]:.1f}% → FY{rf[-1][0] % 100} {rf[-1][1]:.1f}%, revenue {rc:.1f}% a year", "roce_3y_avg_pct")
    else:
        add("C8", "Capital allocation: returns held while growing", None, 10, 0, None, None)
    if cf.get("ca_ok"):
        n_ = cf.get("div_years", 0)
        add("C9", "Dividends 3 of 3 years", n_, 5, {3: 5, 2: 3, 1: 1}.get(n_, 0), 2 if n_ == 3 else 1 if n_ >= 1 else 0,
            f"paid in {n_} of the last 3 years" + (f" (latest ex-date {cf['div_last']})" if cf.get("div_last") else ""))
    else:
        add("C9", "Dividends 3 of 3 years", PENDING, 5, 0, None, None)
    score = got / avail * 100 if avail else None
    cov = avail / (100 - na_w)
    if flag:
        tier, out, rm = 5, True, flag
    elif cov < 0.6 or score is None:
        tier, out, rm = 0, False, None
    elif score < 45:
        tier, out, rm = 4, True, f"conviction {score:.0f}/100 with {cov * 100:.0f}% coverage"
    else:
        tier, out, rm = (1 if score >= 80 else 2 if score >= 65 else 3), False, None
    best, worst = _first(items, 2), _first(items, 0)
    why = rm or (f"{worst['n']}: {worst['v']}" if worst and tier >= 3 else f"{best['n']}: {best['v']}" if best else None)
    return _level("mgmt", items, tier, score, why, out, rm, grey="Conviction unverified", cov_pct=round(cov * 100))


# ------------------------------------------------------------------ L5 Momentum analysis (no removals)
def momentum(t, df, rs_pct, ind_rank, bulk, Mx, an, nse=None):
    items = []
    got = avail = 0.0

    def add(id_, name, w, pts, value, mark=None, avail_=True):
        nonlocal got, avail
        if not avail_:
            items.append(it(id_, name, None, note=PENDING if value == PENDING else value, pts=[0, w]))
            return
        avail += w
        got += pts
        items.append(it(id_, name, mark if mark is not None else (2 if pts >= 0.66 * w else 1 if pts > 0 else 0), value, pts=[round(pts, 1), w]))
    if t:
        st = t["stage"]
        add("P1", "Price stage", 15, {"Stage 2": 15, "Stage 1→2": 12, "Basing": 5, "Downtrend": 0, "Extended": 8}.get(st, 0), st)
        add("P2", "Relative strength vs universe", 15, 15 * rs_pct, f"{rs_pct * 100:.0f}th percentile")
        if ind_rank is not None:
            add("P3", "Top third of its industry", 5, 5 if ind_rank >= 2 / 3 else 0, f"{ind_rank * 100:.0f}th percentile in industry")
        else:
            add("P3", "Top third of its industry", 5, 0, "fewer than 3 industry peers", avail_=False)
        near = t["price"] >= 0.9 * t["hi52"]
        add("P4", "Within 10% of 52-week high or fresh breakout", 5, 5 if near or t["recent_breakout"] else 0,
            f"{(t['price'] / t['hi52'] - 1) * 100:+.1f}% from 52w high" + (" · breakout in last 10 days" if t["recent_breakout"] else ""))
        c = df["Close"]
        flat = len(c) > 50 and abs(float(c.iloc[-1] / c.iloc[-51] - 1)) < 0.05
        obv_pts = (8 if t["obv_high"] else 0) + (4 if t["obv_high"] and flat else 0)
        add("F1", "On-balance volume at 50-day high", 12, obv_pts, ("yes" if t["obv_high"] else "no") + (", while price flat (accumulation)" if t["obv_high"] and flat else ""))
        u = t["ud_ratio"]
        add("F2", "Up-volume vs down-volume (50 days)", 7, 7 if u > 1.3 else 3 if u >= 1 else 0, f"{u:.2f}")
    dv = (nse or {}).get("deliv")
    if dv and dv.get("m3"):
        r_ = dv["d10"] / dv["m3"] if dv["m3"] else 0
        add("F3", "Delivery % vs own 3-month average", 8, 8 if r_ >= 1.2 else 4 if r_ >= 1.0 else 0,
            f"10-day {dv['d10']:.0f}% vs 3-month {dv['m3']:.0f}% ({(nse or {}).get('deliv_src', 'NSE')})")
    elif nse and nse.get("deliv_ok"):
        add("F3", "Delivery % vs own 3-month average", 8, 0, f"building history ({(dv or {}).get('n', 0)} of 40 days)", avail_=False)
    else:
        add("F3", "Delivery % vs own 3-month average", 8, 0, PENDING, avail_=False)
    buys = [b for b in bulk or [] if str(b.get("side", "")).upper() == "BUY" and any(w in f" {str(b.get('client', '')).upper()}" for w in INST_WORDS)]
    sells = [b for b in bulk or [] if str(b.get("side", "")).upper() == "SELL" and any(w in f" {str(b.get('client', '')).upper()}" for w in INST_WORDS)]
    if t:
        add("F4", "Institutional bulk/block deals (1 month)", 4, 4 if buys and not sells else 0,
            f"{len(buys)} institutional buy(s), {len(sells)} sell(s)" if (buys or sells) else "none", mark=2 if buys and not sells else 0 if sells else 1)
        if sells and not buys:
            got -= 4
    sp = (nse or {}).get("shp")
    if sp and sp.get("inst_1q") is not None:
        c1 = sp["inst_1q"]
        add("F5", "Institutional holding up ≥ 1 pt QoQ", 4, 4 if c1 >= 1 else 2 if c1 > 0 else 0,
            f"institutions {sp['inst']:.1f}% ({c1:+.1f} pts in a quarter to {sp['asof']})", mark=2 if c1 >= 1 else 1 if c1 > -1 else 0)
    elif nse and nse.get("shp_ok"):
        add("F5", "Institutional holding up ≥ 1 pt QoQ", 4, 0, "needs 2 quarterly filings", avail_=False)
    else:
        add("F5", "Institutional holding up ≥ 1 pt QoQ", 4, 0, PENDING, avail_=False)
    r0, r1, r2 = v(Mx, "rev_yoy_pct"), v(Mx, "rev_yoy_prev_pct"), v(Mx, "rev_yoy_prev2_pct")
    if r0 is not None and r1 is not None:
        acc2 = r2 is not None and r0 > r1 > r2
        add("E1", "Revenue growth accelerating", 10, 10 if acc2 else 5 if r0 > r1 else 0,
            f"YoY {r0:.0f}% vs {r1:.0f}%" + (f" vs {r2:.0f}%" if r2 is not None else ""))
    else:
        add("E1", "Revenue growth accelerating", 10, 0, "needs 2 quarters of filings", avail_=False)
    filed = Mx.get("filed")
    react = None
    if filed and df is not None:
        try:
            fd = pd.Timestamp(filed)
            before = df["Close"][df.index < fd]
            after = df["Close"][df.index >= fd]
            if len(before) and len(after) >= 3:
                react = (float(after.iloc[2]) / float(before.iloc[-1]) - 1) * 100
        except Exception:  # noqa: BLE001
            react = None
    if react is not None:
        add("E2", "Price reaction to latest results (3 days)", 8, 8 if react > 5 else 0 if react < -5 else 4, f"{react:+.1f}% after {filed}")
    else:
        add("E2", "Price reaction to latest results (3 days)", 8, 0, "results date or prices missing", avail_=False)
    est = (an or {}).get("eps_est") or {}
    if est.get("cur") is not None and est.get("d30"):
        ch = (est["cur"] / est["d30"] - 1) * 100 if est["d30"] else 0
        add("E3", "EPS estimates revised up (30 days)", 7, 7 if ch >= 3 else 0 if ch < 0 else 3, f"{ch:+.1f}% (Yahoo consensus)")
    else:
        add("E3", "EPS estimates revised up (30 days)", 7, 0, "no analyst estimates", avail_=False)
    score = max(0.0, got) / avail * 100 if avail else None
    cov = avail / 100
    extended = bool(t and (t["dist200_pct"] > 45 or (t.get("ret_6m") or 0) > 100))
    tier = 0 if score is None or cov < 0.6 else 1 if score >= 80 else 2 if score >= 65 else 3 if score >= 50 else 4 if score >= 35 else 5
    best = _first(items, 2)
    why = (t["stage"] if t else "") + (f" · {best['n'].lower()}" if best and best["id"] != "P1" else "") + (" · extended" if extended else "")
    return _level("mom", items, tier, score, why.strip(" ·") or None, extended=extended or None, cov_pct=round(cov * 100),
                  rs_pct=round(float(rs_pct), 4) if t else None)


# ------------------------------------------------------------------ L6 Discovery stage (no removals)
def discovery(inst, analysts, df, bulk, nse=None):
    items = []
    vr = None
    if df is not None and len(df) >= 200:
        v200 = float(df["Volume"].iloc[-200:].mean())
        vr = float(df["Volume"].iloc[-50:].mean()) / v200 if v200 > 0 else None
    inst_buy = [b for b in bulk or [] if str(b.get("side", "")).upper() == "BUY" and any(w in f" {str(b.get('client', '')).upper()}" for w in INST_WORDS)]
    an = analysts if analysts is not None else (0 if inst is not None else None)
    sp = (nse or {}).get("shp")
    # D1 on NSE's shareholding pattern, the official filing (owner, 26 Nov 2026); Yahoo only when no filing is loaded
    if sp and sp.get("inst") is not None:
        inst, src = sp["inst"], "NSE shareholding pattern" + (f" · {sp['asof']}" if sp.get("asof") else "")
    else:
        src = "Yahoo (labelled)"
    items.append(it("D1", "Institutional holding", None if inst is None else (2 if inst < 10 else 1 if inst <= 25 else 0), pc(inst), note=src))
    items.append(it("D2", "Analysts covering", None if an is None else (2 if an <= 2 else 1 if an <= 8 else 0), None if an is None else str(an), note="Yahoo (labelled)"))
    items.append(it("D3", "Volume 50 days vs 200 days", None if vr is None else (2 if vr >= 1.3 else 1), None if vr is None else f"{vr:.2f}x"))
    items.append(it("D4", "Institutional bulk buys (1 month)", 2 if inst_buy else 1, str(len(inst_buy))))
    if sp:
        c1, c4 = sp.get("inst_1q"), sp.get("inst_4q")
        if c1 is not None:
            m = 2 if c1 >= 0.5 or (c4 or 0) >= 2 else 0 if (c4 if c4 is not None else c1) <= -2 else 1
            items.append(it("D5", "Institutional holding change (1Q, 4Q)", m,
                            f"{sp['inst']:.1f}% (MF {sp['mf']:.1f}%, foreign {sp['fii']:.1f}%) · 1Q {c1:+.1f} pts" + (f" · 4Q {c4:+.1f} pts" if c4 is not None else ""),
                            note="NSE shareholding pattern"))
        else:
            items.append(it("D5", "Institutional holding change (1Q, 4Q)", None, f"{sp['inst']:.1f}%", note="needs 2 quarterly filings"))
        n1 = sp.get("mf_n_1q")
        items.append(it("D6", "Number of mutual funds holding", None if n1 is None else (2 if n1 > 0 else 0 if n1 < 0 else 1),
                        f"{sp['mf_n']} mutual fund holder(s)" + (f" ({n1:+d} in a quarter)" if n1 is not None else ""), note="NSE shareholding pattern (all MF holdings)"))
    elif nse and nse.get("shp_ok"):
        items.append(it("D5", "Institutional holding change (1Q, 4Q)", None, note="shareholding filing not loaded yet"))
        items.append(it("D6", "Number of mutual funds holding", None, note="shareholding filing not loaded yet"))
    else:
        for id_, n in (("D5", "Institutional holding change (1Q, 4Q)"), ("D6", "Number of mutual funds holding")):
            items.append(pending(id_, n))
    dv = (nse or {}).get("deliv")
    if dv and dv.get("m3"):
        ch = dv["m1"] - dv["m3"]
        items.append(it("D7", "Delivery % trend", 2 if ch >= 3 else 0 if ch <= -3 else 1, f"1-month {dv['m1']:.0f}% vs 3-month {dv['m3']:.0f}% ({(nse or {}).get('deliv_src', 'NSE')})"))
    elif nse and nse.get("deliv_ok"):
        items.append(it("D7", "Delivery % trend", None, note=f"building history ({(dv or {}).get('n', 0)} of 40 days)"))
    else:
        items.append(pending("D7", "Delivery % trend"))
    if nse and nse.get("idx_ok"):
        ix = nse.get("idx")
        if ix:
            items.append(it("D8", "Index inclusion", {"Nifty 50": 0, "Nifty 100": 0, "Nifty Midcap 150": 0, "Nifty Smallcap 250": 1}.get(ix[0], 2),
                            f"{ix[0]} (in our records since {ix[1]})", note="NSE index lists"))
        else:
            items.append(it("D8", "Index inclusion", 2, "listed on BSE only: in no Nifty index" if (nse or {}).get("deliv_src") == "BSE"
                            else "not in Nifty 50/100, Midcap 150, Smallcap 250 or Microcap 250", note="NSE index lists"))
    else:
        items.append(pending("D8", "Index inclusion"))
    if sp and sp.get("retail_yoy_pct") is not None:
        r = sp["retail_yoy_pct"]
        items.append(it("D9", "Retail shareholder count YoY", 2 if r >= 10 else 0 if r <= -10 else 1,
                        f"{sp['retail_n']:,} small holders ({r:+.0f}% in a year)", note="NSE shareholding pattern"))
    elif sp:
        items.append(it("D9", "Retail shareholder count YoY", None, None if sp.get("retail_n") is None else f"{sp['retail_n']:,} small holders",
                        note="needs 5 quarterly filings"))
    elif nse and nse.get("shp_ok"):
        items.append(it("D9", "Retail shareholder count YoY", None, note="shareholding filing not loaded yet"))
    else:
        items.append(pending("D9", "Retail shareholder count YoY"))
    if inst is None and an is None:
        return _level("disc", items, 0, None, None, grey="Not checked")
    i = inst if inst is not None else 0
    # D1 can now come from NSE's filing while Yahoo has no record (no analyst count): unknown analysts count as none,
    # as they did when Yahoo had a holding figure but no analysts; the text says "analysts not known" (run of 26 Nov 2026)
    a = an if an is not None else 0
    atx = "analysts not known" if an is None else f"{an} analyst" + ("" if an == 1 else "s")
    expanding = vr is not None and vr >= 1.3
    if i > 25 or a > 8:
        tier, why = 5, f"institutions {i:.0f}%, {atx}"
    elif 20 <= i <= 25 or 6 <= a <= 8:
        tier, why = 4, f"institutions {i:.0f}%, {atx}"
    elif (10 <= i <= 25 or 3 <= a <= 8) and expanding:
        tier, why = 3, f"institutions {i:.0f}%, volume {vr:.1f}x its 200-day average"
    elif i < 10 and inst_buy and a <= 2:
        tier, why = 2, f"institutional bulk buying, institutions {i:.0f}%, {atx}"
    elif i < 5 and a <= 1 and not expanding:
        tier, why = 1, f"institutions {i:.0f}%, {atx}, no volume expansion"
    elif i >= 10 or a >= 3:
        tier, why = 4, f"institutions {i:.0f}%, {atx}, no volume expansion"
    else:
        tier, why = 1, f"institutions {i:.0f}%, {atx}"
    # tier is rule-based; the score is the rubric share of D1-D9 marks, as for Stability (it was never set: sc[5] was null)
    return _level("disc", items, tier, _rubric_score(items), why, vol_ratio=None if vr is None else round(vr, 2))


# ------------------------------------------------------------------ L7 Future outlook (needs research)
def outlook(Mx, wind, rot_q, research, scan_raw, flags_text, l1, l2, l4, nse=None, signals=None):
    """`signals`: price-moving signals T11-T15 (`signal_triggers`), counted as live triggers before the tier, score and the
    "industry headwind and no live trigger" removal are decided."""
    items, live = [], []
    ob_ratio = None
    researched = bool(scan_raw)
    w = (wind or {}).get("wind")
    wind_pts = {"Tailwind": 30, "Neutral": 15, "Headwind": 0}.get(w, 15)
    if w:
        items.append(it("W", "Industry wind", {"Tailwind": 2, "Neutral": 1, "Headwind": 0}[w],
                        f"{w}: median revenue growth {wind['median']:.1f}% (a year ago {wind['median_prev']:.1f}%), {wind['breadth']:.0f}% growing >10%, {wind['n']} companies"
                        + (f" · price rotation {rot_q}" if rot_q else "")))
    else:
        items.append(it("W", "Industry wind", None, note="fewer than 5 companies with filings (scored Neutral)"))

    def trig(id_, name, state, value=None, strong=False, key=None, note=None):
        if state is None:
            items.append(it(id_, name, None, value, key, note))
            return
        items.append(it(id_, name, 2 if state else 1, value, key))
        if state:
            live.append((id_, name, value, strong))
    rev = v(Mx, "revenue_ttm_cr")
    ob = (scan_raw or {}).get("order_book") or {}
    if researched and ob.get("value_cr") and rev:
        r = ob["value_cr"] / rev
        ob_ratio = round(r, 2)
        trig("T1", "Order book ≥ 2× revenue", r >= 2, f"{r:.2f}x (₹{ob['value_cr']:,.0f} cr, quoted)", strong=r >= 3)
    else:
        trig("T1", "Order book ≥ 2× revenue", None, note="needs research" if not researched else "no order book quoted")
    b2 = (nse or {}).get("b2b")
    if b2:
        st2, val2, note2, url2 = b2
        trig("T2", "Book-to-bill > 1", st2, val2, strong=bool(st2), note=None if st2 is not None else note2)
        if url2 and items[-1].get("id") == "T2":
            items[-1]["u"] = url2
    else:
        trig("T2", "Book-to-bill > 1", None, note=PENDING)
    t3 = (nse or {}).get("t3")
    if t3:
        st3, val3, note3, url3 = t3
        trig("T3", "Single order ≥ 10% of revenue (6 months)", st3, val3, strong=bool(st3), note=None if st3 is not None else note3)
        if url3 and items[-1].get("id") == "T3":
            items[-1]["u"] = url3
    else:
        trig("T3", "Single order ≥ 10% of revenue (6 months)", None, note=PENDING)
    cw = v(Mx, "cwip_pct_ppe")
    trig("T4", "Capacity coming: work in progress ≥ 20% of fixed assets", None if cw is None else cw >= 20, pc(cw), key="cwip_pct_ppe")
    r0, r1, r2 = v(Mx, "rev_yoy_pct"), v(Mx, "rev_yoy_prev_pct"), v(Mx, "rev_yoy_prev2_pct")
    mq, mqy = v(Mx, "ebitda_margin_q_pct"), v(Mx, "ebitda_margin_q_yago_pct")
    if None not in (r0, r1, r2, mq, mqy):
        trig("T7", "Revenue accelerating 2 quarters and margin +2 pts", r0 > r1 > r2 and mq - mqy >= 2,
             f"YoY {r2:.0f}% → {r1:.0f}% → {r0:.0f}% · margin {mqy:.1f}% → {mq:.1f}%", key="rev_yoy_pct")
    else:
        trig("T7", "Revenue accelerating 2 quarters and margin +2 pts", None, note="needs 3 quarters of filings")
    proms = (research or {}).get("promises") or []
    raised = [p for p in proms if p.get("status") == "raised" or any(u.get("type") == "raised" for u in p.get("updates") or [])]
    trig("T8", "Guidance raised", (bool(raised) if researched or proms else None), raised[0]["promise"] if raised else None,
         note=None if researched or proms else "needs research")
    dc = v(Mx, "debt_chg_yoy_pct")
    trig("T9", "Value unlock: debt down > 30% in a year", None if dc is None else dc <= -30, None if dc is None else f"{dc:+.0f}%", key="debt_chg_yoy_pct")
    for m in ((scan_raw or {}).get("checklist") or {}).get("outlook", []):
        if m.get("mark") == "y":
            trig(f"R{m.get('id', '')}", m.get("name") or "Research trigger", True, (m.get("note") or "")[:90] or "quoted in filings")
    cf = (nse or {}).get("cf") or {}
    T10N = "Preferential issue at or above market price (12 months)"
    pf = cf.get("pref") or []
    if pf:
        al, px_, sh_, amt, _typ = pf[0]
        mk = (nse or {}).get("pref_mkt")  # close on the allotment date (prices)
        prem = (px_ / mk - 1) * 100 if px_ and mk else None
        val = f"₹{px_:,.0f} on {al}" + (f" vs market ₹{mk:,.0f} ({prem:+.0f}%)" if prem is not None else "") + (f", ₹{amt / 1e7:,.0f} cr raised" if amt else "")
        trig("T10", T10N, None if prem is None else prem >= 0, val)
    elif cf.get("pref_ok"):
        items.append(it("T10", T10N, None, "no preferential issue in 12 months"))
    else:
        trig("T10", T10N, None, note=PENDING)
    live += [tuple(x) for x in signals or []]
    tp = min(70, sum(15 if s else 10 for *_, s in live))
    score = wind_pts + tp
    # key risks: verifiable only
    risks = []
    for lv in (l1, l2, l4):
        for i in lv["items"]:
            if i["m"] == 0 and i.get("v"):
                risks.append({"text": f"{i['n']}: {i['v']}", "src": "Computed from filings" if lv is not l4 else "NSE shareholding filings", "k": i.get("k")})
    rd = v(Mx, "receivable_days")
    if rd is not None and rd > 120:
        risks.append({"text": f"Receivables {rd:.0f} days of revenue", "src": "Computed from filings", "k": "receivable_days"})
    for f_ in flags_text or []:
        risks.append({"text": f_, "src": "NSE filing"})
    for p in proms:
        if p.get("status") in ("missed", "delayed"):
            risks.append({"text": f"Promise {p['status']}: {p.get('promise', '')}", "src": p.get("source", ""), "quote": p.get("quote")})
    for k in (scan_raw or {}).get("kill_switches") or []:
        risks.append({"text": f"Kill switch: {k.get('text', '')}", "src": k.get("source", ""), "quote": k.get("quote")})
    if not researched:
        tier, grey = 0, "Not scanned yet"
    elif not live:
        tier, grey = 5, None
    else:
        tier, grey = (1 if score >= 75 else 2 if score >= 55 else 3 if score >= 35 else 4), None
    out = researched and w == "Headwind" and not live
    best = max(live, key=lambda x: x[3]) if live else None
    why = (f"{best[1]}" + (f": {best[2]}" if best[2] else "")) if best else (f"{w or 'Neutral'} industry, no live trigger" if researched else
                                                                             f"{w or 'Industry wind unknown'}" + (f" · {len(live)} computed trigger(s)" if live else ""))
    return _level("out", items, tier, score, why, out, "industry headwind and no live trigger" if out else None, grey=grey,
                  wind=w, nlive=len(live), triggers=[{"id": a, "n": b, "v": c, "strong": d or None} for a, b, c, d in live] or None,
                  risks=risks[:8] or None, researched=researched, ob_ratio=ob_ratio)


# ------------------------------------------------------------------ verdict, statement, priority
VERDICTS = ["Prime candidate", "Early story", "Undervalued quality", "Quality, priced in", "Momentum play", "Value watch", "Watchlist", "Not enough data"]


POSITIVE_VERDICTS = ("Prime candidate", "Early story", "Undervalued quality")


def verdict(L, dec=None):
    """Profile tag. A Sell / Strong Sell decision blocks the positive tags so the tag never contradicts the decision."""
    t = {k: L[k]["t"] for k in LEVELS}
    block = dec in ("Sell", "Strong Sell")
    # Outlook is grey until Claude researches the stock; that is expected, not a data gap, so it is not counted here.
    if sum(1 for k in LEVELS if t[k] == 0 and not (k == "out" and not L["out"].get("researched"))) >= 3:
        return "Not enough data"
    turn = bool(L["qual"].get("turn"))
    mg_adequate = t["mgmt"] in (0, 1, 2, 3)  # 0 = conviction unverified (missing data never counts against)
    if not block and t["qual"] in (1, 2) and t["mgmt"] in (1, 2) and t["val"] in (1, 2, 3) and t["out"] in (1, 2) and t["disc"] != 5:
        return "Prime candidate"
    if not block and t["out"] in (1, 2) and (t["qual"] == 3 or turn) and mg_adequate:
        return "Early story"
    if not block and t["qual"] in (1, 2) and t["val"] in (1, 2) and mg_adequate:
        return "Undervalued quality"
    if t["qual"] in (1, 2) and t["mgmt"] in (1, 2) and t["val"] == 4:
        return "Quality, priced in"
    if t["mom"] in (1, 2) and t["qual"] in (1, 2, 3) and t["disc"] in (2, 3):
        return "Momentum play"
    if t["val"] in (1, 2) and t["qual"] in (3, 4):
        return "Value watch"
    return "Watchlist"


def statement(vd, L):
    def best(k, mark=2):
        i = _first(L[k]["items"], mark)
        return fact(i) if i else None
    parts = [f"{vd}."]
    q, m, va = L["qual"], L["mgmt"], L["val"]
    seg = []
    if q["t"]:
        f = best("qual")
        seg.append(f"{q['name']} business" + (f" ({f})" if f else "") + (", turnaround watch" if q.get("turn") else ""))
    if m["t"]:
        f = best("mgmt")
        seg.append(f"{m['name'].lower()} management" + (f" ({f})" if f else ""))
    if va["t"]:
        f = _first(va["items"], 2 if va["t"] <= 2 else 0 if va["t"] >= 4 else 1)
        seg.append(f"{va['name'][:1].lower() + va['name'][1:]} on {va.get('metric')}" + (f" ({FACT.get(f['id'], '')}: {f['v'].split(' (')[0]})" if f else ""))
    if seg:
        s_ = ", ".join(seg)
        parts.append(s_[:1].upper() + s_[1:] + ".")
    mo, di = L["mom"], L["disc"]
    seg = []
    if mo["t"]:
        seg.append(f"Momentum {mo['name'].lower()}")
    if di["t"]:
        seg.append(di["name"].lower())
    if seg:
        parts.append(", ".join(seg) + ".")
    o = L["out"]
    tr = o.get("triggers") or []
    if o.get("researched") and tr:
        b = max(tr, key=lambda x: bool(x.get("strong")))
        parts.append(f"Trigger: {FACT.get(b['id'], b['n'].lower())}" + (f" {b['v']}" if b.get("v") else "") + ".")
    elif not o.get("researched"):
        parts.append("Outlook not checked yet.")
    else:
        parts.append("No live growth trigger found.")
    worst = None
    for k in ("surv", "qual", "mgmt", "val"):
        worst = _first(L[k]["items"], 0)
        if worst:
            break
    if not worst:
        for k in ("surv", "qual", "mgmt"):
            worst = _first(L[k]["items"], 1)
            if worst:
                break
    if worst:
        parts.append(f"Watch: {fact(worst)}.")
    return " ".join(parts)


def priority(L):
    q = L["qual"]
    qs = q["s"] if q["t"] and q["s"] is not None else 50
    m = L["mgmt"]
    ms = m["s"] if m["t"] and m["s"] is not None else 40
    vs = L["val"]["s"] if L["val"]["s"] is not None else 40
    mo = L["mom"]
    mos = mo["s"] if mo["t"] and mo["s"] is not None else 50
    p = 0.35 * qs + 0.25 * ms + 0.22 * vs + 0.18 * mos
    p += {1: 5, 2: 10, 5: -10}.get(L["disc"]["t"], 0)
    if mo.get("extended"):
        p -= 15
    return round(p, 1)


# ------------------------------------------------------------------ entry setups (PLAN.md section 5)
def _atr(df, n=14):
    pc_ = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc_).abs(), (df["Low"] - pc_).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def setup(df, t, target):
    if df is None or t is None or len(df) < 210:
        return {"type": "No data"}
    c = df["Close"]
    price = float(c.iloc[-1])
    h55 = float(df["High"].iloc[-56:-1].max())
    atr = _atr(df)
    e10, e21 = float(c.ewm(span=10).mean().iloc[-1]), float(c.ewm(span=21).mean().iloc[-1])
    s50, s200 = float(c.rolling(50).mean().iloc[-1]), float(c.rolling(200).mean().iloc[-1])
    l20 = float(df["Low"].iloc[-20:].min())
    st = t["stage"]
    out = {"sma50": round(s50, 2), "atr": round(atr, 2), "price": round(price, 2), "h55": round(h55, 2)}  # the setup's stop is the one exit level; atr / price / h55 let the app explain it
    lo_b, hi_b = sorted([e10, e21])
    if st == "Downtrend" or (price < s200 and st != "Basing"):
        return out | {"type": "No setup", "note": "No entry: trend broken (below the 200-day average)"}
    if st in ("Stage 2", "Stage 1→2") and 0.9 * h55 <= price <= 1.05 * h55:
        lo, hi = h55, h55 * 1.05
        # live from 0.9x the high, so a call opens at today's price: anchor the stop on the lower of the price and the
        # breakout level, else the exit level can sit above the entry (SATIN 254.55 with an exit level of 260.8)
        ref = min(price, lo)
        stop = max(ref - 1.5 * atr, ref * 0.92)
        out |= {"type": "Breakout", "lo": lo, "hi": hi, "stop": stop, "ref": round(ref, 2), "note": "Buy on a close above the 55-day high, up to +5%"}
    elif st in ("Stage 2", "Extended") and lo_b * 0.99 <= price <= hi_b * 1.01:
        out |= {"type": "Pullback", "lo": lo_b, "hi": hi_b, "stop": s50 * 0.99, "note": "Pullback to the 10–21 day averages; stop on a close below the 50-day average"}
    elif (s200 < price < s50) or st == "Basing":
        lo, hi = l20, l20 * 1.05
        out |= {"type": "Base", "lo": lo, "hi": hi, "add": s50, "stop": max(l20 - 1.5 * atr, l20 * 0.90),
                "note": "Accumulate near the 20-day low; add above the 50-day average"}
    elif st == "Extended":
        return out | {"type": "No setup", "note": "Extended: wait for a pullback to the 10–21 day averages", "watch_lo": round(lo_b, 2), "watch_hi": round(hi_b, 2)}
    else:
        return out | {"type": "No setup", "note": "Wait: not at a breakout, pullback or base level", "watch_lo": round(lo_b, 2), "watch_hi": round(hi_b, 2)}
    if round(out["stop"], 2) >= round(price, 2):  # an exit level at or above today's price is no live entry (a pullback under the 50-day average)
        return {"sma50": out["sma50"], "type": "No setup", "note": "Wait: price at or below the exit level",
                "watch_lo": round(lo_b, 2), "watch_hi": round(hi_b, 2)}
    if round(out["stop"], 2) >= round(out["lo"], 2):
        # the exit level must sit below the whole buy zone, or a buy at the zone low is already under it (TALBROAUTO Pullback:
        # zone 393.48-401.20 with the 50-day-average stop at 399.06, price 404.05): recompute it under the zone low
        out["stop"] = max(out["lo"] - 1.5 * atr, out["lo"] * 0.92)
        out["stop_basis"] = "zone"  # app: "1.5 x the daily move under the buy zone's low"
        if out["type"] == "Pullback":
            out["note"] = "Pullback to the 10–21 day averages; stop on a close below the zone (the 50-day average sits inside it)"
    mid = (out["lo"] + out["hi"]) / 2
    risk = mid - out["stop"]
    out["size_10l"] = int(10000 / risk) if risk > 0 else None
    if target:
        if target <= out["hi"]:
            out["rr_note"] = "Above analyst target"
        elif risk > 0:
            rr = (target - mid) / risk
            out["rr"] = round(rr, 2)
            if rr < 1.5:
                out["rr_note"] = "Unfavourable"
    for k in ("lo", "hi", "add", "stop"):
        if k in out:
            out[k] = round(out[k], 2)
    return out


LIVE_SETUPS = ("Breakout", "Pullback", "Base")


def setup_tier(su: dict | None, extended) -> int:
    """Entry-setup tier of the readiness ranking (RULES.md Ranking step 2), shared by run.py `readiness` and the history
    replay (narrativ/replay.py) so both rank alike: 0 live setup (breakout, pullback, base); 2 price extended, or no setup
    because the trend is broken ("No entry") or the price is extended; 1 everything else (wait)."""
    su = su or {}
    bad = bool(extended) or (su.get("type") == "No setup" and str(su.get("note") or "").startswith(("No entry", "Extended")))
    return 2 if bad else 0 if su.get("type") in LIVE_SETUPS else 1


def bands(su: dict | None, price) -> dict | None:
    """The dossier's entry / exit band, derived from the entry setup so the app and Claude see one exit level: the setup's
    stop, the level calls.py closes a call at. Until Nov 2026 a separate breakout band (technicals) carried its own stop,
    above the price for 9 of 10 Buys (ARROWGREEN band stop 889 vs setup stop 593 at a price of 670)."""
    su = su or {}
    if su.get("lo") is None or su.get("stop") is None:
        return None
    out = {"type": su.get("type"), "buy_low": su["lo"], "buy_high": su.get("hi"), "stop": su["stop"], "from": "entry setup"}
    if price:
        out["stop_pct"] = round((su["stop"] / price - 1) * 100, 1)
    return out


# ------------------------------------------------------------------ industry statistics from our own filings
def industry_stats(rows):
    """rows: [(industry, Mx)]. Q6 shrink test and L7 industry wind, from computed growth only."""
    by = {}
    for ind, Mx in rows:
        if isinstance(ind, str) and ind:
            by.setdefault(ind, []).append(Mx)
    out = {}
    for ind, ms in by.items():
        cg = [v(m, "rev_cagr_3y_pct") for m in ms]
        cg = [x for x in cg if x is not None]
        now = [v(m, "rev_ttm_growth_pct") for m in ms]
        now = [x for x in now if x is not None]
        prev = [v(m, "rev_ttm_growth_prev_pct") for m in ms]
        prev = [x for x in prev if x is not None]
        d = {}
        if len(cg) >= 5:
            d.update({"n": len(cg), "median_cagr": float(np.median(cg)), "share_below": sum(1 for x in cg if x < 0) / len(cg)})
        if len(now) >= 5:
            med, medp = float(np.median(now)), (float(np.median(prev)) if len(prev) >= 5 else None)
            br = sum(1 for x in now if x > 10) / len(now) * 100
            acc = medp is not None and med > medp
            slowing = medp is not None and med < medp
            wind = ("Tailwind" if med >= 12 and acc and br >= 50 else "Headwind" if med < 3 or (br < 25 and slowing) else "Neutral")
            d["wind"] = {"wind": wind, "median": med, "median_prev": medp if medp is not None else med, "breadth": br, "n": len(now)}
        out[ind] = d
    return out


def peer_medians(rows):
    """rows: [(sym, industry, btype, mkey, value)]. Median per (type, industry) with >=5, else per (metric, industry)."""
    a, b = {}, {}
    for sym, ind, bt, mk, x in rows:
        if x is None or x <= 0 or not isinstance(ind, str):
            continue
        a.setdefault((bt, ind), []).append((sym, x))
        b.setdefault((mk, ind), []).append((sym, x))
    res = {}
    for sym, ind, bt, mk, x in rows:
        grp = [y for s, y in a.get((bt, ind), []) if s != sym]
        scope = f"{bt.lower()} peers in {ind}"
        if len(grp) < 5:
            grp = [y for s, y in b.get((mk, ind), []) if s != sym]
            scope = f"{ind}"
        if len(grp) >= 5:
            res[sym] = {"median": float(np.median(grp)), "n": len(grp), "scope": scope}
    return res


def compact(L):
    """Slim per-level summary for the list file (full rubric goes to the per-stock file)."""
    return {k: {kk: x for kk, x in (("t", L[k]["t"]), ("n", L[k]["name"]), ("s", L[k]["s"]), ("w", L[k]["why"]),
                                    ("out", L[k].get("out")), ("turn", L[k].get("turn")), ("ext", L[k].get("extended"))) if x is not None}
            for k in LEVELS}


def not_rated_reason(L: dict, vd: str | None, th: dict | None, qpos: int | None = None, qlen: int | None = None,
                     rank: int | None = None, n: int | None = None, requested: bool = False) -> str:
    """Why a stock is Not rated, told apart (the decision label stays "Not rated"): too little filed data to score it,
    not researched yet (today's queue position, or not queued), or researched with no verified forward driver found."""
    if vd == "Not enough data":
        grey = [k for k in LEVELS if L[k]["t"] == 0 and not (k == "out" and not L["out"].get("researched"))]
        gaps = []
        for k in grey:
            for i in L[k]["items"]:
                note = str(i.get("note") or "")
                if i["m"] is None and note != PENDING and "research" not in note:
                    f = FACT.get(i["id"], i["n"].lower())
                    if f not in gaps:
                        gaps.append(f)
        return (f"Not enough filed data: {', '.join(SHORT[k] + (' (price history)' if k == 'mom' else '') for k in grey)} cannot be scored"
                + (f" (missing {', '.join(gaps[:6])})" if gaps else ""))
    if th:
        d = max((str(x)[:10] for x in (th.get("updated"), (th.get("scan") or {}).get("date"), (th.get("scan_raw") or {}).get("date")) if x),
                default=None)
        return (f"Researched{f' ({d})' if d else ''}: no verified forward driver found (guidance, order book or dated promise)"
                + (f"; back in today's queue at position {qpos} of {qlen}" if qpos else ""))
    if qpos:
        return f"Not researched yet: today's research queue position {qpos} of {qlen}"
    if requested:
        return "Not researched yet: requested, waiting for research"
    return "Not researched yet: not in today's research queue" + (f" (readiness rank {rank} of {n})" if rank and n else "")


def clean(o):
    """Drop None values recursively and make floats JSON-safe."""
    if isinstance(o, dict):
        return {k: clean(x) for k, x in o.items() if x is not None}
    if isinstance(o, list):
        return [clean(x) for x in o]
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 3)
    if isinstance(o, (np.floating,)):
        return clean(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, date):
        return str(o)
    return o


# ------------------------------------------------------------------ Decision view (rule-built, every reason shown)
SHORT = {"surv": "Stability", "qual": "Quality", "val": "Valuation", "mgmt": "Management", "mom": "Momentum", "disc": "Discovery", "out": "Outlook"}
DECISIONS = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell", "Not rated"]
# Plain words for the app (owner, 28 Nov 2026: "don't state A5 / R8 on the app anywhere, state the actual thing: how will a
# user know our internal rules"): every reason a person reads goes through plain() before it is published
FLAG_NAMES = {"A1": "negative equity", "A2": "loan default", "A3": "audit qualification", "A4": "insolvency",
              "A5": "rating downgrade", "A6": "trading suspension", "G1": "regulator or exchange order", "G2": "search or fraud probe",
              "G3": "auditor resignation", "G4": "CEO and CFO exits", "G5": "promoter stake cut", "G6": "loans to the promoter group",
              "G7": "fund use deviation"}
_RULES = re.compile(r"\s*\((?:see )?RULES\.md[^)]*\)|\s*RULES\.md(?:\s+[RCT]\d+(?:\s*(?:,|and|/)\s*[RCT]\d+)*)?")
_RCODE = re.compile(r"(^|: |; )R[1-8] (?=[a-z])")
_TCODE = re.compile(r"\bT\d{1,2} (?=[A-Z])")
_FLAG = re.compile(r"\b([AG][1-7])\b")


def plain(text):
    """A published reason in plain words: no rule ids (R1-R8, T2-T15, L1-L7), no flag codes (A5 -> rating downgrade),
    no "RULES.md" references. Rating grades such as "Crisil A2" are left alone (flag codes are only read in flag lines)."""
    if not isinstance(text, str):
        return text
    t = _RULES.sub("", text)
    t = t.replace("R1 and R2 not applied", "Cash and other-income checks not applied")
    t = _RCODE.sub(lambda m: m.group(1), t)
    t = _TCODE.sub("", t)
    t = re.sub(r"Removed at L\d ", "Removed at ", t)
    if "flag" in t.lower():
        t = _FLAG.sub(lambda m: FLAG_NAMES.get(m.group(1), m.group(1)), t)
    t = re.sub(r"\s+([,.:;])", r"\1", t).replace("()", "").strip()
    return t[:1].upper() + t[1:] if t else t


def plain_decision(d: dict | None) -> dict | None:
    """plain() on every line of a decision a person reads (why, missing, incomplete)."""
    if not isinstance(d, dict):
        return d
    return d | {k: [plain(x) for x in d[k]] for k in ("why", "missing", "incomplete") if isinstance(d.get(k), list)}


BAD_NEWS_DAYS = 30  # a red filing this recent and newer than the last research holds a Buy until it is read
SERIOUS_FLAGS = ("A2", "A4", "G2")   # unreviewed default / insolvency / fraud-search flags block any buy
OTHER_FLAGS = ("A5", "G1", "G3", "G4")


def _promise_stats(th: dict) -> dict:
    ps = th.get("promises") or []
    ups = [u for p in ps for u in p.get("updates") or []]
    return {"missed": sum(1 for p in ps if p.get("status") == "missed"),
            "raised": any(p.get("status") == "raised" for p in ps) or any(u.get("type") == "raised" for u in ups),
            "cut": any(u.get("type") == "lowered" for u in ups),
            "open": sum(1 for p in ps if p.get("status") == "pending" and p.get("quote"))}


def decision_v1(L: dict, out_l, th: dict | None, scan: dict | None, setup: dict | None, price, ann: dict | None,
             research_flags: dict | None = None) -> dict:
    """Strong Buy / Buy / Hold / Sell / Strong Sell, or Not rated when no verified forward driver exists yet.
    Inputs are filed numbers, computed levels and quote-verified research only. Returns label, reasons, missing."""
    th = th or {}
    t = {k: L[k]["t"] for k in LEVELS}
    missing = []
    ps = _promise_stats(th)
    cred = (th.get("credibility") or {})
    cred_pct = cred.get("pct") if (cred.get("due") or 0) >= 2 else None
    raw = th.get("scan_raw") or {}
    guidance, order_book = raw.get("guidance"), raw.get("order_book")
    drivers = th.get("drivers") or []
    driver = bool(guidance or order_book or ps["open"] or drivers)
    resolved = th.get("resolved") or {}
    kill_hit = [k for k, v in resolved.items() if k.startswith("kill_switch") and str(v.get("status", "")).lower() in ("hit", "triggered", "missed")]
    reviewed = research_flags or th.get("flag_reviews") or {}
    confirmed = [k for k, v in reviewed.items() if (v or {}).get("verdict") == "confirmed"]
    watch = {k for k, v in (ann or {}).items() if v and v[0] == 1 and (reviewed.get(k) or {}).get("verdict") != "dismissed"}
    sc = {c["name"]: c["price"] for c in (scan or {}).get("scenarios") or []}
    live_setup = (setup or {}).get("type") in ("Breakout", "Pullback", "Base")
    extended = bool(L["mom"].get("extended"))

    def lab(k):
        return f"{SHORT[k]}: {L[k]['name']}"

    # ---- Strong Sell
    ss = []
    if out_l and out_l[0] == 1:
        ss.append(f"Removed at Stability: {out_l[1]}")
    ss += [f"Red flag confirmed after reading the filing ({k})" for k in confirmed]
    ss += [f"Kill switch hit ({k.split('-', 2)[-1] if '-' in k else k})" for k in kill_hit]
    if ss:
        return {"d": "Strong Sell", "why": ss, "missing": []}
    # ---- Sell
    s_ = []
    if out_l:
        s_.append(f"Removed at L{out_l[0]} {SHORT[LEVELS[out_l[0] - 1]]}: {out_l[1]}")
    if ps["cut"]:
        s_.append("Management lowered guidance")
    if ps["missed"] >= 2:
        s_.append(f"{ps['missed']} promises missed")
    if price and sc.get("Bull") and price > sc["Bull"]:
        s_.append(f"Price ₹{price:,.0f} is above the bull case ₹{sc['Bull']:,.0f}")
    if s_:
        return {"d": "Sell", "why": s_, "missing": []}
    # ---- evidence needed for any buy / hold call
    if not driver:
        missing.append("No verified forward driver yet (guidance, order book or dated promise): queued for research")
    if t["mgmt"] == 0:
        missing.append("Management conviction not verified yet")
    blockers = [f"Unreviewed red flag: {k}" for k in SERIOUS_FLAGS if k in watch]
    soft = [f"Unreviewed flag: {k}" for k in OTHER_FLAGS if k in watch]
    if not driver:
        return {"d": "Not rated", "why": [lab(k) for k in ("qual", "val") if t[k]], "missing": missing + blockers}

    good = lambda k, hi: t[k] != 0 and t[k] <= hi
    base_ok = "Base" not in sc or (price is not None and price <= sc["Base"])
    pos = []
    if guidance:
        pos.append(f"Guidance quoted: {guidance.get('metric', '')} {guidance.get('low', '')}–{guidance.get('high', '')} {guidance.get('unit', '')} {guidance.get('fy', '')}".strip())
    if order_book:
        pos.append(f"Order book quoted: ₹{order_book.get('value_cr', 0):,} cr")
    if ps["open"]:
        pos.append(f"{ps['open']} dated promise(s) quoted, open")
    pos += [f"{(d.get('kind') or 'driver').capitalize()}: {d.get('text')}" for d in drivers[:3]]
    if ps["raised"]:
        pos.append("Guidance raised")
    if cred_pct is not None:
        pos.append(f"Promises kept {cred_pct}%")
    if "Base" in sc and price:
        pos.append(f"Price ₹{price:,.0f} vs base case ₹{sc['Base']:,.0f}")
    # ---- Strong Buy
    if (good("qual", 2) and good("surv", 2) and good("mgmt", 2) and good("val", 2) and (ps["raised"] or (cred_pct or 0) >= 75)
            and base_ok and live_setup and not extended and not blockers and not soft):
        return {"d": "Strong Buy", "why": [lab(k) for k in ("surv", "qual", "mgmt", "val")] + pos + [f"Entry setup: {setup['type']}"], "missing": missing}
    # ---- Buy
    if good("qual", 3) and good("surv", 3) and good("mgmt", 3) and good("val", 3) and base_ok and not blockers:
        extra = [] if live_setup else ["No entry setup yet: wait for a breakout, pullback or base"]
        return {"d": "Buy", "why": [lab(k) for k in ("surv", "qual", "mgmt", "val")] + pos + extra + soft, "missing": missing}
    # ---- Hold
    hold = [lab(k) for k in ("qual", "val", "mgmt") if t[k]] + pos
    if not base_ok:
        hold.append("Price above the base case")
    if extended:
        hold.append("Price extended")
    return {"d": "Hold", "why": hold + blockers + soft, "missing": missing}


# ------------------------------------------------------------------ decision v2 (PLAN.md section 16)
# Indian prices follow the expected future: forward direction leads, the price trend confirms,
# a weak track record raises the margin of safety instead of forcing Sell, integrity is judged apart from forecasting.
import re as _re
from datetime import date as _date

_METRIC = [("profit", r"\b(pat|profit|eps|earnings|bottom.?line)\b"), ("margin", r"margin"),
           ("revenue", r"\b(revenue|sales|top.?line|turnover|income from operations|growth of \d)"),
           ("order", r"\border"), ("capacity", r"capacity|plant|capex|commission|rig|barge|line|unit")]
_INTEG_RF = _re.compile(r"related.part|promoter.group|group (?:company|companies|entit)|inter.?corporate|loans? (?:given )?to (?:a |the )?(?:promoter|group|related)|corporate guarantee", _re.I)
_ASSURE = _re.compile(r"\bno (?:provision|provisioning|write.?off|impairment|dilution|pledge)|not (?:expecting|expect) any (?:such )?(?:provision|write.?off)", _re.I)
MOS = [(75, 0.90), (50, 0.75), (35, 0.60)]  # credibility % -> buy only if price <= ratio x Base
MOS_UNKNOWN = 0.80


def promise_metric(p: dict) -> str:
    """Rule-based class of a quoted promise (revenue / profit / margin / order / capacity / other)."""
    t = f"{p.get('promise', '')} {p.get('quote', '')}".lower()
    if p.get("metric"):
        return p["metric"]
    for m, rx in _METRIC:
        if _re.search(rx, t):
            return m
    return "other"


def _days(d, today):
    try:
        return (today - _date.fromisoformat(str(d)[:10])).days
    except Exception:  # noqa: BLE001
        return 9999


def credibility_w(th: dict, today) -> dict | None:
    """Weighted: revenue/profit promises 1.0, others 0.5; outcomes in the last 365 days 1.0, older 0.5."""
    pts = wsum = 0.0
    n = 0
    for p in th.get("promises") or []:
        st = p.get("status")
        if st not in ("delivered", "beat", "partly", "missed", "delayed"):
            continue
        last = ((p.get("updates") or [{}])[-1] or {}).get("date") or p.get("made_on")
        w = (1.0 if promise_metric(p) in ("revenue", "profit") else 0.5) * (1.0 if _days(last, today) <= 365 else 0.5)
        pts += w * (1 if st in ("delivered", "beat") else 0.5 if st in ("partly", "delayed") else 0)
        wsum += w
        n += 1
    return {"pct": round(pts / wsum * 100), "due": n} if n >= 2 and wsum else None


def _guidance_moves(th: dict, today, window=180):
    """Revenue/profit guidance raised or cut in the last `window` days; a cut and a raise within 45 days net out."""
    ups, cuts, reaff = [], [], []
    for p in th.get("promises") or []:
        if promise_metric(p) not in ("revenue", "profit"):
            continue
        for u in p.get("updates") or []:
            if _days(u.get("date"), today) > window:
                continue
            (ups if u.get("type") == "raised" else cuts if u.get("type") == "lowered" else reaff if u.get("type") == "reaffirmed" else []).append((u.get("date"), p))
        if p.get("status") == "raised" and not any(x[1] is p for x in ups):
            ups.append((p.get("made_on"), p))
    net_cuts = [c for c in cuts if not any(abs(_days(c[0], today) - _days(r[0], today)) <= 45 for r in ups)]
    return ups, net_cuts, reaff


def integrity_items(th: dict) -> list[dict]:
    """Open integrity questions from verified research (related-party lending, broken assurances).
    Research can close one with integrity: {id: {"status": "resolved"|"confirmed", ...}}."""
    rv = th.get("integrity") or {}
    out = []
    for i, f in enumerate(th.get("red_flags") or []):
        if _INTEG_RF.search(f"{f.get('text', '')} {f.get('quote', '')}"):
            out.append({"id": f"rf{i}", "type": "related party", "text": f.get("text", ""), "source": f.get("source")})
    for p in th.get("promises") or []:
        t = f"{p.get('promise', '')} {p.get('quote', '')}"
        if p.get("status") == "missed" and _ASSURE.search(t):
            out.append({"id": p.get("id"), "type": "broken assurance", "text": p.get("promise", ""), "source": p.get("source")})
        elif _INTEG_RF.search(t) and p.get("status") in ("pending", "unverified", "delayed", "missed", "off_track"):
            out.append({"id": p.get("id"), "type": "related party", "text": p.get("promise", ""), "source": p.get("source")})
    for x in out:
        x["status"] = ((rv.get(x["id"]) or {}).get("status")) or "open"
    return out


def strength_driver(rs: float) -> dict:
    """The strength waiver's forward driver (RULES.md ladder step 3; owner, 25 Nov 2026): a scored stock with no other driver
    whose relative strength is in the top third (rs_pct_of >= R4_RS_MIN). Not dated: it never counts as a dated trigger
    (conviction C1, MB, R4's first leg); R4 passes on the same relative strength (its second leg)."""
    return {"kind": "signal", "text": f"Price strength: relative strength in the top third ({rs * 100:.0f}th percentile)"}


def code_triggers(L: dict) -> list[dict]:
    """Live code triggers on the Outlook tab (T1-T15), except T4 (work in progress alone is not a forward driver)."""
    return [x for x in ((L.get("out") or {}).get("triggers") or []) if x.get("id") != "T4"]


def decision(L: dict, out_l, th: dict | None, scan: dict | None, setup: dict | None, price, ann: dict | None,
             research_flags: dict | None = None, today=None, filed: str | None = None, scored: bool = True,
             call_since: str | None = None, bad_news: list | None = None) -> dict:
    """scored=False: too little filed data to score the stock ("Not enough data"); with no driver it stays Not rated."""
    today = today or _date.today()
    th = th or {}
    t = {k: L[k]["t"] for k in LEVELS}
    raw = th.get("scan_raw") or {}
    guidance, order_book = raw.get("guidance"), raw.get("order_book")
    drivers = th.get("drivers") or []
    ps = _promise_stats(th)
    driver = bool(guidance or order_book or ps["open"] or drivers)
    signals = code_triggers(L)
    if not driver and signals:  # owner, 24 Nov 2026 (idea 1): a live code trigger counts as the forward driver
        drivers = [{"kind": "signal", "text": f"{x['id']} {x.get('n') or ''}".strip()} for x in signals]
        driver = True
    strength_only = False
    rs = rs_pct_of(L)
    if not driver and scored and rs is not None and rs >= R4_RS_MIN:  # owner, 25 Nov 2026: strength waiver (RULES.md step 3)
        drivers = [strength_driver(rs)]
        driver = strength_only = True
    cred = credibility_w(th, today)
    cp = cred["pct"] if cred else None
    ups, cuts, reaff = _guidance_moves(th, today)
    obr = L["out"].get("ob_ratio")
    story = (th.get("story") or {}).get("status")
    integ = integrity_items(th)
    i_conf = [x for x in integ if x["status"] == "confirmed"]
    i_open = [x for x in integ if x["status"] == "open"]
    reviewed = research_flags or th.get("flag_reviews") or {}
    confirmed = [k for k, v in reviewed.items() if (v or {}).get("verdict") == "confirmed"]
    watch = {k for k, v in (ann or {}).items() if v and v[0] == 1 and (reviewed.get(k) or {}).get("verdict") != "dismissed"}
    resolved = th.get("resolved") or {}
    kill_hit = [k for k, v in resolved.items() if k.startswith("kill_switch") and str(v.get("status", "")).lower() in ("hit", "triggered", "missed")]
    sc = {c["name"]: c["price"] for c in (scan or {}).get("scenarios") or []}
    stage = next((i.get("v") for i in L["mom"]["items"] if i["id"] == "P1"), None)
    live_setup = (setup or {}).get("type") in ("Breakout", "Pullback", "Base")
    extended = bool(L["mom"].get("extended"))
    lab = lambda k: f"{SHORT[k]}: {L[k]['name']}"
    good = lambda k, hi: t[k] != 0 and t[k] <= hi
    info = {"credibility_w": cp, "ob_ratio": obr, "integrity": integ or None, "stage": stage, "call_since": call_since}

    def res(d, why, missing=()):
        return plain_decision({"d": d, "why": why, "missing": list(missing), **{k: v for k, v in info.items() if v is not None}})

    # 2 Strong Sell
    ss = []
    if out_l and out_l[0] == 1:
        ss.append(f"Removed at Stability: {out_l[1]}")
    ss += [f"Red flag confirmed after reading the filing: {FLAG_NAMES.get(k, k)}"
           + (f" · {str((reviewed.get(k) or {}).get('note') or '').rstrip('.')}" if (reviewed.get(k) or {}).get("note") else "") for k in confirmed]
    ss += [f"Integrity confirmed: {x['text']}" for x in i_conf]
    ss += [f"Kill switch hit ({k.split('-', 2)[-1] if '-' in k else k})" for k in kill_hit]
    if ss:
        return res("Strong Sell", ss)
    # 3 Sell: story broken, core guidance cut, breakdown, above bull, removed at L2-L4
    if out_l:  # removals come from filed numbers: no research needed
        return res("Sell", [f"Removed at L{out_l[0]} {SHORT[LEVELS[out_l[0] - 1]]}: {out_l[1]}"])
    # RULES.md ladder: every Sell reason comes before Not rated (a broken story or a guidance cut is a Sell even when no
    # forward driver is verified); "story weakening in a downtrend" is the price stage, not also momentum tier 5
    s_ = []
    if story == "broken":
        s_.append(f"Story broken: {(th.get('story') or {}).get('text', '')}".strip(": "))
    s_ += [f"{promise_metric(p).capitalize()} guidance cut ({d}): {p.get('promise', '')}" for d, p in cuts[:2]]
    if price and sc.get("Bull") and price > sc["Bull"]:
        s_.append(f"Price ₹{price:,.0f} is above the bull case ₹{sc['Bull']:,.0f}")
    if stage == "Downtrend" and story == "weakening":
        s_.append("Story weakening and price in a downtrend")
    if s_:
        return res("Sell", s_)
    # 1 Not rated (research-based rules below need a verified forward driver)
    if not driver:
        if scored:  # owner, 24 Nov 2026 (idea 2): scored, nothing removed it, no trigger of any kind -> Hold
            return res("Hold", ["No trigger yet: no forward driver, no live code trigger and relative strength below the top third"] + [lab(k) for k in ("surv", "qual", "val", "mom") if t[k]],
                       ["No verified forward driver yet (guidance, order book or dated promise): queued for research"])
        return res("Not rated", [lab(k) for k in ("qual", "val") if t[k]],
                   ["No verified forward driver yet (guidance, order book or dated promise): queued for research"])
    # positives
    fwd_strong = bool(ups) or (obr or 0) >= 2
    rising = stage in ("Stage 2", "Stage 1→2")  # the market already agrees with the story
    # the strength waiver's driver alone counts as a positive direction (the replay variant that justified it passed both
    # the driver and the forward-direction check when relative strength was top third)
    fwd_pos = (fwd_strong or bool(reaff) or (obr or 0) >= 1.5 or len(drivers) >= 2 or bool(guidance)
               or (len(drivers) == 1 and rising) or strength_only
               or (rs is not None and rs >= R4_RS_MIN))  # strength waiver: top-third strength is a positive direction (as replayed)
    pos = []
    pos += [f"{promise_metric(p).capitalize()} guidance raised ({d}): {p.get('promise', '')}" for d, p in ups[:2]]
    if reaff and not ups:
        pos.append(f"Guidance reaffirmed ({reaff[0][0]}): {reaff[0][1].get('promise', '')}")
    if obr:
        pos.append(f"Order book {obr:.2f}× revenue (quoted)")
    if guidance:
        pos.append(f"Guidance quoted: {guidance.get('metric', '')} {guidance.get('low', '')}–{guidance.get('high', '')} {guidance.get('unit', '')} {guidance.get('fy', '')}".strip())
    pos += [f"{(d.get('kind') or 'driver').capitalize()}: {d.get('text')}" for d in drivers[:3]]
    if cp is not None:
        pos.append(f"Promises kept {cp}% (weighted, {cred['due']} with an outcome)")
    # margin of safety
    need = MOS_UNKNOWN if cp is None else next((r for lo, r in MOS if cp >= lo), None)
    if "Base" in sc and price:
        ratio = price / sc["Base"]
        mos_ok = need is not None and ratio <= need
        mos_txt = f"Price ₹{price:,.0f} = {ratio:.2f}× base case ₹{sc['Base']:,.0f}" + (f" (needs ≤ {need:.2f}× at this credibility)" if need else " (credibility below 35%: no buy)")
    else:
        mos_ok = need is not None and (t["val"] in (1, 2) or (t["val"] == 3 and (cp is None or cp >= 50)))
        mos_txt = f"No price scenarios yet; valuation {L['val']['name']}" + ("" if need else " (credibility below 35%: no buy)")
    pos.append(mos_txt)
    # 4 Hold: integrity open or unreviewed serious flag
    blockers = [f"Integrity check open ({x['type']}): {x['text']}" for x in i_open]
    blockers += [f"Unreviewed red flag: {k}" for k in SERIOUS_FLAGS if k in watch]
    # owner, 28 Nov 2026: a red filing of the last BAD_NEWS_DAYS days not yet read by Claude holds any Buy (the call stays
    # open); Claude's recheck confirms it (a Sell: red flag, kill switch, story broken, guidance cut) or clears it
    news = [f"Unreviewed bad news filed {e.get('date')}: {e.get('type')}: {str(e.get('text') or '')[:90]}" for e in bad_news or []]
    if blockers or news:
        head = "Integrity open: no buy until research confirms or clears it" if blockers else \
            "Bad news filed since the last research: no buy until Narrativ.ai confirms or clears it"
        return res("Hold", [head] + blockers + news + pos,
                   ["Research to verify each open integrity item against later filings"] if blockers else
                   ["Narrativ.ai to read the filing: confirm it (Sell) or clear it (rules decide again)"])
    soft = [f"Unreviewed flag: {k}" for k in OTHER_FLAGS if k in watch]
    trend_ok = stage not in ("Downtrend", None)
    ver = verification(th.get("audit"), filed, today, call_since)
    info["verified"] = ver["state"]

    def gated(label, why_):
        """Buy / Strong Buy only stand once Claude's independent audit passed; caution or fail -> Hold."""
        if ver["state"] in ("caution", "fail"):
            return res("Hold", [f"Independent audit ({ver.get('date')}): {ver['state']}" + (f" · {ver.get('summary')}" if ver.get("summary") else "")]
                       + [f"Audit issue: {x}" for x in ver.get("issues") or []] + why_)
        if ver["state"] == "pass":
            return res(label, why_ + [f"Verified by Narrativ.ai's full review on {ver['date']}"])
        # not verified yet: shown as Hold (candidate), never as Buy, so a Buy in the app always means verified
        r = res("Hold", [f"Rules say {label}: waiting for Narrativ.ai's full review"] + why_,
                ["Verification pending: queued for Narrativ.ai's full review" + (f" ({ver['why']})" if ver.get("why") else "")])
        r["candidate"] = label
        return r

    # 5 Strong Buy
    if (good("surv", 2) and good("qual", 2) and fwd_strong and story != "weakening" and (cp is None or cp >= 60) and mos_ok
            and t["mom"] in (1, 2) and live_setup and not extended and not soft):
        return gated("Strong Buy", [lab(k) for k in ("surv", "qual", "mom")] + pos + [f"Entry setup: {setup['type']}"])
    # 6 Buy
    if good("surv", 3) and good("qual", 3) and fwd_pos and mos_ok and trend_ok:
        extra = [] if live_setup else ["No entry setup yet: wait for a breakout, pullback or base"]
        return gated("Buy", [lab(k) for k in ("surv", "qual", "mom")] + pos + extra + soft)
    # 7 Hold
    hold = [lab(k) for k in ("surv", "qual", "val", "mom") if t[k]] + pos
    if not fwd_pos:
        hold.append("Forward direction not yet positive (needs a raise, reaffirmation, order book ≥ 1.5×, 2 drivers, or 1 driver with a rising price)")
    if not mos_ok:
        hold.append("Price does not leave the margin of safety this track record needs")
    if not trend_ok:
        hold.append(f"Price trend: {stage or 'unknown'}")
    if extended:
        hold.append("Price extended")
    return res("Hold", hold + soft)


# ------------------------------------------------------------------ data consistency checks (layer 2) and Claude verification gate
AUDIT_DAYS = 30
# the app shows "Narrativ.ai" for the reviewer (owner, 25 Nov 2026); decisions stored before then say "Claude": match both
VERIFIED_BY = ("Verified by Claude", "Verified by Narrativ.ai")


def audit_flag_items(Mx: dict, lender: bool) -> list[tuple[str, str]]:
    """Numbers that cannot all be true together, as (stable id, text); handed to Claude's audit and shown in the app.
    The id is what the audit's `flag_notes[].flag` names (RULES.md R7: every consistency flag explained)."""
    if lender:
        return []
    f = []
    fin = inp(Mx, "interest_cover", "finance_cost_cr")
    borr, lease = inp(Mx, "de", "borrowings_cr"), inp(Mx, "de", "lease_liabilities_cr")
    debt = (borr or 0) + (lease or 0)
    rev = v(Mx, "revenue_ttm_cr")
    if fin and rev and fin > 0.01 * rev and (debt <= 0 or fin / debt > 0.20):
        f.append(("finance_cost", f"Finance cost ₹{fin:,.0f} cr a year against debt ₹{debt:,.0f} cr: debt or leases may be missing"))
    roce, roe = v(Mx, "roce_pct"), v(Mx, "roe_pct")
    if roce and roe and roce > 25 and roce > 2 * max(roe, 1):
        f.append(("roce_vs_roe", f"ROCE {roce:.0f}% is more than twice ROE {roe:.0f}%: check capital employed"))
    eve, pe = v(Mx, "ev_ebitda"), v(Mx, "pe")
    if (eve is not None and 0 < eve < 5) or (pe is not None and 0 < pe < 6):
        f.append(("cheap", "Valuation looks unusually cheap (EV/EBITDA < 5 or P/E < 6): check for one-offs or missing liabilities"))
    py = v(Mx, "pat_yoy_pct")
    if py is not None and py > 50:
        f.append(("profit_jump", f"Quarter profit up {py:.0f}% year on year: check for one-offs"))
    if Mx.get("leases_known") is False:
        f.append(("leases_missing", "Lease payments filed but no lease liability line in the balance sheet: debt may be understated (check leases)"))
    return f


def audit_flags(Mx: dict, lender: bool) -> list[str]:
    return [t for _, t in audit_flag_items(Mx, lender)]


def _ist_today() -> str:
    from datetime import datetime, timedelta, timezone
    return str((datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date())


def verification(audit: dict | None, filed: str | None, today, call_since: str | None = None, now=None) -> dict:
    """State of Claude's independent audit: pass / caution / fail / pending (none, stale, dated in the future, results filed
    after it, or the research it judged changed since: `changed_after`, set by mark_changed from the audit stamps)."""
    if not audit or not audit.get("verdict"):
        return {"state": "pending", "why": "Not yet verified by an independent audit"}
    d = str(audit.get("date") or "")
    # `today` is the data date (last trading day); Claude dates a review by the calendar (IST), which runs ahead on the day
    # after a trading day, at weekends and on holidays: only a date after the calendar day is a future date (24 Nov 2026)
    clock = max(str(today)[:10], str(now or _ist_today())[:10])
    if d[:10] > clock:  # a future date would never go stale
        return {"state": "pending", "why": f"Audit dated {d}, after today: not valid"}
    if _days(d, today) > AUDIT_DAYS or (filed and filed > d):
        return {"state": "pending", "why": f"Audit of {d} is out of date" + (" (new results filed)" if filed and filed > d else "")}
    if audit.get("changed_after"):
        return {"state": "pending", "why": f"Research changed after the audit of {d} ({', '.join(audit['changed_after'])}): needs a fresh review"}
    if call_since and call_since > d[:10]:  # owner, 24 Nov 2026: the review must have seen the latest earnings call
        return {"state": "pending", "why": f"The latest earnings call was available from {call_since}, after the audit of {d}: needs a fresh review"}
    return {"state": audit["verdict"], "date": d, "summary": audit.get("summary"), "issues": [i.get("text") for i in audit.get("issues") or []][:5]}


# ---------- re-audit trigger: the research an audit judged must not change after it without a new review
AUDITED = ("drivers", "scan", "story", "integrity", "other_income_recurring")


def _canon(o):
    if isinstance(o, dict):  # dates of saying / scanning are not content: a re-scan that changes nothing is not a change; a
        # driver's `target` (forward ledger, 27 Nov 2026) only labels the audited quote and is checked against it by the verifier
        return {k: _canon(x) for k, x in sorted(o.items()) if k not in ("date", "updated", "target")}
    if isinstance(o, list):
        return [_canon(x) for x in o]
    return o


def _hash(o, canon=True) -> str:
    import hashlib
    import json
    return hashlib.sha1(json.dumps(_canon(o) if canon else o, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def stamp_audits(raw: dict, stamps: dict, today, syms=None) -> dict[str, list[str]]:
    """`raw`: theses.json as Claude wrote it. The first time a review is seen, record a content hash of each audited field
    (AUDITED) with it in `stamps` (docs/data/audit_stamps.json); later, any audited field whose hash differs means the
    research changed after the review. -> {symbol: changed fields}.

    The same review (same date) whose record was edited keeps its original stamp, so an edit to the audit object cannot
    re-baseline research changed after it. A stamp marked `edited_after` (stamps first taken on 20-23 Nov 2026 for reviews
    written earlier, when a later `updated` date was taken as a change) stays pending until `repair_stamps` compares the
    fields with the version the review judged, or the review is redone. A bare `updated` date is not a change: on 23 Nov
    rechecks that changed nothing reset 10 passed reviews that way."""
    out = {}
    for s in (raw if syms is None else syms):
        th = raw.get(s) or {}
        au = th.get("audit")
        if not isinstance(au, dict) or not au:
            stamps.pop(s, None)
            continue
        aid, cur = _hash(au, canon=False), {k: _hash(th.get(k)) for k in AUDITED}
        st = stamps.get(s)
        d = str(au.get("date") or "")[:10]
        if not st or st.get("audit") != aid:
            if st and st.get("audit_date") == d and st.get("fields"):
                st = stamps[s] = {**st, "audit": aid}  # same review, record edited: still judged against what it reviewed
            else:
                st = stamps[s] = {"audit": aid, "audit_date": d, "fields": cur, "stamped": str(today)[:10]}
        ch = [k for k in AUDITED if (st.get("fields") or {}).get(k) != cur[k]]
        if st.get("edited_after") and not ch:
            ch = [f"edited {st['edited_after']}"]
        if ch:
            out[s] = ch
    return out


def repair_stamps(stamps: dict, version_at) -> dict[str, str]:
    """One-off: for each stamp marked `edited_after`, compare the audited fields with the thesis as it was when the review was
    written (`version_at(symbol, audit_date)` -> that thesis or None) and replace the guess with the real baseline.
    -> {symbol: "cleared" | "changed: <fields>" | "kept (no history)"}."""
    out = {}
    for s, st in stamps.items():
        if not st.get("edited_after"):
            continue
        old = version_at(s, st.get("audit_date"))
        if not old:
            out[s] = "kept (no history)"
            continue
        st["fields"] = {k: _hash(old.get(k)) for k in AUDITED}
        st.pop("edited_after", None)
        st["repaired"] = True
        out[s] = "baseline from history"
    return out


def mark_changed(verified: dict, changed: dict) -> None:
    """Put the changed fields on the verified audit, where verification() reads them."""
    for s, ch in changed.items():
        au = (verified.get(s) or {}).get("audit")
        if isinstance(au, dict):
            au["changed_after"] = ch


# ---------- RULES.md R7 in code: what a passing review must have recorded (missing -> verification pending, not fail)
BSE_NOT_EVALUATED = ["institutions selling", "promoter buying", "mutual funds entering"]  # shown in the app: plain words
_LEASE = re.compile(r"lease", re.I)
_DEBT = re.compile(r"borrow|debt", re.I)


def _debt_checked(checks) -> bool:
    items = [str(c.get("item") or "") for c in checks or [] if isinstance(c, dict)]
    if any((c or {}).get("rule") == "debt_leases" for c in checks or [] if isinstance(c, dict)):
        return True
    return any(_LEASE.search(i) for i in items) and any(_DEBT.search(i) for i in items)


def r7_missing(audit: dict | None, Mx: dict, lender, L: dict | None) -> list[str]:
    """What the (verified) audit still lacks: a debt-including-leases check (non-lenders), the related-party item (share
    of turnover quoted, or 'not disclosed' with the source read), a note for each consistency flag present, and for a
    BSE-only stock a note on the checks code could not run. [] when complete."""
    au, miss = audit or {}, []
    if not lender and not _debt_checked(au.get("checks")):
        miss.append("R7 total debt including lease liabilities not checked (audit check with rule 'debt_leases')")
    if (au.get("related_party") or {}).get("status") not in ("quoted", "not disclosed"):
        miss.append("R7 related-party purchases and sales as % of turnover not recorded (audit.related_party: quoted, or 'not disclosed' with its source)")
    have = {str((x or {}).get("flag")) for x in au.get("flag_notes") or []}
    for fid, txt in audit_flag_items(Mx or {}, lender):
        if fid not in have and txt not in have:
            miss.append(f"R7 consistency flag not explained ({fid}): {txt}")
    ne = ((L or {}).get("out") or {}).get("not_evaluated")
    if ne and not au.get("bse_only_note"):
        miss.append(f"BSE-only: {', '.join(ne)} not evaluated by code; the review must say what it checked instead (audit.bse_only_note)")
    return miss


def research_missing(th: dict | None) -> list[str]:
    """RULES.md R8 (owner, 27 Nov 2026: "verified Buys should be full stories scanned properly by Claude, no loopholes"):
    what Claude's research still lacks before a passed review counts as a verification. [] when complete. A full review
    alone left 21 of 26 verified Buys without an outlook scan, a story check or a dated driver (27 Nov 2026)."""
    th = th or {}
    miss = []
    sc = th.get("scan_raw") or th.get("scan") or {}
    if not sc:
        miss.append("R8 no outlook scan (guidance, order book, must-go-right items, kill switches, bull / base / bear)")
    else:
        if not sc.get("must_go_right"):
            miss.append("R8 scan has no must-go-right item")
        if not sc.get("kill_switches"):
            miss.append("R8 scan has no kill switch")
        th_ = sc.get("theories") or {}
        if not all(th_.get(k) for k in ("bull", "base", "bear")):
            miss.append("R8 scan has no bull / base / bear case")
    if not any(d.get("due_verified") for d in th.get("drivers") or []):
        miss.append("R8 no dated driver with a verified due date")
    st = th.get("story") or {}
    if not st.get("status"):
        miss.append("R8 no story check")
    elif st["status"] != "intact":
        miss.append(f"R8 story {st['status']}: a review must re-check it (intact, quoted) or drop the Buy")
    if not th.get("synthesis"):
        miss.append("R8 no synthesis")
    ch = (th.get("audit") or {}).get("checks") or []
    if len(ch) < 3 or not all(c.get("ok") for c in ch):
        miss.append(f"R8 audit has {sum(1 for c in ch if c.get('ok'))} matching check(s) of its own (needs 3, all matching the filing)")
    return miss


# ------------------------------------------------------------------ Buy gates (RULES.md), shared by run.py and republish.py
BUY = ("Buy", "Strong Buy")


def cash_conversion(Mx: dict) -> tuple[float | None, int | None]:
    """R1 input: cash from operations ÷ EBITDA in % before rounding (the shown value is rounded to 0 decimals, so 49.5%
    showed as 50% and passed), and the number of full years behind it (3, or 2 when only 2 are filed)."""
    m = (Mx or {}).get("cfo_to_ebitda_pct")
    if not isinstance(m, dict) or m.get("nm") or m.get("v") is None:
        return None, None
    i = m.get("in") or {}
    x = m.get("exact")
    if x is None and i.get("cfo_cr") is not None and i.get("ebitda_cr"):
        x = i["cfo_cr"] / i["ebitda_cr"] * 100  # data written before `exact` existed: inputs kept to 2 decimals in ₹ cr
    return (float(x) if x is not None else float(m["v"])), i.get("years")


# R1: positive operating cash flow over the full years (owner, 23 Nov 2026). Was cash conversion >= 50% from 17 Nov: the replay
# showed the candidates it blocked (mostly growing companies tying cash up in stock and receivables) beat the Nifty more often
# than those it passed; Claude's review checks receivables and earnings quality for the rest.
R1_MIN = 0.0
# R4: a dated trigger, or price strength in the top third of the universe (owner, 24 Nov 2026). The replay showed the
# trigger-only rule held back stocks the market was already buying: Top 10 12 m win 72% vs 59% with this rule.
R4_RS_MIN = 2 / 3


def rs_pct_of(L: dict) -> float | None:
    """Relative strength vs the universe (0-1) from the momentum level: stored `rs_pct`, else P2's points (out of 15)."""
    mom = (L or {}).get("mom") or {}
    if mom.get("rs_pct") is not None:
        return float(mom["rs_pct"])
    p2 = next((i for i in mom.get("items") or [] if i.get("id") == "P2"), None)
    pts = (p2 or {}).get("pts")
    return pts[0] / pts[1] if isinstance(pts, list) and len(pts) == 2 and pts[0] is not None and pts[1] else None


def buy_gates(Mx: dict, lender: bool, L: dict, th: dict | None, today) -> list[str]:
    """RULES.md Buy gates R1, R2, R4, R6: the failed ones, as text. `th` is the verified research entry."""
    from datetime import timedelta
    th, g = th or {}, []
    cc, yrs = cash_conversion(Mx)
    oi = v(Mx or {}, "other_income_pct_pbt")
    if not lender and cc is not None and cc <= R1_MIN:
        g.append(f"R1 operations did not bring in cash: cash conversion {cc:.1f}% of operating profit (needs above {R1_MIN:.0f}%)"
                 + (f"; only {yrs} full years filed" if yrs and yrs < 3 else ""))
    if not lender and oi is not None and oi > 25 and not th.get("other_income_recurring"):
        g.append(f"R2 other income {oi:.0f}% of pre-tax profit (needs ≤ 25%, or Narrativ.ai to verify it is recurring)")
    live = code_triggers(L)
    horizon = str(today + timedelta(days=548))
    dated = [d for d in th.get("drivers") or [] if d.get("due") and d.get("due_verified") and str(today) <= str(d["due"]) <= horizon]
    rs = rs_pct_of(L)
    if not live and not dated and not (rs is not None and rs >= R4_RS_MIN):
        g.append("R4 no dated trigger yet (order win, commissioning date, guidance raise, value unlock) and relative strength "
                 + (f"{rs * 100:.0f}th percentile (needs the top third)" if rs is not None else "unknown"))
    val, disc = L.get("val") or {}, L.get("disc") or {}
    if val.get("t") == 3 and disc.get("t") in (4, 5):
        g.append(f"R6 no re-rating leg: {str(val.get('name')).lower()} and {str(disc.get('name')).lower()}")
    return g


def ungate(d0: dict | None) -> dict:
    """The decision as it stood before the Buy gates held it (`gated_label`, set by apply_buy_rules), so the gates can be
    applied again with new research: a verified pass is the label again; otherwise Hold with `candidate` (verification
    pending), as funnel.decision returned it. A decision the gates did not hold is returned unchanged (a copy)."""
    d0 = dict(d0 or {})
    label = d0.pop("gated_label", None)
    if not label:
        return d0
    gates = set(d0.pop("gates", None) or [])
    gates |= {plain(g) for g in gates}  # the why lines carry the gates in plain words (gates keep their rule ids)
    why = [w for w in d0.get("why") or [] if w not in gates and not w.startswith("Scores say")]
    if d0.get("verified") == "pass":
        return {**d0, "d": label, "why": why}
    return {**d0, "d": "Hold", "candidate": label, "why": [f"Rules say {label}: waiting for Narrativ.ai's full review"] + why}


def apply_buy_rules(d0: dict, Mx: dict, lender: bool, L: dict, th: dict | None, today, issues: list | None = None,
                    inst_down_q: int | None = None) -> dict:
    """What stands of a Buy / Strong Buy (verified, or a candidate) after the open data issues, R5 and the Buy gates.
    `issues`: open data issues that cannot be patched (corrections.apply) -> Hold until resolved (candidate kept)."""
    d0 = ungate(d0)
    if issues and d0.get("d") in BUY:
        was = d0["d"]
        d0 = {**d0, "d": "Hold", "candidate": was,
              "why": [f"Rules say {was}, but a number is under correction: {', '.join(str(x.get('field')) for x in issues[:3])}"] + d0.get("why", [])}
    label = d0.get("candidate") or (d0.get("d") if d0.get("d") in BUY else None)
    if not label:
        return d0
    g = buy_gates(Mx, lender, L, th, today)
    if label == "Strong Buy" and (inst_down_q or 0) >= 3:
        label = "Buy"
        d0 = {**d0, "why": [f"R5 institutions sold for {inst_down_q} quarters in a row: Strong Buy capped at Buy"] + d0.get("why", [])}
        if d0.get("candidate"):
            d0["candidate"] = "Buy"
        elif d0.get("d") == "Strong Buy":
            d0["d"] = "Buy"
    notes = []
    if isinstance(lender, str) and lender:
        notes.append(f"R1 and R2 not applied: {lender}" + (" (cash conversion and other income do not measure an insurer)" if lender == "insurer" else " (lender)"))
    ne = (L.get("out") or {}).get("not_evaluated") if isinstance(L, dict) else None
    if ne:
        notes.append(f"Not evaluated (BSE-only, no exchange shareholding or insider-trading data): {', '.join(ne)}")
    if notes:
        d0 = {**d0, "why": list(d0.get("why", [])) + [n for n in notes if n not in (d0.get("why") or [])]}
    if g:
        # `candidate` is dropped (no review queued, no candidate call, app shows Hold); `gated_label` keeps what the rules
        # said, so republish.py can re-run the gates when Claude's research changes (e.g. other_income_recurring for R2, a
        # driver with a verified due date for R4) instead of waiting for the evening run (25 Nov 2026)
        d0 = {k: x for k, x in d0.items() if k != "candidate"} | {
            "d": "Hold", "gates": g, "gated_label": label,
            "why": [f"Scores say {label}, but the Buy rules are not met (RULES.md):"] + g + [w for w in d0.get("why", []) if not w.startswith("Rules say")]}
    elif d0.get("d") in BUY:  # a passed review that lacks what R7 requires is not yet a verification
        d0 = {k: x for k, x in d0.items() if k != "incomplete"}
        d0["missing"] = [m for m in d0.get("missing") or [] if not m.startswith(("Research incomplete", "Research pending"))]
        miss = r7_missing((th or {}).get("audit"), Mx, lender, L)
        if miss:
            d0 = {**d0, "d": "Hold", "candidate": label, "verified": "pending",
                  "why": [f"Rules say {label}: Narrativ.ai's review passed but some required checks are not recorded yet"]
                  + [w for w in d0.get("why", []) if not w.startswith(VERIFIED_BY)],
                  "missing": [m for m in d0.get("missing") or [] if not m.startswith("Verification pending")]
                  + [f"Verification pending: {m}" for m in miss]}
        # R8 (owner, 27 Nov 2026): the stock stays a Buy, but without the verified badge until Claude's research is complete
        # ("let them still be Buy, let's just not show the verified badge"); the review queue takes it first with its gaps
        elif gaps := research_missing(th):
            d0 = {**d0, "incomplete": gaps,
                  "why": [w for w in d0.get("why", []) if not w.startswith(VERIFIED_BY)]
                  + ["Narrativ.ai's review passed; research pending, so no verified badge yet (RULES.md R8)"],
                  "missing": d0["missing"] + [f"Research pending: {m}" for m in gaps]}  # owner, 27 Nov 2026: "pending", not "incomplete"
    return plain_decision(d0)


# ------------------------------------------------------------------ price-moving signals (RULES.md T11-T15)
def filed_time(Mx: dict) -> str | None:
    """Time of day (IST, "HH:MM") the latest results were broadcast, from the exchange API (filings.py `filed_time`, kept
    from Nov 2026; older cached filings have none). The time in the XBRL file name is not used: it is a 12-hour clock
    without AM / PM (97% of names show 01-12)."""
    t = (Mx or {}).get("filed_time")
    return str(t)[:5] if t else None


def signal_triggers(df, bench, Mx, av, nse, ann_rows, today, mcap_cr) -> list[tuple]:
    """Dated, data-backed reasons a stock tends to move up, as Outlook triggers (id, name, value, strong).
    T11 results beat (post-results drift), T12 estimates upgraded, T14 insider conviction, T15 mutual funds entering."""
    out = []
    filed = Mx.get("filed")
    pat_yoy = v(Mx, "pat_yoy_pct")
    if filed and df is not None and len(df) > 5:
        try:
            fd = pd.Timestamp(filed)
            if (pd.Timestamp(today) - fd).days <= 60:
                # filed at or after the 15:30 IST close: the filing day's close is the "before" price and the 3-day window
                # starts the next trading day; filing time unknown -> as before (window starts on the filing day)
                ft = filed_time(Mx)
                late = bool(ft and ft >= "15:30")
                b0 = df["Close"][df.index <= fd] if late else df["Close"][df.index < fd]
                a0 = df["Close"][df.index > fd] if late else df["Close"][df.index >= fd]
                if len(b0) and len(a0) >= 3:
                    r = (float(a0.iloc[2]) / float(b0.iloc[-1]) - 1) * 100
                    rb = 0.0
                    if bench is not None and len(bench):
                        bb = bench[bench.index <= fd] if late else bench[bench.index < fd]
                        ba = bench[bench.index > fd] if late else bench[bench.index >= fd]
                        if len(bb) and len(ba) >= 3:
                            rb = (float(ba.iloc[2]) / float(bb.iloc[-1]) - 1) * 100
                    if r - rb >= 5 and (pat_yoy or 0) >= 15:
                        out.append(("T11", "Results beat: price up after results, profit growing",
                                    f"{r - rb:+.1f}% vs Nifty in 3 days after {filed}" + (f" {ft} (after the close)" if late else "")
                                    + f" · profit {pat_yoy:+.0f}% YoY", r - rb >= 10))
        except Exception:  # noqa: BLE001
            pass
    est = (av or {}).get("eps_est") or {}
    if est.get("cur") and est.get("d90") and est["d90"] > 0 and ((av or {}).get("n") or 0) >= 2:
        ch = (est["cur"] / est["d90"] - 1) * 100
        if ch >= 5:
            out.append(("T12", "Analyst estimates upgraded", f"EPS estimate {ch:+.1f}% in 90 days ({av['n']} analysts, Yahoo)", ch >= 15))
    since = str(pd.Timestamp(today) - pd.Timedelta(days=120))[:10]
    bb = [r for r in ann_rows or [] if r[0] >= since and re.search(r"buy-?back", f"{r[1]} {r[2]}", re.I)
          and not re.search(r"postal ballot|newspaper|record date|scrutini", f"{r[1]} {r[2]}", re.I)
          # a subsidiary buying back its own shares is not the company's buyback (LUPIN, 1 Oct 2026: Multicare Philippines
          # bought back 30,559 shares and became a step-down wholly owned subsidiary; feedback #232 review, 27 Nov 2026)
          and not re.search(r"subsidiar|step-?down|wholly[- ]owned", f"{r[1]} {r[2]}", re.I)]
    cf = (nse or {}).get("cf") or {}
    net = (cf.get("prom_buy") or 0) - (cf.get("prom_sell") or 0)
    if bb:
        out.append(("T14", "Buyback announced", f"filed {bb[0][0]}: {str(bb[0][2] or bb[0][1])[:70]}", True))
    elif cf.get("pit_ok") and mcap_cr and net >= 0.001 * mcap_cr:
        out.append(("T14", "Promoters buying in the open market", f"net ₹{net:,.2f} cr in 12 months ({net / mcap_cr * 100:.2f}% of market cap)",
                    net >= 0.005 * mcap_cr))
    sh = (nse or {}).get("shp") or {}
    if (sh.get("mf_n_1q") or 0) >= 2 or (sh.get("mf_1q") or 0) >= 0.5:
        out.append(("T15", "Mutual funds entering", f"{int(sh.get('mf_n_1q') or 0):+d} schemes, holding {sh.get('mf_1q') or 0:+.2f} pts in the quarter to {sh.get('asof')}",
                    (sh.get("mf_n_1q") or 0) >= 5))
    return out
