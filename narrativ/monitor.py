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
  events     (stage 3) the stock's classified filings (narrativ/events.py) and order wins (narrativ/orders.py) after a target
             was made: a single order worth ORDER_PCT+ of last year's revenue is good; orders announced in a target's year
             count toward an order-inflow target (met on announcements alone = good); a commissioning / approval / launch
             filing that names a capacity or event target's plant, site or product = "announced" (good); a red filing (default,
             fraud, downgrade, adverse inspection, auditor or top-management exit ...) is bad for the stock's open targets,
             linked to the one it names; a watch filing is a flag when the stock has a material target. Each filing once.
Only Narrativ.ai's verified targets (ledger src "narrativ") make signals; nothing here changes a rating, gate or conviction
(stage 4 will). State in data/ledger_state.json (kept), signals in data/ledger_signals.json (last SIGNAL_DAYS).
"""
import json
import re
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


GOOD = {"ahead", "beat", "met", "raised", "announced", "order win", "met on orders"}
BAD = {"behind", "missed", "lowered", "red filing"}
ORDER_PCT = 10.0     # a single order of 10%+ of last year's revenue (as R4 T3)
EVENT_MATCH = {"Capacity / commissioning": ("capacity", "other", "event", "capex"), "Approval / launch": ("event", "other"),
               "Regulatory inspection cleared": ("event", "capacity", "other")}
_GENERIC = {"plant", "facil", "capac", "commi", "unit", "new", "produ", "line", "lines", "expan", "compa", "limit", "start",
            "comme", "opera", "proje", "relea", "annou", "trade", "inves", "presen", "disclo", "regul", "intim", "updat",
            "per", "annum", "mr", "ms", "shri", "about", "infor", "excha", "regar", "under", "pursu", "furth", "conti", "filed",
            "board", "meeti", "appro", "india", "indian", "total", "crore", "year", "quart", "month", "expec"}


_BOILER = re.compile(r"^.{0,160}?\b(has|have)\s+informed\s+the\s+exchange\s+(about|regarding|that|of)?|"
                     r"\b(this disclosure is in continuation (to|of) the disclosure filed by the company on [^.]*\.?)|"
                     r"\b(press release|intimation|disclosure|regulation \d+|sebi \(listing[^)]*\))", re.I)
# "announced" needs the filing to say it happened, not that it is planned
_DONE = re.compile(r"\bcommissioned\b|\bcommenced\b|commencement of (commercial|production|operation)|commercial (production|operations?)"
                   r"\s+(has\s+|have\s+)?(started|commenced|begun|began)|started commercial|\bcompleted\b|completion of|"
                   r"(approval|licen[cs]e|clearance|certificate)s?\s+(has\s+been\s+|was\s+)?(received|granted|obtained)|"
                   r"(received|obtained|granted)\s.{0,40}(approval|licen[cs]e|clearance|certificate)|\blaunched\b|\bgo-?live\b|"
                   r"\bnai\b|no action indicated|close-?out", re.I)
WATCH_FLAGS = {"Pollution board notice", "Regulatory inspection: observations", "Regulatory inspection: outcome not in subject",
               "Rating withdrawn", "Credit rating revised (direction in the filing)", "Pledge / encumbrance created"}


def _names(text: str, company: str = "") -> set:
    """Content words that can name a plant, site or product: exchange boilerplate, the company's own name and generic
    project words dropped."""
    from .conviction import _words
    own = {w for w in _words(company) if not w[0].isdigit()}
    return {w for w in _words(_BOILER.sub(" ", text or "")) if not w[0].isdigit()} - _GENERIC - own


def link_events(rows: list[dict], events: list[dict], orders: list[dict], fy_rev: float | None, seen: set, today: date,
                company: str = "") -> list[dict]:
    """Stage 3 for one stock: [(row or None, status, detail)] from filings and order wins not seen before (`seen`: urls)."""
    out = []
    mine = [r for r in rows if r.get("src") == "narrativ"]
    if not mine:
        return out
    first = min(str(r.get("made") or today) for r in mine)
    open_rows = [r for r in mine if r.get("ftype") != "event" or r.get("due")]
    material = any(r.get("material") == 1 for r in mine)
    for e in events or []:
        k = e.get("url") or f"{e.get('date')}|{e.get('text')}"
        k2 = f"{e.get('date')}|{e.get('type')}|{re.sub(r'[^a-z0-9]', '', str(e.get('text') or '').lower())[:120]}"  # same filing, two urls
        if k in seen or k2 in seen or str(e.get("date") or "") < first or str(e.get("date") or "") > str(today):
            continue
        seen.update((k, k2))
        t, sev, txt = e.get("type") or "", e.get("sev") or "", f"{e.get('text') or ''} {e.get('category') or ''}"
        ev_names = _names(txt, company)
        named = [r for r in open_rows if str(r.get("made") or "") <= str(e.get("date")) and len(_names(r["text"], company) & ev_names) >= 2]
        det = {"filing": (e.get("text") or "")[:160], "type": t, "date": e.get("date"), "url": e.get("url")}
        if sev == "green" and t in EVENT_MATCH and _DONE.search(txt):
            for r in named:
                if (r.get("ftype") if r.get("ftype") == "event" else r.get("measure")) in EVENT_MATCH[t] or r.get("ftype") in EVENT_MATCH[t]:
                    out.append((r, "announced", det))
        elif sev == "red":
            out.append((named[0] if named else None, "red filing", {**det, "targets": [r["id"] for r in (named or open_rows)]}))
        elif sev == "watch" and material and t in WATCH_FLAGS:
            out.append((named[0] if named else None, "check", {**det, "targets": [r["id"] for r in (named or open_rows)]}))
    for o in orders or []:
        k = o.get("url") or f"{o.get('date')}|{o.get('text')}"
        if k in seen or str(o.get("date") or "") < first:
            continue
        seen.add(k)
        if o.get("cr") and fy_rev and o["cr"] / fy_rev * 100 >= ORDER_PCT:
            tgt = next((r for r in mine if r.get("measure") in ("order", "order_book")), None)
            out.append((tgt, "order win", {"filing": o.get("text"), "date": o.get("date"), "url": o.get("url"), "cr": o["cr"],
                                           "pct_of_revenue": round(o["cr"] / fy_rev * 100, 1)}))
    # order-inflow targets: announced orders in the target's fiscal year against the target (a floor: only material orders are filed)
    for r in mine:
        t = r.get("target") or {}
        per = _d(r.get("period"))
        if r.get("measure") != "order_book" or not per or not t.get("fy") or not re.search(r"inflow|booking|order intake|new orders",
                                                                                            r["text"], re.I):
            continue
        conv = LG.TO_CR.get(str(t.get("unit") or "").lower().strip())
        lo, _ = _range(t, conv or 0)
        if not conv or not lo:
            continue
        start = f"{per.year - 1}-04-01"
        tot = sum(o["cr"] for o in orders or [] if o.get("cr") and start <= str(o.get("date") or "") <= str(per))
        r["_orders_fy"] = round(tot, 1)
        if tot >= lo and f"inflow-met|{r['id']}" not in seen:
            seen.add(f"inflow-met|{r['id']}")
            out.append((r, "met on orders", {"announced_cr": round(tot, 1), "target_cr": lo}))
    return out


def run(theses: dict, today: date, fins: dict | None = None, events: dict | None = None, orders: dict | None = None,
        names: dict | None = None) -> dict:
    """Update data/ledger_state.json, append new signals to data/ledger_signals.json; return counts. `events`: {symbol:
    classified filings (memory events)}; `orders`: {symbol: orders.recent(...) rows}."""
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
    # stage 3: filings and orders linked to targets
    seen_ev = set(state.get("seen_events") or [])
    by_sym: dict = {}
    for r in rows:
        by_sym.setdefault(r["sym"], []).append(r)
    for sym, rs in by_sym.items():
        if not (events or {}).get(sym) and not (orders or {}).get(sym):
            continue
        fy = bases.fy(sym, today)
        rev = (fy.get(max(fy)) or {}).get("rev") if fy else None
        company = (theses.get(sym) or {}).get("company") or (names or {}).get(sym) or sym.split(".")[0]
        for r, stt, det in link_events(rs, (events or {}).get(sym), (orders or {}).get(sym), rev, seen_ev, today, company):
            if r is None:
                r = {"sym": sym, "id": f"stock:{sym}", "material": int(any(x.get("material") == 1 for x in rs)), "measure": None,
                     "text": "(the stock's open targets)"}
            elif stt in ("announced", "met on orders"):
                items.setdefault(r["id"], {})["evidence"] = {"status": stt, **{k: det.get(k) for k in ("date", "url", "announced_cr")}}
            signal(r, "order" if stt in ("order win", "met on orders") else "filing", stt, det)
    state["seen_events"] = sorted(seen_ev)[-20000:]
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


# ---------------------------------------------------------------- stage 4: what conviction and the queue read
CONTEXT_DAYS = 90       # signals this recent count for conviction
_CTX: dict = {}


def _load_ctx() -> tuple[dict, list]:
    key = tuple((p.stat().st_mtime if p.exists() else 0) for p in (STATE, SIGNALS))
    if _CTX.get("key") != key:
        st = json.loads(STATE.read_text()).get("items", {}) if STATE.exists() else {}
        sg = json.loads(SIGNALS.read_text()).get("signals", []) if SIGNALS.exists() else []
        by: dict = {}
        for x in sg:
            by.setdefault(x.get("sym"), []).append(x)
        _CTX.update({"key": key, "items": st, "signals": by})
    return _CTX["items"], _CTX["signals"]


def context(sym: str, today: date) -> dict:
    """The ledger as conviction sees it: {"items": {id: state}, "signals": [last CONTEXT_DAYS], "cred": {pct, n} | None}.
    Credibility is size-weighted (owner, 27 Nov 2026): each resolved verified target counts 1.0 when material, 0.5 when not;
    beat / met = delivered, missed = not."""
    items, sigs = _load_ctx()
    mine = {k: v for k, v in items.items() if v.get("sym") == sym}
    cut = str(today - timedelta(days=CONTEXT_DAYS))
    rec = [x for x in sigs.get(sym, []) if x.get("date", "") >= cut]
    pts = w = 0.0
    n = 0
    for v in mine.values():
        o = v.get("outcome")
        if o in ("beat", "met", "missed") and v.get("src") == "narrativ":
            wt = 1.0 if v.get("material") == 1 else 0.5
            pts += wt * (o != "missed")
            w += wt
            n += 1
    return {"items": mine, "signals": rec, "cred": {"pct": round(pts / w * 100), "n": n} if n >= 2 and w else None}
