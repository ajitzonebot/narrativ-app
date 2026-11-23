"""Step 1 measurement: last N days of ALL-company announcements (NSE + BSE) through the D1 document funnel.

Output: probe/doc_funnel_30d.json. No PDFs are parsed for content; a random sample is only checked for a text layer.
Usage: python -m scripts.measure_docs [days] [pdf_sample]
"""
import collections
import io
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from narrativ import docfunnel
from narrativ.filings import NSESession

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
SAMPLE = int(sys.argv[2]) if len(sys.argv) > 2 else 80
OUT = Path("probe/doc_funnel_30d.json")
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com", "Accept": "application/json"}


def funnel_sets():
    J = lambda p: json.loads(Path(p).read_text()) if Path(p).exists() else {}
    picks = J("docs/data/picks.json").get("picks", [])
    researched = set(J("docs/data/research.json"))
    queued = {i["symbol"] for i in J("docs/data/queue.json").get("items", [])}
    top = {p["s"] for p in sorted([p for p in picks if not p.get("out")], key=lambda p: -(p.get("pr") or 0))[:80]}
    return researched, queued, top, {p["s"] for p in picks}


def nse_rows(ns, d0, d1):
    rows = []
    d = d0
    while d <= d1:
        f = d.strftime("%d-%m-%Y")
        for idx in ("equities", "sme"):
            js = ns.get("https://www.nseindia.com/api/corporate-announcements", params={"index": idx, "from_date": f, "to_date": f})
            for a in js if isinstance(js, list) else []:
                rows.append({"x": "NSE", "sym": f"{a.get('symbol')}.NS", "date": str(d), "cat": a.get("desc"), "text": a.get("attchmntText"),
                             "url": a.get("attchmntFile"), "size": a.get("fileSize")})
            time.sleep(0.5)
        d += timedelta(days=1)
    return rows


def bse_rows(d0, d1, code2sym, max_pages=80):
    """All-company BSE announcements via the bse library (same client the daily run uses per stock)."""
    from datetime import datetime
    from bse import BSE
    rows, calls = [], 0
    with BSE(download_folder=Path("data/exchange_tmp")) as b:
        d = d0
        while d <= d1:
            dt = datetime.combine(d, datetime.min.time())
            for pg in range(1, max_pages + 1):
                try:
                    res = b.announcements(page_no=pg, from_date=dt, to_date=dt)
                    calls += 1
                    t = res.get("Table", []) if isinstance(res, dict) else []
                except Exception as e:  # noqa: BLE001
                    print(f"[measure] BSE {d} p{pg}: {e}")
                    t = []
                for a in t:
                    code = str(a.get("SCRIP_CD") or "")
                    rows.append({"x": "BSE", "sym": code2sym.get(code, f"BSE:{code}"), "date": str(d), "cat": a.get("CATEGORYNAME"),
                                 "text": a.get("HEADLINE") or a.get("NEWSSUB"),
                                 "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{a['ATTACHMENTNAME']}" if a.get("ATTACHMENTNAME") else None,
                                 "size": a.get("Fld_Attachsize")})
                if len(t) < 50:
                    break
            d += timedelta(days=1)
    print(f"[measure] BSE {len(rows)} rows, {calls} calls")
    return rows


def text_layer(ns, url):
    from pypdf import PdfReader
    try:
        r = ns.s.get(url, timeout=60) if "nseindia" in url else requests.get(url, headers=BSE_H, timeout=60)
        if not r.ok or not r.content.startswith(b"%PDF"):
            return {"url": url, "ok": False, "why": f"http {r.status_code}" if not r.ok else "not a pdf"}
        rd = PdfReader(io.BytesIO(r.content))
        n = len(rd.pages)
        chars = sum(len((p.extract_text() or "").strip()) for p in rd.pages[:3])
        return {"url": url, "ok": True, "pages": n, "kb": len(r.content) // 1024, "chars_first3": chars, "has_text": chars >= 200}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "ok": False, "why": str(e)[:80]}


def main():
    today = date.today()
    d0 = today - timedelta(days=DAYS)
    researched, queued, top, universe = funnel_sets()
    focus = researched | queued | top
    code2sym = {v: k for k, v in json.loads(Path("data/bse_codes.json").read_text()).items()} if Path("data/bse_codes.json").exists() else {}
    ns = NSESession()
    t0 = time.time()
    rows = nse_rows(ns, d0, today)
    print(f"[measure] NSE {len(rows)} rows, {time.time() - t0:.0f}s")
    rows += bse_rows(d0, today, code2sym)
    # one row per filing: drop exact repeats (same exchange, url)
    seen, uniq = set(), []
    for r in rows:
        k = (r["x"], r["url"] or f"{r['sym']}|{r['date']}|{r['text']}")
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    rows = uniq
    by_group, by_rule, unknown = collections.Counter(), collections.Counter(), collections.Counter()
    by_x = collections.defaultdict(collections.Counter)
    d2 = collections.Counter()
    for r in rows:
        g, n = docfunnel.classify(r["cat"], r["text"])
        r["g"], r["rule"] = g, n
        by_group[g] += 1
        by_rule[(g, n)] += 1
        by_x[r["x"]][g] += 1
        if n == "Unknown":
            unknown[(r["cat"] or "")[:80]] += 1
        if r["x"] == "BSE" and not str(r["sym"]).endswith(".BO"):
            by_x["BSE (also on NSE or not in universe)"][g] += 1
            continue
        if g == "download":
            d2["all_companies"] += 1
            if r["sym"] in universe:
                d2["universe"] += 1
            if r["sym"] in focus:
                d2["funnel_focus"] += 1
    random.seed(7)
    dl = [r for r in rows if r["g"] == "download" and r["url"] and str(r["url"]).lower().endswith(".pdf")]
    sample = random.sample(dl, min(SAMPLE, len(dl)))
    checks = []
    for r in sample:
        c = text_layer(ns, r["url"])
        c["rule"] = r["rule"]
        checks.append(c)
        time.sleep(0.5)
    okc = [c for c in checks if c["ok"]]
    n = len(rows) or 1
    res = {
        "from": str(d0), "to": str(today), "days": DAYS, "filings": len(rows),
        "by_exchange": {x: dict(c) for x, c in by_x.items()},
        "groups": {g: {"n": c, "pct": round(100 * c / n, 1)} for g, c in by_group.most_common()},
        "rules": [{"group": g, "rule": r, "n": c} for (g, r), c in by_rule.most_common()],
        "unknown_top_categories": [{"category": k, "n": c} for k, c in unknown.most_common(40)],
        "unknown_examples": [{"cat": r["cat"], "text": (r["text"] or "")[:160]} for r in rows if r["rule"] == "Unknown"][:40],
        "download_volume": {**dict(d2), "focus_set_size": len(focus),
                            "note": "funnel_focus = researched + queued + top 80 by priority; only these get PDFs under D2"},
        "pdf_sample": {"checked": len(checks), "fetched": len(okc), "with_text": sum(c["has_text"] for c in okc),
                       "scanned_or_empty": sum(not c["has_text"] for c in okc),
                       "median_pages": sorted(c["pages"] for c in okc)[len(okc) // 2] if okc else None,
                       "median_kb": sorted(c["kb"] for c in okc)[len(okc) // 2] if okc else None, "items": checks},
        "seconds": round(time.time() - t0),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    print(json.dumps({k: res[k] for k in ("filings", "by_exchange", "groups", "download_volume")}, indent=1))
    print(json.dumps({k: v for k, v in res["pdf_sample"].items() if k != "items"}))


if __name__ == "__main__":
    main()
