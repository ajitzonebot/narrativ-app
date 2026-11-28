"""News headlines and policy releases (owner, 24 Nov 2026: feedback #86 News on the stock page, #90 why an industry rises).

Sources (free RSS, robots.txt allows the feed paths; checked 24 Nov 2026). Google News RSS was the first idea, but its
robots.txt disallows /rss for every crawler, so it is not used.
- Publishers: Economic Times, Business Standard, The Hindu BusinessLine, Moneycontrol, Mint (markets / companies /
  industry feeds). Headline, link, time and the feed's one-line summary only; no article text is fetched.
- RBI press releases and notifications (rate decisions, regulation); PIB (government press releases) when reachable.
Each feed holds only its latest 15-60 items, so `collect` runs every 2 hours (news.yml) into a store in the Actions
cache (data/news_cache, 60 days; the daily run keeps a copy in R2, news/news.json.gz). The daily run (`build`) matches
headlines to companies by name and writes:
- docs/data/news.json: per stock, the last 30 days of matched headlines (shown in the app; no rule uses news);
- docs/data/industry_packs.json: for each Leading / Improving industry, its numbers, member headlines and the policy
  releases, for Claude to write the real-world reasons (tasks/catalyst.md, docs/data/industry_why.json);
- docs/data/industry_reasons.json: Claude's reasons kept only when each one links to an item in that industry's pack.
    python -m narrativ.news collect
"""
import gzip
import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

