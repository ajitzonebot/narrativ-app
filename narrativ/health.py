"""Pipeline health for the app's Data pipeline screen (feedback #41): stage times, problems seen in the log,
source sizes and check coverage. Written to docs/data/health.json at the end of each daily run."""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("docs/data/health.json")
PROBLEM = re.compile(r"failed|error|traceback|exceeded|blocked|not reachable|unavailable|timed out|stopped at the time budget", re.I)
PENDING = "source not connected yet"

_t0 = time.time()
_last = _t0
stages: list[list] = []
problems: list[str] = []
sources: dict = {}


class _Tee:
    def __init__(self, s):
        self.s = s

    def write(self, x):
        for line in x.splitlines():
            if line.strip() and PROBLEM.search(line) and len(problems) < 80:
                problems.append(line.strip()[:220])
        return self.s.write(x)

    def flush(self):
        return self.s.flush()

    def __getattr__(self, k):
        return getattr(self.s, k)


def start() -> None:
    global _t0, _last
    _t0 = _last = time.time()
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)


def mark(name: str) -> None:
    """Time since the previous mark goes to `name`."""
    global _last
    now = time.time()
    stages.append([name, round(now - _last)])
    _last = now


def source(name: str, **kv) -> None:
    sources[name] = {k: v for k, v in kv.items() if v is not None}


def coverage(details: dict) -> list[dict]:
    """Per check: stocks with a mark, with no data, not connected, not applicable."""
    c: dict = {}
    for d in details.values():
        for lk, lv in (d.get("levels") or {}).items():
            for it in lv.get("items") or []:
                k = (lk, it["id"])
                x = c.setdefault(k, {"level": lk, "id": it["id"], "name": it.get("n", ""), "data": 0, "no_data": 0, "pending": 0, "na": 0})
                note = it.get("note")
                if it.get("m") is not None:
                    x["data"] += 1
                elif note == PENDING:
                    x["pending"] += 1
                elif note == "not applicable":
                    x["na"] += 1
                else:
                    x["no_data"] += 1
    return sorted(c.values(), key=lambda x: (x["level"], x["id"]))


def _research_runs() -> dict | None:
    try:  # docs/data/research_runs.jsonl has mixed time formats: narrativ/runlog.py reads them all
        from . import runlog
        return runlog.summary()
    except Exception:  # noqa: BLE001
        return None


def write(today, details: dict, extra: dict | None = None) -> None:
    mark("finish")
    cov = coverage(details)
    tot = sum(x["data"] + x["no_data"] + x["pending"] for x in cov)
    OUT.write_text(json.dumps({
        "date": str(today), "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "minutes": round((time.time() - _t0) / 60, 1), "stages": stages, "problems": problems, "sources": sources,
        "coverage_pct": round(sum(x["data"] for x in cov) / tot * 100, 1) if tot else None,
        "stocks": len(details), "checks": cov, "research_runs": _research_runs(), **(extra or {})}, separators=(",", ":"), ensure_ascii=False))
    hp = OUT.parent / "runs.json"
    try:
        hist = json.loads(hp.read_text()) if hp.exists() else []
    except Exception:  # noqa: BLE001
        hist = []
    hist = ([{"date": str(today), "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "minutes": round((time.time() - _t0) / 60, 1), "problems": len(problems)}] + hist)[:30]
    hp.write_text(json.dumps(hist, separators=(",", ":")))
    print(f"[health] {len(stages)} stages, {len(problems)} problems, coverage {round(sum(x['data'] for x in cov) / tot * 100, 1) if tot else None}%")
