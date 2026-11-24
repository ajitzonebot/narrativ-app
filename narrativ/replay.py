"""History replay of the code rules (owner, 20 Nov 2026: "Top 10 should have a higher probability of winning").

At each month end T it rebuilds what the pipeline would have seen on T, with nothing from after T:
  - filings: only quarters whose XBRL was filed on or before T (data/financials, `filed` per quarter)
  - prices: closes up to T (the exchange-close store, data/source_cache/prices.pkl)
and runs the same functions as run.py: metrics, the seven levels, entry setup, price signals (T11), the Buy gates that code
decides (R1 positive operating cash flow, R2 other income, R4 dated trigger from price/results signals or RS top third, R6 re-rating leg), the
readiness ranking and the Top 10 caps (portfolio.top10).

What it cannot replay: Claude's review and research (guidance, order books, drivers, verdicts), shareholding, analyst
views, announcements and sector rotation. So a "candidate" here is a stock the code rules would send to Claude for a full
review (good stability and quality, margin of safety, price not in a downtrend, gates passed), and the Top 10 is the
readiness order of those candidates. The universe is today's listed stocks (stocks delisted since are missing: survivor
bias, which flatters every variant equally).

Measures, per variant, for each Top 10 stock at each T: return over the next 3 / 6 / 12 months (63 / 126 / 252 trading
days) vs the Nifty over the same days. `win_pct` = share of Top 10 picks that beat the Nifty. Baselines: all candidates,
and every stock. Variants switch one gate or one ranking input off, to show which raise the win rate.
Output docs/data/replay.json (summary) and data/replay/top10.json (each month's Top 10).
python -m narrativ.replay [--quick]
"""
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from narrativ import config, technicals
from narrativ import funnel as FN
from narrativ import metrics as MX
from narrativ import portfolio as PF
from narrativ import upside as UP

OUT, DETAIL = Path("docs/data/replay.json"), Path("data/replay/top10.json")
H = {"3m": 63, "6m": 126, "12m": 252}
START = "2025-01-31"  # filings start Mar 2023; the quality level needs ~3 years of quarters, so earlier months have no candidates
DIAG = "--quick" in sys.argv
P: dict = {}
FIN: dict = {}
META: dict = {}
SHP: dict = {}


def _load(quick: bool) -> None:
    px = pd.read_pickle("data/source_cache/prices.pkl")
    picks = json.loads(Path("docs/data/picks.json").read_text())["picks"]
    syms = [r["s"] for r in picks]
    if quick:
        syms = syms[:300]
    META.update({r["s"]: {"i": r.get("i"), "sec": r.get("sec")} for r in picks})
    for s in syms:
        f = Path(f"data/financials/{s}.json")
        if s in px and f.exists():
            P[s] = px[s]
            FIN[s] = json.loads(f.read_text())
    P[config.BENCHMARK] = px[config.BENCHMARK]
    sh = Path("data/shareholding.json")
    if sh.exists():
        SHP.update({s: v.get("hist") or [] for s, v in json.loads(sh.read_text()).items()})


def _prom_at(s: str, T: str) -> list:
    """Promoter history known on T: a quarter's shareholding pattern is due 21 days after the quarter ends."""
    out = []
    for h in SHP.get(s) or []:
        d = pd.Timestamp(h["date"]) + pd.Timedelta(days=21)
        if str(d.date()) <= T:
            out.append(h)
    return out


def _fin_at(fin: dict, T: str) -> dict:
    q = {}
    for qe, bases in (fin.get("quarters") or {}).items():
        b = {k: v for k, v in bases.items() if (v.get("filed") or "9999") <= T}
        if b:
            q[qe] = b
    return {**fin, "quarters": q}


