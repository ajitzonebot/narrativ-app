"""Every number shown in the app is computed here, by formula, from filed inputs.

Inputs, in order of preference:
  1. Company XBRL filings on NSE (narrativ.filings)          src "NSE filing ..."
  2. Yahoo statement line items (raw filed figures relayed)   src "Yahoo statements" (fallback, labelled)
Yahoo's own ratios (trailingPE, returnOnEquity, ...) are never used. If inputs are missing the value is None
and the app shows a dash.

Each metric is returned as {"v": value, "f": formula, "in": {name: value}, "src": text, "url": link?}.
"""
import math
from datetime import date

CR = 1e7
GROWTH_CAP = (-90.0, 300.0)  # % ; outside this range growth is shown as n/m and kept out of scores


def _m(v, f, inputs, src, url=None, nd=1, unit=None):
    if v is None:
        return None
    out = {"v": round(v, nd), "f": f, "in": {k: (round(x, 2) if isinstance(x, float) else x) for k, x in inputs.items()}, "src": src}
    if url:
        out["url"] = url
    if unit:
        out["u"] = unit
    return out


def _cr(x):
    return None if x is None else x / CR


def _q_end(s: str) -> date:
    return date.fromisoformat(s)


def _prev_q(d: date, n: int = 1) -> str:
    """Quarter end n quarters before d."""
    y, m = d.year, d.month
    for _ in range(n):
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    last = {3: 31, 6: 30, 9: 30, 12: 31}[m]
    return f"{y}-{m:02d}-{last}"


def series(fin: dict) -> dict:
    """Choose one basis for the whole series (consolidated if filed for the latest quarter), return quarter->data.
    Quarters filed in the wrong unit are corrected or dropped by scale_guard (listed under "scale")."""
    qs = fin.get("quarters") or {}
    if not qs:
        return {}
    latest = max(qs)
    basis = fin.get("basis") if fin.get("basis") in qs[latest] else ("Consolidated" if "Consolidated" in qs[latest] else "Standalone")
    out = {}
    for qe, bases in qs.items():
        p = bases.get(basis)
        if p and (p.get("q") or {}).get("rev") is not None:
            out[qe] = p
    out, scale = scale_guard(out)
    out, owners = owners_guard(out)
    return {"basis": basis, "q": dict(sorted(out.items(), reverse=True)), "scale": scale, "owners": owners}


# ---------------------------------------------------------------- unit (scale) guard
# A filer who types crore figures into a filing that declares "Lakhs" publishes every amount 100x too small (METROBRAND
# Sep-2025, NAVNETEDUL Mar-2026, IMPAL Jun-2026: LevelOfRounding "Lakhs", neighbours "Crores"). The XBRL itself is
# internally consistent, so only the neighbouring quarters reveal it.
SCALE_POWERS = (2, 3, 4, 5, 6, 7)  # 10^2 lakh/crore ... 10^7 rupees/crore; 10x is left alone (real swings happen)
SCALE_TOL = 0.2                    # log10 distance from the power allowed for revenue and expenses (about 1.6x)
SCALE_CAP_TOL = 0.05               # paid-up capital must be off by the same power almost exactly (about 12%)
_ROUND_POW = {"rupees": 0, "units": 0, "thousands": 3, "thousand": 3, "lakhs": 5, "lakh": 5, "millions": 6, "million": 6,
              "crores": 7, "crore": 7, "billions": 9, "billion": 9}
_NOT_MONEY = {"eps", "eps_basic", "eps_all", "eps_basic_all", "eps_bank", "eps_basic_bank", "fv", "lease_chk"}


