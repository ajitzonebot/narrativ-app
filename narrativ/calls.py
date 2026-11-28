"""Call tracking (the loop's scorecard): every stock that becomes a verified Buy / Strong Buy is recorded with its date and
price; its return and the Nifty's over the same days are measured at 1, 3 and 6 months (21, 63, 126 trading days) and when
the call ends (the decision leaves Buy). Rule candidates waiting for Claude are tracked the same way, so the two can be
compared. docs/data/calls.json, from our own exchange-file prices."""
import json
from pathlib import Path

import pandas as pd

OUT = Path("docs/data/calls.json")
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252, "36m": 756}
BUY = ("Buy", "Strong Buy")
SELL = ("Sell", "Strong Sell")
# Owner, 28 Nov 2026: "once Buy, check every day if it's a Buy; if it turns Sell, close the card" (and the exit level still
# closes it). Until then a call ended whenever the decision left Buy, so a Buy that dipped to Hold for one run (MOLDTECH and
# 20 others on 27 Nov, a rule change reverted the same evening) was closed and re-entered at a new price.
TRACKING_RULE = "close on Sell or exit level (2026-11-28)"
_FROZEN = ("ended", "end_decision", "to_end", "to_end_vs_nifty") + tuple(f"{h}{x}" for h in HORIZONS for x in ("", "_vs_nifty"))


def reopen_under_rule(calls: list[dict]) -> int:
    """One-time move to TRACKING_RULE: a verified call that ended only because the decision left Buy (Hold, Not rated) is
    open again from its own entry; a later call of the same stock and kind is a duplicate of it and is dropped, unless that
    later call ended on a real exit (exit level, Sell, left the universe): it stays, and the reopened call ends with it (same
    date and reason). Real-exit ends stay; candidate calls keep their ends (a candidate still ends when it stops being one).
    Returns how many calls reopened."""
    keep_end = lambda c: str(c.get("end_decision") or "").startswith(("Exit level", "Left the universe")) or c.get("end_decision") in SELL  # noqa: E731
    reopened = [c for c in calls if c.get("ended") and c["kind"] == "verified" and not keep_end(c)]
    for c in reopened:
        for k in _FROZEN:  # returns were frozen at the old end: measured again from the entry
            c.pop(k, None)
    first = {}
    for c in sorted(calls, key=lambda c: (c["date"], c.get("run") or "")):
        k = (c["symbol"], c["kind"])
        if k in first and not first[k].get("ended"):
            if c.get("ended"):  # a real exit of the same holding: kept, and the earlier call open again ends with it
                first[k]["ended"], first[k]["end_decision"] = c["ended"], c["end_decision"]
                first[k] = c
            else:
                c["_dup"] = True  # overlaps an earlier call that is open again
        else:
            first[k] = c
    calls[:] = [c for c in calls if not c.pop("_dup", False)]
    return len(reopened)


