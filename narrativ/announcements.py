"""All-company NSE announcements (mainboard + SME), 24 months, kept in the Actions cache (not git).

One API call returns a date range for every company, so a full 24-month build is ~50 calls; once loaded, each run
reads only the days since the last run (2-day overlap) for both indices and merges them in. Rows are typed with data/doc_rules.json (D1).

Subject-line checks (no PDF is read, so a hit is 'watch' with the filing link, never an automatic removal):
  A2 default · A4 insolvency · A5 rating downgrade · G1 regulator order · G2 search/fraud ·
  G3 statutory auditor resigned · G4 CFO + CEO exits within 12 months · C7 leadership stable 24 months
"""
import gzip
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from . import docfunnel, events
from .filings import NSESession

STORE = Path("data/source_cache/announcements.json.gz")
API = "https://www.nseindia.com/api/corporate-announcements"
MONTHS = 25
RECENT_DAYS = 120  # keep every non-skip row this long (events, research); older: only rows the checks need
SRC = "NSE announcements (subject line)"

_BOILER = re.compile(r"sebi\s*\([^)]*\)|regulation\s+\d+[^,.;]{0,60}of (the )?sebi[^,.;]*|sebi/[\w/-]+|sebi circular[^,.;]*", re.I)
_SUBSID = re.compile(r"subsidiar|step-?down|associate company|joint venture|\bwos\b|wholly[- ]owned|\bmaterial subsidiary", re.I)
_FINES = re.compile(r"fines|penalt|dues etc|statutory dues", re.I)
_NOT_DEBTOR = re.compile(r"scheme|amalgamat|merger|resolution plan (submitted )?by|submission of (the )?resolution plan|acqui|"
                         r"successful resolution applicant|expression of interest|exit from|withdrawal of (the )?(appeal|petition)|dismiss|vol\w*ntary liquidation|"
                         r"liquidation of [\w&.,() ]{0,60}(private|pvt)", re.I)
_ROUTINE_Q = re.compile(r"clarification|price movement|movement in (the )?price|volume|spurt|news item|query", re.I)
_PR = re.compile(r"press release|media release|launch|product|partnership|solution|\bdeal\b|anti-?fraud|fraud (detection|prevention|management)|"
                 r"sought clarification|clarification", re.I)
_NIL = re.compile(r"\bnil\b|no default|not applicable|non-?applicab|no such", re.I)
X = {
    "A2": re.compile(r"(?<!issuer )default(s)?\s+(on|in)\s+(the\s+)?(re)?payment|(?<!issuer )default(?!\s+rating).{0,40}(loan|borrowing|debenture|\bncd|interest|principal|bank)|"
                     r"delay(ed)?\s+in\s+(payment|servicing).{0,40}(interest|principal|loan|debenture)|non-?payment of (interest|principal)", re.I),
    "A4": re.compile(r"corporate insolvency resolution process|\bcirp\b|interim resolution professional|liquidat|winding up|insolvency.{0,40}admit|admit.{0,40}insolvency", re.I),
    "A5": re.compile(r"(?<!esg )(?<!esg rating )downgrad|rating.{0,40}(withdrawn|suspended)|\bissuer not cooperating\b|credit watch.{0,20}negative|outlook.{0,30}negative", re.I),
    "G1": re.compile(r"(from|by|of)\s+(the\s+)?(sebi|securities and exchange board|reserve bank|rbi|stock exchanges?|nse|bse|national stock exchange)\b|"
                     r"\b(sebi|rbi|nse|bse)\b.{0,30}(order|penalt|show cause|adjudicat|fine)", re.I),
    "G1cat": re.compile(r"action\(s\) (taken|initiated)|orders? passed|show cause|adjudicat|penalt", re.I),
    "G2": re.compile(r"fraud/default/arrest|search and seizure|\bseizure\b|\bsearch\b.{0,30}(income tax|gst|premises|operation)|forensic audit|enforcement directorate|\bfraud\b|arrest|investigation under section 212", re.I),
    "G3": re.compile(r"resignation of statutory auditor|statutory auditor.{0,60}resign|resign.{0,60}statutory auditor", re.I),
    "CFO": re.compile(r"(resign|cessation|step(ped|s)? down|demise).{0,90}(chief financial|\bcfo\b)|(chief financial|\bcfo\b).{0,90}(resign|cessation|step(ped|s)? down)", re.I),
    "CEO": re.compile(r"(resign|cessation|step(ped|s)? down|demise).{0,90}(chief executive|\bceo\b|managing director|\bmd\b)|"
                      r"(chief executive|\bceo\b|managing director|\bmd\b).{0,90}(resign|cessation|step(ped|s)? down)", re.I),
}
DEV = re.compile(r"statement of deviation|deviation\s*(or|/|&)\s*variation|monitoring agency report", re.I)
# rows kept at 600 characters: orders (not the "in order to" of exchange clarifications) and inspection outcomes, whose
# deciding words (observations, VAI / OAI) often come late in the subject
_ORDER = re.compile(events._ORD + r"|contract|letter of award|\bloa\b|letter of intent|inspection|\b(oai|vai|nai|eir)\b|form[- ]?483|"
                    r"warning letter|import alert", re.I)