STORE = Path("data/news_cache/news.json.gz")
UA = {"User-Agent": "Mozilla/5.0 (personal research; RSS, every 2 hours)"}
KEEP_DAYS = 60
FEEDS = [
    ("Economic Times", "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms", "news"),
    ("Economic Times", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms", "news"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss", "news"),
    ("Business Standard", "https://www.business-standard.com/rss/companies-101.rss", "news"),
    ("BusinessLine", "https://www.thehindubusinessline.com/markets/feeder/default.rss", "news"),
    ("BusinessLine", "https://www.thehindubusinessline.com/companies/feeder/default.rss", "news"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/business.xml", "news"),
    ("Mint", "https://www.livemint.com/rss/markets", "news"),
    ("Mint", "https://www.livemint.com/rss/companies", "news"),
    ("RBI", "https://www.rbi.org.in/pressreleases_rss.xml", "policy"),
    ("RBI", "https://www.rbi.org.in/notifications_rss.xml", "policy"),
    ("PIB", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3", "policy"),
]
IST = timezone(timedelta(hours=5, minutes=30))
# words that alone would match too many headlines
_COMMON = set("""india indian national bharat global power energy capital finance financial bank industries industry
international united general new first star city prime royal super standard modern premier great golden green life
home housing infra infrastructure tech technologies systems solutions services products foods consumer metal metals
steel textiles chemicals pharma pharmaceuticals health healthcare hospital hospitals motors auto automotive engineering
electric electricals cement sugar paper oil gas ports logistics media entertainment hotels hotel developers realty
estates investment investments holdings trust ventures enterprises corporation company limited ltd the and of
coal take share shares stock stocks market markets price prices asset assets money fund funds one great best top big next
nifty sensex rally sector sectors rate rates bharat hindustan east eastern west western south southern north northern""".split())
_TAIL = {"india", "industries", "limited", "ltd", "corporation", "company", "enterprises", "international", "(india)"}
_JUNK = re.compile(r"share price (live updates|highlights)|stock price history|stocks to (buy|watch)|top (gainers|losers)", re.I)
_SUFFIX = re.compile(r"\b(limited|ltd\.?|private|pvt\.?|\(india\)|india|corporation|corp\.?|company|co\.?)\s*$", re.I)


def _get(url: str) -> bytes | None:
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        print(f"[news] {url[:70]}: {str(e)[:100]}")
        return None


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _when(s: str | None) -> str | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s.strip())
        return (d if d.tzinfo else d.replace(tzinfo=IST)).astimezone(IST).isoformat(timespec="minutes")
    except Exception:  # noqa: BLE001
        for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%d %b %Y"):
            try:
                return datetime.strptime(s.strip(), f).replace(tzinfo=IST).isoformat(timespec="minutes")
            except ValueError:
                continue
    return None


def parse(xml: bytes, source: str, kind: str) -> list[dict]:
    """RSS 2.0 / RDF items -> [{title, url, time, summary, source, kind}]."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter():
        if it.tag.split("}")[-1] != "item":
            continue
        f = {c.tag.split("}")[-1].lower(): (c.text or "") for c in it}
        title, link = _clean(f.get("title")), (f.get("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        out.append({"title": title[:240], "url": link, "time": _when(f.get("pubdate") or f.get("date")),
                    "summary": _clean(f.get("description"))[:300], "source": source, "kind": kind})
    return out


def _load() -> dict:
    if not STORE.exists() and os.environ.get("CLOUDFLARE_API_TOKEN"):  # Actions cache lost: start from the R2 copy (dbsync.DURABLE)
        try:
            from .dbsync import restore_caches
            restore_caches(only={str(STORE)})
        except Exception as e:  # noqa: BLE001
            print(f"[news] R2 restore failed: {e}")
    if STORE.exists():
        try:
            return json.loads(gzip.decompress(STORE.read_bytes()))
        except Exception as e:  # noqa: BLE001
            print(f"[news] store unreadable, starting again: {e}")
    return {"items": {}}


def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    st, new = _load(), 0
    for source, url, kind in FEEDS:
        x = _get(url)
        for it in parse(x or b"", source, kind):
            it["time"] = it["time"] or now.isoformat(timespec="minutes")
            if it["url"] not in st["items"]:
                st["items"][it["url"]] = it
                new += 1
        time.sleep(0.5)
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat()
    st["items"] = {k: v for k, v in st["items"].items() if (v.get("time") or "") >= cut}
    st["collected"] = now.isoformat(timespec="minutes")
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(gzip.compress(json.dumps(st, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0))
    print(f"[news] {new} new, {len(st['items'])} stored")
    return st


# ---------------------------------------------------------------- matching
def names_for(name: str, sym: str) -> tuple[list[str], str | None]:
    """(phrases, code): the short name and its first two words (case-insensitive); a one-word name only when that word is
    the whole name; the NSE code (5+ letters) matched in capitals only ("DOLLAR" the code, not "dollar")."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    for _ in range(2):
        m = _SUFFIX.sub("", n).strip(" .,&")
        n = m if len(m.split()) >= 1 and m.lower() not in ("", "coal", "oil") else n
    words = [w for w in re.split(r"\s+", n) if w]
    if words and words[0].lower() == "the":
        words = words[1:]
    out = []
    if len(words) >= 2:
        out.append(" ".join(words))
        if not (words[0].lower() in _COMMON and words[1].lower() in _COMMON):
            out.append(" ".join(words[:2]))
    # a distinctive first word alone when the rest is only a suffix ("Polycab India" -> "Polycab"; not "Tata Steel" -> "Tata")
    rest = {w.lower().strip(".,()") for w in words[1:]}
    if words and len(words[0]) >= 5 and words[0].lower() not in _COMMON and rest <= _TAIL:
        out.append(words[0])
    code = sym.removesuffix(".NS").removesuffix(".BO")
    return list(dict.fromkeys(p for p in out if len(p) >= 4)), (code if len(code) >= 5 and code.isalpha() else None)


def matcher(rows: list[dict]):
    """rows: [{s, n}]. -> function(text) -> set of symbols named in it. A phrase two companies share goes only to the
    company whose short name is exactly that phrase (else to none)."""
    owners: dict[str, set] = {}
    full: dict[str, str] = {}
    codes: dict[str, str] = {}
    for r in rows:
        ph, code = names_for(r.get("n") or "", r["s"])
        if ph:
            full[r["s"]] = ph[0].lower()
        for p in ph:
            owners.setdefault(p.lower(), set()).add(r["s"])
        if code:
            codes[code] = r["s"]
    phrases = {}
    for p, ss in owners.items():
        if len(ss) == 1:
            phrases[p] = ss
        else:
            exact = {s for s in ss if full.get(s) == p}
            if len(exact) == 1:
                phrases[p] = exact
    multi = [p for p in phrases if " " in p]
    single = {p.capitalize(): phrases[p] for p in phrases if " " not in p}  # one word: only as a capitalised name ("Reliance", not "reliance on")
    rx = re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(multi, key=len, reverse=True)) + r")\b", re.I) if multi else None
    r1 = re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(single, key=len, reverse=True)) + r")\b") if single else None
    rc = re.compile(r"\b(" + "|".join(sorted(codes, key=len, reverse=True)) + r")\b") if codes else None

    def find(text: str) -> set:
        hit = set()
        for m in (rx.finditer(text or "") if rx else []):
            hit |= phrases.get(m.group(1).lower(), set())
        for m in (r1.finditer(text or "") if r1 else []):
            hit |= single.get(m.group(1), set())
        for m in (rc.finditer(text or "") if rc else []):
            hit.add(codes[m.group(1)])
        return hit
    return find


