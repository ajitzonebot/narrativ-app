"""Primary exchange data (NSE/BSE) via open-source libraries:
  NseIndiaApi (pip `nse`, GPL-3), BseIndiaApi (pip `bse`, GPL-3), nselib (Apache-2.0).
All values here are exchange-published facts with source links. Every call is guarded: failures
return empty data and never break the daily run."""
import json
import re
import csv
import io
from datetime import date, datetime, timedelta
from pathlib import Path

DL = Path("data/exchange_tmp")
FILING_RE = re.compile(r"transcript|investor presentation|analyst.*meet|earnings call|con\.? ?call", re.I)


def _f(d) -> str:
    return d.strftime("%d-%m-%Y")


def _pdate(s):
    s = str(s or "").strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        for cand in (s, s[:11], s[:10], s[:19]):
            try:
                return datetime.strptime(cand, fmt).date()
            except Exception:  # noqa: BLE001
                continue
    return None


def _records(x):
    try:
        import pandas as pd
        if isinstance(x, pd.DataFrame):
            return x.to_dict("records")
    except Exception:  # noqa: BLE001
        pass
    if isinstance(x, dict):
        for k in ("data", "Table"):
            if isinstance(x.get(k), list):
                return x[k]
    return x if isinstance(x, list) else []


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def results_calendar(today: date, back: int = 10, ahead: int = 45) -> dict:
    """Yahoo-style symbol -> {date, purpose, source}. NSE event calendar (direct), BSE via BseIndiaApi."""
    out = {}
    try:  # NSE event calendar, read directly (no wrapper library)
        from .filings import NSESession
        rows = NSESession().get("https://www.nseindia.com/api/event-calendar",
                                params={"index": "equities", "from_date": _f(today - timedelta(days=back)), "to_date": _f(today + timedelta(days=ahead))})
        for r in rows if isinstance(rows, list) else []:
            if "result" not in str(r.get("purpose", "")).lower():
                continue
            d = _pdate(str(r.get("date", "")))
            if d:
                out[f"{r['symbol']}.NS"] = {"date": str(d), "purpose": r.get("purpose"), "source": "NSE event calendar"}
    except Exception as e:  # noqa: BLE001
        print(f"[exchange] nse calendar failed: {e}")
    try:
        from bse import BSE
        DL.mkdir(parents=True, exist_ok=True)
        with BSE(download_folder=DL) as b:
            for r in _records(b.resultCalendar(from_date=datetime.combine(today - timedelta(days=back), datetime.min.time()),
                                               to_date=datetime.combine(today + timedelta(days=ahead), datetime.min.time()))):
                d = _pdate(str(r.get("meeting_date", "")))
                if d and r.get("short_name"):
                    out.setdefault(f"{r['short_name'].strip()}.BO", {"date": str(d), "purpose": "Financial Results",
                                                                      "source": "BSE result calendar", "scrip": str(r.get("scrip_Code"))})
    except Exception as e:  # noqa: BLE001
        print(f"[exchange] bse calendar failed: {e}")
    return out


BULK = Path("data/source_cache/bulk_deals.json")


def bulk_deals(days: int = 31) -> dict:
    """NSE symbol (.NS) -> bulk deals of the last `days` days. NSE's daily bulk-deal file (content/equities/bulk.csv,
    the latest trading day) is added to a rolling store each run; the store was seeded once with a month of history."""
    st = json.loads(BULK.read_text()) if BULK.exists() else {}
    if not st:  # one-time seed: a month of history through nselib (the daily file only has the latest day)
        try:
            from nselib import capital_market as cm
            for r in _records(cm.bulk_deal_data(period="1M")):
                d = _pdate(r.get("Date"))
                if d and r.get("Symbol"):
                    st.setdefault(str(d), []).append({"date": str(d), "client": r.get("ClientName"), "side": r.get("Buy/Sell"),
                                                      "qty": _num(r.get("QuantityTraded")), "price": _num(r.get("TradePrice/Wght.Avg.Price")),
                                                      "source": "NSE bulk deals", "symbol": r.get("Symbol")})
        except Exception as e:  # noqa: BLE001
            print(f"[exchange] bulk deals seed skipped: {e}")
    try:
        from .filings import NSESession
        r = NSESession().s.get("https://nsearchives.nseindia.com/content/equities/bulk.csv", timeout=60)
        if r.ok and r.text.lstrip().startswith("Date"):
            for x in csv.DictReader(io.StringIO(r.text)):
                x = {k.strip(): (v or "").strip() for k, v in x.items() if k}
                d = _pdate(x.get("Date", ""))
                if not d or not x.get("Symbol"):
                    continue
                rec = {"date": str(d), "client": x.get("Client Name"), "side": x.get("Buy/Sell"), "qty": _num(x.get("Quantity Traded")),
                       "price": _num(x.get("Trade Price / Wght. Avg. Price")), "source": "NSE bulk deals"}
                day = st.setdefault(str(d), [])
                if [rec.get(k) for k in ("client", "side", "qty", "price")] not in [[y.get(k) for k in ("client", "side", "qty", "price")]
                                                                                    for y in day if y.get("symbol") == x["Symbol"]]:
                    day.append({**rec, "symbol": x["Symbol"]})
    except Exception as e:  # noqa: BLE001
        print(f"[exchange] bulk deals file failed: {e}")
    cut = str(date.today() - timedelta(days=days))
    st = {d: v for d, v in st.items() if d >= cut}
    BULK.parent.mkdir(parents=True, exist_ok=True)
    BULK.write_text(json.dumps(st, separators=(",", ":")))
    out = {}
    for d in sorted(st, reverse=True):
        for x in st[d]:
            out.setdefault(f"{x['symbol']}.NS", []).append({k: v for k, v in x.items() if k != "symbol"})
    print(f"[exchange] bulk deals: {sum(len(v) for v in st.values())} deals over {len(st)} trading days stored")
    return out