_KEEP_OLD = re.compile("|".join(p.pattern for k, p in X.items() if k != "G1"), re.I)


# ---------- NSE "Resignation of Director/KMP/SMP" filings (owner, 24 Nov 2026) ----------
# The subject never names the role; the attachment (<SYM>_ROID_<n>_KMP_Doc.zip) holds SEBI's "Changes in Management" XBRL
# form with each person's category (Director / KMP / Senior Management / Compliance Officer), designation and how they left.
# The row is rewritten to say it ("Resignation of Chief Financial Officer (Key Managerial Personnel)"), so the CEO / CFO exit
# checks (G4, C7) and the event typing see the role. Cached per url; at most ROID_PER_RUN new attachments a run.
ROID_CACHE = Path("data/source_cache/roid")
ROID_PER_RUN = 60
ROID_CAT = "Change in management (NSE form)"
_HOW = {"resignation": "Resignation of", "superannuation or retirement": "Retirement of", "retirement": "Retirement of",
        "death": "Demise of", "removal": "Removal of", "disqualification": "Disqualification of"}
_VAGUE = {"", "resignation", "cessation", "appointment", "change in designation", "na", "not applicable"}


def roid_people(xml: str) -> list[dict]:
    """SEBI Changes-in-Management XBRL -> [{how, category, designation, reason}] (reason: the form's brief reason, if any)."""
    tags = re.findall(r"<in-capmkt(?:-ent)?:(\w+)[^>]*>([^<]{1,300})</", xml)
    people, cur, reasons = [], None, []
    for tag, val in tags:
        val = " ".join(val.split())
        if tag == "TypeOfChange":
            cur = {"type": val}
            people.append(cur)
        elif cur is not None and tag == "CategoryOfCessation":
            cur["how"] = val
        elif cur is not None and tag == "CategoryForChange":
            cur["category"] = val
        elif cur is not None and tag == "DesignationOfDesignatedPerson":
            cur["designation"] = val
        elif tag == "ReasonOfResignationInBrief":
            reasons.append(val)
    out = []
    for p in people:
        if str(p.get("type", "")).lower() != "cessation":
            continue
        des = p.get("designation") or ""
        out.append({"how": p.get("how") or "Cessation", "category": p.get("category") or "",
                    "designation": "" if des.lower() in _VAGUE else des})
    res = [p for p in out if p["how"].lower() == "resignation"]
    if reasons and res:  # the brief reason is given for resignations
        res[0]["reason"] = reasons[0]
    return out


def roid_text(people: list[dict]) -> str:
    parts = []
    for p in people:
        role = p["designation"] or p["category"] or "director / KMP"
        how = _HOW.get(p["how"].lower(), f"{p['how']} of")
        parts.append(f"{how} {role}" + (f" ({p['category']})" if p["designation"] and p["category"] else ""))
    r = next((p["reason"] for p in people if p.get("reason")), None)
    return "; ".join(parts) + (f". Reason: {r}" if r else "")


