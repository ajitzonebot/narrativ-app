"""10-year multibagger study: which start-date traits, and which 2-3 trait combinations, were more common among
stocks that went on to 5x (and 10x) within 5 years than among look-alike stocks that did not.

    python scripts/study_10y.py --probe     # time-boxed check of how far back annual fundamentals go (NSE, Yahoo)
    python scripts/study_10y.py [--quick]   # the study (quick: 300 stocks, yearly start dates, outputs under data/study_10y/)

Research only: reads docs/data/picks.json and data/financials, downloads long Yahoo history into data/study_cache/
(kept in the Actions cache, never in git), writes docs/data/study_10y.json and docs/research/study_10y.md.
Nothing in the pipeline reads these files.

The trait and combination definitions below (TRAITS, COMBOS, FUND_COMBOS, PASS rule) were written and committed
before the first full run; they are not tuned on the results.
"""
import argparse
import json
import math
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/study_cache/prices_10y.pkl"
PROBE = ROOT / "data/study_10y/probe.json"
HIST_START = "2002-01-01"

# ---- pre-registered definitions ------------------------------------------------------------------------------------
LIQ_MIN = 1e6            # median daily turnover (close x volume) over the prior 63 trading days >= Rs 10 lakh
MIN_HIST = 126           # at least ~6 months of prices before the start date
HORIZON_Y = 5            # multibagger window
MB = 5.0                 # 5x
MB10 = 10.0
SMOOTH = 5               # outcome uses a 5-day rolling median of the adjusted close (one bad Yahoo tick cannot make a 5x)
BASE_RANGE = 1.5         # "sideways": highest close / lowest close within the window <= 1.5
DISCOVER = (2014, 2017)  # start-date years
TEST = (2018, 2021)
PASS_LIFT = 1.3
PASS_MIN_FLAGS = 150     # flagged observations per half
PASS_MIN_HITS = 15       # flagged multibagger observations per half
SMALL_RANK = 250         # SEBI-style: market-cap rank 1-100 large, 101-250 mid, 251+ small; 751+ also "micro"
MICRO_RANK = 750
BIG_MC = 1000            # Rs crore: selection-bias check (see main)

COMBOS = {
    # given by the owner
    "a_small_nearhigh_rs": ("Small cap + within 10% of 52-week high + 12-month RS top tercile",
                            lambda t: t.small & t.near_high & t.rs_top),
    "b_small_longbase_breakout": ("Small cap + base >= 12 months + close above the base high",
                                  lambda t: t.small & t.base_long & t.breakout),
    "c_beaten_above200": ("Beaten down (>= 50% below all-time high) + above 200-day average",
                          lambda t: t.beaten50 & t.above200),
    "d_liqup_rs_small": ("Turnover rising (63d median >= 1.5x prior 9 months) + RS top tercile + small cap",
                         lambda t: t.liq_rising & t.rs_top & t.small),
    "e_sector_rs": ("Sector 12-month strength top tercile + stock RS top tercile",
                    lambda t: t.sector_top & t.rs_top),
    "f_lowvol_breakout": ("Low volatility (252d, bottom tercile) + breakout above a >= 6-month base",
                          lambda t: t.vol_low & t.breakout),
    # added before evaluating
    "g_micro_stage2": ("Micro cap (rank 751+) + above 200-day average + 50-day above 200-day + 200-day rising",
                       lambda t: t.micro & t.stage2),
    "h_small_lowvol_rs": ("Small cap + low volatility (bottom tercile) + RS top tercile",
                          lambda t: t.small & t.vol_low & t.rs_top),
    "i_small_turnaround": ("Small cap + >= 50% below all-time high + 6-month return >= +30%",
                           lambda t: t.small & t.beaten50 & t.ret6_30),
    "j_young_small_above200": ("Listed < 3 years + small cap + above 200-day average",
                               lambda t: t.young & t.small & t.above200),
    "k_sector_small_nearhigh": ("Sector strength top tercile + small cap + within 10% of 52-week high",
                                lambda t: t.sector_top & t.small & t.near_high),
    "l_lowprice_small_rs": ("Share price < Rs 50 + small cap + RS top tercile",
                            lambda t: t.price_low & t.small & t.rs_top),
}
FUND_COMBOS = {
    "m_profit_accel_cheap": ("FY profit growth > 25% + latest-quarter YoY growth above the FY growth + P/E below sector median "
                             "(own-history P/E not available: < 3 years of filings)",
                             lambda t: t.fy_growth25 & t.accel & t.pe_below_sector),
    "n_roce_lowdebt_small": ("ROCE > 20% + debt/equity < 0.5 + small cap",
                             lambda t: t.roce20 & t.de_low & t.small),
}
TRAIT_LABELS = {
    "large": "Large cap (rank 1-100)", "mid": "Mid cap (rank 101-250)", "small": "Small cap (rank 251+)",
    "micro": "Micro cap (rank 751+)", "near_high": "Within 10% of 52-week high", "far_high": "> 40% below 52-week high",
    "ret6_top": "6-month return top tercile", "rs_top": "12-month RS top tercile", "rs_bottom": "12-month RS bottom tercile",
    "beats_nifty": "12-month return above Nifty 50", "ret36_top": "36-month return top tercile",
    "ret36_bottom": "36-month return bottom tercile", "ret6_30": "6-month return >= +30%",
    "beaten50": ">= 50% below all-time high", "beaten75": ">= 75% below all-time high",
    "vol_low": "Volatility bottom tercile", "vol_high": "Volatility top tercile",
    "liq_rising": "Turnover rising >= 1.5x", "liq_falling": "Turnover falling <= 0.67x",
    "turn_low": "Turnover bottom tercile (thinly traded)", "above200": "Above 200-day average",
    "golden": "50-day above 200-day average", "stage2": "Stage 2 (above 200d, 50d > 200d, 200d rising)",
    "base_long": "Sideways base >= 12 months", "base_6": "Sideways base >= 6 months",
    "breakout": "Close above a >= 6-month base high", "young": "Listed < 3 years", "old": "Price history >= 10 years",
    "sector_top": "Sector strength top tercile", "sector_bottom": "Sector strength bottom tercile",
    "price_low": "Share price < Rs 50",
    "fy_growth25": "FY24 profit growth > 25%", "accel": "Mar-24 quarter profit YoY above FY24 growth",
    "pe_below_sector": "P/E below sector median", "roce20": "ROCE > 20%", "de_low": "Debt/equity < 0.5",
    "profitable": "Profitable (FY24)",
}
TREE_FEATURES = ["mc_pct", "near", "ret6", "ret12", "ret36", "rs12", "dd_ath", "vol", "log_turn", "liq_trend",
                 "dist200", "sma50_200", "base_m", "age_y", "sector_ret12", "log_price"]


def log(*a):
    print(*a, flush=True)