from . import events  # noqa: E402


def per_stock(symbols: list[str], today: date, scrip_codes: dict | None = None, ann_st: dict | None = None,
              shp_st: dict | None = None, nsed: dict | None = None) -> dict:
    """Filings (transcripts/presentations), events, promoter history and delivery % for a small set.
    NSE stocks: from the announcement store, the shareholding store and the NSE daily files (no extra calls).
    BSE-only stocks: BSE announcements API."""
    from . import shp as SHP
    from . import nsedaily as NSED
    out = {s: {} for s in symbols}
    nse_syms = [s for s in symbols if s.endswith(".NS")]
    bse_syms = [s for s in symbols if s.endswith(".BO")]
    DL.mkdir(parents=True, exist_ok=True)
    since = (today - timedelta(days=330)).isoformat()
    for s in nse_syms:
        rows = [r for r in ((ann_st or {}).get("rows") or {}).get(s, []) if r[0] >= since]
        anns = [{"date": r[0], "text": r[2] or r[1], "category": r[1], "url": r[3]} for r in rows]
        out[s]["filings"] = [a for a, r in zip(anns, rows) if a["url"] and (FILING_RE.search(f"{a['text']} {a['category']}")
                                                                           or (len(r) > 5 and r[5] in ("Transcript", "Investor presentation")))][:12]
        out[s]["events"] = events.from_announcements(anns)[:40]
        out[s]["promoter"] = SHP.promoter_hist(shp_st or {}, s, 6)
        dv = NSED.delivery_stats((nsed or {}).get("deliv") or {}, s[:-3]) if nsed else None
        if dv and dv.get("m1") is not None:
            out[s]["delivery_pct_1m"] = dv["m1"]
            out[s]["delivery_pct_last"] = dv["last"]
    if bse_syms and scrip_codes:
        try:
            from bse import BSE
            with BSE(download_folder=DL) as b:
                for s in bse_syms:
                    code = scrip_codes.get(s)
                    if not code:
                        continue
                    try:
                        res = _records(b.announcements(scripcode=code, from_date=datetime.combine(today - timedelta(days=330), datetime.min.time()),
                                                       to_date=datetime.combine(today, datetime.min.time())))
                        fil = [{"date": str(a.get("NEWS_DT", ""))[:10], "text": a.get("HEADLINE") or a.get("NEWSSUB"),
                                "category": a.get("CATEGORYNAME"),
                                "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{a['ATTACHMENTNAME']}"}
                               for a in res if a.get("ATTACHMENTNAME") and FILING_RE.search(f"{a.get('HEADLINE','')} {a.get('NEWSSUB','')}")]
                        out[s]["filings"] = fil[:12]
                        out[s]["events"] = events.from_announcements([
                            {"date": str(a.get("NEWS_DT", ""))[:10], "text": a.get("HEADLINE") or a.get("NEWSSUB"), "category": a.get("CATEGORYNAME"),
                             "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{a['ATTACHMENTNAME']}" if a.get("ATTACHMENTNAME") else None}
                            for a in res])[:40]
                    except Exception as e:  # noqa: BLE001
                        print(f"[exchange] {s} bse announcements: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[exchange] BSE session failed: {e}")
    for s, v in out.items():
        h = v.get("promoter") or []
        if len(h) >= 2:
            v["promoter_chg_qoq"] = round(h[-1]["promoter_pct"] - h[-2]["promoter_pct"], 2)
    return out


if __name__ == "__main__":  # Actions smoke test
    t = date.today()
    cal = results_calendar(t)
    bulk = bulk_deals()
    ps = per_stock(["DEEPINDS.NS", "KANPRPLA.NS", "ONWARDTEC.NS", "BONDADA.BO"], t, {"BONDADA.BO": "543971"})
    Path("probe/exchange_test.json").write_text(json.dumps(
        {"calendar_n": len(cal), "calendar_sample": dict(list(cal.items())[:3]), "bse_in_calendar": sum(k.endswith(".BO") for k in cal),
         "bulk_symbols": len(bulk), "bulk_sample": dict(list(bulk.items())[:1]), "per_stock": ps}, indent=1, default=str))
    print("ok")


SH_CACHE = Path("data/shareholding.json")


def shareholding_cached(symbols: list[str], today: date, budget: int = 250, max_age: int = 30) -> dict:
    """Deprecated: promoter history now comes from narrativ.shp (own NSE session). Returns the old git cache as a fallback."""
    return json.loads(SH_CACHE.read_text()) if SH_CACHE.exists() else {}
