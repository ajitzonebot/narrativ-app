"""Company-filed quarterly results (XBRL) from NSE: the primary source for every financial number in the app.

Two NSE listings cover the full history:
  /api/corporates-financial-results   Reg-33 filings up to the Dec-2024 quarter (in-bse-fin taxonomy)
  /api/integrated-filing-results      SEBI Integrated Filing from the Mar-2025 quarter (in-capmkt taxonomy)
Both use the same tag names and context convention (OneD = quarter, FourD = year to date, OneI = balance-sheet date).

Stored per stock in data/financials/<SYMBOL>.json as parsed numbers only (no raw files):
  {"quarters": {"2026-09-30": {"Consolidated": {...}, "Standalone": {...}}}, "checked": "...", ...}
Every quarter keeps the filing URL and filing date, so each app value can show where it came from.
BSE-only stocks are not covered here yet; metrics fall back to Yahoo statements, labelled as such.
"""
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config

DIR = Path("data/financials")
BASE = "https://www.nseindia.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json,text/html,application/xml,*/*", "Accept-Language": "en-US,en;q=0.9",
      "Referer": BASE + "/companies-listing/corporate-integrated-filing"}
QUARTERS_KEEP = 16  # 4 years: 3-year CAGR on full-year numbers + TTM comparisons

# tag -> short key. Alternatives listed first-match-wins per key.
DURATION_TAGS = {
    "RevenueFromOperations": "rev", "InterestEarned": "rev_bank", "OtherIncome": "oi", "Income": "income",
    "Expenses": "exp", "FinanceCosts": "fin", "InterestExpended": "fin_bank",
    "DepreciationDepletionAndAmortisationExpense": "dep", "ProfitBeforeTax": "pbt",
    "ProfitLossFromOrdinaryActivitiesBeforeTax": "pbt_bank", "TaxExpense": "tax",
    "ProfitLossForPeriod": "pat", "ProfitLossForThePeriod": "pat_bank", "NetProfitLossForThePeriod": "pat_bank2",
    "ExceptionalItemsBeforeTax": "exceptional", "ExceptionalItems": "exceptional_bank",
    "ProfitBeforeExceptionalItemsAndTax": "pbt_pre_exc",
    "BasicEarningsPerShareAfterExtraordinaryItems": "eps_basic_bank", "DilutedEarningsPerShareAfterExtraordinaryItems": "eps_bank",
    "OperatingProfitBeforeProvisionAndContingencies": "ppop", "ProvisionsOtherThanTaxAndContingencies": "provisions",
    "GrossNonPerformingAssets": "gnpa", "NonPerformingAssets": "nnpa", "PercentageOfGrossNpa": "gnpa_ratio",
    "PercentageOfNpa": "nnpa_ratio", "CET1Ratio": "cet1_ratio", "AdditionalTier1Ratio": "at1_ratio", "ProfitOrLossAttributableToOwnersOfParent": "pat_owners",
    "ProfitOrLossAttributableToNonControllingInterests": "pat_minority",
    "BasicEarningsLossPerShareFromContinuingOperations": "eps_basic",
    "DilutedEarningsLossPerShareFromContinuingOperations": "eps",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_basic_all",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_all",
    "PaidUpValueOfEquityShareCapital": "share_cap", "FaceValueOfEquityShareCapital": "fv",
    "CashFlowsFromUsedInOperatingActivities": "cfo", "NetCashFlowsFromUsedInOperatingActivities": "cfo_net",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "capex",
    "PurchaseOfPropertyPlantAndEquipment": "capex_alt",
    "CashFlowsFromUsedInInvestingActivities": "cfi", "CashFlowsFromUsedInFinancingActivities": "cff",
    "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": "lease_pay",
}
INSTANT_TAGS = {
    "Equity": "equity", "EquityAttributableToOwnersOfParent": "equity_owners", "EquityShareCapital": "eq_cap",
    "NonControllingInterest": "minority", "BorrowingsCurrent": "borr_cur", "BorrowingsNoncurrent": "borr_ncur",
    "CashAndCashEquivalents": "cash", "BankBalanceOtherThanCashAndCashEquivalents": "bank_bal",
    "CurrentInvestments": "inv_cur", "NoncurrentInvestments": "inv_ncur",
    "TradeReceivablesCurrent": "recv", "TradeReceivablesNoncurrent": "recv_ncur", "Inventories": "inventory",
    "CapitalWorkInProgress": "cwip", "PropertyPlantAndEquipment": "ppe", "Assets": "assets",
    "CurrentAssets": "cur_assets", "Capital": "eq_cap_bank", "ReservesAndSurplus": "reserves_bank", "Borrowings": "borr_total",
    "Advances": "advances", "Deposits": "deposits", "Investments": "investments_bank",
    "LeaseLiabilitiesNoncurrent": "lease_ncur", "NoncurrentLeaseLiabilities": "lease_ncur",
    "LeaseLiabilitiesCurrent": "lease_cur", "CurrentLeaseLiabilities": "lease_cur",
    "CashAndBalancesWithReserveBankOfIndia": "cash_rbi", "BalancesWithBanksAndMoneyAtCallAndShortNotice": "bank_call", "CurrentLiabilities": "cur_liab", "Liabilities": "liabilities",
}
_CTX = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)
_FACT = re.compile(r"<[\w-]+:(\w+)\b([^>]*?)>([^<]{1,40})</[\w-]+:\1>")
_DATE_FMT = ("%d-%b-%Y", "%d-%B-%Y")
_PERIOD_START = re.compile(r'<[\w-]+:DateOfStartOfReportingPeriod\b[^>]*contextRef="([^"]+)"[^>]*>([^<]+)<')
_ROUNDING = re.compile(r"<[\w-]+:LevelOfRounding(?:UsedInFinancialStatements)?\b[^>]*>([^<]+)<")
YTD_CHK = 1  # parser version: 1 reads the Reg-33 year-to-date column (mis-dated FourD context)


