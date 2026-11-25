"""Conviction (RULES.md "Conviction"): how much verified, countable evidence stands behind a verified Buy.

Rule-built from inputs the pipeline already verified; no AI-typed score. It never makes or unmakes a Buy: it is computed
only for stocks whose decision is already a verified Buy / Strong Buy, and only says how strong the evidence is.

Seven checks, each met or not, each with a one-line reason (like the Buy gates):
  C1 Two or more independent dated triggers in 18 months: verified drivers / promises with a verified due date, counted
     once per source document, plus each live price or results signal on the Outlook tab (T4 does not count, as R4)
  C2 Clean independent review: audit pass, at least 3 checks of its own, all matching the filing, debt incl. leases (the
     check tagged "rule": "debt_leases", or named so; lenders exempt), no issue and no data issue logged
  C3 Entry setup live: breakout, pullback or base, price not extended
  C4 Story intact and no open integrity item (Claude's quoted story check)
  C5 Institutions adding: institutional holding up (D5) or mutual funds entering (T15 / D6), not falling, no selling run
  C6 Complete data: 3 full years of results, cash conversion known (lenders exempt), 8+ quarters, no open data issue
  C7 Second read agrees: a free reader found one of Claude's dated statements in the same words (narrativ/reader.py)
Level: High = 6 or 7 met, including C1 and C3 (the two the history replay shows raise the win rate among candidates);
Low = 3 or fewer met; Medium otherwise.
Tested and left out (narrativ/replay.py `conviction`): valuation Deep value / Undervalued lowered the win rate inside the
margin-of-safety gate; price in stage 2 and strong momentum did not help inside the Top 10.
"""
import re
from datetime import date, timedelta

RULE = "conviction v1.1 (2026-11-25)"  # v1.1: C2 accepts the R7 "debt_leases" tag; C1 promise dates verified as drivers
BUY = ("Buy", "Strong Buy")
HORIZON_DAYS = 548  # 18 months, as RULES.md R4
LENDERS = ("bank", "nbfc", "insurance")
LIVE_SETUPS = ("Breakout", "Pullback", "Base")
CORE = ("C1", "C3")
HIGH, LOW = 6, 3
NAMES = {
    "C1": "Two independent dated triggers (18 months)",
    "C2": "Clean independent review",
    "C3": "Entry setup live",
    "C4": "Story intact, no open integrity item",
    "C5": "Institutions adding",
    "C6": "Complete data",
    "C7": "Second read agrees",
}
_DEBT = re.compile(r"debt|borrow|lease", re.I)
_HOST = re.compile(r"^https?://[^/]+")


def _d(x) -> date | None:
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _val(Mx: dict, k: str):
    m = (Mx or {}).get(k)
    if isinstance(m, dict):
        return None if m.get("nm") else m.get("v")
    return m


def _doc(url: str | None) -> str:
    """Same document whatever the host spelling (nsearchives.nseindia.com / .in, http / https)."""
    return _HOST.sub("", str(url or "")).strip().lower()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def dated_evidence(th: dict, L: dict, today: date) -> list[dict]:
    """Independent dated reasons for the price to move within 18 months: one per source document (verified drivers and
    promises whose due date the verifier confirmed), one per live signal on the Outlook tab (T4 excluded, as R4)."""
    end = today + timedelta(days=HORIZON_DAYS)
    docs: dict[str, dict] = {}
    rows = [(d.get("kind") or "driver", d.get("due"), d.get("source")) for d in th.get("drivers") or [] if d.get("due_verified")]
    rows += [(p.get("kind") or "promise", p.get("due"), p.get("source"))
             for p in th.get("promises") or [] if p.get("due_verified") and p.get("status") in ("pending", "raised")]
    for kind, due, url in rows:
        dd = _d(due)
        if not dd or not (today <= dd <= end) or not url:
            continue
        k = _doc(url)
        if k not in docs or str(due) < docs[k]["due"]:
            docs[k] = {"kind": kind, "due": str(due)[:10], "source": url}
    out = sorted(docs.values(), key=lambda x: x["due"])
    for t in (L.get("out") or {}).get("triggers") or []:
        if t.get("id") and t.get("id") != "T4":
            out.append({"kind": "signal", "id": t["id"], "text": t.get("n")})
    return out


def _c1(th, L, today):
    ev = dated_evidence(th, L, today)
    if not ev:
        return False, "no dated trigger in 18 months"
    parts = [f"{x['id']} {x.get('text') or ''}".strip() if x["kind"] == "signal" else f"{x['kind']} due {x['due']}" for x in ev[:4]]
    return len(ev) >= 2, f"{len(ev)} independent: " + "; ".join(parts) + ("" if len(ev) >= 2 else " (one source only)")


def _c2(th, lender):
    au = th.get("audit") or {}
    if au.get("verdict") != "pass":
        return False, f"audit {au.get('verdict') or 'missing'}"
    ch = au.get("checks") or []
    bad = [c.get("item") for c in ch if not c.get("ok")]
    if bad:
        return False, f"{len(bad)} check(s) did not match the filing: {', '.join(str(b) for b in bad[:2])}"
    if len(ch) < 3:
        return False, f"only {len(ch)} check(s) of its own (needs 3)"
    # the R7 debt check is tagged `"rule": "debt_leases"` (funnel._debt_checked accepts it whatever the item says); until
    # 25 Nov 2026 C2 read only the item text, so a tagged check named e.g. "Total financial obligations" did not count
    if not lender and not any(c.get("rule") == "debt_leases" or _DEBT.search(str(c.get("item") or "")) for c in ch):
        return False, "debt including leases not among the checks"
    if au.get("issues"):
        return False, f"{len(au['issues'])} issue(s) logged: {(au['issues'][0] or {}).get('kind', '')}"
    if au.get("data_issues") or th.get("data_issues"):
        return False, "a data issue was logged"
    return True, f"pass on {au.get('date')}: {len(ch)} checks, all match the filing, no issues"


