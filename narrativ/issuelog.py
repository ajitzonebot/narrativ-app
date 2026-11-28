"""The issue log shared by the research runs, the pipeline and the session that fixes things (owner, 28 Nov 2026: "a communication
system between two Claudes ... every run loads issues, we can directly pick from there instead of copy pasting responses").

Write path (git, because the research runs push to main and hold no Cloudflare key):
  docs/data/issues/<source>-<run>.jsonl   one file per run (no rebase conflicts), one row per issue or sighting
  docs/data/issues/fixes.jsonl            status changes by the fixing session: fixed / wontfix / duplicate / open, what changed, PR
Read path: `python3 -m narrativ.issuelog list` (merged view); the daily run copies the merged rows to the Cloudflare D1 table
`issue` (narrativ/dbsync.py, db/schema.sql) for queries.

    python3 -m narrativ.issuelog list [--open] [--kind K] [--symbol S] [--json]
    python3 -m narrativ.issuelog add --source review --run <start> --kind bug --severity high --title "..." --detail "..."
                                   [--symbol X.NS] [--evidence "error text, urls, commands"] [--same <id>]
    python3 -m narrativ.issuelog fix <id> --status fixed --fix "what changed" --ref <PR url>

Kinds: bug (code), data (a wrong or missing number or document), pipeline (a job, fetch or source failed), verifier (a check
rejected something correct, or let through something wrong), rule (a rule held back a good stock or let a weak one through),
environment (network, permissions, installs), feedback (the owner's app feedback), other.
An issue already in the list is not added again: `--same <id>` records another sighting (date, run, what was seen).
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DIR = Path("docs/data/issues")
FIXES = DIR / "fixes.jsonl"
IST = timezone(timedelta(hours=5, minutes=30))
KINDS = ("bug", "data", "pipeline", "verifier", "rule", "environment", "feedback", "other")
SEVERITIES = ("high", "medium", "low")
STATUSES = ("open", "fixed", "wontfix", "duplicate")
COLS = ["id", "created", "source", "run", "kind", "severity", "symbol", "title", "detail", "evidence", "seen", "last_seen",
        "sightings", "status", "fixed_at", "fix", "fix_ref"]


def _now() -> datetime:
    return datetime.now(IST)


def _rows(path: Path) -> list[dict]:
    out = []
    for ln in path.read_text().splitlines() if path.exists() else []:
        try:
            r = json.loads(ln)
            if isinstance(r, dict):
                out.append(r)
        except ValueError:
            continue
    return out


def load(d: Path | None = None) -> list[dict]:
    """Every issue with its sightings and latest status, newest first."""
    d = d or DIR
    issues: dict[str, dict] = {}
    seen: list[dict] = []
    for f in sorted(d.glob("*.jsonl")):
        if f.name == FIXES.name:
            continue
        for r in _rows(f):
            if r.get("same"):
                seen.append(r)
            elif r.get("id") and r["id"] not in issues:
                issues[r["id"]] = {**{k: r.get(k) for k in COLS if k in r}, "sightings": [], "seen": 1, "last_seen": r.get("created"),
                                   "status": "open"}
    for r in seen:
        it = issues.get(r["same"])
        if it:
            it["sightings"].append({k: r.get(k) for k in ("created", "source", "run", "detail", "evidence") if r.get(k)})
            it["seen"] += 1
            it["last_seen"] = max(str(it.get("last_seen") or ""), str(r.get("created") or ""))
    for r in _rows(d / FIXES.name):
        it = issues.get(r.get("id"))
        if it and r.get("status") in STATUSES:
            it.update({"status": r["status"], "fixed_at": r.get("at"), "fix": r.get("fix"), "fix_ref": r.get("ref")})
            if r["status"] == "open":  # reopened
                it.update({"fixed_at": None, "fix": None, "fix_ref": None})
    for it in issues.values():  # seen again after it was marked fixed: open again, the fix did not hold
        if it["status"] == "fixed" and str(it.get("last_seen") or "") > str(it.get("fixed_at") or ""):
            it["status"] = "open"
            it["fix"] = f"reopened: seen on {it['last_seen']} after the fix of {it['fixed_at']} ({it.get('fix') or ''})"
    return sorted(issues.values(), key=lambda x: str(x.get("last_seen") or ""), reverse=True)


def _file(source: str, run: str | None) -> Path:
    tag = re.sub(r"[^0-9A-Za-z]+", "-", run or _now().strftime("%Y-%m-%d")).strip("-")
    return DIR / f"{re.sub(r'[^a-z0-9]+', '-', source.lower())}-{tag}.jsonl"


def add(source: str, kind: str, title: str, detail: str, severity: str = "medium", symbol: str | None = None,
        evidence: str | None = None, run: str | None = None, same: str | None = None) -> dict:
    """Append one issue (or, with `same`, a sighting of an existing one) to this run's file. Returns the row."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
    created = _now().isoformat(timespec="minutes")
    row = {"created": created, "source": source, "run": run, "kind": kind, "severity": severity, "symbol": symbol,
           "title": title.strip()[:200], "detail": detail.strip()[:4000], "evidence": (evidence or "").strip()[:4000] or None}
    if same:
        row["same"] = same
    else:
        row["id"] = hashlib.sha1(f"{created}|{source}|{title}|{symbol}".encode()).hexdigest()[:10]
    DIR.mkdir(parents=True, exist_ok=True)
    with _file(source, run).open("a") as f:
        f.write(json.dumps({k: v for k, v in row.items() if v is not None}, ensure_ascii=False) + "\n")
    return row