def _iso(s: str | None) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


class NSESession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.calls = 0
        self._warm()

    def _warm(self):
        for u in (BASE + "/", BASE + "/companies-listing/corporate-integrated-filing"):
            try:
                self.s.get(u, timeout=20)
            except Exception:  # noqa: BLE001
                pass

    def get(self, url, params=None, as_json=True, tries=3):
        for i in range(tries):
            try:
                r = self.s.get(url, params=params, timeout=40)
                self.calls += 1
                if r.status_code in (401, 403):
                    self._warm()
                    time.sleep(2 + 3 * i)
                    continue
                if r.status_code == 429:
                    time.sleep(10 * (i + 1))
                    continue
                if not r.ok:
                    return None
                if as_json:
                    return r.json() if r.content[:1] in (b"{", b"[") else None
                return r.text
            except Exception:  # noqa: BLE001
                time.sleep(2 + 3 * i)
        return None


def same_doc(a, b) -> bool:
    """Same exchange file even when the host differs (NSE serves archives from nseindia.com and nseindia.in)."""
    if not a or not b:
        return a == b
    return str(a).rsplit("/", 1)[-1].split("?")[0] == str(b).rsplit("/", 1)[-1].split("?")[0]


def _hm(s: str | None) -> str | None:
    """'05-Nov-2026 18:43:22' -> '18:43' (24-hour, IST, as the exchange API gives it); None when no time is given."""
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)", str(s or "")[11:])
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def _d(s: str | None) -> date | None:
    s = (s or "").strip()[:11].title()
    for f in _DATE_FMT:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _num(v: str):
    try:
        x = float(v.replace(",", ""))
        return x
    except ValueError:
        return None


_PERIOD_END = re.compile(r'<[\w-]+:DateOfEndOfReportingPeriod\b[^>]*contextRef="([^"]+)"[^>]*>([^<]+)<')


def _declared_contexts(txt: str) -> dict:
    """Contexts from the filing's own period facts, for NSE's pre-2022 "_WEB" XBRL files: their facts point at OneD /
    FourD / OneI but the file defines none of them (probe 27 Nov 2026: 56 of 56 sampled 2017-2021 files). The periods
    come from DateOfStartOfReportingPeriod / DateOfEndOfReportingPeriod facts in the same file; OneI = OneD's end."""
    st = {c: _iso(v) for c, v in _PERIOD_START.findall(txt)}
    en = {c: _iso(v) for c, v in _PERIOD_END.findall(txt)}
    out = {c: ("D", st[c], en[c]) for c in ("OneD", "FourD") if st.get(c) and en.get(c) and st[c] < en[c]}
    if "OneD" in out:
        out["OneI"] = ("I", out["OneD"][2])
    return out