def _c3(L, setup):
    ty = (setup or {}).get("type") or "No setup"
    if (L.get("mom") or {}).get("extended"):
        return False, f"{ty}, but the price is extended"
    return ty in LIVE_SETUPS, ty if ty in LIVE_SETUPS else f"{ty}: wait for a breakout, pullback or base"


def _c4(th, dec):
    st = th.get("story") or {}
    integ = [x for x in dec.get("integrity") or [] if x.get("status") == "open"]
    if integ:
        return False, f"{len(integ)} integrity item(s) open"
    if st.get("status") != "intact":
        return False, f"story {st.get('status') or 'not checked yet'}"
    return True, f"intact ({st.get('date') or 'undated'}): {st.get('text') or ''}".strip(": ")


def _c5(L, shp):
    items = {i.get("id"): i for i in (L.get("disc") or {}).get("items") or []}
    d5, d6 = (items.get("D5") or {}).get("m"), (items.get("D6") or {}).get("m")
    t15 = any(t.get("id") == "T15" for t in (L.get("out") or {}).get("triggers") or [])
    down = (shp or {}).get("inst_down_q") or 0
    if down >= 2:
        return False, f"institutions sold {down} quarters in a row"
    if d5 == 0:
        return False, f"institutional holding falling ({(items.get('D5') or {}).get('v')})"
    if d5 is None and d6 is None and not t15:
        return False, "no shareholding data yet"
    if d5 == 2 or d6 == 2 or t15:
        why = "mutual funds entering (T15)" if t15 else (items.get("D5") or {}).get("v") if d5 == 2 else (items.get("D6") or {}).get("v")
        return True, str(why)
    return False, "institutions flat: " + " · ".join(str((items.get(k) or {}).get("v")) for k in ("D5", "D6") if (items.get(k) or {}).get("v"))


def _c6(Mx, lender, open_issues):
    miss = []
    if _val(Mx, "rev_cagr_3y_pct") is None or _val(Mx, "pat_cagr_3y_pct") is None:
        miss.append("3 full years of results")
    if not lender and _val(Mx, "cfo_to_ebitda_pct") is None:
        miss.append("cash conversion")
    if ((Mx or {}).get("quarters_available") or 0) < 8:
        miss.append("8 quarters of filings")
    if open_issues:
        miss.append(f"{open_issues} open data issue(s)")
    return not miss, "3 full years, cash conversion, 8+ quarters, no open data issue" if not miss else "missing: " + ", ".join(miss)


def _c7(th, reader):
    if not reader or not reader.get("items"):
        return False, "not read by the free reader yet"
    rq = [_norm(i.get("quote")) for i in reader["items"] if i.get("due")]
    rq = [r for r in rq if len(r) >= 20]
    ours = [x for x in (th.get("drivers") or []) + (th.get("promises") or []) if x.get("due") and x.get("quote")]
    hit = [x for x in ours if len(_norm(x["quote"])) >= 20 and any(r in _norm(x["quote"]) or _norm(x["quote"]) in r for r in rq)]
    if not hit:
        return False, f"reader found {len(rq)} dated row(s), none in the same words as Narrativ.ai's"
    return True, f"{len(hit)} of Narrativ.ai's dated statements also found by the reader ({reader.get('model') or 'free model'})"


def assess(dec: dict, L: dict, setup: dict | None, th: dict | None, Mx: dict | None, today: date, *,
           shp: dict | None = None, open_issues: int = 0, reader: dict | None = None, lender: bool | None = None) -> dict | None:
    """Conviction of one verified Buy / Strong Buy; None for any other decision (conviction never makes a Buy)."""
    if (dec or {}).get("d") not in BUY or dec.get("verified") != "pass":
        return None
    th = th or {}
    lender = ((Mx or {}).get("kind") in LENDERS) if lender is None else lender
    res = {"C1": _c1(th, L, today), "C2": _c2(th, lender), "C3": _c3(L, setup), "C4": _c4(th, dec),
           "C5": _c5(L, shp), "C6": _c6(Mx, lender, open_issues), "C7": _c7(th, reader)}
    met = [k for k, (ok, _) in res.items() if ok]
    core_ok = all(k in met for k in CORE)
    level = "High" if len(met) >= HIGH and core_ok else "Low" if len(met) <= LOW else "Medium"
    why = f"{len(met)} of {len(res)} checks met"
    if len(met) >= HIGH and not core_ok:
        why += f"; not High without {', '.join(NAMES[k].lower() for k in CORE if k not in met)}"
    return {"level": level, "met": len(met), "of": len(res), "why": why, "rule": RULE, "date": str(today),
            "checks": [{"id": k, "n": NAMES[k], "ok": ok, "v": v} for k, (ok, v) in res.items()]}
