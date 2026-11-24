"""Research study: which traits, and which combinations of 2-3 traits, raised the odds of a 25%+ rise in the next 12 months.

Point-in-time, at each month end T from Jan 2024 that has a full 12-month forward window (to about Oct 2025):
  - the pipeline view comes from narrativ/replay.py `_score(T)` (filings filed on or before T, closes up to T, the seven
    levels, the code-decided Buy gates, forward returns vs the Nifty at 252 trading days)
  - the study features are rebuilt here from the same point-in-time inputs (metrics.compute on `_fin_at(T)`, technicals on
    closes up to T, promoter holding known 21 days after the quarter)

Label: winner = 12-month return >= 25% (absolute). Train = buy dates in 2024, test = buy dates in 2025.
Combinations are a fixed, pre-registered list (COMBOS below, written before any result was seen); thresholds that use
terciles take them from the 2024 feature distribution (never from outcomes). Then one shallow decision tree on 2024.

Output docs/data/study_recent.json and docs/research/study_recent.md (quick mode: data/study_recent/quick.*).
python -m narrativ.study_recent [--quick]
"""
import json
import math
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from narrativ import config, technicals
from narrativ import funnel as FN
from narrativ import metrics as MX
from narrativ import replay as RP

QUICK = "--quick" in sys.argv
OUT_JSON = Path("data/study_recent/quick.json" if QUICK else "docs/data/study_recent.json")
OUT_MD = Path("data/study_recent/quick.md" if QUICK else "docs/research/study_recent.md")
START, H12 = "2024-01-31", "12m"
WIN = 25.0
MIN_TEST_N, MIN_LIFT = 30, 1.3

# ------------------------------------------------------------------ features (as known on T)
GROUPS = {
    "earnings": ["rev_g_q", "pat_g_q", "rev_g_ttm", "pat_g_ttm", "rev_cagr_3y", "pat_cagr_3y", "rev_accel", "pat_accel",
                 "pat_accel_num", "margin_chg_yoy", "margin_trough_up", "roce", "roce_chg", "t11"],
    "valuation": ["pe", "val_pct_own", "val_vs_peer", "mcap_cr", "mcap_band"],
    "price": ["stage", "dist_hi52", "rs_pct", "ind_rs_rank", "setup", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol_60",
              "dist200"],
    "flow": ["prom_pct", "prom_chg_1q"],
    "discovery": ["turnover_cr", "turnover_trend"],
    "industry": ["ind_mom_3m", "ind_rs_top", "sec_mom_3m", "ind_wind", "roce_ind_rank"],
    "health": ["de", "net_debt_ebitda", "debt_chg_yoy", "cfo_ebitda", "oi_share", "interest_cover", "cwip_ppe", "capex_rev",
               "dilution_3y"],
    "pipeline": ["tier_surv", "tier_qual", "tier_val", "tier_mgmt", "tier_mom", "tier_disc", "tier_out", "candidate", "top10",
                 "stop", "U1", "U2", "U3", "U4", "U5", "mb", "priority"],
}
CATEGORICAL = {"mcap_band", "stage", "setup", "ind_wind", "stop", "tier_surv", "tier_qual", "tier_val", "tier_mgmt", "tier_mom",
               "tier_disc", "tier_out"}
BOOLEAN = {"pat_accel", "margin_trough_up", "t11", "ind_rs_top", "candidate", "top10", "U1", "U2", "U3", "U4", "U5", "mb"}
DESC = {
    "rev_g_q": "Revenue growth, latest quarter vs same quarter a year earlier (%)",
    "pat_g_q": "Profit growth, latest quarter YoY (%)",
    "rev_g_ttm": "Revenue growth, last 4 quarters vs previous 4 (%)",
    "pat_g_ttm": "Profit growth, last 4 quarters vs previous 4 (%)",
    "rev_cagr_3y": "Revenue growth over full years (3y, or 2y where FY23 is the first year filed) (%)",
    "pat_cagr_3y": "Profit growth over full years (3y or 2y) (%)",
    "rev_accel": "Revenue growth acceleration: latest-quarter YoY minus previous-quarter YoY (pts)",
    "pat_accel": "Profit accelerating: latest-quarter profit YoY > previous quarter's YoY and > 0 (both year-ago profits positive)",
    "pat_accel_num": "Profit YoY latest minus previous quarter (pts, clipped ±300)",
    "margin_chg_yoy": "EBITDA margin, latest quarter minus same quarter last year (pts)",
    "margin_trough_up": "Margin rising from a trough: lowest of the last 8 quarterly margins was 1-5 quarters ago, latest is 2+ pts above it and above a year ago",
    "roce": "ROCE (%)", "roce_chg": "ROCE latest full year minus the year before (pts)",
    "t11": "T11 results beat (price +5% vs Nifty in 3 days after results, profit +15% YoY, results within 60 days)",
    "pe": "P/E (trailing)", "val_pct_own": "Primary multiple's percentile vs its own filed history (0 = cheapest; needs 4+ quarters)",
    "val_vs_peer": "Primary multiple ÷ peer median", "mcap_cr": "Market cap (₹ cr)",
    "mcap_band": "Market cap band (<500, 500-2k, 2k-10k, 10k-50k, 50k+ ₹ cr)",
    "stage": "Price stage (technicals)", "dist_hi52": "Distance from 52-week high (%)",
    "rs_pct": "Relative strength percentile (whole universe)", "ind_rs_rank": "Relative strength percentile within industry",
    "setup": "Entry setup (Breakout / Pullback / Base / none)", "ret_1m": "1-month return (%)", "ret_3m": "3-month return (%)",
    "ret_6m": "6-month return (%)", "ret_12m": "12-month return (%)", "vol_60": "Volatility, 60-day daily returns annualised (%)",
    "dist200": "Distance from 200-day average (%)",
    "prom_pct": "Promoter holding (%)", "prom_chg_1q": "Promoter holding change over the last known quarter (pts)",
    "turnover_cr": "Average daily traded value, 20 days (₹ cr)", "turnover_trend": "Traded value, 20-day avg ÷ 120-day avg",
    "ind_mom_3m": "Industry median 3-month return (%)", "ind_rs_top": "Industry in the top third of industries by median RS",
    "sec_mom_3m": "Sector median 3-month return (%)", "ind_wind": "Industry wind (funnel L7: Tailwind/Neutral/Headwind)",
    "roce_ind_rank": "ROCE percentile within its industry",
    "de": "Debt ÷ equity", "net_debt_ebitda": "Net debt ÷ EBITDA", "debt_chg_yoy": "Borrowings change over 12 months (%)",
    "cfo_ebitda": "Cash conversion: operating cash flow ÷ EBITDA over full years (%)",
    "oi_share": "Other income ÷ profit before tax (%)", "interest_cover": "Interest cover (x)",
    "cwip_ppe": "Capital work in progress ÷ fixed assets (%)", "capex_rev": "Capex ÷ revenue (%)",
    "dilution_3y": "Share count change over 3 years (%)",
    "tier_surv": "L1 survivability tier", "tier_qual": "L2 quality tier", "tier_val": "L3 valuation tier",
    "tier_mgmt": "L4 management tier", "tier_mom": "L5 momentum tier", "tier_disc": "L6 discovery tier", "tier_out": "L7 outlook tier",
    "candidate": "Pipeline candidate (passes every code gate)", "top10": "In the replayed Top 10",
    "stop": "Where the pipeline stopped the stock", "U1": "U1 Profit speeding up", "U2": "U2 Operating leverage",
    "U3": "U3 Re-rating setup", "U4": "U4 Selling overhang over", "U5": "U5 Both engines", "mb": "Multibagger flag",
    "priority": "Pipeline priority score",
}
NOT_BUILT = {
    "delivery % trend": "prices.pkl holds OHLCV only; no delivery history in the stored data",
    "institutional / mutual fund holding and its change": "data/shareholding.json holds promoter and public % only",
    "pledge": "not in the stored shareholding history",
    "index membership": "data/index_membership.json is today's snapshot only, not point-in-time",
    "D1 industry_breadth": "not reachable from the runner (as instructed)",
    "promoter change in 2024": "promoter history starts with the Dec-2024 quarter for most stocks (known ~21 Jan 2025), so no 2024 buy date has it",
}
STOP_ORDER = ["mos", "trend", "R1", "R2", "R4", "R6"]
STOP_NAME = {"mos": "L3 valuation: no margin of safety (tier 4-5 or unknown)", "trend": "price in downtrend / stage unknown",
             "R1": "gate R1 cash conversion", "R2": "gate R2 other income", "R4": "gate R4 no dated trigger",
             "R6": "gate R6 re-rating leg (fair value + heavily discovered)"}
