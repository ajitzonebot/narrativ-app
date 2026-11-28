"""Why an industry is leading, tested (owner, 28 Nov 2026: "how to understand why a sector or industry is leading, like the
legit reason ... build this into the industry reasons").

A lead is legitimate when a real, dated change raises the expected profits of most companies in the industry. Four tests,
answered from data (code) and from Claude's quoted reasons (checked by code):

  cause     a real dated event, not the price move or a broker tip, from a source the run opened: the quote must be in the
            source text (verify.fetch_text, or the copy the run saved with `python3 -m narrativ.industrywhy check`)
  broad     most members are rising: at least BROAD_PCT% above their 200-day average
  numbers   it shows in results: more of its members grew revenue (or profit) over 10% last quarter than in the whole
            market, by at least NUMBERS_EDGE points (10% growth is close to the market norm, so an absolute bar passes
            almost every industry); without the market figures, at least NUMBERS_PCT% of members
  before    the cause came before the move: a reason dated no later than GRACE_DAYS after the industry's 6-month low

4 of 4: "Earnings-led". 2 or 3: "Partly explained". 0 or 1: "Flow or narrative". Prices up without the numbers test is
noted as "prices ahead of earnings" (a re-rating or flows: fragile). `lasting` says whether the counted causes are
structural (multi-year) or one-time.

Reason (docs/data/industry_why.json, written by the catalyst run, tasks/catalyst.md 8b):
  {"date": event date, "type": one of TYPES, "text": what happened, "mechanism": how it reaches revenue or costs,
   "quote": verbatim from the source, "url", "source", "lasting": "structural" | "one_time"}
The url must be in the industry's pack (headline, policy release, filing) or a primary source (government, RBI, SEBI,
NSE, BSE) dated within a year, so the real cause of a move older than the pack's 30 days can be cited.
"""
import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

TYPES = ("policy", "rates", "demand", "prices", "supply", "orders", "global", "flow")
LASTING = ("structural", "one_time")
BROAD_PCT, NUMBERS_PCT, NUMBERS_EDGE, GRACE_DAYS, MAX_AGE_DAYS = 50, 50, 5, 10, 365
SAVED = Path("data/industry_sources")  # page text the run fetched (code, not typed): first line records the url
HEAD = "<!-- source: {} -->\n"
PRIMARY = re.compile(r"^https://([a-z0-9-]+\.)*(rbi\.org\.in|pib\.gov\.in|sebi\.gov\.in|nseindia\.com|nseindia\.in|bseindia\.com|"
                     r"gov\.in|nic\.in)/", re.I)
# the move itself is not a reason ("surges 7% on huge volume", "hits record high")
PRICE_MOVE = re.compile(r"\b(surg|soar|rall(y|ies|ied)|jump|zoom|climb|spurt|skyrocket|tank|plung|slump)\w*\b.{0,50}"
                        r"(\d+(\.\d+)?\s*(%|per\s*cent)|record high|52-week|all-time high|\bvolume)|\btop (gainers?|losers?)\b|"
                        r"\b(record|all-time|52-week) high\b|\bstocks? (in focus|to watch)\b", re.I)
# a broker's view is not an event ("stocks to buy", "names 3 shares", "target price")
TIP = re.compile(r"\bstocks? to buy\b|\btop picks?\b|\btarget price\b|\bstock ideas?\b|\brecommend|\bnames? \d+ (shares|stocks)\b|"
                 r"\btrading guide\b|\btechnical picks?\b|\bbuy or sell\b|\bmultibagger\b|\bbrokerages? (see|bet|bullish)\b", re.I)
LABEL = {4: "Earnings-led", 3: "Partly explained", 2: "Partly explained", 1: "Flow or narrative", 0: "Flow or narrative"}


def _key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def saved_text(url: str) -> str | None:
    f = SAVED / f"{_key(url)}.txt"
    if not f.exists():
        return None
    first, _, rest = f.read_text().partition("\n")
    return rest if first == HEAD.format(url).strip() else None


def source_text(url: str) -> str | None:
    """Text a quote is checked against: the verifier's fetch (cache, docling, other NSE host), else the run's saved copy."""
    from .verify import fetch_text
    try:
        t = fetch_text(url)
    except Exception:  # noqa: BLE001
        t = None
    return t or saved_text(url)


