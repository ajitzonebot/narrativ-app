"""Live feed for the research runs (owner, 28 Nov 2026: "feed the claude dynamically instead of set packets each run ... in a
day if we are done with top priority items, then we can feed the unread stories").

A run asks for one item at a time instead of reading queue.json once:

    python3 -m narrativ.next --task review|catalyst            # the next item, claimed for this run (prints one JSON line)
    python3 -m narrativ.next --task review|catalyst --peek 12  # the first 12 waiting, nothing claimed (work check)

One ladder over queue.json (today's 60) and backlog.json (items past the cap, then never-studied stocks that pass every check):
the daily run's groups in order (narrativ/requeue.py POS), with first studies after old-research rechecks and before the
forward-driver hunts on stocks without a driver. A review run takes full reviews and red flags first; a catalyst run never
takes them (only the review task sets `audit`). Skipped: a stock already worked today (theses.json `updated`), a first study
of a stock researched since, a stock any run took in the last config.CLAIM_MINUTES (docs/data/claims/<run>.json, one file per
run so two runs never conflict on a rebase; committed with the research), and first studies or driver hunts whose pack found no readable call transcript or presentation.
"""
import argparse
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config
from .requeue import POS, pos_group

OUT = Path("docs/data")
IST = timezone(timedelta(hours=5, minutes=30))
REVIEW_TASKS = ("review", "review_flag", "audit")
HUNTS = ("near", "no_driver")  # forward-driver hunts: nothing to find without a readable call or presentation
# serve order: the daily run's slots, except old-research rechecks and first studies come before the no-driver hunts
SLOT = {**{g: float(v[0]) for g, v in POS.items()}, "stale": 17.6, "first_study": 17.8}
UNKNOWN_SLOT = 17.5
STALE_DAYS = 4


def _load(p: Path, default):
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except ValueError:
        return default


def _group(it: dict) -> str | None:
    return "first_study" if it.get("pos") == "first_study" else pos_group(it)


def docs_ready(pack: dict | None) -> bool | None:
    """True / False when the daily run looked for documents; None when it did not (old pack, light pack, time budget)."""
    if not pack or pack.get("light") or "docs_checked" not in pack or not pack.get("docs_checked"):
        return None
    return (pack.get("readable_docs") or 0) > 0


def ladder(queue: dict, backlog: dict, theses: dict, claims: dict, pack_of, task: str, today: str, now: datetime,
           blocked: set | None = None) -> tuple[list, Counter]:
    """Items this run may take, best first, and why the others were skipped."""
    skipped: Counter = Counter()
    qd = str(queue.get("date") or "")
    if not qd or (date.fromisoformat(today) - date.fromisoformat(qd[:10])).days > STALE_DAYS:
        skipped["queue older than 4 days"] += len(queue.get("items") or [])
        return [], skipped
    items = list(queue.get("items") or [])
    nq = len(items)
    if str(backlog.get("date") or "") == qd:
        items += backlog.get("items") or []
    cut = now - timedelta(minutes=config.CLAIM_MINUTES)
    taken = {s for s, c in (claims.get("items") or {}).items() if str(c.get("at") or "") >= cut.isoformat(timespec="minutes")}
    out, seen = [], set()
    for i, it in enumerate(items):
        s, t, g = it.get("symbol"), it.get("task"), _group(it)
        if not s or (s, t) in seen:
            continue
        seen.add((s, t))
        if task == "catalyst" and t in REVIEW_TASKS:
            continue
        th = theses.get(s) or {}
        u = str(th.get("updated") or "")[:10]
        if u == today or (i >= nq and u >= qd[:10]):  # backlog.json is not pruned between daily runs (queue.json is)
            skipped["worked today or since the daily run"] += 1
            continue
        if g == "first_study" and s in theses:
            skipped["studied since the daily run"] += 1
            continue
        if s in (blocked or ()):  # narrativ/blocked.py: blocked twice in 3 days; a GitHub issue "blocked: SYMBOL" is open
            skipped["blocked by earlier runs (see the GitHub issue)"] += 1
            continue
        if s in taken:
            skipped["taken by a run in the last %d minutes" % config.CLAIM_MINUTES] += 1
            continue
        if g == "first_study" or (t == "enrich" and g in HUNTS):
            ok = docs_ready(pack_of(s))
            if ok is False or (ok is None and g == "first_study"):
                skipped["waiting for a readable call transcript or presentation"] += 1
                continue
        lead = 0 if task == "review" and t in REVIEW_TASKS else 1
        out.append((lead, SLOT.get(g, UNKNOWN_SLOT), i, it))
    out.sort(key=lambda x: x[:3])
    return [x[3] for x in out], skipped


