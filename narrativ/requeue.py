"""Light re-sort of the research queue between daily runs (owner, 27 Nov 2026: "yes build the light re-sort").

Runs every 30 minutes with the research publish (republish.yml), also when no research changed:
  1. drops items already done (republish.prune_queue by run time, prune_done_research by content);
  2. puts at the top, in this order: the owner's open review requests from the app ("scan: SYMBOL" issues) not yet worked
     on, Buys whose research is incomplete (RULES.md R8: no verified badge) and Buy candidates waiting for a review;
  3. keeps the rest in the daily run's order and the queue at its cap (config.RESEARCH_PER_DAY), trimming from the end;
  4. writes each item's `why_pos` (its group, the groups around it and its place in the group; label_positions).
New items get a light pack (no document excerpts: those need the NSE fetches of the daily run); the evening run replaces
it with the full pack. The daily run still builds and sorts the whole queue.
"""
import json
from pathlib import Path

from . import config
from . import funnel as FN
from . import requests as scan_requests

OUT = Path("docs/data")
PACKS = OUT / "packs"
TOP_TASKS = ("requested", "complete", "candidate")

# Why an item sits where it does (owner, 28 Nov 2026: "explain why it's in the queue at that position"). The daily run
# (run.py, "Claude queue") adds items group by group in this order; a stock is queued once, in its first group. Each item
# carries its group as `pos` and a plain-words `why_pos` built from it. Groups on the same slot are added in one pass.
POS_SLOTS = ["your requests", "unfinished Buys", "new Buy candidates", "overdue kill switches on Buys and Holds",
             "Buys missing a dated trigger", "other overdue items", "bad news rechecks", "missed forward targets",
             "new transcripts", "quotes to re-source", "dead source links", "due checkpoints", "possible bad news",
             "new announcements and price falls", "forward-driver hunts close to a call", "missing outlook scans", "scan gaps",
             "red flag checks", "other forward-driver hunts", "old research with new filings"]
POS = {"requested": (0, "You asked for this review"),
       "complete": (1, "A Buy whose research is not complete: it stays unverified until the research is finished"),
       "candidate": (2, "Rules say {d}: a full review is needed before it is shown as buyable"),
       "overdue_top": (3, "A kill switch on a Buy or Hold is past its date"),
       "trigger": (4, "Scores say Buy but there is no dated trigger yet"),
       "overdue": (5, "Items past their due date and not resolved"),
       "bad_news": (6, "Bad news filed since the last research"),
       "target": (7, "A forward target went wrong since the last research"),
       "transcript": (8, "A new earnings call transcript is filed"),
       "resource": (9, "Quotes cite a transcript source that is no longer used"),
       "dead_link": (10, "A source link no longer opens"),
       "checkpoint": (11, "A checkpoint is due and a new document is filed"),
       "watch": (12, "Possible bad news filed since the last research"),
       "news": (13, "New announcement since the last research"),
       "shock": (13, "Sharp price fall with something new filed"),
       "near": (14, "Forward-driver hunt: one driver away from a Buy or Hold call"),
       "no_scan": (15, "The research has drivers but no outlook scan"),
       "gaps": (16, "Scan items lack a quote, source or due date"),
       "flag": (17, "Red flag in a filing's subject line"),
       "no_driver": (18, "Forward-driver hunt: no forward driver yet"),
       "stale": (19, f"Research older than {config.THESIS_STALE_DAYS} days and something new is filed")}
POS_RANKED = ("complete", "candidate", "trigger")  # ordered by readiness inside the group: say "N of M"
POS_BY_PRIORITY = ("checkpoint", "near", "no_scan", "no_driver")  # ordered by priority, highest first
_POS_PREFIX = (("rules say", None), ("overdue:", "overdue"), ("scores say buy but no dated trigger", "trigger"),
               ("bad news filed", "bad_news"), ("a material forward target", "target"), ("new transcript", "transcript"),
               ("source link no longer opens", "dead_link"), ("checkpoint due", "checkpoint"), ("possible bad news", "watch"),
               ("new announcement", "news"), ("price shock", "shock"), ("one forward driver away", "near"),
               ("outlook scan missing", "no_scan"), ("scan gaps", "gaps"), ("subject-line red flag", "flag"),
               ("no forward driver yet", "no_driver"), ("thesis older than", "stale"))


