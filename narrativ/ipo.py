"""Open-IPO check without Claude (owner decision 2026-11-23; rules backtested on 223 IPOs, KNOWLEDGE.md).

Runs at 08:30 and 15:30 IST on weekdays (Cloudflare Worker cron -> .github/workflow-src/ipo.yml) and writes
docs/data/ipo_today.json for the app (Home -> Open IPOs and the IPO screen).

Sources (public pages only; robots.txt allows them):
  IPO Watch GMP page      every IPO in the window: board, status, band, lot, size, dates, listing date, GMP
  IPO Watch IPO page      GMP history, category subscription by day, fresh issue / offer for sale
  ipomarket.in GMP page   second GMP source
  NSE ipo-current-issue / ipo-active-category   live category subscription when NSE answers (fallback: IPO Watch)

Calls: APPLY when every rule passes (any day); WAIT before the final day otherwise; AVOID on the final day when a rule
fails, or earlier when GMP has collapsed. Rules (same for Mainboard and SME unless stated):
  G1 GMP >= 20% of the upper band (the lower of the two sources, seen today)
  G2 GMP >= 80% of its highest since the issue opened
  S1 QIB >= 1x (skipped for issues with no QIB portion)
  S2 overall >= 2x Mainboard, >= 20x SME
  S3 Mainboard: QIB >= half of retail
"""
import html as H
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

IST = timezone(timedelta(hours=5, minutes=30))
OUT = Path("docs/data/ipo_today.json")
HIST = Path("docs/data/ipo_history.json")  # per IPO: subscription and GMP seen at each check (day-by-day columns)
IW = "https://ipowatch.in"
IW_GMP = IW + "/ipo-grey-market-premium-latest-ipo-gmp/"
IM_GMP = "https://www.ipomarket.in/gmp"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}
GMP_MIN, PEAK_MIN, QIB_MIN, MAIN_TOTAL, SME_TOTAL, COLLAPSE = 20.0, 0.8, 1.0, 2.0, 20.0, 5.0
CATS = (("qib", re.compile(r"qualified|qib", re.I)), ("nii", re.compile(r"non.?institutional|nii|hni", re.I)),
        ("retail", re.compile(r"retail|rii|individual", re.I)), ("overall", re.compile(r"^total|overall", re.I)))


def _nnum(x):
    try:
        return float(str(x).replace(",", "").replace("x", "").strip())
    except (TypeError, ValueError):
        return None


def _times(row: dict):
    """Times subscribed from one category row: a 'times' field when present, else bids / shares offered."""
    for k, v in row.items():
        if re.search(r"time", k, re.I) and _nnum(v) is not None:
            return round(_nnum(v), 2)
    bid = next((_nnum(v) for k, v in row.items() if re.search(r"bid", k, re.I) and _nnum(v)), None)
    off = next((_nnum(v) for k, v in row.items() if re.search(r"offer|reserv", k, re.I) and _nnum(v)), None)
    return round(bid / off, 2) if bid and off else None


def parse_nse(x) -> dict:
    rows = x if isinstance(x, list) else next((v for v in (x or {}).values() if isinstance(v, list)), [])
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        label = str(next((v for k, v in r.items() if re.search(r"categ", k, re.I)), "")).strip()
        for key, rx in CATS:
            if key not in out and rx.search(label):
                t = _times(r)
                if t is not None:
                    out[key] = t
                break
    return out


RULES = [("G1", "GMP ≥ 20%"), ("G2", "GMP ≥ 80% of peak"), ("S1", "QIB ≥ 1×"), ("S2", "Overall ≥ {t}×"), ("S3", "QIB ≥ ½ retail")]


def _get(url: str, tries: int = 3) -> str | None:
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.ok:
                return r.text
            if r.status_code in (429, 502, 503):
                time.sleep(20 * (i + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(5 * (i + 1))
    return None


def _num(x):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x))) if x is not None and re.search(r"\d", str(x)) else None
    except ValueError:
        return None


def _day(s) -> str | None:
    """'19 Nov 2026' / '2026-11-27T00:00:00' -> '2026-11-19'."""
    if not s:
        return None
    s = str(s)
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _norm(s: str) -> str:
    s = re.sub(r"\b(limited|ltd|ipo|the|and|india|private|pvt)\b", " ", (s or "").lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]", "", s)


def _page_data(text: str) -> str:
    return text.replace('\\"', '"').replace("\\\\", "\\")


