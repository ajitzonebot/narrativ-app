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
  C7 Quotes double-checked: a separate AI read of the same filing (narrativ/reader.py, before Claude) found one of
     Claude's dated statements in the same words
Level (v2, owner 26 Nov 2026, feedback #175): the proof score `score()` sets it, not the count of checks: management
targets with dates (up to 35), signals (up to 25), Narrativ.ai checks C2 + C7 (up to 20), entry setup C3 (10),
institutions C5 (10); High 70+, Medium 45-69, Low below 45; an open integrity item (C4) or incomplete data (C6) keeps it
at Medium at most. The checks are still stored for app versions before 2.32.
Tested and left out (narrativ/replay.py `conviction`): valuation Deep value / Undervalued lowered the win rate inside the
margin-of-safety gate; price in stage 2 and strong momentum did not help inside the Top 10.
"""
import re
from datetime import date, timedelta

BUY = ("Buy", "Strong Buy")
HORIZON_DAYS = 548  # 18 months, as RULES.md R4
LENDERS = ("bank", "nbfc", "insurance")
LIVE_SETUPS = ("Breakout", "Pullback", "Base")
NAMES = {
    "C1": "Two independent dated triggers (18 months)",
    "C2": "Clean independent review",
    "C3": "Entry setup live",
    "C4": "Story intact, no open integrity item",
    "C5": "Institutions adding",
    "C6": "Complete data",
    "C7": "Quotes double-checked",
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
    if not reader:
        return False, "not checked yet"
    if not reader.get("items"):  # read, but nothing dated found (owner, 26 Nov 2026: "not read yet" was wrong here)
        doc = " ".join(x for x in (reader.get("kind"), f"of {reader['date']}" if reader.get("date") else None) if x) or "a document"
        return False, f"nothing dated found in the {doc} to check against"
    rq = [_norm(i.get("quote")) for i in reader["items"] if i.get("due")]
    rq = [r for r in rq if len(r) >= 20]
    ours = [x for x in (th.get("drivers") or []) + (th.get("promises") or []) if x.get("due") and x.get("quote")]
    hit = [x for x in ours if len(_norm(x["quote"])) >= 20 and any(r in _norm(x["quote"]) or _norm(x["quote"]) in r for r in rq)]
    if not hit:
        return False, f"{len(rq)} dated statement(s) found, none in the same words as Narrativ.ai's"
    return True, f"{len(hit)} of Narrativ.ai's dated statements matched word for word"


# ---------------------------------------------------------------- proof score (owner, 26 Nov 2026, feedback #175)
# Conviction is driven by proofs: each proof adds points, the total (0-100) sets the level. Weights approved by the owner.
SCORE_RULE = "conviction score v3 (2026-11-27)"
# v3 (owner, 27 Nov 2026, forward ledger stage 4): a verified target counts by its size (material 15, small 5, size not
# known 10; +5 raised / beat / delivered; cap 35), scaled by size-weighted credibility once 2+ targets resolved (x0.5 at none
# delivered .. x1.0 at all); the ledger's signals of the last 90 days: material good +5 each (max 10, "Targets delivering"),
# material bad or a red filing caps the level at Medium, small bad -5 each (max -10)
T_MATERIAL, T_SMALL, T_UNKNOWN = 15, 5, 10
GOOD_MAX, BAD_SMALL, BAD_MAX = 10, 5, 10
HIGH_AT, MEDIUM_AT = 70, 45
SIZE = {"High": "full", "Medium": "half", "Low": "quarter"}  # option C: every verified Buy stays a Buy, sized by conviction
TARGET_YEARS = 5  # a management target counts when its verified due date is within 5 years
_YEAR = re.compile(r"^(19|20)\d\d$")
_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _target_key(text: str, due) -> tuple:
    """The same target said twice (a driver and a promise) counts once: its due date plus its largest non-year number."""
    ns = [float(x.replace(",", "")) for x in _NUM.findall(str(text or "")) if not _YEAR.match(x.replace(",", ""))]
    return str(due)[:10], max(ns) if ns else _norm(text)[:30]


# words that say nothing about which target it is (time, currency, filler); dates are compared separately
_STOP = set("""the a an of to and in on for by at be is are was with than from as this that its it our we will would should
    next last current previous financial year yearly years fy end before after about around expected expect targeted target
    targets aims aim plan plans likely by till until crore crores cr inr rs lakh million billion january february march april
    may june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec quarter""".split())
_TOK = re.compile(r"[a-z]+|\d[\d,]*\.?\d*")
SAME_DAYS = 92  # one target dated at the period end and again at its results date (MPSLTD 31 Mar / 31 May 2027)


def _words(text: str) -> set:
    """Content words cut to 5 letters (commissioning / commissioned, complete / completed), numbers without commas; years and
    FY tags dropped."""
    out = set()
    txt = re.sub(r"\bfy\s?'?\d{2,4}\b|'\d\d\b|\b(?:cy|h[12])\s?\d{2,4}\b", " ", str(text or "").lower().replace("₹", " "))
    for t in _TOK.findall(txt):
        t = t.replace(",", "")
        if t in _STOP:
            continue
        if t[0].isdigit():
            if _YEAR.match(t.split(".")[0]):
                continue
            out.add(t)
        elif len(t) > 1:
            out.add(t[:5])
    return out


def _same_target(a: dict, b: dict) -> bool:
    """The same management target quoted twice in different words or with a different due date (owner, 27 Nov 2026: SARDAEN's
    coal mine, CAPLIPOINT's COL-II plant, MPSLTD's FY27 EBITDA, ASAHISONG's Q3, SOMANYCERA's growth guidance were each counted
    twice): due dates within SAME_DAYS, most of the shorter statement's words in the longer one, no conflicting figure."""
    da, db = _d(a["due"]), _d(b["due"])
    if not da or not db or abs((da - db).days) > SAME_DAYS:
        return False
    wa, wb = _words(a["text"]), _words(b["text"])
    na, nb = {w for w in wa if w[0].isdigit()}, {w for w in wb if w[0].isdigit()}
    if na and nb and not (na & nb):  # both give figures and none agree: two targets (50 MW vs 100 MW)
        return False
    small = min(len(wa), len(wb))
    return small >= 3 and len(wa & wb) / small >= 0.6


def management_targets(th: dict, today: date, sym: str | None = None) -> list[dict]:
    """Quoted management targets / guidance whose due date the verifier confirmed, due within TARGET_YEARS. With `sym`, each
    carries its forward-ledger id (ledger.item_id), so conviction can read its size and signals."""
    end = today + timedelta(days=365 * TARGET_YEARS)
    out, seen = [], set()
    rows = [(d.get("text"), d.get("due"), None, ("claude", [d.get("text"), d.get("due")])) for d in th.get("drivers") or []
            if d.get("due_verified")]
    rows += [(p.get("promise"), p.get("due"), p.get("status"), ("promise", [p.get("id") or p.get("promise")])) for p in th.get("promises") or []
             if p.get("due_verified") and p.get("status") in ("pending", "raised", "beat", "delivered")]  # RESEARCH.md promise statuses
    if sym:
        from .ledger import item_id
    for text, due, status, key in rows:
        dd = _d(due)
        if not dd or not (today <= dd <= end) or not text:
            continue
        k = _target_key(text, due)
        if k in seen:
            continue
        seen.add(k)
        row = {"text": str(text).rstrip("."), "due": str(due)[:10], "better": status in ("raised", "beat", "delivered"),
               "id": item_id(sym, *key) if sym else None}
        twin = next((x for x in out if _same_target(x, row)), None)
        if twin:
            twin["better"] = twin["better"] or row["better"]  # a raised / delivered restatement keeps its bonus
            continue
        out.append(row)
    return out


_PCT = re.compile(r"([+-]?\d+(?:\.\d+)?)%")


def _signal_strong(t: dict) -> bool:
    """T11: price ≥ +5% vs Nifty after results with profit up ≥ 20%; T12: estimates up ≥ 10%; others: the Outlook flag."""
    v = str(t.get("v") or "")
    nums = [float(x) for x in _PCT.findall(v)]
    if t.get("id") == "T11" and len(nums) >= 2:
        return nums[0] >= 5 and nums[-1] >= 20
    if t.get("id") == "T12" and nums:
        return nums[0] >= 10
    return bool(t.get("strong"))


def _short_date(x: str) -> str:
    d = _d(x)
    return f"{d:%b %Y}" if d else str(x)


def score(dec: dict, L: dict, setup: dict | None, th: dict, Mx: dict | None, today: date, *, shp=None, open_issues=0,
          reader=None, lender=False, checks: dict | None = None, sym: str | None = None, led: dict | None = None) -> dict:
    """Proofs with points, what is missing (one statement each), total score, level and position size. `led`: the forward
    ledger's view of the stock (monitor.context), read when `sym` is given and `led` is not."""
    proofs, not_yet = [], []
    if led is None and sym:
        try:
            from .monitor import context
            led = context(sym, today)
        except Exception:  # noqa: BLE001  no ledger yet: v2 points
            led = None
    items = (led or {}).get("items") or {}
    tg = management_targets(th, today, sym)
    if tg:
        def tpts(t):
            m = (items.get(t.get("id")) or {}).get("material") if items else None
            return (T_MATERIAL if m == 1 else T_SMALL if m == 0 else T_UNKNOWN) + (5 if t["better"] else 0)
        pts = min(35, sum(tpts(t) for t in tg))
        cred = (led or {}).get("cred")
        if cred:
            pts = round(pts * (0.5 + cred["pct"] / 200))
        lab = lambda t: {1: " · material", 0: " · small"}.get((items.get(t.get("id")) or {}).get("material"), "")  # noqa: E731
        proofs.append({"k": "management", "pts": pts, "t": "Management targets with dates" + (f" (delivered {cred['pct']}% of {cred['n']})" if cred else ""),
                       "v": " · ".join(f"{t['text']} (due {_short_date(t['due'])}{lab(t)})" for t in tg[:3])})
    elif (th or {}).get("no_concall"):
        not_yet.append("No call this quarter: no management target on record")
    else:
        not_yet.append("No dated management target on record")
    sig = [t for t in (L.get("out") or {}).get("triggers") or [] if t.get("id") and t.get("id") != "T4"]
    for t in sig:
        st = _signal_strong(t)
        proofs.append({"k": "signal", "pts": 12 if st else 8, "t": ("Strong " + t["n"][0].lower() + t["n"][1:]) if st else t["n"],
                       "v": t.get("v")})
    sig_pts = sum(x["pts"] for x in proofs if x["k"] == "signal")
    if sig_pts > 25:  # cap the signals at 25, trimming the last ones
        over = sig_pts - 25
        for x in reversed([x for x in proofs if x["k"] == "signal"]):
            cut = min(over, x["pts"]); x["pts"] -= cut; over -= cut
        proofs = [x for x in proofs if x["pts"] > 0]
    if not sig:
        not_yet.append("No price or earnings signal live")
    c = checks or {}
    ok2, v2 = c.get("C2") or _c2(th, lender)
    ok7, v7 = c.get("C7") or _c7(th, reader)
    if ok2:
        au = th.get("audit") or {}
        n = len(au.get("checks") or [])
        proofs.append({"k": "checks", "pts": 15 + (5 if ok7 else 0), "t": "Narrativ.ai checks pass",
                       "v": f"{n} of {n} checks match the filing" + (f" · {v7}" if ok7 else "")})
    else:
        not_yet.append(f"Narrativ.ai checks: {v2}")
    ok3, v3 = c.get("C3") or _c3(L, setup)
    if ok3:
        proofs.append({"k": "setup", "pts": 10, "t": f"Entry setup: {str(v3).lower()}", "v": None})
    else:
        not_yet.append("Price extended: wait for a pullback" if "extended" in str(v3) else "No entry setup yet: wait for a breakout, pullback or base")
    ok5, v5 = c.get("C5") or _c5(L, shp)
    if ok5:
        proofs.append({"k": "institutions", "pts": 10, "t": "Institutions adding", "v": v5})
    else:
        not_yet.append(f"Institutions not adding: {v5}" if "no shareholding" not in str(v5) else "No shareholding data yet")
    caps, minus = [], 0
    sig = (led or {}).get("signals") or []
    good = [x for x in sig if x.get("dir") == "good" and x.get("material") == 1]
    if good:
        proofs.append({"k": "delivering", "pts": min(GOOD_MAX, 5 * len(good)), "t": "Targets delivering",
                       "v": " · ".join(f"{x['status']}: {str(x.get('text') or '')[:70]}" for x in good[:3])})
    for x in sig:
        if x.get("dir") != "bad":
            continue
        what = f"{x['status']}: {str((x.get('detail') or {}).get('filing') or x.get('text') or '')[:70]}"
        if x.get("material") == 1 or x.get("status") == "red filing":
            caps.append(f"forward target {what}")
        else:
            minus += BAD_SMALL
            not_yet.append(f"Target {what}")
    total = max(0, min(100, sum(x["pts"] for x in proofs) - min(BAD_MAX, minus)))
    level = "High" if total >= HIGH_AT else "Medium" if total >= MEDIUM_AT else "Low"
    ok4, v4 = c.get("C4") or _c4(th, dec)
    integrity_open = not ok4 and "integrity item" in str(v4)  # C4's passing text can mention integrity (review 26 Nov 2026)
    if integrity_open:
        caps.append(str(v4))
    ok6, v6 = c.get("C6") or _c6(Mx, lender, open_issues)
    if not ok6:
        caps.append(f"data incomplete ({str(v6).replace('missing: ', '')})")
    if level == "High" and caps:
        level = "Medium"
    if not ok4 and not integrity_open:
        not_yet.append(f"Story {str(v4).replace('story ', '')}" if str(v4).startswith("story") else str(v4))
    return {"score": total, "level": level, "size": SIZE[level], "proofs": proofs, "not_yet": not_yet,
            "capped": caps or None, "score_rule": SCORE_RULE}


def assess(dec: dict, L: dict, setup: dict | None, th: dict | None, Mx: dict | None, today: date, *,
           shp: dict | None = None, open_issues: int = 0, reader: dict | None = None, lender: bool | None = None,
           sym: str | None = None, led: dict | None = None) -> dict | None:
    """Conviction of one verified Buy / Strong Buy; None for any other decision (conviction never makes a Buy)."""
    if (dec or {}).get("d") not in BUY or dec.get("verified") != "pass":
        return None
    th = th or {}
    lender = ((Mx or {}).get("kind") in LENDERS) if lender is None else lender
    res = {"C1": _c1(th, L, today), "C2": _c2(th, lender), "C3": _c3(L, setup), "C4": _c4(th, dec),
           "C5": _c5(L, shp), "C6": _c6(Mx, lender, open_issues), "C7": _c7(th, reader)}
    met = [k for k, (ok, _) in res.items() if ok]
    sc = score(dec, L, setup, th, Mx, today, shp=shp, open_issues=open_issues, reader=reader, lender=lender, checks=res, sym=sym, led=led)
    # the level is the proof score's (owner, 26 Nov 2026); met / of and the checks stay for app versions before 2.32
    why = f"{sc['score']} of 100 from proofs" + (f"; capped at Medium: {', '.join(sc['capped'])}" if sc["capped"] and sc["score"] >= HIGH_AT else "")
    return {"level": sc["level"], "score": sc["score"], "size": sc["size"], "proofs": sc["proofs"], "not_yet": sc["not_yet"],
            "met": len(met), "of": len(res), "why": why, "rule": SCORE_RULE, "date": str(today),
            "checks": [{"id": k, "n": NAMES[k], "ok": ok, "v": v} for k, (ok, v) in res.items()]}