# ---- data ----------------------------------------------------------------------------------------------------------
def universe():
    d = json.loads((ROOT / "docs/data/picks.json").read_text())
    return {r["s"]: {"i": r.get("i"), "sec": r.get("sec") or "Unknown", "mc": r.get("mc")} for r in d["picks"]}


def download_long(symbols, chunk=60):
    import yfinance as yf
    have = {}
    if CACHE.exists():
        have = pickle.loads(CACHE.read_bytes())
        log(f"[prices] cache has {len(have)} series")
    need = [s for s in symbols if s not in have]
    t0 = time.time()
    for k in range(0, len(need), chunk):
        batch = need[k:k + chunk]
        data = None
        for attempt in range(3):
            try:
                data = yf.download(batch, start=HIST_START, interval="1d", group_by="ticker", auto_adjust=False,
                                   actions=False, progress=False, threads=True)
                break
            except Exception as e:  # noqa: BLE001
                log(f"[prices] retry {attempt + 1}: {e}")
                time.sleep(10 * (attempt + 1))
        if data is None:
            continue
        for s in batch:
            try:
                df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(subset=["Close"])
                if len(df) >= 20:
                    have[s] = df[["Close", "Adj Close", "Volume"]].astype("float32")
                else:
                    have[s] = None
            except KeyError:
                have[s] = None
        log(f"[prices] {min(k + chunk, len(need))}/{len(need)} downloaded, {time.time() - t0:.0f}s")
        time.sleep(0.5)
    if "^NSEI" not in have or have["^NSEI"] is None:
        df = yf.download("^NSEI", start=HIST_START, auto_adjust=False, actions=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        have["^NSEI"] = df[["Close", "Adj Close", "Volume"]].astype("float32")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(have))
    return have


# ---- probe ---------------------------------------------------------------------------------------------------------
def probe():
    """How far back do annual results go at sources that allow automated access? A few symbols only."""
    out = {"checked": datetime.now(timezone.utc).isoformat(timespec="minutes"), "nse": {}, "yahoo": {}}
    syms = ["RELIANCE", "INFY", "20MICRONS", "SATIN", "KPRMILL", "APARINDS"]
    try:
        sys.path.insert(0, str(ROOT))
        from narrativ.filings import BASE, NSESession, _d
        ns = NSESession()
        for code in syms:
            rec = {}
            for period in ("Annual", "Quarterly"):
                d = ns.get(BASE + "/api/corporates-financial-results", {"index": "equities", "symbol": code, "period": period})
                rows = d if isinstance(d, list) else (d or {}).get("data") or []
                dates = sorted(str(_d(x.get("toDate"))) for x in rows if _d(x.get("toDate")))
                xb = sorted(str(_d(x.get("toDate"))) for x in rows if _d(x.get("toDate")) and str(x.get("xbrl") or "").endswith(".xml"))
                rec[period] = {"rows": len(rows), "earliest": dates[0] if dates else None,
                               "earliest_with_xbrl": xb[0] if xb else None, "with_xbrl": len(xb)}
                time.sleep(1)
            out["nse"][code] = rec
            log("[probe] NSE", code, rec)
    except Exception as e:  # noqa: BLE001
        out["nse_error"] = repr(e)
    try:
        import yfinance as yf
        for code in syms[:4]:
            t = yf.Ticker(code + ".NS")
            rec = {}
            for name in ("income_stmt", "balance_sheet"):
                try:
                    df = getattr(t, name)
                    rec[name] = sorted(str(c)[:10] for c in df.columns) if df is not None and len(df.columns) else []
                except Exception as e:  # noqa: BLE001
                    rec[name] = repr(e)
            out["yahoo"][code] = rec
            log("[probe] Yahoo", code, rec)
    except Exception as e:  # noqa: BLE001
        out["yahoo_error"] = repr(e)
    PROBE.parent.mkdir(parents=True, exist_ok=True)
    PROBE.write_text(json.dumps(out, indent=1))


# ---- panel ---------------------------------------------------------------------------------------------------------
def build_panel(px, syms):
    syms = [s for s in syms if px.get(s) is not None]
    idx = px["^NSEI"].index
    for s in syms:
        idx = idx.union(px[s].index)
    idx = idx[idx >= pd.Timestamp(HIST_START)]
    craw = pd.DataFrame({s: px[s]["Close"] for s in syms}).reindex(idx).astype("float64")
    adj = pd.DataFrame({s: px[s]["Adj Close"] for s in syms}).reindex(idx).astype("float64")
    vol = pd.DataFrame({s: px[s]["Volume"] for s in syms}).reindex(idx).astype("float64")
    craw[craw <= 0] = np.nan
    adj[adj <= 0] = np.nan
    nifty = px["^NSEI"]["Adj Close"].reindex(idx).ffill().astype("float64")
    return idx, syms, craw, adj, vol, nifty


