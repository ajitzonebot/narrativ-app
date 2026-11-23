"""Stage 0: daily universe from the exchanges (since 17 Nov 2026; the Yahoo screener helpers below are no longer called).

Exclusion-based: a stock is removed only on evidence of a problem. Missing data keeps it
(tagged data-light). Each stock records its exclusion reasons. ~80-100 requests, no per-ticker calls.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from yfinance import EquityQuery as Q

from . import config

PAGE = 250
SECTORS = ["Basic Materials", "Communication Services", "Consumer Cyclical", "Consumer Defensive",
           "Energy", "Financial Services", "Healthcare", "Industrials", "Real Estate", "Technology", "Utilities"]

# Positive quality criteria -> quality points (0-9)
QUALITY = {
    "roe": Q("gt", ["returnonequity.lasttwelvemonths", 15]),
    "low_debt": Q("lt", ["totaldebtequity.lasttwelvemonths", 50]),
    "q_rev_growth": Q("gt", ["quarterlyrevenuegrowth.quarterly", 15]),
    "rev_growth": Q("gt", ["totalrevenues1yrgrowth.lasttwelvemonths", 15]),
    "eps_growth": Q("gt", ["epsgrowth.lasttwelvemonths", 20]),
    "good_margin": Q("gt", ["ebitdamargin.lasttwelvemonths", 15]),
    "fcf_pos": Q("gt", ["leveredfreecashflow.lasttwelvemonths", 0]),
    "pe_ok": Q("btwn", ["peratio.lasttwelvemonths", 0, 40]),
    "peg_ok": Q("btwn", ["pegratio_5y", 0, 1.5]),
}
# Evidence-of-problem sets
NEGATIVE = {
    "high_debt": Q("gt", ["totaldebtequity.lasttwelvemonths", 100]),
    "thin_margin": Q("lt", ["ebitdamargin.lasttwelvemonths", 8]),
    "rev_down_ttm": Q("lt", ["totalrevenues1yrgrowth.lasttwelvemonths", 0]),
    "rev_down_q": Q("lt", ["quarterlyrevenuegrowth.quarterly", 0]),
    "q_rev_25": Q("gt", ["quarterlyrevenuegrowth.quarterly", 25]),
}
KEEP = ["symbol", "shortName", "longName", "exchange", "regularMarketPrice", "marketCap",
        "averageDailyVolume3Month", "fiftyDayAverage", "twoHundredDayAverage", "twoHundredDayAverageChangePercent",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekChangePercent", "trailingPE", "priceToBook",
        "epsTrailingTwelveMonths"]


def _base() -> list:
    return [Q("is-in", ["exchange", "NSI", "BSE"]),
            (Q("btwn", ["intradaymarketcap", config.MIN_MCAP, config.MAX_MCAP]) if config.MAX_MCAP
             else Q("gte", ["intradaymarketcap", config.MIN_MCAP]))]


def _pull(extra=None) -> list[dict]:
    q = Q("and", _base() + ([extra] if extra is not None else []))
    out, offset = [], 0
    while True:
        for attempt in range(4):
            try:
                r = yf.screen(q, offset=offset, size=PAGE, sortField="intradaymarketcap", sortAsc=True)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[sweep] retry {attempt + 1}: {e}")
                time.sleep(6 * (attempt + 1))
        else:
            raise RuntimeError("screener unavailable")
        quotes = r.get("quotes", [])
        out += quotes
        offset += len(quotes)
        if not quotes or offset >= r.get("total", 0):
            return out
        time.sleep(0.7)


INDUSTRY_MAP = Path("data/industry_map.json")


def industry_map(max_age_days: int = 7) -> dict[str, str]:
    """symbol -> Yahoo industry. Refreshed weekly (~150 small queries)."""
    if INDUSTRY_MAP.exists():
        m = json.loads(INDUSTRY_MAP.read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(m["_updated"])).days
        if age < max_age_days:
            return m["map"]
    from yfinance.const import EQUITY_SCREENER_EQ_MAP
    out = {}
    for names in EQUITY_SCREENER_EQ_MAP["industry"].values():
        for n in sorted(names):
            try:
                for sym in _syms(Q("eq", ["industry", n])):
                    out[sym] = n.replace("\u2014", " - ")
            except Exception as e:  # noqa: BLE001
                print(f"[sweep] industry {n} failed: {e}")
    if len(out) > 1000:
        INDUSTRY_MAP.parent.mkdir(parents=True, exist_ok=True)
        INDUSTRY_MAP.write_text(json.dumps({"_updated": datetime.now(timezone.utc).isoformat(), "map": out}))
    print(f"[sweep] industry map {len(out)} symbols")
    return out


def _norm(name: str) -> str:
    n = (name or "").lower()
    return re.sub(r"\b(limited|ltd|the|india|co|company|corp|corporation)\b|[^a-z0-9]", "", n)


def _syms(extra) -> set[str]:
    return {x["symbol"] for x in _pull(extra)}


EXTRA_META = Path("data/industry_extra.json")


def fill_meta(symbols: list[str], budget: int = 300) -> dict[str, list]:
    """sector/industry for symbols the Yahoo screener does not return (per-ticker lookup, cached for good)."""
    m = json.loads(EXTRA_META.read_text()) if EXTRA_META.exists() else {}
    todo = [s for s in symbols if s not in m][:budget]
    for s in todo:
        try:
            inf = yf.Ticker(s).info or {}
            m[s] = [inf.get("sector"), (inf.get("industry") or "").replace("\u2014", " - ") or None]
        except Exception as e:  # noqa: BLE001
            print(f"[sweep] meta {s}: {e}")
            m[s] = [None, None]
        time.sleep(0.5)
    if todo:
        EXTRA_META.write_text(json.dumps(m, indent=0, sort_keys=True))
        print(f"[sweep] looked up sector/industry for {len(todo)} symbols not in the screener")
    return m


def _nse_only_map(cls: dict, rows: list[dict]) -> dict:
    """For companies with no BSE listing: their old Yahoo industry (cached on disk, no network) -> the BSE industry most
    companies with that Yahoo industry carry. Returns {symbol: classification} marked src 'mapped'."""
    try:
        ymap = json.loads(INDUSTRY_MAP.read_text())["map"] if INDUSTRY_MAP.exists() else {}
        ymap.update({k: v[1] for k, v in (json.loads(EXTRA_META.read_text()) if EXTRA_META.exists() else {}).items() if v and v[1]})
    except Exception:  # noqa: BLE001
        return {}
    votes: dict = {}
    for r in rows:
        c, y = cls.get(r.get("isin") or ""), ymap.get(r["symbol"])
        if c and c.get("src") == "BSE" and y:
            votes.setdefault(y, {}).setdefault((c["m"], c["s"], c["i"]), 0)
            votes[y][(c["m"], c["s"], c["i"])] += 1
    best = {y: max(v.items(), key=lambda kv: kv[1])[0] for y, v in votes.items()}
    out = {}
    for r in rows:
        if (r.get("isin") or "") in cls:
            continue
        y = ymap.get(r["symbol"])
        if y in best:
            m, sct, ind = best[y]
            out[r["symbol"]] = {"m": m, "s": sct, "i": ind, "b": None, "src": "mapped"}
    return out


def sweep() -> tuple[pd.DataFrame, dict]:
    """Universe from the exchanges only (narrativ.universe): membership, name, market cap, close, listing date;
    classification from BSE (narrativ.classify). No Yahoo calls. Liquidity / penny tags are set later from our own prices."""
    from datetime import date
    from . import classify, universe
    rows, ustats = universe.build(date.today())
    cls = classify.refresh(rows)
    mapped = _nse_only_map(cls, rows)
    recs = []
    for r in rows:
        c = cls.get(r.get("isin") or "") or mapped.get(r["symbol"]) or {}
        recs.append({"symbol": r["symbol"], "isin": r.get("isin"), "bse_code": r.get("bse_code"), "exch": r.get("exch"),
                     "listed": r.get("listed"), "longName": r.get("name"), "shortName": r.get("name"),
                     "marketCap": r["mcap_cr"] * 1e7 if r.get("mcap_cr") is not None else None, "regularMarketPrice": r.get("close"),
                     "sector": c.get("m"), "sector2": c.get("s"), "industry": c.get("i"), "basic_industry": c.get("b"),
                     "class_src": c.get("src")})
    df = pd.DataFrame(recs)
    df["tags"] = [[] for _ in range(len(df))]
    df["exclude_reasons"] = [[] for _ in range(len(df))]
    df["passed"] = True
    n_cls = int(df["industry"].notna().sum())
    print(f"[sweep] universe {len(df)} ({ustats.get('nse')} NSE + {ustats.get('bse_only')} BSE-only); classified {n_cls} "
          f"({int((df['class_src'] == 'mapped').sum())} mapped from the old industry, no BSE listing); {len(df) - n_cls} unclassified")
    stats = {"raw": ustats.get("listed_unique") or len(df), "companies": len(df), "passed": len(df), "universe": ustats,
             "declining_industries": [], "excluded_by": {}, "industry_health": []}
    return df, stats