LEVEL_NAME = {"surv": "L1 survivability", "qual": "L2 quality", "val": "L3 valuation", "mgmt": "L4 management", "mom": "L5 momentum",
              "disc": "L6 discovery", "out": "L7 outlook"}


def _v(M, k):
    return MX.val(M, k)


def _g(cur, prev):
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur / prev - 1) * 100


def _band(mc):
    if mc is None:
        return None
    return "<500" if mc < 500 else "500-2k" if mc < 2000 else "2k-10k" if mc < 10000 else "10k-50k" if mc < 50000 else "50k+"


def _quarterly(M):
    """{quarter end: (rev, pat, margin)} from metrics' quarterly list (₹ cr)."""
    return {q[0]: (q[1], q[2], q[3]) for q in (M.get("quarterly") or [])}


def _prev_q(qe: str, n: int) -> str:
    return MX._prev_q(MX._q_end(qe), n)


def _earn_extra(M) -> dict:
    qd = _quarterly(M)
    out = {"pat_accel": None, "pat_accel_num": None, "margin_trough_up": None}
    if not qd:
        return out
    last = max(qd)
    q1, q4, q5 = _prev_q(last, 1), _prev_q(last, 4), _prev_q(last, 5)
    if all(k in qd for k in (q1, q4, q5)):
        g0, g1 = _g(qd[last][1], qd[q4][1]), _g(qd[q1][1], qd[q5][1])
        if g0 is not None and g1 is not None:
            out["pat_accel"] = bool(g0 > g1 and g0 > 0)
            out["pat_accel_num"] = float(max(-300.0, min(300.0, g0 - g1)))
    seq = [_prev_q(last, i) for i in range(7, -1, -1)]  # oldest .. latest
    ms = [qd[q][2] if q in qd else None for q in seq]
    if sum(m is not None for m in ms) >= 6 and ms[-1] is not None:
        known = [(i, m) for i, m in enumerate(ms) if m is not None]
        imin, mmin = min(known, key=lambda x: x[1])
        ago = len(ms) - 1 - imin
        yago = ms[-5]
        out["margin_trough_up"] = bool(1 <= ago <= 5 and ms[-1] >= mmin + 2 and (yago is None or ms[-1] > yago))
    return out


def _rank_pct(d: dict) -> dict:
    s = pd.Series({k: v for k, v in d.items() if v is not None}, dtype=float)
    return s.rank(pct=True).to_dict() if len(s) else {}


