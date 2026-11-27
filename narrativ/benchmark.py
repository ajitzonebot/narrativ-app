"""Benchmark (owner, 27 Nov 2026): which stocks made big moves over 3 months to 5 years, and would the model have caught
them before the move? Research only: nothing in the pipeline or the app reads it.

Step 1 (this file, `winners`): the winner list. Rules fixed before any result was seen (owner chose the ladder, 27 Nov 2026):

  horizon  window (trading days)  winner if the price reached
  3m        63                    +50%   (1.5x)
  6m       126                    +75%   (1.75x)
  1y       252                    2x
  2y       504                    3x
  3y       756                    4x
  4y      1008                    5x
  5y      1260                    5x

Same conventions as scripts/study_10y.py (one source of truth for long prices: data/study_cache/prices_10y.pkl, Yahoo
from 2002):
  - start dates: every month end from 2014-01 whose full window has ended (the window must fit before the last price)
  - start price: the adjusted close (splits, bonuses, dividends) on the start date
  - "reached": the 5-day rolling median of the adjusted close hit the multiple at any point inside the window, so one bad
    tick cannot make a winner
  - eligible on the start date: a price in the last 5 sessions, at least 126 sessions of history, median daily turnover
    (close x volume) over the prior 63 sessions of at least Rs 10 lakh
  - universe: today's listed stocks (docs/data/picks.json): stocks delisted since are missing (survivor bias)

A stock that qualifies at several consecutive month ends is one rally: `episodes` keeps the first month of each run (the
rally start), which is the date the model had to see it on. Days to the target = trading days from the start date until the
median first reached the multiple.

Output: data/benchmark/winners.json.gz (every rally episode) and docs/data/benchmark.json (summary).
python -m narrativ.benchmark winners
"""
import gzip
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from narrativ import config

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "data/study_cache/prices_10y.pkl"
OUT_DIR = ROOT / "data/benchmark"
SUMMARY = ROOT / "docs/data/benchmark.json"

LADDER = {"3m": (63, 1.5), "6m": (126, 1.75), "1y": (252, 2.0), "2y": (504, 3.0), "3y": (756, 4.0), "4y": (1008, 5.0),
          "5y": (1260, 5.0)}
FIRST_START = "2014-01-01"
LIQ_MIN = 1e6
MIN_HIST = 126
SMOOTH = 5
# data errors (27 Nov 2026: IMAGICAA showed +4,351% in one day on Yahoo): a window with a one-day adjusted move above +100% or
# below -60% (far outside the exchange's 20% band) is dropped and counted, not treated as a rally
GLITCH_UP, GLITCH_DOWN = 1.0, -0.6


def log(*a):
    print(*a, flush=True)


def universe() -> dict:
    d = json.loads((ROOT / "docs/data/picks.json").read_text())
    return {r["s"]: {"n": r.get("n"), "i": r.get("i"), "sec": r.get("sec") or "Unknown"} for r in d["picks"]}