def fix(issue_id: str, status: str, fix_text: str, ref: str | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    row = {"id": issue_id, "at": _now().isoformat(timespec="minutes"), "status": status, "fix": fix_text.strip()[:2000], "ref": ref}
    DIR.mkdir(parents=True, exist_ok=True)
    with FIXES.open("a") as f:
        f.write(json.dumps({k: v for k, v in row.items() if v is not None}, ensure_ascii=False) + "\n")
    return row


def auto(source: str, kind: str, title: str, detail: str, severity: str = "medium", symbol: str | None = None,
         evidence: str | None = None, run: str | None = None) -> dict | None:
    """For the pipeline: add the issue, or a sighting when an open one has the same title and symbol (at most one a day)."""
    today = _now().date().isoformat()
    for it in load():
        if it["status"] == "open" and it.get("title") == title.strip()[:200] and it.get("symbol") == symbol:
            if str(it.get("last_seen") or "")[:10] == today:
                return None
            return add(source, kind, title, detail, severity, symbol, evidence, run, same=it["id"])
    return add(source, kind, title, detail, severity, symbol, evidence, run)


def d1_rows(items: list[dict] | None = None) -> list[list]:
    """Rows for the D1 table `issue` (db/schema.sql), sightings as JSON."""
    return [[json.dumps(it.get(c), ensure_ascii=False) if c == "sightings" else it.get(c) for c in COLS] for it in (items or load())]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Narrativ issue log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--open", action="store_true")
    ls.add_argument("--kind")
    ls.add_argument("--symbol")
    ls.add_argument("--json", action="store_true")
    a_ = sub.add_parser("add")
    for k in ("source", "kind", "title", "detail"):
        a_.add_argument(f"--{k}", required=True)
    for k in ("severity", "symbol", "evidence", "run", "same"):
        a_.add_argument(f"--{k}")
    f_ = sub.add_parser("fix")
    f_.add_argument("id")
    f_.add_argument("--status", default="fixed")
    f_.add_argument("--fix", required=True)
    f_.add_argument("--ref")
    a = ap.parse_args(argv)
    if a.cmd == "add":
        print(json.dumps(add(a.source, a.kind, a.title, a.detail, a.severity or "medium", a.symbol, a.evidence, a.run, a.same), ensure_ascii=False))
    elif a.cmd == "fix":
        print(json.dumps(fix(a.id, a.status, a.fix, a.ref), ensure_ascii=False))
    else:
        items = [it for it in load() if (not a.open or it["status"] == "open") and (not a.kind or it.get("kind") == a.kind)
                 and (not a.symbol or it.get("symbol") == a.symbol)]
        if a.json:
            print(json.dumps(items, ensure_ascii=False, indent=1))
        else:
            for it in items:
                print(f"{it['id']}  {it['status']:<9} {it.get('severity') or '':<6} {it.get('kind') or '':<11} {it.get('symbol') or '-':<14} "
                      f"seen {it['seen']}x, last {str(it.get('last_seen') or '')[:16]}  {it.get('title')}")
            print(f"{len(items)} issue(s)")


if __name__ == "__main__":
    main()
