"""Sector and industry rotation, computed from weekly closes.

RS ratio    = 100 × (group / Nifty 500) ÷ its 10-week average      (>100: outperforming)
RS momentum = 100 × RS ratio ÷ RS ratio 4 weeks ago                 (>100: outperformance improving)
Quadrants: Leading (ratio≥100, mom≥100), Weakening (ratio≥100, mom<100), Lagging (both <100), Improving (ratio<100, mom≥100).
Sectors use NSE sector indices (NSE index-closing file; Yahoo only seeded the history once). Industries are equal-weighted from our own universe (>= 5 stocks).
"""
import pandas as pd

BENCH = "^CRSLDX"  # Nifty 500
SECTORS = {"IT": "^CNXIT", "Auto": "^CNXAUTO", "Pharma": "^CNXPHARMA", "FMCG": "^CNXFMCG", "Metal": "^CNXMETAL",
           "Realty": "^CNXREALTY", "Energy": "^CNXENERGY", "Bank": "^NSEBANK", "PSU Bank": "^CNXPSUBANK",
           "Infra": "^CNXINFRA", "Media": "^CNXMEDIA", "PSE": "^CNXPSE", "Commodities": "^CNXCMDT",
           "Consumption": "^CNXCONSUM", "Fin Services": "NIFTY_FIN_SERVICE.NS"}
MIN_MEMBERS = 5


def _quad(r, m):
    return "Leading" if r >= 100 and m >= 100 else "Weakening" if r >= 100 else "Improving" if m >= 100 else "Lagging"


def _rs(series: pd.Series, bench_w: pd.Series) -> dict | None:
    w = series.resample("W-FRI").last().dropna()
    b = bench_w.reindex(w.index).ffill()
    rs = 100 * w / b
    ratio = 100 * rs / rs.rolling(10).mean()
    mom = 100 * ratio / ratio.shift(4)
    if ratio.dropna().empty or mom.dropna().empty or pd.isna(ratio.iloc[-1]) or pd.isna(mom.iloc[-1]):
        return None
    d = series.dropna()

    def ret(n):
        return round((d.iloc[-1] / d.iloc[-1 - n] - 1) * 100, 1) if len(d) > n else None
    r, m = round(float(ratio.iloc[-1]), 2), round(float(mom.iloc[-1]), 2)
    lo = d.iloc[-126:]  # the move's start: the lowest close of the last 6 months (narrativ/industrywhy.py "before" test)
    lo_at = lo.idxmin() if len(lo) else None
    return {"ratio": r, "mom": m, "q": _quad(r, m), "r1w": ret(5), "r1m": ret(21), "r3m": ret(63),
            "asof": str(d.index[-1].date()), "low_date": str(lo_at.date()) if lo_at is not None else None,
            "from_low_pct": round((d.iloc[-1] / lo.min() - 1) * 100, 1) if len(lo) and lo.min() > 0 else None}


def sectors(today=None) -> tuple[dict, pd.Series | None]:
    """Sector indices and the Nifty 500 from NSE's daily index-closing file (narrativ.indexhist)."""
    from datetime import date
    from . import indexhist
    try:
        st = indexhist.update(today or date.today())
    except Exception as e:  # noqa: BLE001
        print(f"[rotation] index history failed: {e}")
        return {}, None
    bench = indexhist.series(st, "Nifty 500").iloc[-260:]
    if len(bench) < 120:
        return {}, None
    bw = bench.resample("W-FRI").last()
    out = {}
    for name in SECTORS:
        ser = indexhist.series(st, name).iloc[-260:]
        if ser.notna().sum() > 120:
            r = _rs(ser.dropna(), bw)
            if r:
                out[name] = r | {"ticker": indexhist.NAMES[name][0]}
    return out, bench


def industries(px: dict, members: dict, bench: pd.Series | None = None) -> dict:
    """px: symbol -> OHLCV df; members: symbol -> industry.
    Benchmark = equal-weight of the whole universe, so the map shows which industries lead *within* the stocks we
    track (small caps can lag the Nifty 500 as a block, which would put every industry in one quadrant)."""
    groups: dict[str, list] = {}
    allc = []
    for s, ind in members.items():
        if not isinstance(ind, str) or not ind or ind.lower() == "nan":
            continue
        if s in px:
            c = px[s]["Close"].iloc[-260:]
            if len(c) >= 200 and c.iloc[0] > 0:
                groups.setdefault(ind, []).append(c / c.iloc[0])
                allc.append(c / c.iloc[0])
    if len(allc) < 50:
        return {}
    bw = pd.concat(allc, axis=1).ffill().mean(axis=1).resample("W-FRI").last()
    out = {}
    for ind, cs in groups.items():
        if len(cs) < MIN_MEMBERS:
            continue
        idx = pd.concat(cs, axis=1).ffill().mean(axis=1)
        r = _rs(idx, bw)
        if r:
            out[ind] = r | {"n": len(cs)}
    return out