def _study_month(T: str) -> list[dict]:
    """One month end: replay's pipeline view + the study features + 12-month outcome, one dict per stock."""
    res = RP._score(T)
    rows, fwd = res["rows"], res["fwd"]
    top = set(RP._pick(rows, RP.CUR, RP.BASE_W))
    Ts = pd.Timestamp(T)
    bench = P_[config.BENCHMARK]["Close"]
    bT = bench[bench.index <= Ts]
    tech, mx = {}, {}
    for s in rows:
        if H12 not in fwd.get(s, {}):
            continue
        try:
            d = P_[s][P_[s].index <= Ts]
            t = technicals.analyze(d, bT)
            if not t:
                continue
            M = MX.compute(RP._fin_at(RP.FIN[s], T), t["price"], None, None, None)
        except Exception:  # noqa: BLE001
            continue
        tech[s], mx[s] = (t, d), M
    syms = list(mx)
    ind_of = {s: (RP.META.get(s) or {}).get("i") for s in syms}
    sec_of = {s: (RP.META.get(s) or {}).get("sec") for s in syms}
    # industry-relative measures, among the stocks scored this month
    ind_rank, roce_ind = {}, {}
    by_ind, by_sec = {}, {}
    for s in syms:
        if isinstance(ind_of[s], str):
            by_ind.setdefault(ind_of[s], []).append(s)
        if isinstance(sec_of[s], str):
            by_sec.setdefault(sec_of[s], []).append(s)
    ind_med_rs, ind_mom, sec_mom = {}, {}, {}
    for ind, ss in by_ind.items():
        if len(ss) >= 3:
            ind_rank.update(_rank_pct({s: tech[s][0]["rs_raw"] for s in ss}))
            roce_ind.update(_rank_pct({s: _v(mx[s], "roce_pct") for s in ss}))
            ind_med_rs[ind] = float(np.median([tech[s][0]["rs_raw"] for s in ss]))
            r3 = [tech[s][0]["ret_3m"] for s in ss if tech[s][0].get("ret_3m") is not None]
            if r3:
                ind_mom[ind] = float(np.median(r3))
    for sec, ss in by_sec.items():
        r3 = [tech[s][0]["ret_3m"] for s in ss if tech[s][0].get("ret_3m") is not None]
        if len(r3) >= 3:
            sec_mom[sec] = float(np.median(r3))
    ind_top = set()
    if ind_med_rs:
        rr = pd.Series(ind_med_rs).rank(pct=True)
        ind_top = {i for i, p in rr.items() if p >= 2 / 3}
    istats = FN.industry_stats([(ind_of[s], mx[s]) for s in syms])
    bts, prows = {}, []
    for s in syms:
        try:
            bt = FN.business_type(mx[s], ind_of[s], mx[s].get("kind") or "general")
            bt, mk, cur = FN.primary(mx[s], bt)
        except Exception:  # noqa: BLE001
            bt, mk, cur = None, None, None
        bts[s] = (bt, mk, cur)
        if bt:
            prows.append((s, ind_of[s], bt, mk, cur))
    peers = FN.peer_medians(prows)
    out = []
    for s in syms:
        try:
            t, d = tech[s]
            M, rw = mx[s], rows[s]
            c = d["Close"]
            bt, mk, cur = bts[s]
            vpo = None
            if mk and cur is not None:
                hist = MX.history(RP._fin_at(RP.FIN[s], T), c)
                hv = [h[FN.HIST_KEY[mk]] for h in hist if h.get(FN.HIST_KEY[mk]) and h[FN.HIST_KEY[mk]] > 0]
                if len(hv) >= 4:
                    vpo = sum(1 for x in hv if x < cur) / len(hv) * 100
            pr = peers.get(s)
            vvp = cur / pr["median"] if (cur is not None and pr and pr.get("n", 0) >= 5 and pr.get("median")) else None
            rf = M.get("roce_fy") or []
            prom = RP._prom_at(s, T)
            pp = [h.get("promoter_pct") for h in prom if h.get("promoter_pct") is not None]
            val_ = d["Close"] * d["Volume"]
            v20, v120 = float(val_.iloc[-20:].mean()), float(val_.iloc[-120:].mean())
            lr = np.log(c.iloc[-61:]).diff().dropna()
            sig = FN.signal_triggers(d, bT, M, None, None, None, Ts.date(), _v(M, "mcap_cr"))
            su = FN.setup(d, t, None)
            ee = _earn_extra(M)
            tt = rw["_t"]
            # where the pipeline stopped it
            if rw["_out"]:
                stop = f"removed at {LEVEL_NAME.get(rw['_out'].split(':')[0], rw['_out'].split(':')[0])}"
            elif not rw["eligible"]:
                stop = ("L1 survivability tier weak/unknown" if not (tt["surv"] != 0 and tt["surv"] <= 3)
                        else "L2 quality tier weak/unknown")
            else:
                fail = next((g for g in STOP_ORDER if not rw[g]), None)
                stop = STOP_NAME[fail] if fail else ("candidate: in Top 10" if s in top else "candidate: not in Top 10")
            r12, x12 = fwd[s][H12]
            f = {
                "s": s, "T": T, "ret12": r12, "exc12": x12, "win": r12 >= WIN, "beat": x12 > 0,
                "i": ind_of[s], "sec": sec_of[s],
                "rev_g_q": _v(M, "rev_yoy_pct"), "pat_g_q": _v(M, "pat_yoy_pct"),
                "rev_g_ttm": _v(M, "rev_ttm_growth_pct"), "pat_g_ttm": _v(M, "pat_ttm_growth_pct"),
                "rev_cagr_3y": _v(M, "rev_cagr_3y_pct"), "pat_cagr_3y": _v(M, "pat_cagr_3y_pct"),
                "rev_accel": (_v(M, "rev_yoy_pct") - _v(M, "rev_yoy_prev_pct"))
                if _v(M, "rev_yoy_pct") is not None and _v(M, "rev_yoy_prev_pct") is not None else None,
                **ee,
                "margin_chg_yoy": (_v(M, "ebitda_margin_q_pct") - _v(M, "ebitda_margin_q_yago_pct"))
                if _v(M, "ebitda_margin_q_pct") is not None and _v(M, "ebitda_margin_q_yago_pct") is not None else None,
                "roce": _v(M, "roce_pct"), "roce_chg": (rf[-1][1] - rf[-2][1]) if len(rf) >= 2 else None,
                "t11": any(x[0] == "T11" for x in sig),
                "pe": _v(M, "pe"), "val_pct_own": vpo, "val_vs_peer": vvp,
                "mcap_cr": _v(M, "mcap_cr"), "mcap_band": _band(_v(M, "mcap_cr")),
                "stage": t.get("stage"), "dist_hi52": (t["price"] / t["hi52"] - 1) * 100 if t.get("hi52") else None,
                "rs_pct": rw.get("rs"), "ind_rs_rank": ind_rank.get(s, None) * 100 if s in ind_rank else None,
                "setup": su.get("type") if su.get("type") in ("Breakout", "Pullback", "Base") else "none",
                "ret_1m": (float(c.iloc[-1]) / float(c.iloc[-22]) - 1) * 100 if len(c) > 22 else None,
                "ret_3m": t.get("ret_3m"), "ret_6m": t.get("ret_6m"),
                "ret_12m": (float(c.iloc[-1]) / float(c.iloc[-253]) - 1) * 100 if len(c) > 253 else None,
                "vol_60": float(lr.std() * math.sqrt(252) * 100) if len(lr) > 20 else None,
                "dist200": t.get("dist200_pct"),
                "prom_pct": pp[-1] if pp else None, "prom_chg_1q": (pp[-1] - pp[-2]) if len(pp) >= 2 else None,
                "turnover_cr": t.get("traded_value_cr"), "turnover_trend": v20 / v120 if v120 > 0 else None,
                "ind_mom_3m": ind_mom.get(ind_of[s]), "ind_rs_top": (ind_of[s] in ind_top) if ind_of[s] in ind_med_rs else None,
                "sec_mom_3m": sec_mom.get(sec_of[s]),
                "ind_wind": ((istats.get(ind_of[s]) or {}).get("wind") or {}).get("wind"),
                "roce_ind_rank": roce_ind[s] * 100 if s in roce_ind else None,
                "de": _v(M, "de"), "net_debt_ebitda": _v(M, "net_debt_ebitda"), "debt_chg_yoy": _v(M, "debt_chg_yoy_pct"),
                "cfo_ebitda": FN.cash_conversion(M)[0], "oi_share": _v(M, "other_income_pct_pbt"),
                "interest_cover": _v(M, "interest_cover"), "cwip_ppe": _v(M, "cwip_pct_ppe"), "capex_rev": _v(M, "capex_pct_rev"),
                "dilution_3y": _v(M, "dilution_3y_pct"),
                **{f"tier_{k}": tt[k] for k in FN.LEVELS},
                "candidate": all(rw[g] for g in RP.CUR), "top10": s in top, "stop": stop,
                **{u: bool(rw.get(u)) for u in ("U1", "U2", "U3", "U4", "U5")}, "mb": bool(rw.get("mb")), "priority": rw.get("pr"),
            }
            out.append(f)
        except Exception as e:  # noqa: BLE001
            if QUICK:
                print(f"[study] {T} {s} feature error: {e!r}")
            continue
    print(f"[study] {T}: {len(out)} stocks with features and a 12-month outcome")
    return out


