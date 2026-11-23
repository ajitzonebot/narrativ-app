"""Top 10 as a portfolio (RULES.md P1-P3): verified Buys in readiness order, at most 2 per industry, 3 per sector and
6 small caps (market cap under ₹5,000 crore). Fewer than 10 verified Buys: the list stays short (no filler)."""
BUY = ("Buy", "Strong Buy")
MAX_IND, MAX_SEC, MAX_SMALL, SMALL_CR = 2, 3, 6, 5000


def top10(rows: list[dict]) -> list[str]:
    """rows: picks.json rows (s, dc, vf, rk, i, sec, mc). -> symbols in order."""
    cand = sorted([r for r in rows if r.get("dc") in BUY and r.get("vf") == "pass"], key=lambda r: r.get("rk") or 10 ** 9)
    out, ind, sec, small = [], {}, {}, 0
    for r in cand:
        # no industry: its sector stands in, then the stock itself (unclassified stocks shared one "?" bucket and capped
        # each other); missing market cap still counts as small (conservative)
        s_ = r.get("sec") or f"stock:{r['s']}"
        i = r.get("i") or (f"sector:{r['sec']}" if r.get("sec") else f"stock:{r['s']}")
        is_small = (r.get("mc") or 0) < SMALL_CR
        if ind.get(i, 0) >= MAX_IND or sec.get(s_, 0) >= MAX_SEC or (is_small and small >= MAX_SMALL):
            continue
        out.append(r["s"])
        ind[i] = ind.get(i, 0) + 1
        sec[s_] = sec.get(s_, 0) + 1
        small += is_small
        if len(out) == 10:
            break
    return out


def multibagger(mcap_cr, disc_t, rev_yoy, accel, roce, has_trigger, val_t) -> bool:
    """RULES.md MB: small enough to multiply, undiscovered, growing fast, good returns on capital, a dated trigger, cheap."""
    return bool(mcap_cr and mcap_cr < 10000 and disc_t in (1, 2) and ((rev_yoy or 0) >= 20 or accel) and (roce or 0) >= 15
                and has_trigger and val_t in (1, 2))
