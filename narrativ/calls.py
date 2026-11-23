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


MIN_DAYS = 20  # Sharpe and volatility need about a month of daily returns to mean anything


def daily_returns(calls: list[dict], px: dict, bench: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Equal-weight portfolio of the verified Buys: each call held from the close after its entry (first day measured from
    the entry price) to its end date; each day's return = average of the calls held that day. Nifty over the same days."""
    rets = []
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
        rets.append((held / prev - 1).rename(c["symbol"]))
    if not rets:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    port = pd.concat(rets, axis=1).mean(axis=1, skipna=True).sort_index()
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
           conviction: dict | None = None) -> dict:
    st = json.loads(OUT.read_text()) if OUT.exists() else {"calls": []}
    calls = st["calls"]
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
            if c and kind != k:  # call ended: decision moved away
                c["ended"], c["end_decision"] = str(today), d.get("d")
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
    if conviction is not None:
        set_conviction(calls, conviction, today)
    for c in calls:
        close = px[c["symbol"]]["Close"] if c["symbol"] in px else None
        if close is None:
            continue
        end = c.get("ended")  # returns freeze at the end: a holder who exited holds no more of the stock
        for h, n in HORIZONS.items():
            if c.get(h) is None:
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
    out = {"date": str(today), "note": "Returns from our exchange-file closes; vs Nifty = minus the Nifty's return over the same days.",
           "open": sum(1 for c in calls if not c.get("ended")), "summary": summary, "calls": calls}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"[calls] {out['open']} open calls ({sum(1 for c in calls if c['kind'] == 'verified' and not c.get('ended'))} verified), "
          f"{len(calls)} recorded")
    return out
