"""Stage 2: per-stock fundamentals (cached), capex check, inflection / undiscovered / valuation scores."""
import json
import math
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from . import config

CACHE = Path("data/fundamentals.json")
INFO_KEYS = [
    "marketCap", "sector", "industry", "numberOfAnalystOpinions", "heldPercentInstitutions",
    "heldPercentInsiders", "returnOnEquity", "debtToEquity", "trailingPE", "forwardPE", "priceToBook",
    "enterpriseToEbitda", "trailingPegRatio", "revenueGrowth", "earningsGrowth", "profitMargins",
    "operatingMargins", "ebitdaMargins", "freeCashflow", "totalRevenue", "longBusinessSummary", "website",
    "sharesOutstanding",
]
CAPEX_HEAVY_INDUSTRIES = {
    "Steel", "Aluminum", "Building Materials", "Telecom Services", "Marine Shipping", "Airlines",
    "Oil & Gas Refining & Marketing", "Utilities - Regulated Electric", "Utilities - Independent Power Producers",
    "Utilities - Renewable", "Paper & Paper Products", "Other Industrial Metals & Mining",
}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def _row(df: pd.DataFrame, name: str, col):
    if df is None or df.empty or name not in df.index:
        return None
    return _clean(float(df.at[name, col])) if pd.notna(df.at[name, col]) else None


def _quarters(t: yf.Ticker) -> list[dict]:
    q = t.quarterly_income_stmt
    if q is None or q.empty:
        return []
    return [{"date": str(pd.Timestamp(c).date()), "revenue": _row(q, "Total Revenue", c),
             "op_income": _row(q, "Operating Income", c), "net_income": _row(q, "Net Income", c)}
            for c in sorted(q.columns)]


def _annual_capex(t: yf.Ticker) -> list[dict]:
    cf, inc = t.cashflow, t.income_stmt
    if cf is None or cf.empty:
        return []
    out = []
    for c in sorted(cf.columns)[-3:]:
        rev = _row(inc, "Total Revenue", c) if inc is not None and c in getattr(inc, "columns", []) else None
        out.append({"year": str(pd.Timestamp(c).date()), "capex": _row(cf, "Capital Expenditure", c),
                    "fcf": _row(cf, "Free Cash Flow", c), "ocf": _row(cf, "Operating Cash Flow", c), "revenue": rev})
    return out


def _next_earnings(t: yf.Ticker):
    try:
        cal = t.calendar or {}
        d = cal.get("Earnings Date")
        if isinstance(d, list) and d:
            d = d[0]
        return str(d) if isinstance(d, (date, datetime)) else None
    except Exception:  # noqa: BLE001
        return None


def fetch_one(ysym: str) -> dict:
    t = yf.Ticker(ysym)
    info = t.info or {}
    rec = {k: _clean(info.get(k)) for k in INFO_KEYS}
    if rec.get("longBusinessSummary"):
        rec["longBusinessSummary"] = rec["longBusinessSummary"][:600]
    for k, fn in (("quarters", _quarters), ("annual", _annual_capex)):
        try:
            rec[k] = fn(t)
        except Exception as e:  # noqa: BLE001
            print(f"[fund] {ysym} {k} failed: {e}")
            rec[k] = []
    rec["next_earnings"] = _next_earnings(t)
    rec["fetched"] = datetime.now(timezone.utc).isoformat()
    return rec


def load() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def refresh(symbols: list[str], force: set[str] = frozenset()) -> dict:
    """Fetch symbols that are new, older than FUND_MAX_AGE_DAYS, or forced (results checkpoint due)."""
    cache = load()
    now = datetime.now(timezone.utc)

    def age(s):
        f = cache.get(s, {}).get("fetched")
        return (now - datetime.fromisoformat(f)).days if f else 999

    todo = [s for s in symbols if s in force or age(s) >= config.FUND_MAX_AGE_DAYS]
    todo.sort(key=lambda s: (s not in force, -age(s)))
    todo = todo[: config.FUND_MAX_PER_RUN]
    print(f"[fund] refreshing {len(todo)} of {len(symbols)} (forced {len(force & set(todo))})")
    fails = 0
    for i, s in enumerate(todo):
        try:
            cache[s] = fetch_one(s)
            fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"[fund] {s} failed: {e}")
            if fails >= 8:
                print("[fund] too many consecutive failures, stopping")
                break
            time.sleep(5)
        time.sleep(config.FUND_SLEEP_SEC)
        if i % 40 == 39:
            CACHE.write_text(json.dumps(cache))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))
    return cache