def load_prices(uni: dict) -> dict:
    """Long Yahoo history; downloads what the shared study cache lacks (scripts/study_10y.download_long)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import study_10y  # noqa: E402  (research script, same cache file)
    return study_10y.download_long(sorted(uni))


def month_ends(idx: pd.DatetimeIndex, first: str) -> list[int]:
    """Row index of the last trading day of each month from `first`."""
    s = pd.Series(np.arange(len(idx)), index=idx)
    s = s[s.index >= pd.Timestamp(first)]
    return list(s.groupby([s.index.year, s.index.month]).max().values)


def winners() -> dict:
    uni = universe()
    px = load_prices(uni)
    syms = [s for s in uni if px.get(s) is not None]
    idx = px["^NSEI"].index
    for s in syms:
        idx = idx.union(px[s].index)
    idx = idx[idx >= pd.Timestamp("2002-01-01")]
    craw = pd.DataFrame({s: px[s]["Close"] for s in syms}).reindex(idx).astype("float64")
    adj = pd.DataFrame({s: px[s]["Adj Close"] for s in syms}).reindex(idx).astype("float64")
    vol = pd.DataFrame({s: px[s]["Volume"] for s in syms}).reindex(idx).astype("float64")
    craw[craw <= 0] = np.nan
    adj[adj <= 0] = np.nan
    exists = ~np.isnan(craw.values)
    A = adj.ffill(limit=10).values
    M = adj.ffill(limit=10).rolling(SMOOTH, min_periods=3).median().values
    TO = np.where(exists, craw.values * np.nan_to_num(vol.values), 0.0)
    cnt = np.cumsum(exists, axis=0)
    with np.errstate(all="ignore"):
        R = np.vstack([np.zeros((1, A.shape[1])), A[1:] / A[:-1] - 1])
    BAD = np.cumsum(np.nan_to_num((R > GLITCH_UP) | (R < GLITCH_DOWN)).astype(np.int32), axis=0)
    dropped = {}
    last = len(idx) - 1
    starts = month_ends(idx, FIRST_START)
    obs, eligible = [], {}
    for i in starts:
        if i < 63:
            continue
        has = exists[max(0, i - 4):i + 1].any(axis=0)
        med63 = np.median(TO[i - 62:i + 1], axis=0)
        ok = has & (cnt[i] >= MIN_HIST) & (med63 >= LIQ_MIN) & ~np.isnan(A[i])
        d0 = str(idx[i].date())
        for h, (n, mult) in LADDER.items():
            if i + n > last:
                continue
            eligible.setdefault(h, {})[d0] = int(ok.sum())
            win = M[i + 1:i + n + 1]
            with np.errstate(all="ignore"):
                hit = win >= A[i] * mult
            bad = BAD[i + n] - BAD[max(0, i - 5)] > 0
            dropped[h] = dropped.get(h, 0) + int((ok & hit.any(axis=0) & bad).sum())
            for j in np.where(ok & hit.any(axis=0) & ~bad)[0]:
                k = int(np.argmax(hit[:, j]))
                peak = float(np.nanmax(win[:, j]) / A[i, j])
                obs.append({"s": syms[j], "h": h, "start": d0, "days": k + 1, "hit": str(idx[i + 1 + k].date()),
                            "peak_x": round(peak, 2), "start_px": round(float(craw.values[i, j]), 2)})
    # episodes: first month of each run of consecutive qualifying month ends (per stock and horizon)
    mi = {str(idx[i].date()): n for n, i in enumerate(starts)}
    eps = []
    for (s, h), g in pd.DataFrame(obs).groupby(["s", "h"]) if obs else []:
        prev = None
        for r in g.sort_values("start").to_dict("records"):
            m = mi[r["start"]]
            if prev is None or m != prev + 1:
                eps.append({**r, "months": 1})
            else:
                eps[-1]["months"] += 1
            prev = m
    summary = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"), "universe": len(uni),
               "with_prices": len(syms), "price_to": str(idx[-1].date()), "ladder": {h: {"days": n, "multiple": m}
                                                                                     for h, (n, m) in LADDER.items()},
               "horizons": {}}
    for h in LADDER:
        o = [x for x in obs if x["h"] == h]
        e = [x for x in eps if x["h"] == h]
        el = eligible.get(h, {})
        summary["horizons"][h] = {
            "start_dates": len(el), "first_start": min(el) if el else None, "last_start": max(el) if el else None,
            "eligible_obs": sum(el.values()), "winner_obs": len(o), "dropped_data_errors": dropped.get(h, 0),
            "hit_rate": round(len(o) / sum(el.values()), 4) if el and sum(el.values()) else None,
            "episodes": len(e), "stocks": len({x["s"] for x in e}),
            "median_days_to_target": int(np.median([x["days"] for x in e])) if e else None,
            "by_year": {str(y): sum(1 for x in e if x["start"][:4] == str(y)) for y in range(2014, 2027)},
        }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # episodes only, gzipped (every month-end observation was 17 MB; counts stay in the summary)
    with gzip.open(OUT_DIR / "winners.json.gz", "wt") as f:
        json.dump({"summary": summary, "episodes": eps}, f, separators=(",", ":"))
    SUMMARY.write_text(json.dumps({"winners": summary}, indent=1))
    return summary



# ---- step 1b: tradeable winners (owner, 27 Nov 2026: "eliminate extremely low volume, unbuyable, operator driven") ----
# Rules fixed before results were seen. A rally is dropped when any applies; each count is reported.
TURN_MIN = 1e7        # low volume: median daily turnover over the 63 sessions before the start < Rs 1 crore
TRADED_MIN = 0.90     #   or traded on fewer than 90% of those sessions
LOCK_MAX = 0.25       # unbuyable: > 25% of sessions from the start to the 2x day locked at the upper limit (high = low, up)
MCAP_MIN = 100.0      # operator-like: estimated market cap at the start < Rs 100 crore (today's cap x price ratio)
ROUND_TRIP = 0.70     #   or gave back >= 70% from the peak within 12 months after the peak
OHLC = ROOT / "data/study_cache/ohlc_winners.pkl"


def _ohlc(syms: list[str]) -> dict:
    import yfinance as yf
    have = pickle.loads(OHLC.read_bytes()) if OHLC.exists() else {}
    need = [s for s in syms if s not in have]
    for k in range(0, len(need), 60):
        b = need[k:k + 60]
        d = yf.download(b, start="2013-06-01", interval="1d", group_by="ticker", auto_adjust=False, actions=False,
                        progress=False, threads=True)
        for s in b:
            try:
                x = (d[s] if isinstance(d.columns, pd.MultiIndex) else d).dropna(subset=["Close"])
                have[s] = x[["Open", "High", "Low", "Close", "Volume"]].astype("float64") if len(x) else None
            except KeyError:
                have[s] = None
        log(f"[ohlc] {min(k + 60, len(need))}/{len(need)}")
    OHLC.parent.mkdir(parents=True, exist_ok=True)
    OHLC.write_bytes(pickle.dumps(have))
    return have


def screen(h: str = "1y") -> dict:
    with gzip.open(OUT_DIR / "winners.json.gz", "rt") as f:
        W = json.load(f)
    eps = [x for x in W["episodes"] if x["h"] == h]
    uni = {r["s"]: r for r in json.loads((ROOT / "docs/data/picks.json").read_text())["picks"]}
    px = _ohlc(sorted({x["s"] for x in eps}))
    n_days = LADDER[h][0]
    out, why = [], {"low volume": 0, "unbuyable (upper-circuit locked)": 0, "tiny company (< Rs 100 cr)": 0,
                    "round trip (gave back >= 70%)": 0, "no OHLC data": 0}
    for x in eps:
        d = px.get(x["s"])
        if d is None or not len(d):
            why["no OHLC data"] += 1
            continue
        i = int(d.index.searchsorted(pd.Timestamp(x["start"]), side="right")) - 1
        j = int(d.index.searchsorted(pd.Timestamp(x["hit"]), side="right")) - 1
        if i < 63 or j <= i:
            why["no OHLC data"] += 1
            continue
        pre = d.iloc[i - 62:i + 1]
        turn = float((pre["Close"] * pre["Volume"]).median())
        traded = float((pre["Volume"] > 0).mean())
        run = d.iloc[i + 1:j + 1]
        prev = d["Close"].shift(1).iloc[i + 1:j + 1]
        locked = float(((run["High"] == run["Low"]) & (run["Close"] > prev)).mean())
        last_c = d["Close"].iloc[-1]
        mc_now = (uni.get(x["s"]) or {}).get("mc")
        mc0 = mc_now * float(d["Close"].iloc[i]) / float(last_c) if mc_now and last_c else None
        win = d["Close"].iloc[i + 1:i + n_days + 1]
        pk = int(np.argmax(win.values)) + i + 1
        after = d["Close"].iloc[pk:pk + 253]
        giveback = 1 - float(after.min()) / float(d["Close"].iloc[pk]) if len(after) > 1 else 0.0
        reasons = []
        if turn < TURN_MIN or traded < TRADED_MIN:
            reasons.append("low volume")
        if locked > LOCK_MAX:
            reasons.append("unbuyable (upper-circuit locked)")
        if mc0 is not None and mc0 < MCAP_MIN:
            reasons.append("tiny company (< Rs 100 cr)")
        if giveback >= ROUND_TRIP:
            reasons.append("round trip (gave back >= 70%)")
        for r in reasons:
            why[r] += 1
        out.append({**x, "turn_cr": round(turn / 1e7, 2), "traded": round(traded, 2), "locked": round(locked, 2),
                    "mc0_cr": round(mc0) if mc0 else None, "giveback": round(giveback, 2), "drop": reasons})
    keep = [x for x in out if not x["drop"]]
    res = {"horizon": h, "episodes": len(eps), "kept": len(keep), "kept_stocks": len({x["s"] for x in keep}),
           "dropped_by_rule": why, "dropped_any": len(out) - len(keep),
           "kept_by_year": {str(y): sum(1 for x in keep if x["start"][:4] == str(y)) for y in range(2014, 2027)},
           "rules": {"turnover_min_cr": TURN_MIN / 1e7, "traded_min": TRADED_MIN, "locked_max": LOCK_MAX,
                     "mcap_min_cr": MCAP_MIN, "round_trip": ROUND_TRIP}}
    with gzip.open(OUT_DIR / f"tradeable_{h}.json.gz", "wt") as f:
        json.dump({"summary": res, "episodes": out}, f, separators=(",", ":"))
    return res



# ---- step 2: would the model have caught them? (owner, 27 Nov 2026) ------------------------------------------------------
# For each month end T the code rules are rebuilt exactly as narrativ/replay.py does (filings filed on or before T, prices up
# to T, the seven levels, the Buy gates code decides, the readiness ranking and the Top 10 caps). Claude's review, research,
# analyst views and announcements cannot be replayed, so "caught" means the code rules made it a Buy candidate (sent to
# Claude for a full review) or put it in the Top 10. Prices here are Yahoo daily OHLCV (close not adjusted for dividends,
# as the exchange closes the live run uses); the live run uses exchange closes.
LOOKBACK = 3  # months before the rally start that also count as "seen early"


def _replay_env() -> list[str]:
    from narrativ import replay as RP
    uni = json.loads((ROOT / "docs/data/picks.json").read_text())["picks"]
    syms = [r["s"] for r in uni]
    px = _ohlc(syms + [config.BENCHMARK])
    cls = json.loads((ROOT / "data/classification.json").read_text())
    ue = json.loads((ROOT / "data/universe_exchange.json").read_text()).get("stocks", {})
    RP.META.update({r["s"]: {"i": r.get("i"), "sec": r.get("sec"), "b": (cls.get((ue.get(r["s"]) or [None])[0]) or {}).get("b")}
                    for r in uni})
    for s in syms:
        f = ROOT / f"data/financials/{s}.json"
        if px.get(s) is not None and len(px[s]) and f.exists():
            RP.P[s] = px[s]
            RP.FIN[s] = json.loads(f.read_text())
    RP.P[config.BENCHMARK] = px[config.BENCHMARK]
    RP.SHP.update({s: v.get("hist") or [] for s, v in json.loads((ROOT / "data/shareholding.json").read_text()).items()})
    return syms


def _state(T: str) -> dict:
    """Per stock on T: scored, eligible, failed gates, candidate, Top 10 rank."""
    from narrativ import replay as RP
    sc = RP._score(T)
    rows, gates = sc["rows"], RP.VARIANTS["current rules"][0]
    top = {s: n + 1 for n, s in enumerate(RP._pick(rows, gates, RP.BASE_W))}
    out = {}
    for s, r in rows.items():
        fail = [g for g in gates if not r[g]]
        out[s] = {"fail": fail, "cand": not fail, "top10": top.get(s), "out": r.get("_out"), "t": r.get("_t")}
    return out


def catch(h: str = "1y", first: str = "2025-01-01") -> dict:
    from multiprocessing import Pool
    with gzip.open(OUT_DIR / f"tradeable_{h}.json.gz", "rt") as f:
        T_eps = [x for x in json.load(f)["episodes"] if not x["drop"] and x["start"] >= first]
    _replay_env()
    starts = sorted({x["start"] for x in T_eps})
    idx = _ohlc([])["^NSEI"].index
    me = [str(idx[i].date()) for i in month_ends(idx, str((pd.Timestamp(starts[0]) - pd.DateOffset(months=LOOKBACK + 1)).date()))]
    me = [d for d in me if d[:7] <= starts[-1][:7]]
    mk = {d[:7]: n for n, d in enumerate(me)}  # month -> index (a rally start is that month's last trading day)
    with Pool() as pool:
        states = dict(zip(me, pool.map(_state, me)))
    with gzip.open(OUT_DIR / f"states_{h}.json.gz", "wt") as f:  # step 3 reads every month's gate results
        json.dump(states, f, separators=(",", ":"))
    res, rows = {"horizon": h, "months": [me[0], me[-1]], "rallies": len(T_eps)}, []
    for x in T_eps:
        k = mk.get(x["start"][:7])
        if k is None:
            continue
        st = states[me[k]].get(x["s"])
        early = [me[j] for j in range(max(0, k - LOOKBACK), k + 1) if (states[me[j]].get(x["s"]) or {}).get("cand")]
        top = [me[j] for j in range(max(0, k - LOOKBACK), k + 1) if (states[me[j]].get(x["s"]) or {}).get("top10")]
        if st is None:
            why = "not scored (no NSE filing data or under 210 days of prices)"
        elif st["cand"]:
            why = None
        elif "eligible" in st["fail"]:
            why = "level: " + (st["out"] or "stability or quality not good enough")
        else:
            why = "gate: " + ", ".join(st["fail"])
        rows.append({**{k_: x[k_] for k_ in ("s", "start", "hit", "peak_x", "turn_cr", "mc0_cr")},
                     "scored": st is not None, "cand_at_start": bool(st and st["cand"]), "top10_at_start": st["top10"] if st else None,
                     "cand_window": early, "top10_window": top, "miss": why if not early else None,
                     "first_fail": (st["fail"][0] if st and st["fail"] else None)})
    n = len(rows)
    caught = [r for r in rows if r["cand_window"]]
    res.update({
        "scored_at_start": sum(r["scored"] for r in rows),
        "candidate_at_start": sum(r["cand_at_start"] for r in rows),
        "candidate_in_window": len(caught), "top10_in_window": sum(1 for r in rows if r["top10_window"]),
        "catch_rate": round(len(caught) / n, 3) if n else None,
    })
    # precision: of every Buy candidate at each month end, how many doubled within the horizon (any winner)
    cand_obs = [(T[:7], s) for T, st in states.items() if T >= first for s, v in st.items() if v["cand"]]
    top_obs = [(T[:7], s) for T, st in states.items() if T >= first for s, v in st.items() if v["top10"]]
    scored_obs = [(T[:7], s) for T, st in states.items() if T >= first for s in st]
    obs_win = _win_obs(h, first)
    rate = lambda obs: round(sum(1 for o in obs if o in obs_win) / len(obs), 3) if obs else None  # noqa: E731
    res["precision"] = {"candidates": len(cand_obs), "candidate_doubled": rate(cand_obs), "top10": len(top_obs),
                        "top10_doubled": rate(top_obs), "all_scored": len(scored_obs), "all_scored_doubled": rate(scored_obs)}
    from collections import Counter
    res["miss_reasons"] = Counter(r["miss"] for r in rows if r["miss"]).most_common()
    res["first_failed_gate"] = Counter(r["first_fail"] for r in rows if r["miss"] and r["first_fail"]).most_common()
    with gzip.open(OUT_DIR / f"catch_{h}.json.gz", "wt") as f:
        json.dump({"summary": res, "rallies": rows}, f, separators=(",", ":"), default=str)
    return res


def _win_obs(h: str, first: str) -> set:
    """Every (month, stock) whose price doubled within the horizon: all observations, not just rally starts."""
    with gzip.open(OUT_DIR / "winners.json.gz", "rt") as f:
        eps = [x for x in json.load(f)["episodes"] if x["h"] == h]
    months = pd.period_range("2014-01", "2026-12", freq="M").astype(str).tolist()
    pos = {m: n for n, m in enumerate(months)}
    out = set()
    for x in eps:
        k = pos[x["start"][:7]]
        out.update((months[j], x["s"]) for j in range(k, k + x["months"]) if months[j] >= first[:7])
    return out



# ---- step 3: were the blocking checks right to block? (owner, 27 Nov 2026) -----------------------------------------------
# For every stock scored at every month end from `first`, among tradeable stocks (63-day median turnover >= Rs 1 crore on T):
# its 1-year outcome (doubled within 252 trading days; return over 252 days and vs the Nifty). Groups: Buy candidates, stocks
# blocked by each check (and blocked by that check alone, which removing the check would turn into candidates), and the two
# ways the quality / stability level blocks (level failed outright vs tier not good enough).
def _fwd(px: dict, T: str, s: str, n: int = 252):
    d = px.get(s)
    if d is None or not len(d):
        return None
    i = int(d.index.searchsorted(pd.Timestamp(T), side="right")) - 1
    if i < 63 or i + n >= len(d):
        return None
    c = d["Close"].values
    turn = float(np.median(c[i - 62:i + 1] * d["Volume"].values[i - 62:i + 1]))
    return {"ret": c[i + n] / c[i] - 1, "turn": turn}


def gates(h: str = "1y", first: str = "2025-01-01") -> dict:
    with gzip.open(OUT_DIR / f"states_{h}.json.gz", "rt") as f:
        states = json.load(f)
    px = _ohlc([])
    win = _win_obs(h, first)
    n = LADDER[h][0]
    obs = []
    for T, st in states.items():
        if T < first:
            continue
        b = _fwd(px, T, config.BENCHMARK, n)
        for s, v in st.items():
            f = _fwd(px, T, s, n)
            if not f or f["turn"] < TURN_MIN:
                continue
            obs.append({"T": T, "s": s, "fail": v["fail"], "cand": v["cand"], "top10": v["top10"], "out": v["out"],
                        "t": v["t"], "ret": f["ret"], "xs": f["ret"] - (b["ret"] if b else 0), "won": (T[:7], s) in win})

    def g(rows):
        if not rows:
            return {"n": 0}
        r = np.array([x["ret"] for x in rows])
        return {"n": len(rows), "doubled_pct": round(100 * sum(x["won"] for x in rows) / len(rows), 1),
                "median_ret_pct": round(100 * float(np.median(r)), 1), "mean_ret_pct": round(100 * float(r.mean()), 1),
                "beat_nifty_pct": round(100 * sum(x["xs"] > 0 for x in rows) / len(rows), 1)}
    from narrativ import replay as RP
    cur = RP.VARIANTS["current rules"][0]
    res = {"horizon": h, "months": sorted({x["T"] for x in obs}), "population": "scored, turnover >= Rs 1 cr/day on T",
           "all": g(obs), "candidates": g([x for x in obs if x["cand"]]), "top10": g([x for x in obs if x["top10"]]),
           "eligible: level failed outright": g([x for x in obs if "eligible" in x["fail"] and x["out"]]),
           "eligible: stability or quality tier not good enough": g([x for x in obs if "eligible" in x["fail"] and not x["out"]]),
           "blocked by": {k: g([x for x in obs if k in x["fail"]]) for k in cur},
           "blocked only by": {k: g([x for x in obs if x["fail"] == [k]]) for k in cur},
           "passed": {k: g([x for x in obs if k not in x["fail"]]) for k in cur}}
    # tiers of the "not good enough" group (1 best .. 5 worst; eligible needs stability and quality 1-3)
    ng = [x for x in obs if "eligible" in x["fail"] and not x["out"] and x["t"]]
    res["not good enough by tiers"] = {f"stability {a} / quality {q}": g([x for x in ng if x["t"]["surv"] == a and x["t"]["qual"] == q])
                                       for a in range(0, 6) for q in range(0, 6)
                                       if any(x["t"]["surv"] == a and x["t"]["qual"] == q for x in ng)}
    with gzip.open(OUT_DIR / f"gates_{h}.json.gz", "wt") as f:
        json.dump(res, f, separators=(",", ":"))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "winners"
    if cmd == "winners":
        print(json.dumps(winners()["horizons"], indent=1))
    elif cmd == "gates":
        print(json.dumps(gates(sys.argv[2] if len(sys.argv) > 2 else "1y"), indent=1))
    elif cmd == "catch":
        print(json.dumps(catch(sys.argv[2] if len(sys.argv) > 2 else "1y"), indent=1, default=str))
    elif cmd == "screen":
        print(json.dumps(screen(sys.argv[2] if len(sys.argv) > 2 else "1y"), indent=1))