def parse_xbrl(txt: str, declared: bool = False) -> dict:
    """Return {"q": {...}, "ytd": {...}, "bs": {...}, "period": (start, end), "ytd_period": (start, end)} or {}.
    `declared`: when the file defines no OneD context, take the periods from its own period facts (_declared_contexts).
    Off in the daily pipeline; used by the history backfill (narrativ/histfin.py) for the benchmark."""
    ctx, dim = {}, set()
    if declared and not re.search(r'<xbrli:context id="OneD"', txt):
        ctx.update(_declared_contexts(txt))
    for cid, body in _CTX.findall(txt):
        if "<xbrldi:explicitMember" in body or "<xbrldi:typedMember" in body:
            dim.add(cid)  # dimensional contexts (segments, line-item breakdowns) are not company totals
        st = re.search(r"<xbrli:startDate>([^<]+)</xbrli:startDate>", body)
        en = re.search(r"<xbrli:endDate>([^<]+)</xbrli:endDate>", body)
        ins = re.search(r"<xbrli:instant>([^<]+)</xbrli:instant>", body)
        if st and en:
            ctx[cid] = ("D", date.fromisoformat(st.group(1)[:10]), date.fromisoformat(en.group(1)[:10]))
        elif ins:
            ctx[cid] = ("I", date.fromisoformat(ins.group(1)[:10]))
    plain = {k: v for k, v in ctx.items() if k not in dim}
    if not any(c[0] == "D" for c in plain.values()):  # some filers put a dimension on every context
        plain = {k: v for k, v in ctx.items() if k in ("OneD", "FourD", "OneI")}
    ctx = plain
    # Reg-33 filings (in-bse-fin, to Dec-2024) date the year-to-date context "FourD" with the quarter's dates; the real
    # period is only in its DateOfStartOfReportingPeriod fact (e.g. FourD 2023-01-01..03-31 holding the FY23 full year).
    # Without this, every old year-to-date figure was dropped and full-year FY23 could not be read (3-year growth fell to 2).
    for cid, st in _PERIOD_START.findall(txt):
        c, d0 = ctx.get(cid), _iso(st)
        if c and c[0] == "D" and d0 and d0 < c[1] and (c[2] - d0).days <= 370:
            ctx[cid] = ("D", d0, c[2])
    if not ctx:
        return {}
    ends = [c[2] for c in ctx.values() if c[0] == "D"]
    if not ends:
        return {}
    pend = max(ends)
    q_ids = [k for k, c in ctx.items() if c[0] == "D" and c[2] == pend and 80 <= (c[2] - c[1]).days <= 100]
    y_ids = [k for k, c in ctx.items() if c[0] == "D" and c[2] == pend and (c[2] - c[1]).days > 100]
    i_ids = [k for k, c in ctx.items() if c[0] == "I" and c[1] == pend]
    # prefer the conventional ids when several contexts share a period
    q_ids.sort(key=lambda k: (k != "OneD", k))
    y_ids.sort(key=lambda k: (k != "FourD", k))
    i_ids.sort(key=lambda k: (k != "OneI", k))
    q, y, bs = {}, {}, {}
    for tag, attrs, val in _FACT.findall(txt):
        c = re.search(r'contextRef="([^"]+)"', attrs)
        if not c:
            continue
        cid, v = c.group(1), _num(val.strip())
        if v is None:
            continue
        if tag in DURATION_TAGS:
            key = DURATION_TAGS[tag]
            if q_ids and cid == q_ids[0]:
                q.setdefault(key, v)
            elif y_ids and cid == y_ids[0]:
                y.setdefault(key, v)
        elif tag in INSTANT_TAGS and i_ids and cid == i_ids[0]:
            bs.setdefault(INSTANT_TAGS[tag], v)
    # lease liabilities: SEBI's integrated filing has no lease tag; filers put them under "other financial liabilities"
    # as described sub-items (context per item, e.g. I_OtherNoncurrentFinancialLiabilities1 + "Lease liabilities")
    lease = _leases(txt, pend)
    for k, v in lease.items():
        bs[k] = v if k == "lease_chk" else bs.get(k, v)
    if not q and y and y_ids and (ctx[y_ids[0]][2] - ctx[y_ids[0]][1]).days <= 100:
        q = y
    qs = ctx[q_ids[0]][1] if q_ids else None
    ys = ctx[y_ids[0]][1] if y_ids else None
    out = {"q": q, "ytd": y, "bs": bs, "end": str(pend), "q_start": str(qs) if qs else None,
           "ytd_start": str(ys) if ys else None, "ytd_chk": YTD_CHK}
    rnd = _ROUNDING.search(txt)
    if rnd:  # the filer's declared rounding ("Lakhs", "Crores"): the scale guard uses it to confirm a mis-declared unit
        out["rounding"] = rnd.group(1).strip()[:20]
    out.update(audit_fields(txt))
    return out


_AUD = re.compile(r"<[\w-]+:(DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification|AuditorsFirmName|"
                  r"WhetherResultsAreAuditedOrUnaudited)\b[^>]*>([^<]*)<")


def audit_fields(txt: str) -> dict:
    """A3: the auditor's opinion declaration filed with annual results (integrated filing, from the Mar-2025 year)."""
    out = {}
    for tag, v in _AUD.findall(txt):
        v = re.sub(r"\s+", " ", v.replace("&amp;", "&")).strip()
        if not v:
            continue
        if tag.startswith("Declaration") and "audit_opinion" not in out:
            out["audit_opinion"] = v[:120]
        elif tag == "AuditorsFirmName":
            out.setdefault("auditors", [])
            if v[:80] not in out["auditors"]:
                out["auditors"].append(v[:80])
        elif tag == "WhetherResultsAreAuditedOrUnaudited" and "audited_flag" not in out:
            out["audited_flag"] = v[:20]
    return out