def _med(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _rescale(p: dict, f: float, note: str) -> dict:
    out = dict(p)
    for part in ("q", "ytd", "bs"):
        out[part] = {k: (v * f if isinstance(v, (int, float)) and k not in _NOT_MONEY else v) for k, v in (p.get(part) or {}).items()}
    if p.get("shares"):
        out["shares"] = p["shares"] * f
    out["flags"] = list(p.get("flags") or []) + [note]
    out["scaled"] = f
    return out


def scale_guard(q: dict) -> tuple[dict, list[dict]]:
    """{quarter: filing} -> (same with unit errors handled, [events]).

    A quarter is suspect only when revenue AND expenses are both off the median of up to 3 quarters on each side by the
    same power of ten (100x, 1000x, ...; within SCALE_TOL). A real swing (dividend income, a licence fee, a sale) moves
    revenue without moving expenses the same way, and is not touched. The unit error is confirmed when the paid-up
    capital (which does not move 100x in a quarter) is off by the same power, or the declared rounding differs from the
    neighbours' by exactly that power: then every amount in that filing is rescaled ("corrected"). Unconfirmed, the
    quarter is left out of every metric ("excluded"). Either way the event is returned for the data-issues registry."""
    ends = sorted(q)
    fix, events = {}, []
    for i, qe in enumerate(ends):
        p = q[qe]
        left, right = [q[x] for x in ends[max(0, i - 3):i]], [q[x] for x in ends[i + 1:i + 4]]
        nb = left + right
        ks, ratios, shifted = set(), {}, False
        for key in ("rev", "exp"):
            v = (p.get("q") or {}).get(key)
            vals = [[abs(x) for x in ((n.get("q") or {}).get(key) for n in side) if x] for side in (left, right)]
            m = _med(vals[0] + vals[1])
            if not v or not m or len(vals[0] + vals[1]) < 2:
                break
            ml, mr = _med(vals[0]), _med(vals[1])
            # the business itself changed level around this quarter (a sale, a merger): only a confirmed unit error counts
            shifted |= len(vals[0]) >= 2 and len(vals[1]) >= 2 and max(ml, mr) > 10 * min(ml, mr)
            lg = math.log10(abs(v) / m)
            k = round(lg)
            if abs(k) not in SCALE_POWERS or abs(lg - k) > SCALE_TOL:
                break
            ks.add(k)
            ratios[key] = abs(v) / m
        if len(ratios) < 2 or len(ks) != 1:
            continue
        k = ks.pop()
        # profit swings more than revenue, but a unit error moves it too: where profit is material it must sit within 10x
        # of the same power (a quarter whose revenue and costs fell 100x while profit held is not a unit error)
        pat = (p.get("q") or {}).get("pat")
        mp = _med([abs(x) for x in ((n.get("q") or {}).get("pat") for n in nb) if x])
        mrev = abs(p["q"]["rev"]) / ratios["rev"]
        if pat and mp and mp >= 0.02 * mrev and abs(math.log10(abs(pat) / mp) - k) > 1:
            continue
        why = None
        cap, mcap = (p.get("q") or {}).get("share_cap"), _med([x for x in ((n.get("q") or {}).get("share_cap") for n in nb) if x])
        if cap and mcap and abs(math.log10(cap / mcap) - k) <= SCALE_CAP_TOL:
            why = f"paid-up capital also {cap / mcap:.3g}x the neighbouring quarters'"
        rp = _ROUND_POW.get(str(p.get("rounding") or "").strip().lower())
        rn = [_ROUND_POW.get(str(n.get("rounding") or "").strip().lower()) for n in nb]
        rn = [x for x in rn if x is not None]
        if why is None and rp is not None and rn and rp - _med(rn) == k:
            why = f"filing declares {p['rounding']} while neighbouring quarters declare a unit 10^{abs(k)} {'larger' if k < 0 else 'smaller'}"
        f = 10.0 ** (-k)
        size = f"{'below' if k < 0 else 'above'} neighbouring quarters by {10 ** abs(k):,}x (revenue {ratios['rev']:.3g}x, expenses {ratios['exp']:.3g}x)"
        ev = {"quarter": qe, "factor": f, "rev_cr": round(p["q"]["rev"] / CR, 2), "neighbour_rev_cr": round(p["q"]["rev"] / ratios["rev"] / CR, 2),
              "url": p.get("url"), "filed": p.get("filed")}
        if why is None and shifted:
            continue
        if why:
            fix[qe] = _rescale(p, f, f"quarter {qe} filed in the wrong unit ({size}; {why}): amounts multiplied by {f:g}")
            events.append({**ev, "action": "corrected", "why": f"{size}; {why}"})
        else:
            fix[qe] = None
            events.append({**ev, "action": "excluded", "why": f"{size}; unit error not confirmed by paid-up capital or declared rounding"})
    out = {qe: (fix[qe] if qe in fix else p) for qe, p in q.items()}
    return {qe: p for qe, p in out.items() if p is not None}, events


# ---------------------------------------------------------------- owners' profit guard
# Profit = owners' share + minority share (Ind AS 110). A filing whose owners' line is 10x..10^7x away from total profit,
# with a minority share that does not make up the gap, carries a mis-tagged owners' figure (FMGOETZE Sep-2026: owners
# ₹0.53 cr against profit ₹37.25 cr, minority ₹0.07 cr). P/E, profit growth and EPS-based share counts read owners' profit,
# so the owners' figure is rebuilt from total profit (or rescaled when it is off by an exact power of ten).
OWNERS_TOL = 0.05        # owners + minority may differ from total profit by 5% (rounding, discontinued operations)
OWNERS_MIN_LOG = 1.0     # only a gap of 10x or more is treated as a tagging error
OWNERS_MINORITY = 0.2    # the guard applies only while the filed minority share is small against total profit
OWNERS_EPS_CONFIRM = 1.5  # EPS × (paid-up capital ÷ face value) within 1.5x of the filed owners' figure confirms it


def _owners_fix(d: dict, shares_cap: float | None):
    """-> (owners value to use, how, factor, why) for one P&L block, or None when the owners' figure is consistent."""
    pat, po, pm = d.get("pat"), d.get("pat_owners"), d.get("pat_minority") or 0
    if not pat or not po or not isinstance(po, (int, float)):
        return None
    if abs(po + pm - pat) <= OWNERS_TOL * abs(pat) + 1e5:
        return None
    lg = math.log10(abs(pat) / abs(po))
    if abs(lg) < OWNERS_MIN_LOG or abs(pm) >= OWNERS_MINORITY * abs(pat):
        return None  # a modest gap, or a large minority share: the split may be real
    eps = d.get("eps")
    if shares_cap and eps and abs(eps) >= 0.05:
        implied = eps * shares_cap  # EPS is filed separately from the profit lines: it says which figure is the owners'
        if po * implied > 0 and abs(math.log10(abs(implied) / abs(po))) <= math.log10(OWNERS_EPS_CONFIRM):
            return None  # EPS backs the filed owners' figure: total profit is the odd one out, not this guard's call
    gap = f"owners' profit ₹{po / CR:,.2f} cr vs total profit ₹{pat / CR:,.2f} cr (minority ₹{pm / CR:,.2f} cr)"
    k = round(lg)
    f = 10.0 ** k
    if abs(lg - k) <= SCALE_TOL and abs(po * f + pm - pat) <= OWNERS_TOL * abs(pat):
        return po * f, "rescaled", f, f"{gap}: off by exactly {f:,.0f}x, rescaled"
    return pat - pm, "replaced", None, f"{gap}: minority does not explain the gap, used total profit less minority"


def owners_guard(q: dict) -> tuple[dict, list[dict]]:
    """{quarter: filing} -> (same with mis-tagged owners' profit rebuilt, [events]). Input filings are not modified.
    When the bad owners' figure had set the share count (profit ÷ EPS), the paid-up capital ÷ face value count is restored
    if it now agrees with the corrected profit ÷ EPS."""
    out, events = {}, []
    for qe, p in q.items():
        q0 = p.get("q") or {}
        sh_cap = q0["share_cap"] / q0["fv"] if q0.get("share_cap") and q0.get("fv") else None
        fixes = {part: _owners_fix(p.get(part) or {}, sh_cap) for part in ("q", "ytd")}
        fixes = {k: x for k, x in fixes.items() if x}
        if not fixes:
            out[qe] = p
            continue
        p2 = dict(p)
        p2["flags"] = list(p.get("flags") or [])
        for part, (val_, how, f, why) in fixes.items():
            p2[part] = {**(p.get(part) or {}), "pat_owners": val_}
            p2["flags"].append(f"{'quarter' if part == 'q' else 'year-to-date'} {why}")
        nq = p2.get("q") or {}
        if sh_cap and nq.get("eps") and abs(nq["eps"]) >= 0.05 and "q" in fixes:
            implied = nq["pat_owners"] / nq["eps"]
            if implied > 0 and 0.8 <= sh_cap / implied <= 1.25 and p.get("shares") != sh_cap:
                p2["shares"] = sh_cap
                p2["flags"] = [x for x in p2["flags"] if "using profit/EPS" not in x]
                p2["flags"].append(f"share count from paid-up capital ÷ face value ({sh_cap:,.0f}) once owners' profit was corrected")
        out[qe] = p2
        part, (val_, how, f, why) = next(iter(fixes.items()))
        d0 = p.get(part) or {}
        events.append({"kind": "owners", "quarter": qe, "action": "corrected", "fix": how, "factor": f, "parts": sorted(fixes),
                       "pat_cr": round(d0["pat"] / CR, 2), "owners_cr": round(d0["pat_owners"] / CR, 2),
                       "minority_cr": round((d0.get("pat_minority") or 0) / CR, 2), "used_cr": round(val_ / CR, 2),
                       "url": p.get("url"), "filed": p.get("filed"), "why": why})
    return out, events


def scale_issues(fin: dict) -> list[dict]:
    """Unit-error and owners'-profit events for one stock (for the data-issues registry; owners' events have kind "owners")."""
    s = series(fin) or {}
    return (s.get("scale") or []) + (s.get("owners") or [])


MIN_SHARES = 1e5  # no listed company has 1 lakh shares or fewer (JKSHAH's only filing shows 1,000: a pre-allotment shell)


def share_count(s: dict, latest: str) -> tuple[float | None, str | None, bool]:
    """-> (shares, note, plausible). The latest filing's count (filings._normalise: paid-up capital ÷ face value, or
    profit ÷ EPS when they disagree). A count of MIN_SHARES or fewer is not a listed company's: paid-up capital ÷ face
    value is used when that one is plausible, else the count is reported as not meaningful rather than guessed.
    (Earlier quarters are not a usable reference: their own counts are often the mis-filed ones.)"""
    lp = s["q"][latest]
    q = lp.get("q") or {}
    sh, fv = lp.get("shares"), q.get("fv")
    alt = q["share_cap"] / fv if q.get("share_cap") and fv else None
    if not sh and not alt:
        return None, None, True  # not filed: market cap is simply missing (a dash), nothing implausible
    if sh and sh > MIN_SHARES:
        return sh, None, True
    if alt and alt > MIN_SHARES:
        return alt, f"share count from paid-up capital ÷ face value ({alt:,.0f}): profit ÷ EPS gives {sh or 0:,.0f}", True
    return sh, (f"share count {sh or 0:,.0f} implausible (a listed company has more than {MIN_SHARES:,.0f}): "
                "market cap and per-share ratios not computed from this filing"), False


ROE_MAX_PCT = 200.0  # beyond this the equity is too small against the profit for a return to mean anything


def roe_nm(pat_ttm, eq, eq0) -> str | None:
    """Why ROE is not meaningful, or None. Negative (or zero) equity at either end makes the average a netting of a deficit,
    not capital employed: the sign flips (a profit reads as a negative return, a loss as a positive one) and a near-zero
    average explodes the ratio."""
    if eq is None or eq <= 0:
        return "equity is zero or negative"
    if eq0 is not None and eq0 <= 0:
        return "equity was zero or negative a year earlier"
    avg = (eq + eq0) / 2 if eq0 else eq
    if pat_ttm is not None and abs(pat_ttm) > ROE_MAX_PCT / 100 * avg:
        return f"average equity is tiny against the profit (return beyond ±{ROE_MAX_PCT:.0f}%)"
    return None


def _ttm(s: dict, key: str, end: str):
    """Sum of 4 consecutive quarters ending at `end`, or None."""
    d = _q_end(end)
    vals = []
    for i in range(4):
        p = s["q"].get(_prev_q(d, i) if i else end)
        v = (p or {}).get("q", {}).get(key)
        if v is None:
            return None
        vals.append(v)
    return sum(vals)


def _ttm0(s: dict, key: str, end: str) -> float:
    """Like _ttm but a missing line counts as zero (for items such as exceptional items that are often not tagged)."""
    d = _q_end(end)
    tot = 0.0
    for i in range(4):
        p = s["q"].get(_prev_q(d, i) if i else end)
        tot += ((p or {}).get("q") or {}).get(key) or 0
    return tot


def _src(p: dict, basis: str) -> str:
    return f"NSE filing, quarter ended {p.get('end')}, {basis.lower()}, filed {p.get('filed') or 'n/a'}"


def _growth(cur, prev):
    if cur is None or prev is None or prev <= 0:
        return None
    g = (cur / prev - 1) * 100
    return g


def _fy_values(s: dict, key: str) -> dict:
    """Full-year values: the March filing's year-to-date figure, else the sum of the year's 4 quarters (P&L only)."""
    out = {}
    for qe, p in s["q"].items():
        if qe[5:7] != "03":
            continue
        y = int(qe[:4])
        v = (p.get("ytd") or {}).get(key)
        if v is None and key not in ("cfo", "capex", "cfi", "cff"):
            parts = [((s["q"].get(d) or {}).get("q") or {}).get(key) for d in (f"{y-1}-06-30", f"{y-1}-09-30", f"{y-1}-12-31", qe)]
            v = sum(parts) if None not in parts else None
        if v is not None:
            out[y] = v
    return out


def _gnpa_pct(p: dict) -> float | None:
    """Gross NPA % of advances for one quarter: the filed ratio, else gross NPAs ÷ advances. Zero counts as not reported
    (consolidated banking filings carry 0 in these fields; a bank with truly no bad loans does not exist in the data)."""
    q, bs = p.get("q") or {}, p.get("bs") or {}
    r = q.get("gnpa_ratio")
    if r:
        return r * 100 if r < 1 else r
    if q.get("gnpa") and bs.get("advances"):
        return q["gnpa"] / bs["advances"] * 100
    return None


def _lender_metrics(M: dict, s: dict, bq, bp: dict, basis: str) -> None:
    """Banks (and any lender whose filing has these fields): gross NPA %, its 4-quarter trend, CET1 ratio, loan-book growth."""
    lp_q, lp = next(iter(s["q"].items()))
    src, url = _src(lp, basis), lp.get("url")
    g = _gnpa_pct(lp)
    if g is not None:
        M["gnpa_pct_advances"] = _m(g, "Gross NPAs as % of advances (filed ratio)" if (lp.get("q") or {}).get("gnpa_ratio") else "Gross NPAs ÷ advances",
                                    {"quarter": lp_q}, src, url, 2)
    trend = [(qe, _gnpa_pct(p)) for qe, p in list(s["q"].items())[:6]]
    trend = [(qe, x) for qe, x in trend if x is not None]
    if len(trend) >= 5:
        rising = 0
        for (_, a), (_, b) in zip(trend, trend[1:]):  # newest first
            if a > b + 0.005:
                rising += 1
            else:
                break
        M["gnpa_rising_q"] = _m(float(rising), "Quarters in a row gross NPA % rose (latest first)",
                                {qe: round(x, 2) for qe, x in trend[:5]}, src, url, 0)
    c = (lp.get("q") or {}).get("cet1_ratio")
    if c:
        M["cet1_pct"] = _m(c * 100 if c < 1 else c, "CET1 capital ratio (filed)", {"quarter": lp_q}, src, url, 2, "%")
    if bp and (bp.get("bs") or {}).get("advances"):
        pq, pp = None, None
        want = _prev_q(_q_end(bq), 4)
        for qe, p in s["q"].items():
            if qe == want and (p.get("bs") or {}).get("advances"):
                pq, pp = qe, p
        if pp:
            a1, a0 = bp["bs"]["advances"], pp["bs"]["advances"]
            M["advances_yoy_pct"] = _m((a1 / a0 - 1) * 100, "Advances (loan book) growth over 12 months",
                                       {"advances_cr": _cr(a1), "a_year_earlier_cr": _cr(a0), "dates": f"{pq} → {bq}"}, _src(bp, basis), bp.get("url"))


def _latest_bs(s: dict, before: str | None = None):
    for qe, p in s["q"].items():
        if before and qe > before:
            continue
        if (p.get("bs") or {}).get("equity") is not None:
            return qe, p
    return None, None


def compute(fin: dict, price: float, yahoo: dict | None = None, promoter_pct: float | None = None, bse: dict | None = None) -> dict:
    """All metrics for one stock. With no NSE filing: BSE results summary (`bse`) for revenue / profit, Yahoo statements
    (labelled) for the rest."""
    s = series(fin)
    M = {}
    if not s or not s["q"]:
        return _bse_overlay(_yahoo_fallback(yahoo, price, promoter_pct), bse, yahoo)
    basis = s["basis"]
    latest = next(iter(s["q"]))
    lp = s["q"][latest]
    src, url = _src(lp, basis), lp.get("url")
    q = lp["q"]
    M["last_quarter"] = latest
    M["basis"] = basis
    M["source"] = "NSE filing"
    M["flags"] = list(lp.get("flags") or []) + ([fin["basis_note"]] if fin.get("basis_note") else [])
    for e in s.get("scale") or []:
        if e["quarter"] != latest or e["action"] != "corrected":  # the latest quarter's correction is already in its flags
            M["flags"].append(f"quarter {e['quarter']} {'corrected for a unit error' if e['action'] == 'corrected' else 'left out of all metrics'}: {e['why']}")
    for e in s.get("owners") or []:
        if e["quarter"] != latest:  # the latest quarter's note is already in its flags
            M["flags"].append(f"quarter {e['quarter']} owners' profit corrected: {e['why']}")
    mar = [d for d in s["q"] if d.endswith("-03-31") and (s["q"][d] or {}).get("audit_opinion")]
    if mar:
        a = s["q"][max(mar)]
        M["audit"] = {"opinion": a["audit_opinion"], "year_end": max(mar), "auditors": a.get("auditors"), "url": a.get("url"),
                      "filed": a.get("filed")}
    kind = lp.get("kind") or "general"
    lender = kind in ("bank", "nbfc", "insurance")
    M["kind"] = kind

    shares, sh_note, sh_ok = share_count(s, latest)
    if sh_note:
        M["flags"].append(sh_note)
    mcap = price * shares / CR if shares and price else None
    M["mcap_cr"] = _m(mcap, "Price × shares outstanding", {"price": price, "shares": shares}, src, url, 0, "₹ cr")
    if not sh_ok:  # n/m: kept out of scores and every ratio built on it (P/E, P/B, EV); run.py uses the exchange market cap
        if M["mcap_cr"]:
            M["mcap_cr"].update({"nm": True, "nm_why": sh_note})
        shares, mcap = None, None

    rev_ttm, pat_ttm = _ttm(s, "rev", latest), _ttm(s, "pat_owners", latest)
    oi_ttm, pbt_ttm = _ttm(s, "oi", latest), _ttm(s, "pbt", latest)
    fin_ttm, dep_ttm = _ttm(s, "fin", latest), _ttm(s, "dep", latest)
    exc_ttm = _ttm0(s, "exceptional", latest)
    pbt_core = pbt_ttm - exc_ttm if pbt_ttm is not None else None  # before exceptional items
    ebitda_ttm = None
    if not lender:
        exp_ttm = _ttm(s, "exp", latest)
        if None not in (rev_ttm, exp_ttm, fin_ttm, dep_ttm):
            ebitda_ttm = rev_ttm - exp_ttm + fin_ttm + dep_ttm  # operating: excludes other income and exceptional items
        elif None not in (pbt_core, fin_ttm, dep_ttm):
            ebitda_ttm = pbt_core + fin_ttm + dep_ttm - (oi_ttm or 0)
    ebit_ttm = ebitda_ttm - dep_ttm if ebitda_ttm is not None and dep_ttm is not None else None
    if exc_ttm:
        M["flags"].append(f"exceptional items of ₹{exc_ttm / CR:,.1f} cr in the last 4 quarters (excluded from EBITDA and margins)")
    ttm_src = f"Sum of last 4 quarters to {latest}, NSE filings ({basis.lower()})"

    M["revenue_ttm_cr"] = _m(_cr(rev_ttm), "Sum of revenue from operations, last 4 quarters", {}, ttm_src, url, 1, "₹ cr")
    M["pat_ttm_cr"] = _m(_cr(pat_ttm), "Sum of profit attributable to owners, last 4 quarters", {}, ttm_src, url, 1, "₹ cr")
    if mcap and pat_ttm and pat_ttm > 0:
        M["pe"] = _m(mcap / _cr(pat_ttm), "Market cap ÷ profit (last 4 quarters)", {"mcap_cr": mcap, "pat_ttm_cr": _cr(pat_ttm)}, ttm_src, url)
    if ebitda_ttm is not None and rev_ttm:
        M["ebitda_margin_pct"] = _m(ebitda_ttm / rev_ttm * 100, "(Revenue − expenses + finance cost + depreciation) ÷ revenue, last 4 quarters",
                                    {"ebitda_ttm_cr": _cr(ebitda_ttm), "revenue_ttm_cr": _cr(rev_ttm)}, ttm_src, url)
    if q.get("rev") and not lender:
        opq = q["rev"] - q["exp"] + (q.get("fin") or 0) + (q.get("dep") or 0) if q.get("exp") is not None else None
        if opq is not None:
            M["ebitda_margin_q_pct"] = _m(opq / q["rev"] * 100, "Quarter EBITDA ÷ quarter revenue", {"ebitda_cr": _cr(opq), "revenue_cr": _cr(q["rev"])}, src, url)
    if oi_ttm is not None and pbt_core and pbt_core > 0 and not lender:
        M["other_income_pct_pbt"] = _m(oi_ttm / pbt_core * 100, "Other income ÷ profit before tax and exceptional items, last 4 quarters",
                                       {"other_income_cr": _cr(oi_ttm), "pbt_cr": _cr(pbt_core)}, ttm_src, url)
    if ebit_ttm is not None and fin_ttm and not lender:
        M["interest_cover"] = _m(ebit_ttm / fin_ttm, "Operating profit (EBIT) ÷ finance cost, last 4 quarters",
                                 {"ebit_cr": _cr(ebit_ttm), "finance_cost_cr": _cr(fin_ttm)}, ttm_src, url)

    # growth: latest quarter vs same quarter last year; TTM vs previous TTM
    yago = _prev_q(_q_end(latest), 4)
    pq = (s["q"].get(yago) or {}).get("q") or {}
    for key, name in (("rev", "revenue"), ("pat_owners", "profit")):
        g = _growth(q.get(key), pq.get(key))
        if g is not None:
            nm = not GROWTH_CAP[0] <= g <= GROWTH_CAP[1]
            m = _m(g, f"Quarter {name} ÷ same quarter last year − 1", {"this_q_cr": _cr(q.get(key)), "year_ago_cr": _cr(pq.get(key))},
                   f"NSE filings for {latest} and {yago}", url)
            if nm:
                m["nm"] = True
            M[f"{'rev' if key == 'rev' else 'pat'}_yoy_pct"] = m
    prev_ttm_end = yago
    for key, name in (("rev", "revenue"), ("pat_owners", "profit")):
        cur, prev = _ttm(s, key, latest), _ttm(s, key, prev_ttm_end) if prev_ttm_end in s["q"] else None
        g = _growth(cur, prev)
        if g is not None:
            m = _m(g, f"Last-4-quarter {name} ÷ previous 4 quarters − 1", {"ttm_cr": _cr(cur), "prev_ttm_cr": _cr(prev)}, ttm_src, url)
            if not GROWTH_CAP[0] <= g <= GROWTH_CAP[1]:
                m["nm"] = True
            M[f"{'rev' if key == 'rev' else 'pat'}_ttm_growth_pct"] = m

    # EPS: split/bonus-adjusted to today's share count, 3-year CAGR on full-year numbers, PEG
    fy_pat = _fy_values(s, "pat_owners")
    if fy_pat and shares:
        y1 = max(fy_pat)
        y0 = y1 - 3
        if y0 in fy_pat and fy_pat[y0] > 0 and fy_pat[y1] > 0:
            cagr = ((fy_pat[y1] / fy_pat[y0]) ** (1 / 3) - 1) * 100
            # per-share growth adjusts for dilution: shares then vs now
            p0 = s["q"].get(f"{y0}-03-31") or {}
            sh_then, fv_then, fv_now = p0.get("shares"), (p0.get("q") or {}).get("fv"), q.get("fv")
            eps_cagr = None
            if sh_then and fv_then and fv_now:
                sh_then_adj = sh_then * fv_then / fv_now  # splits / consolidations change face value
                ratio = shares / sh_then_adj
                if 0.8 <= ratio <= 1.25:  # larger changes may be bonus issues, which filings do not label: leave as dash
                    eps_cagr = (((fy_pat[y1] / shares) / (fy_pat[y0] / sh_then_adj)) ** (1 / 3) - 1) * 100
            M["pat_cagr_3y_pct"] = _m(cagr, f"(FY{y1 % 100} profit ÷ FY{y0 % 100} profit)^(1/3) − 1 (3-year growth)",
                                      {f"fy{y1 % 100}_cr": _cr(fy_pat[y1]), f"fy{y0 % 100}_cr": _cr(fy_pat[y0]), "years": 3}, "NSE full-year filings", url)
            if eps_cagr is not None:
                M["eps_cagr_3y_pct"] = _m(eps_cagr, "3-year growth in profit per share, adjusted for splits, bonuses and dilution",
                                          {"shares_now": shares, f"shares_fy{y0 % 100}_split_adjusted": sh_then_adj}, "NSE full-year filings", url)
                if eps_cagr > 100:
                    M["eps_cagr_3y_pct"]["nm"] = True
                elif M.get("pe") and eps_cagr > 0:
                    M["peg"] = _m(M["pe"]["v"] / eps_cagr, "P/E ÷ 3-year EPS growth (%)", {"pe": M["pe"]["v"], "eps_cagr_pct": eps_cagr},
                                  "Computed", url, 2)

    # balance sheet (filed half-yearly)
    bq, bp = _latest_bs(s)
    if bp:
        bs = bp["bs"]
        bsrc, burl = _src(bp, basis), bp.get("url")
        eq = bs.get("equity_owners") or bs.get("equity")
        borr = (bs.get("borr_cur") or 0) + (bs.get("borr_ncur") or 0)
        lease = (bs.get("lease_cur") or 0) + (bs.get("lease_ncur") or 0)
        debt = borr + lease  # Ind AS 116: lease liabilities are debt (EBITDA already adds the lease cost back)
        cash = (bs.get("cash") or 0) + (bs.get("bank_bal") or 0)
        M["bs_date"] = bq
        M["lease_cr"] = _cr(lease) if lease else 0.0
        # leases paid in the period but no lease line in the balance sheet (filed inside "other financial liabilities"):
        # debt may be understated, so the stock gets the "check leases" flag instead of a silent zero
        lpay = ((bp.get("ytd") or {}).get("lease_pay") or (bp.get("q") or {}).get("lease_pay") or 0)
        M["leases_known"] = "lease_chk" in bs and not (not lease and lpay > 0)
        if eq and eq > 0:
            if mcap:
                M["pb"] = _m(mcap / _cr(eq), "Market cap ÷ shareholders' equity", {"mcap_cr": mcap, "equity_cr": _cr(eq)}, bsrc, burl)
            M["de"] = _m(debt / eq, "(Borrowings + lease liabilities) ÷ equity", {"borrowings_cr": _cr(borr), "lease_liabilities_cr": _cr(lease), "equity_cr": _cr(eq)}, bsrc, burl, 2)
            # average equity: this balance sheet and the one a year earlier
            pq_, pp_ = _latest_bs(s, _prev_q(_q_end(bq), 4))
            eq0 = ((pp_ or {}).get("bs") or {}).get("equity_owners") or ((pp_ or {}).get("bs") or {}).get("equity") if pq_ == _prev_q(_q_end(bq), 4) else None
            avg_eq = (eq + eq0) / 2 if eq0 else eq
            if pat_ttm is not None:
                M["roe_pct"] = _m(pat_ttm / avg_eq * 100 if avg_eq else 0.0,
                                  "Profit (last 4 quarters) ÷ average equity" + ("" if eq0 else " (latest equity only)"),
                                  {"pat_ttm_cr": _cr(pat_ttm), "avg_equity_cr": _cr(avg_eq)}, bsrc, burl)
                why = roe_nm(pat_ttm, eq, eq0)
                if why:  # shown as n/m and kept out of scores (DIACABS 1,662%, GAYAPROJ −902% on a profit, BLAL +8% on a loss)
                    M["roe_pct"].update({"nm": True, "nm_why": why})
            if ebit_ttm is not None and eq + debt > 0 and not lender:
                M["roce_pct"] = _m(ebit_ttm / (eq + debt) * 100, "EBIT (last 4 quarters) ÷ (equity + borrowings + lease liabilities)",
                                   {"ebit_ttm_cr": _cr(ebit_ttm), "capital_employed_cr": _cr(eq + debt)}, bsrc, burl)
        if lender:
            _lender_metrics(M, s, bq, bp, basis)
        if lender:
            M.pop("de", None)
        if mcap is not None and ebitda_ttm and ebitda_ttm > 0:
            ev = mcap + _cr(debt) - _cr(cash)
            M["ev_ebitda"] = _m(ev / _cr(ebitda_ttm), "(Market cap + borrowings + lease liabilities − cash) ÷ EBITDA (last 4 quarters)",
                                {"mcap_cr": mcap, "borrowings_cr": _cr(borr), "lease_liabilities_cr": _cr(lease), "cash_cr": _cr(cash), "ebitda_ttm_cr": _cr(ebitda_ttm)}, bsrc, burl)
        if mcap and not lender:
            M["net_cash_pct_mcap"] = _m((_cr(cash) - _cr(debt)) / mcap * 100, "(Cash + bank balances − borrowings − lease liabilities) ÷ market cap",
                                        {"cash_cr": _cr(cash), "debt_cr": _cr(debt), "mcap_cr": mcap}, bsrc, burl)
        if rev_ttm and bs.get("recv") is not None and not lender:
            M["receivable_days"] = _m(bs["recv"] / rev_ttm * 365, "Trade receivables ÷ revenue (last 4 quarters) × 365",
                                      {"receivables_cr": _cr(bs["recv"]), "revenue_ttm_cr": _cr(rev_ttm)}, bsrc, burl, 0)
        if rev_ttm and bs.get("inventory") and not lender:
            M["inventory_days"] = _m(bs["inventory"] / rev_ttm * 365, "Inventories ÷ revenue (last 4 quarters) × 365",
                                     {"inventory_cr": _cr(bs["inventory"]), "revenue_ttm_cr": _cr(rev_ttm)}, bsrc, burl, 0)
        if bs.get("cwip") is not None and bs.get("ppe") and not lender:
            M["cwip_pct_ppe"] = _m(bs["cwip"] / bs["ppe"] * 100, "Capital work in progress ÷ property, plant and equipment",
                                   {"cwip_cr": _cr(bs["cwip"]), "ppe_cr": _cr(bs["ppe"])}, bsrc, burl)
        if bs.get("ppe") and rev_ttm and not lender:
            M["asset_turnover"] = _m(rev_ttm / bs["ppe"], "Revenue (last 4 quarters) ÷ property, plant and equipment",
                                     {"revenue_ttm_cr": _cr(rev_ttm), "ppe_cr": _cr(bs["ppe"])}, bsrc, burl, 2)

    # cash conversion: full-year cash from operations ÷ full-year EBITDA, last 3 years
    fy_cfo = _fy_values(s, "cfo")
    fy_pbt, fy_fin, fy_dep, fy_oi = (_fy_values(s, k) for k in ("pbt", "fin", "dep", "oi"))
    yrs = sorted(y for y in fy_cfo if y in fy_pbt and y in fy_fin and y in fy_dep)[-3:]
    fy_exc = _fy_values(s, "exceptional")
    if len(yrs) >= 2 and not lender:
        cfo = sum(fy_cfo[y] for y in yrs)
        op = sum(fy_pbt[y] - fy_exc.get(y, 0) + fy_fin[y] + fy_dep[y] - fy_oi.get(y, 0) for y in yrs)
        if op > 0:  # RULES.md R1 asks for 3 full years: 3 are used whenever filed; 2 only when that is all there is (marked)
            M["cfo_to_ebitda_pct"] = _m(cfo / op * 100, f"Cash from operations ÷ EBITDA, FY{yrs[0] % 100}–FY{yrs[-1] % 100}"
                                        + ("" if len(yrs) >= 3 else " (2 full years filed, not 3)"),
                                        {"cfo_cr": _cr(cfo), "ebitda_cr": _cr(op), "years": len(yrs)}, "NSE full-year filings", url, 0)
            M["cfo_to_ebitda_pct"]["exact"] = cfo / op * 100  # the R1 gate compares this, not the rounded value (49.5% is < 50%)
        fy_capex = _fy_values(s, "capex")
        cy = [y for y in yrs if fy_capex.get(y)]
        if cy and mcap:
            fcf = fy_cfo[cy[-1]] - abs(fy_capex[cy[-1]])
            M["fcf_yield_pct"] = _m(_cr(fcf) / mcap * 100, f"(FY{cy[-1] % 100} cash from operations − capex) ÷ market cap",
                                    {"cfo_cr": _cr(fy_cfo[cy[-1]]), "capex_cr": _cr(abs(fy_capex[cy[-1]])), "mcap_cr": mcap}, "NSE full-year filings", url)
            rv = _fy_values(s, "rev")
            if cy[-1] in rv and rv[cy[-1]]:
                M["capex_pct_rev"] = _m(abs(fy_capex[cy[-1]]) / rv[cy[-1]] * 100, f"FY{cy[-1] % 100} capex ÷ revenue",
                                        {"capex_cr": _cr(abs(fy_capex[cy[-1]])), "revenue_cr": _cr(rv[cy[-1]])}, "NSE full-year filings", url)

    _funnel_inputs(M, s, latest, lender, mcap, shares, url)

    if mcap and promoter_pct is not None:
        M["free_float_mcap_cr"] = _m(mcap * (1 - promoter_pct / 100), "Market cap × (1 − promoter holding)",
                                     {"mcap_cr": mcap, "promoter_pct": promoter_pct}, "NSE shareholding filing", None, 0, "₹ cr")
    M["quarters_available"] = len(s["q"])
    return M


def _yahoo_fallback(y: dict | None, price: float, promoter_pct: float | None) -> dict:
    """Same formulas on Yahoo statement line items when no NSE filing is available (e.g. BSE-only stocks)."""
    M = {"source": "Yahoo statements", "flags": []}
    if not y:
        return M
    qs = [q for q in (y.get("quarters") or []) if q.get("revenue") is not None]
    src = "Yahoo statements (fallback: no NSE filing)"
    if not qs:
        return M
    M["last_quarter"] = qs[-1]["date"]
    mcap = None  # Yahoo share count is not a filed figure; market cap from Yahoo price × shares only if present
    if y.get("sharesOutstanding") and price:
        mcap = price * y["sharesOutstanding"] / CR
        M["mcap_cr"] = _m(mcap, "Price × shares outstanding", {"price": price, "shares": y["sharesOutstanding"]}, src, None, 0, "₹ cr")
    if len(qs) >= 4:
        rev = sum(q["revenue"] for q in qs[-4:])
        ni = [q.get("net_income") for q in qs[-4:]]
        M["revenue_ttm_cr"] = _m(_cr(rev), "Sum of revenue, last 4 quarters", {}, src, None, 1, "₹ cr")
        if None not in ni:
            pat = sum(ni)
            M["pat_ttm_cr"] = _m(_cr(pat), "Sum of net income, last 4 quarters", {}, src, None, 1, "₹ cr")
            if mcap and pat > 0:
                M["pe"] = _m(mcap / _cr(pat), "Market cap ÷ profit (last 4 quarters)", {"mcap_cr": mcap, "pat_ttm_cr": _cr(pat)}, src)
    if len(qs) >= 5 and qs[-5]["revenue"]:
        g = _growth(qs[-1]["revenue"], qs[-5]["revenue"])
        if g is not None:
            m = _m(g, "Quarter revenue ÷ same quarter last year − 1", {"this_q_cr": _cr(qs[-1]["revenue"]), "year_ago_cr": _cr(qs[-5]["revenue"])}, src)
            if not GROWTH_CAP[0] <= g <= GROWTH_CAP[1]:
                m["nm"] = True
            M["rev_yoy_pct"] = m
    if mcap and promoter_pct is not None:
        M["free_float_mcap_cr"] = _m(mcap * (1 - promoter_pct / 100), "Market cap × (1 − promoter holding)",
                                     {"mcap_cr": mcap, "promoter_pct": promoter_pct}, "NSE/BSE shareholding filing", None, 0, "₹ cr")
    return M


def _bse_overlay(M: dict, b: dict | None, y: dict | None) -> dict:
    """Revenue / profit from BSE's results summary (exchange data) over the Yahoo fallback; Yahoo kept for what BSE lacks.
    A Yahoo quarter that disagrees with BSE by more than 5% is flagged."""
    qs = (b or {}).get("q") or {}
    if not qs:
        return M
    src, url = "BSE results summary (no NSE filing)", b.get("url")
    latest = max(qs)
    M["source"] = "BSE results summary + Yahoo statements" if M.get("source") == "Yahoo statements" else "BSE results summary"
    M.setdefault("flags", [])
    if latest >= (M.get("last_quarter") or ""):
        M["last_quarter"] = latest
    four = [_prev_q(_q_end(latest), i) if i else latest for i in range(4)]
    if all(qs.get(d, {}).get("rev") is not None for d in four):
        rev = sum(qs[d]["rev"] for d in four)
        M["revenue_ttm_cr"] = _m(rev, "Sum of revenue, last 4 quarters", {}, f"BSE results summary, quarters to {latest}", url, 1, "₹ cr")
        if all(qs[d].get("pat") is not None for d in four):
            pat = sum(qs[d]["pat"] for d in four)
            M["pat_ttm_cr"] = _m(pat, "Sum of net profit, last 4 quarters", {}, f"BSE results summary, quarters to {latest}", url, 1, "₹ cr")
            mc = (M.get("mcap_cr") or {}).get("v")
            if mc and pat > 0:
                M["pe"] = _m(mc / pat, "Market cap ÷ profit (last 4 quarters)", {"mcap_cr": mc, "pat_ttm_cr": pat}, src, url)
    yago = _prev_q(_q_end(latest), 4)
    cur, old = qs[latest].get("rev"), (qs.get(yago) or {}).get("rev")
    g = _growth(cur, old)
    if g is not None:
        m = _m(g, "Quarter revenue ÷ same quarter last year − 1", {"this_q_cr": cur, "year_ago_cr": old}, src, url)
        if not GROWTH_CAP[0] <= g <= GROWTH_CAP[1]:
            m["nm"] = True
        M["rev_yoy_pct"] = m
    for yq in (y or {}).get("quarters") or []:  # cross-check Yahoo against the exchange where both have the quarter
        d, r = str(yq.get("date") or "")[:10], yq.get("revenue")
        bq = (qs.get(d) or {}).get("rev")
        if r and bq and abs(_cr(r) / bq - 1) > 0.05:
            M["flags"].append(f"Yahoo revenue for the quarter to {d} differs from BSE by {(_cr(r) / bq - 1) * 100:+.0f}%: BSE figure used")
    return M


def val(M: dict, key: str):
    """Plain value for scoring; None if missing or not meaningful."""
    m = M.get(key)
    if not isinstance(m, dict) or m.get("nm"):
        return None
    return m.get("v")


def inflection(fin: dict, roe_pct: float | None = None) -> tuple[float, dict] | None:
    """Same scoring as fundamentals.inflection, on filed quarterly numbers. None if fewer than 5 quarters."""
    s = series(fin)
    if not s or len(s["q"]) < 5:
        return None
    qs = list(s["q"].items())  # newest first
    latest = qs[0][0]
    d = _q_end(latest)

    def qv(end, key):
        return ((s["q"].get(end) or {}).get("q") or {}).get(key)

    def yoy(end, key):
        return _growth(qv(end, key), qv(_prev_q(_q_end(end), 4), key))

    m = {"rev_yoy": yoy(latest, "rev"), "rev_yoy_prev": yoy(_prev_q(d, 1), "rev")}
    m = {k: (v / 100 if v is not None else None) for k, v in m.items()}
    r0, r1, r2 = qv(latest, "rev"), qv(_prev_q(d, 1), "rev"), qv(_prev_q(d, 2), "rev")
    m["rev_qoq_up2"] = bool(None not in (r0, r1, r2) and r0 > r1 > r2)

    def opm(end):
        q = (s["q"].get(end) or {}).get("q") or {}
        if q.get("rev") and q.get("exp") is not None:
            return (q["rev"] - q["exp"] + (q.get("fin") or 0) + (q.get("dep") or 0)) / q["rev"]
        return None
    m["opm"], m["opm_ref"] = opm(latest), opm(_prev_q(d, 4))
    p_now, p_then = qv(latest, "pat_owners"), qv(_prev_q(d, 4), "pat_owners")
    m["turnaround"] = bool(p_now is not None and p_then is not None and p_then <= 0 < p_now)
    g = None if m["turnaround"] else _growth(_ttm(s, "pat_owners", latest), _ttm(s, "pat_owners", _prev_q(d, 4)) if _prev_q(d, 4) in s["q"] else None)
    m["ni_yoy"] = g / 100 if g is not None else None
    m["last_quarter"] = latest
    sc, have = 0.0, 0
    if m["rev_yoy"] is not None:
        have += 1
        sc += min(25, max(0, m["rev_yoy"] / 0.25 * 25))
        if m["rev_yoy_prev"] is not None:
            sc += 15 if m["rev_yoy"] > m["rev_yoy_prev"] + 0.02 else 0
        elif m["rev_qoq_up2"]:
            sc += 10
    if m["opm"] is not None and m["opm_ref"] is not None:
        have += 1
        sc += 20 if m["opm"] > m["opm_ref"] + 0.01 else 0
    if m["turnaround"]:
        have += 1
        sc += 20
    elif m["ni_yoy"] is not None:
        have += 1
        sc += min(20, max(0, min(m["ni_yoy"], 3) / 0.4 * 20))
    if roe_pct is not None:
        have += 1
        sc += 20 if roe_pct >= 18 else 12 if roe_pct >= 12 else 0
    m["completeness"] = have
    return float(min(100, sc)), m


def pe_band(fin: dict, closes) -> dict | None:
    """The stock's own P/E range: close ~45 days after each quarter end ÷ trailing-4-quarter profit per share.
    Uses only filed profit and the share count of that quarter. Needs >= 4 points."""
    s = series(fin)
    if not s or closes is None or len(closes) < 100:
        return None
    pts = []
    for qe, p in s["q"].items():
        ttm = _ttm(s, "pat_owners", qe)
        sh = p.get("shares")
        if not ttm or ttm <= 0 or not sh:
            continue
        d = _q_end(qe)
        from datetime import timedelta
        when = d + timedelta(days=45)
        c = closes[closes.index.date >= when]
        if c.empty:
            continue
        pts.append((qe, float(c.iloc[0]) * sh / ttm))
    if len(pts) < 4:
        return None
    vals = [v for _, v in pts]
    return {"low": round(min(vals), 1), "high": round(max(vals), 1), "n": len(pts),
            "from": min(q for q, _ in pts), "to": max(q for q, _ in pts)}


# ---------------------------------------------------------------- v2 funnel inputs (all from filed numbers)
def _qv(s: dict, end: str, key: str):
    return ((s["q"].get(end) or {}).get("q") or {}).get(key)


def _ebitda_q(p: dict | None):
    q = (p or {}).get("q") or {}
    if q.get("rev") is None or q.get("exp") is None:
        return None
    return q["rev"] - q["exp"] + (q.get("fin") or 0) + (q.get("dep") or 0)


def _ttm_ebitda(s: dict, end: str):
    d = _q_end(end)
    vals = [_ebitda_q(s["q"].get(_prev_q(d, i) if i else end)) for i in range(4)]
    return None if None in vals else sum(vals)


def _fy_ebitda(s: dict) -> dict:
    rev, exp, fin, dep = (_fy_values(s, k) for k in ("rev", "exp", "fin", "dep"))
    return {y: rev[y] - exp[y] + fin.get(y, 0) + dep.get(y, 0) for y in rev if y in exp}


def _bs_at(s: dict, qe: str):
    bs = (s["q"].get(qe) or {}).get("bs") or {}
    return bs if bs.get("equity") is not None else None


def _debt_cash(bs: dict):
    """Debt includes lease liabilities (Ind AS 116)."""
    return ((bs.get("borr_cur") or 0) + (bs.get("borr_ncur") or 0) + (bs.get("lease_cur") or 0) + (bs.get("lease_ncur") or 0),
            (bs.get("cash") or 0) + (bs.get("bank_bal") or 0))


def _funnel_inputs(M: dict, s: dict, latest: str, lender: bool, mcap, shares, url) -> None:
    d = _q_end(latest)
    yago, y2ago = _prev_q(d, 4), _prev_q(d, 8)
    lp = s["q"][latest]
    M["filed"] = lp.get("filed")
    if lp.get("filed_time"):
        M["filed_time"] = lp["filed_time"]  # IST time of the broadcast (funnel.signal_triggers: T11 after the close)
    ttm_src = f"NSE filings to {latest}"
    fy_rev = _fy_values(s, "rev")
    for key, name, mk in (("rev", "revenue", "rev_cagr_3y_pct"), ("pat_owners", "profit", "pat_cagr_3y_pct")):
        fy = fy_rev if key == "rev" else _fy_values(s, key)
        if not fy or (mk in M and M[mk]):
            continue
        y1 = max(fy)
        # 3 years where FY(y1-3) is filed, else 2. The key keeps its "_3y" name (the app reads it); the span actually used is
        # in the formula and in inputs["years"], and every label reads it from there (FY23 needs the Reg-33 full-year
        # column, see filings.YTD_CHK: until a stock's old March filing is re-read the rate is a 2-year one)
        n = 3 if y1 - 3 in fy else 2 if y1 - 2 in fy else 0
        y0 = y1 - n
        if n and fy[y0] > 0 and fy[y1] > 0:
            M[mk] = _m(((fy[y1] / fy[y0]) ** (1 / n) - 1) * 100, f"(FY{y1 % 100} {name} ÷ FY{y0 % 100} {name})^(1/{n}) − 1 ({n}-year growth)",
                       {f"fy{y1 % 100}_cr": _cr(fy[y1]), f"fy{y0 % 100}_cr": _cr(fy[y0]), "years": n}, "NSE full-year filings", url)
    r_now, r_then, r_then2 = _ttm(s, "rev", latest), _ttm(s, "rev", yago) if yago in s["q"] else None, _ttm(s, "rev", y2ago) if y2ago in s["q"] else None
    g = _growth(r_then, r_then2)
    if g is not None:
        M["rev_ttm_growth_prev_pct"] = _m(g, "Revenue growth of the 4 quarters to a year ago vs the 4 quarters before",
                                          {"ttm_year_ago_cr": _cr(r_then), "ttm_two_years_ago_cr": _cr(r_then2)}, ttm_src, url)
    g = _growth(_qv(s, _prev_q(d, 1), "rev"), _qv(s, _prev_q(d, 5), "rev"))
    if g is not None:
        M["rev_yoy_prev_pct"] = _m(g, "Previous quarter revenue ÷ same quarter a year earlier − 1",
                                   {"quarter": _prev_q(d, 1), "this_q_cr": _cr(_qv(s, _prev_q(d, 1), "rev")), "year_ago_cr": _cr(_qv(s, _prev_q(d, 5), "rev"))}, ttm_src, url)
    g2 = _growth(_qv(s, _prev_q(d, 2), "rev"), _qv(s, _prev_q(d, 6), "rev"))
    if g2 is not None:
        M["rev_yoy_prev2_pct"] = _m(g2, "Revenue YoY two quarters ago", {"quarter": _prev_q(d, 2)}, ttm_src, url)
    pats = [_qv(s, _prev_q(d, i) if i else latest, "pat_owners") for i in range(4)]
    if None not in pats:
        # judged on the figure shown (₹ cr, 1 decimal): a −₹0.9 lakh quarter shows as 0.0 and is break-even, not a loss
        shown = [round(_cr(x), 1) + 0.0 for x in pats]  # + 0.0 turns −0.0 into 0.0
        M["loss_quarters_4"] = _m(float(sum(1 for x in shown if x < 0)), "Quarters with a net loss, last 4 (a loss that rounds to ₹0.0 cr counts as break-even)",
                                  {"profits_cr": ", ".join(f"{x:,.1f}" for x in shown),  # newest first
                                   "quarters": ", ".join(str(_prev_q(d, i) if i else latest)[:10] for i in range(4))}, ttm_src, url, 0)

    bq, bp = _latest_bs(s)
    bs = (bp or {}).get("bs") or {}
    debt, cash = _debt_cash(bs) if bs else (None, None)
    if bs:
        eq = bs.get("equity_owners") or bs.get("equity")
        M["equity_cr"] = _m(_cr(eq), "Shareholders' equity (latest balance sheet)", {"date": bq}, _src(bp, s["basis"]), bp.get("url"), 1, "₹ cr")
        if bs.get("assets"):
            inv = (bs.get("inv_ncur") or 0) + (bs.get("inv_cur") or 0)
            M["investments_pct_assets"] = _m(inv / bs["assets"] * 100, "Investments ÷ total assets", {"investments_cr": _cr(inv), "assets_cr": _cr(bs["assets"])}, _src(bp, s["basis"]), bp.get("url"))
            pat_ttm = _ttm(s, "pat_owners", latest)
            if lender and pat_ttm is not None:
                M["roa_pct"] = _m(pat_ttm / bs["assets"] * 100, "Profit (last 4 quarters) ÷ total assets", {"pat_ttm_cr": _cr(pat_ttm), "assets_cr": _cr(bs["assets"])}, _src(bp, s["basis"]), bp.get("url"), 2)
        if not lender and bs.get("cur_assets") and bs.get("cur_liab"):
            M["current_ratio"] = _m(bs["cur_assets"] / bs["cur_liab"], "Current assets ÷ current liabilities",
                                    {"current_assets_cr": _cr(bs["cur_assets"]), "current_liabilities_cr": _cr(bs["cur_liab"]),
                                     "short_term_borrowings_cr": _cr(bs.get("borr_cur") or 0), "cash_and_bank_cr": _cr(cash)}, _src(bp, s["basis"]), bp.get("url"), 2)
        b0 = _bs_at(s, _prev_q(_q_end(bq), 4))
        if b0 and not lender:
            debt0, _ = _debt_cash(b0)
            eq0 = b0.get("equity_owners") or b0.get("equity")
            if debt0 > 0 and eq0 and debt0 >= 0.1 * eq0:
                M["debt_chg_yoy_pct"] = _m((debt - debt0) / debt0 * 100, "Borrowings now ÷ borrowings a year earlier − 1",
                                           {"debt_now_cr": _cr(debt), "debt_year_ago_cr": _cr(debt0)}, _src(bp, s["basis"]), bp.get("url"))
    if lender:
        return
    e_ttm = _ttm_ebitda(s, latest)
    if bs and e_ttm and e_ttm > 0:
        M["net_debt_ebitda"] = _m((debt - cash) / e_ttm, "(Borrowings + lease liabilities − cash and bank) ÷ EBITDA (last 4 quarters)",
                                  {"debt_cr": _cr(debt), "cash_cr": _cr(cash), "ebitda_ttm_cr": _cr(e_ttm)}, ttm_src, url, 2)
    if bs and mcap and r_now:
        M["ev_sales"] = _m((mcap + _cr(debt) - _cr(cash)) / _cr(r_now), "(Market cap + borrowings + lease liabilities − cash) ÷ revenue (last 4 quarters)",
                           {"mcap_cr": mcap, "debt_cr": _cr(debt), "cash_cr": _cr(cash), "revenue_ttm_cr": _cr(r_now)}, ttm_src, url, 2)
    e_then = _ttm_ebitda(s, yago) if yago in s["q"] else None
    if e_then is not None and r_then:
        M["ebitda_margin_prev_pct"] = _m(e_then / r_then * 100, "EBITDA margin of the 4 quarters to a year ago", {"ebitda_cr": _cr(e_then), "revenue_cr": _cr(r_then)}, ttm_src, url)
    mq = _ebitda_q(s["q"].get(yago))
    if mq is not None and _qv(s, yago, "rev"):
        M["ebitda_margin_q_yago_pct"] = _m(mq / _qv(s, yago, "rev") * 100, "EBITDA margin of the same quarter a year ago", {"quarter": yago}, ttm_src, url)
    margins = []
    for i in range(12):
        qe = _prev_q(d, i) if i else latest
        e, r = _ebitda_q(s["q"].get(qe)), _qv(s, qe, "rev")
        if e is not None and r:
            margins.append(e / r * 100)
    if len(margins) >= 8:
        M["margin_range_12q_pts"] = _m(max(margins) - min(margins), "Highest − lowest quarterly EBITDA margin, last 12 quarters", {"quarters": len(margins)}, ttm_src, url)
    fy_e, fy_dep = _fy_ebitda(s), _fy_values(s, "dep")
    years = sorted(y for y in fy_e if fy_rev.get(y))
    if years:
        y1 = years[-1]
        y0 = y1 - 3 if y1 - 3 in years else (y1 - 2 if y1 - 2 in years else None)
        if y0:
            m1, m0 = fy_e[y1] / fy_rev[y1] * 100, fy_e[y0] / fy_rev[y0] * 100
            M["margin_chg_3y_pts"] = _m(m1 - m0, f"FY{y1 % 100} EBITDA margin − FY{y0 % 100} EBITDA margin ({y1 - y0}-year change)",
                                        {f"fy{y1 % 100}_pct": m1, f"fy{y0 % 100}_pct": m0, "years": y1 - y0}, "NSE full-year filings", url)
        last3 = years[-3:]
        avg_m = sum(fy_e[y] / fy_rev[y] for y in last3) / len(last3)
        if bs and mcap and r_now and avg_m > 0:
            mid = avg_m * r_now
            M["ev_midcycle_ebitda"] = _m((mcap + _cr(debt) - _cr(cash)) / _cr(mid), f"EV ÷ (average FY{last3[0] % 100}–FY{last3[-1] % 100} EBITDA margin × revenue, last 4 quarters)",
                                         {"avg_margin_pct": avg_m * 100, "revenue_ttm_cr": _cr(r_now), "midcycle_ebitda_cr": _cr(mid)}, ttm_src, url)
    roce = {}
    for y in years:
        b = _bs_at(s, f"{y}-03-31")
        if b and y in fy_dep:
            dbt, _ = _debt_cash(b)
            ce = (b.get("equity_owners") or b.get("equity") or 0) + dbt
            if ce > 0:
                roce[y] = (fy_e[y] - fy_dep[y]) / ce * 100
    if len(roce) >= 2:
        ys = sorted(roce)[-3:]
        M["roce_3y_avg_pct"] = _m(sum(roce[y] for y in ys) / len(ys), f"Average of FY{ys[0] % 100}–FY{ys[-1] % 100} ROCE ({len(ys)} years; "
                                  "EBIT ÷ equity + borrowings + lease liabilities at year end)",
                                  {**{f"fy{y % 100}_pct": roce[y] for y in ys}, "years": len(ys)}, "NSE full-year filings", url)
    fy_cfo, fy_pat = _fy_values(s, "cfo"), _fy_values(s, "pat_owners")
    cy = sorted(fy_cfo)[-3:]
    if len(cy) >= 2:
        M["cfo_negative_years"] = _m(float(sum(1 for y in cy if fy_cfo[y] < 0)), f"Years with negative cash from operations, FY{cy[0] % 100}–FY{cy[-1] % 100}",
                                     {**{f"cfo_fy{y % 100}_cr": _cr(fy_cfo[y]) for y in cy}, "profit_latest_fy_cr": _cr(fy_pat.get(cy[-1]))}, "NSE full-year filings", url, 0)
    # dilution: share count now vs 12 quarters ago, adjusted for splits via face value
    p0 = s["q"].get(_prev_q(d, 12)) or {}
    if shares and p0.get("shares") and (p0.get("q") or {}).get("fv") and (lp.get("q") or {}).get("fv"):
        adj = p0["shares"] * p0["q"]["fv"] / lp["q"]["fv"]
        ratio = shares / adj
        if 0.8 <= ratio <= 1.25:
            M["dilution_3y_pct"] = _m((ratio - 1) * 100, "Shares now ÷ shares 12 quarters ago (split-adjusted) − 1",
                                      {"shares_now": shares, "shares_then_adjusted": adj}, ttm_src, url)
    M["quarterly"] = [[qe, round(_cr(_qv(s, qe, "rev")) or 0, 1), round(_cr(_qv(s, qe, "pat_owners")) or 0, 1),
                       (round(_ebitda_q(s["q"][qe]) / _qv(s, qe, "rev") * 100, 1) if _ebitda_q(s["q"][qe]) is not None and _qv(s, qe, "rev") else None)]
                      for qe in sorted(s["q"])[-16:]]
    if roce:
        M["roce_fy"] = [[y, round(v, 1)] for y, v in sorted(roce.items())]


def history(fin: dict, closes) -> list[dict]:
    """Multiples at each quarter: close ~45 days after quarter end with that quarter's share count and trailing numbers."""
    from datetime import timedelta
    s = series(fin)
    if not s or closes is None or len(closes) < 100:
        return []
    out = []
    for qe, p in sorted(s["q"].items()):
        sh = p.get("shares")
        if not sh:
            continue
        c = closes[closes.index.date >= _q_end(qe) + timedelta(days=45)]
        if c.empty:
            continue
        mc = float(c.iloc[0]) * sh
        row = {"q": qe}
        pat = _ttm(s, "pat_owners", qe)
        if pat and pat > 0:
            row["pe"] = mc / pat
        bq_, bp_ = _latest_bs(s, qe)
        if bp_:
            b = bp_["bs"]
            eq = b.get("equity_owners") or b.get("equity")
            if eq and eq > 0:
                row["pb"] = mc / eq
            dbt, csh = _debt_cash(b)
            e = _ttm_ebitda(s, qe)
            if e and e > 0:
                row["ev_ebitda"] = (mc + dbt - csh) / e
            r = _ttm(s, "rev", qe)
            if r:
                row["ev_sales"] = (mc + dbt - csh) / r
        if len(row) > 1:
            out.append(row)
    return out
