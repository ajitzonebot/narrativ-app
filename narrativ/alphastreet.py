"""AlphaStreet India (alphastreet.co.in): free earnings-call transcripts and AI briefs, no login (owner, 24 Nov 2026).

Used only as a fallback when a review has no call transcript for the latest results quarter from the exchange or the
company (narrativ/latest_call.py). Their robots.txt allows all crawling; we call their public JSON API politely (one list
request per stock per day, cached; transcripts cached for good) and label everything as AlphaStreet's transcription.

  GET https://api.alphastreet.co.in/transcripts?ticker=<NSE symbol>  -> the company's calls (quarter, date, status, id)
  GET https://api.alphastreet.co.in/transcript/<id>                  -> remarks + Q&A, turn by turn with speakers
  GET https://api.alphastreet.co.in/alphacall/<id>                   -> AlphaBrief (AI-written headline, metrics, bullets)
"""
import json
import re
import time
from datetime import date
from pathlib import Path

API = "https://api.alphastreet.co.in"
CACHE = Path("data/source_cache/alphastreet")
UA = {"User-Agent": "Mozilla/5.0 (personal research; daily, a few requests)"}
TRANSCRIPT_URL = re.compile(r"^https://api\.alphastreet\.co\.in/transcript/([0-9a-f-]{36})$")
PAUSE = 0.6
_last = [0.0]


def _get(path: str):
    import requests
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    r = requests.get(API + path, headers=UA, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def calls(ticker: str, today: date | None = None) -> list[dict]:
    """The company's calls, newest first; cached for the day. [] when AlphaStreet does not cover it or is unreachable."""
    t = ticker.removesuffix(".NS").removesuffix(".BO")
    f = CACHE / "lists" / f"{t}.json"
    day = str(today or date.today())
    if f.exists():
        c = json.loads(f.read_text())
        if c.get("day") == day:
            return c["calls"]
    try:
        j = _get(f"/transcripts?ticker={t}")
    except Exception as e:  # noqa: BLE001
        print(f"[alphastreet] {t}: {str(e)[:80]}")
        return []
    items = (j or {}).get("items", j) if isinstance(j, dict) else (j or [])
    out = sorted(({k: x.get(k) for k in ("id", "fiscal_period", "fiscal_year", "event_type", "event_utc_datetime", "transcript_status")}
                  for x in items or [] if isinstance(x, dict) and x.get("id")), key=lambda x: str(x.get("event_utc_datetime")), reverse=True)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"day": day, "calls": out}))
    return out


def transcript_url(call_id: str) -> str:
    return f"{API}/transcript/{call_id}"


def _turns(section) -> list[str]:
    out = []
    for x in section or []:
        if not isinstance(x, dict):
            continue
        who = x.get("participant_name") or x.get("name") or "Speaker"
        role = ", ".join(v for v in (x.get("participant_designation"), x.get("participant_company")) if v)
        body = x.get("transcript_data") or x.get("text") or ""
        body = " ".join(body) if isinstance(body, list) else str(body)
        if body.strip():
            out.append(f"{who}{f' ({role})' if role else ''}: {body.strip()}")
    return out


def render(j: dict) -> str:
    """Transcript JSON -> plain text: management remarks, then the Q&A under a 'Question and answer session' heading."""
    td = ((j or {}).get("items") or {}).get("transcript_data") or {}
    cd = td.get("call_data") or {}
    head = f"{cd.get('company', '')} {cd.get('period', '')} FY{cd.get('year', '')} earnings call, {str(cd.get('eventdatetime', ''))[:10]}".strip()
    rem, qa = _turns(td.get("presentation")), _turns(td.get("questions_and_answers"))
    return "\n\n".join([head, *rem] + (["Question and answer session", *qa] if qa else []))


