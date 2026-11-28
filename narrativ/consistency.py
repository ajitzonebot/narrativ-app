"""Consistency check across what the app shows for each stock (owner, 28 Nov 2026: "every information ties back to the
stock ... inconsistencies like this reduce confidence").

Reads the published files (docs/data: picks.json, fin/<symbol>.json, research.json, theses.json, queue.json,
research_done.json) and reports, per check, the stocks where two screens disagree. Run:
    python -m narrativ.consistency            # summary + examples
    python -m narrativ.consistency --json     # machine-readable
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from . import funnel as FN

OUT = Path("docs/data")
BUY = FN.BUY

CHECKS = {
    "K1": "Decision card says no forward driver, but the research has a driver with a verified due date",
    "K2": "Outlook says 'Not scanned yet', but Claude's research has an outlook scan",
    "K3": "Claude researched the stock (drivers), but there is no outlook scan, so Outlook is not rated",
    "K4": "Verified badge shown, but the research is not complete (RULES.md R8)",
    "K5": "Stock list (picks) and stock page (fin) disagree on the decision, verification, badge or conviction",
    "K6": "Research is newer than the decision on the stock page (the page was not recomputed)",
    "K7": "Decision card names a driver that is no longer in the research",
    "K8": "Reviewed Buy without a conviction, or with a conviction from an older rule",
    "K9": "Research queue's 'dated drivers found' differs from the research",
    "K10": "Conviction counts a signal that is not live on the Outlook tab",
}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def _ist_day(ts) -> str:
    """picks.json `updated` is a UTC timestamp; research dates are IST calendar days."""
    from datetime import datetime, timedelta, timezone
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    except (TypeError, ValueError):
        return str(ts or "")[:10]


def run(base: Path = OUT) -> dict:
    picks = _load(base / "picks.json", {})
    rows = {p["s"]: p for p in picks.get("picks") or []}
    research = _load(base / "research.json", {})
    theses = _load(base / "theses.json", {})
    done = _load(base / "research_done.json", {})
    built = str(picks.get("date") or "")[:10]
    rebuilt = _ist_day(picks.get("updated"))  # when the pages were last computed (a weekend rebuild keeps Friday's data date)
    hits: dict[str, list] = defaultdict(list)
    rule = None
    for s, p in rows.items():
        fin = _load(base / "fin" / f"{s}.json", None)
        if fin is None:
            continue
        dec, L = fin.get("decision") or {}, fin.get("levels") or {}
        rs, th = research.get(s) or {}, theses.get(s) or {}
        drivers = rs.get("drivers") or []
        dated = [d for d in drivers if d.get("due_verified")]
        text = " ".join(dec.get("why") or []) + " " + " ".join(dec.get("missing") or [])
        if dated and ("no forward driver" in text or "No verified forward driver" in text):
            hits["K1"].append((s, f"{len(dated)} dated driver(s) in research; card: no forward driver"))
        out = L.get("out") or {}
        has_scan = bool(th.get("scan") or rs.get("scan"))
        if out.get("t") == 0 and has_scan:
            hits["K2"].append((s, "scan in research, Outlook 'Not scanned yet'"))
        if drivers and not has_scan:
            hits["K3"].append((s, f"{len(drivers)} driver(s), no scan"))
        if p.get("dc") in BUY and p.get("vf") == "pass" and not p.get("ic") and rs:
            gaps = FN.research_missing({**rs, "scan_raw": th.get("scan") or rs.get("scan_raw")})
            if gaps:
                hits["K4"].append((s, "; ".join(gaps[:2])))
        cv = (fin.get("conviction") or {}).get("level")
        diffs = [f"{k}: list {a!r} vs page {b!r}" for k, a, b in (
            ("decision", p.get("dc"), dec.get("d")), ("verified", p.get("vf"), dec.get("verified")),
            ("badge", bool(p.get("ic")), bool(dec.get("incomplete"))), ("conviction", p.get("cv"), cv)) if a != b]
        if diffs:
            hits["K5"].append((s, "; ".join(diffs)))
        ru = str(rs.get("updated") or "")[:10]
        if ru and rebuilt and ru > rebuilt:  # research dated after the last rebuild of the stock pages
            hits["K6"].append((s, f"research {ru}, pages rebuilt {rebuilt}"))
        texts = {str(d.get("text") or "").strip().rstrip(".") for d in drivers}
        for w in dec.get("why") or []:
            head, _, body = str(w).partition(": ")
            if head in ("Capacity", "Capex", "Order", "Margin", "Product", "Demand") and body.strip().rstrip(".") not in texts:
                hits["K7"].append((s, f"{head}: {body[:60]}"))
                break
        c = fin.get("conviction") or {}
        if p.get("dc") in BUY and p.get("vf") == "pass":
            rule = rule or c.get("rule")
            if not c:
                hits["K8"].append((s, "no conviction"))
        if c:
            live = {t.get("n") for t in out.get("triggers") or []}
            for pr in c.get("proofs") or []:
                if pr.get("k") == "signal":
                    n = str(pr.get("t") or "")
                    n = n[7].upper() + n[8:] if n.startswith("Strong ") else n
                    if n not in live:
                        hits["K10"].append((s, f"'{pr.get('t')}' not live"))
                        break
    rules = {str((_load(base / "fin" / f"{s}.json", {}).get("conviction") or {}).get("rule")) for s, p in rows.items()
             if p.get("dc") in BUY and p.get("vf") == "pass"}
    if len(rules) > 1:
        hits["K8"].append(("*", f"conviction rules mixed: {sorted(rules)}"))
    last = {}
    for r in done.get("runs") or []:
        for it in r.get("items") or []:
            if it.get("dated") is not None:
                last[it.get("s")] = it["dated"]
    for s, n in last.items():
        have = sum(1 for d in (research.get(s) or {}).get("drivers") or [] if d.get("due_verified"))
        if s in research and n != have:
            hits["K9"].append((s, f"queue says {n}, research has {have}"))
    return {"stocks": len(rows), "data_date": built, "checks": {k: {"what": CHECKS[k], "n": len(hits[k]), "examples": hits[k][:8]}
                                                                for k in CHECKS}}


# checks that must be 0 after a rebuild; K3 (scan missing) is work queued for Claude, reported but not alerted
HARD = ("K1", "K2", "K4", "K5", "K6", "K7", "K8", "K9", "K10")
TITLE = "consistency: stocks disagree across screens"


def publish(r: dict, path: Path = OUT / "consistency.json") -> int:
    """Write the report; open, update or close the one GitHub issue for hard mismatches. Returns the hard count."""
    import os

    import requests
    path.write_text(json.dumps(r, indent=1, ensure_ascii=False))
    hard = {k: v for k, v in r["checks"].items() if k in HARD and v["n"]}
    n = sum(v["n"] for v in hard.values())
    repo, tok = os.environ.get("NARRATIV_REPO") or os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and tok):
        return n
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}/issues"
    try:
        found = [i for i in requests.get(api, params={"labels": "consistency", "state": "open"}, headers=h, timeout=30).json()
                 if i.get("title") == TITLE]
        sig = "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_"
        if n:
            body = (f"Data {r['data_date']}: {n} mismatch(es) between screens (narrativ/consistency.py).\n\n"
                    + "\n".join(f"- **{k}** {v['what']}: {v['n']} (e.g. " + ", ".join(f"{s} ({w})" for s, w in v["examples"][:3]) + ")"
                                 for k, v in hard.items()) + sig)
            if found:
                requests.post(f"{api}/{found[0]['number']}/comments", json={"body": body}, headers=h, timeout=30)
            else:
                requests.post(api, json={"title": TITLE, "body": body, "labels": ["consistency"]}, headers=h, timeout=30)
        elif found:
            requests.post(f"{api}/{found[0]['number']}/comments", json={"body": f"Data {r['data_date']}: no mismatches left." + sig},
                          headers=h, timeout=30)
            requests.patch(f"{api}/{found[0]['number']}", json={"state": "closed", "state_reason": "completed"}, headers=h, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[consistency] issue update failed: {e}")
    return n


if __name__ == "__main__":
    r = run()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=1, ensure_ascii=False))
    else:
        print(f"{r['stocks']} stocks, data {r['data_date']}")
        for k, v in r["checks"].items():
            print(f"{k:4} {v['n']:>5}  {v['what']}")
            for s, why in v["examples"][:4]:
                print(f"        {s}: {why}")
