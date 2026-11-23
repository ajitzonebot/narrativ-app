"""14:10 IST subscription update for open IPOs (IPO.md, "After the check"). No Claude: NSE numbers only.
Refreshes category-wise subscription for each actionable IPO in docs/data/ipo_today.json; on the final day an APPLY
with overall subscription below 1x becomes WAIT, recorded in `pm_update`. Exits at once when nothing is open today."""
import json
import re
from datetime import datetime, timedelta, timezone

from .ipo_check import F, check

IST = timezone(timedelta(hours=5, minutes=30))
API = "https://www.nseindia.com/api"
CATS = (("qib", re.compile(r"qualified|qib", re.I)), ("nii", re.compile(r"non.?institutional|nii|hni", re.I)),
        ("retail", re.compile(r"retail|rii|individual", re.I)), ("overall", re.compile(r"^total|overall", re.I)))


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("x", "").strip())
    except (TypeError, ValueError):
        return None


def _times(row: dict):
    """Times subscribed from one category row: a 'times' field when present, else bids / shares offered."""
    for k, v in row.items():
        if re.search(r"time", k, re.I) and _num(v) is not None:
            return round(_num(v), 2)
    bid = next((_num(v) for k, v in row.items() if re.search(r"bid", k, re.I) and _num(v)), None)
    off = next((_num(v) for k, v in row.items() if re.search(r"offer|reserv", k, re.I) and _num(v)), None)
    return round(bid / off, 2) if bid and off else None


def parse(x) -> dict:
    rows = x if isinstance(x, list) else next((v for v in (x or {}).values() if isinstance(v, list)), [])
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        label = str(next((v for k, v in r.items() if re.search(r"categ", k, re.I)), "")).strip()
        for key, rx in CATS:
            if key not in out and rx.search(label):
                t = _times(r)
                if t is not None:
                    out[key] = t
                break
    return out


def main() -> None:
    now = datetime.now(IST)
    d = json.loads(F.read_text())
    if d.get("date") != now.date().isoformat() or not d.get("actionable"):
        print(f"[ipo-pm] nothing open today (report date {d.get('date')}, {len(d.get('actionable') or [])} actionable)")
        return
    from .filings import NSESession
    ns = NSESession()
    changed = False
    for i in d["actionable"]:
        sym = i.get("symbol")
        if not sym:
            print(f"[ipo-pm] {i['name']}: no NSE symbol in the report; subscription not refreshed")
            continue
        x = ns.get(f"{API}/ipo-active-category", params={"symbol": sym})
        sub = parse(x)
        if not sub:
            print(f"[ipo-pm] {sym}: subscription not parsed; response keys: {list(x)[:8] if isinstance(x, dict) else type(x).__name__}")
            continue
        i["subscription"] = {"as_of": now.strftime("%Y-%m-%dT%H:%M+05:30"), **sub,
                             "source": f"https://www.nseindia.com/market-data/issue-information?symbol={sym}&series=EQ&type=Active"}
        changed = True
        before = i.get("action")
        if i.get("final_day") and before == "APPLY" and (sub.get("overall") or 0) < 1:
            i["action"] = "WAIT"
            i.setdefault("missing", []).append("Undersubscribed (below 1x overall) at 14:10 on the final day")
        i["pm_update"] = {"as_of": i["subscription"]["as_of"], "call_before": before, "call_after": i["action"]}
        print(f"[ipo-pm] {sym}: {sub} · call {before} -> {i['action']}")
    if changed:
        d, errs = check(d)
        F.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        for e in errs:
            print("-", e)


if __name__ == "__main__":
    main()