P_: dict = {}


# ------------------------------------------------------------------ statistics
def _num(x):
    if isinstance(x, (bool, np.bool_)) or not isinstance(x, (int, float, np.integer, np.floating)) or x != x:
        return None
    return float(x)


def stats(sel: pd.DataFrame, base: float) -> dict:
    n = len(sel)
    if n == 0:
        return {"n": 0}
    r = sel["ret12"].astype(float)
    hit = float(sel["win"].mean())
    k = max(1, int(round(n * 0.1)))
    by_m = sel.groupby("T").size()
    return {"n": n, "hit_pct": round(100 * hit, 1), "lift": round(hit / base, 2) if base else None,
            "avg_ret": round(float(r.mean()), 1), "med_ret": round(float(r.median()), 1),
            "avg_vs_nifty": round(float(sel["exc12"].mean()), 1), "beat_nifty_pct": round(100 * float(sel["beat"].mean()), 1),
            "months": int(by_m.size), "median_monthly_count": float(by_m.median()),
            "worst_decile_avg": round(float(r.nsmallest(k).mean()), 1), "p10_ret": round(float(r.quantile(0.1)), 1)}


def months_beating(sel: pd.DataFrame, df: pd.DataFrame) -> float | None:
    """Share of months where the flagged stocks' hit rate beat that month's base rate (months with 3+ flagged)."""
    base_m = df.groupby("T")["win"].mean()
    g = sel.groupby("T")["win"].agg(["mean", "size"])
    g = g[g["size"] >= 3]
    if g.empty:
        return None
    return round(100 * float((g["mean"] > base_m.reindex(g.index)).mean()), 0)


TERC_FROM_TEST: list = []


def terciles(train: pd.DataFrame, feats: list[str], test: pd.DataFrame | None = None) -> dict:
    """Cut points from the 2024 distribution; a feature with no 2024 values (promoter history) uses 2025's, flagged."""
    q = {}
    for f in feats:
        x = pd.to_numeric(train[f], errors="coerce").dropna()
        if len(x) < 30 and test is not None:
            x = pd.to_numeric(test[f], errors="coerce").dropna()
            if len(x) >= 30:
                TERC_FROM_TEST.append(f)
        if len(x) >= 30:
            q[f] = (float(x.quantile(1 / 3)), float(x.quantile(2 / 3)))
    return q


def bucket(df: pd.DataFrame, f: str, Q: dict) -> pd.Series:
    if f in BOOLEAN:
        return df[f].map(lambda x: "missing" if x is None or (isinstance(x, float) and x != x) else ("yes" if x else "no"))
    if f in CATEGORICAL:
        return df[f].map(lambda x: "missing" if x is None or (isinstance(x, float) and x != x) else str(x))
    lo, hi = Q[f]
    x = pd.to_numeric(df[f], errors="coerce")
    return pd.Series(np.where(x.isna(), "missing", np.where(x <= lo, "low", np.where(x <= hi, "mid", "high"))), index=df.index)


def single_lift(train, test, base_tr, base_te, Q) -> dict:
    out = {}
    for grp, fs in GROUPS.items():
        for f in fs:
            if f not in BOOLEAN and f not in CATEGORICAL and f not in Q:
                out[f] = {"group": grp, "desc": DESC.get(f), "note": "too few values in 2024 to form terciles", "buckets": {}}
                continue
            btr, bte = bucket(train, f, Q), bucket(test, f, Q)
            bk = {}
            for b in sorted(set(btr) | set(bte)):
                bk[b] = {"train": stats(train[btr == b], base_tr), "test": stats(test[bte == b], base_te)}
            cov = {"train_pct": round(100 * float((btr != "missing").mean()), 1), "test_pct": round(100 * float((bte != "missing").mean()), 1)}
            out[f] = {"group": grp, "desc": DESC.get(f), "terciles_2024": Q.get(f), "coverage": cov, "buckets": bk}
    return out


# ------------------------------------------------------------------ pre-registered combinations (fixed before any result)
def _n(r, k):
    return _num(r.get(k))


def _yes(r, k):
    x = r.get(k)
    return x is not None and not (isinstance(x, float) and x != x) and bool(x)


def _ge(r, k, x):
    v = _n(r, k)
    return v is not None and x is not None and v >= x


def _le(r, k, x):
    v = _n(r, k)
    return v is not None and x is not None and v <= x


def _lt(r, k, x):
    v = _n(r, k)
    return v is not None and x is not None and v < x


def _hi(Q, f):
    return (Q.get(f) or (None, None))[1]


def _lo(Q, f):
    return (Q.get(f) or (None, None))[0]


def low_debt(r):
    de, nd = _n(r, "de"), _n(r, "net_debt_ebitda")
    return (de is not None and de <= 0.3) or (nd is not None and nd <= 0.5)


STAGE_UP = ("Stage 2", "Stage 1→2")