def iw_list(text: str) -> list[dict]:
    """IPO objects embedded in the IPO Watch GMP page."""
    u = _page_data(text)
    out = []
    for o in re.findall(r'\{"id":\d+,"slug":"[^"]+-ipo-details".*?"listPrice":[^,}]+\}', u):
        try:
            out.append(json.loads(o))
        except json.JSONDecodeError:
            continue
    seen, uniq = set(), []
    for o in out:
        if o["slug"] not in seen:
            seen.add(o["slug"]); uniq.append(o)
    return uniq


def _arr(u: str, key: str):
    i = u.find(f'"{key}":[')
    if i < 0:
        return None
    j = u.index("[", i); d = 0
    for k in range(j, len(u)):
        if u[k] == "[":
            d += 1
        elif u[k] == "]":
            d -= 1
            if d == 0:
                try:
                    return json.loads(u[j:k + 1])
                except json.JSONDecodeError:
                    return None
    return None


def iw_detail(text: str) -> dict:
    """GMP history, subscription by category and day, fresh / OFS (₹ cr), exchanges, from one IPO Watch IPO page."""
    u = _page_data(text)
    out = {"gmp_history": [], "subs": {}}
    for h in _arr(u, "gmpHistory") or []:
        if h.get("gmp") is not None and h.get("date"):
            out["gmp_history"].append([h["date"][:16], float(h["gmp"])])
    out["gmp_history"].sort()
    for s in _arr(u, "subscriptions") or []:
        d, c, v = s.get("subscriptionDate"), (s.get("categoryName") or "").lower(), _num(s.get("subscriptionValue"))
        if not d or v is None:
            continue
        key = "qib" if c.startswith("qib") else "nii" if c.startswith("nii") else "retail" if c.startswith(("retail", "individual", "rii")) \
            else "overall" if c.startswith(("total", "overall")) else None
        if key:
            out["subs"].setdefault(d[:10], {})[key] = v
    txt = H.unescape(re.sub(r"<[^>]+>", " ", text))
    for key, lab in (("fresh_cr", r"Fresh Issue"), ("ofs_cr", r"Offer for Sale")):
        m = re.search(lab + r"\s+(?:Approx\s+)?([\d,.]+)\s*Cr", txt)
        out[key] = _num(m.group(1)) if m else None
    m = re.search(r"Listing At\s+([A-Za-z &;]+?)\s{2,}", txt)
    out["exchanges"] = m.group(1).strip() if m else None
    out["has_qib"] = bool(re.search(r'"categoryName":"QIB', u)) or bool(re.search(r">\s*QIB\s*<", text))
    return out


