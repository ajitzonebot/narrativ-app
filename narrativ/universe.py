"""Exchange-sourced universe: non-SME companies with market cap >= MIN_MCAP, NSE + BSE, one row per ISIN.

NSE: official daily market-cap file (PR zip -> mcapDDMMYYYY.csv) + equity master for ISINs.
BSE: active equity list (all groups) with BSE's own market cap; SME groups M/MT/MS excluded. NSE preferred when on both.
Fallbacks: last good list in data/universe_exchange.json (membership only), so a failed download never empties the universe.
"""
import csv
import io
import json
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config
from .filings import NSESession

SME_NSE = {"SM", "ST", "SZ"}
NON_EQ = {"IV", "RR", "IT"}  # InvIT / REIT units
SME_BSE = {"M", "MT", "MS"}
BSE_GROUPS = ["A", "B", "T", "X", "XT", "Z", "ZP", "M", "MT", "MS", "P", "R", "W", "XD", "Y", "F", "E", "IF", "TS", "IP", ""]
LAST = Path("data/universe_exchange.json")
BSE_CACHE = Path("data/source_cache/bse_list.json")


def _nse_mcap(ns, today: date):
    d = today
    for _ in range(8):
        r = ns.s.get(f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{d.strftime('%d%m%y')}.zip", timeout=60)
        if r.ok and r.content[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(r.content))
            n = next(x for x in z.namelist() if x.lower().startswith("mcap"))
            rows = [{k.strip(): (v or "").strip() for k, v in x.items() if k} for x in csv.DictReader(io.StringIO(z.read(n).decode("latin1")))]
            return str(d), rows
        d -= timedelta(days=1)
    return None, []


def _nse_master(ns) -> dict:
    out = {}
    for u in ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
              "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"):
        for i in range(4):
            r = ns.s.get(u, timeout=60)
            if r.ok and r.text.lstrip().upper().startswith("SYMBOL"):
                break
            ns._warm()
            time.sleep(5 * (i + 1))
        else:
            raise RuntimeError(f"NSE master unavailable: {u}")
        for x in csv.DictReader(io.StringIO(r.text)):
            x = {k.strip(): (v or "").strip() for k, v in x.items() if k}
            if x.get("SYMBOL"):
                ld = None
                try:
                    ld = datetime.strptime(x.get("DATE OF LISTING", "").title(), "%d-%b-%Y").date().isoformat()
                except ValueError:
                    pass
                out[x["SYMBOL"]] = {"isin": x.get("ISIN NUMBER"), "name": x.get("NAME OF COMPANY"), "listed": ld}
    return out