def combos(Q):
    """name -> (definition text, rule(row) -> bool). Thresholds: top tercile = above the 2024 67th percentile, etc."""
    def undiscovered(r):
        return _ge(r, "roce", _hi(Q, "roce")) and low_debt(r) and _le(r, "turnover_cr", _lo(Q, "turnover_cr"))
    return {
        "1 Twin engine": ("mcap < ₹2,000 cr + profit accelerating (latest-quarter profit YoY above previous quarter's and > 0) + primary multiple below its own-history median (percentile < 50)",
                          lambda r: _lt(r, "mcap_cr", 2000) and _yes(r, "pat_accel") and _lt(r, "val_pct_own", 50)),
        "2 Undiscovered quality": (f"ROCE top tercile (≥ {_hi(Q, 'roce')}) + low debt (D/E ≤ 0.3 or net debt/EBITDA ≤ 0.5) + low discovery PROXY: traded value bottom tercile (≤ ₹{_lo(Q, 'turnover_cr')} cr/day) — institutional holding is not in the stored data",
                                   undiscovered),
        "3 Discovery starting": ("#2 + traded value rising (20-day avg ≥ 1.5x the 120-day avg) — PROXY for institutions/MFs entering (holding data not stored)",
                                 lambda r: undiscovered(r) and _ge(r, "turnover_trend", 1.5)),
        "4 Capacity coming": (f"CWIP/fixed assets top tercile (≥ {_hi(Q, 'cwip_ppe')}%) or capex/revenue top tercile (≥ {_hi(Q, 'capex_rev')}%) + revenue accelerating (latest-quarter YoY > previous quarter's)",
                              lambda r: (_ge(r, "cwip_ppe", _hi(Q, "cwip_ppe")) or _ge(r, "capex_rev", _hi(Q, "capex_rev"))) and _ge(r, "rev_accel", 0.0001)),
        "5 Turnaround": ("margin rising from a trough (margin_trough_up) + borrowings down over 12 months + price stage Stage 1→2 or Stage 2",
                         lambda r: _yes(r, "margin_trough_up") and _lt(r, "debt_chg_yoy", 0) and r.get("stage") in STAGE_UP),
        "6 Confirmed breakout": ("within 10% of 52-week high + RS percentile top tercile (≥ 66.7) + T11 results beat",
                                 lambda r: _ge(r, "dist_hi52", -10) and _ge(r, "rs_pct", 66.7) and _yes(r, "t11")),
        "7 Industry leader, rising industry": ("ROCE top third within its industry (industry percentile ≥ 66.7) + industry in the top third of industries by median RS",
                                               lambda r: _ge(r, "roce_ind_rank", 66.7) and _yes(r, "ind_rs_top")),
        "8 Promoter conviction": ("promoter holding up in the last known quarter + primary multiple below own-history median (pledge not in stored data; promoter history only from 2025 buy dates)",
                                  lambda r: _ge(r, "prom_chg_1q", 0.01) and _lt(r, "val_pct_own", 50)),
        # own additions, written before evaluation
        "9 Quality growth at a fair price": (f"ROCE top tercile + revenue growth (4Q vs 4Q) top tercile (≥ {_hi(Q, 'rev_g_ttm')}%) + multiple below own-history median",
                                             lambda r: _ge(r, "roce", _hi(Q, "roce")) and _ge(r, "rev_g_ttm", _hi(Q, "rev_g_ttm")) and _lt(r, "val_pct_own", 50)),
        "10 Momentum + profit growth": (f"RS percentile top tercile + profit growth (4Q vs 4Q) top tercile (≥ {_hi(Q, 'pat_g_ttm')}%)",
                                        lambda r: _ge(r, "rs_pct", 66.7) and _ge(r, "pat_g_ttm", _hi(Q, "pat_g_ttm"))),
        "11 Small cap in stage 2 with sales growth": (f"mcap < ₹5,000 cr + Stage 2 or Stage 1→2 + latest-quarter revenue YoY top tercile (≥ {_hi(Q, 'rev_g_q')}%)",
                                                      lambda r: _lt(r, "mcap_cr", 5000) and r.get("stage") in STAGE_UP and _ge(r, "rev_g_q", _hi(Q, "rev_g_q"))),
        "12 Operating leverage": ("latest-quarter revenue YoY top tercile + EBITDA margin up YoY + profit accelerating",
                                  lambda r: _ge(r, "rev_g_q", _hi(Q, "rev_g_q")) and _ge(r, "margin_chg_yoy", 0.0001) and _yes(r, "pat_accel")),
        "13 Cheap vs peers and improving": ("multiple < 0.8x peer median + ROCE up vs prior year + revenue growing (4Q vs 4Q > 0) + not in a downtrend",
                                            lambda r: _lt(r, "val_vs_peer", 0.8) and _ge(r, "roce_chg", 0.0001) and _ge(r, "rev_g_ttm", 0.0001)
                                            and r.get("stage") not in ("Downtrend", None)),
        "14 Pipeline candidate near highs": ("passes every code gate (candidate) + within 10% of 52-week high",
                                             lambda r: _yes(r, "candidate") and _ge(r, "dist_hi52", -10)),
    }


LIQ_TEXT = "market cap ≥ ₹500 cr and average daily traded value ≥ ₹1 cr"


def liquid(df: pd.DataFrame) -> pd.DataFrame:
    return df[(pd.to_numeric(df["mcap_cr"], errors="coerce") >= 500) & (pd.to_numeric(df["turnover_cr"], errors="coerce") >= 1)]


REFERENCE = {
    "every stock (base rate)": lambda r: True,
    "pipeline candidate (all code gates)": lambda r: _yes(r, "candidate"),
    "pipeline Top 10": lambda r: _yes(r, "top10"),
}


def eval_rules(rules: dict, train, test, base_tr, base_te, all_df) -> dict:
    out = {}
    for name, fn in rules.items():
        rule = fn[1] if isinstance(fn, tuple) else fn
        mtr = train.apply(lambda r: bool(rule(r)), axis=1) if len(train) else pd.Series(dtype=bool)
        mte = test.apply(lambda r: bool(rule(r)), axis=1) if len(test) else pd.Series(dtype=bool)
        st_tr, st_te = stats(train[mtr], base_tr), stats(test[mte], base_te)
        st_tr["months_beat_base_pct"] = months_beating(train[mtr], train) if st_tr["n"] else None
        st_te["months_beat_base_pct"] = months_beating(test[mte], test) if st_te["n"] else None
        passed = bool(st_tr.get("lift") and st_te.get("lift") and st_tr["lift"] > MIN_LIFT and st_te["lift"] > MIN_LIFT
                      and st_te["n"] >= MIN_TEST_N and st_tr["n"] >= MIN_TEST_N)
        out[name] = {"definition": fn[0] if isinstance(fn, tuple) else name, "train": st_tr, "test": st_te, "passed": passed}
    return out


# ------------------------------------------------------------------ decision tree
STAGE_ORD = {"Downtrend": 0, "Basing": 1, "Stage 1→2": 2, "Stage 2": 3, "Extended": 4}
SETUP_ORD = {"none": 0, "Base": 1, "Pullback": 2, "Breakout": 3}
WIND_ORD = {"Headwind": 0, "Neutral": 1, "Tailwind": 2}


def _matrix(df: pd.DataFrame, rank: bool = False) -> tuple[np.ndarray, list[str]]:
    cols = []
    X = {}
    for grp, fs in GROUPS.items():
        for f in fs:
            if f in ("stop", "mcap_band"):
                continue
            if f == "stage":
                X[f] = df[f].map(STAGE_ORD)
            elif f == "setup":
                X[f] = df[f].map(SETUP_ORD)
            elif f == "ind_wind":
                X[f] = df[f].map(WIND_ORD)
            elif f in BOOLEAN:
                X[f] = df[f].map(lambda x: np.nan if x is None or (isinstance(x, float) and x != x) else float(bool(x)))
            else:
                X[f] = pd.to_numeric(df[f], errors="coerce")
                if rank:  # within-month percentile (0-100): removes month-level shifts such as a market-wide rally
                    X[f] = X[f].groupby(df["T"]).rank(pct=True) * 100
            cols.append(f)
    M = pd.DataFrame(X)[cols].astype(float)
    return M.to_numpy(), cols