def im_gmp(text: str) -> dict:
    """ipomarket.in GMP table: normalised name -> GMP in ₹."""
    out = {}
    for t in re.findall(r"<table.*?</table>", text or "", re.S):
        for r in re.findall(r"<tr.*?</tr>", t, re.S):
            c = [H.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[hd].*?</t[hd]>", r, re.S)]
            if len(c) >= 4 and c[0] and not c[0].lower().startswith("company"):
                g = _num(c[3])
                if g is not None:
                    out[_norm(c[0])] = g
    return out


def nse_subscription(names: dict) -> dict:
    """{iw slug: {qib, nii, retail, overall, symbol}} from NSE for IPOs it lists; {} when NSE does not answer."""
    try:
        from .filings import NSESession
        ns = NSESession()
        cur = ns.get("https://www.nseindia.com/api/ipo-current-issue")
    except Exception as e:  # noqa: BLE001
        print(f"[ipo] NSE unavailable: {e}")
        return {}
    rows = cur if isinstance(cur, list) else (cur or {}).get("data") or []
    out = {}
    for r in rows:
        sym, nm = r.get("symbol"), _norm(r.get("companyName") or r.get("company") or "")
        slug = next((s for s, n in names.items() if nm and (nm.startswith(n[:10]) or n.startswith(nm[:10]))), None)
        if not sym or not slug:
            continue
        sub = parse_nse(ns.get("https://www.nseindia.com/api/ipo-active-category", params={"symbol": sym}))
        if sub:
            out[slug] = {**sub, "symbol": sym}
    return out


def evaluate(i: dict, today: str, final: bool) -> tuple[str, list]:
    """-> (call, rules [{id, n, ok, v}]). ok None = cannot be checked yet."""
    sme = i["board"] == "SME"
    gp = i.get("gmp_pct")
    sb = i.get("subscription") or {}
    q, r, t = sb.get("qib"), sb.get("retail"), sb.get("overall")
    tot = SME_TOTAL if sme else MAIN_TOTAL
    rules = []
    fresh = (i.get("gmp_observed") or "").startswith(today)
    rules.append({"id": "G1", "n": "GMP ≥ 20%", "ok": None if gp is None else (gp >= GMP_MIN and fresh),
                  "v": None if gp is None else f"{gp:.1f}%" + ("" if fresh else " (not today)")})
    pk = i.get("gmp_peak")
    g = i.get("gmp_high")
    ratio = (g / pk) if (g is not None and pk) else None
    rules.append({"id": "G2", "n": "GMP ≥ 80% of peak", "ok": None if g is None else (True if not pk else ratio >= PEAK_MIN),
                  "v": None if ratio is None else f"{ratio * 100:.0f}%"})
    if i.get("has_qib", True):
        rules.append({"id": "S1", "n": "QIB ≥ 1×", "ok": None if q is None else q >= QIB_MIN, "v": None if q is None else f"{q:.1f}×"})
    rules.append({"id": "S2", "n": f"Overall ≥ {tot:g}×", "ok": None if t is None else t >= tot, "v": None if t is None else f"{t:.1f}×"})
    if not sme:
        rules.append({"id": "S3", "n": "QIB ≥ ½ retail", "ok": None if (q is None or not r) else q >= 0.5 * r,
                      "v": None if (q is None or r is None) else f"{q:.1f} / {r:.1f}"})
    oks = [x["ok"] for x in rules]
    if all(o is True for o in oks):
        return "APPLY", rules
    if final or (gp is not None and fresh and gp < COLLAPSE):
        return "AVOID", rules
    return "WAIT", rules


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    today, slot = now.date().isoformat(), ("am" if now.hour < 12 else "pm")
    text = _get(IW_GMP)
    if not text:
        raise RuntimeError("IPO Watch GMP page unavailable")
    lst = iw_list(text)
    im = im_gmp(_get(IM_GMP) or "")
    hist = json.loads(HIST.read_text()) if HIST.exists() else {}
    actionable, upcoming = [], []
    open_ = [o for o in lst if (_day(o.get("openDate")) or "9") <= today <= (_day(o.get("closeDate")) or "0")]
    nse = nse_subscription({o["slug"]: _norm(o["name"]) for o in open_}) if open_ else {}
    for o in lst:
        od, cd = _day(o.get("openDate")), _day(o.get("closeDate"))
        board = "Mainboard" if (o.get("type") or "").lower() == "mainboard" else "SME"
        up = _num(o.get("issuePrice"))
        lo_hi = [_num(x) for x in re.findall(r"[\d,.]+", (o.get("priceBand") or "").replace(",", ""))]
        if od and od > today:
            if len(upcoming) < 8:
                upcoming.append({"name": o["name"], "board": board, "open_date": od, "last_date": cd,
                                 "price_low": lo_hi[0] if lo_hi else None, "price_high": up, "gmp": None if o.get("gmp") is None else f"₹{o['gmp']:g}",
                                 "gmp_observed": None, "note": None, "source": f"{IW}/{o['slug']}/"})
            continue
        if not od or not cd or not (od <= today <= cd):
            continue
        dt = iw_detail(_get(f"{IW}/{o['slug']}/") or "")
        time.sleep(2)
        g1 = _num(o.get("gmp"))
        g2 = im.get(_norm(o["name"]))
        if g2 is None:
            g2 = next((v for k, v in im.items() if k[:10] and _norm(o["name"]).startswith(k[:10])), None)
        gs = [g for g in (g1, g2) if g is not None]
        gmp = min(gs) if gs else None
        since = [g for d, g in dt["gmp_history"] if d[:10] >= od] + gs
        days_all = [od]
        d0 = date.fromisoformat(od)
        # trading days of the issue: weekdays from open to close (exchange holidays are rare inside an issue)
        x = d0
        while x.isoformat() < cd:
            x += timedelta(days=1)
            if x.weekday() < 5:
                days_all.append(x.isoformat())
        day_n = sum(1 for d in days_all if d <= today)
        live = nse.get(o["slug"]) or {}
        iw_sub = dt["subs"].get(max(dt["subs"])) if dt["subs"] else {}
        sub = {k: live.get(k, (iw_sub or {}).get(k)) for k in ("qib", "nii", "retail", "overall")}
        if sub.get("overall") is None and o.get("subscription"):
            sub["overall"] = _num(o.get("subscription"))
        h = hist.setdefault(o["slug"], {"subs": {}, "gmp": {}})
        for d, v in dt["subs"].items():
            h["subs"].setdefault(d, v)
        if any(v is not None for v in sub.values()):
            h["subs"][today] = {k: v for k, v in sub.items() if v is not None}
        if gmp is not None:
            h["gmp"][today] = gmp
        lot = _num(o.get("lotSize"))
        i = {
            "name": o["name"], "slug": o["slug"], "symbol": live.get("symbol"), "board": board,
            "price_low": lo_hi[0] if lo_hi else None, "price_high": up, "lot": int(lot) if lot else None,
            "issue_cr": _num(o.get("issueSize")), "fresh_cr": dt.get("fresh_cr"), "ofs_cr": dt.get("ofs_cr"),
            "open_date": od, "last_date": cd, "listing_date": _day(o.get("listingDate")), "close_time": "5:00 PM",
            "trading_days": days_all, "day": day_n, "days": len(days_all), "final_day": cd == today,
            "gmp_low": gmp, "gmp_high": gmp, "gmp_sources": [IW_GMP] + ([IM_GMP] if g2 is not None else []),
            "gmp_by_source": {"IPO Watch": g1, "ipomarket": g2}, "gmp_observed": now.strftime("%Y-%m-%dT%H:%M+05:30") if gs else None,
            "gmp_peak": max(since) if since else None,
            "gmp_history": [[d[:10], g] for d, g in dt["gmp_history"]][-20:],
            "has_qib": dt.get("has_qib", board == "Mainboard"),
            "subscription": {"as_of": now.strftime("%Y-%m-%dT%H:%M+05:30"), **sub,
                             "source": "NSE" if live else f"{IW}/{o['slug']}/"},
            "sub_days": [[d, (h["subs"][d] or {}).get("overall")] for d in sorted(h["subs"]) if od <= d <= cd],
            "sources": [f"{IW}/{o['slug']}/", IW_GMP] + ([IM_GMP] if g2 is not None else []) + (["https://www.nseindia.com/api/ipo-current-issue"] if live else []),
        }
        if gmp is not None and up:
            i["gmp_pct"] = round(gmp / up * 100, 1)
            i["gmp_pct_low"] = i["gmp_pct_high"] = i["gmp_pct"]
            i["implied_low"] = i["implied_high"] = round(up + gmp, 1)
            if lot:
                i["profit_lot"] = round(gmp * lot)
        i["gmp_stale"] = not gs
        i["action"], i["rules"] = evaluate(i, today, i["final_day"] and slot == "pm")  # the final-day decision is the 15:30 check
        i["top10"] = i["action"] == "APPLY" and (sub.get("overall") or 0) >= 2
        actionable.append(i)
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    if prev.get("date") == today:  # a call that changed during the day is shown and notified (IpoAlerts)
        before = {p["name"]: p.get("action") for p in prev.get("actionable") or []}
        for i in actionable:
            b = before.get(i["name"])
            if b and (b != i["action"] or slot == "pm"):
                i["pm_update"] = {"as_of": i["subscription"]["as_of"], "call_before": b, "call_after": i["action"]}
    actionable.sort(key=lambda i: ({"APPLY": 0, "WAIT": 1, "AVOID": 2}[i["action"]], not i["final_day"], -(i.get("gmp_pct") or 0)))
    keep = {o["slug"] for o in lst} | {i["slug"] for i in actionable}
    HIST.write_text(json.dumps({k: v for k, v in hist.items() if k in keep}, ensure_ascii=False, indent=0))
    n = {c: sum(1 for i in actionable if i["action"] == c) for c in ("APPLY", "WAIT", "AVOID")}
    return {"date": today, "checked_at": now.strftime("%Y-%m-%dT%H:%M+05:30"), "slot": slot, "rules_version": 2,
            "summary": f"{len(actionable)} open: {n['APPLY']} apply, {n['WAIT']} wait, {n['AVOID']} avoid",
            "actionable": actionable, "later_today": [], "upcoming": upcoming, "top": [i["name"] for i in actionable if i["action"] == "APPLY"]}


def main() -> None:
    d = build()
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    print(f"[ipo] {d['checked_at']}: {d['summary']}")
    for i in d["actionable"]:
        print(f"  {i['name']} ({i['board']}, day {i['day']}/{i['days']}): {i['action']} · " +
              " · ".join(f"{r['id']} {'ok' if r['ok'] else 'no' if r['ok'] is False else '?'} {r['v'] or ''}" for r in i["rules"]))


if __name__ == "__main__":
    main()
