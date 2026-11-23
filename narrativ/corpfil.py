"""NSE corporate filings (Batch 3). One store: data/source_cache/corpfil.json (Actions cache) + R2 nse/corpfil.json.gz.
- dividends   : api/corporates-corporateActions (market-wide, by date range)                         -> C9
- preferential: api/corporate-further-issues-pref?index=FIPREF (market-wide, by date range)          -> T10
- governance  : api/integrated-filing-results type "Integrated Filing- Governance" (paged list) + XBRL:
                half-yearly loans / guarantees / security to promoter, promoter group, directors, KMPs -> G6
- insider     : api/corporates-pit?symbol= (per stock, weekly)                                       -> C3
Statement of deviation (G7) has no machine-readable NSE source found yet (probed 2026-11-14)."""
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .filings import NSESession

STORE = Path("data/source_cache/corpfil.json")
API = "https://www.nseindia.com/api"
GOV_TYPE = "Integrated Filing- Governance"
PIT_EVERY = 7        # days, stocks in the funnel
PIT_EVERY_OUT = 30   # days, stocks outside the funnel


def _d(s) -> str | None:
    s = str(s or "").strip()
    for f, n in (("%d-%b-%Y", 11), ("%d-%m-%Y", 10), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n].title(), f).date().isoformat()
        except ValueError:
            continue
    return None


def _f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _rows(x):
    return x.get("data", []) if isinstance(x, dict) else (x or [])


def _load() -> dict:
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def _ranges(start: date, end: date, days: int):
    a = start
    while a <= end:
        b = min(end, a + timedelta(days=days - 1))
        yield a, b
        a = b + timedelta(days=1)


# ------------------------------------------------------------------ dividends (corporate actions)
def _dividends(ns, st, today):
    s = st.setdefault("ca", {"asof": None, "rows": {}})
    start = date.fromisoformat(s["asof"]) - timedelta(days=10) if s["asof"] else today - timedelta(days=3 * 365 + 120)
    n = 0
    for a, b in _ranges(start, today, 365):
        x = ns.get(f"{API}/corporates-corporateActions", params={"index": "equities", "from_date": f"{a:%d-%m-%Y}", "to_date": f"{b:%d-%m-%Y}"})
        if x is None:
            print(f"[corp] corporate actions {a}..{b} failed")
            return
        for r in _rows(x):
            sub, sym, ex = r.get("subject") or "", r.get("symbol"), _d(r.get("exDate"))
            if sym and ex and re.search(r"dividend", sub, re.I):
                rs = s["rows"].setdefault(f"{sym}.NS", [])
                if [ex, sub[:80]] not in rs:
                    rs.append([ex, sub[:80]])
                    n += 1
    cut = (today - timedelta(days=4 * 365)).isoformat()
    s["rows"] = {k: sorted(v for v in vs if v[0] >= cut) for k, vs in s["rows"].items()}
    s["asof"] = today.isoformat()
    print(f"[corp] dividends: {n} new, {len(s['rows'])} companies")