def compute(idx, syms, craw, adj, vol, nifty, uni, start_dates):
    T, N = craw.shape
    Craw = craw.values
    exists = ~np.isnan(Craw)
    C = craw.ffill(limit=10).values
    A = adj.ffill(limit=10).values
    TO = np.where(exists, Craw * np.nan_to_num(vol.values), 0.0)
    cnt = np.cumsum(exists, axis=0)
    first = np.argmax(exists, axis=0)
    first_date = idx.values[first]
    ATH = np.fmax.accumulate(np.where(np.isnan(A), -np.inf, A), axis=0)
    ATH[np.isinf(ATH)] = np.nan
    M = adj.ffill(limit=10).rolling(SMOOTH, min_periods=3).median().values
    LR = np.vstack([np.full((1, N), np.nan), np.diff(np.log(A), axis=0)])
    NF = nifty.values
    sector = np.array([uni[s]["sec"] for s in syms])
    mc_now = np.array([uni[s]["mc"] or np.nan for s in syms], dtype=float)
    last_close = np.array([craw[s].dropna().iloc[-1] for s in syms])
    dates = idx
    rows = []
    for sd in start_dates:
        i = int(dates.searchsorted(sd, side="right")) - 1
        if i < 260:
            continue
        d0 = dates[i]
        has = exists[max(0, i - 4):i + 1].any(axis=0)
        hist = cnt[i]
        med63 = np.median(TO[i - 62:i + 1], axis=0)
        liquid = has & (hist >= MIN_HIST) & (med63 >= LIQ_MIN) & ~np.isnan(A[i])
        if liquid.sum() < 30:
            continue
        a, c = A[i], C[i]

        def back(k):
            return A[i - k] if i - k >= 0 else np.full(N, np.nan)

        with np.errstate(all="ignore"):
            hi52 = np.nanmax(A[i - 251:i + 1], axis=0)
            near = a / hi52
            ret6, ret12, ret36 = a / back(126) - 1, a / back(252) - 1, a / back(756) - 1
            ret6[hist < 126], ret12[hist < 252], ret36[hist < 756] = np.nan, np.nan, np.nan
            n12 = NF[i] / NF[i - 252] - 1
            rs12 = (1 + ret12) / (1 + n12) - 1
            dd = a / ATH[i] - 1
            win = LR[i - 251:i + 1]
            vola = np.nanstd(win, axis=0) * math.sqrt(252)
            vola[np.sum(~np.isnan(win), axis=0) < 120] = np.nan
            prev = np.median(TO[i - 251:i - 62], axis=0)
            liq_trend = np.where((prev > 0) & (hist >= 252), med63 / prev, np.nan)
            sma200 = np.nanmean(A[i - 199:i + 1], axis=0)
            sma50 = np.nanmean(A[i - 49:i + 1], axis=0)
            sma200p = np.nanmean(A[i - 220:i - 20], axis=0)
            sma200[hist < 200], sma200p[hist < 221] = np.nan, np.nan
            # base: longest window ending 21 trading days before the start date with max/min close <= BASE_RANGE
            e = i - 21
            seg = A[max(0, e - 756):e + 1][::-1]
            rmax = np.fmax.accumulate(np.where(np.isnan(seg), -np.inf, seg), axis=0)
            rmin = np.fmin.accumulate(np.where(np.isnan(seg), np.inf, seg), axis=0)
            ratio = rmax / rmin
            exceed = ratio > BASE_RANGE
            blen = np.where(exceed.any(axis=0), np.argmax(exceed, axis=0), seg.shape[0])
            blen = np.minimum(blen, np.maximum(hist - 21, 0))
            bmax = rmax[np.clip(blen - 1, 0, seg.shape[0] - 1), np.arange(N)]
            base_m = blen / 21.0
            breakout = (base_m >= 6) & (a > bmax)
            age_y = (np.datetime64(d0) - first_date).astype("timedelta64[D]").astype(float) / 365.25
            mc_est = mc_now * c / last_close
        # ranks among liquid stocks
        L = np.where(liquid)[0]

        def pct(x):
            return pd.Series(x[L]).rank(pct=True).values

        P = {"ret6": pct(ret6), "ret12": pct(ret12), "ret36": pct(ret36), "vol": pct(vola), "turn": pct(med63)}

        mc_rank = pd.Series(mc_est[L]).rank(ascending=False, method="first").values
        sec_df = pd.DataFrame({"sec": sector[L], "r": ret12[L]})
        sec_med = sec_df.groupby("sec")["r"].agg(["median", "count"])
        sec_med = sec_med[sec_med["count"] >= 5]["median"]
        sec_pct = sec_med.rank(pct=True)
        # forward outcome
        j_end = int(dates.searchsorted(d0 + pd.DateOffset(years=HORIZON_Y), side="right")) - 1
        fwd_years = (dates[j_end] - d0).days / 365.25
        for k, n in enumerate(L):
            path = M[i + 1:j_end + 1, n] / a[n]
            if not np.isfinite(path).any():
                continue
            maxr = np.nanmax(path)
            hit = np.argmax(path >= MB) if maxr >= MB else -1
            end_r = A[j_end, n] / a[n] if np.isfinite(A[j_end, n]) else path[np.isfinite(path)][-1]
            days5 = dd_route = worst = None
            if hit >= 0:
                p = pd.Series(path[:hit + 1]).ffill().values
                peak = np.fmax.accumulate(np.fmax(p, 1.0))
                dd_route = float(np.nanmin(p / peak) - 1)
                worst = float(np.nanmin(p) - 1)
                days5 = int((dates[i + 1 + hit] - d0).days)
            rows.append({
                "date": d0.strftime("%Y-%m-%d"), "year": d0.year, "sym": syms[n], "sec": sector[n],
                "mc_rank": int(mc_rank[k]), "mc_pct": 1 - (mc_rank[k] - 1) / len(L), "mc_est": float(mc_est[n]),
                "near": float(near[n]), "ret6": float(ret6[n]), "ret12": float(ret12[n]), "ret36": float(ret36[n]),
                "rs12": float(rs12[n]), "dd_ath": float(dd[n]), "vol": float(vola[n]), "turn": float(med63[n]),
                "liq_trend": float(liq_trend[n]), "dist200": float(a[n] / sma200[n] - 1),
                "sma50_200": float(sma50[n] / sma200[n] - 1), "sma200_up": bool(sma200[n] > sma200p[n]),
                "base_m": float(base_m[n]), "breakout": bool(breakout[n]), "age_y": float(age_y[n]), "price": float(c[n]),
                "sector_ret12": float(sec_med.get(sector[n], np.nan)), "sector_pct": float(sec_pct.get(sector[n], np.nan)),
                "ret6_pct": float(P["ret6"][k]), "ret12_pct": float(P["ret12"][k]), "ret36_pct": float(P["ret36"][k]),
                "vol_pct": float(P["vol"][k]), "turn_pct": float(P["turn"][k]),
                "maxr": float(maxr), "end_r": float(end_r), "fwd_years": round(fwd_years, 2),
                "days5": days5, "dd_route": dd_route, "worst": worst,
            })
        log(f"[study] {d0:%Y-%m-%d}: {len(L)} liquid, {sum(1 for r in rows if r['date'] == d0.strftime('%Y-%m-%d') and r['maxr'] >= MB)} reached 5x")
    return pd.DataFrame(rows)


def add_traits(df):
    t = df
    nan_false = lambda s: s.fillna(False).astype(bool)  # noqa: E731
    t["large"] = t.mc_rank <= 100
    t["mid"] = (t.mc_rank > 100) & (t.mc_rank <= SMALL_RANK)
    t["small"] = t.mc_rank > SMALL_RANK
    t["micro"] = t.mc_rank > MICRO_RANK
    t["near_high"] = t.near >= 0.90
    t["far_high"] = t.near < 0.60
    t["ret6_top"] = nan_false(t.ret6_pct >= 2 / 3) & t.ret6.notna()
    t["rs_top"] = (t.ret12_pct >= 2 / 3) & t.ret12.notna()
    t["rs_bottom"] = (t.ret12_pct <= 1 / 3) & t.ret12.notna()
    t["beats_nifty"] = t.rs12 > 0
    t["ret36_top"] = (t.ret36_pct >= 2 / 3) & t.ret36.notna()
    t["ret36_bottom"] = (t.ret36_pct <= 1 / 3) & t.ret36.notna()
    t["ret6_30"] = t.ret6 >= 0.30
    t["beaten50"] = t.dd_ath <= -0.50
    t["beaten75"] = t.dd_ath <= -0.75
    t["vol_low"] = (t.vol_pct <= 1 / 3) & t.vol.notna()
    t["vol_high"] = (t.vol_pct >= 2 / 3) & t.vol.notna()
    t["liq_rising"] = t.liq_trend >= 1.5
    t["liq_falling"] = t.liq_trend <= 0.67
    t["turn_low"] = t.turn_pct <= 1 / 3
    t["above200"] = t.dist200 > 0
    t["golden"] = t.sma50_200 > 0
    t["stage2"] = t.above200 & t.golden & t.sma200_up
    t["base_long"] = t.base_m >= 12
    t["base_6"] = t.base_m >= 6
    t["young"] = t.age_y < 3
    t["old"] = t.age_y >= 10
    t["sector_top"] = t.sector_pct >= 2 / 3
    t["sector_bottom"] = t.sector_pct <= 1 / 3
    t["price_low"] = t.price < 50
    t["mb5"] = t.maxr >= MB
    t["mb10"] = t.maxr >= MB10
    t["half"] = np.where(t.year <= DISCOVER[1], "discover", "test")
    t["log_turn"] = np.log10(t.turn)
    t["log_price"] = np.log10(t.price)
    return t