def roid_fetch(url: str, ns) -> str | None:
    """Readable summary of a ROID attachment (cached), or None when it cannot be read."""
    import hashlib
    import io
    import zipfile
    f = ROID_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if f.exists():
        return f.read_text() or None
    try:
        r = ns.s.get(url, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = next((z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.lower().endswith(".xml")), "")
        t = roid_text(roid_people(xml))
    except Exception as e:  # noqa: BLE001
        print(f"[ann] ROID {url[-40:]}: {str(e)[:80]}")
        return None
    ROID_CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(t)
    return t or None


def _roid_rows(st: dict, ns, today: date) -> int:
    """Rewrite stored ROID rows (last RECENT_DAYS + 24 months kept by _KEEP_OLD afterwards) with the role from the form."""
    n, since = 0, (today - timedelta(days=31 * MONTHS)).isoformat()
    for rows in st["rows"].values():
        for r in rows:
            if r[1] == ROID_CAT or "_ROID_" not in str(r[3] or "") or r[0] < since:
                continue
            cached = (ROID_CACHE / (__import__("hashlib").sha1(str(r[3]).encode()).hexdigest() + ".txt")).exists()
            if not cached and n >= ROID_PER_RUN:
                continue
            ns = ns or NSESession()
            t = roid_fetch(r[3], ns)
            n += 0 if cached else 1
            if t:
                r[1], r[2] = ROID_CAT, t[:600]
    return n


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(gzip.decompress(STORE.read_bytes()))
        except Exception as e:  # noqa: BLE001
            print(f"[ann] store unreadable, rebuilding: {e}")
    return {"months": {}, "rows": {}}


def _save(st: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(gzip.compress(json.dumps(st, separators=(",", ":"), ensure_ascii=False).encode()))


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    a = date(y, m, 1)
    b = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return a, b


def _pdate(s: str) -> str | None:
    from datetime import datetime
    try:
        return datetime.strptime(s[:11], "%d-%b-%Y").date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _fetch_range(ns, idx, a: date, b: date, depth: int = 0):
    """Whole range in one call; on failure split in halves (big months time out). -> (rows | None, calls)."""
    js = ns.get(API, params={"index": idx, "from_date": a.strftime("%d-%m-%Y"), "to_date": b.strftime("%d-%m-%Y")})
    time.sleep(1)
    if isinstance(js, list):
        return js, 1
    if depth >= 3 or a >= b:
        return None, 1
    mid = a + (b - a) // 2
    r1, c1 = _fetch_range(ns, idx, a, mid, depth + 1)
    r2, c2 = _fetch_range(ns, idx, mid + timedelta(days=1), b, depth + 1)
    return (None if r1 is None or r2 is None else r1 + r2), 1 + c1 + c2


def refresh(today: date, max_minutes: float = 15) -> dict:
    """Fetch months that are missing or still open. Returns {sym: [[date, category, text, url, group, rule], ...]} newest first."""
    st = _load()
    if st.get("v", 1) < 3:  # v2: 600 characters for order announcements (T3); v3: statements of deviation kept (G7). Rebuild once
        st = {"months": {}, "rows": {}, "v": 3}
    months = []
    y, m = today.year, today.month
    for _ in range(MONTHS):
        months.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    need = []
    for y, m in months:
        k = f"{y}-{m:02d}"
        _, end = _month_bounds(y, m)
        got = st["months"].get(k)
        if not got or got <= (end + timedelta(days=3)).isoformat():  # still open, or fetched before it closed
            need.append((y, m))
    ns, t0, calls = None, time.time(), 0
    last = st.get("last")  # date of the last successful daily fetch
    for y, m in need:
        if time.time() - t0 > max_minutes * 60:
            break
        a, b = _month_bounds(y, m)
        b = min(b, today)
        k = f"{y}-{m:02d}"
        # loaded months: only the days since the last run (2-day overlap for late-published items), merged into the store
        delta = bool(last and st["months"].get(k) and date.fromisoformat(last) - timedelta(days=2) >= a)
        if delta:
            a = date.fromisoformat(last) - timedelta(days=2)
        ns = ns or NSESession()
        rows, ok = [], True
        for idx in ("equities", "sme"):
            got, c = _fetch_range(ns, idx, a, b)
            calls += c
            if got is None:
                ok = False
                break
            rows += got
        if not ok:
            print(f"[ann] {y}-{m:02d} fetch failed, keeping stored rows")
            continue
        old = (today - date(y, m, 1)).days > RECENT_DAYS + 31
        if delta:  # drop only the re-read days; earlier days of the month stay as stored
            for sym in st["rows"]:
                st["rows"][sym] = [r for r in st["rows"][sym] if not (a.isoformat() <= r[0] <= b.isoformat())]
        else:
            for sym in st["rows"]:
                st["rows"][sym] = [r for r in st["rows"][sym] if not r[0].startswith(k)]
        seen = set()
        for x in rows:
            d = _pdate(x.get("an_dt") or "")
            sym = f"{x.get('symbol')}.NS"
            cat, txt, url = (x.get("desc") or "").strip(), (x.get("attchmntText") or "").strip(), x.get("attchmntFile")
            key = url or f"{sym}|{d}|{txt[:80]}"
            if not d or key in seen:
                continue
            seen.add(key)
            g, rule = docfunnel.classify(cat, txt)
            s = f"{cat} {txt}"
            if g == "skip" and not _KEEP_OLD.search(s) and not DEV.search(s):
                continue
            if old and not _KEEP_OLD.search(s) and not DEV.search(s):
                continue
            st["rows"].setdefault(sym, []).append([d, cat[:80], txt[:600] if _ORDER.search(s) else txt[:240], url, g, rule])
        st["months"][k] = today.isoformat()
        if k == f"{today.year}-{today.month:02d}":
            st["last"] = today.isoformat()
    for sym in st["rows"]:
        st["rows"][sym].sort(key=lambda r: r[0], reverse=True)
    if time.time() - t0 < max_minutes * 60:
        print(f"[ann] ROID forms read: {_roid_rows(st, ns, today)}")
    # drop rows older than the window and long-past recent detail
    cut, cut_recent = (today - timedelta(days=31 * MONTHS)).isoformat(), (today - timedelta(days=RECENT_DAYS)).isoformat()
    st["rows"] = {s: [r for r in rs if r[0] >= cut and (r[0] >= cut_recent or _KEEP_OLD.search(f"{r[1]} {r[2]}") or DEV.search(f"{r[1]} {r[2]}") or (len(r) > 5 and r[5] in ("Transcript", "Investor presentation")))] for s, rs in st["rows"].items()}
    st["since"] = min(st["months"]) if st["months"] else None
    _save(st)
    n = sum(len(v) for v in st["rows"].values())
    print(f"[ann] {len(need)} month(s) due, {calls} calls, {len(st['rows'])} companies, {n} rows kept, {time.time() - t0:.0f}s")
    return st


def _hit(rows, key, since, extra=None):
    out = []
    for d, cat, txt, url, *_ in rows:
        if d < since:
            continue
        s = f"{cat} {txt}"
        if key == "G1":
            if not (X["G1cat"].search(s) and X["G1"].search(_BOILER.sub(" ", s))):
                continue
        elif not X[key].search(s):
            continue
        if extra and not extra(s):
            continue
        out.append({"d": d, "t": (txt or cat)[:160], "u": url})
    return out


def checks(st: dict, sym: str, today: date, bse: dict | None = None) -> dict | None:
    """-> {id: (mark, value, note, url)} or None when the company is not covered.
    BSE-only stocks use the BSE store (narrativ.bseann), same row format and rules."""
    if sym.endswith(".BO"):
        if not bse or sym not in (bse.get("loaded") or {}):
            return None
        rows = bse["rows"].get(sym, [])
    elif not sym.endswith(".NS") or len(st.get("months", {})) < MONTHS - 1:
        return None
    else:
        rows = st["rows"].get(sym, [])
    src = "BSE announcements (subject line)" if sym.endswith(".BO") else SRC
    d12, d24 = (today - timedelta(days=365)).isoformat(), (today - timedelta(days=730)).isoformat()
    not_sub = lambda s: not _SUBSID.search(s)
    res = {}

    def put(id_, hits, window):
        if hits:
            h = hits[0]
            more = f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""
            res[id_] = (1, f"{h['d']}: {h['t'][:110]}{more}", "filing found; subject line only, open the filing", h["u"])
        else:
            res[id_] = (2, f"none filed ({window})", src, None)

    put("A2", _hit(rows, "A2", d24, lambda s: not _NIL.search(s) and not _FINES.search(s) and not_sub(s)), "24 months")
    put("A4", _hit(rows, "A4", d24, lambda s: not _NOT_DEBTOR.search(s) and not_sub(s)), "24 months")
    put("A5", _hit(rows, "A5", d12), "12 months")
    put("G1", _hit(rows, "G1", d24, lambda s: not _ROUTINE_Q.search(s)), "24 months")
    put("G2", _hit(rows, "G2", d24, lambda s: not _PR.search(s) and not_sub(s)), "24 months")
    put("G3", _hit(rows, "G3", d24, not_sub), "24 months")
    cfo12, ceo12 = _hit(rows, "CFO", d12, not_sub), _hit(rows, "CEO", d12, not_sub)
    if cfo12 and ceo12:
        h = max(cfo12[0], ceo12[0], key=lambda x: x["d"])
        res["G4"] = (1, f"CFO exit {cfo12[0]['d']} and CEO/MD exit {ceo12[0]['d']}", "filings found; subject line only", h["u"])
    else:
        res["G4"] = (2, "not both in 12 months", src, None)
    cfo24, ceo24 = _hit(rows, "CFO", d24, not_sub), _hit(rows, "CEO", d24, not_sub)
    ex = sorted(cfo24 + ceo24, key=lambda x: x["d"], reverse=True)
    if len(ex) >= 2:
        res["C7"] = (1, f"{len(ex)} CEO/MD/CFO exits, latest {ex[0]['d']}", "filings found; subject line only", ex[0]["u"])
    elif ex:
        res["C7"] = (1, f"1 CEO/MD/CFO exit, {ex[0]['d']}: {ex[0]['t'][:90]}", "filing found; subject line only", ex[0]["u"])
    else:
        res["C7"] = (2, "no CEO/MD/CFO exit filed (24 months)", src, None)
    return res


def recent_events(st: dict, sym: str, limit: int | None = 20, info: bool = False) -> list[dict]:
    """Red and green events (info is left out to keep memory small) for any covered company, newest first.
    info=True: every typed row (used to re-type stored events: a red that a rule fix turns into info must be found)."""
    rows = st["rows"].get(sym, [])
    evs = events.from_announcements([{"date": d, "text": txt or cat, "category": cat, "url": url} for d, cat, txt, url, *_ in rows])
    return [e for e in evs if info or e["sev"] != "info"][:limit]


if __name__ == "__main__":  # Actions smoke test: python -m narrativ.announcements SYM...
    import sys
    st = refresh(date.today())
    for s in sys.argv[1:]:
        print(s, json.dumps(checks(st, s, date.today()), ensure_ascii=False)[:900])


PIT = re.compile(r"insider trading|regulation 7\s*\(2\)|reg\.?\s*7\s*\(2\)|\bsast\b|regulation 29\s*\(|regulation 31\s*\(|pledge|encumbrance", re.I)


def insider_filers(st: dict, since: str) -> set:
    """Symbols with an insider-trading / SAST / pledge disclosure announced on or after `since` (ISO date)."""
    return {s for s, rows in (st.get("rows") or {}).items() if any(r[0] >= since and PIT.search(f"{r[1]} {r[2]}") for r in rows)}
