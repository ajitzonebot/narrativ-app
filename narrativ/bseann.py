"""BSE announcements for BSE-only stocks (NSE's market-wide list does not cover them), via the `bse` library.
First load: per stock, 25 months. After that: BSE's market-wide list for the days since the last run (2-day overlap),
kept for the covered scrip codes only. Rows use the NSE store's format, so the same subject-line checks and events apply.
Store: data/source_cache/bse_announcements.json.gz (Actions cache)."""
import gzip
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import docfunnel
from .announcements import _KEEP_OLD, _ORDER, DEV, MONTHS, RECENT_DAYS

STORE = Path("data/source_cache/bse_announcements.json.gz")
ATT = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(gzip.decompress(STORE.read_bytes()))
        except Exception as e:  # noqa: BLE001
            print(f"[bseann] store unreadable, rebuilding: {e}")
    return {"rows": {}, "loaded": {}, "last": None}


def _row(a: dict) -> list | None:
    d = str(a.get("NEWS_DT") or a.get("DT_TM") or "")[:10]
    if len(d) != 10:
        return None
    cat = " / ".join(x for x in (a.get("CATEGORYNAME"), a.get("SUBCATNAME")) if x and x != "-1")
    sub, head = (a.get("NEWSSUB") or "").strip(), (a.get("HEADLINE") or "").strip()
    txt = f"{sub} - {head}" if sub and head and head.lower() not in sub.lower() else (sub or head)
    url = ATT + a["ATTACHMENTNAME"] if a.get("ATTACHMENTNAME") else None
    g, rule = docfunnel.classify(cat, txt)
    s = f"{cat} {txt}"
    return [d, cat[:80], txt[:600] if _ORDER.search(s) else txt[:240], url, g, rule]


def _pages(b, frm: date, to: date, code: str | None = None, max_pages: int = 400):
    out, p = [], 1
    while p <= max_pages:
        r = b.announcements(page_no=p, from_date=datetime.combine(frm, datetime.min.time()),
                            to_date=datetime.combine(to, datetime.min.time()), scripcode=code)
        rows = (r or {}).get("Table") or []
        out += rows
        total = int((((r or {}).get("Table1") or [{}])[0]).get("ROWCNT") or 0)
        if len(rows) < 50 or len(out) >= total:
            break
        p += 1
    return out


def _keep(rec: list, today: date) -> bool:
    s = f"{rec[1]} {rec[2]}"
    if rec[4] == "skip" and not _KEEP_OLD.search(s) and not DEV.search(s):
        return False
    return rec[0] >= (today - timedelta(days=RECENT_DAYS)).isoformat() or bool(_KEEP_OLD.search(s)) or bool(DEV.search(s)) \
        or rec[5] in ("Transcript", "Investor presentation")


def refresh(codes: dict[str, str], today: date, max_minutes: float = 6) -> dict:
    """codes: {BSE-only symbol: scrip code}."""
    st = _load()
    t0, first, calls = time.time(), 0, 0
    by_code = {str(c).lstrip("0"): s for s, c in codes.items() if c}
    try:
        from bse import BSE
        with BSE(download_folder=Path("data/exchange_tmp")) as b:
            # daily: market-wide days since the last run, covered codes only
            if st.get("last"):
                frm = date.fromisoformat(st["last"]) - timedelta(days=2)
                rows = _pages(b, frm, today)
                calls += max(1, len(rows) // 50 + 1)
                for s in by_code.values():
                    st["rows"][s] = [r for r in st["rows"].get(s, []) if r[0] < frm.isoformat()]
                for a in rows:
                    s = by_code.get(str(a.get("SCRIP_CD") or "").lstrip("0"))
                    rec = _row(a) if s and s in st["loaded"] else None
                    if rec and _keep(rec, today):
                        st["rows"].setdefault(s, []).append(rec)
            st["last"] = today.isoformat()
            # first load per stock (25 months), within the time budget
            for s, c in codes.items():
                if s in st["loaded"] or not c:
                    continue
                if time.time() - t0 > max_minutes * 60:
                    break
                rows, ok, end = [], True, today
                start = today - timedelta(days=31 * MONTHS)
                while end > start:  # BSE rejects ranges longer than about a year: 300-day windows
                    frm = max(start, end - timedelta(days=300))
                    try:
                        rows += _pages(b, frm, end, code=str(c), max_pages=20)
                        calls += 1
                    except Exception as e:  # noqa: BLE001
                        print(f"[bseann] {s} {frm}..{end}: {e}")
                        ok = False
                        break
                    end = frm - timedelta(days=1)
                if not ok:
                    continue
                recs = [r for r in (_row(a) for a in rows) if r and _keep(r, today)]
                st["rows"][s] = recs
                st["loaded"][s] = today.isoformat()
                first += 1
    except Exception as e:  # noqa: BLE001
        print(f"[bseann] BSE session failed: {e}")
    cut = (today - timedelta(days=31 * MONTHS)).isoformat()
    for s in list(st["rows"]):
        seen, out = set(), []
        for r in sorted(st["rows"][s], key=lambda r: r[0], reverse=True):
            k = r[3] or f"{r[0]}|{r[2][:80]}"
            if r[0] >= cut and k not in seen:
                seen.add(k)
                out.append(r)
        st["rows"][s] = out
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(gzip.compress(json.dumps(st, separators=(",", ":"), ensure_ascii=False).encode()))
    print(f"[bseann] {first} stocks loaded (25 months), {sum(1 for s in codes if s in st['loaded'])} of {len(codes)} covered, "
          f"~{calls} calls, {time.time() - t0:.0f}s")
    return st