# ---- evaluation ----------------------------------------------------------------------------------------------------
def rnd(x, k=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), k)


def evaluate(df, flag, n_dates):
    """Hit rate, lift (hit rate when flagged / base rate), matched lift, flags per date, flagged losers' outcome."""
    out = {}
    for half in ("discover", "test", "all"):
        d = df if half == "all" else df[df.half == half]
        f = flag.loc[d.index]
        n, nf = len(d), int(f.sum())
        base = d.mb5.mean() if n else np.nan
        hits = int((f & d.mb5).sum())
        hr = hits / nf if nf else np.nan
        hr10 = (f & d.mb10).sum() / nf if nf else np.nan
        base10 = d.mb10.mean() if n else np.nan
        losers = d[f & ~d.mb5]
        # matched: same date, same market-cap band, same sector -> expected prevalence among each multibagger's look-alikes
        mbd = d[d.mb5]
        key = d["date"] + "|" + d["band"] + "|" + d["sec"]
        nonmb = d[~d.mb5]
        prev_nonmb = f.loc[nonmb.index].groupby(key.loc[nonmb.index]).mean()
        exp = key.loc[mbd.index].map(prev_nonmb).dropna()
        act = f.loc[exp.index].mean() if len(exp) else np.nan
        matched = act / exp.mean() if len(exp) and exp.mean() > 0 else np.nan
        out[half] = {
            "n_obs": n, "n_flagged": nf, "flags_per_date": rnd(nf / max(n_dates[half], 1), 1),
            "mb_hits": hits, "mb_unique_stocks": int(d[f & d.mb5].sym.nunique()),
            "hit_rate": rnd(hr), "base_rate": rnd(base), "lift": rnd(hr / base if base else np.nan, 2),
            "hit_rate_10x": rnd(hr10), "lift_10x": rnd(hr10 / base10 if base10 else np.nan, 2),
            "prevalence_in_mb": rnd(f[d.mb5].mean() if d.mb5.any() else np.nan),
            "prevalence_in_others": rnd(f[~d.mb5].mean()),
            "matched_prevalence_ratio": rnd(matched, 2),
            "losers_median_5y_return": rnd(losers.end_r.median() - 1 if len(losers) else np.nan),
            "losers_share_lost_money": rnd((losers.end_r < 1).mean() if len(losers) else np.nan),
            "flagged_median_5y_return": rnd(d[f].end_r.median() - 1 if nf else np.nan),
        }
    dh, th = out["discover"], out["test"]
    out["passed"] = bool(all(h["lift"] is not None and h["lift"] > PASS_LIFT and h["n_flagged"] >= PASS_MIN_FLAGS
                             and h["mb_hits"] >= PASS_MIN_HITS for h in (dh, th)))
    out["test_lift_ci90"] = cluster_ci(df[df.half == "test"], flag)
    return out


def cluster_ci(d, flag, reps=300, seed=7):
    """90% interval of the lift, resampling whole stocks (each stock appears at many start dates)."""
    if d.empty:
        return None
    f = flag.loc[d.index].values
    g = d.sym.values
    codes, uniq = pd.factorize(g)
    agg = np.zeros((len(uniq), 4))
    np.add.at(agg, codes, np.c_[np.ones(len(d)), f, d.mb5.values, f & d.mb5.values])
    rng = np.random.default_rng(seed)
    lifts = []
    for _ in range(reps):
        w = rng.multinomial(len(uniq), np.full(len(uniq), 1 / len(uniq)))
        s = w @ agg
        if s[1] > 0 and s[2] > 0:
            lifts.append((s[3] / s[1]) / (s[2] / s[0]))
    if len(lifts) < 50:
        return None
    return [rnd(np.percentile(lifts, 5), 2), rnd(np.percentile(lifts, 95), 2)]


def tree_finds(df):
    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        return {"error": "scikit-learn not installed"}
    disc, test = df[df.half == "discover"], df[df.half == "test"]
    X = disc[TREE_FEATURES].fillna(-9).values
    leaf_min = max(200, int(0.01 * len(disc)))
    clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=leaf_min, class_weight="balanced", random_state=0)
    clf.fit(X, disc.mb5.values)
    tr = clf.tree_
    paths = {}

    def walk(node, conds):
        if tr.children_left[node] == -1:
            paths[node] = conds
            return
        f, th = TREE_FEATURES[tr.feature[node]], tr.threshold[node]
        walk(tr.children_left[node], conds + [(f, "<=", th)])
        walk(tr.children_right[node], conds + [(f, ">", th)])

    walk(0, [])
    leaves = []
    for node, conds in paths.items():
        out = {"rule": " AND ".join(f"{f} {op} {th:.3g}" for f, op, th in conds)
               + ("  (missing values coded -9)" if any(th < -8 for _, _, th in conds) else "")}
        for name, d in (("discover", disc), ("test", test)):
            m = np.ones(len(d), bool)
            Xd = d[TREE_FEATURES].fillna(-9)
            for f, op, th in conds:
                m &= (Xd[f].values <= th) if op == "<=" else (Xd[f].values > th)
            nf, hits = int(m.sum()), int((m & d.mb5.values).sum())
            base = d.mb5.mean()
            out[name] = {"n": nf, "hits": hits, "hit_rate": rnd(hits / nf if nf else np.nan),
                         "lift": rnd(hits / nf / base if nf and base else np.nan, 2)}
        out["held"] = bool(all(out[h]["lift"] is not None and out[h]["lift"] > PASS_LIFT and out[h]["n"] >= PASS_MIN_FLAGS
                               and out[h]["hits"] >= PASS_MIN_HITS for h in ("discover", "test")))
        leaves.append(out)
    leaves.sort(key=lambda x: -(x["discover"]["lift"] or 0))
    imp = sorted(zip(TREE_FEATURES, clf.feature_importances_), key=lambda x: -x[1])
    return {"leaf_min": leaf_min, "leaves": leaves, "importance": [[f, rnd(v)] for f, v in imp if v > 0]}


