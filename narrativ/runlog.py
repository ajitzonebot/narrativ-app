"""Tolerant reader of docs/data/research_runs.jsonl (one line per Claude research run, appended by the research task).

Times were written in mixed formats: "18:06 IST", "22:36 IST+0 (UTC 22:35)", "08:36 UTC (14:06 IST)", "23:00 UTC".
tasks/review.md and tasks/catalyst.md ask for ISO-8601 (and a "task" field: review / catalyst) with offset ("2026-11-20T18:06+05:30"); old lines stay as they are, so every reader goes
through parse_time(). A time without a date takes the date from `day` (the line's queue_date: an approximation, flagged `approx`).
Nothing here raises on a bad line or a bad time.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FILE = Path("docs/data/research_runs.jsonl")
IST = timezone(timedelta(hours=5, minutes=30))
ISO = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?\s*(Z|UTC|IST|[+-]\d{2}(?::?\d{2})?)?\s*$", re.I)
UTC_TIME = re.compile(r"UTC\s*(\d{1,2}):(\d{2})|(\d{1,2}):(\d{2})\s*UTC", re.I)
IST_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*IST", re.I)
ANY_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def _offset(tz: str | None) -> timezone:
    if not tz or tz.upper() in ("Z", "UTC"):
        return timezone.utc
    if tz.upper() == "IST":
        return IST
    sign = -1 if tz[0] == "-" else 1
    digits = tz[1:].replace(":", "")
    return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0)))


def parse_time(s, day=None) -> datetime | None:
    """-> timezone-aware UTC datetime, or None. Accepts ISO-8601 with offset ("2026-11-20T18:06+05:30", "...Z") and the legacy
    "HH:MM IST" / "HH:MM UTC" / "HH:MM IST+0 (UTC HH:MM)" / "HH:MM UTC (HH:MM IST)" texts. A legacy time needs `day` (date or
    "YYYY-MM-DD"); an explicit UTC time in the text wins over the IST one."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return (s if s.tzinfo else s.replace(tzinfo=IST)).astimezone(timezone.utc)
    text = str(s).strip()
    m = ISO.match(text)
    try:
        if m:
            d = date.fromisoformat(m.group(1))
            return datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)), int(m.group(4) or 0),
                            tzinfo=_offset(m.group(5) or "+05:30")).astimezone(timezone.utc)  # no offset: the research task runs in IST
        d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
        u = UTC_TIME.search(text)
        if u:
            hh, mm, tz = int(u.group(1) or u.group(3)), int(u.group(2) or u.group(4)), timezone.utc
        else:
            t = IST_TIME.search(text) or ANY_TIME.search(text)
            hh, mm, tz = int(t.group(1)), int(t.group(2)), IST
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def read(path: Path | str = FILE) -> list[dict]:
    """Every run line as a dict with `start_utc` / `end_utc` (ISO strings or None) added and `approx` True when a time had no date
    of its own. Unreadable lines are skipped."""
    out, prev_end = [], None
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        day = r.get("queue_date")
        s, e = parse_time(r.get("start"), day), parse_time(r.get("end"), day)
        r["approx"] = not (ISO.match(str(r.get("start") or "")) and ISO.match(str(r.get("end") or "")))
        if r["approx"] and s and prev_end:  # dateless times: the file is chronological, so move the guessed day next to the previous run
            while s > prev_end + timedelta(hours=24):
                s, e = s - timedelta(days=1), e - timedelta(days=1) if e else e
            while s < prev_end - timedelta(hours=1):
                s, e = s + timedelta(days=1), e + timedelta(days=1) if e else e
        if r["approx"] and s and e and e < s:  # the run crossed midnight
            e += timedelta(days=1)
        prev_end = e or s or prev_end
        r["start_utc"], r["end_utc"] = (s.isoformat(timespec="minutes") if s else None), (e.isoformat(timespec="minutes") if e else None)
        out.append(r)
    return out


def summary(runs: list[dict] | None = None) -> dict:
    """Runs logged, runs that stopped on an error or without work, and the last logged run (for health.json)."""
    runs = read() if runs is None else runs
    last = runs[-1] if runs else {}
    return {"runs": len(runs), "last_end": last.get("end_utc"), "last_done": len(last.get("done") or []),
            "last_stopped": str(last.get("stopped") or "")[:120] or None}


DONE = Path("docs/data/research_done.json")


def completed(days: int = 7, now: datetime | None = None, path: Path | None = None, out_path: Path | None = None,
              theses: dict | None = None) -> dict:
    """docs/data/research_done.json for the app's Research queue > Completed: every item a research run finished in the last
    `days` days, newest run first. Each `done` entry "SYMBOL:result" becomes {"s", "r"} (r: pass / caution / fail for a full
    review, else the task, e.g. enrich, recheck, dismissed); "industries:..." stays a text line. `task` is review / catalyst
    (older lines have none). With `theses` (the verified research) each stock row carries `dated`: its drivers whose due date
    the verifier confirmed, now (feedback #219, 27 Nov 2026: the app said "Dated driver found" for enrich runs that found
    none, e.g. WINDLAS, DSSL, VENKEYS, or had no call to read)."""
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(days=days)
    runs = []
    for r in read(path or FILE):
        t = r.get("start_utc") or r.get("end_utc")
        if not t or datetime.fromisoformat(t) < cut or not r.get("done"):
            continue
        items = []
        for d in r["done"]:
            k, _, v = str(d).partition(":")
            if k == "industries":
                items.append({"industries": v})
            elif k:
                # "A.NS/B.NS:..." (one note for two stocks) becomes one row per stock: the app opens each row's stock page,
                # and "BONDADA.NS/CAPLIPOINT.NS" opened an empty page (feedback #136, 26 Nov 2026)
                for one in re.split(r"\s*/\s*|\s*,\s*|\s+(?:and|&|\+)\s+", k):  # "&" only with spaces: J&KBANK and M&M are symbols (review 26 Nov 2026)
                    one = one.strip()
                    if one:
                        sym = one if "." in one else f"{one}.NS"
                        it = {"s": sym, "r": (v or "done").strip()}
                        if theses is not None:
                            it["dated"] = sum(1 for x in (theses.get(sym) or {}).get("drivers") or [] if x.get("due_verified"))
                        items.append(it)
        runs.append({"task": r.get("task"), "start": t, "approx": r.get("approx", False), "items": items})
    runs.sort(key=lambda x: x["start"], reverse=True)
    out = {"since": cut.date().isoformat(), "days": days, "runs": runs}
    (out_path or DONE).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    return out
