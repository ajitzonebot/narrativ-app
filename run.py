"""Daily funnel v2 (PLAN.md): sweep (all NSE+BSE) -> filings + prices -> 7 levels -> verdict -> Claude queue -> app data."""
import argparse
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from narrativ import alerts, analyst, announcements as ANN, dbsync, config, exchange, filings, fundamentals as F, funnel as FN, memory as M, metrics as MX, mood, prices, rotation, sweep, technicals, verify
from narrativ import requests as scan_requests
from narrativ import events as EV
from narrativ import nsedaily as NSED
from narrativ import shp as SHP
from narrativ import corpfil as CF
from narrativ import health as H
from narrativ.util import prune, write_if_changed

OUT = Path("docs/data")
IST = timezone(timedelta(hours=5, minutes=30))


def num(x, nd=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def hidden_value(f: dict) -> list[str]:
    """Hidden-value metrics in the green (computed). Research-based ones (order book / revenue, guided P/E) are added from theses."""
    out = []
    if f.get("pe") and f.get("ind_pe") and f["pe"] < 0.7 * f["ind_pe"]:
        out.append(f"P/E {f['pe']} vs industry {f['ind_pe']}")
    if (f.get("net_cash_pct_mcap") or 0) >= 20:
        out.append(f"Net cash {f['net_cash_pct_mcap']}% of market cap")
    if (f.get("cfo_to_ebitda_pct") or 0) >= 80:
        out.append(f"Cash conversion {f['cfo_to_ebitda_pct']:.0f}%")
    if (f.get("fcf_yield_pct") or 0) >= 5:
        out.append(f"FCF yield {f['fcf_yield_pct']}%")
    if f.get("peg") and 0 < f["peg"] <= 1:
        out.append(f"PEG {f['peg']}")
    if (f.get("cwip_pct_ppe") or 0) >= 20:
        out.append(f"Capital work in progress {f['cwip_pct_ppe']}% of fixed assets")
    return out


FUND_KEYS = {  # app key -> metrics key (all computed by narrativ.metrics from filed numbers)
    "mcap_cr": "mcap_cr", "pe": "pe", "pb": "pb", "ev_ebitda": "ev_ebitda", "peg": "peg", "roe_pct": "roe_pct",
    "roce_pct": "roce_pct", "de": "de", "ebitda_margin_pct": "ebitda_margin_pct", "opm_pct": "ebitda_margin_q_pct",
    "rev_yoy_pct": "rev_yoy_pct", "pat_yoy_pct": "pat_yoy_pct", "rev_ttm_growth_pct": "rev_ttm_growth_pct",
    "pat_ttm_growth_pct": "pat_ttm_growth_pct", "eps_cagr_3y_pct": "eps_cagr_3y_pct", "cfo_to_ebitda_pct": "cfo_to_ebitda_pct",
    "oi_pct_pbt": "other_income_pct_pbt", "receivable_days": "receivable_days", "inventory_days": "inventory_days",
    "cwip_pct_ppe": "cwip_pct_ppe", "net_cash_pct_mcap": "net_cash_pct_mcap", "fcf_yield_pct": "fcf_yield_pct",
    "capex_pct_rev": "capex_pct_rev", "interest_cover": "interest_cover", "free_float_mcap_cr": "free_float_mcap_cr",
    "revenue_ttm_cr": "revenue_ttm_cr", "pat_ttm_cr": "pat_ttm_cr", "gnpa_pct": "gnpa_pct_advances",
}


def fund_view(Mx: dict, f: dict, ind_pe: float | None, capex_note: str | None, prom: tuple) -> dict:
    """Compact values for lists. None = not computable -> the app shows a dash. Formulas live in docs/data/fin/<sym>.json."""
    out = {k: MX.val(Mx, mk) for k, mk in FUND_KEYS.items()}
    out["nm"] = [k for k, mk in FUND_KEYS.items() if isinstance(Mx.get(mk), dict) and Mx[mk].get("nm")]
    out["ind_pe"] = num(ind_pe, 1)
    out["src"] = Mx.get("source")
    out["basis"] = Mx.get("basis")
    out["kind"] = Mx.get("kind")
    out["last_quarter"] = Mx.get("last_quarter")
    out["flags"] = Mx.get("flags") or []
    out["promoter_pct"], out["promoter_chg"] = prom
    # third-party / descriptive (labelled in the app): Yahoo analyst count and institutional holding
    out["analysts"] = f.get("numberOfAnalystOpinions")
    out["inst_pct"] = num(f["heldPercentInstitutions"] * 100, 1) if f.get("heldPercentInstitutions") is not None else None
    out["capex"] = capex_note
    out["website"] = f.get("website")
    out["summary"] = f.get("longBusinessSummary")
    return out


def scan_view(th: dict, f: dict, price: float, band: dict | None, credibility: dict | None) -> dict | None:
    """Turns verified scan inputs into what the app shows. Label, legs, arc and scenario prices are rules on
    verified marks and computed numbers; nothing here is typed by a model."""
    raw = th.get("scan_raw")
    if not raw:
        return None
    cl = raw.get("checklist") or {}

    def share(lens):
        ms = [m["mark"] for m in cl.get(lens, []) if m["mark"] != "u"]
        return None if not ms else (sum(1 for m in ms if m == "y") + 0.5 * sum(1 for m in ms if m == "p")) / len(ms)
    F, V, Mg, O, Fl = (share(k) for k in ("fundamentals", "valuation", "management", "outlook", "flow"))
    live = sum(1 for m in cl.get("outlook", []) if m["mark"] == "y")
    red = any(m["mark"] == "n" and m["id"] in ("F10", "F10a", "M4", "M2a") for lens in cl.values() for m in lens)
    if red:
        label = "Red-flag / avoid"
    elif (F or 0) >= 0.6 and (V or 0) >= 0.5 and live >= 2:
        label = "Prime candidate"
    elif (F or 0) >= 0.6 and V is not None and V < 0.5:
        label = "Quality-but-priced"
    elif live >= 2:
        label = "Story / early"
    elif V is not None and V >= 0.5:
        label = "Value-trap risk"
    else:
        label = "Unproven"

    def leg(x):
        return "off" if x is None else "on" if x >= 0.6 else "half" if x >= 0.3 else "off"
    fund_leg = None if F is None and Mg is None else ((F or 0) + (Mg if Mg is not None else (F or 0))) / 2
    inst, an = f.get("inst_pct"), f.get("analysts") or 0
    arc = None if inst is None else "Early" if inst < 10 and an <= 2 else "Confirming" if inst < 25 or an <= 6 else "Late"
    out = {"date": raw.get("date"), "label": label, "legs": {"fundamentals": leg(fund_leg), "narrative": leg(O), "flow": leg(Fl)},
           "arc": arc, "checklist": cl, "levers": raw.get("levers") or [], "must_go_right": raw.get("must_go_right") or [],
           "kill_switches": raw.get("kill_switches") or [], "scenarios": [], "derived": []}
    mcap, pe = f.get("mcap_cr"), f.get("pe")
    ob, g = raw.get("order_book"), raw.get("guidance")
    if ob and f.get("revenue_ttm_cr"):
        r = ob["value_cr"] / f["revenue_ttm_cr"]
        out["derived"].append({"name": "Order book / revenue", "value": f"{r:.2f}x",
                               "formula": f"₹{ob['value_cr']:,} cr order book ÷ ₹{f['revenue_ttm_cr']:,.0f} cr revenue (4 quarters)",
                               "src": "Order book: quoted filing · revenue: NSE filings", "good": r >= 2.5})
    if g and g.get("metric") == "pat" and mcap and g.get("low"):
        gpe = mcap / g["low"]
        out["derived"].append({"name": f"P/E on guided {g.get('fy', '')} profit", "value": f"{gpe:.1f}x",
                               "formula": f"₹{mcap:,.0f} cr market cap ÷ ₹{g['low']:,} cr guided profit (low end)" + (f" · today's P/E {pe}" if pe else ""),
                               "src": "Guidance: quoted transcript · market cap: computed", "good": bool(pe and gpe < 0.7 * pe)})
        if credibility and credibility.get("pct") is not None:
            adj = g["low"] * credibility["pct"] / 100
            out["derived"].append({"name": "Credibility-adjusted profit", "value": f"₹{adj:,.0f} cr",
                                   "formula": f"₹{g['low']:,} cr guide × {credibility['pct']}% promise delivery rate", "src": "Promises tab"})
        if price and pe and f.get("pat_ttm_cr"):
            th_t = raw.get("theories") or {}
            hi_pe = band["high"] if band else None
            lo_pe = band["low"] if band else None
            per_cr = price / mcap  # rupees of price per ₹ cr of market cap
            band_src = f"own P/E range {band['from'][:7]} to {band['to'][:7]} ({band['n']} quarters)" if band else ""
            cases = []
            if hi_pe and g.get("high"):
                cases.append(("Bull", g["high"] * hi_pe, f"₹{g['high']:,} cr profit (top of guide) × {hi_pe} P/E (own high)", band_src))
            cases.append(("Base", g["low"] * pe, f"₹{g['low']:,} cr profit (bottom of guide) × {pe} P/E (today)", "Guidance quote · P/E computed"))
            if lo_pe:
                cases.append(("Bear", f["pat_ttm_cr"] * lo_pe, f"₹{f['pat_ttm_cr']:,.0f} cr profit (last 4 quarters, no growth) × {lo_pe} P/E (own low)", band_src))
            for name, mc, formula, src in cases:
                px_ = mc * per_cr
                out["scenarios"].append({"name": name, "price": round(px_), "pct": round((px_ / price - 1) * 100, 1),
                                         "theory": th_t.get(name.lower(), ""), "formula": formula, "src": src})
            out["settles"] = g.get("settles")
    return out


def code_of(ysym: str) -> tuple[str, str]:
    base, _, suf = ysym.rpartition(".")
    return base, "NSE" if suf == "NS" else "BSE"


def scan_state(sym: str, th: dict, today: date, queued: set, checkpoints: list) -> dict:
    """Scan button state (PLAN.md section 6)."""
    sc = (th.get("scan") or {}).get("date") or ((th.get("scan_raw") or {}).get("date"))
    nxt = [c["due"] for c in checkpoints if c.get("status") in ("open", "due") and c.get("due")]
    if sym in queued:
        return {"state": "queued"}
    if sc:
        age = (today - date.fromisoformat(sc[:10])).days
        refresh = min([str(date.fromisoformat(sc[:10]) + timedelta(days=config.THESIS_STALE_DAYS))] + nxt)
        if age < 7:
            return {"state": "recent", "date": sc[:10], "reopen": str(date.fromisoformat(sc[:10]) + timedelta(days=7)), "next": refresh}
        return {"state": "stale" if age > config.THESIS_STALE_DAYS else "scanned", "date": sc[:10], "next": refresh}
    if th:
        return {"state": "promises", "date": th.get("updated")}
    return {"state": "never"}


def standouts(L: dict) -> dict:
    good, watch = [], []
    for k in ("qual", "surv", "mgmt", "val", "mom", "out"):
        for i in L[k]["items"]:
            if i["m"] == 2 and i.get("v") and len(good) < 3 and i["id"] not in ("A1", "D4", "Q6", "P1"):
                good.append({"lv": k, "n": FN.FACT.get(i["id"], i["n"]).capitalize(), "v": i["v"], "k": i.get("k")})
    for mark in (0, 1):
        for k in ("surv", "qual", "mgmt", "val", "mom"):
            for i in L[k]["items"]:
                if i["m"] == mark and i.get("v") and len(watch) < 2:
                    watch.append({"lv": k, "n": FN.FACT.get(i["id"], i["n"]).capitalize(), "v": i["v"], "k": i.get("k")})
    return {"good": good, "watch": watch}


def main(limit: int | None) -> None:
    H.start()
    # limit (testing) also skips slow network refreshes
    if limit:
        config.FUND_MAX_PER_RUN = config.FILINGS_MAX_PER_RUN = 0
    today = datetime.now(IST).date()
    raw_theses = json.loads((OUT / "theses.json").read_text()) if (OUT / "theses.json").exists() else {}
    theses, vreport = verify.verify_all(raw_theses)  # only source-verified items survive
    (OUT / "verification.json").write_text(json.dumps(vreport, indent=1, ensure_ascii=False))

    if not limit:
        try:
            dbsync.restore_caches()
        except Exception as e:  # noqa: BLE001
            print(f"[store] restore failed: {e}")

    # ---------- Universe: all NSE+BSE >= Rs 200 cr (old exclusion rules are now tags) ----------
    df, stats = sweep.sweep()
    H.mark("universe")
    # BSE codes from the exchange list; research filed under an old .BO symbol follows the company to its current symbol
    codes_path = Path("data/bse_codes.json")
    bse_codes = json.loads(codes_path.read_text()) if codes_path.exists() else {}
    from narrativ import universe as U
    alias = U.aliases(df[["symbol", "bse_code"]].to_dict("records"), bse_codes)
    bse_codes.update({r.symbol: str(r.bse_code) for r in df.itertuples() if r.symbol.endswith(".BO") and r.bse_code})
    codes_path.write_text(json.dumps(bse_codes, indent=0, sort_keys=True))
    moved = {o: n for o, n in alias.items() if o in raw_theses}
    if moved:
        print(f"[run] research moved to current symbols: {moved}")
        raw_theses = {moved.get(k, k): v for k, v in raw_theses.items()}
        (OUT / "theses.json").write_text(json.dumps(raw_theses, indent=1, ensure_ascii=False))
        theses, vreport = verify.verify_all(raw_theses)
    mem_moved = {o: n for o, n in alias.items() if M.load(o)}
    if mem_moved:
        M.rename(mem_moved)
        print(f"[run] memory moved to current symbols for {len(mem_moved)} stocks")
    # re-audit trigger: research the review judged (drivers, scan, story, integrity) that changed after it -> verification pending
    stamps_path = OUT / "audit_stamps.json"
    stamps = json.loads(stamps_path.read_text()) if stamps_path.exists() else {}
    stamps = {moved.get(k, k): x for k, x in stamps.items()}
    changed_after = FN.stamp_audits(raw_theses, stamps, today)
    FN.mark_changed(theses, changed_after)
    stamps_path.write_text(json.dumps(stamps, indent=0, sort_keys=True))
    print(f"[run] research changed after its audit: {changed_after or 'none'}")
    s0 = df.copy()
    if limit:  # testing: prefer companies whose filings are already cached
        cached = {p.stem for p in Path("data/financials").glob("*.json")}
        s0 = pd.concat([s0[s0["symbol"].isin(cached)], s0[~s0["symbol"].isin(cached)]]).head(limit)
    s0i = s0.set_index("symbol")
    syms = s0["symbol"].tolist()
    print(f"[run] universe {len(syms)} companies of {stats['raw']} listings")

    prev = json.loads((OUT / "picks.json").read_text()) if (OUT / "picks.json").exists() else {}
    prev_pr = {p.get("s") or p.get("symbol"): p.get("pr", 0) or -(p.get("rank") or 9999) for p in prev.get("picks", [])}
    requested = scan_requests.load(set(df["symbol"]))
    req_syms = [r["symbol"] for r in requested]
    order = list(dict.fromkeys(list(theses) + req_syms + sorted(syms, key=lambda s: -(prev_pr.get(s) or 0))))
    order = [s for s in order if s in s0i.index]
    Path("data/universe_stage1.json").write_text(json.dumps(order))

    # ---------- Prices (5 years for own-history valuation and market mood) ----------
    px = prices.download_cached(syms + [config.BENCHMARK], period="5y")
    H.mark("prices")
    H.source("prices", stocks=len(px))
    bench = px.pop(config.BENCHMARK, None)
    bench_close = bench["Close"] if bench is not None else pd.Series(dtype=float)
    if len(bench_close):  # data date = last trading date of the prices, not the IST calendar day (a run after midnight IST, or on a holiday, must not stamp the next day on old prices)
        today = min(today, bench_close.index[-1].date())
    tech = {}
    for sym in syms:
        d = px.get(sym)
        t = technicals.analyze(d, bench_close) if d is not None else None
        if t:
            tech[sym] = t
    try:  # closes of ETFs and other listed symbols (the app's Portfolio prices your ETFs from this)
        prices.extra_prices({*syms}, bench_close)
    except Exception as e:  # noqa: BLE001
        print(f"[prices] extra prices failed: {e}")
    rs_all = pd.Series({s: t["rs_raw"] for s, t in tech.items()}).rank(pct=True)
    # liquidity / penny tags from our own prices (exchange files), not a screener
    def _tags(s):
        t = tech.get(s) or {}
        out = []
        if t.get("traded_value_cr") is not None and t["traded_value_cr"] < config.MIN_TRADED_VALUE / config.CRORE:
            out.append("illiquid")
        if t.get("price") is not None and t["price"] < config.MIN_PRICE:
            out.append("penny")
        return out
    s0i["tags"] = pd.Series({s: _tags(s) for s in s0i.index})
    ind_of = {s: s0i.loc[s, "industry"] for s in syms}
    ind_rank = {}
    for ind, grp in pd.Series({s: t["rs_raw"] for s, t in tech.items()}).groupby(lambda s: ind_of.get(s)):
        if isinstance(ind, str) and len(grp) >= 3:
            ind_rank.update(grp.rank(pct=True).to_dict())
    print(f"[run] price history for {len(tech)} of {len(syms)}")

    # ---------- Filings (primary), Yahoo statements (fallback), shareholding ----------
    mem = M.all_records()
    force = set()
    for sym, rec in mem.items():
        for c in rec.get("checkpoints", []):
            if c["type"] == "results" and c["status"] == "due" and sym in s0i.index:
                if F.load().get(sym, {}).get("fetched", "")[:10] < c["due"]:
                    force.add(sym)
    fund = F.refresh(order, force=force)
    cal = exchange.results_calendar(today)
    fins = filings.refresh(order, today, cal, order[:300])
    H.mark("filings")
    H.source("filings", stocks=len(fins))
    sh_old = exchange.shareholding_cached(order, today)  # old git cache: fallback until the new store has every stock
    shp_st = SHP._load() if limit else SHP.refresh(order, today)
    H.mark("shareholding")
    H.source("shareholding", stocks=sum(1 for v in shp_st.values() if v.get("q")))
    # announcements first: today's insider-trading / SAST disclosures decide which stocks' insider trades are re-read
    try:
        ann_st = ANN._load() if limit else ANN.refresh(today)
    except Exception as e:  # noqa: BLE001
        print(f"[ann] refresh failed: {e}")
        ann_st = ANN._load()
    pit_since = (CF._load().get("pit_since") or str(today - timedelta(days=3)))
    in_funnel = {p.get("s") for p in prev.get("picks", []) if p.get("vd") != "Removed"} or None
    bo_all = {s: str(s0i.loc[s, "bse_code"]) for s in syms if s.endswith(".BO") and s0i.loc[s, "bse_code"] == s0i.loc[s, "bse_code"] and s0i.loc[s, "bse_code"]}
    cf_st = CF._load() if limit else CF.refresh(order, today, bse_codes=bo_all, insider_filers=ANN.insider_filers(ann_st, pit_since),
                                                    scope=in_funnel)  # dividends, preferential issues, related-party loans, insider trades
    H.mark("corporate filings")
    H.source("corporate filings", dividends=len((cf_st.get("ca") or {}).get("rows", {})), preferential=len((cf_st.get("pref") or {}).get("rows", {})),
             governance=sum(1 for v in ((cf_st.get("gov") or {}).get("parsed") or {}).values() if v.get("date")), governance_not_disclosed=sum(1 for v in ((cf_st.get("gov") or {}).get("parsed") or {}).values() if not v.get("date")), insider=len(cf_st.get("pit") or {}))

    def prom_hist(sym):
        return SHP.promoter_hist(shp_st, sym) or (sh_old.get(sym) or {}).get("hist") or []

    def promoter(sym):
        h = prom_hist(sym)
        return (h[-1]["promoter_pct"] if h else None), (round(h[-1]["promoter_pct"] - h[-2]["promoter_pct"], 2) if len(h) >= 2 else None)

    def price_of(sym):
        if sym in tech:
            return tech[sym]["price"]
        if sym in px and len(px[sym]):
            return float(px[sym]["Close"].iloc[-1])
        x = s0i.loc[sym, "regularMarketPrice"]
        return float(x) if x == x else None

    # companies with no NSE results filings (BSE-only, or NSE-traded but filing on BSE): BSE results summary
    from narrativ import bseres
    no_nse = {s: str(s0i.loc[s, "bse_code"]) for s in syms
              if s0i.loc[s, "bse_code"] == s0i.loc[s, "bse_code"] and s0i.loc[s, "bse_code"] and not ((fins.get(s) or {}).get("quarters"))}
    bres = bseres.refresh(no_nse, today, filings.expected_quarter(today))
    H.source("bse_results", companies=len(no_nse), with_results=sum(1 for s in no_nse if (bres.get(s) or {}).get("q")))
    from narrativ import corrections as CORR  # the loop: wrong numbers found in Claude's reviews replace ours, then re-score
    fins_c, corr_applied, corr_block = CORR.apply(fins)
    mx = {s: MX.compute(fins_c.get(s) or {}, price_of(s), fund.get(s), promoter(s)[0], bres.get(s) if s in no_nse else None) for s in syms}
    for s in syms:
        if s in s0i.index and MX.val(mx[s], "mcap_cr") is None and s0i.loc[s, "marketCap"] == s0i.loc[s, "marketCap"]:  # missing or n/m
            mx[s]["mcap_cr"] = MX._m(float(s0i.loc[s, "marketCap"]) / 1e7, "Market cap (exchange market-cap file)", {}, "NSE/BSE", None, 0, "₹ cr")
    by_ind = {}
    for s, Mx in mx.items():
        pe = MX.val(Mx, "pe")
        if pe and 0 < pe < 300:
            by_ind.setdefault(ind_of.get(s), []).append(pe)
    ind_pe = {k: float(pd.Series(v).median()) for k, v in by_ind.items() if len(v) >= 5}
    print(f"[run] filings-sourced {sum(1 for m in mx.values() if m.get('source') == 'NSE filing')} of {len(mx)}")

    # ---------- Exchange flow + analyst consensus ----------
    bulk = exchange.bulk_deals()
    bse_codes.update({k: v["scrip"] for k, v in cal.items() if v.get("scrip")})
    codes_path.write_text(json.dumps(bse_codes, indent=0, sort_keys=True))
    an_cands = [s for s in order if (fund.get(s) or {}).get("numberOfAnalystOpinions")]
    an_prio = ({p.get("s") for p in prev.get("picks", []) if p.get("dc") in ("Buy", "Strong Buy") or p.get("cand")} | set(theses)
               | {x.get("symbol") for x in (json.loads((OUT / "queue.json").read_text()).get("items", []) if (OUT / "queue.json").exists() else [])})
    an_res = {s: max((((q or {}).get("Consolidated") or (q or {}).get("Standalone") or {}).get("filed") or "")
                     for q in (fins.get(s) or {}).get("quarters", {}).values()) if (fins.get(s) or {}).get("quarters") else ""
              for s in an_cands}
    an = analyst.fetch(an_cands, today, priority=an_prio, results_since=an_res)
    print(f"[run] analyst consensus for {len(an)} of {len(an_cands)}")

    named_of = {}  # named broker calls (verified research), shown next to the Yahoo consensus

    def analyst_view(sym):
        a, p = an.get(sym), price_of(sym)
        bt = (theses.get(sym) or {}).get("broker_targets") or []
        named = None
        if bt and p:
            tg = sorted(b["target"] for b in bt)
            med = tg[len(tg) // 2] if len(tg) % 2 else (tg[len(tg) // 2 - 1] + tg[len(tg) // 2]) / 2
            named = {"n": len(bt), "median": med, "upside": round((med / p - 1) * 100, 1), "latest": bt[0]["date"], "calls": bt,
                     "src": "named broker calls, quoted (research)"}
        named_of[sym] = named
        if not a or not p:
            return None
        return {"mean": a["mean"], "low": a.get("low"), "high": a.get("high"), "n": a.get("n") or (fund.get(sym) or {}).get("numberOfAnalystOpinions"),
                "upside": round((a["mean"] / p - 1) * 100, 1), "fresh": a["fresh"], "mix": analyst.mix_text(a), "eps_est": a.get("eps_est"),
                "first_tracked": a.get("first_tracked"), "last_change": a.get("last_change"), "asof": a.get("asof"), "src": "Yahoo consensus",
                "named": named}

    # ---------- Funnel levels ----------
    rot_sec, bench500 = rotation.sectors(today)
    rot_ind = rotation.industries(px, ind_of, bench500)
    istats = FN.industry_stats([(ind_of.get(s), mx[s]) for s in syms])
    btypes, prows = {}, []
    for s in syms:
        k = (mx[s].get("kind") or "general")
        bt = FN.business_type(mx[s], ind_of.get(s), k)
        bt, mk, val_ = FN.primary(mx[s], bt)
        btypes[s] = (bt, mk, val_)
        prows.append((s, ind_of.get(s), bt, mk, val_))
    peers = FN.peer_medians(prows)

    # ---------- All-company NSE announcements (refreshed above, before corporate filings) -> subject-line red-flag checks ----------
    from narrativ import bseann, orders as ORD
    bo_codes = {s: str(s0i.loc[s, "bse_code"]) for s in syms if s.endswith(".BO") and s0i.loc[s, "bse_code"] == s0i.loc[s, "bse_code"] and s0i.loc[s, "bse_code"]}
    try:
        bse_ann = bseann.refresh(bo_codes, today) if not limit else bseann._load()
    except Exception as e:  # noqa: BLE001
        print(f"[bseann] refresh failed: {e}")
        bse_ann = bseann._load()
    annc = {s: ANN.checks(ann_st, s, today, bse_ann) for s in syms}
    # credit-rating actions the agencies upload to NSE (narrativ/ratings.py): A5 from the agencies' own filings
    try:
        from narrativ import ratings as RT
        rat = RT.per_stock(RT.refresh(today), today)
        n_a5 = 0
        for s in syms:
            a = RT.a5(rat.get(s))
            if a and annc.get(s) is not None and (a[0] == 1 or (annc[s].get("A5") or (None,))[0] != 1):
                n_a5 += annc[s].get("A5") != a
                annc[s]["A5"] = a
        H.source("credit ratings (NSE)", stocks=len(rat), downgrades_12m=sum(1 for v in rat.values() if v.get("downgrade")),
                 upgrades_12m=sum(1 for v in rat.values() if v.get("upgrades")), negative_outlook=sum(1 for v in rat.values() if v.get("negative")),
                 a5_from_agencies=n_a5)
    except Exception as e:  # noqa: BLE001
        print(f"[ratings] failed: {e}")
        rat = {}
    # insolvency public announcements (narrativ/ibbi.py): a listed company as the debtor fails A4; as the applicant, shown
    try:
        from narrativ import ibbi as IB
        name_col = "longName" if "longName" in s0i.columns else None
        names = {s: (s0i.loc[s, name_col] if name_col else None) or (mem.get(s) or {}).get("name") or "" for s in syms}
        ins = IB.match(IB.refresh(), names, today)
        for s, m in ins.items():
            a = IB.a4(m)
            if a and annc.get(s) is not None:
                annc[s]["A4"] = a
        H.source("insolvency notices (IBBI)", stocks=len(ins), as_debtor=sum(1 for v in ins.values() if v["as_debtor"]),
                 as_applicant=sum(1 for v in ins.values() if v["as_applicant"]))
    except Exception as e:  # noqa: BLE001
        print(f"[ibbi] failed: {e}")
        ins = {}
    print(f"[run] announcement checks for {sum(1 for v in annc.values() if v)} of {len(syms)} (BSE-only: {sum(1 for s in bo_codes if annc.get(s))} of {len(bo_codes)})")

    def ann_rows(s):
        return (bse_ann.get("rows") or {}).get(s, []) if s.endswith(".BO") else (ann_st.get("rows") or {}).get(s, [])
    nsed = NSED.load(today) if not limit else {}  # delivery %, GSM/ASM, index lists (NSE daily files)
    H.mark("announcements and NSE daily files")
    H.source("announcements", companies=len((ann_st or {}).get("rows") or {}))
    H.source("NSE daily files", delivery_days=len(nsed.get("deliv") or {}), latest=max(nsed.get("deliv") or {"": 0}) or None,
             surveillance=len(nsed.get("surv") or {}), index_members=len(nsed.get("idx") or {}))

    try:  # exchange classification by ISIN (industry decides whether book-to-bill applies)
        cls_of = json.loads(Path("data/classification.json").read_text())
    except Exception:  # noqa: BLE001
        cls_of = {}

    def ext(sym):  # exchange daily files + filings for one stock; BSE-only: BSE delivery, BSE dividends, BSE announcements
        e = NSED.for_symbol(nsed, sym, s0i.loc[sym, "bse_code"] if sym in s0i.index else None) if nsed else None
        if not sym.endswith((".NS", ".BO")):
            return None
        cf = CF.stats(cf_st, sym, today)
        mk = None
        if cf["pref"] and sym in px:
            c = px[sym]["Close"]
            c = c[c.index <= pd.Timestamp(cf["pref"][0][0])]
            mk = float(c.iloc[-1]) if len(c) else None
        t3 = ORD.t3(ann_rows(sym), MX.val(mx[sym], "revenue_ttm_cr"), today)
        ind = (cls_of.get(s0i.loc[sym, "isin"]) or {}).get("i") if "isin" in s0i.columns else None
        b2b = ORD.b2b(ann_rows(sym), MX.val(mx[sym], "revenue_ttm_cr"), today, ind in ORD.ORDER_INDUSTRIES)
        d24 = str(today - timedelta(days=730))
        cf = {**cf, "dev_docs": [{"date": r[0], "url": r[3], "title": (r[2] or r[1])[:120]} for r in ann_rows(sym)
                                 if r[0] >= d24 and r[3] and ANN.DEV.search(f"{r[1]} {r[2]}")][:3]}
        if sym.endswith(".BO"):  # no BSE shareholding / surveillance / insider source: those checks stay "not connected"
            return {**(e or {}), "deliv_src": "BSE", "shp": None, "shp_ok": False, "cf": cf, "pref_mkt": None, "t3": t3, "b2b": b2b}
        return {**(e or {}), "deliv_src": "NSE", "shp": SHP.stats(shp_st, sym), "shp_ok": bool(shp_st), "cf": cf, "pref_mkt": mk, "t3": t3, "b2b": b2b}

    ev = {}
    for s in syms:
        Mx, t, d = mx[s], tech.get(s), px.get(s)
        # R1 / R2 exemption (RULES.md "Lenders exempt"): banks, NBFCs, HFCs, insurers (labelled); brokers / AMCs / exchanges are not
        lend_t = FN.lender_type(Mx.get("kind"), Mx.get("source"), s0i.loc[s, "sector"], ind_of.get(s), s0i.loc[s, "basic_industry"] if "basic_industry" in s0i.columns else None)
        lender = Mx.get("kind") in FN.LENDERS or bool(lend_t)  # scoring model (lender metrics), consistent with how metrics.py read the filing
        th = theses.get(s) or {}
        f = fund.get(s) or {}
        L = {}
        L["surv"] = FN.survivability(Mx, lender, annc.get(s), ext(s))
        L["qual"] = FN.quality(Mx, lender, istats.get(ind_of.get(s)))
        bt, mk, cur = btypes[s]
        hist = MX.history(fins.get(s) or {}, d["Close"] if d is not None else None)
        L["val"] = FN.valuation(Mx, bt, mk, cur, hist, peers.get(s), lender)
        L["mgmt"] = FN.management(Mx, prom_hist(s), th, lender, annc.get(s), ext(s))
        av = analyst_view(s)
        L["mom"] = FN.momentum(t, d, float(rs_all.get(s, 0.5)) if s in rs_all.index else 0.5, ind_rank.get(s), bulk.get(s), Mx, av, ext(s))
        inst = f.get("heldPercentInstitutions")
        L["disc"] = FN.discovery(None if inst is None else round(inst * 100, 1), f.get("numberOfAnalystOpinions"), d, bulk.get(s), ext(s))
        # RULES.md T11-T15: price-moving signals are dated triggers on the Outlook tab, counted before its removal is decided
        # buybacks (T14) from the stock's own exchange: BSE announcements for a BSE-only stock
        sig = FN.signal_triggers(d, bench_close, Mx, av, ext(s), ann_rows(s), today, MX.val(Mx, "mcap_cr"))
        L["out"] = FN.outlook(Mx, (istats.get(ind_of.get(s)) or {}).get("wind"), (rot_ind.get(ind_of.get(s)) or {}).get("q"),
                              th, th.get("scan_raw"), Mx.get("flags"), L["surv"], L["qual"], L["mgmt"], ext(s), signals=sig)
        if not s.endswith(".NS"):  # no BSE shareholding or insider-trading store: these checks did not run (not passed)
            L["out"]["not_evaluated"] = FN.BSE_NOT_EVALUATED
        out_l = next(((i + 1, L[k]["rm"]) for i, k in enumerate(FN.LEVELS) if L[k].get("out")), None)
        vd = "Removed" if out_l else FN.verdict(L)
        ev[s] = {"L": L, "vd": vd, "out": out_l, "pr": FN.priority(L), "an": av, "hist": hist, "lender": lend_t, "lscore": lender,
                 "setup": FN.setup(d, t, av["mean"] if av else None)}
    infunnel = [s for s in syms if not ev[s]["out"]]

    # ---------- Research view (scan label, scenarios) ----------
    for s, th in theses.items():
        if th.get("scan_raw") and s in ev:
            f = {k: MX.val(mx[s], mk) for k, mk in FUND_KEYS.items()}
            band = MX.pe_band(fins.get(s) or {}, px[s]["Close"] if s in px else None)
            sv = scan_view(th, f | {"inst_pct": None, "analysts": None}, price_of(s), band, th.get("credibility"))
            if sv:
                theses[s]["scan"] = sv
    (OUT / "research.json").write_text(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "scan_raw"} for k, v in theses.items()},
                                                  ensure_ascii=False, separators=(",", ":")))

    try:
        from narrativ import issues as ISS
        scale = {s: MX.scale_issues(fins_c.get(s) or {}) for s in syms}  # unit errors: corrected or left out, logged either way
        print(f"[issues] unit errors: {sum(1 for v in scale.values() for e in v if e['action'] == 'corrected' and e.get('kind') != 'owners')} quarters corrected, "
              f"{sum(1 for v in scale.values() for e in v if e['action'] == 'excluded')} left out; "
              f"owners' profit rebuilt in {sum(1 for v in scale.values() for e in v if e.get('kind') == 'owners')} quarters")
        reg = ISS.update(theses, mx, MX.val, today, corr_applied, scale)
        H.source("data issues", open=reg["open"], systemic_open=reg["open_systemic"], fixed=reg["fixed"])
    except Exception as e:  # noqa: BLE001
        print(f"[issues] failed: {e}")
    # ---------- Latest earnings call (narrativ/latest_call.py; owner, 24 Nov 2026) ----------
    # a review must have seen the call for the latest results quarter: exchange / company transcript, else AlphaStreet's
    from narrativ import alphastreet as AS, latest_call as LC
    calls, call_pre = {}, {}

    def latest(s, filings):
        try:
            return LC.latest_call(s, (mx.get(s) or {}).get("last_quarter"), (mx.get(s) or {}).get("filed"), ann_st, filings, today,
                                  AS.calls(s, today))
        except Exception as e:  # noqa: BLE001
            print(f"[calls] {s}: {type(e).__name__}: {e}")
            return None

    def call_of(s):  # after the exchange filings (ex) are loaded: NSE + BSE transcripts + AlphaStreet (its list is cached for the day)
        if s not in calls:
            calls[s] = latest(s, ex)
        return calls[s]
    for s in syms:  # stocks with a review: did the review see the latest call? (NSE transcripts + AlphaStreet; ex is not loaded yet)
        if ((theses.get(s) or {}).get("audit") or {}).get("verdict"):
            call_pre[s] = latest(s, {})
    print(f"[calls] reviewed stocks: {len(call_pre)}, latest call found {sum(1 for c in call_pre.values() if c and c['state'] == 'found')}")
    dec = {s: FN.decision(ev[s]["L"], ev[s]["out"], theses.get(s), (theses.get(s) or {}).get("scan"), ev[s]["setup"], price_of(s), annc.get(s), today=today,
                          filed=(mx.get(s) or {}).get("filed"), scored=ev[s]["vd"] != "Not enough data",
                          call_since=(call_pre.get(s) or {}).get("since"))
           for s in syms}
    # ---------- Open data issues and Buy gates (RULES.md; FN.apply_buy_rules, shared with republish.py) ----------
    gate_n = {}
    for s in syms:
        d0 = dec.get(s) or {}
        if not (d0.get("candidate") or d0.get("d") in FN.BUY):
            continue
        sh = (ext(s) or {}).get("shp") or {}
        dec[s] = FN.apply_buy_rules(d0, mx.get(s) or {}, ev[s]["lender"], ev[s]["L"], theses.get(s), today, corr_block.get(s), sh.get("inst_down_q"))
        for x in dec[s].get("gates") or []:
            gate_n[x[:2]] = gate_n.get(x[:2], 0) + 1
    print(f"[gates] Buy rules held back {sum(1 for d in dec.values() if d.get('gates'))} stocks: {gate_n}")
    for s, a in corr_applied.items():
        if s in dec:
            dec[s].setdefault("why", []).append("Re-scored with corrected filing values: " + ", ".join(f"{x['field']} ₹{x['now']:,.0f} cr" for x in a))
    aflags = {s: FN.audit_flags(mx.get(s) or {}, ev[s]["lender"]) for s in syms}
    # v1 kept for one week of side-by-side comparison (PLAN.md section 16)
    dec_v1 = {s: FN.decision_v1(ev[s]["L"], ev[s]["out"], theses.get(s), (theses.get(s) or {}).get("scan"), ev[s]["setup"], price_of(s), annc.get(s))["d"]
              for s in syms}
    moved = [(s, dec_v1[s], dec[s]["d"]) for s in syms if dec_v1[s] != dec[s]["d"]]
    print(f"[run] decision v1 -> v2: {pd.Series([f'{a} -> {b}' for _, a, b in moved]).value_counts().to_dict() if moved else 'no change'}")
    (OUT / "decision_compare.json").write_text(json.dumps({"date": str(today), "v1": pd.Series(list(dec_v1.values())).value_counts().to_dict(),
        "v2": pd.Series([d["d"] for d in dec.values()]).value_counts().to_dict(), "changed": [{"s": s, "v1": a, "v2": b} for s, a, b in moved]},
        ensure_ascii=False, indent=0))
    for s in syms:  # the profile tag must not contradict the decision
        if not ev[s]["out"]:
            ev[s]["vd"] = FN.verdict(ev[s]["L"], dec[s]["d"])
    print(f"[run] in funnel {len(infunnel)} of {len(syms)}")

    # ---------- Exchange per-stock records for the top of the funnel ----------
    top = sorted(infunnel, key=lambda s: -ev[s]["pr"])
    pre = list(dict.fromkeys([s for s in theses if s in s0i.index] + [s for s in req_syms if s in s0i.index] + top[:80]))
    ex = exchange.per_stock(pre, today, bse_codes, ann_st, shp_st, nsed)

    # ---------- Memory, checkpoints, verdict log ----------
    newly_due_all, changes, new_events = [], [], []
    keep = set(infunnel) | set(theses) | set(req_syms)
    rank = {s: i for i, s in enumerate(top, 1)}
    for s in syms:
        if s not in keep:
            continue
        e = ev[s]
        th = theses.get(s) or {}
        name = s0i.loc[s, "longName"] if s0i.loc[s, "longName"] == s0i.loc[s, "longName"] else s0i.loc[s, "shortName"]
        rec = M.touch(mem.get(s), s, name, today)
        rec.update({"status": "removed" if e["out"] else "active", "drop_reason": (f"L{e['out'][0]} {FN.LEVEL_NAMES[FN.LEVELS[e['out'][0] - 1]]}: {e['out'][1]}" if e["out"] else None),
                    "last_seen": str(today)})
        cps = []
        if rank.get(s, 9999) <= config.CHECKPOINT_TOP_N or th:
            ex_date = (cal.get(s) or {}).get("date")
            cps += M.auto_checkpoints(mx[s].get("last_quarter"), ex_date or (fund.get(s) or {}).get("next_earnings"), today, source=(cal.get(s) or {}).get("source"))
        cps += [c for c in (th.get("checkpoints") or []) if c.get("id") and c.get("due")]
        cps += [{"id": f"promise-{p['id']}", "type": "promise", "due": p["due"], "what": p["promise"], "expected": f"Promised on {p['call']}", "source": p["source"]}
                for p in (th.get("promises") or []) if p.get("due") and p.get("due_verified")]
        raw = th.get("scan_raw") or {}
        for kind, lst in (("must_go_right", raw.get("must_go_right")), ("kill_switch", raw.get("kill_switches"))):
            for n, w in enumerate(lst or []):
                if w.get("due"):
                    cps.append({"id": f"{kind}-{n}-{w['due']}", "type": kind, "due": w["due"], "what": w.get("text", ""),
                                "expected": w.get("check"), "source": w.get("source")})
        # every exchange announcement is stored; new red/watch/green ones after the last research re-queue the stock
        known = {e.get("url") or f"{e.get('date')}|{e.get('text')}" for e in rec.get("events", [])}
        src_ev = (ex.get(s) or {}).get("events") or ANN.recent_events(bse_ann if s.endswith(".BO") else ann_st, s)
        recent = (today - timedelta(days=7)).isoformat()  # first sight of a stock's history must not flood alerts
        # stored events take the current rules (a rule fix reaches filings already kept); one that turns red alerts like a new one
        all_ev = (ex.get(s) or {}).get("events") or ANN.recent_events(bse_ann if s.endswith(".BO") else ann_st, s, limit=None, info=True)
        new_events += [(s, x) for x in EV.retype(rec.get("events", []), all_ev, str(today)) if (x.get("date") or "") >= recent]
        fresh = [ev for ev in src_ev if (ev.get("url") or f"{ev.get('date')}|{ev.get('text')}") not in known]
        if fresh:
            rec["events"] = sorted(rec.get("events", []) + fresh, key=lambda e: e.get("date") or "", reverse=True)[:80]
            new_events += [(s, ev) for ev in fresh if ev["sev"] == "red" and (ev.get("date") or "") >= recent]
        resolved = dict(th.get("resolved") or {})
        for pr in (th.get("promises") or []):
            if pr.get("status") in ("delivered", "beat", "partly", "missed", "delayed"):
                last = (pr.get("updates") or [{}])[-1]
                resolved[f"promise-{pr['id']}"] = {"status": pr["status"], "outcome": last.get("text"), "source": last.get("source"), "date": last.get("date")}
        nd = M.update_checkpoints(rec, cps, resolved, today)
        newly_due_all += [(s, c) for c in nd]
        M.record_thesis(rec, th)
        tiers = [e["L"][k]["t"] for k in FN.LEVELS]
        vl = rec.setdefault("verdicts", [])
        if not vl or vl[-1]["v"] != e["vd"]:
            old = rec.get("tiers") or []
            cause = [f"{FN.LEVEL_NAMES[k]} {e['L'][k]['name']}" for i, k in enumerate(FN.LEVELS) if i < len(old) and old[i] != tiers[i]]
            vl.append({"d": str(today), "v": e["vd"], "from": vl[-1]["v"] if vl else None, "cause": "; ".join(cause) or ("first rating" if not vl else "rule change")})
            if len(vl) > 1:
                changes.append((s, vl[-1]))
            rec["verdicts"] = vl[-30:]
        rec["tiers"] = tiers
        M.snapshot(rec, {"pr": e["pr"], "vd": e["vd"], "t": tiers, "price": price_of(s), "stage": (tech.get(s) or {}).get("stage")}, today)
        M.save(rec)
        mem[s] = rec
    for s, rec in mem.items():
        if s not in keep and rec.get("status") not in ("removed", "dropped") and s in ev:
            rec.update({"status": "removed", "drop_reason": f"L{ev[s]['out'][0]}: {ev[s]['out'][1]}" if ev[s]["out"] else None})
            M.save(rec)

    # ---------- Multibagger potential (RULES.md MB) ----------
    from narrativ import portfolio as PF
    mb_of = {}
    for s in syms:
        L, Mx = ev[s]["L"], mx.get(s) or {}
        if ev[s]["out"]:
            continue
        horizon = str(today + timedelta(days=548))
        dated = any(d.get("due") and d.get("due_verified") and str(today) <= str(d["due"]) <= horizon for d in (theses.get(s) or {}).get("drivers") or [])
        trig = dated or any(x.get("id") != "T4" for x in L["out"].get("triggers") or [])
        e1 = next((i for i in L["mom"].get("items") or [] if i.get("id") == "E1"), {})
        mb_of[s] = PF.multibagger(MX.val(Mx, "mcap_cr"), L["disc"]["t"], MX.val(Mx, "rev_yoy_pct"), e1.get("m") == 2,
                                  MX.val(Mx, "roce_pct"), trig, L["val"]["t"])
    print(f"[run] multibagger potential: {sum(mb_of.values())} stocks")
    # U1 profit speeding up (narrativ/upside.py, RULES.md Ranking): +10 in the blend (owner, 25 Nov 2026, after the replay)
    from narrativ import upside as UP
    u1_of = {s: UP.profit_speeding((mx.get(s) or {}).get("quarterly")) for s in syms}
    print(f"[run] U1 profit speeding up: {sum(1 for v in u1_of.values() if v[0])} stocks")

    # ---------- Readiness ranking (review order and Top 10 order) ----------
    # 1 industry rotation: Leading/Improving > neutral/unknown > Weakening > Lagging
    # 2 entry setup: live (breakout, pullback, base) > wait > extended / trend broken
    # 3 blend: 45% momentum (relative-strength percentile) + 15% nearness to the 52-week high (T13) + 40% valuation score;
    #   -15 institutions sold 3+ quarters (R5), +5 mutual funds entering (T15), +5 multibagger potential (MB),
    #   +10 profit speeding up (U1)  [RULES.md Ranking]
    # 4 overall score
    def readiness(s):
        q = (rot_ind.get(ind_of.get(s)) or {}).get("q")
        ti = 0 if q in ("Leading", "Improving") else 2 if q == "Weakening" else 3 if q == "Lagging" else 1
        ts = FN.setup_tier(ev[s]["setup"], ev[s]["L"]["mom"].get("extended"))  # shared with the replay (narrativ/replay.py)
        rs = float(rs_all.get(s, 0.5)) * 100 if s in rs_all.index else 50.0
        vs = ev[s]["L"]["val"].get("s")
        t_ = tech.get(s) or {}
        hi, pxl = t_.get("hi52"), t_.get("price")
        near = max(0.0, min(100.0, (1 - (1 - pxl / hi) / 0.30) * 100)) if hi and pxl else 50.0  # T13: 100 at the high, 0 at 30% below
        blend = 0.45 * rs + 0.15 * near + 0.4 * (vs if vs is not None else 50)
        if (((ext(s) or {}).get("shp") or {}).get("inst_down_q") or 0) >= 3:  # RULES.md R5
            blend -= 15
        if any(x.get("id") == "T15" for x in ev[s]["L"]["out"].get("triggers") or []):  # T15 mutual funds entering
            blend += 5
        if mb_of.get(s):  # MB multibagger potential
            blend += 5
        if (u1_of.get(s) or (None,))[0]:  # U1 profit speeding up
            blend += UP.U1_BOOST
        return (ti, ts, -round(blend, 2), -ev[s]["pr"])
    rank_of = {s: i + 1 for i, s in enumerate(sorted(syms, key=readiness))}

    # ---------- Claude queue (PLAN.md section 4) ----------
    queue, seen = [], set()

    def q(sym, why, task, extra=None):
        if sym in seen or len(queue) >= config.RESEARCH_PER_DAY or sym not in s0i.index and sym not in mem:
            return
        seen.add(sym)
        item = {"symbol": sym, "name": (mem.get(sym) or {}).get("name") or sym, "reason": why, "task": task, **(extra or {})}
        fil = (ex.get(sym) or {}).get("filings")
        if fil and "filings" not in item:
            item["filings"] = fil
        if sym in ev:
            item["priority"] = ev[sym]["pr"]
            item["verdict"] = ev[sym]["vd"]
        queue.append(item)

    # every Buy / Strong Buy must pass Claude's independent audit before the app shows it as buyable (top priority after requests),
    # in readiness order: the stocks most likely to be good buys now are reviewed first (and lead the Top 10)
    to_audit = sorted([s for s in syms if dec[s].get("candidate") in ("Strong Buy", "Buy")], key=readiness)
    for r in requested:  # the owner asked: a full review (every check), unless Claude reviewed it in the last 7 days
        a = ((raw_theses.get(r["symbol"]) or {}).get("audit") or {}).get("date")
        if not a or (today - date.fromisoformat(str(a)[:10])).days > 7:
            q(r["symbol"], f"requested ({r['via']}): full review (verify every number, connect the dots, verdict)", "review",
              {"checks": aflags.get(r["symbol"]) or [], "requested": True})
    def researched_on(th):
        return max(x for x in (th.get("updated"), (th.get("scan") or {}).get("date"), (th.get("scan_raw") or {}).get("date"), "2000-01-01") if x)[:10]

    waits, ns_w = [], [None]

    def intimation_text(url):  # the call-schedule letter (short PDF, cached by packs._text)
        try:
            from narrativ.filings import NSESession
            ns_w[0] = ns_w[0] or NSESession()
            return PK_text(url, ns_w[0])[0]
        except Exception as e:  # noqa: BLE001
            print(f"[calls] intimation {url[-40:]}: {str(e)[:80]}")
            return None
    from narrativ.packs import _text as PK_text
    for s in to_audit:  # idea 2: results due soon, a scheduled call, or results out and the call not yet: review after it
        rd = (cal.get(s) or {}).get("date")
        sc = LC.scheduled_call(s, ann_st, today, intimation_text) if (calls.get(s) or call_of(s) or {}).get("state") != "found" else None
        why = LC.waiting(call_of(s), today, rd, (sc or {}).get("date"))
        if why:
            waits.append(s)
            dec[s]["missing"] = [why] + list(dec[s].get("missing") or [])
            continue
        q(s, f"rules say {dec[s]['candidate']}: full review (verify every number, connect the dots, verdict) before it is shown as buyable",
          "review", {"checks": aflags[s]})
    # queue hygiene (narrativ/overdue.py): overdue kill switches / must-go-right items / promises go first among the rechecks,
    # and a recheck is only queued when there is something to check: a real new document (not a cover letter, audio link or
    # call intimation) filed since the thesis was updated, a new announcement, or an overdue item
    from narrativ import overdue as OD, packs as PK

    def new_docs(s):
        return PK.new_documents((ex.get(s) or {}).get("filings"), (raw_theses.get(s) or theses.get(s) or {}).get("updated"))
    hold_buy = {s for s in syms if dec[s].get("d") in ("Strong Buy", "Buy", "Hold") or dec[s].get("candidate") in ("Strong Buy", "Buy")}
    odp = OD.plan(raw_theses, mem, today, new_docs, hold_buy, config.OVERDUE_COOLDOWN_DAYS)
    od_syms = {s for s, _, _ in odp["overdue"]}

    def q_overdue(top):
        for s, items, is_top in odp["overdue"]:
            if is_top == top:
                nd = new_docs(s)
                q(s, OD.reason(items), "recheck", {"overdue": items[:8], "filings": nd[:3]})
    q_overdue(True)  # a kill switch past due on a Buy / Hold: above everything except reviews
    # RULES.md R4: scores say Buy and only the dated trigger is missing: research can supply it (dated, quoted driver)
    # stocks where the free readers found a dated, verified forward statement go first (narrativ/reader.py; Claude still confirms)
    fwd = json.loads((OUT / "forward.json").read_text()).get("stocks", {}) if (OUT / "forward.json").exists() else {}
    for s in sorted([s for s in syms if [g[:2] for g in dec[s].get("gates") or []] == ["R4"]],
                    key=lambda s: (not (fwd.get(s) or {}).get("dated"), readiness(s)))[:6]:
        q(s, "scores say Buy but no dated trigger (RULES.md R4): find an order win, commissioning date or guidance raise with its date",
          "enrich")
    q_overdue(False)
    def new_since(e, th):
        """Filed after the last research, or re-typed red (red_seen, a rule fix) on or after it: research dates have no time,
        so a same-day research may predate the re-typing; it stays queued until a later research day (at most a day of repeats)."""
        r = researched_on(th)
        return (e.get("date") or "") > r or (e.get("red_seen") or "") >= r
    for sev, why in (("red", "bad news filed since the last research: check kill switches and the thesis"),):
        for s, th in theses.items():
            evs = [e for e in (mem.get(s) or {}).get("events", []) if e["sev"] == sev and new_since(e, th)]
            if evs:
                q(s, why, "recheck", {"events": evs[:5]})
    for s, th in theses.items():
        u = th.get("updated")
        new = [x for x in new_docs(s) if u and "transcript" in str(x.get("text", "")).lower()]
        if new:
            q(s, "new transcript filed: re-check promises and kill switches", "recheck", {"filings": new[:3]})
    for s, rep in (vreport or {}).items():  # quotes whose source link is dead: research swaps in a live copy of the same document
        dead = sorted({r["reason"].split(": ", 1)[1].split(" -> ")[0] for r in (rep or {}).get("rejected") or [] if str(r.get("reason", "")).startswith("source not reachable: ")})
        if dead and s in theses:
            q(s, "source link no longer opens: replace it with a live copy of the same document (NSE archive, BSE AttachHis, company site) and keep the quote", "recheck", {"dead_links": dead[:5]})
    for s, rec in sorted(mem.items(), key=lambda kv: -(ev.get(kv[0]) or {}).get("pr", 0)):
        due = [c for c in rec.get("checkpoints", []) if c["status"] == "due"]
        if due and s in theses and (s in od_syms or new_docs(s)):  # nothing new to read and nothing overdue: no recheck
            q(s, "checkpoint due and a new document is filed", "recheck", {"checkpoints": due})
    def evs_any(s, th):  # any announcement filed since the last research
        return any((e.get("date") or "") > researched_on(th) for e in (mem.get(s) or {}).get("events", []))
    for s, th in theses.items():  # watch: inspection observations (VAI, Form 483), court / tax / pollution board orders
        evs = [e for e in (mem.get(s) or {}).get("events", []) if e["sev"] == "watch" and new_since(e, th)]
        if evs:
            q(s, "possible bad news filed since the last research (inspection observations, court, tax or pollution board order): "
                 "open the filing, check kill switches and the thesis", "recheck", {"events": evs[:5]})
    for s, th in theses.items():
        evs = [e for e in (mem.get(s) or {}).get("events", []) if e["sev"] == "green" and (e.get("date") or "") > researched_on(th)]
        if evs:
            q(s, "new announcement since the last research (order, capacity, approval or corporate action): update triggers", "recheck", {"events": evs[:5]})
        d = px.get(s)
        if d is not None and len(d) > 11:
            c = d["Close"]
            r1, r10 = float(c.iloc[-1] / c.iloc[-2] - 1) * 100, float(c.iloc[-1] / c.iloc[-11] - 1) * 100
            if (r1 <= -10 or r10 <= -20) and (s in od_syms or new_docs(s) or evs_any(s, th)):  # a shock with nothing filed has nothing to check
                q(s, f"price shock ({r1:+.1f}% today, {r10:+.1f}% in 10 sessions): look for a filed reason", "recheck")
    # decision-first: stocks that would be Buy-rated if a verified forward driver existed, then flagged filings to review,
    # then the rest of the funnel by priority (each gets a pack prepared by narrativ.packs)
    def has_driver(s):
        th = theses.get(s) or {}
        return bool((th.get("scan_raw") or {}).get("guidance") or (th.get("scan_raw") or {}).get("order_book") or th.get("drivers")
                    or any(p.get("status") == "pending" for p in th.get("promises", [])))
    def fresh(s):  # researched recently: an enrich now would mostly re-read the same documents
        th = theses.get(s) or raw_theses.get(s) or {}
        r = researched_on(th)
        return r > "2000" and (today - date.fromisoformat(r)).days < config.RECENT_RESEARCH_DAYS
    n_enrich = [0]
    def enrich(s, why):
        if n_enrich[0] < config.ENRICH_PER_DAY and not fresh(s) and s not in seen:
            n_enrich[0] += 1
            q(s, why, "enrich")
    near = [s for s in top if not has_driver(s) and all(0 < ev[s]["L"][k]["t"] <= 3 for k in ("surv", "qual", "val"))]
    near.sort(key=lambda s: not (fwd.get(s) or {}).get("dated"))  # stable: the free readers found a dated row -> first, then priority
    for s in near:
        enrich(s, f"one forward driver away from a Buy/Hold call (priority {ev[s]['pr']})")
    for s, gp in odp["gaps"][:config.GAP_ENRICH_PER_DAY]:  # scan items with no quote / source / due date: only Claude can fill them
        q(s, OD.gap_reason(gp), "enrich", {"scan_gaps": gp[:8]})
    for s in top:
        fl = [k for k, v in (annc.get(s) or {}).items() if v and v[0] == 1 and k in ("A2", "A4", "G2")
              and k not in ((theses.get(s) or {}).get("flag_reviews") or {})]
        if fl:
            q(s, f"subject-line red flag(s) {', '.join(fl)}: open the filing, confirm or dismiss", "review_flag", {"flags": fl})
    for s in top:
        if not has_driver(s):
            enrich(s, f"no forward driver yet (priority {ev[s]['pr']})")
    for s, th in theses.items():
        u = th.get("updated")
        if u and (today - date.fromisoformat(u)).days > config.THESIS_STALE_DAYS and (s in od_syms or new_docs(s) or evs_any(s, th)):
            q(s, "thesis older than 90 days and something new is filed", "recheck")
    gap_of = dict(odp["gaps"])
    for x in queue:  # every queued stock carries its scan gaps into the pack
        if x["symbol"] in gap_of and "scan_gaps" not in x:
            x["scan_gaps"] = gap_of[x["symbol"]][:8]
    queued = {x["symbol"] for x in queue if x["task"] in ("scan", "triage", "enrich", "review_flag", "audit", "review")} | set(req_syms)
    qpos = {x["symbol"]: i + 1 for i, x in reversed(list(enumerate(queue)))}
    for s in syms:  # Not rated: name the gap (filed data, research not done yet, or researched without a driver)
        if dec[s]["d"] == "Not rated":
            dec[s]["missing"] = [FN.not_rated_reason(ev[s]["L"], ev[s]["vd"], theses.get(s), qpos.get(s), len(queue), rank_of.get(s), len(syms),
                                                     s in req_syms)] + [m for m in dec[s].get("missing", []) if not m.startswith("No verified forward driver")]

    # ---------- Decision view: Strong Buy .. Strong Sell, rule-built from levels + verified research ----------
    print(f"[run] decisions {pd.Series([d['d'] for d in dec.values()]).value_counts().to_dict()}")
    if not limit:
        try:
            from narrativ import packs
            for x in queue:  # every pack says whether the latest call is in it (idea 1)
                call_of(x["symbol"])
            packs.build(queue, today, ann_st, ex, dec, ev, mx, annc, theses, mem, MX.val, aflags, calls=calls)
            packs.doc_index(syms, ann_st, ex, today, rank_of, queue)  # what the free readers read next (narrativ/reader.py)
            pk = [json.loads(f.read_text()) for f in (OUT / "packs").glob("*.json")]
            dd = [d for x in pk for d in x.get("documents", [])]
            lc = [x.get("latest_call") or {} for x in pk if x.get("task") in ("review", "audit")]
            H.source("latest call in review packs", reviews=len(lc), in_pack=sum(1 for c in lc if c.get("in_pack")),
                     from_alphastreet=sum(1 for c in lc if c.get("fallback") == "alphastreet"),
                     found_not_readable=sum(1 for c in lc if c.get("state") == "found" and not c.get("in_pack")),
                     missing=sum(1 for c in lc if c.get("state") == "missing"), no_filed_quarter=sum(1 for x in pk if x.get("task") in ("review", "audit") and not x.get("latest_call")),
                     waiting=len(waits), stale_reviews=sum(1 for s in syms if any("latest earnings call was available" in str(m) for m in dec[s].get("missing") or [])))
            H.source("research packs", packs=len(pk), with_transcript=sum(1 for x in pk if any(d.get("kind") == "transcript" for d in x.get("documents", []))),
                     no_call=sum(1 for x in pk if x.get("no_call_note")), documents=len(dd),
                     poor_text=sum(1 for d in dd if (d.get("quality") or {}).get("grade") == "poor"),
                     weak_text=sum(1 for d in dd if (d.get("quality") or {}).get("grade") == "weak"))
        except Exception as e:  # noqa: BLE001
            print(f"[packs] failed: {e}")

    # ---------- Market mood (replaces RISK ON / CAUTION / RISK OFF) ----------
    try:
        md = mood.compute(px, bench_close, today)
    except Exception as e:  # noqa: BLE001
        print(f"[run] mood failed: {e}")
        md = {}
    try:  # foreign investors' equity flows with history since 2002 (narrativ/nsdl.py): shown with the mood, not scored yet
        from narrativ import nsdl as NS
        fp = NS.summary(NS.refresh(today), today)
        if fp and isinstance(md, dict):
            md["fpi_nsdl"] = fp
        H.source("FPI flows (NSDL)", months=(fp or {}).get("months"), days=(fp or {}).get("days"), last_month=(fp or {}).get("month"))
    except Exception as e:  # noqa: BLE001
        print(f"[nsdl] failed: {e}")
    nifty_ok = bool(len(bench_close) > 200 and bench_close.iloc[-1] > bench_close.rolling(200).mean().iloc[-1])
    breadth = float(sum(1 for t in tech.values() if (t.get("dist200_pct") or 0) > 0) / len(tech)) if tech else 0.0  # own prices
    regime = "RISK ON" if nifty_ok and breadth >= 0.5 else "CAUTION" if nifty_ok or breadth >= 0.4 else "RISK OFF"

    # ---------- Outputs ----------
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    passed = [sum(1 for s in syms if not ev[s]["out"] or ev[s]["out"][0] > i) for i in range(1, 8)]
    funnel = {"listed": stats["raw"], "companies": len(syms), "levels": passed, "researched": sum(1 for s in theses if s in ev),
              "decisions": pd.Series([dec[s]["d"] for s in syms]).value_counts().to_dict(),
              "queue": len(queue), "verdicts": pd.Series([ev[s]["vd"] for s in syms]).value_counts().to_dict()}
    # Conviction (narrativ/conviction.py, RULES.md "Conviction"): how much verified evidence stands behind each verified
    # Buy. Computed after the decision and the gates; it never changes a decision.
    conv = {}
    try:
        from narrativ import conviction as CV
        fwd_rows = json.loads((OUT / "forward.json").read_text()).get("stocks", {}) if (OUT / "forward.json").exists() else {}
        di = (json.loads((OUT / "data_issues.json").read_text()).get("issues") or {}) if (OUT / "data_issues.json").exists() else {}
        for s in syms:
            if dec[s].get("d") in ("Buy", "Strong Buy"):
                th = theses.get(s) or {}
                c = CV.assess(dec[s], ev[s]["L"], ev[s]["setup"], th, mx.get(s), today,
                              shp=(ext(s) or {}).get("shp"), reader=fwd_rows.get(s), lender=ev[s]["lender"],
                              open_issues=sum(1 for x in di.values() if x.get("symbol") == s and x.get("status") == "open"))
                if c:
                    conv[s] = c
        print(f"[conviction] {pd.Series([c['level'] for c in conv.values()]).value_counts().to_dict() if conv else 'no verified Buys'}")
    except Exception as e:  # noqa: BLE001  conviction must not stop the daily run
        print(f"[conviction] failed: {e}")
    picks, detail_syms = [], set(infunnel) | set(theses) | set(req_syms)
    for s in sorted(syms, key=lambda s: -ev[s]["pr"]):
        e, b = ev[s], s0i.loc[s]
        code, exch = code_of(s)
        name = b["longName"] if b["longName"] == b["longName"] else b["shortName"]
        t = tech.get(s) or {}
        lv = FN.compact(e["L"])
        row = {"s": s, "c": code, "x": exch, "n": name, "i": b["industry"] if b["industry"] == b["industry"] else None,
               "sec": b["sector"], "p": price_of(s), "d1": t.get("chg_1d"), "mc": MX.val(mx[s], "mcap_cr"),
               "t": [lv[k]["t"] for k in FN.LEVELS], "sc": [lv[k].get("s") for k in FN.LEVELS], "vd": e["vd"], "pr": e["pr"], "dc": dec[s]["d"], "vf": dec[s].get("verified"), "cand": dec[s].get("candidate"), "rk": rank_of.get(s), "mb": mb_of.get(s) or None,
               "af": len(aflags.get(s) or []) or None, "cv": (conv.get(s) or {}).get("level")}
        ld = s0i.loc[s, "listed"] if "listed" in s0i.columns else None
        if isinstance(ld, str) and ld and (today - date.fromisoformat(ld)).days <= 365:
            row["ld"] = ld  # listed in the last 12 months (NSE equity list): Recent IPOs on Home
        if lv["qual"].get("turn"):
            row["turn"] = True
        if lv["mom"].get("ext"):
            row["ext"] = True
        # Beaten-up quality (feedback #19): quality tier 1-2, >= 40% below the 52-week high, turning (back above the 50-day average)
        px_, hi_, ma50 = t.get("price"), t.get("hi52"), t.get("sma50")
        if not e["out"] and e["L"]["qual"]["t"] in (1, 2) and px_ and hi_ and ma50 and px_ <= 0.6 * hi_ and px_ > ma50:
            row["bq"] = round((1 - px_ / hi_) * 100)
        gn = {k: e["L"][k]["name"] for k in FN.LEVELS if e["L"][k]["t"] == 0 and e["L"][k]["name"] != "Not enough data"}
        if gn:
            row["gn"] = gn
        if e["out"]:
            row["out"] = {"l": e["out"][0], "w": e["out"][1]}
        else:
            row["why"] = next((lv[k].get("w") for k in ("out", "qual", "val", "mom") if lv[k].get("w") and lv[k]["t"]), None)
            row["su"] = e["setup"]["type"]
            if str(e["setup"].get("note") or "").startswith("No entry: trend broken"):
                row["tb"] = 1  # app: "Avoid · trend broken" in lists, same as the Plan card
            row["bt"] = e["L"]["val"].get("type")
            if e["an"]:
                row["up"] = e["an"]["upside"]
                row["na"] = e["an"]["n"]
            if s in px:
                c = px[s]["Close"].iloc[-60:]
                row["sp"] = [round(float(x), 2) for x in c.iloc[::2]]
        if s in theses:
            row["r"] = True
        row["ss"] = scan_state(s, theses.get(s) or {}, today, queued, (mem.get(s) or {}).get("checkpoints", []))["state"]
        if (mem.get(s) or {}).get("checkpoints"):
            due = [c for c in mem[s]["checkpoints"] if c["status"] in ("open", "due")]
            if due:
                row["cp"] = [{k: c.get(k) for k in ("type", "due", "what", "status")} for c in due[:3]]
        row["tags"] = list(b["tags"])[:4]
        picks.append(FN.clean(row))

    (OUT / "picks.json").write_text(json.dumps({"v": 2, "updated": now, "date": str(today), "mood": md,
        "regime": {"label": regime, "nifty_above_200dma": nifty_ok, "breadth_pct": round(breadth * 100, 1)},
        "funnel": funnel, "tiers": FN.TIERS, "level_names": FN.LEVEL_NAMES, "top10": PF.top10(picks), "picks": picks}, separators=(",", ":"), ensure_ascii=False))
    (OUT / "queue.json").write_text(json.dumps({"date": str(today), "items": queue}, indent=1, ensure_ascii=False))
    (OUT / "funnel.json").write_text(json.dumps({"date": str(today), "funnel": funnel,
        "removed_by": {FN.LEVEL_NAMES[FN.LEVELS[i]]: sum(1 for s in syms if ev[s]["out"] and ev[s]["out"][0] == i + 1) for i in range(7)},
        "industry": {k: v for k, v in istats.items() if v}}, separators=(",", ":"), ensure_ascii=False))
    (OUT / "memory.json").write_text(json.dumps({"date": str(today), "stocks": [
        {"symbol": s, "name": r["name"], "status": r["status"], "first_seen": r["first_seen"], "drop_reason": r.get("drop_reason"),
         "health": M.thesis_health(r), "checkpoints": [c for c in r.get("checkpoints", []) if c["status"] in ("open", "due")],
         "verdicts": (r.get("verdicts") or [])[-3:]}
        for s, r in sorted(M.all_records().items())]}, separators=(",", ":"), ensure_ascii=False))

    # ---------- Rotation (Money Movement) ----------
    best = {}
    for ind, r in rot_ind.items():
        if r["q"] not in ("Leading", "Improving"):
            continue
        cand = [s for s in infunnel if ind_of.get(s) == ind and ev[s]["L"]["val"]["t"] in (1, 2, 3) and ev[s]["setup"]["type"] in ("Breakout", "Pullback", "Base")]
        best[ind] = sorted(cand, key=lambda s: -ev[s]["pr"])[:3]
    (OUT / "rotation.json").write_text(json.dumps({"date": str(today), "bench": "Nifty 500", "ind_bench": "our universe (equal-weight)",
                                                   "sectors": rot_sec, "industries": rot_ind, "best": best}, separators=(",", ":"), ensure_ascii=False))

    # ---------- Per-stock detail: levels, formulas, setup, flow ----------
    fin_dir = OUT / "fin"
    fin_dir.mkdir(exist_ok=True)
    audit, details = [], {}
    try:
        from narrativ import researchlog
        rlog = researchlog.update(raw_theses)
    except Exception as e:  # noqa: BLE001
        print(f"[researchlog] failed: {e}")
        rlog = {}

    def uniq_events(evs):  # NSE and BSE copies of the same filing appear twice
        seen, out = set(), []
        for x in evs:
            k = (x.get("date"), x.get("category"), x.get("text"))
            if k not in seen:
                seen.add(k); out.append(x)
        return out
    try:  # commodity prices that move each industry (narrativ/commodities.py): context on the dossier, not a rule
        from narrativ import commodities as CM
        cm = CM.refresh(today)
        H.source("commodity prices", month=(cm or {}).get("month"), series=len((cm or {}).get("series") or {}),
                 industries=len((cm or {}).get("industries") or {}), missing=len((cm or {}).get("missing_series") or []))
    except Exception as e:  # noqa: BLE001
        print(f"[commodities] failed: {e}")
        CM, cm = None, None
    basic_of = s0i["basic_industry"].to_dict() if "basic_industry" in s0i.columns else {}
    try:  # the app's 'Latest call' card (AlphaBrief of the latest call): queue, Buys and candidates daily, the rest in turn
        cards = AS.refresh_cards([x["symbol"] for x in queue] + [s for s in syms if dec[s].get("d") in ("Buy", "Strong Buy") or dec[s].get("candidate")],
                                 [s for s in sorted(syms, key=lambda s: rank_of.get(s, 10 ** 9)) if s.endswith(".NS")], today)
        H.source("call cards (AlphaStreet)", stored=len(cards))
    except Exception as e:  # noqa: BLE001
        print(f"[alphastreet] cards failed: {e}")
        cards = {}
    try:  # news headlines (publisher RSS, collected every 2 hours by news.yml) and the industry packs for Claude's reasons
        from narrativ import news as NW
        since30 = str(today - timedelta(days=30))
        facts = {}
        for ind_, r_ in rot_ind.items():
            if r_.get("q") not in ("Leading", "Improving"):
                continue
            mem_ = [x for x in syms if ind_of.get(x) == ind_]
            grow = [x for x in mem_ if (mx[x].get("rev_yoy_pct") or {}).get("v") is not None]
            orders, urls = [], []
            for x in mem_:
                try:
                    for e_ in ANN.recent_events(bse_ann if x.endswith(".BO") else ann_st, x, limit=None):
                        if str(e_.get("date") or "") >= since30 and re.search(r"order|contract|award", str(e_.get("type") or ""), re.I):
                            orders.append(x); urls.append(e_.get("url"))
                            break
                except Exception:  # noqa: BLE001
                    pass
            ups = [x for x in mem_ if any(a.get("action") == "Upgrade" and str(a.get("date") or "") >= since30 for a in (rat.get(x) or {}).get("actions") or [])]
            comm = {}
            for x in mem_:
                for c_ in (CM.for_industry(cm, basic_of.get(x)) if CM else None) or []:
                    comm[c_["series"]] = c_
            facts[ind_] = {"members": len(mem_), "rev_growth_over_10pct": sum(1 for x in grow if mx[x]["rev_yoy_pct"]["v"] > 10), "rev_reported": len(grow),
                           "above_200_day": sum(1 for x in mem_ if ((tech.get(x) or {}).get("dist200_pct") or -1) > 0),
                           "order_wins_30d": sorted(set(orders)), "rating_upgrades_30d": ups, "commodities": list(comm.values()), "urls": [u for u in urls if u]}
        news_of = NW.build([{"s": p_["s"], "n": p_.get("n"), "i": p_.get("i")} for p_ in picks], {"industries": rot_ind}, None, today, facts)
        H.source("news headlines", stocks=len(news_of), headlines=sum(len(v) for v in news_of.values()), industry_packs=len(facts))
    except Exception as e:  # noqa: BLE001
        print(f"[news] failed: {e}")
        news_of = {}
    from narrativ import story as ST
    pick_of = {r_["s"]: r_ for r_ in picks}
    fwd_st = (json.loads((OUT / "forward.json").read_text()) if (OUT / "forward.json").exists() else {}).get("stocks", {})
    story_st = ST._load()
    H.source("Narrativ sheets", plain_written=len(story_st.get("stocks") or {}), held=len(story_st.get("held") or {}))
    for s in syms:
        if s not in detail_syms:
            continue
        e, Mx, f, t = ev[s], mx[s], fund.get(s) or {}, tech.get(s) or {}
        bd = (bulk.get(s) or [])[:5]
        det = {"metrics": Mx, "analyst": e["an"], "broker_targets": named_of.get(s), "levels": e["L"], "verdict": e["vd"], "decision": dec[s], "audit_flags": aflags.get(s) or None,
               "conviction": conv.get(s), "u1": (lambda u: {"ok": u[0], "v": u[1]} if u[0] is not None else None)(u1_of.get(s) or (None, None)), "commodity": CM.for_industry(cm, basic_of.get(s)) if CM else None,
               "ratings": rat.get(s), "insolvency": ins.get(s), "latest_call_card": cards.get(s), "news": news_of.get(s),
               "statement": FN.statement(e["vd"], e["L"]) if not e["out"] else f"Removed at L{e['out'][0]} {FN.LEVEL_NAMES[FN.LEVELS[e['out'][0] - 1]]}: {e['out'][1]}.",
               "standouts": standouts(e["L"]), "setup": e["setup"], "hist": [{k: (round(x, 2) if isinstance(x, float) else x) for k, x in h.items()} for h in e["hist"]],
               "scan": scan_state(s, theses.get(s) or {}, today, queued, (mem.get(s) or {}).get("checkpoints", [])),
               "verdict_log": (mem.get(s) or {}).get("verdicts") or [], "research_log": rlog.get(s) or None,
               "stock": {"stage": t.get("stage"), "status": t.get("status"), "bands": FN.bands(e["setup"], price_of(s)), "ret_3m": t.get("ret_3m"), "ret_6m": t.get("ret_6m"),
                         "hi52": t.get("hi52"), "lo52": t.get("lo52"), "dist200": t.get("dist200_pct"), "rs_pct": round(float(rs_all[s]) * 100) if s in rs_all.index else None,
                         "traded_value_cr": t.get("traded_value_cr"), "ind_pe": num(ind_pe.get(ind_of.get(s)), 1), "kind": Mx.get("kind"),
                         "promoter": prom_hist(s), "inst_pct": num(f["heldPercentInstitutions"] * 100, 1) if f.get("heldPercentInstitutions") is not None else None,
                         "analysts": f.get("numberOfAnalystOpinions"), "summary": f.get("longBusinessSummary"), "website": f.get("website"),
                         "next_results": cal.get(s), "bulk_deals": bd, "exchange": {k: x for k, x in (ex.get(s) or {}).items() if k != "events"},
                         "events": uniq_events((mem.get(s) or {}).get("events") or (ex.get(s) or {}).get("events") or [])[:60], "tags": list(s0i.loc[s, "tags"]),
                         "industry": ind_of.get(s), "rotation": (rot_ind.get(ind_of.get(s)) or {}).get("q"), "lender": e["lender"]}}
        try:  # the app's Narrativ sheet (narrativ/story.py): plain-words story, model text only where it passed the checks
            det["narrativ"] = ST.sheet(s, pick_of.get(s) or {}, Mx, det["stock"].get("summary"), theses, fwd_st, story_st)
        except Exception as e_:  # noqa: BLE001
            print(f"[story] {s}: {e_}")
        details[s] = FN.clean(det)
        write_if_changed(fin_dir / f"{s}.json", json.dumps(details[s], separators=(",", ":"), ensure_ascii=False))
        ype, ope = f.get("trailingPE"), MX.val(Mx, "pe")
        if ype and ope and abs(ope / ype - 1) > 0.15:
            audit.append({"s": s, "metric": "P/E", "ours": ope, "yahoo": round(ype, 1), "src": Mx.get("source")})
    prune(fin_dir, {f"{s}.json" for s in details})  # only stocks that dropped out of today's detail set are removed
    (OUT / "source_audit.json").write_text(json.dumps({"date": str(today), "note": "Our computed value vs Yahoo's ratio; Yahoo is never shown",
                                                       "items": audit}, separators=(",", ":"), ensure_ascii=False))

    charts = OUT / "charts"
    charts.mkdir(exist_ok=True)
    chart_files = set()
    for s in detail_syms:
        full = px.get(s)
        if full is None:
            continue
        d = full.iloc[-260:]
        rec = {"c": [round(float(x), 2) for x in d["Close"]], "d0": str(d.index[0].date()),
               "sma50": [num(x) for x in full["Close"].rolling(50).mean().reindex(d.index)],
               "sma200": [num(x) for x in full["Close"].rolling(200).mean().reindex(d.index)]}
        write_if_changed(charts / f"{s}.json", json.dumps(rec, separators=(",", ":")))
        chart_files.add(f"{s}.json")
    prune(charts, chart_files)

    if not limit:  # NSE trading holidays (docs/data/holidays.json): the exchange's own list only; kept as is when NSE is unreachable
        try:
            from narrativ import holidays
            holidays.update(today)
        except Exception as e:  # noqa: BLE001
            print(f"[holidays] failed: {e}")
    H.mark("funnel, research view, app files")
    alerts.send([p for p in picks if not p.get("out")][:60], newly_due_all, changes, new_events)
    if not limit:  # D1 tables + R2 files (git JSON above stays the fallback during the switch-over)
        try:
            isin_of = {s: s0i.loc[s, "isin"] for s in syms if "isin" in s0i.columns and isinstance(s0i.loc[s, "isin"], str)}
            mcap_of = {s: float(s0i.loc[s, "mcap_cr"]) for s in syms if "mcap_cr" in s0i.columns and pd.notna(s0i.loc[s, "mcap_cr"])}
            mom_of = {p["s"]: (p.get("sc") or [None] * 7)[FN.LEVELS.index("mom")] for p in picks if p.get("s")}
            dbsync.sync(today, s0i, btypes, {s: ev[s]["lscore"] for s in syms}, picks, details, fins, M.all_records(), theses, md, ann_st,
                        {"universe": len(syms), "in_funnel": len(infunnel)}, breadth_in=(px, isin_of, mcap_of, mom_of))
        except Exception as e:  # noqa: BLE001
            print(f"[store] sync failed: {e}")
    H.mark("database sync")
    H.source("research", researched=len(theses), queue=len(queue))
    if not limit:  # scan requests Claude has worked on since they were made: comment and close the issue (needs issues: write)
        H.source("scan requests closed", closed=len(scan_requests.close_done(requested, raw_theses)))
    try:  # the loop's scorecard: did verified calls make money (vs the rule candidates and the Nifty)?
        from narrativ import calls as CALLS
        cl = CALLS.update(dec, px, bench_close, theses, today, {s: (ev[s]["setup"] or {}).get("stop") for s in syms},
                          {s: c["level"] for s, c in conv.items()})
        H.source("calls", open=cl["open"], verified_3m=(cl["summary"]["verified"]["3m"] or {}).get("avg_vs_nifty"))
    except Exception as e:  # noqa: BLE001
        print(f"[calls] failed: {e}")
        cl = None
    try:  # RULES.md scorecard + lessons (the rules themselves change only through a merged pull request)
        from narrativ import rules as RULES
        held = sorted(s.split(".")[0] for s, d in dec.items() if d.get("gates"))
        RULES.update(today, gate_n, held, funnel.get("decisions") or {}, cl)
    except Exception as e:  # noqa: BLE001
        print(f"[rules] failed: {e}")
    H.write(today, details, {"universe": len(syms), "in_funnel": len(infunnel), "decisions": funnel.get("decisions")})
    print(f"[run] funnel {funnel} mood {md.get('score')} {md.get('zone')} queue {[x['symbol'] for x in queue]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="cap the universe (testing)")
    main(ap.parse_args().limit)