def _bse_dividends(st, today, bse_codes: dict, max_minutes: float = 3):
    """BSE-only stocks: dividends from BSE corporate actions (bse library). First load per stock (full history, one call
    each, within the time budget); every run, BSE's current list of upcoming actions for all companies (one call) adds
    new ones. BSE's all-company call ignores dates, so it is used only for that daily list."""
    if not bse_codes:
        return
    from bse import BSE
    s = st.setdefault("ca_bse", {"loaded": []})
    rows = st.setdefault("ca", {"asof": None, "rows": {}})["rows"]
    by_code = {str(c).lstrip("0"): sym for sym, c in bse_codes.items() if c}
    loaded, t0, n, first = set(s.get("loaded") or []), time.time(), 0, 0
    cut = (today - timedelta(days=4 * 365)).isoformat()

    def add(sym, r):
        nonlocal n
        sub, ex = r.get("Purpose") or "", _d(str(r.get("Ex_date") or "").replace(" ", "-"))
        if sym and ex and ex >= cut and re.search(r"dividend", sub, re.I):
            rs = rows.setdefault(sym, [])
            if [ex, sub[:80]] not in rs:
                rs.append([ex, sub[:80]])
                n += 1
    with BSE(download_folder=Path("data/exchange_tmp")) as b:
        for r in b.actions() or []:  # upcoming actions, all companies
            add(by_code.get(str(r.get("scrip_code") or "").lstrip("0")), r)
        for sym, code in bse_codes.items():
            if sym in loaded or not code or time.time() - t0 > max_minutes * 60:
                continue
            try:
                for r in b.actions(scripcode=str(code)) or []:
                    add(sym, r)
                loaded.add(sym)
                first += 1
            except Exception as e:  # noqa: BLE001
                print(f"[corp] BSE actions {sym}: {e}")
    s["loaded"] = sorted(loaded)
    s["asof"] = today.isoformat()
    print(f"[corp] BSE dividends: {n} new ({first} stocks loaded with full history), {len(loaded & set(bse_codes))} of {len(bse_codes)} "
          f"BSE-only companies covered, {sum(1 for x in bse_codes if x in rows)} with dividends")


# ------------------------------------------------------------------ preferential issues
def _preferential(ns, st, today):
    s = st.setdefault("pref", {"asof": None, "rows": {}})
    start = date.fromisoformat(s["asof"]) - timedelta(days=15) if s["asof"] else today - timedelta(days=2 * 365)
    n = 0
    for a, b in _ranges(start, today, 90):
        x = ns.get(f"{API}/corporate-further-issues-pref", params={"index": "FIPREF", "from_date": f"{a:%d-%m-%Y}", "to_date": f"{b:%d-%m-%Y}"})
        if x is None:
            print(f"[corp] preferential {a}..{b} failed")
            return
        for r in _rows(x):
            sym, al = r.get("nseSymbol"), _d(r.get("dateOfAllotmentOfShares"))
            if not sym or not al:
                continue
            rec = [al, _f(r.get("offerPricePerSecurity")), _f(r.get("totalNumOfSharesAllotted")), _f(r.get("amountRaised")), r.get("issueType")]
            rs = s["rows"].setdefault(f"{sym}.NS", [])
            if rec not in rs:
                rs.append(rec)
                n += 1
    s["asof"] = today.isoformat()
    print(f"[corp] preferential issues: {n} new, {len(s['rows'])} companies")


# ------------------------------------------------------------------ governance: loans / guarantees / security to related persons
_GOV = re.compile(r"<[a-z0-9-]+:((?:Aggregate|BalanceOutstanding)[A-Za-z]+)\b[^>]*>([^<]*)<")


def _gov_parse(xml: str) -> dict | None:
    """Sums by kind (loan / guarantee / security) and measure (advanced in 6 months / outstanding), all related persons, ₹ crore."""
    vals = _GOV.findall(xml)
    if not vals:
        return None
    out = {}
    for name, v in vals:
        x = _f(v)
        if x is None:
            continue
        kind = "loan" if "Loan" in name and "Security" not in name else "guarantee" if "Guarantee" in name else "security"
        meas = "out" if name.startswith("Balance") else "adv"
        who = "promoter" if "ToPromoter" in name or "ByPromoter" in name else "director_kmp"
        k = f"{kind}_{meas}"
        out[k] = round(out.get(k, 0) + x / 1e7, 2)
        if who == "promoter":
            out[f"{k}_prom"] = round(out.get(f"{k}_prom", 0) + x / 1e7, 2)
    return out


