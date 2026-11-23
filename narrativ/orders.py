"""T3 (single order >= 10% of revenue, 6 months) from order announcements. Subject / description text only; the value
must be stated in rupees (₹ / Rs / INR with crore, lakh, million or billion). Foreign-currency values are not converted
(no rate is guessed): such orders, and orders with no stated value, leave the check open."""
import re
from datetime import date, timedelta

WIN = re.compile(r"\b(receiv\w*|bag\w*|secur\w*|won|win[sn]?\w*|award\w*|bagged|got)\b.{0,80}\b(order|contract|work|project|loa|letter of award|"
                 r"letter of intent|purchase order|work order)s?\b|\b(order|contract|loa|letter of award|work order|purchase order)s?\b.{0,60}"
                 r"\b(receiv\w*|award\w*|secur\w*|bag\w*|won)\b|\b(order inflow|new orders?|orders? worth|order of|contract worth|l1 bidder)\b", re.I)
NOT = re.compile(r"order (passed|issued) by|court order|tribunal|nclt|sebi|penalt|show cause|stock exchange|adjudicat|arbitral award|"
                 r"interim order|final order|restraining|in the order of", re.I)
AMT = re.compile(r"(?:₹|rs\.?|inr|rupees)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn)\b", re.I)
FX = re.compile(r"(?:usd|us\$|\$|eur|€|gbp|£|aed|sar)\s*[\d,.]+", re.I)
MULT = {"cr": 1, "crore": 1, "crores": 1, "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01, "million": 0.1, "mn": 0.1,
        "billion": 100, "bn": 100}


def value_cr(text: str) -> float | None:
    """Largest rupee amount stated in the text, in ₹ crore."""
    best = None
    for n, u in AMT.findall(text or ""):
        try:
            v = float(n.replace(",", "")) * MULT[u.lower().rstrip(".")]
        except (ValueError, KeyError):
            continue
        best = v if best is None or v > best else best
    return best


def recent(rows: list, today: date, days: int = 183) -> list[dict]:
    """Order announcements in the window: [{date, cr|None, fx, text, url}], newest first."""
    cut = (today - timedelta(days=days)).isoformat()
    out = []
    for r in rows or []:
        d, cat, txt, url = r[0], r[1], r[2], r[3]
        s = f"{cat} {txt}"
        if d < cut or not WIN.search(s) or NOT.search(s):
            continue
        out.append({"date": d, "cr": value_cr(s), "fx": bool(FX.search(s)), "text": (txt or cat)[:160], "url": url})
    return out


def t3(rows: list, rev_ttm_cr: float | None, today: date) -> tuple:
    """-> (state True/False/None, value text, note, url) for 'Single order >= 10% of revenue (6 months)'."""
    o = recent(rows, today)
    if not o:
        return None, None, "no order announcement in 6 months", None
    valued = [x for x in o if x["cr"]]
    if not valued:
        fx = any(x["fx"] for x in o)
        return None, f"{len(o)} order announcement(s), value not stated in ₹" + (" (foreign currency, not converted)" if fx else ""), \
            "open the filing", o[0]["url"]
    top = max(valued, key=lambda x: x["cr"])
    if not rev_ttm_cr:
        return None, f"largest order ₹{top['cr']:,.1f} cr ({top['date']})", "revenue (last 4 quarters) not available", top["url"]
    pct = top["cr"] / rev_ttm_cr * 100
    return pct >= 10, f"₹{top['cr']:,.1f} cr on {top['date']} = {pct:.1f}% of revenue (last 4 quarters)", "order value from the filing's subject line", top["url"]
