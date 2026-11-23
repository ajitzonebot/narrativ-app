"""NSE daily files (Batch 1). All free, no login:
- delivery %   : products/content/sec_bhavdata_full_DDMMYYYY.csv (one file per trading day; ~65 days kept)
- surveillance : api/reportGSM, api/reportASM (current lists) and content/equities/suspension.csv
- index lists  : content/indices/ind_<index>list.csv (broad indices; refreshed weekly)
Feeds checks A6 (Stability), F3 (Momentum), D7 and D8 (Discovery). BSE-only stocks are not covered (NSE files)."""
import csv
import io
import json
import re
import statistics as stx
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .filings import NSESession

ARCH = "https://nsearchives.nseindia.com"
CACHE = Path("data/source_cache")
DELIV = CACHE / "delivery.json"
INDEX = CACHE / "indices.json"
SURV = CACHE / "surveillance.json"
SINCE = Path("data/index_membership.json")  # small, in git: first date we saw a stock in its current index
KEEP_DAYS = 65  # ~3 months of trading days
# broadest-first is wrong for labels; order = most discovered first
INDICES = [("Nifty 50", "ind_nifty50list"), ("Nifty 100", "ind_nifty100list"), ("Nifty Midcap 150", "ind_niftymidcap150list"),
           ("Nifty Smallcap 250", "ind_niftysmallcap250list"), ("Nifty Microcap 250", "ind_niftymicrocap250_list")]
