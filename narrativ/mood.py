"""Market mood (0-100), own composite from open data. Replaces the RISK ON / CAUTION / RISK OFF rule.

Each input is turned into a percentile of its own last 3 years (756 sessions); fear-type inputs (India VIX, put-call
ratio) are inverted so that high always means greed. The index is the plain average of the inputs available today.
Inputs without a long history (NSE put-call ratio, FII/DII flows) are stored daily in data/mood_history.json and join
the average once 20 days are stored.
Zones: Extreme fear < 25 · Fear 25-45 · Neutral 45-55 · Greed 55-75 · Extreme greed > 75.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HIST = Path("data/mood_history.json")
WIN = 756
ZONES = [(25, "Extreme fear"), (45, "Fear"), (55, "Neutral"), (75, "Greed"), (101, "Extreme greed")]
HINT = {
    "Extreme fear": "Prices are depressed across the market. Review Undervalued quality and Value watch names; stage entries.",
    "Fear": "Selective market. Favour quality names with a live entry setup.",
    "Neutral": "No strong signal from the market as a whole.",
    "Greed": "Be choosy on entries; skip extended names.",
    "Extreme greed": "Froth: tighten stops, skip extended names, size positions smaller.",
}


def zone(x):
    for th, z in ZONES:
        if x < th:
            return z
    return "Extreme greed"


def _pct(s: pd.Series, at=None):
    s = s.dropna()
    if at is not None:
        s = s[s.index <= at]
    if len(s) < 60:
        return None
    w = s.iloc[-WIN:]
    return float((w.iloc[:-1] < w.iloc[-1]).mean() * 100)


def _pcr_day(ns, d: date):
    """(trading date, Nifty put OI ÷ call OI, all expiries) from the F&O UDiFF bhavcopy; None if no file."""
    import csv
    import io
    import zipfile
    r = ns.s.get(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip", timeout=60)
    if r.status_code != 200 or r.content[:2] != b"PK":
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    ce = pe = 0.0
    td = None
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x.get("TckrSymb") == "NIFTY" and x.get("OptnTp") in ("CE", "PE"):
            oi = float(x.get("OpnIntrst") or 0)
            td = td or x.get("TradDt")
            if x["OptnTp"] == "CE":
                ce += oi
            else:
                pe += oi
    return (str(td)[:10], round(pe / ce, 3)) if ce and td else None


def _nse_inputs(today: date, hist: dict) -> None:
    try:
        from .filings import NSESession, BASE
        ns = NSESession()
    except Exception as e:  # noqa: BLE001
        print(f"[mood] NSE session failed: {e}")
        return
    try:  # Nifty put-call ratio (open interest) from NSE's daily F&O end-of-day file; first run loads ~90 days
        pcr = hist.setdefault("pcr", {})
        back = 10 if len(pcr) >= 40 else 130
        n = 0
        for i in range(back, -1, -1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5 or str(d) in pcr:
                continue
            v = _pcr_day(ns, d)
            if v:
                pcr[v[0]] = v[1]
                n += 1
        print(f"[mood] put-call ratio: {n} day(s) added, {len(pcr)} stored")
    except Exception as e:  # noqa: BLE001
        print(f"[mood] put-call ratio: {e}")
    try:
        rows = ns.get(BASE + "/api/fiidiiTradeReact") or []
        for r in rows:
            cat = str(r.get("category", "")).upper()
            d = pd.to_datetime(r.get("date"), format="%d-%b-%Y", errors="coerce")
            net = float(str(r.get("netValue", "")).replace(",", "")) if r.get("netValue") not in (None, "") else None
            if pd.isna(d) or net is None:
                continue
            key = "fii" if "FII" in cat or "FPI" in cat else "dii" if "DII" in cat else None
            if key:
                hist.setdefault(key, {})[str(d.date())] = net
    except Exception as e:  # noqa: BLE001
        print(f"[mood] FII/DII: {e}")


def compute(px: dict, bench: pd.Series, today: date) -> dict:
    hist = json.loads(HIST.read_text()) if HIST.exists() else {}
    closes = pd.concat({s: d["Close"] for s, d in px.items() if len(d) >= 300}, axis=1).sort_index()
    closes = closes[closes.index >= closes.index[-1] - pd.Timedelta(days=4 * 365 + 300)]
    sma200 = closes.rolling(200).mean()
    valid = sma200.notna().sum(axis=1)
    breadth = ((closes > sma200).sum(axis=1) / valid * 100).where(valid >= 200)
    hi = closes >= closes.rolling(252).max()
    lo = closes <= closes.rolling(252).min()
    v252 = closes.rolling(252).max().notna().sum(axis=1)
    hl = ((hi.sum(axis=1) - lo.sum(axis=1)) / v252 * 100).where(v252 >= 200)
    chg = closes.diff()
    adv, dec = (chg > 0).sum(axis=1), (chg < 0).sum(axis=1)
    ad = (adv / dec.where(dec > 0)).rolling(10).mean()
    dist = (bench / bench.rolling(200).mean() - 1) * 100
    try:  # NSE index-closing file (stored by narrativ.indexhist, refreshed by the rotation step earlier in the run)
        from . import indexhist
        vix = indexhist.series(json.loads(indexhist.STORE.read_text()) if indexhist.STORE.exists() else {}, "India VIX").dropna()
    except Exception as e:  # noqa: BLE001
        print(f"[mood] VIX: {e}")
        vix = pd.Series(dtype=float)
    _nse_inputs(today, hist)

    def stored(key, roll=None):
        d = hist.get(key) or {}
        s = pd.Series({pd.Timestamp(k): v for k, v in d.items()}).sort_index()
        return s.rolling(roll).sum().dropna() if roll and len(s) >= roll else (s if not roll else pd.Series(dtype=float))

    spec = [  # key, name, series, invert, unit, source, decimals
        ("vix", "India VIX", vix, True, "", "India VIX (NSE index-closing file)", 2),
        ("nifty_200", "Nifty 50 vs its 200-day average", dist, False, "%", "Nifty 50 (NSE index closing file)", 1),
        ("breadth", "Stocks above their 200-day average", breadth, False, "%", "Our universe, daily closes", 1),
        ("highs_lows", "52-week highs minus lows", hl, False, "% of stocks", "Our universe, daily closes", 1),
        ("adv_dec", "Advance/decline ratio, 10-day average", ad, False, "", "Our universe, daily closes", 2),
        ("pcr", "Nifty put-call ratio (open interest)", stored("pcr"), True, "", "NSE F&O end-of-day file (Nifty options, open interest)", 2),
        ("fii", "FII net cash buying, 10-day sum", stored("fii", 10), False, "₹ cr", "NSE FII/DII daily data", 0),
    ]
    inputs, scores = [], []
    for key, name, s, inv, unit, src, nd in spec:
        s = s.dropna() if len(s) else s
        if not len(s):
            inputs.append({"k": key, "name": name, "src": src, "note": "not available today"})
            continue
        p = _pct(s) if len(s) >= (20 if key in ("pcr", "fii") else 60) else None
        sc = None if p is None else (100 - p if inv else p)
        row = {"k": key, "name": name, "value": round(float(s.iloc[-1]), nd), "unit": unit, "asof": str(s.index[-1].date()), "src": src,
               "pct": None if p is None else round(p), "score": None if sc is None else round(sc), "fear_when": "high" if inv else "low"}
        if sc is None:
            row["note"] = f"building history ({len(s)} days stored, needs 20)"
        else:
            scores.append(sc)
            past = _pct(s, s.index[-1] - pd.Timedelta(days=30)) if len(s) > 80 else None
            if past is not None:
                row["chg_1m"] = round((sc - (100 - past if inv else past)))
        inputs.append(row)
    if hist.get("dii"):
        d = stored("dii", 10)
        if len(d):
            inputs.append({"k": "dii", "name": "DII net cash buying, 10-day sum (context)", "value": round(float(d.iloc[-1])), "unit": "₹ cr",
                           "asof": str(d.index[-1].date()), "src": "NSE FII/DII daily data", "note": "shown for context, not scored"})
    if not scores:
        return {}
    score = round(sum(scores) / len(scores))
    # 1-month trend from the price-based inputs (the ones with 3 years of history)
    series = []
    idx = closes.index[-22:]
    for d_ in idx:
        ps = []
        for key, name, s, inv, *_ in spec[:5]:
            p = _pct(s, d_) if len(s) else None
            if p is not None:
                ps.append(100 - p if inv else p)
        if ps:
            series.append([str(d_.date()), round(sum(ps) / len(ps))])
    hist.setdefault("index", {})[str(today)] = score
    for k in ("pcr", "fii", "dii", "index"):
        if k in hist:
            hist[k] = dict(sorted(hist[k].items())[-900:])
    HIST.parent.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps(hist, separators=(",", ":")))
    movers = sorted([i for i in inputs if i.get("chg_1m") is not None], key=lambda i: -abs(i["chg_1m"]))[:2]
    z = zone(score)
    return {"score": score, "zone": z, "hint": HINT[z], "n_inputs": len(scores), "inputs": inputs, "series": series,
            "chg_1m": (score - series[0][1]) if series else None,
            "movers": [f"{m['name']} {'+' if m['chg_1m'] >= 0 else ''}{m['chg_1m']}" for m in movers],
            "method": "Average of each input's percentile vs its own last 3 years; VIX and put-call ratio inverted. Zones: <25 extreme fear, 25-45 fear, 45-55 neutral, 55-75 greed, >75 extreme greed."}