def _day(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def check_reason(r: dict, ok_urls: set, titles: dict, today: date, move_start: str | None, text_of=source_text) -> tuple[dict | None, str | None]:
    """-> (the reason with code labels, None) or (None, why it was dropped)."""
    from .verify import long_enough, quoted_in
    t, url, q = r.get("type"), str(r.get("url") or ""), str(r.get("quote") or "")
    if t not in TYPES:
        return None, f"type must be one of {', '.join(TYPES)}"
    if not str(r.get("text") or "").strip():
        return None, "no text"
    if t != "flow" and not str(r.get("mechanism") or "").strip():
        return None, "no mechanism (how it reaches revenue or costs)"
    d = _day(r.get("date"))
    if not d or d > today or (today - d).days > MAX_AGE_DAYS:
        return None, "date missing, in the future or older than a year"
    if url not in ok_urls and not PRIMARY.match(url):
        return None, "url not in the industry's pack and not a primary source (government, RBI, SEBI, NSE, BSE)"
    said = " ".join((str(r.get("text") or ""), q, titles.get(url, "")))
    if PRICE_MOVE.search(said):
        return None, "the price move is not a reason"
    if TIP.search(said):
        return None, "a broker's tip is not an event"
    if not long_enough(q):
        return None, "no quote from the source"
    src = text_of(url)
    if src is not None and not quoted_in(q, src):
        return None, "quote not in the source"
    ms = _day(move_start)
    out = {k: r.get(k) for k in ("date", "type", "text", "mechanism", "quote", "url", "source")}
    out["lasting"] = r.get("lasting") if r.get("lasting") in LASTING else None
    out["checked"] = src is not None  # False: the source could not be read here, so it does not count as the cause
    out["timing"] = None if not ms else "before" if d <= ms + timedelta(days=GRACE_DAYS) else "after"
    return out, None


def _pct(a, b) -> int | None:
    return round(100 * a / b) if a is not None and b else None


def verdict(facts: dict, kept: list[dict]) -> dict:
    """The four tests, the label, and notes."""
    cause = [r for r in kept if r["type"] != "flow" and r["checked"]]
    breadth = _pct(facts.get("above_200_day"), facts.get("members"))
    rev = _pct(facts.get("rev_growth_over_10pct"), facts.get("rev_reported"))
    pat = _pct(facts.get("profit_growth_over_10pct"), facts.get("profit_reported"))
    mrev, mpat = facts.get("market_revenue_growth_pct"), facts.get("market_profit_growth_pct")

    def beats(x, m):
        return x is not None and (x >= m + NUMBERS_EDGE if m is not None else x >= NUMBERS_PCT)
    tests = {"cause": bool(cause), "broad": breadth is not None and breadth >= BROAD_PCT,
             "numbers": beats(rev, mrev) or beats(pat, mpat), "before": any(r["timing"] == "before" for r in cause)}
    n = sum(tests.values())
    notes = []
    if not tests["numbers"] and (facts.get("median_ret_3m") or 0) > 0:
        notes.append("prices ahead of earnings: a re-rating or flows, which reverse faster")
    if not tests["broad"] and breadth is not None:
        notes.append(f"narrow: {breadth}% of members above their 200-day average, so a few stocks drive it")
    if cause and not tests["before"] and any(r["timing"] == "after" for r in cause):
        notes.append("every cause found came after the move began: it may explain the move afterwards rather than start it")
    if any(r["type"] == "flow" for r in kept):
        notes.append("part of the move is flows (index changes, fund buying), not earnings")
    lasting = "structural" if any(r.get("lasting") == "structural" for r in cause) else "one_time" if cause else None
    return {"tests": tests, "score": n, "verdict": LABEL[n], "lasting": lasting, "notes": notes,
            "numbers": {"breadth_pct": breadth, "revenue_growth_pct": rev, "profit_growth_pct": pat,
                        "market_revenue_growth_pct": mrev, "market_profit_growth_pct": mpat,
                        "median_ret_3m": facts.get("median_ret_3m"), "move_start": facts.get("move_start"),
                        "from_low_pct": facts.get("from_low_pct")}}


def judge(name: str, w: dict, pk: dict, policy: list, today: date, text_of=source_text) -> dict:
    """One industry: reasons checked, dropped ones with why, and the verdict."""
    facts = pk.get("facts") or {}
    heads = pk.get("headlines") or []
    ok_urls = {p["url"] for p in policy} | {h["url"] for h in heads} | set(facts.get("urls") or [])
    titles = {h["url"]: h.get("title") or "" for h in heads} | {p["url"]: p.get("title") or "" for p in policy}
    kept, dropped = [], []
    for r in w.get("reasons") or []:
        k, why = check_reason(r, ok_urls, titles, today, facts.get("move_start"), text_of)
        if k:
            kept.append(k)
        else:
            dropped.append({"text": str(r.get("text") or "")[:160], "url": r.get("url"), "why": why})
    kept.sort(key=lambda r: (r["checked"], r["timing"] == "before", r["date"] or ""), reverse=True)
    kept = kept[:3]
    return {"date": w.get("date"), "quadrant": w.get("quadrant") or pk.get("quadrant"), "reasons": kept,
            "none_found": bool(w.get("none_found")) and not kept, "dropped": len(dropped), "dropped_why": dropped,
            **verdict(facts, kept)}


def save(urls: list[str]) -> list[tuple[str, bool, str]]:
    """The run's check: fetch each url here (code, not typed) and keep its text for the daily run's quote check."""
    from .verify import _fetch_text
    SAVED.mkdir(parents=True, exist_ok=True)
    out = []
    for u in urls:
        try:
            t = _fetch_text(u)
        except Exception as e:  # noqa: BLE001
            t, err = None, str(e)[:100]
        else:
            err = "" if t else "no text"
        if t:
            (SAVED / f"{_key(u)}.txt").write_text(HEAD.format(u) + t)
        out.append((u, bool(t), err))
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Industry reasons: save sources and check them as the daily run will")
    ap.add_argument("cmd", choices=("check",))
    ap.add_argument("--industry", action="append", help="only these industries (default: all in industry_why.json)")
    a = ap.parse_args(argv)
    why = json.loads(Path("docs/data/industry_why.json").read_text()).get("industries") or {}
    packs = json.loads(Path("docs/data/industry_packs.json").read_text())
    today = date.today()
    for name, w in why.items():
        if a.industry and name not in a.industry:
            continue
        for u, ok, err in save([r.get("url") for r in w.get("reasons") or [] if r.get("url")]):
            if not ok:
                print(f"[industrywhy] {name}: could not read {u} ({err}); the reason will not count as the cause")
        j = judge(name, w, (packs.get("industries") or {}).get(name) or {}, packs.get("policy") or [], today)
        print(json.dumps({"industry": name, "verdict": j["verdict"], "tests": j["tests"], "notes": j["notes"],
                          "kept": [(r["type"], r["timing"], r["checked"]) for r in j["reasons"]], "dropped": j["dropped_why"]},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
