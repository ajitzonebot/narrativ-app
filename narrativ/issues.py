"""Data issues registry (the loop's error log): wrong numbers found by Claude's audits, quote-verified.
docs/data/data_issues.json keeps every issue with status: open -> fixed (the pipeline now matches the filed value)
or wontfix (set by hand). Systemic issues (a parser or rule bug) are fixed once in code for every stock; stock issues
are one company's filing quirk."""
import hashlib
import json
from pathlib import Path

OUT = Path("docs/data/data_issues.json")


def _id(sym, f):
    return hashlib.sha1(f"{sym}|{f.get('field')}|{f.get('found_value')}".encode()).hexdigest()[:10]


def scale_id(sym: str, quarter: str) -> str:
    return hashlib.sha1(f"{sym}|scale|{quarter}".encode()).hexdigest()[:10]


def _log_owners(reg: dict, sym: str, e: dict, today) -> str:
    """Owners' profit far from total profit with a small minority share (metrics.owners_guard): rebuilt from total profit
    (or rescaled by an exact power of ten), so the issue stays "corrected" until the filing reads right."""
    i = scale_id(sym, f"{e['quarter']}|owners")
    r = reg.get(i) or {"symbol": sym, "kind": "owners", "field": f"pat_owners {e['quarter']}", "scope": "stock",
                       "found_value": None, "first_seen": str(today), "times_seen": 0}
    r.update({"status": "corrected", "app": f"owners' profit ₹{e['owners_cr']:,.2f} cr as filed",
              "found": f"total profit ₹{e['pat_cr']:,.2f} cr, minority ₹{e['minority_cr']:,.2f} cr; used ₹{e['used_cr']:,.2f} cr",
              "cause": f"owners' profit mis-tagged ({e['fix']}): {e['why']}", "source": e.get("url"), "last_seen": str(today)})
    r["times_seen"] = r.get("times_seen", 0) + (0 if r.get("last_seen_run") == str(today) else 1)
    r["last_seen_run"] = str(today)
    r.setdefault("corrected_on", str(today))
    reg[i] = r
    return i


def log_scale(reg: dict, scale: dict, today) -> None:
    """Unit errors found by metrics.scale_guard (no audit needed: the neighbouring quarters show them). {symbol: [events]}
    covers every stock evaluated this run, so an issue it no longer reports (the company refiled, or the quarter rolled out
    of the series) is closed as fixed. Excluded quarters stay "open" (a number is missing until the filing is fixed);
    rescaled ones are "corrected" (a filer's mis-declared unit, confirmed by paid-up capital or declared rounding).
    Scope is "stock": the filing is wrong, not the parser (the XBRL is internally consistent with its declared unit)."""
    seen = set()
    for sym, evs in scale.items():
        for e in evs or []:
            if e.get("kind") == "owners":
                seen.add(_log_owners(reg, sym, e, today))
                continue
            i = scale_id(sym, e["quarter"])
            seen.add(i)
            st = "corrected" if e["action"] == "corrected" else "open"
            r = reg.get(i) or {"symbol": sym, "kind": "scale", "field": f"quarter {e['quarter']}", "scope": "stock",
                               "found_value": None, "first_seen": str(today), "times_seen": 0}
            cause = f"unit error, amounts ×{e['factor']:g}" if st == "corrected" else "likely unit error, quarter left out of metrics"
            r.update({"status": st, "app": f"revenue ₹{e['rev_cr']:,.2f} cr as filed",
                      "found": f"neighbouring quarters ≈ ₹{e['neighbour_rev_cr']:,.2f} cr", "cause": f"{cause}: {e['why']}",
                      "source": e.get("url"), "last_seen": str(today)})
            r["times_seen"] = r.get("times_seen", 0) + (0 if r.get("last_seen_run") == str(today) else 1)
            r["last_seen_run"] = str(today)
            if st == "corrected":
                r.setdefault("corrected_on", str(today))
            reg[i] = r
    for i, r in reg.items():
        if r.get("kind") in ("scale", "owners") and r.get("symbol") in scale and i not in seen and r.get("status") in ("open", "corrected"):
            r.update({"status": "fixed", "fixed_on": str(today)})


def update(theses: dict, mx: dict, val, today, corrected: dict | None = None, scale: dict | None = None) -> dict:
    old = json.loads(OUT.read_text()) if OUT.exists() else {"issues": {}}
    reg = old.get("issues", {})
    if scale is not None:
        log_scale(reg, scale, today)
    for sym, th in theses.items():
        for f in th.get("data_issues") or []:
            i = _id(sym, f)
            r = reg.get(i) or {"symbol": sym, **f, "first_seen": str(today), "status": "open", "times_seen": 0}
            r["last_seen"] = str(today)
            r["times_seen"] = r.get("times_seen", 0) + (0 if r.get("last_seen_run") == str(today) else 1)
            r["last_seen_run"] = str(today)
            reg[i] = r
    done = {a["id"] for v in (corrected or {}).values() for a in v}
    for i, r in reg.items():  # auto-close: the app's value now matches the filed value within 5%
        if i in done:  # matched only because the correction was applied: stays in force until the parser reads it right
            if r.get("status") == "open":
                r.update({"status": "corrected", "corrected_on": str(today)})
            continue
        if r.get("status") not in ("open", "corrected") or r.get("found_value") is None:
            continue
        M_ = mx.get(r["symbol"]) or {}
        fld = r.get("field") or ""
        if "." in fld:  # an input of a metric, e.g. "de.lease_liabilities_cr"
            m_, k_ = fld.split(".", 1)
            cur = ((M_.get(m_) or {}).get("in") or {}).get(k_) if isinstance(M_.get(m_), dict) else None
        else:
            cur = val(M_, fld)
        try:
            fv = float(r["found_value"])
        except (TypeError, ValueError):
            continue
        if cur is not None and (abs(cur - fv) <= 0.05 * max(abs(fv), 1e-9)):
            r.update({"status": "fixed", "fixed_on": str(today), "now": cur})
        elif cur is not None:
            r["now"] = cur
    opn = [r for r in reg.values() if r.get("status") == "open"]
    out = {"date": str(today), "open": len(opn), "open_systemic": sum(1 for r in opn if r.get("scope") == "systemic"),
           "corrected": sum(1 for r in reg.values() if r.get("status") == "corrected"),
           "fixed": sum(1 for r in reg.values() if r.get("status") == "fixed"), "issues": reg}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f"[issues] {out['open']} open ({out['open_systemic']} systemic), {out['fixed']} fixed")
    return out