def tree_pass(train, test, base_tr, base_te, rank: bool = False) -> dict:
    try:
        from sklearn.tree import DecisionTreeClassifier
    except Exception as e:  # noqa: BLE001
        return {"error": f"scikit-learn not available: {e!r}"}
    if len(train) < 200 or train["win"].nunique() < 2:
        return {"error": "too few training rows"}
    Xtr, cols = _matrix(train, rank)
    Xte, _ = _matrix(test, rank)
    ytr = train["win"].astype(int).to_numpy()
    leaf_min = max(30, int(round(0.01 * len(train))))
    clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=leaf_min, random_state=0)
    clf.fit(Xtr, ytr)
    tr_ = clf.tree_
    paths = {}

    def walk(node, conds):
        if tr_.children_left[node] == -1:
            paths[node] = conds
            return
        f, th = cols[tr_.feature[node]], tr_.threshold[node]
        mv = getattr(tr_, "missing_go_to_left", None)
        ml = bool(mv[node]) if mv is not None else None
        if not np.isfinite(th):  # split only on whether the value is known
            walk(tr_.children_left[node], conds + [f"{f} {'is missing' if ml else 'is known'}"])
            walk(tr_.children_right[node], conds + [f"{f} {'is known' if ml else 'is missing'}"])
            return
        walk(tr_.children_left[node], conds + [f"{f} <= {th:.3g}" + (" (or missing)" if ml else "")])
        walk(tr_.children_right[node], conds + [f"{f} > {th:.3g}" + (" (or missing)" if ml is False else "")])
    walk(0, [])
    ltr, lte = clf.apply(Xtr), clf.apply(Xte) if len(test) else np.array([])
    leaves = []
    for node, conds in paths.items():
        st_tr = stats(train[ltr == node], base_tr)
        st_te = stats(test[lte == node], base_te) if len(test) else {"n": 0}
        held = bool(st_tr.get("lift") and st_te.get("lift") and st_tr["lift"] > MIN_LIFT and st_te["lift"] > MIN_LIFT
                    and st_te["n"] >= MIN_TEST_N and st_tr["n"] >= MIN_TEST_N)
        leaves.append({"rule": " AND ".join(conds), "train": st_tr, "test": st_te, "held_out_of_sample": held})
    leaves.sort(key=lambda x: -(x["train"].get("lift") or 0))
    imp = sorted(((c, round(float(v), 3)) for c, v in zip(cols, clf.feature_importances_) if v > 0), key=lambda x: -x[1])
    return {"features": "numeric features as within-month percentiles (0-100)" if rank else "raw feature values",
            "max_depth": 3, "min_samples_leaf": leaf_min, "train_rows": len(train), "importances": imp, "leaves": leaves}


# ------------------------------------------------------------------ pipeline losses
def pipeline_tally(df: pd.DataFrame) -> dict:
    """For each place the pipeline stopped a stock: winners (>= 25%), losers (12-month return < 0), and rates."""
    out = {}
    W, L = int(df["win"].sum()), int((df["ret12"] < 0).sum())
    g = df.groupby("stop")
    rows = []
    for stop, x in g:
        w, lo = int(x["win"].sum()), int((x["ret12"] < 0).sum())
        rows.append({"stop": stop, "n": len(x), "winners": w, "losers": lo,
                     "share_of_all_winners_pct": round(100 * w / W, 1) if W else None,
                     "share_of_all_losers_pct": round(100 * lo / L, 1) if L else None,
                     "hit_pct": round(100 * w / len(x), 1), "loss_pct": round(100 * lo / len(x), 1),
                     "avg_ret": round(float(x["ret12"].mean()), 1)})
    rows.sort(key=lambda r: -r["winners"])
    out["by_stop_first_reason"] = rows
    # each gate on its own (a stock can fail several): what failing it means, regardless of order
    gate_rows = []
    checks = {"removed at a level (any L1-L7 'out')": df["stop"].str.startswith("removed at"),
              "L1 survivability tier 4-5 or unknown": ~df["tier_surv"].isin([1, 2, 3]),
              "L2 quality tier 4-5 or unknown": ~df["tier_qual"].isin([1, 2, 3]),
              "L3 valuation tier 4-5 or unknown (no margin of safety)": ~df["tier_val"].isin([1, 2, 3]),
              "price in downtrend": df["stage"].eq("Downtrend")}
    for name, m in checks.items():
        x = df[m]
        if len(x):
            gate_rows.append({"check": name, "n": len(x), "winners": int(x["win"].sum()), "losers": int((x["ret12"] < 0).sum()),
                              "share_of_all_winners_pct": round(100 * x["win"].sum() / W, 1) if W else None,
                              "share_of_all_losers_pct": round(100 * (x["ret12"] < 0).sum() / L, 1) if L else None,
                              "hit_pct": round(100 * float(x["win"].mean()), 1)})
    out["each_check_alone"] = gate_rows
    tiers = {}
    for k in FN.LEVELS:
        tb = {}
        for tier, x in df.groupby(f"tier_{k}"):
            tb[str(tier)] = {"n": len(x), "hit_pct": round(100 * float(x["win"].mean()), 1),
                             "loss_pct": round(100 * float((x["ret12"] < 0).mean()), 1), "winners": int(x["win"].sum())}
        tiers[LEVEL_NAME[k]] = tb
    out["tiers"] = tiers
    out["totals"] = {"rows": len(df), "winners": W, "losers": L}
    return out


# ------------------------------------------------------------------ report
def _fmt(st, keys=("n", "hit_pct", "lift", "avg_ret", "avg_vs_nifty", "beat_nifty_pct", "median_monthly_count", "worst_decile_avg")):
    if not st or not st.get("n"):
        return " | ".join(["0"] + ["–"] * (len(keys) - 1))
    return " | ".join("–" if st.get(k) is None else f"{st[k]:g}" if isinstance(st[k], (int, float)) else str(st[k]) for k in keys)


