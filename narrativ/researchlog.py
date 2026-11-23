"""Per-stock history of Claude's work (shown as 'Claude's research' in the app): deep scans, research updates and full reviews.
theses.json keeps only the latest of each, so every run records any new (kind, date) here and the history builds up.
data/research_log.json: {symbol: [{"date", "kind", "text"}]} newest first."""
import json
from pathlib import Path

LOG = Path("data/research_log.json")


def _entries(th: dict) -> list[dict]:
    out = []
    sc = th.get("scan") or th.get("scan_raw") or {}
    if sc.get("date"):
        src = th.get("sources") or []
        bits = [x for x in (th.get("quarter"), th.get("source_type")) if x]
        out.append({"date": sc["date"][:10], "kind": "Deep scan",
                    "text": " ".join(bits) + (f" · {len(src)} source{'s' if len(src) != 1 else ''}" if src else "")})
    if th.get("updated"):
        n = {k: len(th.get(k) or []) for k in ("drivers", "promises", "catalysts")}
        out.append({"date": th["updated"][:10], "kind": "Research update",
                    "text": " · ".join(f"{v} {k[:-1] if v == 1 else k}" for k, v in n.items() if v)})
    au = th.get("audit") or {}
    if au.get("date") and au.get("verdict"):
        out.append({"date": au["date"][:10], "kind": "Full review", "verdict": au["verdict"],
                    "text": f"{len(au.get('checks') or [])} checks verified"})
    return out


def update(theses: dict) -> dict:
    """Merge today's research state into the log; returns the whole log."""
    try:
        log = json.loads(LOG.read_text()) if LOG.exists() else {}
    except Exception:  # noqa: BLE001
        log = {}
    for s, th in theses.items():
        cur = log.setdefault(s, [])
        have = {(e["kind"], e["date"]) for e in cur}
        for e in _entries(th or {}):
            if (e["kind"], e["date"]) not in have:
                cur.append(e)
        cur.sort(key=lambda e: e["date"], reverse=True)
        del cur[40:]
    LOG.write_text(json.dumps(log, ensure_ascii=False, separators=(",", ":")))
    return log