# leases sit under other (non)current financial liabilities, or other (non)current liabilities (AUTOAXLES, GOLDIAM)
_DESC = re.compile(r'<[\w-]+:DescriptionOf(Other(?:Noncurrent|Current)(?:Financial)?Liabilities)\b[^>]*contextRef="([^"]+)"[^>]*>([^<]*)<')
LEASE_CHK = 2.0  # parser version: 2 reads other (non)current liabilities too
_CTX_DATE = re.compile(r'<xbrli:context id="([^"]+)">.*?<xbrli:instant>([^<]+)</xbrli:instant>', re.S)


def _leases(txt: str, pend) -> dict:
    """{"lease_ncur", "lease_cur", "lease_chk"} at the period end, from described 'other financial liabilities' items."""
    dates = {c: d[:10] for c, d in _CTX_DATE.findall(txt)}
    out = {"lease_chk": LEASE_CHK}
    for tag, cid, desc in _DESC.findall(txt):
        if not re.search(r"lease", desc, re.I) or dates.get(cid, str(pend)) != str(pend):
            continue
        m = re.search(rf'<[\w-]+:{tag}\b[^>]*contextRef="{re.escape(cid)}"[^>]*>([^<]+)<', txt)
        v = _num(m.group(1).strip()) if m else None
        if v is not None:
            k = "lease_ncur" if "Noncurrent" in tag else "lease_cur"
            out[k] = out.get(k, 0) + v
    return out


def reread_leases(symbols: list[str], max_minutes: float = 50) -> int:
    """One-off: add lease liabilities to stored balance sheets by re-reading their filing (url kept per quarter)."""
    ns, t0, n = NSESession(), time.time(), 0
    for s in symbols:
        f = DIR / f"{s}.json"
        if not f.exists() or time.time() - t0 > max_minutes * 60:
            continue
        d = json.loads(f.read_text())
        changed = False
        for qe, bases in sorted(d.get("quarters", {}).items(), reverse=True)[:6]:
            for b, p in bases.items():
                bs = p.get("bs") or {}
                if not bs or (bs.get("lease_chk") or 0) >= LEASE_CHK or not p.get("url"):
                    continue
                txt = ns.get(p["url"], as_json=False)
                if not txt:
                    continue
                bs.pop("lease_cur", None)
                bs.pop("lease_ncur", None)
                bs.update(_leases(txt, qe))
                p["bs"] = bs
                changed, n = True, n + 1
        if changed:
            f.write_text(json.dumps(d, separators=(",", ":")))
    print(f"[filings] leases re-read for {n} balance sheets in {time.time() - t0:.0f}s")
    return n


def _normalise(p: dict) -> dict:
    """Fill alternatives (bank/NBFC/discontinued-ops tags) into the common keys and run sanity checks."""
    flags = []
    for part in ("q", "ytd"):
        d = p.get(part) or {}
        alts = (("rev", "rev_bank"), ("fin", "fin_bank"), ("pbt", "pbt_bank"), ("pat", "pat_bank"), ("pat", "pat_bank2"),
                ("eps", "eps_all"), ("eps", "eps_bank"), ("eps", "eps_basic"), ("eps", "eps_basic_all"), ("eps", "eps_basic_bank"),
                ("cfo", "cfo_net"), ("capex", "capex_alt"), ("exceptional", "exceptional_bank"))
        for k, alt in alts:
            if d.get(k) is None and d.get(alt) is not None:
                d[k] = d[alt]
        for _, alt in alts:
            d.pop(alt, None)
        if d.get("pat_owners") is None and d.get("pat") is not None and not d.get("pat_minority"):
            d["pat_owners"] = d["pat"]
        if d.get("pat_owners") == 0 and d.get("pat") and (d.get("eps") or 0) != 0:
            d["pat_owners"] = d["pat"] - (d.get("pat_minority") or 0)  # owners' line filed as 0 by mistake
            if part == "q":
                flags.append("owners' profit filed as 0; used total profit less minority")
    bs = p.get("bs") or {}
    if bs.get("equity") is None and bs.get("eq_cap_bank") is not None and bs.get("reserves_bank") is not None:
        bs["equity"] = bs["eq_cap_bank"] + bs["reserves_bank"]
    if bs.get("borr_cur") is None and bs.get("borr_ncur") is None and bs.get("borr_total") is not None:
        bs["borr_ncur"] = bs["borr_total"]
    if bs.get("cash") is None and bs.get("cash_rbi") is not None:
        bs["cash"] = bs["cash_rbi"] + (bs.get("bank_call") or 0)
    q = p.get("q") or {}
    # share count: paid-up capital / face value, cross-checked with profit / EPS
    sh = None
    if q.get("share_cap") and q.get("fv"):
        sh = q["share_cap"] / q["fv"]
    implied = None
    if q.get("pat_owners") and q.get("eps") and abs(q["eps"]) >= 0.05:
        implied = q["pat_owners"] / q["eps"]
    if sh and implied and implied > 0:
        r = sh / implied
        if not 0.8 <= r <= 1.25:
            flags.append(f"share capital/face value gives {sh:,.0f} shares but profit/EPS gives {implied:,.0f}; using profit/EPS")
            sh = implied
    elif not sh and implied and implied > 0:
        sh = implied
    p["shares"] = sh
    if q.get("rev") is not None and q["rev"] < 0:
        flags.append("negative revenue")
    if q.get("rev") and q.get("pat") and abs(q["pat"]) > 5 * abs(q["rev"]) and not q.get("oi"):
        flags.append("profit more than 5x revenue")
    p["flags"] = flags
    return p