# The 28 Nov 2026 run of the first reopen_under_rule (docs/data/calls.json at d447bf4e1 -> 3da233321) also reopened 42
# candidate calls whose ends were real under the rule (the candidate became verified, or stopped being a candidate). Their
# ends as recorded before that run: symbol, entry date, run, ended, then "Buy" (became verified) or "Hold" (no longer one).
_CANDIDATE_ENDS = """
ATL 2026-11-16 2026-11-17 2026-11-18 Hold|CHENNPETRO 2026-11-16 2026-11-17 2026-11-18 Hold|SONAMLTD 2026-11-16 2026-11-17 2026-11-18 Hold
HUDCO 2026-11-19 2026-11-19 2026-11-20 Buy|ARROWGREEN 2026-11-20 2026-11-20 2026-11-23 Buy|CANTABIL 2026-11-20 2026-11-20 2026-11-23 Hold
CAPLIPOINT 2026-11-20 2026-11-20 2026-11-23 Buy|FMGOETZE 2026-11-20 2026-11-20 2026-11-23 Hold|GHCLTEXTIL 2026-11-20 2026-11-20 2026-11-23 Buy
GPTHEALTH 2026-11-20 2026-11-20 2026-11-23 Buy|INDRAMEDCO 2026-11-20 2026-11-20 2026-11-23 Hold|MAYURUNIQ 2026-11-20 2026-11-20 2026-11-23 Hold
MPSLTD 2026-11-20 2026-11-20 2026-11-23 Buy|SATIN 2026-11-20 2026-11-20 2026-11-23 Buy|SEAMECLTD 2026-11-20 2026-11-20 2026-11-23 Hold
TALBROAUTO 2026-11-20 2026-11-20 2026-11-23 Buy|THEJO 2026-11-20 2026-11-20 2026-11-23 Buy|PASUPTAC 2026-11-23 2026-11-23 2026-11-26 Hold
WINDLAS 2026-11-23 2026-11-23 2026-11-25 Buy|CASTROLIND 2026-11-23 2026-11-23 2026-11-25 Hold|ERIS 2026-11-23 2026-11-23 2026-11-25 Hold
FCL 2026-11-23 2026-11-23 2026-11-25 Hold|TNPETRO 2026-11-23 2026-11-23 2026-11-25 Hold|NORTHARC 2026-11-25 2026-11-23 2026-11-25 Hold
SARDAEN 2026-11-25 2026-11-23 2026-11-25 Buy|EQUIPPP 2026-11-25 2026-11-25 2026-11-26 Hold|MANAKSTEEL 2026-11-25 2026-11-25 2026-11-26 Hold
MOREPENLAB 2026-11-25 2026-11-25 2026-11-26 Hold|RAMRAT 2026-11-25 2026-11-25 2026-11-26 Hold|RPGLIFE 2026-11-25 2026-11-25 2026-11-26 Hold
AFIL 2026-11-26 2026-11-25 2026-11-26 Hold|DHANBANK 2026-11-26 2026-11-25 2026-11-26 Buy|PRECWIRE 2026-11-26 2026-11-25 2026-11-26 Hold
PRICOLLTD 2026-11-26 2026-11-25 2026-11-26 Hold|SANGHVIMOV 2026-11-26 2026-11-25 2026-11-26 Buy|SHREERAMA 2026-11-26 2026-11-25 2026-11-26 Hold
SURAKSHA 2026-11-26 2026-11-25 2026-11-26 Buy|EMAMILTD 2026-11-27 2026-11-26 2026-11-27 Hold|EMKAY 2026-11-27 2026-11-26 2026-11-27 Hold
INSECTICID 2026-11-27 2026-11-26 2026-11-27 Buy|KPIGREEN 2026-11-27 2026-11-26 2026-11-27 Hold|LUPIN 2026-11-27 2026-11-26 2026-11-27 Buy
"""
CAND_VERIFIED, CAND_DROPPED, CAND_FAILED = "Became verified", "No longer a candidate", "Review did not pass"


def restore_candidate_ends(calls: list[dict]) -> int:
    """Gives the 42 candidate calls in _CANDIDATE_ENDS their recorded end back, only while that exact call (symbol, entry
    date, run) is still open; a no-op once done. Returns how many were restored."""
    ends = {}
    for row in _CANDIDATE_ENDS.replace("\n", "|").split("|"):
        if row.strip():
            s, d, run, ended, was = row.split()
            ends[(f"{s}.NS", d, run)] = (ended, CAND_VERIFIED if was == "Buy" else CAND_DROPPED)
    n = 0
    for c in calls:
        e = ends.get((c["symbol"], c["date"], c.get("run")))
        if e and c["kind"] == "candidate" and not c.get("ended"):
            c["ended"], c["end_decision"] = e
            n += 1
    return n