def _governance(ns, st, today, symbols, deadline):
    s = st.setdefault("gov", {"asof": None, "list": {}, "parsed": {}})
    start = date.fromisoformat(s["asof"]) - timedelta(days=20) if s["asof"] else today - timedelta(days=400)
    page, got = 1, 0
    while time.time() < deadline:
        x = ns.get(f"{API}/integrated-filing-results", params={"index": "equities", "type": GOV_TYPE, "from_date": f"{start:%d-%m-%Y}",
                                                                 "to_date": f"{today:%d-%m-%Y}", "page": page, "size": 500})
        rows = _rows(x)
        if not rows:
            break
        for r in rows:
            sym, qe, u = r.get("symbol"), _d(r.get("qe_Date")), r.get("xbrl")
            if sym and qe and u:
                lst = s["list"].setdefault(f"{sym}.NS", {})
                lst[qe] = u  # a revised filing for the same quarter replaces the original
        got += len(rows)
        tot = (x or {}).get("totalCount") if isinstance(x, dict) else None
        if len(rows) < 500 or (tot and got >= tot):
            break
        page += 1
    else:
        print("[corp] governance list stopped at the time budget")
    if got:
        s["asof"] = today.isoformat()
    fetched = 0
    for sym in symbols:
        if time.time() > deadline:
            break
        lst = s["list"].get(sym) or {}
        p = s["parsed"].get(sym) or {}
        for qe in sorted(lst, reverse=True)[:3]:  # newest first; quarterly filings without the half-yearly annexure are skipped
            if qe <= (p.get("date") or "") or qe in (p.get("checked") or []):
                break
            t = ns.get(lst[qe], as_json=False)
            fetched += 1
            if not t:
                break
            g = _gov_parse(t)
            if g is not None and any(k.endswith("_out") or k.endswith("_adv") for k in g):
                s["parsed"][sym] = {"date": qe, **g, "src": lst[qe], "checked": []}
                break
            p.setdefault("checked", []).append(qe)
            s["parsed"][sym] = p
    print(f"[corp] governance: {got} list rows, {fetched} filings read, {len(s['parsed'])} companies parsed")


# ------------------------------------------------------------------ insider trading (per stock)
def _insider(ns, st, today, symbols, deadline, filers: set | None = None, scope: set | None = None):
    """Per stock (NSE has no market-wide insider list). Refreshed at once when the stock announced an insider-trading /
    SAST / pledge disclosure since its last check (`filers`); otherwise weekly for stocks in `scope` (the funnel) and
    every PIT_EVERY_OUT days for the rest."""
    s = st.setdefault("pit", {})
    calls, trig = 0, 0
    cut = (today - timedelta(days=2 * 365)).isoformat()
    filers, scope = filers or set(), scope
    order = [x for x in symbols if x in filers] + [x for x in symbols if x not in filers]
    for sym in order:
        if time.time() > deadline:
            break
        rec = s.get(sym)
        try:
            age = (today - date.fromisoformat(rec["checked"])).days if rec and rec.get("v") == 2 else None
        except Exception:  # noqa: BLE001
            age = None
        every = PIT_EVERY if scope is None or sym in scope else PIT_EVERY_OUT
        if age is not None and not (sym in filers and age >= 1) and age < every:
            continue
        trig += sym in filers
        x = ns.get(f"{API}/corporates-pit", params={"index": "equities", "symbol": sym[:-3]})
        calls += 1
        if x is None:
            continue
        rows = []
        for r in _rows(x):
            dt = _d(r.get("acqfromDt")) or _d(r.get("intimDt")) or _d(r.get("date"))
            if not dt or dt < cut:  # `exchange` is where the trade was done (NSE and BSE rows are separate trades)
                continue
            rows.append([dt, r.get("personCategory") or "", r.get("tdpTransactionType") or "", r.get("acqMode") or "",
                         _f(r.get("secAcq")), _f(r.get("secVal")), (r.get("secType") or "")[:20]])
        s[sym] = {"v": 2, "checked": today.isoformat(), "rows": sorted(rows, key=lambda r: r[0], reverse=True)[:200]}
    done = sum(1 for x in symbols if x in s)
    print(f"[corp] insider trades: {calls} stocks refreshed ({trig} after an insider/SAST announcement), {done} of {len(symbols)} covered")