def fundamentals_sidebar(idx, syms, craw, adj, uni, start="2024-06-28"):
    """Exploratory: the repo's filings start in 2022-23, so fundamentals can only be tested from a mid-2024 start with
    a ~2.4-year forward window (outcome: >= 2x / >= 3x by the latest price)."""
    i = int(idx.searchsorted(pd.Timestamp(start), side="right")) - 1
    d0 = idx[i]
    A = adj.ffill(limit=10).values
    M = adj.ffill(limit=10).rolling(SMOOTH, min_periods=3).median().values
    rows = []
    for n, s in enumerate(syms):
        p = ROOT / "data/financials" / f"{s}.json"
        if not p.exists() or not np.isfinite(A[i, n]):
            continue
        cr = craw[s]
        win = cr.iloc[max(0, i - 62):i + 1]
        if win.notna().sum() < 40:
            continue
        q = json.loads(p.read_text()).get("quarters", {})

        def pick(qe):
            rec = q.get(qe) or {}
            for b in ("Consolidated", "Standalone"):
                r = rec.get(b)
                if r and (r.get("filed") or "9999") <= d0.strftime("%Y-%m-%d"):
                    return r
            return None

        f24, f23 = pick("2024-03-31"), pick("2023-03-31")
        if not f24 or not f23:
            continue

        def pat(x, part):
            v = (x.get(part) or {})
            return v.get("pat_owners") if v.get("pat_owners") is not None else v.get("pat")

        fy24, fy23, q24, q23 = pat(f24, "ytd"), pat(f23, "ytd"), pat(f24, "q"), pat(f23, "q")
        bs = f24.get("bs") or {}
        eq = bs.get("equity_owners") or bs.get("equity")
        borr = (bs.get("borr_cur") or 0) + (bs.get("borr_ncur") or 0)
        y = f24.get("ytd") or {}
        if fy24 is None or not eq:
            continue
        mc_est = (uni[s]["mc"] or np.nan) * cr.iloc[i] / cr.dropna().iloc[-1] if np.isfinite(cr.iloc[i]) else np.nan
        ebit = (y.get("pbt") or 0) + (y.get("fin") or 0)
        path = M[i + 1:, n] / A[i, n]
        rows.append({
            "sym": s, "sec": uni[s]["sec"], "mc_est": mc_est,
            "fy_growth": fy24 / fy23 - 1 if fy23 and fy23 > 0 else np.nan,
            "q_yoy": q24 / q23 - 1 if q24 is not None and q23 and q23 > 0 else np.nan,
            "roce": ebit / (eq + borr) if eq + borr > 0 else np.nan, "de": borr / eq if eq > 0 else np.nan,
            "pe": mc_est * 1e7 / fy24 if fy24 and fy24 > 0 else np.nan,
            "maxr": np.nanmax(path) if np.isfinite(path).any() else np.nan,
        })
    t = pd.DataFrame(rows).dropna(subset=["maxr"])
    if t.empty:
        return {"error": "no stocks with FY23 and FY24 filings"}
    t["mc_rank"] = t.mc_est.rank(ascending=False, method="first")
    t["small"] = t.mc_rank > SMALL_RANK
    t["fy_growth25"] = t.fy_growth > 0.25
    t["accel"] = t.q_yoy > t.fy_growth
    sec_pe = t[t.pe > 0].groupby("sec").pe.median()
    t["pe_below_sector"] = t.pe < t.sec.map(sec_pe)
    t["roce20"] = t.roce > 0.20
    t["de_low"] = t.de < 0.5
    t["profitable"] = t.pe > 0
    out = {"start": d0.strftime("%Y-%m-%d"), "end": idx[-1].strftime("%Y-%m-%d"),
           "years": rnd((idx[-1] - d0).days / 365.25, 2), "n": len(t), "rows": {}}
    for thr in (2.0, 3.0):
        hit = t.maxr >= thr
        base = hit.mean()
        out[f"base_rate_{int(thr)}x"] = rnd(base)
        tests = {k: (TRAIT_LABELS.get(k, k), t[k]) for k in ("small", "fy_growth25", "accel", "pe_below_sector",
                                                             "roce20", "de_low", "profitable")}
        tests.update({k: (lab, fn(t)) for k, (lab, fn) in FUND_COMBOS.items()})
        for k, (lab, f) in tests.items():
            f = f.fillna(False).astype(bool)
            nf, h = int(f.sum()), int((f & hit).sum())
            r = out["rows"].setdefault(k, {"label": lab, "n_flagged": nf})
            r[f"hit_rate_{int(thr)}x"] = rnd(h / nf if nf else np.nan)
            r[f"lift_{int(thr)}x"] = rnd(h / nf / base if nf and base else np.nan, 2)
            r[f"hits_{int(thr)}x"] = h
    return out


def holding_pain(df):
    mb = df[df.mb5].sort_values("date")
    first = mb.groupby("sym").head(1)
    q = lambda s, p: rnd(s.quantile(p), 2)  # noqa: E731
    yrs = first.days5 / 365.25
    return {
        "unique_5x_stocks": int(first.sym.nunique()),
        "years_to_5x_median": q(yrs, 0.5), "years_to_5x_p25": q(yrs, 0.25), "years_to_5x_p75": q(yrs, 0.75),
        "max_drawdown_en_route_median": q(first.dd_route, 0.5),
        "max_drawdown_en_route_p75_worse": q(first.dd_route, 0.25),
        "share_with_drawdown_50pct_or_more": rnd((first.dd_route <= -0.5).mean()),
        "share_fell_10pct_below_start": rnd((first.worst <= -0.1).mean()),
        "worst_below_start_median": q(first.worst, 0.5),
        "share_fell_30pct_below_start": rnd((first.worst <= -0.3).mean()),
        "end_of_window_multiple_median": q(first.end_r, 0.5),
        "share_ended_window_below_3x": rnd((first.end_r < 3).mean()),
        "note": "First start date at which each stock qualified; drawdowns measured on the 5-day median close up to the day it first reached 5x.",
    }


def sectors(df):
    rows = []
    for sec, d in df.groupby("sec"):
        rows.append({"sector": sec, "obs": len(d), "hit_rate": rnd(d.mb5.mean()), "lift": rnd(d.mb5.mean() / df.mb5.mean(), 2),
                     "unique_5x_stocks": int(d[d.mb5].sym.nunique()), "unique_10x_stocks": int(d[d.mb10].sym.nunique()),
                     "unique_stocks": int(d.sym.nunique())})
    return sorted(rows, key=lambda r: -r["unique_5x_stocks"])


# ---- report --------------------------------------------------------------------------------------------------------
def pctf(x, k=1):
    return "–" if x is None else f"{100 * x:.{k}f}%"


def num(x, k=2):
    return "–" if x is None else f"{x:.{k}f}"


