"""Probe 5: market-wide lists for integrated governance and insider trading. Commits nothing."""
import json
from narrativ.filings import NSESession

ns = NSESession()
for u in ("https://www.nseindia.com/api/integrated-filing-results?index=equities&type=Integrated%20Filing-%20Governance&from_date=01-10-2026&to_date=13-11-2026",
          "https://www.nseindia.com/api/integrated-filing-results?index=equities&from_date=01-10-2026&to_date=13-11-2026",
          "https://www.nseindia.com/api/integrated-filing-results?index=equities&type=Integrated%20Filing-%20Governance&page=1&size=500",
          "https://www.nseindia.com/api/corporates-pit?index=equities&from_date=01-11-2026&to_date=13-11-2026&symbol=",
          "https://www.nseindia.com/api/corporates-pit?index=equities"):
    x = ns.get(u)
    meta = {k: v for k, v in x.items() if k != "data" and not isinstance(v, list)} if isinstance(x, dict) else {}
    d = x.get("data", x) if isinstance(x, dict) else x
    n = len(d) if d else 0
    syms = len({r.get("symbol") for r in d}) if d else 0
    dates = sorted({str(r.get("qe_Date") or r.get("date"))[:11] for r in d})[:3] + ["..."] + sorted({str(r.get("qe_Date") or r.get("date"))[:11] for r in d})[-3:] if d else []
    print(f"\n### n={n} symbols={syms} meta={meta} {dates}\n{u}")