def _score(T: str) -> dict:
    """Everything the selection needs for one month end: per stock, gates, readiness inputs, forward returns."""
    Ts = pd.Timestamp(T)
    bench = P[config.BENCHMARK]["Close"]
    bT = bench[bench.index <= Ts]
    px = {s: d[d.index <= Ts] for s, d in P.items() if s != config.BENCHMARK}
    tech = {}
    for s, d in px.items():
        if len(d) >= 210 and (Ts - d.index[-1]).days <= 7:
            t = technicals.analyze(d, bT)
            if t:
                tech[s] = t
    syms = list(tech)
    rs_all = pd.Series({s: t["rs_raw"] for s, t in tech.items()}).rank(pct=True)
    ind_of = {s: (META.get(s) or {}).get("i") for s in syms}
    ind_rank = {}
    for ind, grp in pd.Series({s: tech[s]["rs_raw"] for s in syms}).groupby(lambda s: ind_of.get(s)):
        if isinstance(ind, str) and len(grp) >= 3:
            ind_rank.update(grp.rank(pct=True).to_dict())
    mx = {}
    for s in syms:
        try:
            mx[s] = MX.compute(_fin_at(FIN[s], T), tech[s]["price"], None, None, None)
        except Exception:  # noqa: BLE001
            continue
    syms = [s for s in syms if s in mx and mx[s].get("source") == "NSE filing"]
    istats = FN.industry_stats([(ind_of.get(s), mx[s]) for s in syms])
    bts, prows = {}, []
    for s in syms:
        bt = FN.business_type(mx[s], ind_of.get(s), mx[s].get("kind") or "general")
        bt, mk, v_ = FN.primary(mx[s], bt)
        bts[s] = (bt, mk, v_)
        prows.append((s, ind_of.get(s), bt, mk, v_))
    peers = FN.peer_medians(prows)
    rows = {}
    for s in syms:
        try:
            Mx, t, d = mx[s], tech[s], px[s]
            exempt = FN.lender_type(Mx.get("kind"), Mx.get("source"), (META.get(s) or {}).get("sec"), ind_of.get(s), None)  # R1 / R2, as run.py
            lender = Mx.get("kind") in FN.LENDERS or bool(exempt)
            L = {"surv": FN.survivability(Mx, lender, None, None), "qual": FN.quality(Mx, lender, istats.get(ind_of.get(s)))}
            bt, mk, cur = bts[s]
            hist = MX.history(_fin_at(FIN[s], T), d["Close"])
            L["val"] = FN.valuation(Mx, bt, mk, cur, hist, peers.get(s), lender)
            up = UP.checks(Mx.get("quarterly"), Mx.get("roce_fy"), MX.val(Mx, "debt_chg_yoy_pct"), MX.val(Mx, "net_debt_ebitda"),
                           cur, [h.get(FN.HIST_KEY[mk]) for h in hist], peers.get(s), _prom_at(s, T))
            L["mgmt"] = FN.management(Mx, [], {}, lender, None, None)
            L["mom"] = FN.momentum(t, d, float(rs_all.get(s, 0.5)), ind_rank.get(s), None, Mx, None, None)
            L["disc"] = FN.discovery(None, None, d, None, None)
            sig = FN.signal_triggers(d, bT, Mx, None, None, None, Ts.date(), MX.val(Mx, "mcap_cr"))
            L["out"] = FN.outlook(Mx, (istats.get(ind_of.get(s)) or {}).get("wind"), None, {}, None, Mx.get("flags"),
                                  L["surv"], L["qual"], L["mgmt"], None, signals=sig)
            trig = [x for x in (L["out"].get("triggers") or []) if x.get("id") != "T4"]
        except Exception:  # noqa: BLE001
            continue
        out_l = any(L[k].get("out") for k in FN.LEVELS)
        tt = {k: L[k]["t"] for k in FN.LEVELS}
        good = lambda k, hi: tt[k] != 0 and tt[k] <= hi  # noqa: E731
        su = FN.setup(d, t, None)
        stage = next((i.get("v") for i in L["mom"]["items"] if i["id"] == "P1"), None)
        cc, oi = FN.cash_conversion(Mx)[0], MX.val(Mx, "other_income_pct_pbt")  # R1 on the unrounded value
        hi, pxl = t.get("hi52"), t.get("price")
        rows[s] = {
            "eligible": not out_l and good("surv", 3) and good("qual", 3),
            "mos": tt["val"] in (1, 2, 3),  # no research: credibility unknown, so valuation tier 1-3 (decision rule 6)
            "trend": stage not in ("Downtrend", None),
            "R1": bool(exempt) or cc is None or cc > FN.R1_MIN, "R1_50": bool(exempt) or cc is None or cc >= 50, "R1_25": bool(exempt) or cc is None or cc >= 25, "R2": bool(exempt) or oi is None or oi <= 25, "R4": bool(trig) or float(rs_all.get(s, 0.5)) >= FN.R4_RS_MIN, "R4_trig": bool(trig), "R4u": bool(trig) or bool(up["U1"][0] or up["U2"][0] or up["U3"][0]),
            "R6": not (tt["val"] == 3 and tt["disc"] in (4, 5)),
            "rs": float(rs_all.get(s, 0.5)) * 100,
            "near": max(0.0, min(100.0, (1 - (1 - pxl / hi) / 0.30) * 100)) if hi and pxl else 50.0,
            # confirmed breakout (study_recent 24 Nov 2026): within 10% of the 52-week high + RS top third + results beat T11
            "cb": bool(hi and pxl and pxl >= 0.9 * hi) and float(rs_all.get(s, 0.5)) >= 2 / 3 and any(x.get("id") == "T11" for x in trig),
            "vs": L["val"].get("s"), "pr": FN.priority(L),
            "setup": 0 if su.get("type") in ("Breakout", "Pullback", "Base") else 2 if L["mom"].get("extended") else 1,
            "liq1": (t.get("traded_value_cr") or 0) >= 1, "liq5": (t.get("traded_value_cr") or 0) >= 5,
            "mc": MX.val(Mx, "mcap_cr"), "i": ind_of.get(s), "sec": (META.get(s) or {}).get("sec"),
            "_t": tt, "_out": next((f"{k}: {L[k].get('rm')}"[:70] for k in FN.LEVELS if L[k].get("out")), None),
            **{k: bool(st) for k, (st, _) in up.items()},
            "mb": PF.multibagger(MX.val(Mx, "mcap_cr"), tt["disc"], MX.val(Mx, "rev_yoy_pct"), False, MX.val(Mx, "roce_pct"),
                                 bool(trig), tt["val"]),
            # conviction inputs that code can replay (narrativ/conviction.py): C1 2+ dated triggers (code signals only here),
            # C3 entry setup live and not extended, C6 3 full years + cash conversion known; and inputs tested but left out
            "cv": {"C1 two or more dated triggers": len({x["id"] for x in trig}) >= 2,
                   "(tested, not used) deep value or undervalued": tt["val"] in (1, 2),
                   "C3 entry setup live": su.get("type") in ("Breakout", "Pullback", "Base") and not L["mom"].get("extended"),
                   "C6 3 full years and cash conversion": MX.val(Mx, "rev_cagr_3y_pct") is not None and MX.val(Mx, "pat_cagr_3y_pct") is not None
                   and (lender or cc is not None) and (Mx.get("quarters_available") or 0) >= 8,
                   "(tested, not used) price in stage 2": stage in ("Stage 2", "Stage 1→2"),
                   "(tested, not used) momentum surging or strong": tt["mom"] in (1, 2),
                   **{f"(test) {k} {UP.NAMES[k]}": bool(st) for k, (st, _) in up.items()},
                   **{f"(test) {k} {UP.NAMES[k]} (known)": st is not None for k, (st, _) in up.items()}},
        }
    # forward returns from the close on T
    fwd = {}
    b0 = float(bT.iloc[-1])
    bf = bench[bench.index > Ts]
    for s in rows:
        c = P[s]["Close"]
        c0, after = float(c[c.index <= Ts].iloc[-1]), c[c.index > Ts]
        fwd[s] = {}
        for k, n in H.items():
            if len(after) >= n and len(bf) >= n:
                r, rb = (float(after.iloc[n - 1]) / c0 - 1) * 100, (float(bf.iloc[n - 1]) / b0 - 1) * 100
                fwd[s][k] = (round(r, 2), round(r - rb, 2))
    if DIAG:
        from collections import Counter
        print(f"[replay] {T} tiers surv {Counter(r['_t']['surv'] for r in rows.values())} qual {Counter(r['_t']['qual'] for r in rows.values())} "
              f"out {Counter(r['_out'] for r in rows.values()).most_common(6)}")
    print(f"[replay] {T}: {len(rows)} scored, {sum(r['eligible'] for r in rows.values())} eligible")
    return {"T": T, "rows": rows, "fwd": fwd}


