"""Analyst consensus from Yahoo (third-party opinions; no formula can produce these). Labelled "Yahoo consensus".

Freshness, because Yahoo gives no per-broker date:
  - rating mix by month for the last 3 months (Ticker.recommendations)
  - change in the current-year EPS estimate over 30 and 90 days (Ticker.eps_trend; zeros mean missing)
  - our own dated log of consensus-target changes (data/analyst_history.json), from the first snapshot onward
Shown only when at least one analyst has a target.
"""
import json
import math
import time
from datetime import date
from pathlib import Path

import yfinance as yf

HIST = Path("data/analyst_history.json")


def _f(x):
    try:
        x = float(x)
        return None if math.isnan(x) or x == 0 else x
    except (TypeError, ValueError):
        return None


STORE = Path("data/analyst.json")   # {symbol: snapshot + "asof"} kept between runs (in git, small)
WEEKLY = 7                           # days between refreshes for covered stocks outside the priority set


def _one(t, s: str) -> dict | None:
    pt = t.analyst_price_targets or {}
    mean = _f(pt.get("mean"))
    if not mean:
        return None
    rec = {"mean": round(mean, 2), "low": _f(pt.get("low")), "high": _f(pt.get("high")), "median": _f(pt.get("median"))}
    mix = {}
    try:
        r = t.recommendations
        for _, row in (r if r is not None else []).iterrows():
            mix[row["period"]] = [int(row[k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")]
    except Exception:  # noqa: BLE001
        pass
    rec["mix"] = mix
    rec["n"] = sum(mix.get("0m", [])) or None
    try:
        e = t.eps_trend
        if e is not None and "0y" in e.index:
            cur, d30, d90 = (_f(e.loc["0y", c]) for c in ("current", "30daysAgo", "90daysAgo"))
            rec["eps_est"] = {"cur": cur, "d30": d30, "d90": d90}
    except Exception:  # noqa: BLE001
        pass
    return rec


def fetch(symbols: list[str], today: date, priority: set | None = None, results_since: dict | None = None,
          max_minutes: float = 6) -> dict:
    """Covered stocks only (Yahoo shows at least one analyst). Load once, then: daily for `priority` (decision-relevant),
    right after new results (`results_since`: {symbol: filing date}), weekly for the rest. Returns every stored snapshot,
    each with its "asof" date."""
    hist = json.loads(HIST.read_text()) if HIST.exists() else {}
    st = json.loads(STORE.read_text()) if STORE.exists() else {}
    priority, results_since = priority or set(), results_since or {}

    def due(s):
        r = st.get(s)
        if not r or not r.get("asof"):
            return 3
        age = (today - date.fromisoformat(r["asof"])).days
        if s in priority and age >= 1 and not r.get("none"):
            return 0
        if (results_since.get(s) or "") > r["asof"]:
            return 1
        return 2 if age >= WEEKLY else None

    todo = sorted((x for x in symbols if due(x) is not None), key=lambda x: (due(x), symbols.index(x)))
    t0, got, none = time.time(), 0, 0
    for s in todo:
        if time.time() - t0 > max_minutes * 60:
            break
        try:
            rec = _one(yf.Ticker(s), s)
        except Exception as e:  # noqa: BLE001
            print(f"[analyst] {s}: {e}")
            continue
        time.sleep(0.25)
        if not rec:
            none += 1
            st[s] = {"none": True, "asof": str(today)}  # no target published: re-checked weekly like the rest
            continue
        h = hist.setdefault(s, [])
        if not h or abs(h[-1]["mean"] - rec["mean"]) > 0.005 * h[-1]["mean"] or h[-1].get("n") != rec["n"] \
                or ((rec.get("eps_est") or {}).get("cur") or 0) != (h[-1].get("eps") or 0):
            h.append({"date": str(today), "mean": rec["mean"], "n": rec["n"], "eps": (rec.get("eps_est") or {}).get("cur")})
        hist[s] = h[-24:]
        rec["first_tracked"] = h[0]["date"]
        rec["last_change"] = h[-1]["date"] if len(h) > 1 else None
        rec["fresh"] = freshness(rec)
        rec["asof"] = str(today)
        st[s] = rec
        got += 1
    HIST.parent.mkdir(exist_ok=True)
    HIST.write_text(json.dumps(hist, separators=(",", ":")))
    STORE.write_text(json.dumps(st, separators=(",", ":"), sort_keys=True))
    cov = set(symbols)
    print(f"[analyst] {got} refreshed of {len(todo)} due, {none} without targets, {time.time() - t0:.0f}s; "
          f"targets stored for {sum(1 for x in cov if (st.get(x) or {}).get('mean'))} of {len(cov)} covered stocks")
    return {s: r for s, r in st.items() if s in cov and r.get("mean")}


def freshness(rec: dict) -> str:
    """Fresh: rating mix or EPS estimate changed within ~30 days. Aging: no change seen for 2+ months. Unknown otherwise."""
    mix = rec.get("mix") or {}
    eps = rec.get("eps_est") or {}
    if eps.get("cur") and eps.get("d30") and abs(eps["cur"] / eps["d30"] - 1) >= 0.01:
        return "Fresh"
    if mix.get("0m") and mix.get("-1m") and mix["0m"] != mix["-1m"]:
        return "Fresh"
    if mix.get("0m") and mix.get("-1m") and mix.get("-2m") and mix["0m"] == mix["-1m"] == mix["-2m"]:
        return "Aging"
    return "Unknown"


def mix_text(rec: dict) -> str:
    m = (rec.get("mix") or {}).get("0m")
    if not m:
        return ""
    names = ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")
    return " · ".join(f"{v} {n}" for v, n in zip(m, names) if v)
