"""Industry market breadth (owner request 2026-11-23): one row per group per trading day, kept in D1 to watch trends.

Not shown in the app. Groups are the exchanges' 4-level classification (data/classification.json, keyed by ISIN) at three
levels: sector, industry, basic industry. Equal-weighted: every stock counts once, whatever its size.

Per group and day: stocks, market cap (cr), average momentum score (today only; the score has no stored history),
% with RSI(14) > 50, % with MFI(14) > 50, % closing above SMA 20 / 50 / 200, % with SMA 50 > SMA 200,
% up on the day, % up on the week (5 sessions).

A stock counts in a column only on days its indicator exists (e.g. SMA 200 needs 200 sessions), so new listings join
each column when they have enough history. Market cap for past days is today's market cap scaled by the price change
(share count changes are ignored, so older values are approximate).

Backfill: past days are written oldest-missing-first within a row budget per run (D1 Workers Free allows 100,000
written rows a day and the daily sync needs most of it), daily for the last BACKFILL_DAILY sessions, then one day a
week back to BACKFILL_WEEKS weeks. Progress lives in the D1 table itself, so nothing extra is stored in git.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

LEVELS = (("sector", "s"), ("industry", "i"), ("basic_industry", "b"))
COLS = ["date", "level", "grp", "n", "mcap_cr", "momentum", "rsi50", "mfi50", "above20", "above50", "above200", "golden",
        "day_up", "week_up"]
KEYS = ["date", "level", "grp"]
BACKFILL_DAILY = 250       # about one year of sessions, every day
BACKFILL_WEEKS = 156       # three years, one day a week before that
BACKFILL_BUDGET = 20_000   # rows per run for past days
MIN_STOCKS = 3             # smaller groups are left out (a 1-2 stock "trend" is noise)


def _rsi(c: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return _ratio_index(up, dn)


def _ratio_index(pos: pd.DataFrame, neg: pd.DataFrame) -> pd.DataFrame:
    """100 - 100 / (1 + pos / neg); 100 when there were only gains, NaN while either side is still undefined."""
    out = 100 - 100 / (1 + pos / neg.where(neg > 0))
    return out.mask((neg == 0) & (pos > 0), 100.0).mask((neg == 0) & (pos == 0), 50.0)


def _mfi(h: pd.DataFrame, l: pd.DataFrame, c: pd.DataFrame, v: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    tp = (h + l + c) / 3
    mf = tp * v
    d = tp.diff()
    pos = mf.where(d > 0, 0.0).rolling(n, min_periods=n).sum()
    neg = mf.where(d < 0, 0.0).rolling(n, min_periods=n).sum()
    return _ratio_index(pos, neg)


def flags(px: dict) -> tuple[dict, pd.DataFrame]:
    """px: symbol -> OHLCV frame (DatetimeIndex). -> ({flag name: date x symbol frame of 1.0 / 0.0 / NaN}, closes)."""
    frames = {k: pd.DataFrame({s: d[k] for s, d in px.items() if d is not None and k in d and len(d)}) for k in ("High", "Low", "Close", "Volume")}
    c, h, l, v = frames["Close"].sort_index(), frames["High"].sort_index(), frames["Low"].sort_index(), frames["Volume"].sort_index()
    c = c.where(c > 0)
    s20, s50, s200 = (c.rolling(n, min_periods=n).mean() for n in (20, 50, 200))
    rsi, mfi = _rsi(c), _mfi(h, l, c, v)

    def f(cond, *need):
        out = cond.astype(float)
        for x in need:
            out = out.where(x.notna())
        return out.where(c.notna())

    return {
        "rsi50": f(rsi > 50, rsi), "mfi50": f(mfi > 50, mfi),
        "above20": f(c > s20, s20), "above50": f(c > s50, s50), "above200": f(c > s200, s200),
        "golden": f(s50 > s200, s50, s200),
        "day_up": f(c > c.shift(1), c.shift(1)), "week_up": f(c > c.shift(5), c.shift(5)),
    }, c


def groups(isin_of: dict, path: Path = Path("data/classification.json")) -> dict:
    """symbol -> {level: group name} for symbols with a classification."""
    try:
        cl = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for s, i in isin_of.items():
        x = cl.get(i) or {}
        g = {lv: x.get(k) for lv, k in LEVELS if x.get(k)}
        if g:
            out[s] = g
    return out


def rows_for(dates, fl: dict, close: pd.DataFrame, grp: dict, mcap_today: dict, momentum: dict | None = None) -> list[list]:
    """Group rows for the given trading dates (Timestamps present in close.index)."""
    syms = [s for s in close.columns if s in grp]
    if not syms:
        return []
    last = close[syms].ffill().iloc[-1]
    out = []
    for dt in dates:
        cd = close.loc[dt, syms]
        live = cd.notna()
        mc = pd.Series({s: (mcap_today.get(s) or np.nan) for s in syms}) * (cd / last)
        day = {k: v.loc[dt, syms] for k, v in fl.items()}
        ds = str(pd.Timestamp(dt).date())
        for lv, _ in LEVELS:
            names = pd.Series({s: grp[s].get(lv) for s in syms})
            for g, members in names[live].groupby(names[live]).groups.items():
                m = list(members)
                if not g or len(m) < MIN_STOCKS:
                    continue
                row = [ds, lv, g, len(m), round(float(np.nansum(mc[m].values)), 1) if mc[m].notna().any() else None]
                if momentum is not None:
                    vals = [momentum[s] for s in m if momentum.get(s) is not None]
                    row.append(round(float(np.mean(vals)), 1) if vals else None)
                else:
                    row.append(None)
                for k in COLS[6:]:
                    x = day[k][m].dropna()
                    row.append(round(100 * float(x.mean()), 1) if len(x) else None)
                out.append(row)
    return out


def backfill_dates(index: pd.DatetimeIndex, have: set) -> list:
    """Past trading dates still missing in D1, newest first: daily for BACKFILL_DAILY sessions, then weekly (Fridays or the
    week's last session)."""
    idx = index.sort_values()[:-1]  # today is written by the daily step
    daily = list(idx[-BACKFILL_DAILY:])
    older = idx[:-BACKFILL_DAILY]
    weekly = []
    if len(older):
        wk = pd.Series(older, index=older).groupby(older.to_period("W")).max()
        weekly = list(wk.values[-BACKFILL_WEEKS:])
    want = [pd.Timestamp(d) for d in daily[::-1] + weekly[::-1]]
    return [d for d in want if str(d.date()) not in have]


def sync(st, today, px: dict, isin_of: dict, mcap: dict, momentum: dict) -> dict:
    """Write today's rows and as much backfill as the budget allows. Never fatal for the caller (it wraps this)."""
    grp = groups(isin_of)
    px = {s: d for s, d in px.items() if s in grp}
    if not px:
        return {"rows": 0, "note": "no classified stocks with prices"}
    fl, close = flags(px)
    if close.empty:
        return {"rows": 0}
    last = close.index[-1]
    if last.date() > today:
        last = close.index[close.index.date <= today][-1]
    n_today = st.upsert("industry_breadth", COLS, rows_for([last], fl, close, grp, mcap, momentum), KEYS)
    have = {r["date"] for r in st.q("SELECT DISTINCT date FROM industry_breadth")}
    todo, rows = [], []
    per_day = max(1, n_today)
    for d in backfill_dates(close.index[close.index <= last], have | {str(last.date())}):
        if len(rows) + per_day > BACKFILL_BUDGET:
            break
        rows += rows_for([d], fl, close, grp, mcap)
        todo.append(d)
    n_back = st.upsert("industry_breadth", COLS, rows, KEYS) if rows else 0
    left = len(backfill_dates(close.index[close.index <= last], have | {str(last.date())} | {str(d.date()) for d in todo}))
    return {"today": n_today, "backfill_rows": n_back, "backfill_days": len(todo), "days_left": left}