def refresh(symbols: list[str], today: date, max_minutes: float = 8, bse_codes: dict | None = None,
            insider_filers: set | None = None, scope: set | None = None) -> dict:
    st = _load()
    t0 = time.time()
    try:
        ns = NSESession()
    except Exception as e:  # noqa: BLE001
        print(f"[corp] session failed: {e}")
        return st
    nse = [s for s in symbols if s.endswith(".NS")]
    for name, fn in (("dividends", lambda: _dividends(ns, st, today)), ("BSE dividends", lambda: _bse_dividends(st, today, bse_codes)),
                     ("preferential", lambda: _preferential(ns, st, today))):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"[corp] {name} failed: {e}")
    deadline = t0 + max_minutes * 60
    try:
        _governance(ns, st, today, nse, t0 + max_minutes * 60 * 0.45)
    except Exception as e:  # noqa: BLE001
        print(f"[corp] governance failed: {e}")
    try:
        _insider(ns, st, today, nse, deadline, insider_filers, scope)
    except Exception as e:  # noqa: BLE001
        print(f"[corp] insider failed: {e}")
    st["pit_since"] = (today - timedelta(days=1)).isoformat()  # next run: insider announcements from yesterday on
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(st, separators=(",", ":")))
    print(f"[corp] done in {time.time() - t0:.0f}s")
    return st


# ------------------------------------------------------------------ per-stock view for the funnel
PROMO = re.compile(r"promoter", re.I)


def stats(st: dict, sym: str, today: date) -> dict:
    out = {"ca_ok": bool((st.get("ca") or {}).get("asof")) and (not sym.endswith(".BO") or sym in set((st.get("ca_bse") or {}).get("loaded") or [])), "pref_ok": bool((st.get("pref") or {}).get("asof")) and sym.endswith(".NS"),
           "gov_ok": bool((st.get("gov") or {}).get("asof")) and sym.endswith(".NS"), "pit_ok": sym in (st.get("pit") or {})}
    # C9: dividend ex-dates in each of the last three rolling 12-month periods (final dividends are paid after the year closes)
    divs = sorted(d for d, _ in (st.get("ca") or {}).get("rows", {}).get(sym, []))
    wins = [((today - timedelta(days=365 * (i + 1))).isoformat(), (today - timedelta(days=365 * i)).isoformat()) for i in range(3)]
    hit = [any(a < d <= b for d in divs) for a, b in wins]
    out["div_years"] = sum(hit)
    out["div_last"] = divs[-1] if divs else None
    # T10: preferential issues in the last 12 months
    cut = (today - timedelta(days=365)).isoformat()
    out["pref"] = sorted([r for r in (st.get("pref") or {}).get("rows", {}).get(sym, []) if r[0] >= cut], reverse=True)
    # G6: latest half-yearly related-person loans / guarantees / security
    g = (st.get("gov") or {}).get("parsed", {}).get(sym)
    out["gov"] = g if g and g.get("date") else None  # a record holding only checked quarters (no annexure found) is not data
    out["gov_absent"] = len((g or {}).get("checked") or []) if g and not g.get("date") else 0  # filings read that carry no annexure
    # C3: promoter / promoter-group open-market trades, last 12 months
    rows = [r for r in ((st.get("pit") or {}).get(sym) or {}).get("rows", []) if r[0] >= cut and PROMO.search(r[1]) and "equity" in (r[6] or "").lower()]
    mkt = [r for r in rows if re.search(r"market", r[3], re.I)]
    out["prom_buy"] = round(sum((r[5] or 0) for r in mkt if r[2].lower().startswith("buy")) / 1e7, 2)
    out["prom_sell"] = round(sum((r[5] or 0) for r in mkt if r[2].lower().startswith("sell")) / 1e7, 2)
    out["prom_trades"] = len(mkt)
    return out