def _listings(ns: NSESession, code: str, index: str = "equities") -> list[dict]:
    """All quarterly filings for a symbol from both NSE listings, newest first."""
    rows = []
    page = 1
    while page <= 5:
        d = ns.get(BASE + "/api/integrated-filing-results",
                   {"index": index, "symbol": code, "type": "Integrated Filing- Financials", "page": page, "size": 50})
        data = (d or {}).get("data") or []
        for x in data:
            qe = _d(x.get("qe_Date"))
            url = x.get("xbrl") or ""
            if qe and url.endswith(".xml"):
                rows.append({"qe": str(qe), "basis": "Consolidated" if x.get("consolidated") == "Consolidated" else "Standalone",
                             "url": url, "filed": str(_d((x.get("revised_Date") or x.get("broadcast_Date") or "")[:11]) or ""),
                             "filed_time": _hm(x.get("revised_Date") or x.get("broadcast_Date")),
                             "revision": x.get("type_Sub") == "Revision", "audited": x.get("audited"), "src": "NSE integrated filing"})
        total = int((d or {}).get("totalCount") or 0)
        if page * 50 >= total or not data:
            break
        page += 1
    for period in ("Quarterly", "Annual"):
        d = ns.get(BASE + "/api/corporates-financial-results", {"index": index, "symbol": code, "period": period})
        for x in (d if isinstance(d, list) else (d or {}).get("data") or []):
            qe = _d(x.get("toDate"))
            url = x.get("xbrl") or ""
            if qe and url.endswith(".xml"):
                rows.append({"qe": str(qe), "basis": "Consolidated" if x.get("consolidated") == "Consolidated" else "Standalone",
                             "url": url, "filed": str(_d((x.get("filingDate") or "")[:11]) or ""), "filed_time": _hm(x.get("filingDate")), "revision": False,
                             "audited": x.get("audited"), "src": "NSE financial results", "period": period})
    # one filing per (quarter, basis): latest revision, then latest filed
    best = {}
    for r in rows:
        k = (r["qe"], r["basis"])
        cur = best.get(k)
        if cur is None or (r["revision"], r["filed"]) > (cur["revision"], cur["filed"]):
            best[k] = r
    return sorted(best.values(), key=lambda r: r["qe"], reverse=True)


HISTORY_Q = 13       # quarters needed for 3-year growth on full-year numbers
RECHECK_DAYS = 90     # safety net only: new filings are found through the market-wide list below
RECENT_DAYS = 10      # market-wide list window (covers missed runs, weekends, late filers)


def _ts(s: str | None) -> datetime | None:
    """NSE '16-NOV-2026 18:17:15' (IST) -> aware UTC datetime."""
    for f in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return (datetime.strptime(str(s).strip().title(), f) - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def recent_filers(ns: "NSESession", today: date, days: int = RECENT_DAYS) -> dict[str, datetime]:
    """Every company that filed or revised quarterly results in the last `days` days, market-wide (paged list):
    {SYMBOL.NS: latest filing time (UTC)}. Late filers, standalone-then-consolidated and revisions all show up here."""
    out: dict[str, datetime] = {}
    page, got = 1, 0
    while page <= 20:
        d = ns.get(BASE + "/api/integrated-filing-results", {"index": "equities", "type": "Integrated Filing- Financials",
                                                              "from_date": f"{today - timedelta(days=days):%d-%m-%Y}",
                                                              "to_date": f"{today:%d-%m-%Y}", "page": page, "size": 500})
        rows = (d or {}).get("data") or []
        for x in rows:
            t = _ts(x.get("creation_Date")) or _ts(x.get("revised_Date")) or _ts(x.get("broadcast_Date"))
            sym = (x.get("symbol") or "").strip()
            if sym and t:
                k = f"{sym}.NS"
                out[k] = max(out.get(k, t), t)
        got += len(rows)
        if not rows or got >= int((d or {}).get("totalCount") or 0):
            break
        page += 1
    print(f"[filings] market-wide list: {got} filings by {len(out)} companies in the last {days} days")
    return out


def load(sym: str) -> dict:
    f = DIR / f"{sym}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save(sym: str, rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{sym}.json").write_text(json.dumps(rec, separators=(",", ":"), ensure_ascii=False))


