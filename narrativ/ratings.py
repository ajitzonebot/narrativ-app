"""Credit-rating actions from NSE's system-driven disclosure (owner, 24 Nov 2026).

Since 2 Aug 2025 every SEBI-registered rating agency (CRISIL, ICRA, CARE, India Ratings, Acuite, Infomerics, ...)
uploads its rating actions to NSE by ISIN (circular NSE/CML/2025/33). NSE publishes them with the symbol, instrument,
rating, outlook and the action (New / Re-affirm / Upgrade / Downgrade / Other) and a link to the agency's rationale:
https://www.nseindia.com/api/credit-rating-sdd-reg30. One full load (30-day windows back to FIRST), then the last
DAILY_DAYS every day, merged; the store lives in the Actions cache (a lost cache reloads in ~16 calls).

Per stock (dossier "ratings"): the latest action per agency and instrument kind in 12 months, upgrades and downgrades,
negative outlooks or watches. A downgrade in 12 months fails A5 (the same check, now from the agencies' own filings).
"""
import gzip
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

API = "https://www.nseindia.com/api/credit-rating-sdd-reg30"
STORE = Path("data/source_cache/ratings_sdd.json.gz")
FIRST = date(2025, 8, 1)
DAILY_DAYS = 7
KEEP = ("creditAgencyName", "symbol", "isin", "classOfAction", "ratingAssigned", "typeOfRating", "creditRating", "outlook",
        "dateOfCurrentCredit", "amount", "currentAction", "detailsOfRatingLink", "broadcastDateTime")
NEG = ("negative", "watch with negative", "watch negative", "credit watch negative")


def _d(s) -> str | None:
    for f in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s).strip(), f).date().isoformat()
        except ValueError:
            continue
    return None


def _key(r: dict) -> str:
    return "|".join(str(r.get(k) or "") for k in ("isin", "creditAgencyName", "ratingAssigned", "typeOfRating", "dateOfCurrentCredit", "amount", "creditRating"))


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(gzip.decompress(STORE.read_bytes()))
        except Exception as e:  # noqa: BLE001
            print(f"[ratings] store unreadable, reloading: {e}")
    return {"rows": {}, "loaded_to": None}


def _fetch(ns, a: date, b: date) -> list[dict] | None:
    out = []
    for idx in ("equities", "sme"):
        try:
            j = ns.get(API, params={"index": idx, "from_date": a.strftime("%d-%m-%Y"), "to_date": b.strftime("%d-%m-%Y")})
        except Exception as e:  # noqa: BLE001
            print(f"[ratings] {idx} {a}..{b}: {str(e)[:120]}")
            return None
        out += j if isinstance(j, list) else (j or {}).get("data") or []
        time.sleep(0.5)
    return out


def refresh(today: date, max_minutes: float = 6) -> dict:
    """Full load once (oldest window last), then the last DAILY_DAYS. -> store {rows: {key: row}, loaded_to}"""
    from .filings import NSESession
    st, ns, t0 = _load(), NSESession(), time.time()
    windows = [(max(today - timedelta(days=DAILY_DAYS), FIRST), today)]
    lo = date.fromisoformat(st["loaded_to"]) if st.get("loaded_to") else today - timedelta(days=DAILY_DAYS)
    while lo > FIRST and len(windows) < 40:
        a = max(lo - timedelta(days=30), FIRST)
        windows.append((a, lo))
        lo = a
    n_new, reached = 0, st.get("loaded_to")
    for a, b in windows:
        if time.time() - t0 > max_minutes * 60:
            break
        rows = _fetch(ns, a, b)
        if rows is None:
            break
        for r in rows:
            k = _key(r)
            if k not in st["rows"]:
                n_new += 1
            st["rows"][k] = {f: r.get(f) for f in KEEP}
        if (a, b) != windows[0]:
            reached = str(a)
    st["loaded_to"] = reached or str(windows[0][0])
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(gzip.compress(json.dumps(st, separators=(",", ":"), ensure_ascii=False).encode()))
    print(f"[ratings] {len(st['rows'])} actions stored ({n_new} new), loaded back to {st['loaded_to']}, {time.time() - t0:.0f}s")
    return st


def per_stock(st: dict, today: date, months: int = 12) -> dict[str, dict]:
    """{SYMBOL.NS: {actions: [...latest per agency + instrument kind, newest first], upgrades, downgrades, negative, latest}}"""
    since = str(today - timedelta(days=31 * months))
    by: dict[str, list] = {}
    for r in st.get("rows", {}).values():
        d = _d(r.get("dateOfCurrentCredit")) or _d(r.get("broadcastDateTime"))
        if not d or d < since or not r.get("symbol"):
            continue
        by.setdefault(f"{r['symbol']}.NS", []).append({**r, "d": d})
    out = {}
    for s, rows in by.items():
        rows.sort(key=lambda x: x["d"], reverse=True)
        latest, seen = [], set()
        for r in rows:
            k = (r.get("creditAgencyName"), r.get("typeOfRating"), r.get("ratingAssigned"))
            if k in seen:
                continue
            seen.add(k)
            latest.append({"date": r["d"], "agency": str(r.get("creditAgencyName") or "").replace(" Limited", "").replace(" Private", ""),
                           "instrument": r.get("ratingAssigned"), "term": r.get("typeOfRating"), "rating": r.get("creditRating"),
                           "outlook": r.get("outlook"), "action": r.get("currentAction"), "url": r.get("detailsOfRatingLink")})
        act = lambda a: sum(1 for r in rows if str(r.get("currentAction") or "").lower() == a)  # noqa: E731
        neg = [x for x in latest if any(w in f"{x.get('outlook') or ''} {x.get('rating') or ''}".lower() for w in NEG)]
        down = next((r for r in rows if str(r.get("currentAction") or "").lower() == "downgrade"), None)
        out[s] = {"actions": latest[:8], "upgrades": act("upgrade"), "downgrades": act("downgrade"), "negative": len(neg),
                  "latest": latest[0]["date"] if latest else None,
                  "downgrade": {"date": down["d"], "agency": down.get("creditAgencyName"), "rating": down.get("creditRating"),
                                "url": down.get("detailsOfRatingLink")} if down else None,
                  "source": "NSE system-driven credit rating disclosures (agencies' own uploads)"}
    return out


def a5(summary: dict | None):
    """A5 from the agencies' filings: (mark, value, source, url) or None when the stock has no rating action in 12 months."""
    if not summary:
        return None
    dn = summary.get("downgrade")
    if dn:
        return (1, f"{dn['date']}: downgraded to {dn['rating']} by {dn['agency']}", "NSE credit rating disclosure (agency upload)", dn.get("url"))
    return (2, f"no downgrade in 12 months ({summary['upgrades']} upgrade(s), {len(summary['actions'])} rating(s) current)",
            "NSE credit rating disclosures (agency uploads)", None)