def pos_group(it: dict) -> str | None:
    """The item's queue group: `pos` when set, else read from the reason (queue files written before `pos` existed)."""
    if it.get("pos") in POS:
        return it["pos"]
    if it.get("requested"):
        return "requested"
    r = str(it.get("reason") or "").lower()
    if "alphastreet" in r:
        return "resource"
    for pre, g in _POS_PREFIX:
        if r.startswith(pre):
            return g or ("complete" if "not complete" in r else "candidate")
    return None


def why_pos(it: dict, rank: int | None = None, n: int | None = None) -> str | None:
    """Plain words: the item's group, the groups just ahead of and behind it, and its place inside the group."""
    g = pos_group(it)
    if g is None:
        return None
    slot, title = POS[g]
    d = "Strong Buy" if "rules say strong buy" in str(it.get("reason") or "").lower() else "Buy"
    out = [title.format(d=d)]
    if slot == 0:
        out.append("Your requests go first")
    elif slot == len(POS_SLOTS) - 1:
        out.append(f"Comes after {POS_SLOTS[slot - 1]}; last in the order")
    else:
        out.append(f"Comes after {POS_SLOTS[slot - 1]}, before {POS_SLOTS[slot + 1]}")
    if g in POS_RANKED and rank and n:
        out.append(f"{rank} of {n} in this group, " + ("those with a dated statement already found in the filings first, then "
                                                       if g == "trigger" else "") + "by how ready it is to buy")
    od = [x.get("days_late") for x in it.get("overdue") or [] if isinstance(x, dict) and x.get("days_late")]
    if g in ("overdue", "overdue_top") and od:
        out.append(f"Oldest item {max(od)} days late")
    if g in POS_BY_PRIORITY and isinstance(it.get("priority"), (int, float)):
        out.append(f"Priority {it['priority']:g}, highest first")
    return ". ".join(out) + "."


def label_positions(items: list[dict]) -> list[dict]:
    """Set `why_pos` on every item, in the order the items now stand (ranks inside the ranked groups are counted here)."""
    groups = [pos_group(x) for x in items]
    tot = {g: groups.count(g) for g in POS_RANKED}
    seen: dict[str, int] = {}
    for it, g in zip(items, groups):
        seen[g] = seen.get(g, 0) + 1
        w = why_pos(it, seen[g], tot.get(g)) if g in POS_RANKED else why_pos(it)
        if w:
            it["why_pos"] = w
    return items


def _fin(sym: str) -> dict:
    p = OUT / "fin" / f"{sym}.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        return {}


def light_pack(sym: str, item: dict, theses: dict, research: dict | None = None) -> dict:
    """What a review needs that is on disk now: the dossier, Claude's own checks, the R8 gaps and the decision so far."""
    from .packs import machine_checks
    d = _fin(sym)
    Mx, lender = d.get("metrics") or {}, (d.get("stock") or {}).get("lender")
    mc, need = machine_checks(Mx)
    ids = FN.audit_flag_items(Mx, lender)
    return {"symbol": sym, "task": item["task"], "light": True,
            "note": "Built between daily runs: no document excerpts yet. Read the dossier (docs/data/fin/<symbol>.json: events and "
                    "announcements list the latest results, transcript and presentation) and open those filings yourself. "
                    "The evening run replaces this with the full pack.",
            "dossier": f"docs/data/fin/{sym}.json", "machine_checked": mc,
            "claude_checks": need + [f"consistency flag [{i}]: {t} (explain it in audit.flag_notes with flag '{i}', note, quote, source)"
                                     for i, t in ids],
            "consistency_flag_ids": [{"flag": i, "text": t} for i, t in ids],
            "complete_record": FN.research_missing({**((research or {}).get(sym) or {}), "scan_raw": (theses.get(sym) or {}).get("scan")
                                                    or ((research or {}).get(sym) or {}).get("scan_raw")}) or ["complete: keep it current"],
            "decision_reasons": (d.get("decision") or {}).get("why"), "requested": bool(item.get("requested"))}


