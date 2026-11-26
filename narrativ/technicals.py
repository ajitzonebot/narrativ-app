"""Early-momentum metrics, stage classification and entry/exit bands."""
import numpy as np
import pandas as pd

from . import config


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _ret(c: pd.Series, n: int) -> float:
    return float(c.iloc[-1] / c.iloc[-n - 1] - 1) if len(c) > n else np.nan


def analyze(df: pd.DataFrame, bench: pd.Series) -> dict | None:
    if len(df) < 210:
        return None
    c, h, v = df["Close"], df["High"], df["Volume"]
    sma50, sma150, sma200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
    ema10, ema21 = c.ewm(span=10).mean(), c.ewm(span=21).mean()
    last = float(c.iloc[-1])

    slope200 = float(sma200.iloc[-1] / sma200.iloc[-22] - 1)
    slope200_prev = float(sma200.iloc[-22] / sma200.iloc[-43] - 1) if len(df) > 243 else np.nan
    hi52, lo52 = float(h.iloc[-252:].max()), float(df["Low"].iloc[-252:].min())
    dist200 = last / float(sma200.iloc[-1]) - 1

    # Accumulation: up-volume / down-volume over 50 days
    chg = c.diff().iloc[-50:]
    vol50 = v.iloc[-50:]
    down = float(vol50[chg < 0].sum())
    ud_ratio = float(vol50[chg > 0].sum() / down) if down > 0 else 3.0

    # OBV new 50-day high
    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    obv_high = bool(obv.iloc[-1] >= obv.iloc[-50:].max() * 0.99)

    # Relative-strength line vs benchmark, leading price
    rs_leads = False
    b = bench.reindex(c.index).ffill()
    if b.notna().sum() > 200:
        rs = c / b
        rs_high = rs.iloc[-10:].max() >= rs.iloc[-252:].max() * 0.995
        px_high = c.iloc[-10:].max() >= hi52 * 0.97
        rs_leads = bool(rs_high and not px_high)

    # Volatility contraction: 20-day range vs 100-day range
    rng20 = (h.iloc[-20:].max() - df["Low"].iloc[-20:].min()) / last
    rng100 = (h.iloc[-100:].max() - df["Low"].iloc[-100:].min()) / last
    vcp = bool(rng100 > 0 and rng20 / rng100 < 0.45)

    # Breakout pivot = prior 55-day high (excluding today)
    pivot = float(h.iloc[-56:-1].max())
    avgvol50 = float(v.iloc[-51:-1].mean())
    recent_breakout = False
    for k in range(1, 11):
        piv_k = float(h.iloc[-55 - k : -k].max())
        if c.iloc[-k] > piv_k and v.iloc[-k] > 1.5 * v.iloc[-50 - k : -k].mean():
            recent_breakout, pivot = True, piv_k
            break

    traded_value = float((c * v).iloc[-20:].mean())
    r63, r126, r189, r252 = (_ret(c, n) for n in (63, 126, 189, 252))
    rs_raw = np.nansum([0.4 * r63, 0.2 * r126, 0.2 * r189, 0.2 * r252])

    # Stage
    trend_template = (
        last > sma50.iloc[-1] > sma150.iloc[-1] > sma200.iloc[-1]
        and slope200 > 0 and last >= 0.75 * hi52 and last >= 1.3 * lo52
    )
    if dist200 > 0.45 or (r126 == r126 and r126 > 1.0):
        stage = "Extended"
    elif trend_template:
        stage = "Stage 2"
    elif last > sma200.iloc[-1] and -0.01 <= slope200 <= 0.04:
        stage = "Stage 1→2"
    elif last < sma200.iloc[-1] and slope200 < 0 and last < sma50.iloc[-1]:
        stage = "Downtrend"  # below a falling 200DMA with no turn above the 50DMA yet
    else:
        stage = "Basing"

    # Breakout levels for the status label only. Entry zone and the one exit level (stop) come from funnel.setup;
    # this band no longer carries a stop, target or trail of its own (it disagreed with the setup's stop).
    buy_hi = pivot * (1 + config.BUY_ZONE_PCT)
    pb_lo, pb_hi = sorted([float(ema21.iloc[-1]), float(ema10.iloc[-1])])

    if last < float(sma50.iloc[-1]) and stage in ("Stage 2", "Extended"):
        status = "EXIT"
    elif recent_breakout and pivot <= last <= buy_hi:
        status = "BUY ZONE"
    elif pivot * 0.95 <= last < pivot:
        status = "WATCH"
    elif last > buy_hi and stage == "Stage 2" and pb_lo * 0.99 <= last <= pb_hi * 1.01:
        status = "PULLBACK"
    elif last > buy_hi:
        status = "EXTENDED"
    else:
        status = "BASE"

    return {
        "price": round(last, 2),
        "chg_1d": round(_ret(c, 1) * 100, 2),
        "ret_3m": round(r63 * 100, 1) if r63 == r63 else None,
        "ret_6m": round(r126 * 100, 1) if r126 == r126 else None,
        "sma50": round(float(sma50.iloc[-1]), 2),
        "sma200": round(float(sma200.iloc[-1]), 2),
        "dist200_pct": round(dist200 * 100, 1),
        "slope200_pct": round(slope200 * 100, 2),
        "slope200_turning": bool(slope200 > 0 and slope200_prev == slope200_prev and slope200_prev <= 0),
        "hi52": round(hi52, 2),
        "lo52": round(lo52, 2),
        "ud_ratio": round(ud_ratio, 2),
        "obv_high": obv_high,
        "rs_leads": rs_leads,
        "vcp": vcp,
        "recent_breakout": recent_breakout,
        "avgvol50": avgvol50,
        "traded_value_cr": round(traded_value / config.CRORE, 2),
        "rs_raw": float(rs_raw),
        "stage": stage,
        "status": status,
        "bands": {
            "pivot": round(pivot, 2),
            "buy_low": round(pivot, 2),
            "buy_high": round(buy_hi, 2),
            "pullback_low": round(pb_lo, 2),
            "pullback_high": round(pb_hi, 2),
        },
    }


