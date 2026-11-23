"""NSE shareholding pattern (Batch 2): quarterly filing list + the XBRL behind each filing, one store for all NSE stocks.
- list : api/corporate-share-holdings-master?index=equities&symbol=X  (promoter / public %, XBRL link per quarter)
- XBRL : nsearchives .../corporate/xbrl/SHP_*.xml  (category holdings, holder counts, promoter pledge)
Feeds D5 D6 D9 (Discovery), F5 (Momentum), B5 (Stability), C4 (Management) and the promoter history.
BSE-only stocks are not covered. Store: data/source_cache/shp.json (Actions cache) + R2 nse/shp.json.gz."""
import json
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

from .filings import NSESession, same_doc

STORE = Path("data/source_cache/shp.json")
MASTER = "https://www.nseindia.com/api/corporate-share-holdings-master"
X = "{http://www.xbrl.org/2003/instance}"
KEEP_Q = 5            # parsed quarters kept per stock (latest + 4 back = 1Q and 4Q changes)
LIST_EVERY = 30       # days between per-stock filing-list checks (safety net; new filings come from the market-wide list)
RETRY_EVERY = 7       # days between retries of a filing that failed to parse
MKT_BACK = 10         # days of the market-wide list re-read each run (covers missed runs; first run: 120)
SRC = "NSE shareholding pattern (XBRL)"
PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
CNT = "NumberOfShareholders"
PLEDGE = "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares"
ENCUMB = "EncumberedSharesHeldAsPercentageOfTotalNumberOfShares"
PROM = "ShareholdingOfPromoterAndPromoterGroupMember"