def report(R):
    L = []
    w = L.append
    m = R["meta"]
    w("# 10-year multibagger study\n")
    w(f"Generated {m['generated']} by `scripts/study_10y.py` (workflow `study-10y`). Research only; nothing in the pipeline reads it.\n")
    w("## What was tested\n")
    w(f"- Universe: the {m['universe']} stocks in today's `docs/data/picks.json`; {m['with_prices']} had Yahoo daily history "
      f"(from {m['price_from']} to {m['price_to']}). Yahoo adjusted closes (splits, bonuses and dividends) are used for returns; "
      "unadjusted-for-dividends close x volume for turnover.")
    w(f"- Start dates: every quarter-end from {m['start_dates'][0]} to {m['start_dates'][-1]} ({len(m['start_dates'])} dates). "
      f"Discovery half = start years {DISCOVER[0]}-{DISCOVER[1]}, test half = {TEST[0]}-{TEST[1]}.")
    w(f"- Eligible on a start date: a price in the last 5 sessions, at least {MIN_HIST} sessions of history, and median daily "
      f"turnover over the prior 63 sessions of at least Rs {LIQ_MIN / 1e5:.0f} lakh.")
    w(f"- Multibagger: the {SMOOTH}-day median adjusted close reached at least {MB:.0f}x the start price within "
      f"{HORIZON_Y} years ({MB10:.0f}x subset reported too). Windows from late-2021 starts end at the last price "
      f"({m['price_to']}), a few weeks short of 5 years.")
    w(f"- Market-cap band: rank by estimated market cap among eligible stocks that day (today's market cap scaled by the price "
      f"change; ignores share issuance). 1-100 large, 101-250 mid, 251+ small, 751+ micro.")
    w("- Controls: every trait is judged by lift = multibagger hit rate among flagged stocks / hit rate among all eligible stocks "
      "on the same start dates. A second check, the matched prevalence ratio, compares how often multibaggers had the trait "
      "with how often non-multibaggers of the same start date, market-cap band and sector had it.\n")
    w("## Pre-registered combinations (fixed before the first full run)\n")
    w(f"Pass rule: lift > {PASS_LIFT} in both halves, each half with at least {PASS_MIN_FLAGS} flagged observations and "
      f"{PASS_MIN_HITS} flagged multibagger observations.\n")
    for k, (lab, _) in COMBOS.items():
        w(f"- **{k}**: {lab}")
    for k, (lab, _) in FUND_COMBOS.items():
        w(f"- **{k}** (fundamentals): {lab}")
    w("\nTrait definitions: RS = 12-month return percentile among eligible stocks; terciles are taken among eligible stocks "
      f"each start date; a base is the longest window ending 21 sessions before the start date in which the highest close was "
      f"at most {BASE_RANGE}x the lowest; breakout = start-date close above that base's high with a base of at least 6 months; "
      "sector strength = median 12-month return of the sector's eligible stocks, ranked among sectors with 5+ stocks; "
      "turnover trend = 63-day median turnover / median of the 9 months before that.\n")
    w("## Base rates\n")
    s = R["summary"]
    w(f"{s['observations']:,} stock-date observations, {s['unique_stocks']:,} distinct stocks. "
      f"Reached 5x: {pctf(s['base_rate_5x'])} of observations ({s['unique_5x_stocks']} distinct stocks); "
      f"10x: {pctf(s['base_rate_10x'])} ({s['unique_10x_stocks']} stocks). "
      f"Discovery half 5x rate {pctf(s['base_rate_5x_discover'])}, test half {pctf(s['base_rate_5x_test'])}.\n")
    w("| Start date | Eligible | 5x | 5x rate | 10x | 10x rate |\n|---|---:|---:|---:|---:|---:|")
    for b in R["base_rates"]:
        w(f"| {b['date']} | {b['eligible']} | {b['mb5']} | {pctf(b['rate5'])} | {b['mb10']} | {pctf(b['rate10'])} |")
    w("\n## Combination results\n")
    w("Hit rate = share of flagged observations that reached 5x. Flags/date = average flagged stocks per start date. "
      "Losers = flagged stocks that did not reach 5x: their median return to the end of the window and the share that lost money "
      "(dividends included through the adjusted close). CI = 90% interval of the test-half lift, resampling whole stocks.\n")
    w("| Combination | Passed | Disc. hit / lift (n, hits) | Test hit / lift (n, hits) | Test CI | Flags/date (test) | Matched ratio (all) | 10x lift (all) | Losers median 5y / lost money |\n"
      "|---|:---:|---|---|---|---:|---:|---:|---|")
    for k, r in R["combos"].items():
        d, t, a = r["discover"], r["test"], r["all"]
        ci = r.get("test_lift_ci90")
        w(f"| {k} | {'yes' if r['passed'] else 'no'} | {pctf(d['hit_rate'])} / {num(d['lift'])} ({d['n_flagged']}, {d['mb_hits']}) "
          f"| {pctf(t['hit_rate'])} / {num(t['lift'])} ({t['n_flagged']}, {t['mb_hits']}) | {('–' if not ci else f'{ci[0]}-{ci[1]}')} "
          f"| {num(t['flags_per_date'], 1)} | {num(a['matched_prevalence_ratio'])} | {num(a['lift_10x'])} "
          f"| {pctf(a['losers_median_5y_return'], 0)} / {pctf(a['losers_share_lost_money'], 0)} |")
    sc = R["selection_check"]
    w(f"\n### Same combinations, stocks worth at least Rs {BIG_MC:,} crore at the start date\n")
    w("Today's universe requires a market cap of about Rs 200 crore, so small stocks that later fell are missing while small "
      "stocks that rose are present. This look-ahead selection inflates hit rates most for the smallest and cheapest stocks. "
      f"Among stocks already worth Rs {BIG_MC:,} crore or more (estimated) at the start date, only a fall of more than about 80% "
      f"would have removed them, so these lifts are less exposed. {sc['observations']:,} observations; 5x base rate "
      f"{pctf(sc['base_rate_5x'])} (discovery {pctf(sc['base_rate_5x_discover'])}, test {pctf(sc['base_rate_5x_test'])}).\n")
    w("| Combination | Passed | Disc. hit / lift (n, hits) | Test hit / lift (n, hits) | Test CI | Flags/date (test) |\n|---|:---:|---|---|---|---:|")
    for k, r in sc["combos"].items():
        d, t = r["discover"], r["test"]
        ci = r.get("test_lift_ci90")
        w(f"| {k} | {'yes' if r['passed'] else 'no'} | {pctf(d['hit_rate'])} / {num(d['lift'])} ({d['n_flagged']}, {d['mb_hits']}) "
          f"| {pctf(t['hit_rate'])} / {num(t['lift'])} ({t['n_flagged']}, {t['mb_hits']}) | {('–' if not ci else f'{ci[0]}-{ci[1]}')} "
          f"| {num(t['flags_per_date'], 1)} |")
    w("\nSingle traits passing both halves in this subset: " + (", ".join(TRAIT_LABELS[k] for k in sc["passed_traits"]) or "none") + ".\n")
    w("\n## Single traits\n")
    w("| Trait | Passed | Disc. lift (n) | Test lift (n) | Test CI | Prevalence MB vs others (all) | Matched ratio |\n|---|:---:|---|---|---|---|---:|")
    for k, r in sorted(R["traits"].items(), key=lambda kv: -(kv[1]["test"]["lift"] or 0)):
        d, t, a = r["discover"], r["test"], r["all"]
        ci = r.get("test_lift_ci90")
        w(f"| {r['label']} | {'yes' if r['passed'] else 'no'} | {num(d['lift'])} ({d['n_flagged']}) | {num(t['lift'])} ({t['n_flagged']}) "
          f"| {('–' if not ci else f'{ci[0]}-{ci[1]}')} | {pctf(a['prevalence_in_mb'], 0)} vs {pctf(a['prevalence_in_others'], 0)} | {num(a['matched_prevalence_ratio'])} |")
    w("\n## Decision tree (depth 3, trained on the discovery half only)\n")
    tf = R["tree"]
    if "error" in tf:
        w(f"Not run: {tf['error']}\n")
    else:
        w(f"Minimum leaf size {tf['leaf_min']}; class weights balanced. Features: {', '.join(TREE_FEATURES)} "
          "(mc_pct = market-cap percentile, 1 = largest; near = close / 52-week high; dist200 = close / 200-day average - 1; "
          "base_m = base length in months; age_y = years of price history).\n")
        w("| Leaf rule | Disc. n / hit / lift | Test n / hit / lift | Held |\n|---|---|---|:---:|")
        for lf in tf["leaves"]:
            d, t = lf["discover"], lf["test"]
            w(f"| {lf['rule']} | {d['n']} / {pctf(d['hit_rate'])} / {num(d['lift'])} | {t['n']} / {pctf(t['hit_rate'])} / {num(t['lift'])} | {'yes' if lf['held'] else 'no'} |")
        w("\nFeature importance: " + ", ".join(f"{f} {v}" for f, v in tf["importance"]) + "\n")
    w("## Sectors\n")
    w("| Sector | Distinct 5x stocks | Distinct 10x | Distinct stocks | Obs. hit rate | Lift |\n|---|---:|---:|---:|---:|---:|")
    for r in R["sectors"][:15]:
        w(f"| {r['sector']} | {r['unique_5x_stocks']} | {r['unique_10x_stocks']} | {r['unique_stocks']} | {pctf(r['hit_rate'])} | {num(r['lift'])} |")
    w("\n## Holding pain\n")
    h = R["holding_pain"]
    w(f"For the {h['unique_5x_stocks']} distinct stocks that reached 5x (first qualifying start date of each):\n")
    w(f"- Time to 5x: median {num(h['years_to_5x_median'], 1)} years (middle half {num(h['years_to_5x_p25'], 1)}-{num(h['years_to_5x_p75'], 1)}).")
    w(f"- Deepest fall from a previous high on the way to 5x: median {pctf(h['max_drawdown_en_route_median'], 0)}; a quarter fell "
      f"{pctf(h['max_drawdown_en_route_p75_worse'], 0)} or worse; {pctf(h['share_with_drawdown_50pct_or_more'], 0)} had a fall of 50% or more.")
    w(f"- {pctf(h['share_fell_10pct_below_start'], 0)} traded 10% or more below the purchase price at some point before reaching 5x; "
      f"{pctf(h['share_fell_30pct_below_start'], 0)} were 30% or more under water.")
    w(f"- At the end of the 5-year window the median multiple was {num(h['end_of_window_multiple_median'], 1)}x; "
      f"{pctf(h['share_ended_window_below_3x'], 0)} had given back enough to end below 3x.\n")
    w("## Fundamentals\n")
    pr = R.get("probe") or {}
    w(R["fundamentals_note"] + "\n")
    if pr.get("nse"):
        w("Probe of NSE's results listing (corporates-financial-results), earliest period end with an XBRL file:\n")
        for code, rec in pr["nse"].items():
            a, qq = rec.get("Annual", {}), rec.get("Quarterly", {})
            w(f"- {code}: annual {a.get('earliest_with_xbrl')} ({a.get('with_xbrl')} filings, earliest listed {a.get('earliest')}); "
              f"quarterly {qq.get('earliest_with_xbrl')} ({qq.get('with_xbrl')} filings)")
    if pr.get("yahoo"):
        w("\nYahoo (yfinance) annual statements: " + "; ".join(f"{k}: {', '.join(v.get('income_stmt', [])) if isinstance(v.get('income_stmt'), list) else v.get('income_stmt')}"
                                                             for k, v in pr["yahoo"].items()) + "\n")
    fs = R["fundamentals_sidebar"]
    if "error" not in fs:
        w(f"\nExploratory fundamentals test from {fs['start']} ({fs['n']} eligible stocks with FY23 and FY24 filings filed by then; "
          f"outcome by {fs['end']}, {fs['years']} years). Base rate: 2x {pctf(fs['base_rate_2x'])}, 3x {pctf(fs['base_rate_3x'])}. "
          "One start date, short window: hypotheses only, no robustness split.\n")
        w("| Trait / combination | Flagged | 2x hit / lift | 3x hit / lift |\n|---|---:|---|---|")
        for k, r in fs["rows"].items():
            w(f"| {r['label']} | {r['n_flagged']} | {pctf(r['hit_rate_2x'])} / {num(r['lift_2x'])} | {pctf(r['hit_rate_3x'])} / {num(r['lift_3x'])} |")
    w("\n## Caveats\n")
    for c in R["caveats"]:
        w(f"- {c}")
    return "\n".join(L) + "\n"


