"""Upside checks U1-U5 (owner, 21 Nov 2026: "when can we expect upside on a stock"). Computed from filed numbers only.

Price = earnings x multiple, so upside needs earnings to grow faster than priced in, the multiple to re-rate, or selling
pressure to end. T7 already covers revenue accelerating with margin; these add what it does not:
  U1 Profit speeding up   : quarterly owners' profit YoY rising 2 quarters in a row, latest >= 15%, revenue YoY >= 10%
  U2 Operating leverage   : EBITDA (last 4 quarters) growing >= 5 pts faster than revenue, revenue >= 10%, margin up
  U3 Re-rating setup      : ROCE up on the year, debt not rising, multiple below its own median and below the peer median
  U4 Selling overhang over: promoter stake stopped falling (fell >= 1 pt over the 4 quarters before, flat or up now), or
                            promoter pledge cleared (zero now, above zero a quarter ago)
  U5 Both engines         : U1 or U2 (earnings) and U3 (multiple) together
Each check returns True / False, or None when the inputs are missing (never passed silently).
"""


def _yoy(a, b):
    return (a / b - 1) * 100 if a is not None and b is not None and b > 0 else None


_QEND = {3: 31, 6: 30, 9: 30, 12: 31}


def _back(qe: str, n: int) -> str | None:
    """The quarter end n quarters before qe ("2026-09-30", 4 -> "2025-09-30"); None when qe is not a quarter end."""
    try:
        y, m = int(qe[:4]), int(qe[5:7])
    except (TypeError, ValueError):
        return None
    if m not in _QEND:
        return None
    m -= 3 * n
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}-{_QEND[m]}"


def _run(q: list, n: int) -> list | None:
    """The last n quarters as consecutive quarter ends (oldest first), or None when one is missing: `quarterly` holds only
    the quarters filed, so positions are not periods (audit 26 Nov 2026: TAJGVK compared Sep-2026 with Jun-2025)."""
    if not q:
        return None
    by = {r[0]: r for r in q if isinstance(r, list) and r}
    last = q[-1][0]
    keys = [_back(last, i) for i in range(n - 1, -1, -1)]
    if None in keys or any(k not in by for k in keys):
        return None
    return [by[k] for k in keys]


def profit_speeding(quarterly: list | None) -> tuple[bool | None, str | None]:
    """U1. quarterly: [[quarter_end, revenue_cr, profit_cr, ebitda_margin_pct], ...] oldest first (metrics `quarterly`).
    Each quarter against the same quarter a year earlier, by date; None when one of the 7 quarters is not filed."""
    q = _run(quarterly or [], 7)
    if q is None:
        return None, None
    p = [_yoy(q[-1 - i][2], q[-5 - i][2]) for i in range(3)]
    r0 = _yoy(q[-1][1], q[-5][1])
    if None in p or r0 is None:
        return None, None
    ok = p[0] > p[1] > p[2] and p[0] >= 15 and r0 >= 10
    return ok, f"profit YoY {p[2]:.0f}% → {p[1]:.0f}% → {p[0]:.0f}% · revenue YoY {r0:.0f}%"


def operating_leverage(quarterly: list | None) -> tuple[bool | None, str | None]:
    """U2. Last 4 quarters vs the 4 before: EBITDA growth >= revenue growth + 5 pts, revenue growth >= 10%, margin up.
    The 8 quarters must be consecutive (by date)."""
    q = _run(quarterly or [], 8)
    if q is None:
        return None, None
    now, then = q[-4:], q[-8:-4]
    if any(x[3] is None or x[1] is None for x in now + then):
        return None, None
    rn, rt = sum(x[1] for x in now), sum(x[1] for x in then)
    en, et = sum(x[1] * x[3] / 100 for x in now), sum(x[1] * x[3] / 100 for x in then)
    gr, ge = _yoy(rn, rt), _yoy(en, et)
    if gr is None or ge is None or rn <= 0:
        return None, None
    mn, mt = en / rn * 100, et / rt * 100
    ok = gr >= 10 and ge >= gr + 5 and mn > mt
    return ok, f"revenue {gr:+.0f}% · EBITDA {ge:+.0f}% · margin {mt:.1f}% → {mn:.1f}% (last 4 quarters vs 4 before)"