def report(R: dict) -> str:
    L = [f"# Study: what raised the odds of a 25%+ rise in 12 months (point-in-time, {R['dates'][0]} to {R['dates'][-1]})", "",
         f"Generated by `python -m narrativ.study_recent` on {R['generated']}. All numbers in docs/data/study_recent.json.", "",
         "Method: at each month end T, only filings filed on or before T, closes up to T and promoter holding known by T. "
         "Winner = 12-month (252 trading days) return ≥ 25%. Train (discovery) = buy dates in 2024; test = buy dates in 2025. "
         "A combination counts as a finding only if lift > 1.3 in BOTH periods and test n ≥ 30. Each row is a stock-month, so "
         "one stock appears up to 12 times a year (overlapping windows).", "",
         "## Base rate", "",
         f"Overall: {R['base']['all']['hit_pct']}% of {R['base']['all']['n']} stock-months rose 25%+ "
         f"(train 2024: {R['base']['train']['hit_pct']}% of {R['base']['train']['n']}; test 2025: {R['base']['test']['hit_pct']}% of {R['base']['test']['n']}). "
         f"Beat the Nifty: train {R['base']['train']['beat_nifty_pct']}%, test {R['base']['test']['beat_nifty_pct']}%.", "",
         "| month | stocks | 25% winners % | beat Nifty % | avg 12m return % |", "|---|---|---|---|---|"]
    for m in R["base"]["by_month"]:
        L.append(f"| {m['T']} | {m['n']} | {m['hit_pct']} | {m['beat_nifty_pct']} | {m['avg_ret']} |")
    L += ["", "## Top single traits by lift", "",
          "Buckets: low / mid / high = 2024 terciles of the feature (cut points in the JSON); yes/no for flags. Listed: buckets with "
          "train n ≥ 100, ranked by the lower of train and test lift.", "",
          "| trait | bucket | train n | train hit % | train lift | test n | test hit % | test lift | test avg ret % |", "|---|---|---|---|---|---|---|---|---|"]
    for t in R["top_single"][:20]:
        L.append(f"| {t['feature']} ({t['desc']}) | {t['bucket']} | {t['train']['n']} | {t['train']['hit_pct']} | {t['train']['lift']} | "
                 f"{t['test'].get('n', 0)} | {t['test'].get('hit_pct', '–')} | {t['test'].get('lift', '–')} | {t['test'].get('avg_ret', '–')} |")
    L += ["", "Worst traits (lift ≤ 0.8 in both periods, train n ≥ 100, test n ≥ 30):", ""]
    for t in R["bottom_single"][:10]:
        L.append(f"- {t['feature']} = {t['bucket']}: train hit {t['train']['hit_pct']}% (lift {t['train']['lift']}), "
                 f"test hit {t['test'].get('hit_pct')}% (lift {t['test'].get('lift')})")
    cols = "n | hit % | lift | avg ret % | avg vs Nifty | beat Nifty % | median monthly count | worst-decile avg %"
    L += ["", "## Pre-registered combinations", "",
          "Fixed before any result was looked at. ✅ = lift > 1.3 in both periods and test n ≥ 30 (also train n ≥ 30, so a "
         "2-row 2024 sample cannot pass). The pipeline itself had almost no 2024 candidates (its quality level needs ~3 years of "
         "quarters), so its rows are effectively test-only.", "",
          f"| combination | period | {cols} | months beating base % |", "|---|---|" + "---|" * 9]
    for name, c in {**R["reference"], **R["combinations"]}.items():
        mark = " ✅" if c.get("passed") else ""
        for per in ("train", "test"):
            L.append(f"| {name}{mark if per == 'train' else ''} | {per} | {_fmt(c[per])} | {c[per].get('months_beat_base_pct', '–')} |")
    L += ["", f"Robustness (not a new test): the same rules within tradeable stocks only — {LIQ_TEXT} — against that subset's own base rate.", "",
          f"| combination | period | {cols} | months beating base % |", "|---|---|" + "---|" * 9]
    for name, c in {**R["reference_liquid"], **R["combinations_liquid"]}.items():
        mark = " ✅" if c.get("passed") else ""
        for per in ("train", "test"):
            L.append(f"| {name}{mark if per == 'train' else ''} | {per} | {_fmt(c[per])} | {c[per].get('months_beat_base_pct', '–')} |")
    L += ["", "Definitions:", ""]
    for name, c in R["combinations"].items():
        L.append(f"- **{name}**: {c['definition']}")
    L += ["", "## Decision trees (data-driven pass, fitted on 2024 only)", "",
          "Tree A uses raw values; tree B uses each numeric feature's within-month percentile, so it cannot simply pick out "
          "the months that rallied (with 12 training months, raw market-wide features such as sector momentum can do that)."]
    for lab, T_ in (("A (raw values)", R["tree"]), ("B (within-month percentiles)", R["tree_ranked"])):
        L += ["", f"### Tree {lab}", ""]
        if T_.get("error"):
            L.append(f"Not run: {T_['error']}")
        else:
            L.append(f"Depth 3, min leaf {T_['min_samples_leaf']} rows ({T_['train_rows']} training rows). Splits used: "
                     + ", ".join(f"{c} ({v})" for c, v in T_["importances"]) + ".")
            L.extend(["", f"| leaf rule | period | {cols} | held? |", "|---|---|" + "---|" * 9])
            for lf in T_["leaves"]:
                L.append(f"| {lf['rule']} | train | {_fmt(lf['train'])} | |")
                L.append(f"| | test | {_fmt(lf['test'])} | {'✅' if lf['held_out_of_sample'] else ''} |")
    P = R["pipeline"]
    for per in ("test", "train", "all"):
        x = P[per]
        L += ["", f"## Where the pipeline lost winners ({per}: {x['totals']['winners']} winners, {x['totals']['losers']} losers of {x['totals']['rows']} stock-months)", "",
              "First reason the pipeline stopped each stock (order: level 'out' → L1/L2 tier → valuation → trend → R1 → R2 → R4 → R6 → candidate). Loser = 12-month return < 0.", "",
              "| stopped at | n | winners | % of all winners | losers | % of all losers | hit % | loss % | avg ret % |", "|---|---|---|---|---|---|---|---|---|"]
        for r in x["by_stop_first_reason"]:
            L.append(f"| {r['stop']} | {r['n']} | {r['winners']} | {r['share_of_all_winners_pct']} | {r['losers']} | {r['share_of_all_losers_pct']} | {r['hit_pct']} | {r['loss_pct']} | {r['avg_ret']} |")
        L += ["", "| check on its own | n | winners | % of all winners | losers | % of all losers | hit % |", "|---|---|---|---|---|---|---|"]
        for r in x["each_check_alone"]:
            L.append(f"| {r['check']} | {r['n']} | {r['winners']} | {r['share_of_all_winners_pct']} | {r['losers']} | {r['share_of_all_losers_pct']} | {r['hit_pct']} |")
    L += ["", "Hit rate by level tier (test period):", ""]
    for lv, tb in P["test"]["tiers"].items():
        L.append(f"- {lv}: " + ", ".join(f"tier {t} {v['hit_pct']}% (n {v['n']})" for t, v in sorted(tb.items())))
    L += ["", "## Feature coverage", "", "| feature | train % with a value | test % |", "|---|---|---|"]
    for f, v in R["single"].items():
        if v.get("coverage"):
            L.append(f"| {f} | {v['coverage']['train_pct']} | {v['coverage']['test_pct']} |")
    L += ["", "## Caveats", ""]
    for c in R["caveats"]:
        L.append(f"- {c}")
    L += ["", "Not built point-in-time:", ""]
    for k, v in NOT_BUILT.items():
        L.append(f"- {k}: {v}")
    return "\n".join(L) + "\n"


