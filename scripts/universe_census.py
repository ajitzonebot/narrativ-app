"""Exchange-sourced universe count: non-SME companies with market cap >= 200 cr, NSE + BSE, de-duplicated by ISIN.

NSE: official daily market-cap file (PR zip, mcapDDMMYYYY.csv). BSE: active equity list (all groups) + market cap per
BSE-only company from BSE's quote header API. Output: probe/universe_census.json (+ data/universe_exchange.json list).
"""
import csv
import io
import json
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

from narrativ.filings import NSESession

MIN_CR = 200
SME_NSE = {"SM", "ST", "SZ"}
NON_EQ = {"IV", "RR", "IT"}  # InvIT / REIT units
SME_BSE = {"M", "MT", "MS"}


def nse_mcap(ns):
    d = date.today()
    for _ in range(7):
        tag = d.strftime("%d%m%y")
        r = ns.s.get(f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{tag}.zip", timeout=60)
        if r.ok and r.content[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(r.content))
            n = next(x for x in z.namelist() if x.lower().startswith("mcap"))
            rows = [{k.strip(): (v or "").strip() for k, v in x.items()} for x in csv.DictReader(io.StringIO(z.read(n).decode("latin1")))]
            print(f"[uc] NSE {n}: {len(rows)} rows")
            return str(d), rows
        d -= timedelta(days=1)
    return None, []


def nse_isin(ns):
    out = {}
    for u in ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"):
        for i in range(4):
            r = ns.s.get(u, timeout=60)
            if r.ok and r.text.lstrip().upper().startswith("SYMBOL"):
                break
            print(f"[uc] {u.rsplit('/', 1)[-1]} try {i + 1}: http {r.status_code}, {r.text[:60]!r}")
            ns._warm()
            time.sleep(5 * (i + 1))
        else:
            raise SystemExit(f"NSE list unavailable: {u}")
        for x in csv.DictReader(io.StringIO(r.text)):
            x = {k.strip(): (v or "").strip() for k, v in x.items() if k}
            if x.get("SYMBOL"):
                out[x["SYMBOL"]] = x.get("ISIN NUMBER")
    return out


def bse_list():
    from bse import BSE
    seen = {}
    with BSE(download_folder=Path("data/exchange_tmp")) as b:
        for g in ["A", "B", "T", "X", "XT", "Z", "ZP", "M", "MT", "MS", "P", "R", "W", "XD", "Y", "F", "G", "E", "IF", "TS", ""]:
            try:
                for x in b.listSecurities(segment="Equity", status="Active", group=g) or []:
                    x["_g"] = g or x.get("GROUP")
                    seen[x.get("ISIN_NUMBER") or x.get("SCRIP_CD")] = x
            except Exception as e:  # noqa: BLE001
                print(f"[uc] BSE group {g!r}: {e}")
        sess = getattr(b, "session", None) or getattr(b, "s", None)
    print(f"[uc] BSE list {len(seen)} rows; keys sample {list(next(iter(seen.values())).keys())[:12] if seen else None}")
    return seen


def bse_mcap(codes, max_minutes=30):
    """{scripcode: mcap_cr} via BSE quote header (same API family the bse library uses)."""
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
                      "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com", "Accept": "application/json, text/plain, */*"})
    try:
        s.get("https://www.bseindia.com/", timeout=20)
    except Exception:  # noqa: BLE001
        pass
    out, t0, fail, sample = {}, time.time(), 0, None
    for i, c in enumerate(codes):
        if time.time() - t0 > max_minutes * 60:
            print(f"[uc] BSE mcap time cap after {i}")
            break
        try:
            r = s.get("https://api.bseindia.com/BseIndiaAPI/api/StockTrading/w", params={"flag": "", "quotetype": "EQ", "scripcode": c}, timeout=20)
            js = r.json() if r.ok else {}
            sample = sample or js
            v = js.get("MktCapFull") or js.get("MktCapFF")
            if v not in (None, "", "-"):
                out[c] = float(str(v).replace(",", ""))
            else:
                fail += 1
        except Exception:  # noqa: BLE001
            fail += 1
        time.sleep(0.25)
        if i % 300 == 0:
            print(f"[uc] BSE mcap {i}/{len(codes)}, got {len(out)}, fail {fail}")
    print(f"[uc] BSE mcap got {len(out)} of {len(codes)}; sample {str(sample)[:300]}")
    return out


