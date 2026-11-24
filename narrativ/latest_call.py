"""Is the latest earnings call available? (owner, 24 Nov 2026: ideas 1 and 2 + the AlphaStreet fallback)

The latest call is the one for the latest results quarter (filed XBRL `last_quarter`, results filed on `filed`):
- an exchange transcript filed on or after the results date (less EARLY_DAYS: some calls come a few days before the
  results), not an AGM; a cover letter counts (the pack follows its link, or falls back to AlphaStreet);
- an AlphaStreet earnings call for the same fiscal quarter (Q1-Q4 of an April-March year), status FINAL; if the quarter
  labels do not match, one held on or after the results date (less EARLY_DAYS).

`since` = the first date the call was available from any source. A review written before `since` did not see the call
(funnel.verification: pending), and a Buy candidate whose results are newer than WAIT_DAYS without a call waits for it
(run.py queue: idea 2).
"""
import re
from datetime import date, timedelta

EARLY_DAYS = 5
WAIT_DAYS = 7
RESULTS_SOON_DAYS = 10   # results due within this: wait (a review now goes stale the day they are filed)
CALL_AFTER_DAYS = 3      # a scheduled call: wait until this many days after it (transcripts follow in 1-5 days)
RECENT_BRIEFS = 4        # AlphaBriefs of the last calls in a review pack (owner: the app shows the latest, Claude gets more)
_MON = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_D1 = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s,.-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[\s,.-]+(20\d\d)\b", re.I)
_D2 = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)
_D3 = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b")
INTIM = re.compile(r"analyst|institutional investor|investor meet|conference call|con\.? ?call|earnings call", re.I)
EARN = re.compile(r"earnings|financial results|results for|quarter|q[1-4]\b|h[12]\s*fy|half year", re.I)
NOT_SCHEDULE = re.compile(r"transcript|audio|recording|video|webcast link|presentation", re.I)
AGM = re.compile(r"\bAGM\b|annual general|postal ballot|e-?voting", re.I)


def fiscal_quarter(qe: str | None) -> tuple[str, int] | None:
    """Quarter-end date -> (Q1..Q4, fiscal year ending March): 2026-09-30 -> ('Q2', 2027)."""
    try:
        d = date.fromisoformat(str(qe)[:10])
    except ValueError:
        return None
    q = {6: "Q1", 9: "Q2", 12: "Q3", 3: "Q4"}.get(d.month)
    if not q:
        return None
    return q, d.year + (1 if d.month >= 4 else 0)


def label(qe: str | None) -> str | None:
    fq = fiscal_quarter(qe)
    return f"{fq[0]} FY{str(fq[1])[2:]}" if fq else None


def exchange_transcripts(sym: str, ann_st: dict, ex: dict) -> list[dict]:
    """Transcript filings (NSE announcements, then exchange filings), newest first: {date, url, title}."""
    from .packs import junk_filing
    out = []
    for d, cat, txt, url, *rest in (ann_st.get("rows") or {}).get(sym, []):
        rule = rest[1] if len(rest) > 1 else None
        t = str(txt or cat or "")
        if rule == "Transcript" and url and not AGM.search(t) and not junk_filing({"text": t, "url": url}):
            out.append({"date": str(d)[:10], "url": url, "title": t[:140]})
    for x in (ex.get(sym) or {}).get("filings") or []:
        t = f"{x.get('text') or ''} {x.get('category') or ''}"
        if x.get("url") and re.search(r"transcript", t, re.I) and not AGM.search(t) and not junk_filing(x):
            out.append({"date": str(x.get("date") or "")[:10], "url": x["url"], "title": str(x.get("text"))[:140]})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def latest_call(sym: str, last_quarter: str | None, filed: str | None, ann_st: dict, ex: dict, today: date,
                as_calls=None) -> dict | None:
    """-> {quarter, results_filed, state: found|missing, since, sources: [...]} or None without a filed quarter.
    as_calls: AlphaStreet's call list for the stock (alphastreet.calls), or None to look at the exchange only."""
    if not filed or not last_quarter:
        return None
    fq = fiscal_quarter(last_quarter)
    lo = str(date.fromisoformat(filed[:10]) - timedelta(days=EARLY_DAYS))
    srcs = [{"src": "exchange", "date": x["date"], "url": x["url"]}
            for x in exchange_transcripts(sym, ann_st, ex) if lo <= x["date"] <= str(today)][:1]
    for c in as_calls or []:
        if c.get("event_type") not in (None, "earnings_conference") or str(c.get("transcript_status") or "").upper() != "FINAL":
            continue
        d = str(c.get("event_utc_datetime") or "")[:10]
        same_q = fq and c.get("fiscal_period") == fq[0] and str(c.get("fiscal_year")) == str(fq[1])
        if (same_q or (lo <= d and not c.get("fiscal_period"))) and d <= str(today):
            from .alphastreet import transcript_url
            srcs.append({"src": "alphastreet", "date": d, "id": c["id"], "url": transcript_url(c["id"])})
            break
    r = {"quarter": label(last_quarter), "results_filed": filed[:10], "state": "found" if srcs else "missing", "sources": srcs,
         "recent": [{"id": c["id"], "call": f"{c.get('fiscal_period')} FY{str(c.get('fiscal_year'))[2:]}", "date": str(c.get("event_utc_datetime") or "")[:10]}
                    for c in (as_calls or []) if c.get("event_type") in (None, "earnings_conference")
                    and str(c.get("transcript_status") or "").upper() == "FINAL"][:RECENT_BRIEFS]}
    if srcs:
        r["since"] = min(s["date"] for s in srcs)
    return r


