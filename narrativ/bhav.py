"""Exchange end-of-day files (one per trading day, free, no login), cached under data/source_cache/bhav/:
- NSE  products/content/sec_bhavdata_full_DDMMYYYY.csv  : OHLC, volume, PREV_CLOSE (adjusted by NSE for splits / bonus / rights)
- NSE  content/indices/ind_close_all_DDMMYYYY.csv       : index OHLC (Nifty 50 = benchmark)
- BSE  download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV : same for BSE (UDiFF format), keyed by scrip code
Each returns {key: (open, high, low, close, volume, prev_close), "_date": trading date printed in the file}, {} when the file is not
published (holiday / not yet), None on error. Always key by "_date": on a holiday NSE can serve the previous day's file."""
import csv
import io
import re
from datetime import date, datetime
from pathlib import Path

import requests

DIR = Path("data/source_cache/bhav")
ARCH = "https://nsearchives.nseindia.com"
BSE_H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/"}
KEEP = 15  # cached files kept


def _f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _get(name: str, url: str, sess=None) -> str | None:
    """Cached text of one daily file; '' when not published (404 / HTML page)."""
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / name
    if p.exists():
        return p.read_text()
    r = (sess or requests).get(url, headers=None if sess else BSE_H, timeout=60)
    if r.status_code == 404 or r.text.lstrip().startswith("<"):
        try:  # no file for a day 3+ days back: remember it, so weekends and holidays are asked once
            d = datetime.strptime(re.search(r"(\d{8})", name).group(1), "%Y%m%d").date()
            if (date.today() - d).days >= 3:
                p.write_text("")
        except Exception:  # noqa: BLE001
            pass
        return ""
    r.raise_for_status()
    p.write_text(r.text)
    for old in sorted(DIR.glob("*"), key=lambda x: x.stat().st_mtime)[:-KEEP * 3]:
        old.unlink()
    return r.text


def nse(ns, d: date) -> dict | None:
    try:
        t = _get(f"nse_{d:%Y%m%d}.csv", f"{ARCH}/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv", ns.s)
    except Exception as e:  # noqa: BLE001
        print(f"[bhav] NSE {d}: {e}")
        return None
    out, rank = {}, {"EQ": 0, "BE": 1, "BZ": 2}
    rows = csv.reader(io.StringIO(t or ""))
    head = [h.strip() for h in next(rows, [])]
    if "CLOSE_PRICE" not in head:
        return {}
    ix = {h: i for i, h in enumerate(head)}
    best = {}
    for row in rows:
        row = [c.strip() for c in row]
        if len(row) < len(head) or row[ix["SERIES"]] not in rank:
            continue
        sym, ser = row[ix["SYMBOL"]], row[ix["SERIES"]]
        if "_date" not in out and "DATE1" in ix:
            out["_date"] = row[ix["DATE1"]]
        if sym in best and best[sym] <= rank[ser]:
            continue
        c = _f(row[ix["CLOSE_PRICE"]])
        if not c:
            continue
        best[sym] = rank[ser]
        out[sym] = (_f(row[ix["OPEN_PRICE"]]), _f(row[ix["HIGH_PRICE"]]), _f(row[ix["LOW_PRICE"]]), c,
                    _f(row[ix["TTL_TRD_QNTY"]]) or 0.0, _f(row[ix["PREV_CLOSE"]]))
    return out


def index(ns, d: date, name: str = "Nifty 50") -> tuple | None:
    try:
        t = _get(f"idx_{d:%Y%m%d}.csv", f"{ARCH}/content/indices/ind_close_all_{d:%d%m%Y}.csv", ns.s)
    except Exception as e:  # noqa: BLE001
        print(f"[bhav] index {d}: {e}")
        return None
    for r in csv.DictReader(io.StringIO(t or "")):
        if (r.get("Index Name") or "").strip().lower() == name.lower():
            return (r.get("Index Date") or "").strip(), (_f(r.get("Open Index Value")), _f(r.get("High Index Value")), _f(r.get("Low Index Value")),
                    _f(r.get("Closing Index Value")), _f(r.get("Volume")) or 0.0, None)
    return None


def bse(d: date) -> dict | None:
    try:
        t = _get(f"bse_{d:%Y%m%d}.csv", f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV")
    except Exception as e:  # noqa: BLE001
        print(f"[bhav] BSE {d}: {e}")
        return None
    out = {}
    for r in csv.DictReader(io.StringIO(t or "")):
        out.setdefault("_date", (r.get("TradDt") or "").strip())
        code, c = (r.get("FinInstrmId") or "").strip(), _f(r.get("ClsPric"))
        if code and c:
            out[code] = (_f(r.get("OpnPric")), _f(r.get("HghPric")), _f(r.get("LwPric")), c, _f(r.get("TtlTradgVol")) or 0.0, _f(r.get("PrvsClsgPric")))
    return out
