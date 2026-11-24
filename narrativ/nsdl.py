"""Foreign portfolio investor (FPI) equity flows from NSDL (owner, 24 Nov 2026): long history for the market mood.

NSE's FII/DII endpoint (mood.py) gives one day at a time and we only have days since 12 Nov 2026. NSDL publishes:
- monthly net FPI investment per calendar year since 2002 (Yearwise.aspx?RptType=6; other years by the page's year
  dropdown): loaded once, then the current and last year refreshed monthly;
- the latest day's trades (Latest.aspx): appended daily.
Equity net, INR crore (stock exchange + primary market). NSDL is settlement-reported (trades up to the previous day), so
its days differ slightly from NSE's provisional trade-date figures. Stored in data/nsdl_fpi.json (small).
Shown with the market mood; no score uses it until the replay shows it helps.
"""
import json
import re
import time
from datetime import date, datetime
from pathlib import Path

BASE = "https://www.fpi.nsdl.co.in/web/Reports/"
OUT = Path("data/nsdl_fpi.json")
UA = {"User-Agent": "Mozilla/5.0 (personal research; daily, one page)"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
FIRST_YEAR = 2002


def _text(html: str) -> str:
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ")


def _num(s: str) -> float:
    s = s.replace(",", "")
    return -float(s.strip("()")) if s.startswith("(") else float(s)


def parse_monthly(html: str) -> tuple[int | None, dict[str, float]]:
    t = _text(html)
    m = re.search(r"Calendar Year - (\d{4})", t)
    year = int(m.group(1)) if m else None
    body = t[m.end():] if m else t
    out = {}
    for i, mon in enumerate(MONTHS):
        x = re.search(rf"\b{mon}\s+(\(?-?[\d,]+(?:\.\d+)?\)?)", body)
        if x and year:
            out[f"{year}-{i + 1:02d}"] = _num(x.group(1))
    return year, out


def parse_latest(html: str) -> tuple[str | None, float | None]:
    t = _text(html)
    m = re.search(r"Daily Trends in FPI Investments on (\d{2}-\w{3}-\d{4})", t)
    e = re.search(r"\bEquity\b.*?Sub-total\s+(\(?[\d,.]+\)?)\s+(\(?[\d,.]+\)?)\s+(\(?-?[\d,.]+\)?)", t)
    if not m or not e:
        return None, None
    return datetime.strptime(m.group(1), "%d-%b-%Y").date().isoformat(), _num(e.group(3))


def _form(html: str) -> dict:
    return {k: v for k, v in re.findall(r'<input type="hidden" name="(__[A-Z]+)" id="__[A-Z]+" value="([^"]*)"', html)}


def refresh(today: date, max_minutes: float = 3) -> dict:
    import requests
    st = json.loads(OUT.read_text()) if OUT.exists() else {"monthly": {}, "daily": {}, "years_loaded": []}
    s, t0 = requests.Session(), time.time()
    s.headers.update(UA)
    try:
        d, net = parse_latest(s.get(BASE + "Latest.aspx", timeout=60).text)
        if d and net is not None:
            st["daily"][d] = net
        page = s.get(BASE + "Yearwise.aspx?RptType=6", timeout=60).text
        y, mo = parse_monthly(page)
        st["monthly"].update(mo)
        want = [yr for yr in range(FIRST_YEAR, today.year) if yr not in st["years_loaded"] or yr == today.year - 1 and today.month == 1]
        for yr in want:
            if time.time() - t0 > max_minutes * 60:
                break
            f = _form(page)
            f.update({"__EVENTTARGET": "ddl", "__EVENTARGUMENT": "", "ddl": str(yr)})
            page = s.post(BASE + "Yearwise.aspx?RptType=6", data=f, timeout=60).text
            y, mo = parse_monthly(page)
            if y == yr and mo:
                st["monthly"].update(mo)
                st["years_loaded"] = sorted(set(st["years_loaded"]) | {yr})
            time.sleep(1.0)
    except Exception as e:  # noqa: BLE001
        print(f"[nsdl] {str(e)[:150]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(st, indent=0, sort_keys=True))
    print(f"[nsdl] {len(st['monthly'])} months ({min(st['monthly'], default='-')}..{max(st['monthly'], default='-')}), {len(st['daily'])} days")
    return st


def summary(st: dict | None, today: date) -> dict | None:
    """Last full month's FPI equity net and its percentile among all months; month to date and last 10 days from the daily file."""
    if not st or not st.get("monthly"):
        return None
    cur = f"{today.year}-{today.month:02d}"
    full = {k: v for k, v in st["monthly"].items() if k < cur}
    if not full:
        return None
    last = max(full)
    vals = sorted(full.values())
    pct = round(sum(1 for v in vals if v <= full[last]) / len(vals) * 100)
    days = sorted(st.get("daily", {}).items())
    return {"month": last, "net_cr": full[last], "percentile": pct, "months": len(vals),
            "month_to_date_cr": st["monthly"].get(cur), "last_days_cr": round(sum(v for _, v in days[-10:]), 1) if days else None,
            "days": len(days), "source": "NSDL FPI monthly net investment, equity (since 2002)"}