def needs_check(rec: dict, today: date, results_date: str | None, filed_at: datetime | None = None) -> bool:
    """Due when never checked, when the company filed (or revised) after our last check, or as a 90-day safety net."""
    if not rec.get("checked"):
        return True
    chk = datetime.fromisoformat(rec["checked"])
    if chk.tzinfo is None:
        chk = chk.replace(tzinfo=timezone.utc)
    if filed_at and filed_at > chk:
        return True
    if results_date and chk.date() < date.fromisoformat(results_date) <= today:
        return True
    latest = max(rec.get("quarters") or {"": 0})
    if latest and latest < expected_quarter(today) and (today - chk.date()).days >= 7:
        return True  # behind the latest quarter whose filing deadline has passed: weekly until it appears
    return (today - chk.date()).days >= RECHECK_DAYS


def expected_quarter(today: date) -> str:
    """Latest quarter end whose results deadline has passed (45 days; 60 for the March quarter)."""
    y = today.year
    ends = [date(y - 1, 12, 31), date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]
    ok = [e for e in ends if e + timedelta(days=60 if e.month == 3 else 45) <= today]
    return max(ok).isoformat() if ok else date(y - 1, 9, 30).isoformat()


def needs_ytd_reread(qe: str, p: dict) -> bool:
    """A March-quarter filing parsed before YTD_CHK has no full-year column (Reg-33 mis-dated FourD context): read it
    once more so full-year FY numbers (3-year growth, 3-year ROCE) exist. One extra download per such quarter, ever."""
    return qe[5:7] == "03" and not p.get("ytd") and (p.get("ytd_chk") or 0) < YTD_CHK and bool(p.get("url"))


def update(sym: str, ns: NSESession, today: date) -> dict:
    """Fetch listing, download only filings not yet parsed. Returns the stored record."""
    code = sym[:-3]
    rec = load(sym) or {"symbol": sym, "quarters": {}}
    rows = _listings(ns, code)
    if not rows:
        rows = _listings(ns, code, index="sme")
    rec["checked"] = datetime.now(timezone.utc).isoformat()
    if not rows:
        rec["status"] = "no NSE filings"
        save(sym, rec)
        return rec
    keep_q = sorted({r["qe"] for r in rows}, reverse=True)[:QUARTERS_KEEP]
    # one basis for the whole series (halves the downloads), following the latest quarter: consolidated when the latest
    # quarter has it, else standalone (a company filing only standalone for the newest quarter is not left stale)
    basis = "Consolidated" if any(r["basis"] == "Consolidated" for r in rows if r["qe"] == keep_q[0]) else "Standalone"
    # history: 3-year growth and own-history valuation need 13+ quarters. A company that began consolidated reporting
    # recently has a short consolidated series but a long standalone one: use standalone when it also has the latest
    # quarter and at least 13 quarters (one consistent series, never mixed).
    have = {b: {r["qe"] for r in rows if r["basis"] == b and r["qe"] in keep_q} for b in ("Consolidated", "Standalone")}
    other = "Standalone" if basis == "Consolidated" else "Consolidated"
    rec["basis_note"] = None
    if len(have[basis]) < HISTORY_Q and len(have[other]) >= HISTORY_Q and keep_q[0] in have[other]:
        rec["basis_note"] = f"{other.lower()} series used: {basis.lower()} results filed for only {len(have[basis])} quarters"
        basis = other
    # banks: RBI's ratios (gross NPA, CET1) are filled only in the standalone banking filing; the consolidated one carries
    # zeros (SBI, HDFC Bank, Bank of Baroda ... showed gross NPA 0 and passed C1 on it). Banks use the standalone series.
    if keep_q[0] in have["Standalone"] and any("BANKING" in (r.get("url") or "").upper() for r in rows if r["qe"] == keep_q[0]):
        if basis != "Standalone":
            rec["basis_note"] = "standalone series used: bank ratios (gross NPA, CET1) are reported only in the standalone filing"
        basis = "Standalone"
    rec["basis"] = basis
    for r in rows:
        if r["qe"] not in keep_q or r["basis"] != basis:
            continue
        have = (rec["quarters"].get(r["qe"]) or {}).get(r["basis"])
        bank_reread = have and have.get("kind") == "bank" and not have.get("bank_tags")  # parsed before the NPA % / CET1 tags (once)
        if have and same_doc(have.get("url"), r["url"]) and not needs_ytd_reread(r["qe"], have) and not bank_reread:
            continue
        txt = ns.get(r["url"], as_json=False)
        time.sleep(config.FILINGS_SLEEP_SEC)
        if not txt:
            continue
        p = parse_xbrl(txt)
        if not p or p.get("end") != r["qe"]:
            if p and p.get("end"):
                r["qe_note"] = f"file period ends {p['end']}"
            if not p:
                continue
        p = _normalise(p)
        u = r["url"].upper()
        kind = "bank" if "BANKING" in u else "nbfc" if "NBFC" in u else "insurance" if "INSURANCE" in u else "general"
        p.update({"url": r["url"], "filed": r["filed"], "src": r["src"], "audited": r["audited"], "kind": kind})
        if kind == "bank":
            p["bank_tags"] = 1
        if r.get("filed_time"):  # time of day (IST) the exchange broadcast it: T11 starts after an after-close filing next day
            p["filed_time"] = r["filed_time"]
        rec["quarters"].setdefault(p["end"], {})[r["basis"]] = p
    rec["quarters"] = dict(sorted(rec["quarters"].items(), reverse=True)[:QUARTERS_KEEP])
    rec["status"] = "ok"
    save(sym, rec)
    return rec


