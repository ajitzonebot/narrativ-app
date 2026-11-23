"""Exact count of listed companies on NSE and BSE, de-duplicated by ISIN, and how our universe maps onto them.

Sources: NSE equity master (mainboard + SME) and BSE active equity scrip list. Output: probe/census.json
"""
import csv
import io
import json
from pathlib import Path

import requests

from narrativ.filings import NSESession

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com", "Accept": "application/json"}


def nse_master(ns, url):
    r = ns.s.get(url, timeout=60)
    rows = list(csv.DictReader(io.StringIO(r.text))) if r.ok else []
    out = {}
    for x in rows:
        x = {k.strip(): (v or "").strip() for k, v in x.items()}
        isin = x.get("ISIN NUMBER") or x.get("ISIN_NUMBER")
        if isin:
            out[isin] = {"sym": x.get("SYMBOL"), "name": x.get("NAME OF COMPANY") or x.get("NAME_OF_COMPANY"), "series": x.get("SERIES")}
    print(f"[census] {url.rsplit('/', 1)[-1]}: {len(rows)} rows, http {r.status_code}")
    return out


def bse_master():
    rows = []
    try:  # 1) bse library (handles BSE cookies/headers)
        from bse import BSE
        with BSE(download_folder=Path("data/exchange_tmp")) as b:
            seen = {}
            for g in ["", "A", "B", "T", "X", "XT", "Z", "ZP", "M", "MT", "MS", "P", "R", "W", "XD", "Y", "F", "G", "E", "IF", "IT", "TS"]:
                try:
                    got = b.listSecurities(segment="Equity", status="Active", group=g)
                except Exception as e:  # noqa: BLE001
                    print(f"[census] group {g!r}: {e}")
                    continue
                for x in got or []:
                    seen[x.get("ISIN_NUMBER") or x.get("SCRIP_CD")] = x
                print(f"[census] group {g!r}: {len(got or [])} rows, {len(seen)} unique so far")
            rows = list(seen.values())
        print(f"[census] bse.listSecurities: {len(rows)} rows")
    except Exception as e:  # noqa: BLE001
        print(f"[census] bse.listSecurities failed: {e}")
    if rows:
        return _bse_rows(rows)
    try:
        r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w", headers=H, timeout=90,
                         params={"Group": "", "Scripcode": "", "industry": "", "segment": "Equity", "status": "Active"})
        print(f"[census] BSE direct http {r.status_code}, {r.headers.get('content-type')}, {r.text[:120]!r}")
        rows = r.json() if r.ok else []
    except Exception as e:  # noqa: BLE001
        print(f"[census] BSE list failed: {e}")
        rows = []
    return _bse_rows(rows)


def _bse_rows(rows):
    out = {}
    for x in rows if isinstance(rows, list) else []:
        isin = (x.get("ISIN_NUMBER") or x.get("ISIN_NO") or x.get("isin") or "").strip()
        if isin.startswith("INE"):  # equity shares of Indian companies (INF = funds, IN9 = partly paid etc.)
            out[isin] = {"code": str(x.get("SCRIP_CD") or x.get("SCRIP_CODE") or x.get("scrip_cd")), "name": x.get("Scrip_Name") or x.get("Issuer_Name"), "group": x.get("GROUP")}
    print(f"[census] BSE active equity: {len(rows) if isinstance(rows, list) else 0} rows, {len(out)} with INE ISIN")
    return out


def main():
    ns = NSESession()
    main_ = nse_master(ns, "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
    sme = nse_master(ns, "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv")
    bse = bse_master()
    nse = {**main_, **sme}
    both = set(nse) & set(bse)
    res = {
        "nse_mainboard": len(main_), "nse_sme": len(sme), "nse_total": len(nse), "bse_active_equity": len(bse),
        "unique_companies": len(set(nse) | set(bse)), "on_both": len(both), "nse_only": len(set(nse) - set(bse)), "bse_only": len(set(bse) - set(nse)),
    }
    # our universe (Yahoo screener, market cap >= 200 cr, de-duplicated by company name)
    p = json.loads(Path("docs/data/picks.json").read_text())["picks"]
    codes = json.loads(Path("data/bse_codes.json").read_text()) if Path("data/bse_codes.json").exists() else {}
    nse_sym = {v["sym"]: k for k, v in nse.items()}
    bse_code = {v["code"]: k for k, v in bse.items()}
    mapped, unmapped = set(), []
    for x in p:
        s = x["s"]
        isin = nse_sym.get(s[:-3]) if s.endswith(".NS") else bse_code.get(str(codes.get(s)))
        (mapped.add(isin) if isin else unmapped.append(s))
    res["universe"] = {
        "companies": len(p), "nse": sum(x["s"].endswith(".NS") for x in p), "bse_only": sum(x["s"].endswith(".BO") for x in p),
        "matched_to_isin": len(mapped), "duplicate_isin": len(p) - len(unmapped) - len(mapped), "unmatched": len(unmapped),
        "unmatched_sample": unmapped[:20],
        "bse_listed_but_also_on_nse": sum(1 for x in p if x["s"].endswith(".BO") and bse_code.get(str(codes.get(x["s"]))) in nse),
        "rule": "Yahoo screener, market cap >= 200 cr, NSE preferred when on both",
    }
    Path("probe").mkdir(exist_ok=True)
    Path("probe/census.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
