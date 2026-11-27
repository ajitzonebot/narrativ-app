"""History backfill for the benchmark (owner, 27 Nov 2026): company-filed quarterly results older than the daily store.

The daily store (data/financials, narrativ/filings.py) keeps 16 quarters and cannot read NSE's pre-2022 "_WEB" XBRL files
(they reference OneD / FourD / OneI without defining them). This reads those older filings with
`parse_xbrl(declared=True)` (periods from the filing's own period facts; reproduces the normal parse exactly on files that
do define them) and stores them separately, so nothing the app reads changes:

  data/financials_hist/<SYMBOL>.json   same shape as data/financials: {"quarters": {qe: {basis: {...}}}, "basis", ...}

Same basis as the stock's daily record (one consistent series), same normalisation (filings._normalise), same filing
date per quarter (the benchmark uses only quarters filed on or before each date). Resumable: a stock with `done` is
skipped; `--minutes` caps one run. `merged(sym)` gives daily + history quarters for the benchmark.
python -m narrativ.histfin [--minutes 50] [--symbols A,B]   (default: the symbols in data/benchmark/histfin_symbols.json)
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
FROM_QE = "2019-03-31"  # owner, 27 Nov 2026 (cut the load): quarters from Mar 2019, 3 years of history for 2022-2024 starts
MAX_TRIES = 3  # a stock whose listing or files keep failing is closed after 3 runs (status says what is missing)
STOP_EMPTY = 10  # this many listings in a row empty or failed: NSE is likely refusing us, stop the chunk
SCOPE = Path("data/benchmark/histfin_symbols.json")  # liquid NSE stocks (Rs 1 crore a day at some point in 2020-2024)


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
    rec["tries"] = rec.get("tries", 0) + 1
    if not rows:
        # an empty listing is final only when the daily store also found none; otherwise NSE may be refusing us: retry later
        final = live.get("status") == "no NSE filings" or rec["tries"] >= MAX_TRIES
        rec.update({"status": "no NSE filings" if final else "listing empty (retry)", "done": VERSION if final else None,
                    "checked": datetime.now(timezone.utc).isoformat()})
        return rec
    if not basis:  # no daily record: the same rule as filings.update, from the latest quarter
        latest = max(r["qe"] for r in rows)
        basis = "Consolidated" if any(r["basis"] == "Consolidated" for r in rows if r["qe"] == latest) else "Standalone"
    have_live = set((live.get("quarters") or {}))
    missed = 0
    for r in sorted(rows, key=lambda r: r["qe"], reverse=True):
        if r["basis"] != basis or r["qe"] in have_live or r["qe"] < FROM_QE:
            continue
        got = (rec["quarters"].get(r["qe"]) or {}).get(basis)
        if got and F.same_doc(got.get("url"), r["url"]):
            continue
        txt = ns.get(r["url"], as_json=False)
        time.sleep(config.FILINGS_SLEEP_SEC)
        if not txt:
            missed += 1  # download failed: not done, the next run retries (files already read are skipped)
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
    final = not missed or rec["tries"] >= MAX_TRIES
    rec.update({"basis": basis, "status": "ok" if not missed else f"{missed} file(s) not downloaded",
                "done": VERSION if final else None, "checked": datetime.now(timezone.utc).isoformat()})
    return rec


def merged(sym: str) -> dict:
    """Daily record with the older quarters added (daily wins for a quarter in both)."""
    live, hist = F.load(sym) or {}, load(sym)
    q = {**(hist.get("quarters") or {}), **(live.get("quarters") or {})}
    return {**hist, **live, "quarters": dict(sorted(q.items(), reverse=True))}


def _done(rec: dict) -> bool:
    """Closed for this version. A "no NSE filings" record without a try count came from the first run (27 Nov 2026), which
    took an empty listing as final while NSE was refusing requests (65 of 68, e.g. ACE, ALEMBICLTD): read again."""
    return rec.get("done") == VERSION and (rec.get("status") != "no NSE filings" or "tries" in rec)


def run(symbols: list[str], minutes: float) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    ns, t0, n = F.NSESession(), time.time(), 0
    todo = [s for s in symbols if not _done(load(s))]
    empty = 0
    for s in todo:
        if time.time() - t0 > minutes * 60:
            break
        try:
            rec = backfill(s, ns)
        except Exception as e:  # noqa: BLE001
            print(f"[histfin] {s}: {e}", flush=True)
            empty += 1
            continue
        _path(s).write_text(json.dumps(rec, separators=(",", ":")))
        empty = empty + 1 if rec.get("status") == "listing empty (retry)" else 0
        if empty >= STOP_EMPTY:
            print(f"[histfin] {empty} empty listings in a row: NSE is likely refusing requests; stopping this chunk", flush=True)
            break
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
    elif SCOPE.exists():
        syms = json.loads(SCOPE.read_text())["symbols"]
    else:
        syms = [r["s"] for r in json.loads(Path("docs/data/picks.json").read_text())["picks"] if r["s"].endswith(".NS")]
    run(syms, mins)
