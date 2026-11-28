"""Study coverage and yield (owner, 28 Nov 2026, live feed phase 2: "show yield, not just activity").

data/study_log.json: {symbol: date first studied}. A stock enters on the first daily run that finds it in theses.json (any
research: a quick check, an enrich or a review). Stocks already studied when the log started are kept with "" (date not
known) and left out of the weekly numbers. stats() feeds picks.json funnel.study for the app's Knockout Funnel:
  pool      stocks that pass every level and have enough filed data to score (the never-studied ones are first studies)
  studied   how many of the pool have any research
  week      first studies in the last 7 days -> how many the quick check found no story in -> how many are Buy candidates
            now -> how many are verified Buys now
  start     the same since the log started (date of the first dated entry)
"""
import json
from datetime import date
from pathlib import Path

LOG = Path("data/study_log.json")
BUY = ("Buy", "Strong Buy")


def update(theses: dict, today: date, path: Path = LOG) -> dict:
    """Add today's newly studied stocks; returns the log."""
    try:
        log = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        log = {}
    if not log:  # first run: everything researched so far has an unknown first-study date
        log = {s: "" for s in theses}
    for s in theses:
        log.setdefault(s, str(today))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=0, sort_keys=True))
    return log


def _yield(syms: list[str], theses: dict, dec: dict) -> dict:
    d = {s: dec.get(s) or {} for s in syms}
    return {"studied": len(syms),
            "no_story": sum(1 for s in syms if ((theses.get(s) or {}).get("triage") or {}).get("outcome") == "no_story"),
            "candidates": sum(1 for s in syms if d[s].get("candidate") in BUY or d[s].get("d") in BUY),
            "verified": sum(1 for s in syms if d[s].get("d") in BUY and d[s].get("verified") == "pass" and not d[s].get("incomplete"))}


def stats(log: dict, theses: dict, today: date, pool: list[str], dec: dict) -> dict:
    dated = {s: v for s, v in log.items() if v}
    week = sorted(s for s, v in dated.items() if (today - date.fromisoformat(v)).days < 7)
    ps = set(pool)
    return {"pool": len(ps), "studied": sum(1 for s in ps if s in theses), "week": _yield(week, theses, dec),
            "start": {"date": min(dated.values()) if dated else None, **_yield(sorted(dated), theses, dec)}}