def resort(queue: dict, picks: dict, theses: dict, requests: list[dict], cap: int = config.RESEARCH_PER_DAY,
           today: str | None = None) -> list[str]:
    """Re-order `queue` in place; returns the symbols added (they need a light pack). Pure apart from the dossier reads."""
    from datetime import date, timedelta
    t0 = date.fromisoformat(today) if today else date.today()
    recent = str(t0 - timedelta(days=7))
    items = queue.get("items") or []
    rows = {p["s"]: p for p in picks.get("picks") or []}
    have = {(x.get("symbol"), x.get("task")) for x in items}
    top: dict[str, list] = {k: [] for k in TOP_TASKS}
    added = []
    for r in requests:  # the owner asked from the app; done once Claude worked on it since the request (requests.done)
        s = r["symbol"]
        got = scan_requests.reviewed_on(theses.get(s))
        if r.get("date") and got and got >= r["date"]:
            continue
        a = str(((theses.get(s) or {}).get("audit") or {}).get("date") or "")[:10]
        if not r.get("date") and a and a >= recent:  # a standing request (data/scan_requests.txt): as the daily run, 7 days
            continue
        it = next((x for x in items if x.get("symbol") == s and x.get("task") == "review"), None)
        if it is None:
            it = {"symbol": s, "name": (rows.get(s) or {}).get("n") or s, "task": "review",
                  "reason": f"requested ({r['via']}): full review (verify every number, connect the dots, verdict)"}
            added.append(s)
        it["requested"] = True
        top["requested"].append(it)
    for s, p in rows.items():
        if p.get("dc") in FN.BUY and p.get("ic"):  # R8: a Buy without the verified badge
            dec = _fin(s).get("decision") or {}
            gaps = dec.get("incomplete") or []
            it = next((x for x in items if x.get("symbol") == s and x.get("task") == "review"), None)
            if it is None and gaps:
                it = {"symbol": s, "name": p.get("n") or s, "task": "review", "complete": gaps,
                      "reason": f"rules say {p['dc']}: the review passed but the research is not complete (RULES.md R8; no verified "
                                "badge until it is): " + "; ".join(gaps[:6])}
                added.append(s)
            if it is not None:
                top["complete"].append(it)
        elif p.get("cand") in FN.BUY and p.get("vf") != "pass" and (s, "review") not in have:
            it = {"symbol": s, "name": p.get("n") or s, "task": "review",
                  "reason": f"rules say {p['cand']}: full review (verify every number, connect the dots, verdict) before it is shown as buyable"}
            added.append(s)
            top["candidate"].append(it)
    for k in ("complete", "candidate"):  # as the daily run: by how ready it is to buy (picks rk, 1 = readiest)
        top[k].sort(key=lambda it: (rows.get(it["symbol"]) or {}).get("rk") or 10 ** 9)
    seen, lead = set(), []
    for k in TOP_TASKS:
        for it in top[k]:
            key = (it["symbol"], it["task"])
            if key not in seen:
                seen.add(key)
                it["pos"] = k
                lead.append(it)
    rest = [x for x in items if (x.get("symbol"), x.get("task")) not in seen]
    out = lead + rest
    for drop in ("enrich", "recheck", None):  # over the cap: the last enrich items go first, then rechecks, then anything
        while len(out) > cap:
            i = next((k for k in range(len(out) - 1, -1, -1) if drop is None or out[k].get("task") == drop), None)
            if i is None:
                break
            out.pop(i)
    queue["items"] = label_positions(out)
    kept = {x["symbol"] for x in queue["items"]}
    return [s for s in dict.fromkeys(added) if s in kept]


def main() -> dict:
    qp, pp, tp, rp = OUT / "queue.json", OUT / "picks.json", OUT / "theses.json", OUT / "research.json"
    if not (qp.exists() and pp.exists() and tp.exists()):
        return {"changed": False}
    q, picks, theses = json.loads(qp.read_text()), json.loads(pp.read_text()), json.loads(tp.read_text())
    research = json.loads(rp.read_text()) if rp.exists() else {}
    before = json.dumps(q, sort_keys=True)
    from . import republish, runlog
    n = republish.prune_queue(runlog.completed(theses=research) or {}, picks.get("updated"), q)
    n += republish.prune_done_research(q, theses, research)
    reqs = scan_requests.load({p["s"] for p in picks.get("picks") or []})
    added = resort(q, picks, theses, reqs)
    PACKS.mkdir(parents=True, exist_ok=True)
    for s in added:
        pk = PACKS / f"{s}.json"
        if not pk.exists():
            it = next(x for x in q["items"] if x["symbol"] == s)
            pk.write_text(json.dumps(light_pack(s, it, theses, research), ensure_ascii=False, indent=0, default=str))
    changed = json.dumps(q, sort_keys=True) != before
    if changed:
        qp.write_text(json.dumps(q, indent=1, ensure_ascii=False))
    print(f"[requeue] {n} done item(s) dropped, {len(added)} added ({', '.join(added) or 'none'}), "
          f"top: {[x['symbol'] for x in q['items'][:5]]}")
    return {"changed": changed, "dropped": n, "added": added}


if __name__ == "__main__":
    import os
    r = main()
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"changed={'true' if r.get('changed') else 'false'}\n")