def momentum_score(t: dict, rs_pct: float) -> float:
    """0-100. Rewards early trend formation, penalises extension."""
    s = 0.0
    s += 10 if t["price"] > t["sma50"] else 0
    s += 10 if t["price"] > t["sma200"] else 0
    s += 10 if t["sma50"] > t["sma200"] else 0
    s += 8 if t["slope200_pct"] > 0 else 0
    s += 7 if t["slope200_turning"] else 0
    s += 20 * rs_pct
    s += min(15, max(0, (t["ud_ratio"] - 1.0) / 0.5 * 15))
    s += 5 if t["obv_high"] else 0
    s += 8 if t["rs_leads"] else 0
    s += 7 if t["vcp"] else 0
    if t["stage"] == "Extended":
        s -= 30
    elif t["dist200_pct"] > 30:
        s -= 10
    if t["stage"] == "Downtrend":
        s -= 20
    return float(max(0, min(100, s)))


def ma_cross(close: pd.Series, span: int = 260) -> tuple[int, int | None] | None:
    """The 50-day vs 200-day average over the chart's year (feedback #170, owner 26 Nov 2026): (1 when the 50-day is above
    the 200-day today else 0, trading days since the latest cross in that year or None when there was none). The same
    reading as the app's cross card (PaperParts CrossCard): a golden cross when the 50-day rose above, a death cross when it fell
    below. None without 200 days of prices."""
    a = close.rolling(50).mean().iloc[-span:]
    b = close.rolling(200).mean().iloc[-span:]
    d = (a - b).to_numpy()
    if len(d) < 30 or np.isnan(d[-1]):
        return None
    last = None
    for i in range(1, len(d)):
        if not (np.isnan(d[i]) or np.isnan(d[i - 1])) and d[i] * d[i - 1] < 0:
            last = i
    return (1 if d[-1] > 0 else 0), (None if last is None else len(d) - 1 - last)