ROMAN = {"0": 0, "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


def _num(x):
    try:
        return float(str(x).strip())
    except ValueError:
        return None


# ------------------------------------------------------------------ delivery %
def _delivery_day(ns, d: date) -> dict | None:
    from .bhav import _get  # shared cache with the prices step: one download per day
    t = _get(f"nse_{d:%Y%m%d}.csv", f"{ARCH}/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv", ns.s)
    if not t:
        return None
    if f"{d:%d-%b-%Y}".lower() not in t[:400].lower():
        return None  # on a holiday NSE can serve the previous day's file
    out = {}
    rows = csv.reader(io.StringIO(t))
    head = [h.strip() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    for row in rows:
        row = [c.strip() for c in row]
        if len(row) < len(head):
            continue
        sym, ser, pct = row[ix["SYMBOL"]], row[ix["SERIES"]], _num(row[ix["DELIV_PER"]])
        if pct is None or ser not in ("EQ", "BE", "BZ"):
            continue
        if sym not in out or ser == "EQ":
            out[sym] = pct
    return out


def delivery(ns, today: date, max_minutes: float = 4) -> dict:
    """Refresh the rolling store; returns {date_iso: {symbol: delivery_pct}} for the last KEEP_DAYS trading days."""
    st = json.loads(DELIV.read_text()) if DELIV.exists() else {"days": {}, "closed": []}
    days, closed = st["days"], set(st["closed"])
    t0, d, got, fetched = time.time(), today, 0, 0
    floor = today - timedelta(days=KEEP_DAYS * 7 // 5 + 20)
    while d > floor and got < KEEP_DAYS and time.time() - t0 < max_minutes * 60:
        k = d.isoformat()
        if d.weekday() < 5 and k not in closed:
            if k not in days:
                try:
                    x = _delivery_day(ns, d)
                    fetched += 1
                except Exception as e:  # noqa: BLE001
                    print(f"[nse] delivery {k}: {e}")
                    x = {}
                if x is None:  # 404: holiday, or today's file not out yet
                    if (today - d).days > 3:
                        closed.add(k)
                elif x:
                    days[k] = x
            if k in days:
                got += 1
        d -= timedelta(days=1)
    keep = sorted(days)[-KEEP_DAYS:]
    bdone = set(st.get("bse_days") or [])
    nb = 0
    for k in keep:  # BSE delivery file for the same days (BSE-only stocks)
        if k in bdone or time.time() - t0 > max_minutes * 60:
            continue
        x = _bse_delivery_day(date.fromisoformat(k))
        if x is not None:
            days[k].update(x)
            bdone.add(k)
            nb += 1
    st = {"days": {k: days[k] for k in keep}, "closed": sorted(c for c in closed if c >= floor.isoformat()),
          "bse_days": sorted(b for b in bdone if b in set(keep))}
    CACHE.mkdir(parents=True, exist_ok=True)
    DELIV.write_text(json.dumps(st, separators=(",", ":")))
    print(f"[nse] delivery: {len(keep)} trading days stored ({fetched} NSE + {nb} BSE files read), latest {keep[-1] if keep else None}")
    return st["days"]


def _bse_delivery_day(d: date) -> dict | None:
    """BSE daily delivery file (bse library, SCBSEALLddmm): {"B:<scrip code>": delivery %}; None when not available."""
    try:
        from bse import BSE
        tmp = CACHE / "bse_deliv"
        tmp.mkdir(parents=True, exist_ok=True)
        with BSE(download_folder=tmp) as b:
            f = Path(b.deliveryReport(datetime.combine(d, datetime.min.time()), folder=tmp))
        out = {}
        for r in csv.DictReader(io.StringIO(f.read_text())):
            code, pct = (r.get("SCRIP CODE") or "").strip(), _num(r.get("DELV. PER."))
            if code and pct is not None:
                out[f"B:{code.lstrip('0')}"] = pct
        f.unlink(missing_ok=True)
        return out
    except Exception as e:  # noqa: BLE001
        if "unavailable" in str(e).lower() and (date.today() - d).days > 3:
            return {}  # no BSE file for that day (holiday): recorded, not asked again
        print(f"[nse] BSE delivery {d}: {e}")
        return None


def delivery_stats(days: dict, sym: str) -> dict | None:
    """10-day and 1-month vs 3-month average delivery %. Needs >= 40 trading days."""
    ser = [days[k][sym] for k in sorted(days) if sym in days[k]]
    if len(ser) < 40:
        return {"n": len(ser)} if ser else None
    return {"n": len(ser), "last": ser[-1], "d10": round(stx.mean(ser[-10:]), 1), "m1": round(stx.mean(ser[-21:]), 1),
            "m3": round(stx.mean(ser[-63:]), 1)}


# ------------------------------------------------------------------ surveillance
def _stage(desc: str, key: str) -> int | None:
    m = re.search(key + r"\)?\s*(?:-\s*)?(?:Stage\s*)?\(?\b(0|I{1,3}|IV|VI?|[1-6])\b", desc, re.I)
    if not m:
        return None
    s = m.group(1).upper()
    return int(s) if s.isdigit() else ROMAN.get(s)


def surveillance(ns) -> dict:
    """{symbol: {"gsm": stage|None, "asm": stage|None, "susp": date|None, "desc": [...]}} from the current NSE lists."""
    out = {}

    def rec(sym):
        return out.setdefault(sym, {"gsm": None, "asm": None, "susp": None, "desc": []})

    gsm = ns.get("https://www.nseindia.com/api/reportGSM")
    for r in gsm if isinstance(gsm, list) else []:
        x = rec(r.get("symbol"))
        desc = r.get("survDesc") or ""
        x["desc"].append(desc)
        s = _stage(desc, "GSM")
        x["gsm"] = s if x["gsm"] is None else max(x["gsm"], s or 0)
        if "ASM" in desc:
            a = _stage(desc, "ASM") or 1
            x["asm"] = max(x["asm"] or 0, a)
    asm = ns.get("https://www.nseindia.com/api/reportASM")
    for part in (asm.values() if isinstance(asm, dict) else []):
        for r in (part or {}).get("data", []) if isinstance(part, dict) else []:
            x = rec(r.get("symbol"))
            desc = r.get("survDesc") or ""
            x["desc"].append(desc)
            a = ROMAN.get(str(r.get("asmSurvIndicator", "")).replace("Stage", "").strip().upper()) or _stage(desc, "ASM") or 1
            x["asm"] = max(x["asm"] or 0, a)
    try:
        r = ns.s.get(f"{ARCH}/content/equities/suspension.csv", timeout=40)
        if r.ok:
            for row in csv.DictReader(io.StringIO(r.text)):
                row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                if row.get("Symbol"):
                    rec(row["Symbol"])["susp"] = row.get("Date of Suspension") or "listed"
    except Exception as e:  # noqa: BLE001
        print(f"[nse] suspension list: {e}")
    if gsm is None and asm is None:
        return {}
    CACHE.mkdir(parents=True, exist_ok=True)
    SURV.write_text(json.dumps(out, separators=(",", ":")))
    print(f"[nse] surveillance: {sum(1 for x in out.values() if x['gsm'] is not None)} GSM, "
          f"{sum(1 for x in out.values() if x['asm'])} ASM, {sum(1 for x in out.values() if x['susp'])} suspended")
    return out


def a6(x: dict | None) -> tuple:
    """(mark, value) for 'Not suspended, not in NSE GSM stage II+'."""
    if not x:
        return 2, "not on NSE GSM, ASM or suspension lists"
    ibc = " · insolvency (IBC) linked" if any("IBC" in d for d in x["desc"]) else ""
    m, val = _a6(x)
    return m, val + ibc


def _a6(x):
    if x["susp"]:
        return 0, f"suspended ({x['susp']})"
    if (x["gsm"] or 0) >= 2:
        return 0, f"GSM stage {x['gsm']}"
    if x["gsm"] is not None:
        return 1, f"GSM stage {x['gsm']}" + (f" · ASM stage {x['asm']}" if x["asm"] else "")
    if (x["asm"] or 0) >= 2:
        return 1, f"ASM stage {x['asm']}"
    return 2, f"ASM stage {x['asm']} only" if x["asm"] else "not on NSE GSM, ASM or suspension lists"


# ------------------------------------------------------------------ index membership
def indices(ns, today: date, max_age: int = 7) -> dict:
    """{symbol: index label} for the most-discovered broad index a stock is in."""
    if INDEX.exists():
        st = json.loads(INDEX.read_text())
        if (today - date.fromisoformat(st["asof"])).days < max_age and st.get("map"):
            return st["map"]
    mp = {}
    for label, f in reversed(INDICES):  # later (bigger) indices overwrite smaller ones
        try:
            r = ns.s.get(f"{ARCH}/content/indices/{f}.csv", timeout=40)
            r.raise_for_status()
            for row in csv.DictReader(io.StringIO(r.text)):
                s = (row.get("Symbol") or "").strip()
                if s:
                    mp[s] = label
        except Exception as e:  # noqa: BLE001
            print(f"[nse] index {label}: {e}")
            return json.loads(INDEX.read_text())["map"] if INDEX.exists() else {}
    CACHE.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps({"asof": today.isoformat(), "map": mp}, separators=(",", ":")))
    print(f"[nse] index lists: {len(mp)} stocks in {len(INDICES)} broad indices")
    return mp


def index_since(mp: dict, today: date) -> dict:
    """Keeps the first date we saw each stock in its current index (git file; changes only when membership changes)."""
    old = json.loads(SINCE.read_text()) if SINCE.exists() else {}
    new = {s: (old[s] if s in old and old[s][0] == lab else [lab, today.isoformat()]) for s, lab in mp.items()}
    if new != old:
        SINCE.write_text(json.dumps(new, indent=0, sort_keys=True))
    return new


# ------------------------------------------------------------------ one call for run.py
def load(today: date) -> dict:
    """{"deliv": {date: {sym: pct}}, "surv": {...}, "idx": {sym: [label, since]}}; empty parts on failure (checks stay pending)."""
    t0 = time.time()
    out = {"deliv": {}, "surv": {}, "idx": {}}
    try:
        ns = NSESession()
    except Exception as e:  # noqa: BLE001
        print(f"[nse] session failed: {e}")
        return out
    for k, fn in (("deliv", lambda: delivery(ns, today)), ("surv", lambda: surveillance(ns)),
                  ("idx", lambda: index_since(indices(ns, today), today))):
        try:
            out[k] = fn()
        except Exception as e:  # noqa: BLE001
            print(f"[nse] {k} failed: {e}")
    print(f"[nse] daily files loaded in {time.time() - t0:.0f}s")
    return out


def for_symbol(nd: dict, sym: str, bse_code: str | None = None) -> dict | None:
    """Per-stock view for the funnel. BSE-only stocks: delivery from BSE's file; surveillance not covered (no BSE list
    source yet); not in any Nifty index by definition."""
    if sym.endswith(".BO"):
        if not bse_code or bse_code != bse_code or str(bse_code) in ("nan", "None") or not nd.get("deliv"):
            return None
        return {"deliv": delivery_stats(nd["deliv"], f"B:{str(bse_code).lstrip('0')}"), "deliv_ok": True,
                "surv": None, "surv_ok": False, "idx": None, "idx_ok": True}
    if not sym.endswith(".NS") or not any(nd.get(k) for k in ("deliv", "surv", "idx")):
        return None
    c = sym[:-3]
    return {"deliv": delivery_stats(nd.get("deliv") or {}, c) if nd.get("deliv") else None,
            "deliv_ok": bool(nd.get("deliv")), "surv": _live(nd, c), "surv_ok": bool(nd.get("surv")),
            "idx": (nd.get("idx") or {}).get(c), "idx_ok": bool(nd.get("idx"))}


def _live(nd: dict, c: str) -> dict | None:
    """The suspension list keeps old entries (some revoked years ago); a stock that traded in the last 5 sessions is not suspended."""
    x = (nd.get("surv") or {}).get(c)
    if x and x.get("susp"):
        dv = nd.get("deliv") or {}
        if any(c in dv[k] for k in sorted(dv)[-5:]):
            x = {**x, "susp": None}
            if x["gsm"] is None and not x["asm"]:
                return None
    return x
