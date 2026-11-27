"""Forward ledger, stage 2 (owner, 27 Nov 2026): watch every verified target after it is made.

Three monitors, run daily on the ledger (narrativ/ledger.py) and the filed quarters, code only:
  progress   at each results filing, for company revenue / EBITDA / profit / margin / growth targets with a fiscal year:
             this year's filed quarters scaled by the share the same quarters had of last year's total (seasonality from
             the company's own last year) give a projected full year, compared with the target's low-high range:
             ahead / on track / behind. Needs 2+ quarters of the year before it says ahead or behind (one quarter is noise).
  resolution once all four quarters of the target year are filed: beat / met / missed against the target (2% tolerance).
             A non-financial target 30+ days past its due date with no outcome is flagged for Narrativ.ai to check.
  restatement a new version of a target (ledger.link): raised = good, lowered = bad. A target of an earlier call that is
             missing after the stock's research moved to a newer call is flagged "not restated" (a flag first, owner's
             choice: it can be the earliest warning, or an editing change).
Only Narrativ.ai's verified targets (ledger src "narrativ") make signals; nothing here changes a rating, gate or conviction
(stage 4 will). State in data/ledger_state.json (kept), signals in data/ledger_signals.json (last SIGNAL_DAYS).
"""
import json
from datetime import date, timedelta
from pathlib import Path

from . import ledger as LG
from . import metrics as MX

STATE = Path("data/ledger_state.json")
SIGNALS = Path("data/ledger_signals.json")
SIGNAL_DAYS = 400
TOL = 0.03          # projected within 3% below the low end still counts as on track
GROWTH_TOL = 2.0    # points, for growth-rate targets
MARGIN_TOL = 1.0    # points, for margin targets
RESOLVE_TOL = 0.02  # beat above high + 2%, missed below low - 2%
DUE_GRACE = 30      # days after a non-financial due date before it is flagged
MIN_Q = 2           # quarters of the target year filed before ahead / behind is said


def _d(x):
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _q_ends(fy: int) -> list[str]:
    return [f"{fy - 1}-06-30", f"{fy - 1}-09-30", f"{fy - 1}-12-31", f"{fy}-03-31"]


def _val(p: dict, what: str):
    q = (p or {}).get("q") or {}
    if what == "rev":
        return q.get("rev")
    if what == "pat":
        return q.get("pat")
    if what == "ebitda":
        return MX._ebitda_q(p)
    return None


def year_so_far(series: dict, fy: int, today: date) -> dict | None:
    """Filed quarters of fiscal year `fy` (in order, filed on or before today) and the same quarters of the year before.
    -> {"k", "cur": {rev, ebitda, pat}, "ly_part": {...}, "ly_full": {...}, "last_q", "filed"} in crore; None if not usable."""
    q = (series or {}).get("q") or {}
    cur_q = []
    for qe in _q_ends(fy):
        p = q.get(qe)
        if not p or str(p.get("filed") or qe) > str(today):
            break
        cur_q.append(p)
    ly = [q.get(qe) for qe in _q_ends(fy - 1)]
    if not cur_q or None in ly:
        return None
    k = len(cur_q)

    def tot(ps, what):
        vals = [_val(p, what) for p in ps]
        return None if None in vals else sum(vals) / MX.CR

    keys = ("rev", "ebitda", "pat")
    return {"k": k, "cur": {w: tot(cur_q, w) for w in keys}, "ly_part": {w: tot(ly[:k], w) for w in keys},
            "ly_full": {w: tot(ly, w) for w in keys}, "last_q": cur_q[-1].get("end"), "filed": cur_q[-1].get("filed")}


def _range(t: dict, conv: float = 1.0) -> tuple[float | None, float | None]:
    lo, hi = t.get("low"), t.get("high")
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    return (None, None) if lo is None else (lo * conv, hi * conv)


def check_progress(item: dict, series: dict, today: date) -> dict | None:
    """Progress or resolution of one verified financial target; None when it does not apply or cannot be computed yet."""
    t = item.get("target") or {}
    per = _d(item.get("period"))
    if item.get("src") != "narrativ" or not per or not t.get("fy") or str(t.get("of") or "company") != "company":
        return None  # only a target whose quote names its fiscal year is tracked (a medium-term corridor is not a FY27 target)
    m = item.get("measure") or ""
    what = {"revenue": "rev", "ebitda": "ebitda", "pat": "pat", "growth:revenue": "rev", "growth:ebitda": "ebitda",
            "growth:pat": "pat", "margin": "ebitda"}.get(m)
    if not what:
        return None
    ys = year_so_far(series, per.year, today)
    if not ys:
        return None
    k, cur, lp, lf = ys["k"], ys["cur"], ys["ly_part"], ys["ly_full"]
    out = {"k": k, "last_q": ys["last_q"], "filed": ys["filed"]}
    if m == "margin":
        if not cur.get("rev") or cur.get("ebitda") is None:
            return None
        actual = cur["ebitda"] / cur["rev"] * 100
        lo, hi = _range(t)
        if lo is None:
            return None
        out.update({"metric": "EBITDA margin %", "actual": round(actual, 1), "target": [lo, hi]})
        out["status"] = _status(actual, lo, hi, MARGIN_TOL, absolute=True, k=k)
        return out
    if lp.get(what) in (None, 0) or not lf.get(what) or lf[what] <= 0 or cur.get(what) is None:
        return None
    share = lp[what] / lf[what]  # how much of last year's total the same quarters made
    projected = cur[what] / share if share > 0 else None
    if projected is None:
        return None
    if m.startswith("growth:"):
        g = (projected / lf[what] - 1) * 100
        lo, hi = _range(t)
        if lo is None:
            return None
        out.update({"metric": f"{what} growth %", "projected": round(g, 1), "target": [lo, hi],
                    "actual_ytd": round(cur[what], 1), "share_ly": round(share, 3)})
        out["status"] = _status(g, lo, hi, GROWTH_TOL, absolute=True, k=k)
        return out
    conv = LG.TO_CR.get(str(t.get("unit") or "").lower().replace("₹", "").replace("inr", "").strip())
    if conv is None:
        return None
    lo, hi = _range(t, conv)
    if lo is None:
        return None
    out.update({"metric": what, "projected": round(projected, 1), "actual_ytd": round(cur[what], 1), "target": [lo, hi],
                "share_ly": round(share, 3)})
    out["status"] = _status(projected, lo, hi, TOL, absolute=False, k=k)
    return out