BASE_W = {"rs": 0.45, "near": 0.15, "vs": 0.40}
VARIANTS = {  # name -> (gates and checks that must pass, ranking weights)
    "current rules": (["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], BASE_W),
    "without R1 cash conversion": (["eligible", "mos", "trend", "R2", "R4", "R6"], BASE_W),
    "without R2 other income": (["eligible", "mos", "trend", "R1", "R4", "R6"], BASE_W),
    "without R4 dated trigger": (["eligible", "mos", "trend", "R1", "R2", "R6"], BASE_W),
    "without R6 re-rating leg": (["eligible", "mos", "trend", "R1", "R2", "R4"], BASE_W),
    "without margin of safety": (["eligible", "trend", "R1", "R2", "R4", "R6"], BASE_W),
    "without trend check": (["eligible", "mos", "R1", "R2", "R4", "R6"], BASE_W),
    "rank: momentum only": (["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], {"rs": 1.0}),
    "rank: valuation only": (["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], {"vs": 1.0}),
    "rank: near 52-week high only": (["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], {"near": 1.0}),
    "rank: overall priority": (["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], {"pr": 1.0}),
    "rank: no entry-setup tier": (["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], {**BASE_W, "_nosetup": 1}),
}
# upside checks U1-U5 (narrativ/upside.py), tested before they become rules: as a required gate, and as a ranking boost
CUR = ["eligible", "mos", "trend", "R1", "R2", "R4", "R6"]
for u in ("U1", "U2", "U3", "U4", "U5"):
    VARIANTS[f"plus {u} {UP.NAMES[u]} required"] = (CUR + [u], BASE_W)
    VARIANTS[f"rank: +10 for {u} {UP.NAMES[u]}"] = (CUR, {**BASE_W, "_boost": {u: 10}})
VARIANTS["rank: +10 U1, +10 U2, +10 U3, +5 U4, +10 U5"] = (CUR, {**BASE_W, "_boost": {"U1": 10, "U2": 10, "U3": 10, "U4": 5, "U5": 10}})
VARIANTS["U1 or U2 or U3 counts as R4 trigger"] = (["eligible", "mos", "trend", "R1", "R2", "R4u", "R6"], BASE_W)
# R1 softer levels (owner, 23 Nov 2026: R1 blocks the most candidates; replay showed the blocked ones beat the passed ones)
VARIANTS["R1 at 50% cash conversion (17-23 Nov 2026)"] = (["eligible", "mos", "trend", "R1_50", "R2", "R4", "R6"], BASE_W)
VARIANTS["R1 at 25% cash conversion"] = (["eligible", "mos", "trend", "R1_25", "R2", "R4", "R6"], BASE_W)
# owner 24 Nov 2026, from the winners study: confirmed-breakout ranking boost and a softer R4
VARIANTS["rank: +10 confirmed breakout"] = (CUR, {**BASE_W, "_boost": {"cb": 10}})
VARIANTS["rank: +20 confirmed breakout"] = (CUR, {**BASE_W, "_boost": {"cb": 20}})
VARIANTS["rank: confirmed breakouts first"] = (CUR, {**BASE_W, "_boost": {"cb": 1000}})
VARIANTS["rank: confirmed breakouts ahead of setup tiers"] = (CUR, {**BASE_W, "_cbfirst": 1})
VARIANTS["R4 dated trigger only (until 24 Nov 2026)"] = (["eligible", "mos", "trend", "R1", "R2", "R4_trig", "R6"], BASE_W)
VARIANTS["without R4, +20 confirmed breakout"] = (["eligible", "mos", "trend", "R1", "R2", "R6"], {**BASE_W, "_boost": {"cb": 20}})
# stricter entry: average daily traded value of at least Rs 1 crore / Rs 5 crore (can you buy and sell it)
for g, lab in (("liq1", "₹1 cr"), ("liq5", "₹5 cr")):
    VARIANTS[f"plus turnover ≥ {lab} a day"] = (["eligible", "mos", "trend", "R1", "R2", "R4", "R6", g], BASE_W)
# ranking weights tried for RULES.md Ranking (momentum percentile, nearness to the 52-week high, valuation score)
for rs_, nr_, vs_ in ((0.6, 0.2, 0.2), (0.5, 0.3, 0.2), (0.7, 0.3, 0.0), (0.45, 0.35, 0.2), (0.34, 0.33, 0.33), (0.55, 0.15, 0.3)):
    VARIANTS[f"weights {round(rs_ * 100)}/{round(nr_ * 100)}/{round(vs_ * 100)}"] = (
        ["eligible", "mos", "trend", "R1", "R2", "R4", "R6"], {"rs": rs_, "near": nr_, "vs": vs_})


def _pick(rows: dict, gates: list[str], w: dict) -> list[str]:
    cand = [s for s, r in rows.items() if all(r[g] for g in gates)]

    def key(s):
        r = rows[s]
        blend = sum(wt * (r[k] if r[k] is not None else 50) for k, wt in w.items() if not k.startswith("_")) + (5 if r["mb"] else 0)
        blend += sum(pts for u, pts in (w.get("_boost") or {}).items() if r.get(u))
        tier = 0 if w.get("_nosetup") else r["setup"]
        if w.get("_cbfirst") and r.get("cb"):
            tier = -1  # confirmed breakouts ahead of every setup tier
        return (tier, -blend)
    ranked = sorted(cand, key=key)
    out = [{"s": s, "dc": "Buy", "vf": "pass", "rk": i + 1, "i": rows[s]["i"], "sec": rows[s]["sec"], "mc": rows[s]["mc"]}
           for i, s in enumerate(ranked)]
    return PF.top10(out)


def _stats(picks: list[tuple], k: str) -> dict:
    """picks: [(T, symbol, fwd)] -> win % (beat Nifty), average return, average excess, monthly basket excess."""
    x = [(T, f[k]) for T, s, f in picks if k in f]
    if not x:
        return {"n": 0}
    exc = [e for _, (r, e) in x]
    by_T = {}
    for T, (r, e) in x:
        by_T.setdefault(T, []).append(e)
    basket = [sum(v) / len(v) for v in by_T.values()]
    return {"n": len(x), "months": len(by_T), "win_pct": round(100 * sum(e > 0 for e in exc) / len(exc)),
            "avg_return_pct": round(sum(r for _, (r, e) in x) / len(x), 2), "avg_vs_nifty": round(sum(exc) / len(exc), 2),
            "basket_beat_months_pct": round(100 * sum(b > 0 for b in basket) / len(basket))}


CV_CODE = ("C1 two or more dated triggers", "C3 entry setup live", "C6 3 full years and cash conversion")


def conviction_split(res: list[dict], top: dict) -> dict:
    """Conviction never changes the Top 10; it says how much evidence stands behind each pick. So each code-replayable
    conviction input is checked inside the current rules' Top 10 (and, for a bigger sample, all candidates): win rate of the
    picks that meet it vs those that do not. An input belongs in conviction only if it does not lower the win rate.
    `code_checks_met`: picks by how many of the three code checks (C1 C3 C6) they meet."""
    gates = VARIANTS["current rules"][0]
    pools = {"top10": [(r["T"], s, r["fwd"].get(s, {}), r["rows"][s]["cv"]) for r in res for s in top.get(r["T"], [])],
             "candidates": [(r["T"], s, r["fwd"].get(s, {}), rw["cv"]) for r in res for s, rw in r["rows"].items()
                            if all(rw[g] for g in gates)]}
    out = {}
    for pool, rows in pools.items():
        inputs = {}
        for name in rows[0][3] if rows else []:
            inputs[name] = {side: {k: _stats([(T, s, f) for T, s, f, cv in rows if bool(cv[name]) == want], k) for k in H}
                            for side, want in (("met", True), ("not met", False))}
        by_n = {}
        for n in range(len(CV_CODE) + 1):
            sel = [(T, s, f) for T, s, f, cv in rows if sum(bool(cv[c]) for c in CV_CODE) == n]
            if sel:
                by_n[str(n)] = {k: _stats(sel, k) for k in H}
        out[pool] = {"inputs": inputs, "code_checks_met": by_n}
    return out


def gate_split(res: list[dict]) -> dict:
    """Does each gate hold back winners? For every gate: stocks that pass all the other current gates, split into those the
    gate passes vs those it blocks (all candidates, not just the Top 10, for sample size). A gate earns its place when the
    blocked side beats the Nifty less often and by less (owner, 23 Nov 2026: more high-conviction Buys without losing accuracy)."""
    gates = VARIANTS["current rules"][0]
    out = {}
    for g in gates:
        if g == "eligible":
            continue
        others = [x for x in gates if x != g]
        rows = [(r["T"], s, r["fwd"].get(s, {}), bool(rw[g])) for r in res for s, rw in r["rows"].items() if all(rw[x] for x in others)]
        out[g] = {side: {k: _stats([(T, s, f) for T, s, f, ok in rows if ok == want], k) for k in H}
                  for side, want in (("passes", True), ("blocked", False))}
    return out


def run(quick: bool = False) -> dict:
    t0 = time.time()
    _load(quick)
    b = P[config.BENCHMARK]["Close"]
    ends = b[b.index >= pd.Timestamp(START)].groupby(b[b.index >= pd.Timestamp(START)].index.to_period("M")).apply(lambda x: x.index[-1])
    dates = [str(d.date()) for d in ends][:-1]  # the current month is not over
    if quick:
        dates = [dates[0], dates[len(dates) // 2], dates[-1]]
    with Pool() as pool:
        res = pool.map(_score, dates)
    out = {"dates": [dates[0], dates[-1]] if dates else [], "months": len(dates), "horizons": H, "variants": {}, "baselines": {},
           "note": ("Replay of the code rules only (Claude's research and review cannot be replayed). win_pct = share of Top 10 "
                    "picks that beat the Nifty over the horizon. Universe = today's listed stocks (survivor bias)."),
           "minutes": None}
    detail = {}
    for name, (gates, w) in VARIANTS.items():
        picks = []
        for r in res:
            top = _pick(r["rows"], gates, w)
            if name == "current rules":
                detail[r["T"]] = top
            picks += [(r["T"], s, r["fwd"].get(s, {})) for s in top]
        out["variants"][name] = {"avg_top10": round(len(picks) / max(1, len(res)), 1), **{k: _stats(picks, k) for k in H}}
    for name, f in (("all candidates (current gates)", lambda rw: all(rw[g] for g in VARIANTS["current rules"][0])),
                    ("every stock scored", lambda rw: True),
                    *((f"every stock with {u} {UP.NAMES[u]}", (lambda u: lambda rw: rw[u])(u)) for u in ("U1", "U2", "U3", "U4", "U5")),
                    *((f"every stock without {u} {UP.NAMES[u]}", (lambda u: lambda rw: not rw[u])(u)) for u in ("U1", "U2", "U3", "U4", "U5"))):
        picks = [(r["T"], s, r["fwd"].get(s, {})) for r in res for s, rw in r["rows"].items() if f(rw)]
        out["baselines"][name] = {k: _stats(picks, k) for k in H}
    out["conviction"] = conviction_split(res, detail)
    out["gates"] = gate_split(res)
    out["minutes"] = round((time.time() - t0) / 60, 1)
    OUT.write_text(json.dumps(out, indent=1))
    DETAIL.parent.mkdir(parents=True, exist_ok=True)
    DETAIL.write_text(json.dumps(detail, indent=0))
    for name, v in out["variants"].items():
        print(f"[replay] {name}: " + ", ".join(f"{k} win {v[k].get('win_pct')}% vs Nifty {v[k].get('avg_vs_nifty')} (n {v[k].get('n')})" for k in H))
    for name, v in out["baselines"].items():
        print(f"[replay] baseline {name}: " + ", ".join(f"{k} win {v[k].get('win_pct')}%" for k in H))
    for g, sides in out["gates"].items():
        print(f"[replay] gate {g}: " + " | ".join(
            f"{side} " + ", ".join(f"{k} win {sides[side][k].get('win_pct')}% vs Nifty {sides[side][k].get('avg_vs_nifty')} (n {sides[side][k].get('n')})" for k in H) for side in sides))
    for pool, v in out["conviction"].items():
        for name, sides in v["inputs"].items():
            print(f"[replay] conviction {pool} {name}: " + " | ".join(
                f"{side} " + ", ".join(f"{k} win {sides[side][k].get('win_pct')}% (n {sides[side][k].get('n')})" for k in H) for side in sides))
        for n, st in v["code_checks_met"].items():
            print(f"[replay] conviction {pool} {n} of {len(CV_CODE)} code checks: " + ", ".join(f"{k} win {st[k].get('win_pct')}% vs Nifty {st[k].get('avg_vs_nifty')} (n {st[k].get('n')})" for k in H))
    return out


if __name__ == "__main__":
    run("--quick" in sys.argv)