def rerating_setup(roce_fy: list | None, debt_chg_pct, net_debt_ebitda, cur, hist_vals: list, peer: dict | None
                   ) -> tuple[bool | None, str | None]:
    """U3. roce_fy: [[year, roce_pct], ...]; cur: the stock's primary multiple; hist_vals: that multiple at past quarters."""
    r = sorted(roce_fy or [])
    hv = [x for x in hist_vals or [] if x and x > 0]
    if len(r) < 2 or cur is None or cur <= 0 or len(hv) < 6 or not peer or peer.get("n", 0) < 5:
        return None, None
    roce_up = r[-1][1] > r[-2][1]
    debt_ok = (debt_chg_pct is None or debt_chg_pct <= 0) or (net_debt_ebitda is not None and net_debt_ebitda <= 0.5)
    own = sorted(hv)[len(hv) // 2]
    cheap_own, cheap_peer = cur < own, cur < peer["median"]
    ok = roce_up and debt_ok and cheap_own and cheap_peer
    return ok, (f"ROCE {r[-2][1]:.0f}% → {r[-1][1]:.0f}% · multiple {cur:.1f} vs own median {own:.1f}, peers {peer['median']:.1f}"
                + ("" if debt_ok else " · debt rising"))


def overhang_over(promoter_hist: list | None, pledge=None, pledge_1q=None) -> tuple[bool | None, str | None]:
    """U4. promoter_hist: [{"date", "promoter_pct"}, ...] oldest first; pledge in % of promoter shares (NSE XBRL)."""
    if pledge is not None and pledge_1q is not None and pledge == 0 and pledge_1q < 0:
        return True, f"promoter pledge cleared ({pledge_1q:+.1f} pts to 0%)"
    h = [x["promoter_pct"] for x in promoter_hist or [] if x.get("promoter_pct") is not None]
    if len(h) < 6 or h[-1] <= 0:
        return None, None
    fell, now = h[-2] - h[-6], h[-1] - h[-2]
    ok = fell <= -1 and now >= 0
    return ok, f"promoter {fell:+.1f} pts over the 4 quarters before, {now:+.1f} pts latest"


def checks(Mx_quarterly, roce_fy, debt_chg_pct, net_debt_ebitda, cur, hist_vals, peer, promoter_hist,
           pledge=None, pledge_1q=None) -> dict:
    """{id: (state, value)} for U1-U5."""
    u1, u2 = profit_speeding(Mx_quarterly), operating_leverage(Mx_quarterly)
    u3 = rerating_setup(roce_fy, debt_chg_pct, net_debt_ebitda, cur, hist_vals, peer)
    u4 = overhang_over(promoter_hist, pledge, pledge_1q)
    earn = True if (u1[0] or u2[0]) else (None if u1[0] is None and u2[0] is None else False)
    u5 = (None if earn is None or u3[0] is None else bool(earn and u3[0]), None)
    if u5[0]:
        u5 = (True, "earnings: " + (u1[1] if u1[0] else u2[1]) + " · multiple: " + u3[1])
    return {"U1": u1, "U2": u2, "U3": u3, "U4": u4, "U5": u5}


NAMES = {"U1": "Profit speeding up", "U2": "Operating leverage", "U3": "Re-rating setup", "U4": "Selling overhang over",
         "U5": "Both engines: earnings and multiple"}

# Tested as a ranking boost (adopted then removed 25 Nov 2026): in the replay matched to the live rules (code trigger as
# forward driver) +10 for U1 gave 51/59/61% vs 53/57/61% without it at 3/6/12 months. Kept for the replay variants.
U1_BOOST = 10