def main():
    ns = NSESession()
    asof, rows = nse_mcap(ns)
    isin_of = nse_isin(ns)
    nse = {}
    for r in rows:
        try:
            m = float(r["Market Cap(Rs.)"]) / 1e7
        except (ValueError, KeyError):
            continue
        s, se = r["Symbol"], r["Series"]
        if se in NON_EQ or not s or s in ("Total", "Listed", "Permitted"):
            continue
        e = nse.setdefault(s, {"sme": True, "mcap": 0, "isin": isin_of.get(s), "name": r["Security Name"]})
        e["sme"] = e["sme"] and se in SME_NSE
        e["mcap"] = max(e["mcap"], m)
    nse_isins = {v["isin"] for v in nse.values() if v["isin"]}
    bl = bse_list()
    bse_only = {i: x for i, x in bl.items() if str(i).startswith("INE") and i not in nse_isins}
    b_sme = {i for i, x in bse_only.items() if (x.get("_g") or x.get("GROUP") or "").strip() in SME_BSE}
    b_main = {i: x for i, x in bse_only.items() if i not in b_sme}
    ref = bl.get("INE002A01018") or {}
    print(f"[uc] unit check, Reliance BSE Mktcap field = {ref.get('Mktcap')!r} (NSE file: {next((v['mcap'] for v in nse.values() if v['isin'] == 'INE002A01018'), None)} cr)")
    def _f(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None
    nse_cr, bse_raw = next((v["mcap"] for v in nse.values() if v["isin"] == "INE002A01018"), None), _f(ref.get("Mktcap"))
    scale = (nse_cr / bse_raw) if nse_cr and bse_raw else None  # BSE field unit, calibrated on Reliance
    if scale:
        scale = min((1, 1e-7, 1e-5, 1e-2, 100, 0.01), key=lambda k: abs(k - scale) / max(k, scale))
    print(f"[uc] BSE Mktcap -> cr scale {scale}")
    mc = {str(x.get("SCRIP_CD")): _f(x.get("Mktcap")) * scale for x in b_main.values() if scale and _f(x.get("Mktcap")) is not None}
    b_big = {i: x for i, x in b_main.items() if mc.get(str(x.get("SCRIP_CD")), 0) >= MIN_CR}
    n_main = {s: v for s, v in nse.items() if not v["sme"]}
    n_big = {s: v for s, v in n_main.items() if v["mcap"] >= MIN_CR}
    res = {
        "asof_nse": asof,
        "nse": {"companies": len(nse), "mainboard": len(n_main), "sme": len(nse) - len(n_main), "mainboard_ge200": len(n_big),
                "sme_ge200": sum(1 for v in nse.values() if v["sme"] and v["mcap"] >= MIN_CR)},
        "bse_only": {"companies": len(bse_only), "sme": len(b_sme), "mainboard": len(b_main), "mcap_found": len(mc), "mainboard_ge200": len(b_big),
                     "groups": {g: sum(1 for x in bse_only.values() if (x.get("_g") or "") == g) for g in sorted({x.get("_g") or "" for x in bse_only.values()})}},
        "universe_target": len(n_big) + len(b_big),
    }
    p = json.loads(Path("docs/data/picks.json").read_text())["picks"]
    cur_ns = {x["s"][:-3] for x in p if x["s"].endswith(".NS")}
    res["vs_current"] = {"current": len(p), "nse_missing": sorted(set(n_big) - cur_ns, key=lambda s: -n_big[s]["mcap"])[:60],
                         "nse_missing_n": len(set(n_big) - cur_ns), "nse_current_below_200_or_sme": len(cur_ns - set(n_big))}
    Path("probe").mkdir(exist_ok=True)
    Path("probe/universe_census.json").write_text(json.dumps(res, indent=1))
    Path("data/universe_exchange.json").write_text(json.dumps({
        "asof": asof, "rule": "non-SME, market cap >= 200 cr, NSE preferred, ISIN de-duplicated",
        "nse": {s: {"isin": v["isin"], "mcap_cr": round(v["mcap"])} for s, v in sorted(n_big.items())},
        "bse": {str(x.get("SCRIP_CD")): {"isin": i, "id": x.get("scrip_id") or x.get("SCRIP_ID"), "mcap_cr": round(mc[str(x.get("SCRIP_CD"))])}
                for i, x in sorted(b_big.items())},
    }, indent=0))
    print(json.dumps({k: v for k, v in res.items() if k != "vs_current"}, indent=1), res["vs_current"]["nse_missing_n"])


if __name__ == "__main__":
    main()
