"""Insolvency public announcements from IBBI (owner, 24 Nov 2026): one full load, then only new notices daily.

https://ibbi.gov.in/public-announcement lists every public announcement (CIRP, liquidation, voluntary liquidation,
pre-pack): date, corporate debtor, applicant, insolvency professional. robots.txt allows it. The full list (~15,000)
is read BACKFILL_PAGES pages a run until the end, then each day pages from the newest until one holds only known
notices. Store: Actions cache, with a durable copy in R2 (narrativ/dbsync.py DURABLE).

Matching is by normalised company name (the list has no CIN):
- a listed company as the corporate debtor of a CIRP or liquidation -> A4 fails (as the exchange filing would);
- a listed company as the applicant -> it is a creditor that filed against a debtor (receivables stress), shown only.
"""
import gzip
import json
import re
import time
from datetime import date, datetime
from pathlib import Path

URL = "https://ibbi.gov.in/public-announcement"
STORE = Path("data/source_cache/ibbi.json.gz")
UA = {"User-Agent": "Mozilla/5.0 (personal research; daily, a few pages)"}
BACKFILL_PAGES = 80
PAUSE = 1.0
_STOP = re.compile(r"\b(limited|ltd|private|pvt|the|and|company|co|corporation|corp|india|inc)\b|[^a-z0-9 ]")


def norm(name: str) -> str:
    n = _STOP.sub(" ", str(name or "").lower().replace("&", " and ").replace("(", " ").replace(")", " "))
    return " ".join(n.split())


def _cells(tr: str) -> list[str]:
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).replace("&amp;", "&").strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def page(n: int) -> list[dict] | None:
    import requests
    try:
        r = requests.get(URL, params={"page": n}, headers=UA, timeout=60)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[ibbi] page {n}: {str(e)[:100]}")
        return None
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        c = _cells(tr)
        if len(c) < 6:
            continue
        try:
            d = datetime.strptime(c[1], "%d-%m-%Y").date().isoformat()
        except ValueError:
            continue
        pdf = re.search(r'href="([^"]+\.pdf)"', tr)
        out.append({"type": c[0], "date": d, "debtor": c[3], "applicant": c[4], "ip": c[5],
                    "pdf": pdf.group(1) if pdf else None})
    return out


def _k(x: dict) -> str:
    return f"{x['date']}|{x['type']}|{x['debtor']}"


def refresh(max_minutes: float = 4) -> dict:
    st = {"rows": {}, "next_page": 1, "done": False}
    if STORE.exists():
        try:
            st = json.loads(gzip.decompress(STORE.read_bytes()))
        except Exception as e:  # noqa: BLE001
            print(f"[ibbi] store unreadable, reloading: {e}")
    t0, new = time.time(), 0
    for n in range(1, 60):  # daily: newest pages until one holds only known notices
        rows = page(n)
        if not rows:
            break
        fresh = [x for x in rows if _k(x) not in st["rows"]]
        for x in fresh:
            st["rows"][_k(x)] = x
        new += len(fresh)
        time.sleep(PAUSE)
        if not fresh or not st["done"] and n >= 2:
            break
    p = st.get("next_page", 1)
    while not st.get("done") and time.time() - t0 < max_minutes * 60 and p < st.get("next_page", 1) + BACKFILL_PAGES:
        rows = page(p)
        if rows is None:
            break
        if not rows:
            st["done"] = True
            break
        for x in rows:
            st["rows"].setdefault(_k(x), x)
        p += 1
        time.sleep(PAUSE)
    st["next_page"] = p
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(gzip.compress(json.dumps(st, separators=(",", ":"), ensure_ascii=False).encode(), mtime=0))  # same data, same bytes: R2 copy skipped
    print(f"[ibbi] {len(st['rows'])} notices ({new} new today), backfill {'done' if st.get('done') else f'at page {p}'}, {time.time() - t0:.0f}s")
    return st


def match(st: dict, names: dict[str, str], today: date, months: int = 24) -> dict[str, dict]:
    """names: {symbol: company name}. -> {symbol: {as_debtor: [...], as_applicant: [...]}} within `months`."""
    since = str(date(today.year - months // 12, today.month, 1))
    idx: dict[str, list[str]] = {}
    for s, n in names.items():
        k = norm(n)
        if len(k) >= 6:
            idx.setdefault(k, []).append(s)
    out: dict[str, dict] = {}
    for x in st.get("rows", {}).values():
        if x["date"] < since:
            continue
        for role, who in (("as_debtor", x["debtor"]), ("as_applicant", x["applicant"])):
            for s in idx.get(norm(who), []):
                if role == "as_applicant" and norm(x["debtor"]) == norm(who):
                    continue  # voluntary liquidation: the company applies for itself
                out.setdefault(s, {"as_debtor": [], "as_applicant": []})[role].append(
                    {"date": x["date"], "type": x["type"], "debtor": x["debtor"], "applicant": x["applicant"],
                     "url": x.get("pdf") and ("https://ibbi.gov.in" + x["pdf"] if x["pdf"].startswith("/") else x["pdf"])
                     or f"{URL}?title={x['debtor'][:60]}"})
    for v in out.values():
        for k in v:
            v[k].sort(key=lambda r: r["date"], reverse=True)
    return out


def a4(m: dict | None):
    """A4 when a listed company itself is the debtor of a CIRP / liquidation (not a voluntary liquidation)."""
    hits = [x for x in (m or {}).get("as_debtor", []) if "voluntary" not in x["type"].lower()]
    if not hits:
        return None
    h = hits[0]
    return (1, f"{h['date']}: {h['type']} (applicant {h['applicant']})", "IBBI public announcement", h["url"])
