"""BSE results summary for companies with no NSE results filings (BSE-only listings, and NSE-traded companies that file
only on BSE). Source: BSE's results snapshot via the `bse` library (resultsSnapshot): revenue, net profit and EPS for the
latest quarter, the quarter before and the last financial year, in ₹ crore. Quarters are kept as they are seen, so the
history grows each quarter. Balance-sheet items are not in this source: they stay on Yahoo statements, labelled.
Store: data/bse_results.json (in git)."""
import json
import re
import time
from datetime import date
from pathlib import Path

STORE = Path("data/bse_results.json")
KEEP_Q = 12
MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
QEND = {3: 31, 6: 30, 9: 30, 12: 31}


def _period(p: str) -> tuple[str, str] | None:
    """'Sep-26' -> ('q', '2026-09-30'); 'FY25-26' -> ('fy', '2026-03-31')."""
    m = re.fullmatch(r"([A-Z][a-z]{2})-(\d{2})", p.strip())
    if m and MON.get(m.group(1)) in QEND:
        mo = MON[m.group(1)]
        return "q", date(2000 + int(m.group(2)), mo, QEND[mo]).isoformat()
    m = re.fullmatch(r"FY(\d{2})-(\d{2})", p.strip())
    if m:
        return "fy", date(2000 + int(m.group(2)), 3, 31).isoformat()
    return None


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse(snap: dict) -> dict:
    """{'q': {date: {rev, pat, eps}}, 'fy': {...}} in ₹ crore from one resultsSnapshot response."""
    t = (snap or {}).get("results_in_crores") or {}
    fields, data = t.get("fields") or [], t.get("data") or []
    rows = {(r[0] or "").strip().lower(): r for r in data if r}
    out = {"q": {}, "fy": {}}
    for i, p in enumerate(fields[1:], 1):
        k = _period(p)
        if not k:
            continue
        rec = {"rev": _num((rows.get("revenue") or [None] * 9)[i]), "pat": _num((rows.get("net profit") or [None] * 9)[i]),
               "eps": _num((rows.get("eps") or [None] * 9)[i])}
        if rec["rev"] is not None or rec["pat"] is not None:
            out[k[0]][k[1]] = rec
    links = (snap or {}).get("period_links") or []
    out["url"] = (links[0].get("LLQ") if links else None)
    return out


def load() -> dict:
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def due(rec: dict | None, today: date, expected_q: str) -> bool:
    if not rec or not rec.get("checked"):
        return True
    age = (today - date.fromisoformat(rec["checked"])).days
    latest = max(rec.get("q") or {"": 0})
    return (latest < expected_q and age >= 7) or age >= 45


def refresh(codes: dict[str, str], today: date, expected_q: str, max_minutes: float = 4) -> dict:
    """codes: {symbol: BSE scrip code} for the companies to cover."""
    st = load()
    todo = [s for s in codes if due(st.get(s), today, expected_q)]
    t0, got, fail = time.time(), 0, 0
    if todo:
        try:
            from bse import BSE
            with BSE(download_folder=Path("data/exchange_tmp")) as b:
                for s in todo:
                    if time.time() - t0 > max_minutes * 60:
                        break
                    rec = st.setdefault(s, {"q": {}, "fy": {}})
                    try:
                        p = parse(b.resultsSnapshot(str(codes[s])))
                    except Exception as e:  # noqa: BLE001
                        fail += 1
                        if fail <= 3:
                            print(f"[bseres] {s}: {e}")
                        continue
                    rec["q"].update(p["q"])
                    rec["fy"].update(p["fy"])
                    rec["q"] = dict(sorted(rec["q"].items(), reverse=True)[:KEEP_Q])
                    rec["url"] = p.get("url") or rec.get("url")
                    rec["code"] = str(codes[s])
                    rec["checked"] = today.isoformat()
                    got += 1
        except Exception as e:  # noqa: BLE001
            print(f"[bseres] BSE session failed: {e}")
        STORE.write_text(json.dumps(st, indent=0, sort_keys=True))
    have = sum(1 for s in codes if (st.get(s) or {}).get("q"))
    print(f"[bseres] {got} refreshed of {len(todo)} due" + (f", {fail} not answered" if fail else "") + f", {time.time() - t0:.0f}s; results for {have} of {len(codes)} companies")
    return st
