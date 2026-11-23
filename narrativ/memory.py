"""Per-stock memory (data/stocks/<SYM>.json) and checkpoint engine.

Single writer rule: this module (daily Actions run) owns data/stocks/*.json.
Claude research owns docs/data/theses.json; its checkpoints and resolutions are merged in here.
"""
import json
from datetime import date, timedelta
from pathlib import Path

from . import config
from .util import write_if_changed

DIR = Path("docs/data/stocks")  # served by Pages so the app can read history


def _path(sym: str) -> Path:
    return DIR / f"{sym.replace('/', '_')}.json"


def load(sym: str) -> dict | None:
    p = _path(sym)
    return json.loads(p.read_text()) if p.exists() else None


def save(rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    write_if_changed(_path(rec["symbol"]), json.dumps(rec, indent=1, ensure_ascii=False))


def all_records() -> dict[str, dict]:
    return {json.loads(p.read_text())["symbol"]: json.loads(p.read_text()) for p in DIR.glob("*.json")} if DIR.exists() else {}


# ---------- quarter / SEBI calendar helpers ----------
def _quarter_ends_around(today: date) -> list[date]:
    out = []
    for y in (today.year - 1, today.year, today.year + 1):
        out += [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]
    return sorted(out)


def results_deadline(qe: date) -> date:
    # SEBI LODR Reg 33: 45 days after quarter end, 60 days for the March (annual) quarter
    return qe + timedelta(days=60 if qe.month == 3 else 45)


def auto_checkpoints(last_quarter: str | None, next_earnings: str | None, today: date, source: str | None = None) -> list[dict]:
    qes = _quarter_ends_around(today)
    last_q = date.fromisoformat(last_quarter) if last_quarter else None
    # Results: earliest quarter end not yet in data whose deadline is not long past
    cps = []
    for qe in qes:
        if last_q and qe <= last_q:
            continue
        if results_deadline(qe) + timedelta(days=config.CHECKPOINT_EXPIRE_DAYS) < today:
            continue
        due = results_deadline(qe)
        if next_earnings:
            ne = date.fromisoformat(next_earnings[:10])
            if qe < ne <= due + timedelta(days=15):
                due = ne
        cps.append({"id": f"results-{qe}", "type": "results", "due": str(due),
                    "what": f"Quarterly results for quarter ending {qe}",
                    "expected": "Check revenue growth, margins and guidance delivery vs thesis",
                    "source": source if (source and due != results_deadline(qe)) else "SEBI deadline" if due == results_deadline(qe) else "announced date"})
        break
    # Shareholding pattern: within 21 days of quarter end
    for qe in qes:
        d = qe + timedelta(days=21)
        if d >= today - timedelta(days=7) and qe < today + timedelta(days=95):
            cps.append({"id": f"shp-{qe}", "type": "shareholding", "due": str(d),
                        "what": f"Shareholding pattern for quarter ending {qe}",
                        "expected": "Promoter stake, pledge, FII/DII change", "source": "SEBI deadline"})
            break
    return cps


def update_checkpoints(rec: dict, new_cps: list[dict], resolved: dict, today: date) -> list[dict]:
    """Merge new checkpoints, apply Claude resolutions, set statuses. Returns newly-due checkpoints."""
    cps = {c["id"]: c for c in rec.get("checkpoints", [])}
    for c in new_cps:
        if c["id"] not in cps:
            cps[c["id"]] = {**c, "status": "open", "created": str(today)}
        elif cps[c["id"]]["status"] in ("open", "due"):
            cps[c["id"]].update({k: c[k] for k in ("due", "what", "expected", "source") if k in c})
    newly_due = []
    for cid, c in cps.items():
        if cid in resolved and c["status"] in ("open", "due", "expired") or (cid in resolved and c["status"] != resolved[cid].get("status")):
            r = resolved[cid]
            c.update({"status": r.get("status", "noted"), "outcome": r.get("outcome"),
                      "evidence": r.get("source"), "resolved": r.get("date", str(today))})
            continue
        if c["status"] == "open" and date.fromisoformat(c["due"]) <= today:
            c["status"] = "due"
            newly_due.append(c)
        if c["status"] == "due" and date.fromisoformat(c["due"]) + timedelta(days=config.CHECKPOINT_EXPIRE_DAYS) < today:
            c["status"] = "expired"
    rec["checkpoints"] = sorted(cps.values(), key=lambda c: c["due"])
    return newly_due


def touch(rec: dict | None, sym: str, name: str, today: date) -> dict:
    if rec is None:
        rec = {"symbol": sym, "name": name, "first_seen": str(today), "snapshots": [],
               "checkpoints": [], "thesis_history": [], "status": "active"}
    rec["name"] = name
    return rec


def snapshot(rec: dict, snap: dict, today: date) -> None:
    snaps = [s for s in rec["snapshots"] if s["d"] != str(today)]
    snaps.append({"d": str(today), **snap})
    rec["snapshots"] = snaps[-config.SNAPSHOTS_KEEP:]


def record_thesis(rec: dict, th: dict) -> None:
    """Append a thesis version when Claude's thesis changes."""
    if not th:
        return
    hist = rec.setdefault("thesis_history", [])
    key = (th.get("updated"), th.get("thesis"), (th.get("scan") or th.get("scan_raw") or {}).get("date"))
    if hist and (hist[-1].get("updated"), hist[-1].get("thesis"), hist[-1].get("scan_date")) == key:
        return
    sc = th.get("scan") or th.get("scan_raw") or {}
    hist.append({k: th.get(k) for k in ("updated", "quarter", "thesis", "outlook_score", "sentiment_score",
                                          "sentiment", "guidance", "tone")} | {"scan_date": sc.get("date"), "scan_label": sc.get("label")})


def thesis_health(rec: dict) -> str:
    missed = sum(1 for c in rec.get("checkpoints", []) if c["status"] == "missed")
    met = sum(1 for c in rec.get("checkpoints", []) if c["status"] == "met")
    if missed >= 2:
        return "broken"
    if missed == 1:
        return "under review"
    return "on track" if met else "untested"


def rename(moved: dict[str, str]) -> None:
    """Move a stock's memory to its current symbol (e.g. a BSE-only listing that moved to NSE); history is kept."""
    for old, new in moved.items():
        rec = load(old)
        if not rec:
            continue
        cur = load(new)
        if cur:  # merge: keep the longer history
            for k in ("events", "verdicts", "snapshots", "checkpoints"):
                if isinstance(rec.get(k), list) and isinstance(cur.get(k), list):
                    seen = {json.dumps(x, sort_keys=True) for x in cur[k]}
                    cur[k] += [x for x in rec[k] if json.dumps(x, sort_keys=True) not in seen]
            rec = {**rec, **cur}
        rec["symbol"] = new
        rec.setdefault("aliases", []).append(old)
        save(rec)
        _path(old).unlink(missing_ok=True)