def _ret(close: pd.Series, d0: str, n: int | None, base: float | None = None):
    """Return from the entry close (dated d0, or `base` if given) to the n-th close after it (latest when n is None)."""
    c = close.dropna()
    before, after = c[c.index <= pd.Timestamp(d0)], c[c.index > pd.Timestamp(d0)]
    b0 = base if base else (float(before.iloc[-1]) if len(before) else None)
    if not b0 or not len(after) or (n is not None and len(after) < n):
        return None
    end = after.iloc[n - 1] if n is not None else after.iloc[-1]
    return round((float(end) / float(b0) - 1) * 100, 2)


def _close_date(close: pd.Series, price: float, upto: str) -> str | None:
    """Date of the close a call was entered at (the run prices at the latest exchange close, often the day before)."""
    c = close.dropna()
    c = c[c.index <= pd.Timestamp(upto)]
    for d, v in zip(reversed(c.index), reversed(c.values)):
        if round(float(v), 2) == round(float(price), 2):
            return str(d.date())
        if (pd.Timestamp(upto) - d).days > 10:
            break
    return None


def _held(close: pd.Series, d0: str, n: int | None, base: float | None, ended: str | None):
    """Return at horizon n (latest when None) as the holder had it: a call that ended before the horizon keeps its return
    at the end date (frozen, it is not followed after the exit); the horizon is still filled only once n closes exist."""
    if not ended:
        return _ret(close, d0, n, base)
    c = close.dropna()
    after = c[c.index > pd.Timestamp(d0)]
    if not len(after) or (n is not None and len(after) < n):
        return None
    if (after.index[n - 1] if n is not None else after.index[-1]) <= pd.Timestamp(ended):
        return _ret(close, d0, n, base)
    return _ret(c[c.index <= pd.Timestamp(ended)], d0, None, base)


COOLDOWN = 10  # trading days


def cooling(calls: list[dict], s: str, kind: str, close: pd.Series) -> bool:
    """After a call ends on its exit level, the stock is not re-entered (no new call) until a close is back above that exit
    level, or COOLDOWN trading days have passed since the exit (a fresh setup). Stops a still-Buy stock from reopening the
    run after its stop broke."""
    ended = [c for c in calls if c["symbol"] == s and c["kind"] == kind and c.get("ended")]
    last = max(ended, key=lambda c: c["ended"], default=None)
    if not last or not str(last.get("end_decision") or "").startswith("Exit level") or not last.get("stop"):
        return False
    c = close.dropna()
    after = c[c.index > pd.Timestamp(last["ended"])]
    if len(after) >= COOLDOWN:
        return False
    return not (len(c) and float(c.iloc[-1]) > float(last["stop"]))


def exited_on_stop(c: dict) -> bool:
    return bool(c.get("ended")) and str(c.get("end_decision") or "").startswith("Exit level")


def reentry_after(ended: str, close: pd.Series | None = None, hol: set[str] | None = None) -> str:
    """Date of the COOLDOWN-th trading day after a call's exit (feedback #92): the day `cooling` stops holding the stock
    back even if the price stays below the exit level (it counts closes after the exit date). From the stock's own closes
    while they reach that far; beyond the latest close, from the NSE trading calendar (weekends and
    docs/data/holidays.json)."""
    from datetime import date as _date

    from narrativ import holidays
    hol = holidays.load() if hol is None else hol
    t0 = pd.Timestamp(ended)
    after = [] if close is None else list(close.dropna().index[close.dropna().index > t0])
    if len(after) >= COOLDOWN:
        return str(after[COOLDOWN - 1].date())
    base = after[-1].date() if after else _date.fromisoformat(str(ended)[:10])
    return str(holidays.nth_trading_day_after(base, COOLDOWN - len(after), hol))


def exit_hit(calls: list[dict], s: str, kind: str | None, close: pd.Series) -> dict | None:
    """For the stock's detail file (the app): the latest call of the kind the stock is rated now (verified Buy or
    candidate) ended on its exit level and the stock is still cooling (no new call yet), else None."""
    if not kind:
        return None
    ended = [c for c in calls if c["symbol"] == s and c["kind"] == kind and c.get("ended")]
    last = max(ended, key=lambda c: c["ended"], default=None)
    if not last or not exited_on_stop(last) or not last.get("stop") or not cooling(calls, s, kind, close):
        return None
    return {"stop": float(last["stop"]), "date": str(last["ended"])[:10],
            "reentry_after": last.get("reentry_after") or reentry_after(last["ended"], close), "kind": kind}


