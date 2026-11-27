"""History backfill for the benchmark (owner, 27 Nov 2026): company-filed quarterly results older than the daily store.

The daily store (data/financials, narrativ/filings.py) keeps 16 quarters and cannot read NSE's pre-2022 "_WEB" XBRL files
(they reference OneD / FourD / OneI without defining them). This reads those older filings with
`parse_xbrl(declared=True)` (periods from the filing's own period facts; reproduces the normal parse exactly on files that
do define them) and stores them separately, so nothing the app reads changes:

  data/financials_hist/<SYMBOL>.json   same shape as data/financials: {"quarters": {qe: {basis: {...}}}, "basis", ...}

Same basis as the stock's daily record (one consistent series), same normalisation (filings._normalise), same filing
date per quarter (the benchmark uses only quarters filed on or before each date). Resumable: a stock with `done` is
skipped; `--minutes` caps one run. `merged(sym)` gives daily + history quarters for the benchmark.
python -m narrativ.histfin [--minutes 50] [--symbols A,B]
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from narrativ import config
from narrativ import filings as F

DIR = Path("data/financials_hist")
VERSION = 1


def _path(sym: str) -> Path:
    return DIR / f"{sym}.json"


def load(sym: str) -> dict:
    p = _path(sym)
    return json.loads(p.read_text()) if p.exists() else {}


def backfill(sym: str, ns: F.NSESession) -> dict:
    live = F.load(sym) or {}
    basis = live.get("basis")
    rec = load(sym) or {"symbol": sym, "quarters": {}}
    rows = F._listings(ns, sym[:-3]) or F._listings(ns, sym[:-3], index="sme")
    if not rows:
        rec.update({"status": "no NSE filings", "done": VERSION, "checked": datetime.now(timezone.utc).isoformat()})
        return rec
    if not basis:  # no daily record: the same rule as filings.update, from the latest quarter
        latest = max(r["qe"] for r in rows)
        basis = "Consolidated" if any(r["basis"] == "Consolidated" for r in rows if r["qe"] == latest) else "Standalone"
    have_live = set((live.get("quarters") or {}))
    for r in sorted(rows, key=lambda r: r["qe"], reverse=True):
        if r["basis"] != basis or r["qe"] in have_live:
            continue
        got = (rec["quarters"].get(r["qe"]) or {}).get(basis)
        if got and F.same_doc(got.get("url"), r["url"]):
            continue
        txt = ns.get(r["url"], as_json=False)
        time.sleep(config.FILINGS_SLEEP_SEC)
        if not txt:
            continue
        p = F.parse_xbrl(txt, declared=True)
        if not p or p.get("end") != r["qe"]:
            continue
        p = F._normalise(p)
        u = r["url"].upper()
        kind = "bank" if "BANKING" in u else "nbfc" if "NBFC" in u else "insurance" if "INSURANCE" in u else "general"
        p.update({"url": r["url"], "filed": r["filed"], "src": r["src"], "audited": r["audited"], "kind": kind,
                  "declared_ctx": '<xbrli:context id="OneD"' not in txt})
        rec["quarters"].setdefault(p["end"], {})[basis] = p
    rec["quarters"] = dict(sorted(rec["quarters"].items(), reverse=True))
    rec.update({"basis": basis, "status": "ok", "done": VERSION, "checked": datetime.now(timezone.utc).isoformat()})
    return rec


def merged(sym: str) -> dict:
    """Daily record with the older quarters added (daily wins for a quarter in both)."""
    live, hist = F.load(sym) or {}, load(sym)
    q = {**(hist.get("quarters") or {}), **(live.get("quarters") or {})}
    return {**hist, **live, "quarters": dict(sorted(q.items(), reverse=True))}


def run(symbols: list[str], minutes: float) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    ns, t0, n = F.NSESession(), time.time(), 0
    todo = [s for s in symbols if load(s).get("done") != VERSION]
    for s in todo:
        if time.time() - t0 > minutes * 60:
            break
        try:
            rec = backfill(s, ns)
        except Exception as e:  # noqa: BLE001
            print(f"[histfin] {s}: {e}", flush=True)
            continue
        _path(s).write_text(json.dumps(rec, separators=(",", ":")))
        n += 1
        if n % 25 == 0:
            print(f"[histfin] {n}/{len(todo)} stocks, {ns.calls} requests, {time.time() - t0:.0f}s", flush=True)
    left = len(todo) - n
    print(f"[histfin] {n} stocks this run, {left} left, {ns.calls} requests", flush=True)
    return {"done_now": n, "left": left, "requests": ns.calls}


if __name__ == "__main__":
    args = sys.argv[1:]
    mins = float(args[args.index("--minutes") + 1]) if "--minutes" in args else 50
    if "--symbols" in args:
        syms = args[args.index("--symbols") + 1].split(",")
    else:
        syms = [r["s"] for r in json.loads(Path("docs/data/picks.json").read_text())["picks"] if r["s"].endswith(".NS")]
    run(syms, mins)