def _status(v: float, lo: float, hi: float, tol: float, absolute: bool, k: int) -> str:
    """beat / met / missed once the year is filed (k = 4); else ahead / on track / behind (early with fewer than MIN_Q)."""
    if k == 4:
        rt = RESOLVE_TOL if not absolute else tol
        up, down = (hi + rt, lo - rt) if absolute else (hi * (1 + rt), lo * (1 - rt))
        return "beat" if v > up else "met" if v >= down else "missed"
    if k < MIN_Q:
        return "early"
    up, down = (hi + tol, lo - tol) if absolute else (hi * (1 + tol), lo * (1 - tol))
    return "ahead" if v > up else "on track" if v >= down else "behind"


GOOD = {"ahead", "beat", "met", "raised"}
BAD = {"behind", "missed", "lowered"}


def run(theses: dict, today: date, fins: dict | None = None) -> dict:
    """Update data/ledger_state.json, append new signals to data/ledger_signals.json; return counts."""
    bases = LG.Bases(fins)
    rows = LG.annotate(LG.rows_from_theses(theses), bases)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"items": {}}
    items = state.setdefault("items", {})
    sig, seen = [], set()

    def signal(r, kind, status, detail):
        d = "good" if status in GOOD else "bad" if status in BAD else "neutral" if status == "on track" else "flag"
        sig.append({"date": str(today), "sym": r["sym"], "item": r["id"], "kind": kind, "status": status, "dir": d,
                    "material": r.get("material"), "measure": r.get("measure"), "text": r.get("text"), "detail": detail})

    quarter = {s: (t or {}).get("quarter") for s, t in theses.items()}
    for r in rows:
        seen.add(r["id"])
        st = items.get(r["id"])
        new = st is None
        st = items.setdefault(r["id"], {"first_seen": str(today)})
        st.update({"sym": r["sym"], "text": r["text"], "measure": r.get("measure"), "period": r.get("period"), "due": r.get("due"),
                   "src": r.get("src"), "material": r.get("material"), "quarter": quarter.get(r["sym"]), "last_seen": str(today)})
        st.pop("gone_on", None)
        if r.get("src") != "narrativ":
            continue
        if new and r.get("change") in ("raised", "lowered"):
            signal(r, "restatement", r["change"], {"prev": r.get("prev")})
        pr = check_progress(r, bases.series(r["sym"]), today)
        if pr:
            old = (st.get("progress") or {}).get("status")
            st["progress"] = pr
            if pr["status"] != old and pr["status"] != "early" and not (old is None and pr["status"] == "on track"):
                signal(r, "resolution" if pr["k"] == 4 else "progress", pr["status"], pr)
            if pr["k"] == 4:
                st["outcome"] = pr["status"]
        elif r.get("ftype") != "financial" and r.get("due") and not st.get("outcome") and not st.get("due_flagged"):
            dd = _d(r["due"])
            if dd and today > dd + timedelta(days=DUE_GRACE):
                st["due_flagged"] = str(today)
                signal(r, "due passed", "check", {"due": r["due"]})
    for iid, st in items.items():
        if iid in seen or st.get("gone_on"):
            continue
        st["gone_on"] = str(today)
        if st.get("src") == "narrativ" and not st.get("outcome") and quarter.get(st.get("sym")) and st.get("quarter") \
                and quarter[st["sym"]] != st["quarter"]:
            sig.append({"date": str(today), "sym": st["sym"], "item": iid, "kind": "not restated", "status": "check", "dir": "flag",
                        "material": st.get("material"), "measure": st.get("measure"), "text": st.get("text"),
                        "detail": {"made_in": st["quarter"], "now": quarter[st["sym"]]}})
    state["date"] = str(today)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, separators=(",", ":"), ensure_ascii=False))
    old = json.loads(SIGNALS.read_text()).get("signals", []) if SIGNALS.exists() else []
    cut = str(today - timedelta(days=SIGNAL_DAYS))
    keep = [x for x in old if x.get("date", "") >= cut and not (x.get("date") == str(today))] + sig
    SIGNALS.write_text(json.dumps({"date": str(today), "signals": keep}, separators=(",", ":"), ensure_ascii=False))
    tracked = [s for s in items.values() if s.get("progress")]
    return {"signals_today": len(sig), "good": sum(x["dir"] == "good" for x in sig), "bad": sum(x["dir"] == "bad" for x in sig),
            "neutral": sum(x["dir"] == "neutral" for x in sig),
            "flags": sum(x["dir"] == "flag" for x in sig), "tracked": len(tracked),
            "status": {k: sum((s.get("progress") or {}).get("status") == k for s in tracked)
                       for k in ("early", "ahead", "on track", "behind", "beat", "met", "missed")}}