def text(url: str) -> str | None:
    """Plain text of an AlphaStreet transcript url (cached for good: FINAL transcripts do not change)."""
    m = TRANSCRIPT_URL.match(url or "")
    if not m:
        return None
    f = CACHE / "transcripts" / f"{m.group(1)}.txt"
    if f.exists():
        return f.read_text()
    try:
        j = _get(f"/transcript/{m.group(1)}")
    except Exception as e:  # noqa: BLE001
        print(f"[alphastreet] transcript {m.group(1)}: {str(e)[:80]}")
        return None
    t = render(j) if j else ""
    if len(t) < 500:
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(t)
    return t


CARDS = Path("data/alphabriefs.json")
ROTATE = 150


def card_metrics(ms) -> list:
    """Key numbers for the card: a value repeated under a second label (e.g. EBITDA and PAT both INR543 crores) is
    AlphaStreet's summary putting one figure under two labels, so only its first label is kept (owner, 24 Nov 2026)."""
    out, seen = [], set()
    for m in ms or []:
        if not isinstance(m, list) or len(m) < 2:
            continue
        v = re.sub(r"inr|rs\.?|₹|[\s,]", "", str(m[1]).lower())
        if v in seen:
            continue
        seen.add(v)
        out.append(m)
    return out[:3]


def card(ticker: str, today: date | None = None) -> dict | None:
    """The app's 'Latest call' card: the latest FINAL earnings call's AlphaBrief (AlphaStreet has briefs for the latest call)."""
    c = next((x for x in calls(ticker, today) if x.get("event_type") in (None, "earnings_conference")
              and str(x.get("transcript_status") or "").upper() == "FINAL"), None)
    if not c:
        return None
    b = brief(c["id"])
    if not b:
        return None
    t = ticker.removesuffix(".NS").removesuffix(".BO")
    return {"call": f"{c.get('fiscal_period')} FY{str(c.get('fiscal_year'))[2:]}", "date": str(c.get("event_utc_datetime") or "")[:10],
            "headline": b.get("headline"), "metrics": card_metrics(b.get("metrics")),
            "bullets": [x for x in b.get("bullets") or [] if isinstance(x, str)][:4], "url": f"https://alphastreet.co.in/company/{t}"}


def refresh_cards(priority: list[str], rest: list[str], today: date) -> dict:
    """Stored cards for every stock: the priority list (queue, Buys, candidates) daily, the rest ROTATE a day in turn."""
    st = json.loads(CARDS.read_text()) if CARDS.exists() else {}
    n = max(1, -(-len(rest) // ROTATE))
    k = today.toordinal() % n
    todo = list(dict.fromkeys(priority + rest[k * ROTATE:(k + 1) * ROTATE]))
    for s in todo:
        try:
            c = card(s, today)
        except Exception as e:  # noqa: BLE001
            print(f"[alphastreet] card {s}: {str(e)[:80]}")
            continue
        if c:
            st[s] = c
    for c in st.values():  # cards stored before the repeat filter
        c["metrics"] = card_metrics(c.get("metrics"))
    CARDS.parent.mkdir(parents=True, exist_ok=True)
    CARDS.write_text(json.dumps(st, ensure_ascii=False, indent=0, sort_keys=True))
    print(f"[alphastreet] cards: {len(todo)} checked today, {len(st)} stored")
    return st


def brief(call_id: str) -> dict | None:
    """AlphaBrief for a call (AI-written by AlphaStreet: a lead, never a fact for scoring)."""
    f = CACHE / "briefs" / f"{call_id}.json"
    if f.exists():
        return json.loads(f.read_text())
    try:
        j = _get(f"/alphacall/{call_id}")
    except Exception as e:  # noqa: BLE001
        print(f"[alphastreet] brief {call_id}: {str(e)[:80]}")
        return None
    if not j or not j.get("headline"):
        return None
    b = {"headline": j.get("headline"), "metrics": j.get("metrics") or [], "bullets": j.get("bullets") or [], "note": j.get("note")}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(b, ensure_ascii=False))
    return b