def dates_in(text: str) -> list[date]:
    out = []
    for d, m, y in _D1.findall(text or ""):
        out.append((int(y), _MON[m[:3].lower()], int(d)))
    for m, d, y in _D2.findall(text or ""):
        out.append((int(y), _MON[m[:3].lower()], int(d)))
    for d, m, y in _D3.findall(text or ""):
        out.append((int(y), int(m), int(d)))
    res = []
    for y, m, d in out:
        try:
            res.append(date(y, m, d))
        except ValueError:
            pass
    return res


def scheduled_call(sym: str, ann_st: dict, today: date, text_of) -> dict | None:
    """The next earnings call the company announced (NSE 'analyst / investor meet' intimation, date read from its subject or
    PDF via text_of(url) -> str | None), on or after today - CALL_AFTER_DAYS. -> {date, url, filed} or None."""
    lo = str(today - timedelta(days=30))
    for d, cat, txt, url, *_ in (ann_st.get("rows") or {}).get(sym, []):
        s = f"{cat} {txt}"
        if str(d) < lo or not url or not INTIM.search(s) or NOT_SCHEDULE.search(s):
            continue
        body = f"{s} {text_of(url) or ''}"
        if not EARN.search(body):  # a broker conference, not the company's earnings call
            continue
        f = date.fromisoformat(str(d)[:10])
        ds = sorted(x for x in dates_in(body) if f <= x <= f + timedelta(days=40) and x >= today - timedelta(days=CALL_AFTER_DAYS))
        if ds:
            return {"date": str(ds[0]), "url": url, "filed": str(f)}
    return None


def waiting(call: dict | None, today: date, results_due: str | None = None, call_date: str | None = None) -> str | None:
    """Idea 2 (owner, 24 Nov 2026): why a Buy candidate's review should wait, or None.
    - results due within RESULTS_SOON_DAYS: a review now would go stale the day they are filed;
    - the company announced its call: wait until CALL_AFTER_DAYS after it;
    - results filed within WAIT_DAYS and no call found yet."""
    if results_due and str(today) < results_due <= str(today + timedelta(days=RESULTS_SOON_DAYS)) \
            and not (call and call.get("results_filed", "") >= results_due):
        return f"Results due {results_due}: reviewed after the results and the call"
    if call_date and (not call or call.get("state") == "missing") and str(today) <= str(date.fromisoformat(call_date) + timedelta(days=CALL_AFTER_DAYS)):
        return f"Earnings call scheduled {call_date}: reviewed once its transcript is out"
    if call and call.get("state") == "missing" and (today - date.fromisoformat(call["results_filed"])).days <= WAIT_DAYS:
        return (f"Waiting for the {call['quarter']} earnings call transcript (results filed {call['results_filed']}); "
                f"reviewed once it is out, or after {WAIT_DAYS} days without it")
    return None


def summary(call: dict | None) -> str:
    if not call:
        return "No filed quarter to match a call to"
    if call["state"] == "missing":
        return f"Latest call ({call['quarter']}) not found: results filed {call['results_filed']}, no transcript from the exchange, the company or AlphaStreet yet"
    s = call["sources"]
    return f"Latest call ({call['quarter']}) found: " + ", ".join(f"{x['src']} ({x['date']})" for x in s)
