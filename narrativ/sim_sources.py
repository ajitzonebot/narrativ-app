"""Probe (owner, 24 Nov 2026): can GitHub Actions read three new free sources, and what do they return? Changes no rule.
1 NSE system-driven credit-rating disclosures (agencies upload by ISIN since Aug 2025)
2 IBBI public announcements (insolvency notices)
3 NSDL daily FPI flows (via nselib)
Writes docs/research/sim_sources.md (public logs are quiet). python -m narrativ.sim_sources"""
import collections
import json
import re
from datetime import date, timedelta
from pathlib import Path

OUT = []


def p(*a):
    OUT.append(" ".join(str(x) for x in a))


def nse_ratings():
    from narrativ.filings import NSESession
    ns = NSESession()
    t = date.today()
    for params in ({"index": "equities", "from_date": (t - timedelta(days=30)).strftime("%d-%m-%Y"), "to_date": t.strftime("%d-%m-%Y")},
                   {"index": "equities"}):
        try:
            j = ns.get("https://www.nseindia.com/api/credit-rating-sdd-reg30", params=params)
        except Exception as e:  # noqa: BLE001
            p("  error", params, type(e).__name__, str(e)[:200])
            continue
        rows = j if isinstance(j, list) else (j or {}).get("data") or []
        p(f"  params {params}: {type(j).__name__}, {len(rows)} rows" + (f", keys {list(j)[:8]}" if isinstance(j, dict) else ""))
        if rows:
            p("  fields:", list(rows[0].keys()))
            for k in ("classOfAction", "currentAction", "typeOfRating", "creditAgencyName", "outlook"):
                p(f"  {k}:", collections.Counter(str(r.get(k)) for r in rows).most_common(12))
            for r in rows[:4]:
                p("  sample:", json.dumps(r, ensure_ascii=False)[:700])
            p("  symbols:", len({r.get("symbol") for r in rows}), "dates:", min(str(r.get("broadcastDateTime")) for r in rows), "..", max(str(r.get("broadcastDateTime")) for r in rows))
            break


def ibbi():
    import requests
    r = requests.get("https://ibbi.gov.in/public-announcement?page=1", headers={"User-Agent": "Mozilla/5.0 (personal research)"}, timeout=60)
    p(f"  page 1: {r.status_code}, {len(r.text)} chars")
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)
    p(f"  rows: {len(trs)}")
    for tr in trs[:4]:
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        links = re.findall(r'href="([^"]+)"', tr)
        p("  ", cells[:8], links[:2])
    m = re.search(r"page=(\d+)[^>]*>\s*(?:Last|&raquo;|»)", r.text)
    p("  last page link:", m.group(1) if m else "not found")


def nsdl():
    import nselib
    p("  nselib", getattr(nselib, "__version__", "?"))
    found = []
    for mod in ("nselib.capital_market", "nselib.derivatives", "nselib.indices", "nselib.debt", "nselib"):
        try:
            m = __import__(mod, fromlist=["x"])
            found += [f"{mod}.{n}" for n in dir(m) if re.search(r"fpi|nsdl|fii|dii", n, re.I)]
        except Exception as e:  # noqa: BLE001
            p("  import", mod, type(e).__name__)
    p("  functions:", found)
    for name in found:
        if "fpi" not in name.lower():
            continue
        mod, fn = name.rsplit(".", 1)
        try:
            f = getattr(__import__(mod, fromlist=["x"]), fn)
            import inspect
            p("  ", name, str(inspect.signature(f)))
        except Exception as e:  # noqa: BLE001
            p("  ", name, type(e).__name__, str(e)[:120])


def main():
    for title, fn in (("NSE credit-rating SDD", nse_ratings), ("IBBI public announcements", ibbi), ("NSDL FPI via nselib", nsdl)):
        p(f"## {title}")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            p("  failed:", type(e).__name__, str(e)[:300])
    Path("docs/research/sim_sources.md").write_text("```\n" + "\n".join(OUT) + "\n```\n")


if __name__ == "__main__":
    main()
