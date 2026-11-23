"""Research-queue hygiene: what is overdue, what is missing, and whether a recheck has anything to check.

Overdue (past its due date, not resolved): kill switches and must-go-right items of the deep scan, promises still
pending / unverified, results checkpoints. These go first among the rechecks (a kill switch on a Buy or Hold above everything
except reviews). Gaps: kill switches / must-go-right items with no quote or source, or no due date: an `enrich` task fills them.
A recheck needs a reason to exist: a new document (narrativ.packs.new_documents) or an overdue item.
"""
from datetime import date

KIND_RANK = {"kill_switch": 0, "must_go_right": 1, "promise": 2, "results": 3}
KIND_NAME = {"kill_switch": "kill switch", "must_go_right": "must-go-right item", "promise": "promise", "results": "results checkpoint"}
OPEN_STATES = ("open", "due", "expired")  # checkpoint states that mean "nobody has checked it yet"


def _days(due, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(due)[:10])).days
    except (TypeError, ValueError):
        return None


def past_due(th: dict | None, mem_rec: dict | None, today: date) -> list[dict]:
    """Unresolved items whose due date has passed, hardest first (kill switch, must-go-right, promise, results checkpoint)."""
    th = th or {}
    resolved = th.get("resolved") or {}
    cps = {c.get("id"): c for c in (mem_rec or {}).get("checkpoints") or []}
    sc = th.get("scan") or th.get("scan_raw") or {}
    out = []
    for kind, key in (("kill_switch", "kill_switches"), ("must_go_right", "must_go_right")):
        for n, w in enumerate(sc.get(key) or []):
            due = w.get("due")
            late = _days(due, today) if due else None
            cid = f"{kind}-{n}-{due}"
            if late is None or late <= 0 or cid in resolved or (cps.get(cid) or {}).get("status", "open") not in OPEN_STATES:
                continue
            out.append({"kind": kind, "id": cid, "what": w.get("text", ""), "due": str(due)[:10], "days_late": late})
    for p in th.get("promises") or []:
        late = _days(p.get("due"), today) if p.get("due") else None
        if late and late > 0 and p.get("status") in ("unverified", "pending") and f"promise-{p.get('id')}" not in resolved:
            out.append({"kind": "promise", "id": f"promise-{p.get('id')}", "what": p.get("promise", ""), "due": str(p["due"])[:10], "days_late": late})
    for c in (mem_rec or {}).get("checkpoints") or []:
        late = _days(c.get("due"), today) if c.get("due") else None
        if c.get("type") == "results" and c.get("status") in ("open", "due") and late and late > 0 and c.get("id") not in resolved:
            out.append({"kind": "results", "id": c["id"], "what": c.get("what", ""), "due": c["due"], "days_late": late})
    return sorted(out, key=lambda x: (KIND_RANK[x["kind"]], -x["days_late"]))


def gaps(th: dict | None) -> list[dict]:
    """Kill switches / must-go-right items of the scan that have no quote or no source, or no due date."""
    sc = (th or {}).get("scan") or (th or {}).get("scan_raw") or {}
    out = []
    for kind, key in (("kill_switch", "kill_switches"), ("must_go_right", "must_go_right")):
        for n, w in enumerate(sc.get(key) or []):
            miss = [m for m, ok in (("quote", w.get("quote")), ("source", w.get("source")), ("due", w.get("due"))) if not ok]
            if miss:
                out.append({"kind": kind, "n": n, "what": w.get("text", ""), "missing": miss})
    return out


def sort_key(items: list[dict]) -> tuple:
    """Order of stocks with overdue items: hardest kind first, then more items, then longest overdue."""
    return (min(KIND_RANK[x["kind"]] for x in items), -len(items), -max(x["days_late"] for x in items))


def reason(items: list[dict]) -> str:
    n = {}
    for x in items:
        n[x["kind"]] = n.get(x["kind"], 0) + 1
    parts = ", ".join(f"{v} {KIND_NAME[k]}{'s' if v > 1 else ''}" for k, v in sorted(n.items(), key=lambda kv: KIND_RANK[kv[0]]))
    return f"overdue: {parts} past due and not resolved (oldest {max(x['days_late'] for x in items)} days late): find the filed evidence and resolve each"


def gap_reason(gp: list[dict]) -> str:
    q = sum(1 for g in gp if "quote" in g["missing"] or "source" in g["missing"])
    d = sum(1 for g in gp if "due" in g["missing"])
    bits = ([f"{q} without a quote or source"] if q else []) + ([f"{d} without a due date"] if d else [])
    return f"scan gaps: {' and '.join(bits)} among kill switches / must-go-right items: add the verbatim quote, its source link and the due date"


def plan(raw_theses: dict, mem: dict, today: date, new_docs_of, hold_buy: set, cooldown_days: int) -> dict:
    """-> {"overdue": [(sym, items, top)] in queue order, "gaps": [(sym, gaps)] in queue order}.
    `new_docs_of(sym)` -> the real documents filed since the thesis was last updated. An overdue stock researched within
    `cooldown_days` is skipped unless a new document arrived (the last run found nothing to resolve it with).
    Results checkpoints alone count only when the results document is out (a new document exists)."""
    od, gp = [], []
    for s, th in raw_theses.items():
        u = (th or {}).get("updated")
        recent = bool(u) and (today - date.fromisoformat(str(u)[:10])).days < cooldown_days
        nd = new_docs_of(s)
        items = [x for x in past_due(th, (mem or {}).get(s), today) if x["kind"] != "results" or nd]
        if items and (nd or not recent):
            od.append((s, items, s in hold_buy and any(x["kind"] == "kill_switch" for x in items)))
        g = gaps(th)
        if g and not recent:
            gp.append((s, g))
    od.sort(key=lambda r: (not r[2], sort_key(r[1])))
    gp.sort(key=lambda r: (-sum("quote" in g["missing"] for g in r[1]), -len(r[1])))
    return {"overdue": od, "gaps": gp}