CLAIMS = OUT / "claims"


def load_claims(now: datetime) -> dict:
    """Every run's claims of the last CLAIM_MINUTES, merged (docs/data/claims/*.json; the old single file too)."""
    cut = (now - timedelta(minutes=config.CLAIM_MINUTES)).isoformat(timespec="minutes")
    out = {}
    for f in sorted(CLAIMS.glob("*.json")) + [OUT / "claims.json"]:
        for s, c in (_load(f, {}).get("items") or {}).items():
            if str(c.get("at") or "") >= cut and str(c.get("at") or "") >= str((out.get(s) or {}).get("at") or ""):
                out[s] = c
    return {"items": out}


def run_file(task: str, run: str | None, now: datetime) -> Path:
    """This run's claims file: --run (the run's start time) names it; without it, the task and today's date."""
    tag = re.sub(r"[^0-9A-Za-z]+", "-", run or now.strftime("%Y-%m-%d")).strip("-")
    return CLAIMS / f"{task}-{tag}.json"


def claim(claims: dict, sym: str, task: str, now: datetime) -> dict:
    cut = (now - timedelta(minutes=config.CLAIM_MINUTES)).isoformat(timespec="minutes")
    keep = {s: c for s, c in (claims.get("items") or {}).items() if str(c.get("at") or "") >= cut}
    keep[sym] = {"run": task, "at": now.isoformat(timespec="minutes")}
    return {"items": keep}


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task", choices=("review", "catalyst"), required=True)
    ap.add_argument("--peek", type=int, default=0, help="list the first N waiting items; claim nothing")
    ap.add_argument("--run", help="this run's start time (ISO), names its claims file docs/data/claims/<task>-<run>.json")
    a = ap.parse_args(argv)
    now = datetime.now(IST)
    today = str(now.date())
    queue, backlog = _load(OUT / "queue.json", {}), _load(OUT / "backlog.json", {})
    theses, claims = _load(OUT / "theses.json", {}), load_claims(now)

    def pack_of(s):
        return _load(OUT / "packs" / f"{s}.json", None)
    from .blocked import live
    items, skipped = ladder(queue, backlog, theses, claims, pack_of, a.task, today, now, live(theses, now.date()))
    first = [x for x in backlog.get("items") or [] if x.get("pos") == "first_study"]
    stats = {"queue_date": queue.get("date"), "waiting": len(items), "skipped": dict(skipped),
             "first_studies_waiting": sum(1 for x in items if x.get("pos") == "first_study"), "first_studies_listed": len(first)}
    if a.peek:
        r = {**stats, "next": [{"task": x.get("task"), "symbol": x.get("symbol"), "group": _group(x)} for x in items[:a.peek]]}
    elif not items:
        r = {**stats, "none": True}
    else:
        it = items[0]
        f = run_file(a.task, a.run, now)
        CLAIMS.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(claim(_load(f, {}), it["symbol"], a.task, now), indent=1))
        r = {**stats, "waiting": len(items) - 1, "item": {**it, "group": _group(it)}, "pack": f"docs/data/packs/{it['symbol']}.json"}
    print(json.dumps(r, ensure_ascii=False, default=str))
    return r


if __name__ == "__main__":
    main()
