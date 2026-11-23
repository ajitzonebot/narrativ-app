"""Probe NSE daily sources for Batch 1. Prints status, size and the first lines. Commits nothing."""
from datetime import date, timedelta
from narrativ.filings import NSESession

ns = NSESession()
d = date.today()
days = []
while len(days) < 3:
    d -= timedelta(days=1)
    if d.weekday() < 5:
        days.append(d)
cands = []
for x in days:
    cands += [f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{x:%d%m%Y}.csv",
              f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{x:%d%m%Y}.DAT"]
cands += [f"https://nsearchives.nseindia.com/content/indices/{n}.csv" for n in
          ("ind_nifty50list", "ind_nifty100list", "ind_nifty500list", "ind_niftymidcap150list", "ind_niftysmallcap250list",
           "ind_niftymicrocap250_list", "ind_niftytotalmarket_list")]
cands += ["https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
          "https://www.nseindia.com/api/reportGSM", "https://www.nseindia.com/api/reportASM",
          "https://www.nseindia.com/api/report-gsm", "https://www.nseindia.com/api/reportGSMList",
          "https://nsearchives.nseindia.com/content/cm/GSM.csv", "https://nsearchives.nseindia.com/content/equities/gsm.csv",
          "https://www.nseindia.com/api/live-analysis-suspended", "https://nsearchives.nseindia.com/content/equities/suspension.csv"]
for u in cands:
    try:
        r = ns.s.get(u, timeout=40)
        body = r.text if r.ok else ""
        print(f"\n### {r.status_code} {len(r.content)}B {r.headers.get('content-type','')} {u}")
        print(body[:700])
    except Exception as e:  # noqa: BLE001
        print(f"\n### ERR {u}: {e}")
