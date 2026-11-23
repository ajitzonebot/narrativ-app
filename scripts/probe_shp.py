"""Probe: pledge tags in a pledged company's SHP XBRL; MF members in a large company. Commits nothing."""
import csv, io, json, re, collections
import xml.etree.ElementTree as ET
from narrativ.filings import NSESession

ns = NSESession()
X = "{http://www.xbrl.org/2003/instance}"


def facts(sym):
    j = ns.get(f"https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={sym}")
    t = ns.get(j[0]["xbrl"], as_json=False)
    root = ET.fromstring(t.encode())
    ctx = {c.get("id"): "/".join(m.text.split(":")[-1] for m in c.iter() if m.tag.endswith("explicitMember")) or "-" for c in root.iter(X + "context")}
    f = collections.defaultdict(list)
    for el in root:
        if el.get("contextRef"):
            f[el.tag.split("}")[-1]].append((ctx.get(el.get("contextRef")), (el.text or "")[:30]))
    return j[0]["date"], f


p = ns.get("https://www.nseindia.com/api/corporate-pledgedata?index=equities")["data"]
hi = [r for r in p if float(r["percPromoterShares"] or 0) > 20][:3]
print("PLEDGED", [(r["comName"], r["percPromoterShares"], r["percTotShares"], r["totPromoterShares"], r["totPromoterHolding"], r["shp"]) for r in hi])
print("rows with promoter pledge > 0:", sum(float(r["percPromoterShares"] or 0) > 0 for r in p), "of", len(p))
eq = ns.s.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=60).text
names = {row["NAME OF COMPANY"].strip().lower(): row["SYMBOL"] for row in csv.DictReader(io.StringIO(eq))}
for r in hi[:1]:
    sym = names.get(r["comName"].strip().lower())
    print("\n### pledged", r["comName"], "->", sym)
    if sym:
        d, f = facts(sym)
        print(d)
        for k, v in f.items():
            if re.search(r"Pledg|Encumb|NonDisposal", k):
                print(" ", k, v[:12])
for sym in ("RELIANCE",):
    d, f = facts(sym)
    mem = sorted({m for v in f.values() for m, _ in v})
    print("\n### members", sym, d, mem)
    for k in ("ShareholdingAsAPercentageOfTotalNumberOfShares", "NumberOfShareholders"):
        print(k, [(m, x) for m, x in f[k] if m != "-"])