def build(rows: list[dict], rotation: dict | None, commodities: dict | None, today: date, extra: dict | None = None) -> dict:
    """rows: picks rows (s, n, i). Writes news.json, industry_packs.json and industry_reasons.json. -> per-stock news."""
    st = _load()
    items = sorted(st.get("items", {}).values(), key=lambda x: x.get("time") or "", reverse=True)
    since30 = str(today - timedelta(days=30))
    find = matcher(rows)
    per: dict[str, list] = {}
    for it in items:
        if it["kind"] != "news" or (it.get("time") or "")[:10] < since30 or _JUNK.search(it["title"]):
            continue
        for s in find(it["title"]):
            if len(per.setdefault(s, [])) < 10:
                per[s].append({k: it[k] for k in ("title", "url", "time", "source")})
    out = {"date": str(today), "source": "Publisher RSS (ET, Business Standard, BusinessLine, Moneycontrol, Mint); headlines matched by company name",
           "collected": st.get("collected"), "stocks": per}
    Path("docs/data/news.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    packs = industry_packs(rows, rotation, commodities, per, items, today, extra or {})
    reasons(packs, today)
    print(f"[news] {sum(len(v) for v in per.values())} headlines on {len(per)} stocks; {len(packs.get('industries', {}))} industry packs")
    return per


def industry_packs(rows, rotation, commodities, per, items, today, extra) -> dict:
    """For Leading / Improving industries: numbers, member headlines, policy releases (30 days); `due` when no reasons
    were written in 7 days or the industry turned Leading / Improving since."""
    ind = (rotation or {}).get("industries") or {}
    prev = {}
    try:
        prev = json.loads(Path("docs/data/industry_why.json").read_text()).get("industries", {})
    except Exception:  # noqa: BLE001
        pass
    since30 = str(today - timedelta(days=30))
    policy = [{k: it[k] for k in ("title", "url", "time", "source", "summary")} for it in items
              if it["kind"] == "policy" and (it.get("time") or "")[:10] >= since30][:40]
    members: dict[str, list] = {}
    for r in rows:
        if r.get("i"):
            members.setdefault(r["i"], []).append(r["s"])
    out = {}
    for name, v in ind.items():
        if v.get("q") not in ("Leading", "Improving"):
            continue
        syms = members.get(name, [])
        heads = [dict(h, symbol=s) for s in syms for h in per.get(s, [])]
        heads.sort(key=lambda h: h.get("time") or "", reverse=True)
        p = prev.get(name) or {}
        written = str(p.get("date") or "")
        old_format = any("type" not in r for r in p.get("reasons") or [])  # written before the four tests (28 Nov 2026)
        due = not written or written < str(today - timedelta(days=7)) or p.get("quadrant") != v.get("q") or old_format
        out[name] = {"quadrant": v.get("q"), "r1m": v.get("r1m"), "r3m": v.get("r3m"), "ratio": v.get("ratio"), "mom": v.get("mom"),
                     "stocks": len(syms), "due": due, "facts": (extra.get(name) or {}),
                     "commodity": ((commodities or {}).get("industries") or {}).get(name),
                     "headlines": heads[:30]}
    pk = {"date": str(today), "policy": policy, "industries": out,
          "how": "tasks/catalyst.md 8b and RESEARCH.md 'Why an industry leads': up to 3 typed, quoted reasons per due industry in docs/data/industry_why.json; each url in this pack or a primary source; check with python3 -m narrativ.industrywhy check."}
    Path("docs/data/industry_packs.json").write_text(json.dumps(pk, ensure_ascii=False, indent=0))
    return pk


def reasons(packs: dict, today: date) -> dict:
    """Claude's reasons, each checked by narrativ/industrywhy.py (linked to the pack or a primary source, not the price move
    or a broker tip, quote found in the source), and the four-test verdict on whether the lead is legitimate."""
    from . import industrywhy as IW
    try:
        why = json.loads(Path("docs/data/industry_why.json").read_text())
    except Exception:  # noqa: BLE001
        why = {"industries": {}}
    out = {}
    for name, w in (why.get("industries") or {}).items():
        pk = (packs.get("industries") or {}).get(name) or {}
        try:
            out[name] = IW.judge(name, w, pk, packs.get("policy") or [], today)
        except Exception as e:  # noqa: BLE001
            print(f"[news] industry reasons {name}: {e}")
    doc = {"date": str(today), "industries": out, "source": "Narrativ.ai, from the linked releases, headlines and filings",
           "tests": {"cause": "a real dated event (not the price move or a broker tip), quote found in the opened source",
                     "broad": f"at least {IW.BROAD_PCT}% of members above their 200-day average",
                     "numbers": f"more members grew revenue or profit over 10% than in the whole market, by {IW.NUMBERS_EDGE}+ points",
                     "before": f"a cause dated no later than {IW.GRACE_DAYS} days after the industry's 6-month low"}}
    Path("docs/data/industry_reasons.json").write_text(json.dumps(doc, ensure_ascii=False, indent=0))
    return doc


if __name__ == "__main__":
    if sys.argv[1:2] == ["collect"]:
        collect()