def refresh(symbols: list[str], today: date, calendar: dict, priority: list[str], budget: int | None = None) -> dict:
    """Update the stored filings for NSE symbols, priority first, within the per-run budget."""
    nse = [s for s in symbols if s.endswith(".NS")]
    t0 = time.time()
    ns = None
    filers: dict = {}
    try:
        ns = NSESession()
        filers = recent_filers(ns, today)
    except Exception as e:  # noqa: BLE001
        print(f"[filings] market-wide list failed, using the results calendar only: {e}")
    # who filed first (newest filing first), then the priority list, then the rest
    fresh = sorted([s for s in nse if s in filers], key=lambda s: filers[s], reverse=True)
    order = list(dict.fromkeys(fresh + [s for s in priority if s in set(nse)] + nse))
    todo = [s for s in order if needs_check(load(s), today, (calendar.get(s) or {}).get("date"), filers.get(s))]
    budget = budget or config.FILINGS_MAX_PER_RUN
    done = 0
    for s in todo:
        if done >= budget or time.time() - t0 > config.FILINGS_MAX_MINUTES * 60:
            break
        try:
            ns = ns or NSESession()
            update(s, ns, today)
        except Exception as e:  # noqa: BLE001
            print(f"[filings] {s}: {e}")
        done += 1
    print(f"[filings] updated {done} of {len(todo)} due ({len(nse)} NSE symbols), {ns.calls if ns else 0} requests, "
          f"{time.time() - t0:.0f}s")
    return {s: load(s) for s in nse}


