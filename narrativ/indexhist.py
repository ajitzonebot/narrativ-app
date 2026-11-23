"""Daily index closes from NSE's index-closing file (ind_close_all, already downloaded for the prices step):
sector indices for rotation, Nifty 500 (rotation benchmark) and India VIX (mood). Yahoo is used once per index, only to
seed its history; after that one row a day comes from the NSE file. Store: data/source_cache/index_hist.json."""
import csv
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

STORE = Path("data/source_cache/index_hist.json")
WINDOW_DAYS = 10
# our label -> (NSE index name in the file, Yahoo ticker used once for history)
NAMES = {"IT": ("Nifty IT", "^CNXIT"), "Auto": ("Nifty Auto", "^CNXAUTO"), "Pharma": ("Nifty Pharma", "^CNXPHARMA"),
         "FMCG": ("Nifty FMCG", "^CNXFMCG"), "Metal": ("Nifty Metal", "^CNXMETAL"), "Realty": ("Nifty Realty", "^CNXREALTY"),
         "Energy": ("Nifty Energy", "^CNXENERGY"), "Bank": ("Nifty Bank", "^NSEBANK"), "PSU Bank": ("Nifty PSU Bank", "^CNXPSUBANK"),
         "Infra": ("Nifty Infrastructure", "^CNXINFRA"), "Media": ("Nifty Media", "^CNXMEDIA"), "PSE": ("Nifty PSE", "^CNXPSE"),
         "Commodities": ("Nifty Commodities", "^CNXCMDT"), "Consumption": ("Nifty India Consumption", "^CNXCONSUM"),
         "Fin Services": ("Nifty Financial Services", "NIFTY_FIN_SERVICE.NS"), "Nifty 500": ("Nifty 500", "^CRSLDX"),
         "India VIX": ("India VIX", "^INDIAVIX")}


def _date(s: str):
    for f in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip().title(), f).date()
        except ValueError:
            continue
    return None


def update(today: date) -> dict:
    from .bhav import _get
    st = json.loads(STORE.read_text()) if STORE.exists() else {}
    seeded, rows = [], 0
    missing = [k for k in NAMES if len(st.get(k) or {}) < 200]
    if missing:  # one-time history from Yahoo
        try:
            import yfinance as yf
            d = yf.download([NAMES[k][1] for k in missing], period="5y", interval="1d", auto_adjust=True, progress=False)["Close"]
            d = d.to_frame() if isinstance(d, pd.Series) else d
            for k in missing:
                t = NAMES[k][1]
                if t in d:
                    ser = d[t].dropna()
                    if len(ser) > 200:
                        st[k] = {**{str(i.date()): round(float(v), 4) for i, v in ser.items()}, **(st.get(k) or {})}
                        seeded.append(k)
        except Exception as e:  # noqa: BLE001
            print(f"[indices] Yahoo seed failed: {e}")
    ns = None
    try:
        from .filings import NSESession
        ns = NSESession()
    except Exception as e:  # noqa: BLE001
        print(f"[indices] NSE session failed: {e}")
    if ns:
        want = {v[0].lower(): k for k, v in NAMES.items()}
        for i in range(WINDOW_DAYS, -1, -1):
            d = today - timedelta(days=i)
            try:
                t = _get(f"idx_{d:%Y%m%d}.csv", f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv", ns.s)
            except Exception as e:  # noqa: BLE001
                print(f"[indices] {d}: {e}")
                continue
            for r in csv.DictReader(io.StringIO(t or "")):
                k = want.get((r.get("Index Name") or "").strip().lower())
                td = _date(r.get("Index Date") or "")
                try:
                    c = float(r.get("Closing Index Value"))
                except (TypeError, ValueError):
                    continue
                if k and td:
                    st.setdefault(k, {})[str(td)] = c  # the exchange's figure replaces Yahoo's for the same day
                    rows += 1
    cut = str(today - timedelta(days=5 * 366))
    st = {k: dict(sorted((d, v) for d, v in s.items() if d >= cut)) for k, s in st.items()}
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(st, separators=(",", ":")))
    print(f"[indices] {len(st)} indices, {rows} NSE closes read" + (f", seeded from Yahoo: {', '.join(seeded)}" if seeded else "")
          + f"; latest {max((max(s) for s in st.values() if s), default='–')}")
    return st


def series(st: dict, name: str) -> pd.Series:
    s = st.get(name) or {}
    return pd.Series({pd.Timestamp(d): v for d, v in s.items()}, dtype=float).sort_index()
