"""Keeps RULES.md current: rewrites its Scorecard and Lessons sections after each daily run (rules themselves change only
through a merged pull request; see RULES.md 'How the rules learn')."""
import json
import re
from pathlib import Path

DOC = Path("RULES.md")
LESSONS = Path("docs/data/lessons.jsonl")


def _put(text: str, key: str, body: str) -> str:
    return re.sub(rf"(<!-- AUTO:{key} -->\n).*?(\n<!-- /AUTO:{key} -->)", lambda m: m.group(1) + body.strip() + m.group(2), text, flags=re.S)


def lessons(n: int = 30) -> list[dict]:
    if not LESSONS.exists():
        return []
    out = []
    for line in LESSONS.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out[-n:]


def update(today, gates: dict, held: list, decisions: dict, calls: dict | None) -> None:
    if not DOC.exists():
        return
    rows = [f"Run of {today}.", "", "| Measure | Value |", "|---|---|"]
    rows.append("| Decisions | " + ", ".join(f"{k} {v}" for k, v in sorted(decisions.items(), key=lambda kv: -kv[1])) + " |")
    rows.append(f"| Held back by the Buy gates | {len(held)} stocks |")
    for g in sorted(gates):
        rows.append(f"| {g} held back | {gates[g]} |")
    if held:
        rows.append("| Held stocks | " + ", ".join(held[:25]) + (" …" if len(held) > 25 else "") + " |")
    if calls:
        rows.append(f"| Calls tracked | {calls.get('open', 0)} open · {len(calls.get('calls') or [])} recorded |")
        for k in ("verified", "candidate"):
            c = (calls.get("summary") or {}).get(k) or {}
            done = {h: v for h, v in c.items() if v.get("n")}
            rows.append(f"| {k.capitalize()} calls | " + (" · ".join(
                f"{h}: avg {v['avg_pct']:+.1f}%, vs Nifty {v['avg_vs_nifty']:+.1f}%, hit {v['hit_pct']:.0f}% (n={v['n']})" for h, v in done.items())
                or "no call old enough yet (first 1-month results mid-December)") + " |")
    ls = lessons()
    lrows = ["| Date | Stock | Rule | Lesson | Evidence |", "|---|---|---|---|---|"] + [
        f"| {x.get('date', '')} | {x.get('symbol', '')} | {x.get('rule', '')} | {str(x.get('lesson', '')).replace('|', '/')} | {x.get('source', '')} |"
        for x in reversed(ls)] if ls else ["_No lessons logged yet._"]
    t = DOC.read_text()
    t = _put(t, "scorecard", "\n".join(rows))
    t = _put(t, "lessons", "\n".join(lrows))
    DOC.write_text(t)