def _qdate(s: str) -> str | None:
    try:
        return datetime.strptime(str(s).strip().title(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _f(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def parse(xml: str) -> dict:
    """One filing -> holdings (% of shares), holder counts and promoter pledge (% of promoter shares)."""
    root = ET.fromstring(xml.encode())
    ctx = {c.get("id"): "/".join(m.text.split(":")[-1] for m in c.iter() if m.tag.endswith("explicitMember")) or "-"
           for c in root.iter(X + "context")}
    facts: dict = {}
    flags = {}
    for el in root:
        ref = el.get("contextRef")
        if not ref:
            continue
        tag, mem = el.tag.split("}")[-1], ctx.get(ref, "-")
        if mem == "-":
            if tag.startswith("WhetherAnySharesHeldByPromotersAreEncumbered"):
                flags[tag] = (el.text or "").strip().lower() == "true"
            continue
        facts.setdefault(tag, {}).setdefault(mem, el.text)  # first value per member (category totals)

    def pct(m, tag=PCT):
        v = _f((facts.get(tag) or {}).get(m))
        return None if v is None else round(v * 100, 2)

    def cnt(m):
        v = _f((facts.get(CNT) or {}).get(m))
        return None if v is None else int(v)

    pledged = flags.get("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged")
    pl = pct(PROM, PLEDGE)
    en = pct(PROM, ENCUMB)
    dii, fii = pct("InstitutionsDomesticMember"), pct("InstitutionsForeignMember")
    return {"promoter": pct(PROM), "public": pct("PublicShareholdingMember"),
            "mf": pct("MutualFundsOrUTIMember") or 0.0, "mf_n": cnt("MutualFundsOrUTIMember") or 0,
            "ins": pct("InsuranceCompaniesMember") or 0.0, "dii": dii or 0.0, "fii": fii or 0.0,
            "inst": round((dii or 0) + (fii or 0), 2),
            "retail_n": cnt("ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember"),
            "holders": cnt("ShareholdingPatternMember"),
            "pledge": pl if pl is not None else (0.0 if pledged is False else None),
            "encumbered": en if en is not None else (0.0 if pledged is False else None)}


def _load() -> dict:
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def refresh(symbols: list[str], today: date, max_minutes: float = 10) -> dict:
    """New and revised filings come from NSE's market-wide list (one request); per-stock lists only for stocks never
    loaded and every LIST_EVERY days as a safety net. Parses the latest KEEP_Q filings not parsed yet, within the budget."""
    st = _load()
    t0, lists, parsed, errs = time.time(), 0, 0, 0
    bad: dict[str, list] = {}
    try:
        ns = NSESession()
    except Exception as e:  # noqa: BLE001
        print(f"[shp] session failed: {e}")
        return st
    meta = st.pop("_meta", {})
    nse_set = {x for x in symbols if x.endswith(".NS")}
    fresh = _market_wide(ns, st, nse_set, today, meta)
    order = sorted(fresh) + [x for x in symbols if x.endswith(".NS") and x not in fresh]  # new filers first
    for s in order:
        if time.time() - t0 > max_minutes * 60:
            break
        rec = st.setdefault(s, {"q": {}})
        chk = rec.get("checked")
        if not chk or (s not in fresh and (today - date.fromisoformat(chk)).days >= LIST_EVERY):
            j = ns.get(MASTER, params={"index": "equities", "symbol": s[:-3]})
            lists += 1
            if isinstance(j, list):
                m = [{"date": _qdate(r.get("date")), "promoter_pct": _f(r.get("pr_and_prgrp")), "public_pct": _f(r.get("public_val")),
                      "xbrl": r.get("xbrl"), "revised": r.get("revisedData") == "Y"} for r in j]
                m = {x["date"]: x for x in (rec.get("master") or []) + [x for x in m if x["date"]]}  # list wins over older entries
                rec["master"] = sorted(m.values(), key=lambda x: x["date"])[-21:]
                rec["checked"] = today.isoformat()
            else:
                errs += 1
                bad.setdefault("list", []).append(s)
                continue
        want = [x for x in (rec.get("master") or [])[-KEEP_Q:] if x.get("xbrl")]
        for x in want:
            old = rec["q"].get(x["date"])
            if old and not ("error" in old and (today - date.fromisoformat(old.get("tried") or "2000-01-01")).days >= RETRY_EVERY) \
                    and same_doc((rec.get("qx") or {}).get(x["date"], x["xbrl"]), x["xbrl"]):
                continue  # parsed, or a parse error retried weekly
            if time.time() - t0 > max_minutes * 60:
                continue
            t = ns.get(x["xbrl"], as_json=False)
            if not t:
                errs += 1
                bad.setdefault("xbrl", []).append(s)
                continue
            try:
                rec["q"][x["date"]] = parse(t)
                rec.setdefault("qx", {})[x["date"]] = x["xbrl"]  # a revised filing has a new link: re-parsed
                parsed += 1
            except Exception as e:  # noqa: BLE001
                errs += 1
                bad.setdefault("parse", []).append(s)
                rec["q"][x["date"]] = {"error": str(e)[:80], "tried": today.isoformat()}
        keep = {x["date"] for x in want}
        rec["q"] = {k: v for k, v in rec["q"].items() if k in keep}
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps({**st, "_meta": meta}, separators=(",", ":")))
    nse = [x for x in symbols if x.endswith(".NS")]
    state = {"complete": 0, "no filings at NSE": 0, "list not fetched yet": 0, "some quarters unread": 0}
    for x in nse:
        r = st.get(x) or {}
        m = r.get("master")
        ok = [d for d, v in (r.get("q") or {}).items() if "error" not in v]
        if m is None:
            state["list not fetched yet"] += 1
        elif not m or not any(y.get("xbrl") for y in m):
            state["no filings at NSE"] += 1
        elif len(ok) >= min(KEEP_Q, sum(1 for y in m[-KEEP_Q:] if y.get("xbrl"))):
            state["complete"] += 1
        else:
            state["some quarters unread"] += 1
    print(f"[shp] {lists} filing lists, {parsed} filings parsed{f", {errs} errors" if errs else ""} in {time.time() - t0:.0f}s; {state} of {len(nse)} NSE stocks"
          + "".join(f"; {k} failed: {', '.join(v[:8])}" for k, v in bad.items()))
    return st


def _market_wide(ns, st: dict, nse_set: set, today: date, meta: dict) -> set:
    """Filings (new or revised) by all companies since the last run, from NSE's market-wide shareholding list.
    Merges them into each stock's filing list; returns the symbols with something new to parse."""
    since = date.fromisoformat(meta["asof"]) - timedelta(days=MKT_BACK) if meta.get("asof") else today - timedelta(days=120)
    j = ns.get(MASTER, params={"index": "equities", "from_date": f"{since:%d-%m-%Y}", "to_date": f"{today:%d-%m-%Y}"})
    if not isinstance(j, list):
        print("[shp] market-wide list failed; per-stock lists only")
        return set()
    fresh = set()
    for r in j:
        s = f"{(r.get('symbol') or '').strip()}.NS"
        d, x = _qdate(r.get("date")), r.get("xbrl")
        if s not in nse_set or not d or not x:
            continue
        rec = st.setdefault(s, {"q": {}})
        m = {y["date"]: y for y in rec.get("master") or []}
        if same_doc((m.get(d) or {}).get("xbrl"), x) and d in rec["q"]:
            continue
        if d in rec["q"] and (m.get(d) or {}).get("xbrl") and not same_doc((m.get(d) or {}).get("xbrl"), x):
            rec["q"].pop(d, None)  # revised filing (new link): parse it again
        m[d] = {"date": d, "promoter_pct": _f(r.get("pr_and_prgrp")), "public_pct": _f(r.get("public_val")), "xbrl": x,
                "revised": r.get("revisedData") == "Y"}
        rec["master"] = sorted(m.values(), key=lambda y: y["date"])[-21:]
        fresh.add(s)
    meta["asof"] = today.isoformat()
    print(f"[shp] market-wide list: {len(j)} filings since {since}, {len(fresh)} stocks with new or revised filings")
    return fresh


def promoter_hist(st: dict, sym: str, n: int = 8) -> list[dict]:
    return [{"date": x["date"], "promoter_pct": x["promoter_pct"], "public_pct": x.get("public_pct")}
            for x in ((st.get(sym) or {}).get("master") or []) if x.get("promoter_pct") is not None][-n:]


def stats(st: dict, sym: str) -> dict | None:
    """Latest quarter and changes; None when no filing has been parsed yet."""
    q = (st.get(sym) or {}).get("q") or {}
    ds = sorted(d for d, v in q.items() if "error" not in v)
    if not ds:
        return None
    cur = q[ds[-1]]
    prev = q[ds[-2]] if len(ds) >= 2 else None
    yago = q[ds[-5]] if len(ds) >= 5 else None
    out = {"asof": ds[-1], "n": len(ds), **cur}

    def chg(k, base):
        return None if base is None or cur.get(k) is None or base.get(k) is None else round(cur[k] - base[k], 2)
    out.update({"inst_1q": chg("inst", prev), "inst_4q": chg("inst", yago), "mf_n_1q": chg("mf_n", prev), "mf_1q": chg("mf", prev),
                "pledge_1q": chg("pledge", prev)})
    # consecutive quarters (latest backwards) in which institutional holding fell: RULES.md R5
    down = 0
    for a, b in zip(reversed(ds[:-1]), reversed(ds[1:])):
        x, y = q[a].get("inst"), q[b].get("inst")
        if x is None or y is None or y >= x:
            break
        down += 1
    out["inst_down_q"] = down
    if yago and cur.get("retail_n") and yago.get("retail_n"):
        out["retail_yoy_pct"] = round((cur["retail_n"] / yago["retail_n"] - 1) * 100, 1)
    return out