# ---- main ----------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()
    if args.probe:
        probe()
        return
    t0 = time.time()
    uni = universe()
    syms = sorted(uni)
    if args.quick:
        rng = np.random.default_rng(1)
        syms = sorted(rng.choice(syms, 300, replace=False).tolist())
    px = download_long(syms)
    log(f"[study] prices ready in {time.time() - t0:.0f}s")
    idx, psyms, craw, adj, vol, nifty = build_panel(px, syms)
    log(f"[study] panel {craw.shape}, {idx[0]:%Y-%m-%d} to {idx[-1]:%Y-%m-%d}")
    qends = pd.date_range("2014-03-31", "2021-12-31", freq="QE")
    if args.quick:
        qends = pd.date_range("2014-12-31", "2021-12-31", freq="YE")
    df = compute(idx, psyms, craw, adj, vol, nifty, uni, qends)
    df = add_traits(df)
    df["band"] = np.select([df.large, df.mid, df.micro], ["large", "mid", "micro"], "small")
    log(f"[study] {len(df)} observations, {df.mb5.sum()} reached 5x, {time.time() - t0:.0f}s")
    n_dates = {"discover": df[df.half == "discover"].date.nunique(), "test": df[df.half == "test"].date.nunique(),
               "all": df.date.nunique()}
    base_rates = []
    for dte, d in df.groupby("date"):
        base_rates.append({"date": dte, "eligible": len(d), "mb5": int(d.mb5.sum()), "mb10": int(d.mb10.sum()),
                           "rate5": rnd(d.mb5.mean(), 4), "rate10": rnd(d.mb10.mean(), 4)})
    traits = {}
    for k, lab in list(TRAIT_LABELS.items())[:31]:
        traits[k] = {"label": lab, **evaluate(df, df[k].astype(bool), n_dates)}
    combos = {}
    for k, (lab, fn) in COMBOS.items():
        combos[k] = {"label": lab, **evaluate(df, fn(df).astype(bool), n_dates)}
        log(f"[combo] {k}: disc lift {combos[k]['discover']['lift']} test lift {combos[k]['test']['lift']} passed {combos[k]['passed']}")
    # Today's universe needs a market cap of about Rs 200 crore, so a stock that was small at the start date and then
    # fell is missing while one that rose is present. Re-run the combinations on stocks already worth >= Rs 1,000 crore
    # (estimated) at the start date: only a fall of more than ~80% would have pushed those out of today's universe.
    big = df[df.mc_est >= BIG_MC]
    nb = {"discover": big[big.half == "discover"].date.nunique(), "test": big[big.half == "test"].date.nunique(),
          "all": big.date.nunique()}
    combos_big = {k: {"label": lab, **evaluate(big, fn(df).astype(bool), nb)} for k, (lab, fn) in COMBOS.items()}
    traits_big = {k: {"label": lab, **evaluate(big, df[k].astype(bool), nb)} for k, lab in list(TRAIT_LABELS.items())[:31]}
    tree = tree_finds(df)
    fside = fundamentals_sidebar(idx, psyms, craw, adj, uni)
    probe_res = json.loads(PROBE.read_text()) if PROBE.exists() else {}
    R = {
        "meta": {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "quick": args.quick,
                 "universe": len(uni) if not args.quick else len(syms), "with_prices": len(psyms),
                 "price_from": idx[0].strftime("%Y-%m-%d"), "price_to": idx[-1].strftime("%Y-%m-%d"),
                 "start_dates": sorted(df.date.unique().tolist()),
                 "rules": {"liquidity_min_rs": LIQ_MIN, "min_history_sessions": MIN_HIST, "horizon_years": HORIZON_Y,
                           "multibagger": MB, "smoothing_days": SMOOTH, "base_range": BASE_RANGE, "discover": DISCOVER,
                           "test": TEST, "pass_lift": PASS_LIFT, "pass_min_flags": PASS_MIN_FLAGS, "pass_min_hits": PASS_MIN_HITS}},
        "summary": {"observations": len(df), "unique_stocks": int(df.sym.nunique()),
                    "base_rate_5x": rnd(df.mb5.mean(), 4), "base_rate_10x": rnd(df.mb10.mean(), 4),
                    "base_rate_5x_discover": rnd(df[df.half == "discover"].mb5.mean(), 4),
                    "base_rate_5x_test": rnd(df[df.half == "test"].mb5.mean(), 4),
                    "unique_5x_stocks": int(df[df.mb5].sym.nunique()), "unique_10x_stocks": int(df[df.mb10].sym.nunique()),
                    "passed_combos": [k for k, r in combos.items() if r["passed"]],
                    "passed_traits": [k for k, r in traits.items() if r["passed"]],
                    "tree_leaves_held": [lf["rule"] for lf in tree.get("leaves", []) if lf["held"]]},
        "base_rates": base_rates, "combos": combos, "traits": traits, "tree": tree,
        "selection_check": {"rule": f"start-date estimated market cap >= Rs {BIG_MC:,.0f} crore", "observations": len(big),
                            "base_rate_5x": rnd(big.mb5.mean(), 4), "base_rate_5x_discover": rnd(big[big.half == "discover"].mb5.mean(), 4),
                            "base_rate_5x_test": rnd(big[big.half == "test"].mb5.mean(), 4),
                            "passed_combos": [k for k, r in combos_big.items() if r["passed"]],
                            "passed_traits": [k for k, r in traits_big.items() if r["passed"]],
                            "combos": combos_big, "traits": traits_big},
        "holding_pain": holding_pain(df), "sectors": sectors(df), "fundamentals_sidebar": fside, "probe": probe_res,
        "fundamentals_note": (
            "No point-in-time fundamentals were used for the 2014-2021 start dates. The repo's filings (data/financials, "
            "from NSE XBRL) keep only the last 16 quarters (from late 2022), and Yahoo's annual statements cover 5 fiscal "
            "years (FY22-FY26). NSE's results listing does hold machine-readable (XBRL) annual results back to FY2017-FY2019 "
            "for the sampled companies (older years are listed as PDFs only), so fundamentals could be added for start dates "
            "from about mid-2019 with a backfill of roughly 10 filings per stock (~20,000 files); that was not done in this "
            "run, and the discovery half (2014-2017) could not be covered at all. The profit-growth/valuation and ROCE/debt "
            "combinations were therefore run only as a one-date exploratory test from mid-2024, below. BSE's API was not used."),
        "caveats": [
            "Survivor and selection bias: only stocks in today's universe are included, and that universe needs a market cap "
            "of about Rs 200 crore and Rs 50 lakh daily turnover today. Delisted collapses are missing, and a stock that was "
            "tiny at the start date is only present if it grew. Hit rates are inflated, most of all for micro caps, low share "
            "prices and beaten-down stocks; the Rs 1,000 crore subset is the more honest read for those traits.",
            "Market-cap bands use today's market cap scaled by price, so companies that issued many shares look larger in "
            "the past than they were.",
            "Yahoo data quality: occasional bad ticks and mis-applied corporate actions. Outcomes use a 5-day median close to "
            "blunt single-day errors; wrong split or bonus adjustments can still create or hide a multibagger.",
            "Returns use Yahoo's adjusted close, which folds dividends in (back-adjusted), so they are close to total "
            "returns, not price-only.",
            "Overlapping windows: quarterly start dates mean one stock's run is counted at several start dates, and "
            "discovery windows (2014-2017 starts) overlap test windows in calendar time (2018-2022). The halves are not "
            "independent markets; the stock-resampled interval partly accounts for the repetition.",
            "Turnover filter on Rs 10 lakh nominal: the same rupee threshold is looser in 2021 than in 2014.",
            "Many traits and combinations were tested: a few will clear lift 1.3 in both halves by chance.",
            "Fundamentals: see above; the 10-year study is price, size, liquidity and volatility only.",
        ],
    }
    out_json = ROOT / ("data/study_10y/quick.json" if args.quick else "docs/data/study_10y.json")
    out_md = ROOT / ("data/study_10y/quick.md" if args.quick else "docs/research/study_10y.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(R, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    out_md.write_text(report(R))
    log(f"[study] wrote {out_json.relative_to(ROOT)} and {out_md.relative_to(ROOT)} in {time.time() - t0:.0f}s")
    log(json.dumps(R["summary"], indent=1))


if __name__ == "__main__":
    main()