SIZE_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.25}  # position size by conviction (narrativ/conviction.py SIZE)
MIN_DAYS = 20  # Sharpe and volatility need about a month of daily returns to mean anything


def daily_returns(calls: list[dict], px: dict, bench: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Portfolio of the verified Buys, sized by conviction at entry (owner, 26 Nov 2026, option C: High full, Medium half, Low
    a quarter; calls without a rule-built level count as full): each call held from the close after its entry (first day
    measured from the entry price) to its end date; each day's return = the size-weighted average of the calls held that
    day. Nifty over the same days."""
    rets, wts = [], []
    for c in calls:
        if c["kind"] != "verified" or c["symbol"] not in px:
            continue
        cl = px[c["symbol"]]["Close"].dropna()
        held = cl[cl.index > pd.Timestamp(c["date"])]
        if c.get("ended"):
            held = held[held.index <= pd.Timestamp(c["ended"])]
        if not len(held):
            continue
        prev = pd.concat([pd.Series([float(c["price"])], index=[pd.Timestamp(c["date"])]), held]).shift(1).iloc[1:]
        rets.append((held / prev - 1).rename(f"{c['symbol']}|{c['date']}"))
        wts.append(SIZE_WEIGHT.get(c.get("conviction") or "", 1.0))
    if not rets:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    R = pd.concat(rets, axis=1)
    W = R.notna().mul(wts, axis=1)
    port = (R.fillna(0).mul(wts, axis=1).sum(axis=1) / W.sum(axis=1)).dropna().sort_index()
    b = bench.dropna().pct_change().reindex(port.index).fillna(0.0)
    return port, b


def portfolio(calls: list[dict], px: dict, bench: pd.Series) -> dict | None:
    """Scorecard of the Buys as one portfolio vs the Nifty (quantstats): total return, max drawdown, share of days ahead;
    Sharpe and volatility once MIN_DAYS of returns exist. `curve`: growth of 100 for the app chart."""
    import quantstats as qs
    port, b = daily_returns(calls, px, bench)
    if not len(port):
        return None
    pi, bi = (1 + port).cumprod() * 100, (1 + b).cumprod() * 100
    enough = len(port) >= MIN_DAYS
    r2 = lambda x: None if x is None or pd.isna(x) else round(float(x), 2)  # noqa: E731
    return {"since": str(port.index[0].date()), "days": len(port), "min_days": MIN_DAYS,
            "return_pct": r2(qs.stats.comp(port) * 100), "nifty_pct": r2(qs.stats.comp(b) * 100),
            "excess_pct": r2((qs.stats.comp(port) - qs.stats.comp(b)) * 100),
            "max_dd_pct": r2(qs.stats.max_drawdown(port) * 100), "nifty_max_dd_pct": r2(qs.stats.max_drawdown(b) * 100),
            "days_ahead_pct": r2((port > b).mean() * 100),
            "sharpe": r2(qs.stats.sharpe(port)) if enough else None, "nifty_sharpe": r2(qs.stats.sharpe(b)) if enough else None,
            "vol_pct": r2(qs.stats.volatility(port) * 100) if enough else None,
            "curve": [[str(d.date()), round(float(x), 2), round(float(y), 2)] for d, x, y in zip(pi.index, pi, bi)]}


def set_conviction(calls: list[dict], conviction: dict, today) -> None:
    """`conviction` on a verified call is the rule-built level (narrativ/conviction.py: high / medium / low) on the day the
    call was entered, so summary.by_conviction measures whether more verified evidence meant better outcomes. Calls entered
    before the rule existed: Claude's typed synthesis value moves to `claude_conviction` (kept for comparison, not used in
    by_conviction); open ones take today's rule level once (`conviction_date` says when it was taken)."""
    for c in calls:
        if "conviction_rule" in c:  # already set by the rule (or marked as never set)
            continue
        if c.get("conviction") is not None:
            c["claude_conviction"] = c["conviction"]
        lv = None if c.get("ended") or c["kind"] != "verified" else conviction.get(c["symbol"])
        c["conviction"] = lv.lower() if lv else None
        c["conviction_rule"] = bool(lv)  # False: entered before the rule or not a verified Buy; never backfilled later
        if lv:
            c["conviction_date"] = str(today)