if __name__ == "__main__":  # Actions: python -m narrativ.filings --backfill | --tags CODE | SYMBOL...
    import sys
    if sys.argv[1] == "--leases":  # one-off: lease liabilities into stored balance sheets (sharded like --backfill)
        uni = sorted(p.stem for p in DIR.glob("*.json"))
        shard = os.environ.get("FILINGS_SHARD")
        if shard:
            i, n = map(int, shard.split("/"))
            uni = [s for k, s in enumerate(uni) if k % n == i]
        reread_leases(uni, float(os.environ.get("FILINGS_MAX_MINUTES", "50")))
        sys.exit()
    if sys.argv[1] == "--banks":  # one-off: banks re-read on the standalone series with the NPA % / CET1 fields (2026-11-23)
        uni = sorted(p.stem for p in DIR.glob("*.json"))
        shard = os.environ.get("FILINGS_SHARD")
        if shard:
            i, n = map(int, shard.split("/"))
            uni = [s for k, s in enumerate(uni) if k % n == i]
        ns, t0, n_ok = NSESession(), time.time(), 0
        for s in uni:
            rec = load(s) or {}
            qs = rec.get("quarters") or {}
            if not qs or not any((v or {}).get("kind") == "bank" for v in qs[max(qs)].values()):
                continue
            if time.time() - t0 > float(os.environ.get("FILINGS_MAX_MINUTES", "50")) * 60:
                break
            try:
                update(s, ns, date.today()); n_ok += 1
            except Exception as e:  # noqa: BLE001
                print(f"[filings] {s}: {e}")
        print(f"[filings] banks re-read: {n_ok}, {ns.calls} requests, {time.time() - t0:.0f}s")
        sys.exit()
    if sys.argv[1] == "--audit":  # one-off: re-read the latest March-quarter filing of each company for the A3 fields
        uni = sorted(p.stem for p in DIR.glob("*.json"))
        shard = os.environ.get("FILINGS_SHARD")
        if shard:
            i, n = map(int, shard.split("/"))
            uni = [s for k, s in enumerate(uni) if k % n == i]
        ns, t0, n_ok = NSESession(), time.time(), 0
        for s in uni:
            if time.time() - t0 > float(os.environ.get("FILINGS_MAX_MINUTES", "50")) * 60:
                break
            rec = load(s)
            mar = sorted(q for q in (rec.get("quarters") or {}) if q.endswith("-03-31") and q >= "2025-03-31")
            if not mar:
                continue
            p = (rec["quarters"][mar[-1]] or {}).get(rec.get("basis") or "Consolidated") or next(iter(rec["quarters"][mar[-1]].values()))
            if p.get("audit_opinion") or not p.get("url"):
                continue
            txt = ns.get(p["url"], as_json=False)
            time.sleep(config.FILINGS_SLEEP_SEC)
            if txt:
                a = audit_fields(txt)
                if a:
                    p.update(a)
                    save(s, rec)
                    n_ok += bool(a.get("audit_opinion"))
        print(f"[filings] audit: {n_ok} companies with the opinion declaration, {time.time() - t0:.0f}s")
        sys.exit()
    if sys.argv[1] == "--history":  # one-off: companies with under 13 stored quarters re-read (basis switch for history)
        uni = sorted(p.stem for p in DIR.glob("*.json") if 0 < len((json.loads(p.read_text()).get("quarters") or {})) < HISTORY_Q)
        shard = os.environ.get("FILINGS_SHARD")
        if shard:
            i, n = map(int, shard.split("/"))
            uni = [s for k, s in enumerate(uni) if k % n == i]
        ns, t0, n_sw = NSESession(), time.time(), 0
        for s in uni:
            if time.time() - t0 > float(os.environ.get("FILINGS_MAX_MINUTES", "50")) * 60:
                break
            try:
                r = update(s, ns, date.today())
                n_sw += bool(r.get("basis_note"))
            except Exception as e:  # noqa: BLE001
                print(f"[filings] {s}: {e}")
        print(f"[filings] history: {len(uni)} short-history companies re-read, {n_sw} switched basis for history, {time.time() - t0:.0f}s")
        sys.exit()
    if sys.argv[1] == "--ytd":  # one-off: re-read Reg-33 March filings for the full-year column (YTD_CHK), sharded
        uni = sorted(p.stem for p in DIR.glob("*.json")
                     if any(needs_ytd_reread(qe, p_) for qe, b in (json.loads(p.read_text()).get("quarters") or {}).items() for p_ in b.values()))
        shard = os.environ.get("FILINGS_SHARD")
        if shard:
            i, n = map(int, shard.split("/"))
            uni = [s for k, s in enumerate(uni) if k % n == i]
        ns, t0 = NSESession(), time.time()
        for s in uni:
            if time.time() - t0 > float(os.environ.get("FILINGS_MAX_MINUTES", "50")) * 60:
                break
            try:
                update(s, ns, date.today())
            except Exception as e:  # noqa: BLE001
                print(f"[filings] {s}: {e}")
        print(f"[filings] ytd: {len(uni)} companies with Reg-33 March filings to re-read, {time.time() - t0:.0f}s")
        sys.exit()
    if sys.argv[1] == "--backfill":  # between daily runs: work through the stage-1 universe saved by run.py
        uni = json.loads(Path("data/universe_stage1.json").read_text())
        shard = os.environ.get("FILINGS_SHARD")  # "i/n": this runner takes every n-th symbol (parallel burst)
        if shard:
            i, n = map(int, shard.split("/"))
            uni = [s for k, s in enumerate(sorted(uni)) if k % n == i]
        refresh(uni, date.today(), {}, [], budget=int(sys.argv[2]) if len(sys.argv) > 2 else 250)
        sys.exit()
    ns = NSESession()
    if sys.argv[1] == "--tags":  # list every non-dimensional tag in a symbol's latest filing (for new taxonomies)
        rows = _listings(ns, sys.argv[2])
        txt = ns.get(rows[0]["url"], as_json=False)
        print(rows[0]["url"])
        for tag, attrs, v in sorted(set(_FACT.findall(txt))):
            c = re.search(r'contextRef="([^"]+)"', attrs)
            if c and c.group(1) in ("OneD", "FourD", "OneI"):
                print(" ", c.group(1), tag, v.strip())
        sys.exit()
    for s in sys.argv[1:]:
        r = update(s, ns, date.today())
        qs = r.get("quarters", {})
        print(s, r.get("status"), len(qs), "quarters", list(qs)[:3])
        for qe, bases in list(qs.items())[:2]:
            for b, p in bases.items():
                print("  ", qe, b, {k: p["q"].get(k) for k in ("rev", "pat", "pat_owners", "eps")}, "bs", len(p.get("bs", {})),
                      "ytd keys", sorted(p.get("ytd", {}))[:8], "shares", p.get("shares"), "flags", p.get("flags"))