def bse_list(max_age_days: int = 7) -> dict:
    """ISIN -> BSE row (SCRIP_CD, scrip_id, GROUP, Mktcap in cr, Issuer_Name). Weekly, cached in the Actions cache."""
    if BSE_CACHE.exists():
        c = json.loads(BSE_CACHE.read_text())
        if (date.today() - date.fromisoformat(c["date"])).days < max_age_days and len(c["rows"]) > 3000:
            return c["rows"]
    seen = {}
    try:
        from bse import BSE
        with BSE(download_folder=Path("data/exchange_tmp")) as b:
            for g in BSE_GROUPS:
                for attempt in range(2):
                    try:
                        for x in b.listSecurities(segment="Equity", status="Active", group=g) or []:
                            i = (x.get("ISIN_NUMBER") or "").strip()
                            if i.startswith("INE"):
                                seen[i] = {k: x.get(k) for k in ("SCRIP_CD", "scrip_id", "GROUP", "Mktcap", "Issuer_Name", "Scrip_Name", "INDUSTRY")}
                        break
                    except Exception as e:  # noqa: BLE001
                        if "not a valid" in str(e):
                            break
                        time.sleep(3)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] BSE list failed: {e}")
    if len(seen) > 3000:
        BSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        BSE_CACHE.write_text(json.dumps({"date": str(date.today()), "rows": seen}))
        return seen
    if BSE_CACHE.exists():
        print("[universe] BSE list incomplete, using cached copy")
        return json.loads(BSE_CACHE.read_text())["rows"]
    return seen


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def build(today: date) -> tuple[list[dict], dict]:
    """-> rows [{symbol, isin, name, exch, mcap_cr, close, bse_code}], stats."""
    ns = NSESession()
    asof, rows = _nse_mcap(ns, today)
    master = _nse_master(ns)
    nse = {}
    for r in rows:
        s, se = r.get("Symbol"), r.get("Series")
        m = _f(r.get("Market Cap(Rs.)"))
        if not s or m is None or se in NON_EQ or s in ("Total", "Listed", "Permitted"):
            continue
        e = nse.setdefault(s, {"sme": True, "mcap": 0.0, "close": None, "name": r.get("Security Name")})
        e["sme"] = e["sme"] and se in SME_NSE
        if m / 1e7 >= e["mcap"]:  # several equity series: keep the largest (m is rupees, mcap crore)
            e["mcap"], e["close"] = m / 1e7, _f(r.get("Close Price/Paid up value(Rs.)"))
    nse_isins = {v["isin"] for v in master.values() if v.get("isin")}
    bl = bse_list()
    code_of_isin = {i: str(x.get("SCRIP_CD")) for i, x in bl.items()}
    out = []
    for s, e in nse.items():
        if e["sme"] or e["mcap"] < config.MIN_MCAP / 1e7:
            continue
        isin = (master.get(s) or {}).get("isin")
        out.append({"symbol": f"{s}.NS", "isin": isin, "name": (master.get(s) or {}).get("name") or e["name"], "exch": "NSE",
                    "mcap_cr": round(e["mcap"], 1), "close": e["close"], "bse_code": code_of_isin.get(isin),
                    "listed": (master.get(s) or {}).get("listed")})
    n_bse = 0
    for i, x in bl.items():
        if i in nse_isins or (x.get("GROUP") or "").strip() in SME_BSE:
            continue
        m = _f(x.get("Mktcap"))
        if m is None or m < config.MIN_MCAP / 1e7 or not x.get("scrip_id"):
            continue
        n_bse += 1
        out.append({"symbol": f"{str(x['scrip_id']).strip()}.BO", "isin": i, "name": x.get("Issuer_Name") or x.get("Scrip_Name"), "exch": "BSE",
                    "mcap_cr": round(m, 1), "close": None, "bse_code": str(x.get("SCRIP_CD"))})
    stats = {"asof": asof, "listed_unique": len(nse_isins | set(bl)), "nse_companies": len(master), "bse_companies": len(bl),
             "universe": len(out), "nse": len(out) - n_bse, "bse_only": n_bse}
    ok = asof and len(out) > 1500 and n_bse > 50
    if ok:
        LAST.write_text(json.dumps({"asof": asof, "rule": f"non-SME, market cap >= {config.MIN_MCAP / 1e7:.0f} cr, NSE preferred, one row per ISIN",
                                    "stocks": {r["symbol"]: [r["isin"], r["bse_code"]] for r in sorted(out, key=lambda r: r["symbol"])}}, indent=0))
    elif LAST.exists():
        last = json.loads(LAST.read_text())
        if "stocks" in last:
            print(f"[universe] exchange lists incomplete ({stats}); using last good list from {last['asof']}")
            have = {r["symbol"] for r in out}
            out += [{"symbol": s, "isin": v[0], "name": None, "exch": "NSE" if s.endswith(".NS") else "BSE", "mcap_cr": None, "close": None,
                     "bse_code": v[1]} for s, v in last["stocks"].items() if s not in have]
            stats["fallback"] = last["asof"]
    print(f"[universe] {stats}")
    return out, stats


def aliases(rows: list[dict], bse_codes: dict) -> dict:
    """Old .BO symbol -> current symbol for the same company (e.g. a BSE listing that moved to NSE)."""
    by_code = {r["bse_code"]: r["symbol"] for r in rows if r.get("bse_code")}
    return {old: by_code[str(code)] for old, code in bse_codes.items() if old.endswith(".BO") and str(code) in by_code and by_code[str(code)] != old}