def capex_check(f: dict, industry: str | None) -> tuple[bool, str | None]:
    """(exclude, note). Exclude if capex > 15% of revenue on average AND FCF < 0 in >= 2 of last 3 years."""
    yrs = [y for y in f.get("annual", []) if y.get("capex") is not None and y.get("revenue")]
    if len(yrs) >= 2:
        intensity = sum(abs(y["capex"]) / y["revenue"] for y in yrs) / len(yrs)
        neg_fcf = sum(1 for y in yrs if (y.get("fcf") or 0) < 0)
        if intensity > config.CAPEX_MAX_INTENSITY and neg_fcf >= 2:
            return True, f"capex-heavy ({intensity:.0%} of revenue, FCF negative {neg_fcf}/{len(yrs)} yrs)"
        return False, f"capex {intensity:.0%} of revenue"
    if industry in CAPEX_HEAVY_INDUSTRIES:
        return False, "capex-heavy industry (no cash-flow data)"
    return False, None


def _yoy(qs, key, idx):
    try:
        cur, prev = qs[idx][key], qs[idx - 4][key]
    except IndexError:
        return None
    if cur is None or prev is None or prev <= 0:
        return None
    return cur / prev - 1


def inflection(f: dict) -> tuple[float, dict]:
    qs = [q for q in f.get("quarters", []) if q.get("revenue")]
    # Yahoo statement line items only (fallback when no NSE filing); Yahoo's own ratios are not used
    m = {"rev_yoy": _yoy(qs, "revenue", -1)}
    m["rev_yoy_prev"] = _yoy(qs, "revenue", -2) if len(qs) >= 6 else None
    m["rev_qoq_up2"] = bool(len(qs) >= 3 and qs[-1]["revenue"] > qs[-2]["revenue"] > qs[-3]["revenue"])
    ref = None
    if len(qs) >= 5 and qs[-5]["revenue"] and 0.5 < qs[-1]["revenue"] / qs[-5]["revenue"] < 2.5:
        ref = qs[-5]
    elif len(qs) >= 2:
        ref = qs[-2]
    if qs and ref and qs[-1]["op_income"] is not None and ref["op_income"] is not None:
        m["opm"], m["opm_ref"] = qs[-1]["op_income"] / qs[-1]["revenue"], ref["op_income"] / ref["revenue"]
    else:
        m["opm"], m["opm_ref"] = None, None
    ni = [q["net_income"] for q in qs if q.get("net_income") is not None]
    m["turnaround"] = bool(len(ni) >= 5 and ni[-5] <= 0 < ni[-1])
    ttm = [sum(ni[i - 4:i]) for i in (len(ni), len(ni) - 4)] if len(ni) >= 8 else None
    m["ni_yoy"] = None if m["turnaround"] or not ttm or ttm[1] <= 0 else ttm[0] / ttm[1] - 1
    m["last_quarter"] = qs[-1]["date"] if qs else None

    s, have = 0.0, 0
    if m["rev_yoy"] is not None:
        have += 1
        s += min(25, max(0, m["rev_yoy"] / 0.25 * 25))
        if m["rev_yoy_prev"] is not None:
            s += 15 if m["rev_yoy"] > m["rev_yoy_prev"] + 0.02 else 0
        elif m["rev_qoq_up2"]:
            s += 10
    if m["opm"] is not None and m["opm_ref"] is not None:
        have += 1
        s += 20 if m["opm"] > m["opm_ref"] + 0.01 else 0
    if m["turnaround"]:
        s += 20
    elif m["ni_yoy"] is not None:
        have += 1
        s += min(20, max(0, m["ni_yoy"] / 0.4 * 20))
    m["completeness"] = have
    return float(min(100, s)), m


def undiscovered(f: dict, mcap: float | None) -> float:
    s = 0.0
    n = f.get("numberOfAnalystOpinions")
    s += 40 if not n or n <= 2 else 25 if n <= 5 else 10 if n <= 8 else 0
    inst = f.get("heldPercentInstitutions")
    s += 15 if inst is None else 30 if inst < 0.10 else 20 if inst < 0.20 else 10 if inst < 0.30 else 0
    mc = mcap or f.get("marketCap") or 0
    s += 30 if mc < 1500 * config.CRORE else 22 if mc < 4000 * config.CRORE else 12 if mc < 10000 * config.CRORE else 0
    return float(min(100, s))


def valuation(pe, ev_ebitda, peg, ind_pe_median) -> float:
    """0-100: cheap vs own industry, reasonable absolute multiples, PEG."""
    s, n = 0.0, 0
    if pe and pe > 0 and ind_pe_median and ind_pe_median > 0:
        n += 1
        rel = pe / ind_pe_median
        s += 40 if rel < 0.7 else 30 if rel < 0.9 else 18 if rel < 1.1 else 8 if rel < 1.4 else 0
    if ev_ebitda and ev_ebitda > 0:
        n += 1
        s += 30 if ev_ebitda < 10 else 20 if ev_ebitda < 15 else 10 if ev_ebitda < 22 else 0
    if peg and peg > 0:
        n += 1
        s += 30 if peg < 1 else 18 if peg < 1.5 else 8 if peg < 2 else 0
    return float(s if n else 40)