def update(dec: dict, px: dict, bench: pd.Series, theses: dict, today, stops: dict | None = None,
           conviction: dict | None = None, aliases: dict | None = None, universe: set | None = None) -> dict:
    st = json.loads(OUT.read_text()) if OUT.exists() else {"calls": []}
    calls = st["calls"]
    if st.get("tracking_rule") != TRACKING_RULE:
        print(f"[calls] tracking rule '{TRACKING_RULE}': {reopen_under_rule(calls)} call(s) open again from their entry")
    if n := restore_candidate_ends(calls):
        print(f"[calls] {n} candidate call(s) reopened by the 28 Nov move given their recorded end back")
    for c in calls:  # a company that moved symbol (BSE -> NSE) keeps its calls, as research and memory do (audit 26 Nov 2026)
        if aliases and c["symbol"] in aliases:
            c["symbol"] = aliases[c["symbol"]]
    seen = set()  # after a move, the older open call stays; one opened under the new symbol is a duplicate
    for c in sorted(calls, key=lambda c: c["date"]):
        k = (c["symbol"], c["kind"])
        if not c.get("ended"):
            c["_dup"] = k in seen
            seen.add(k)
    calls[:] = [c for c in calls if not c.pop("_dup", False)]
    if universe:  # a stock that left the universe (below the size floor, delisted) ends its open calls today
        gone = [c for c in calls if not c.get("ended") and c["symbol"] not in universe]
        if len(gone) <= max(3, len(calls) // 10):  # many at once means a short universe list, not real exits
            for c in gone:
                c["ended"], c["end_decision"] = str(today), "Left the universe"
        else:
            print(f"[calls] {len(gone)} open calls not in today's universe: universe list looks short, none ended")
    for c in calls:  # date each call by the close it was entered at (older calls carried the run date)
        if "run" not in c:
            c["run"] = c["date"]
            if c["symbol"] in px and len(px[c["symbol"]]):
                c["date"] = _close_date(px[c["symbol"]]["Close"], c["price"], c["run"]) or c["date"]
    # calls opened and closed by re-runs on the same day never held a close: noise, not a track record
    calls[:] = [c for c in calls if not (c.get("ended") and c["ended"] <= c["run"]
                                         and not str(c.get("end_decision") or "").startswith("Exit level"))]
    # a call opened with its exit level at or above the entry price was over before it began (a setup bug, e.g. SATIN entry
    # 254.55, exit level 260.8): not a track record. Exit levels attached later (`stop_from`) may sit above the entry.
    calls[:] = [c for c in calls if not (c.get("stop") is not None and not c.get("stop_from") and c["stop"] >= c["price"])]
    stops = stops or {}
    for c in calls:  # calls opened before exit tracking: take today's exit level once, tested only from the close it was set at
        s = c["symbol"]
        if not c.get("ended") and c.get("stop") is None and stops.get(s) and s in px and len(px[s]["Close"].dropna()):
            cl0 = px[s]["Close"].dropna()
            if stops[s] < float(cl0.iloc[-1]):
                c["stop"], c["stop_from"] = stops[s], str(cl0.index[-1].date())
    # exit level broken on a close: the call ends there, as a real holder would exit (checked before the decision moves,
    # so a stop broken days ago is not dated by today's run)
    for c in calls:
        if c.get("ended") or not c.get("stop") or c["symbol"] not in px:
            continue
        cl = px[c["symbol"]]["Close"].dropna()
        cl = cl[cl.index > pd.Timestamp(c.get("stop_from") or c["date"])]
        hit = cl[cl < c["stop"]]
        if len(hit):
            c["ended"], c["end_decision"] = str(hit.index[0].date()), f"Exit level ₹{c['stop']:,.2f} broken"
    open_ = {(c["symbol"], c["kind"]): c for c in calls if not c.get("ended")}
    for s, d in dec.items():
        kind = "verified" if d.get("d") in BUY else "candidate" if d.get("candidate") in BUY else None
        for k in ("verified", "candidate"):
            c = open_.get((s, k))
            if not c:
                continue
            end = d.get("d") if d.get("d") in SELL else None  # TRACKING_RULE: a verified call ends only on a Sell (or exit level)
            if not end and k == "candidate":  # a candidate call ends when the stock stops being a candidate
                if d.get("d") in BUY or (s, "verified") in open_:  # verified now: one call per stock, the verified one
                    end = CAND_VERIFIED
                elif d.get("candidate") not in BUY:
                    end = CAND_FAILED if d.get("verified") in ("caution", "fail") else CAND_DROPPED
            if end:
                c["ended"], c["end_decision"] = str(today), end
                open_.pop((s, k), None)
        if kind == "candidate" and (s, "verified") in open_:  # a verified Buy back to review: its call carries on, no candidate call
            kind = None
        if kind and (s, kind) not in open_ and s in px and len(px[s]):
            cl0 = px[s]["Close"].dropna()
            stop = stops.get(s)
            if stop is not None and stop >= float(cl0.iloc[-1]):
                continue  # exit level at or above the price: no live entry, nothing to track
            if cooling(calls, s, kind, cl0):
                continue
            sy = (theses.get(s) or {}).get("synthesis") or {}
            row = {"symbol": s, "kind": kind, "decision": d.get("d") if kind == "verified" else d.get("candidate"),
                   "date": str(cl0.index[-1].date()), "run": str(today), "price": round(float(cl0.iloc[-1]), 2),
                   "conviction": sy.get("conviction"), "stop": stop}
            if conviction is not None:  # rule-built level at entry; Claude's typed value kept beside it for comparison
                lv = conviction.get(s) if kind == "verified" else None
                row |= {"conviction": lv.lower() if lv else None, "conviction_rule": bool(lv), "claude_conviction": sy.get("conviction")}
                if lv:
                    row["conviction_date"] = str(today)
            calls.append(row)
    # re-entry date of every call that ended on its exit level (feedback #92; older calls backfilled): recomputed each run,
    # so a calendar estimate becomes the stock's own 10th close once it exists
    from narrativ import holidays
    hol = holidays.load()
    for c in calls:
        if exited_on_stop(c) and (c["symbol"] in px or not c.get("reentry_after")):
            c["reentry_after"] = reentry_after(c["ended"], px[c["symbol"]]["Close"] if c["symbol"] in px else None, hol)
    if conviction is not None:
        set_conviction(calls, conviction, today)
    for c in calls:
        close = px[c["symbol"]]["Close"] if c["symbol"] in px else None
        if close is None:
            continue
        end = c.get("ended")  # returns freeze at the end: a holder who exited holds no more of the stock
        for h, n in HORIZONS.items():
            if c.get(h) is None or c.get(f"{h}_vs_nifty") is None:  # a Nifty close missing that day is filled on a later run
                r, b = _held(close, c["date"], n, c["price"], end), _held(bench, c["date"], n, None, end)
                if r is not None:
                    c[h], c[f"{h}_vs_nifty"] = r, (round(r - b, 2) if b is not None else None)
        c["now"] = _held(close, c["date"], None, c["price"], end)
        c["price_now"] = round(float(close.dropna().iloc[-1]), 2) if len(close.dropna()) else None
        b_now = _held(bench, c["date"], None, None, end)
        c["now_vs_nifty"] = round(c["now"] - b_now, 2) if c["now"] is not None and b_now is not None else None
        if end and c.get("to_end") is None:
            sub = close[close.index <= pd.Timestamp(end)]
            c["to_end"] = _ret(sub, c["date"], None, c["price"])
            bsub = bench[bench.index <= pd.Timestamp(end)]
            be = _ret(bsub, c["date"], None)
            c["to_end_vs_nifty"] = round(c["to_end"] - be, 2) if c["to_end"] is not None and be is not None else None

    def stats(rows, h):
        v = [r[h] for r in rows if r.get(h) is not None]
        x = [r[f"{h}_vs_nifty"] for r in rows if r.get(f"{h}_vs_nifty") is not None]
        return {"n": len(v), "avg_pct": round(sum(v) / len(v), 2) if v else None, "hit_pct": round(sum(1 for y in v if y > 0) / len(v) * 100) if v else None,
                "avg_vs_nifty": round(sum(x) / len(x), 2) if x else None}
    summary = {k: {h: stats([c for c in calls if c["kind"] == k], h) for h in HORIZONS} for k in ("verified", "candidate")}
    # rule-built conviction at entry only (narrativ/conviction.py); Claude's typed value is not a measure
    summary["by_conviction"] = {cv: {h: stats([c for c in calls if c["kind"] == "verified" and c.get("conviction_rule")
                                               and c.get("conviction") == cv], h) for h in HORIZONS}
                                for cv in ("high", "medium", "low")}
    # outcome mix of verified Buys vs the goal (2 multibaggers, 3 beat Nifty, 3 near, 2 losers per 10): latest return
    # (exit return for closed calls); multibagger = 2x, "on track" = +50% within 12 months
    mix = {"multibagger": 0, "on_track": 0, "beat": 0, "near": 0, "loser": 0, "n": 0}
    for c in calls:
        if c["kind"] != "verified":
            continue
        r = c.get("to_end") if c.get("ended") else c.get("now")
        rv = c.get("to_end_vs_nifty") if c.get("ended") else c.get("now_vs_nifty")
        if r is None or rv is None:
            continue
        mix["n"] += 1
        days = (pd.Timestamp(c.get("ended") or today) - pd.Timestamp(c["date"])).days
        mix["multibagger" if r >= 100 else "on_track" if r >= 50 and days <= 365 else "beat" if rv > 5 else "loser" if rv < -5 else "near"] += 1
    v_ = [c for c in calls if c["kind"] == "verified"]
    def avg(k):
        x = [(c.get("to_end") if c.get("ended") else c.get(k)) for c in v_]
        x = [y for y in x if y is not None]
        return round(sum(x) / len(x), 2) if x else None
    vs = [(c.get("to_end_vs_nifty") if c.get("ended") else c.get("now_vs_nifty")) for c in v_]
    vs = [y for y in vs if y is not None]
    summary["now"] = {"n": len(v_), "avg_pct": avg("now"), "avg_vs_nifty": round(sum(vs) / len(vs), 2) if vs else None,
                      "beat_pct": round(sum(1 for y in vs if y > 0) / len(vs) * 100) if vs else None, "mix": mix}
    try:
        summary["portfolio"] = portfolio(calls, px, bench)
    except Exception as e:  # noqa: BLE001  the scorecard must not stop the daily run
        print(f"[calls] portfolio metrics failed: {type(e).__name__}: {e}")
    out = {"date": str(today), "tracking_rule": TRACKING_RULE,
           "note": "Returns from our exchange-file closes; vs Nifty = minus the Nifty's return over the same days.",
           "open": sum(1 for c in calls if not c.get("ended")), "summary": summary, "calls": calls}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"[calls] {out['open']} open calls ({sum(1 for c in calls if c['kind'] == 'verified' and not c.get('ended'))} verified), "
          f"{len(calls)} recorded")
    return out