def run() -> dict:
    t0 = time.time()
    RP._load(QUICK)
    P_.update(RP.P)
    b = RP.P[config.BENCHMARK]["Close"]
    bb = b[b.index >= pd.Timestamp(START)]
    ends = bb.groupby(bb.index.to_period("M")).apply(lambda x: x.index[-1])
    last_ok = b.index[-1 - 252] if len(b) > 253 else b.index[0]
    dates = [str(d.date()) for d in ends if d <= last_ok]
    if QUICK:
        dates = [dates[0], dates[len(dates) // 2], dates[-1]]
    print(f"[study] {len(RP.FIN)} stocks with filings, {len(dates)} month ends {dates[0]} .. {dates[-1]}")
    with Pool() as pool:
        res = pool.map(_study_month, dates)
    df = pd.DataFrame([r for m in res for r in m])
    df["year"] = df["T"].str[:4]
    train, test = df[df["year"] == "2024"].copy(), df[df["year"] == "2025"].copy()
    base_all, base_tr = float(df["win"].mean()), float(train["win"].mean()) if len(train) else 0.0
    base_te = float(test["win"].mean()) if len(test) else 0.0
    num_feats = [f for fs in GROUPS.values() for f in fs if f not in BOOLEAN and f not in CATEGORICAL]
    Q = terciles(train if len(train) else df, num_feats, test)
    R = {"generated": time.strftime("%Y-%m-%d"), "quick": QUICK, "dates": [dates[0], dates[-1]], "months": len(dates),
         "label": "winner = 12-month return >= 25% (absolute); beat = 12-month return above the Nifty's",
         "split": "train = buy dates in 2024, test = buy dates in 2025", "finding_rule": f"lift > {MIN_LIFT} in both periods and test n >= {MIN_TEST_N}",
         "terciles_2024": Q, "terciles_from_2025_no_2024_data": TERC_FROM_TEST, "not_built": NOT_BUILT}
    R["base"] = {"all": stats(df, base_all), "train": stats(train, base_tr), "test": stats(test, base_te),
                 "by_month": [{"T": T, **{k: v for k, v in stats(x, float(x["win"].mean())).items() if k in ("n", "hit_pct", "avg_ret", "beat_nifty_pct")}}
                              for T, x in df.groupby("T")]}
    R["single"] = single_lift(train, test, base_tr, base_te, Q)
    cand = []
    for f, v in R["single"].items():
        for b_, st in v["buckets"].items():
            if b_ == "missing" or st["train"].get("n", 0) < 100:
                continue
            lt, le = st["train"].get("lift"), st["test"].get("lift")
            cand.append({"feature": f, "desc": DESC.get(f), "bucket": b_, "train": st["train"], "test": st["test"],
                         "min_lift": min(lt or 0, le or 0) if st["test"].get("n", 0) >= MIN_TEST_N else 0})
    R["top_single"] = sorted(cand, key=lambda x: -x["min_lift"])[:25]
    R["top_single_by_train_lift"] = sorted(cand, key=lambda x: -(x["train"].get("lift") or 0))[:15]
    R["bottom_single"] = sorted([c for c in cand if c["test"].get("n", 0) >= MIN_TEST_N
                                 and max(c["train"].get("lift") or 9, c["test"].get("lift") or 9) <= 0.8],
                                key=lambda x: max(x["train"]["lift"], x["test"]["lift"]))[:15]
    C = combos(Q)
    R["reference"] = eval_rules(REFERENCE, train, test, base_tr, base_te, df)
    R["combinations"] = eval_rules(C, train, test, base_tr, base_te, df)
    ltr, lte = liquid(train), liquid(test)
    lb_tr, lb_te = (float(ltr["win"].mean()) if len(ltr) else 0.0), (float(lte["win"].mean()) if len(lte) else 0.0)
    R["reference_liquid"] = eval_rules(REFERENCE, ltr, lte, lb_tr, lb_te, df)
    R["combinations_liquid"] = eval_rules(C, ltr, lte, lb_tr, lb_te, df)
    R["liquid_filter"] = LIQ_TEXT
    R["tree"] = tree_pass(train, test, base_tr, base_te)
    R["tree_ranked"] = tree_pass(train, test, base_tr, base_te, rank=True)
    R["pipeline"] = {"all": pipeline_tally(df), "train": pipeline_tally(train) if len(train) else {}, "test": pipeline_tally(test) if len(test) else {}}
    R["caveats"] = [
        "Survivor bias: the universe is today's listed stocks with stored filings; companies delisted or suspended since are missing, which flatters every hit rate (most for small caps).",
        "Overlapping windows: each stock appears every month, and consecutive 12-month windows overlap by 11 months, so the "
        f"{len(df)} stock-months are far from independent; effective sample sizes are closer to the number of distinct stocks per period, and month-level effects (a rally) move all rows together.",
        "Short period and regime: 2024 buy dates rode the small-cap rally into its Sept-2024 peak and the correction after; 2025 buy dates are a different market. A trait that worked in one may not in the other; that is what the train/test split checks, but two regimes are still only two.",
        "Filings start in late 2022/2023 for most companies, so in 2024 many growth, ROCE-change, 3-year and own-history valuation features are missing or rest on 2-year spans; the pipeline's quality level (which needs ~3 years of quarters) rejects most stocks in 2024 as 'unknown', so the 2024 pipeline tally mostly measures missing history, not the rules.",
        "Thresholds from 2024 terciles were applied unchanged to 2025; definitions were written before results were seen. The decision tree is the only data-mined step and is judged on 2025 alone.",
        "Size dominates: the smallest and least-traded stocks have by far the highest 25% hit rates. Those are also where survivor bias is worst (failed micro-caps delisted and missing) and where returns are hardest to capture (circuit limits, impact cost); the 'tradeable only' table repeats every rule within market cap ≥ ₹500 cr and ≥ ₹1 cr/day.",
        "Industry and sector labels are today's classification (docs/data/picks.json), applied to the past.",
        "Pipeline replay covers code rules only (no Claude review, research, announcements, analysts, shareholding for the management level).",
    ]
    R["minutes"] = round((time.time() - t0) / 60, 1)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(R, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    OUT_MD.write_text(report(R))
    print(f"[study] base all {R['base']['all']} train {R['base']['train'].get('hit_pct')} test {R['base']['test'].get('hit_pct')}")
    for name, c in {**R["reference"], **R["combinations"], **{f"[liquid] {k}": v for k, v in R["combinations_liquid"].items()}}.items():
        print(f"[study] {name}: train {c['train'].get('n')} hit {c['train'].get('hit_pct')} lift {c['train'].get('lift')} | "
              f"test {c['test'].get('n')} hit {c['test'].get('hit_pct')} lift {c['test'].get('lift')} {'PASS' if c['passed'] else ''}")
    print(f"[study] done in {R['minutes']} min")
    return R


if __name__ == "__main__":
    run()
