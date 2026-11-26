"""Research packs: what Claude needs per queued stock, prepared by GitHub so Claude judges instead of searching.

docs/data/packs/<symbol>.json (only today's queue; old packs are deleted):
  task, reason, decision so far, gaps to fill, key computed numbers, the latest transcript / presentation
  (exchange links) with forward-looking excerpts (verbatim sentences: a number + a guidance/capacity/order word,
  with one sentence either side), flagged filings to review, open promises and checkpoints.
Excerpts are verbatim text from the PDF, so quotes copied from them pass narrativ.verify (which re-reads the source).
"""
import hashlib
import io
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from .util import write_if_changed

OUT = Path("docs/data/packs")
TXT = Path("data/source_cache/doctext")
KEY = re.compile(r"guidance|guide|expect|target|outlook|going forward|next (year|quarter|fy)|by (fy|20\d\d)|fy ?2?\d|"
                 r"order (book|inflow|pipeline)|orders? (worth|of|from)|capacity|commission|capex|expansion|new (plant|line|facility|product)|"
                 r"margin|growth|grow|revenue (visibility|potential)|pipeline|launch|ramp|utili[sz]ation|demand|backlog|peak revenue", re.I)
NUM = re.compile(r"\d")
ABBR = re.compile(r"\b(Rs|INR|Mr|Mrs|Ms|Dr|No|Nos|approx|Ltd|Pvt|Co|vs|i\.e|e\.g|viz|Sr|Jr|St|Mn|Bn|Cr|Q[1-4]|FY|H[12])\.$", re.I)
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])")
MAX_EXCERPTS, MAX_CHARS = 45, 18_000
SHORT_CHARS = 9_000  # enrich / recheck packs: forward excerpts only, about half the reading
DOC_RULES = ("Transcript", "Investor presentation")
RESULTS_RULE = "Results filed (XBRL covers numbers)"
# notes to results and the auditor's review report: the parts XBRL does not carry (one-offs, emphasis of matter, leases, disputes)
NOTE = re.compile(r"exceptional|one[- ]?time|emphasis of matter|qualified (opinion|conclusion)|basis for qualif|material uncertainty|"
                  r"going concern|attach|enforcement directorate|contingent|subsequent event|impairment|write[- ]?off|written off|"
                  r"lease liabilit|right[- ]of[- ]use|provision|litigation|dispute|show cause|penalty|search|survey|fraud|"
                  r"discontinued|restat|reclassif|regroup|deferred tax|tax demand|warrants?|preferential|scheme of|amalgamat|demerg|"
                  r"segment|related part|guarantee|default|moratorium|pledge", re.I)
NOTES_CHARS = 9_000


# ---------- Is it a document? Cover letters, audio links and call intimations are not new information ----------
# (research runs wasted slots on "transcript is a cover letter only", "only an audio link", "only a call intimation")
JUNK_SUBJECT = re.compile(r"about\s+(link of recording|audio|schedule of meet|intimation|record(ing)? of)|link of recording|audio recording|"
                          r"schedule of (analyst|investor|meet)|intimation of (the )?(earnings|conference|analyst|investor|call|meet)", re.I)
JUNK_FILE = re.compile(r"audio|recording|covering[_ -]?letter|cover[_ -]?letter", re.I)
INTIMATION_FILE = re.compile(r"intimation|invitation|schedule", re.I)
REAL_SUBJECT = re.compile(r"transcript|presentation|results|outcome|annual report|press release|earnings (release|update)", re.I)
THIN_CHARS = 1_500        # a transcript or presentation shorter than this is a cover letter or a link
THIN_CHARS_WORDED = 4_000  # shorter than this and worded like an intimation / audio link / cover letter
THIN_WORDS = re.compile(r"audio (recording|link)|link (of|to|for) (the )?(audio|recording|call)|intimation|cover(ing)? letter|"
                        r"kindly (take|find)|hereby (inform|intimate|submit|enclose)|pursuant to regulation", re.I)


def thin_text(text: str | None) -> bool:
    """True for a 'transcript' that is only a cover letter, an audio-recording link or a call intimation: very short, or short
    and worded like one (and no Q&A). None / empty text is thin too."""
    t = " ".join((text or "").split())
    if len(t) < THIN_CHARS:
        return True
    return len(t) < THIN_CHARS_WORDED and bool(THIN_WORDS.search(t)) and not QA.search(t)


def junk_filing(f: dict) -> bool:
    """Exchange filing (dict with text, category, url) that cannot hold new information: audio link, call intimation, cover letter."""
    subj = str(f.get("text") or "")
    name = str(f.get("url") or "").rsplit("/", 1)[-1]
    if JUNK_SUBJECT.search(subj) and not REAL_SUBJECT.search(subj.split("about", 1)[-1]):
        return True
    if JUNK_FILE.search(name):
        return True
    return bool(INTIMATION_FILE.search(name) and not REAL_SUBJECT.search(subj.split("about", 1)[-1]))


def cached_text(url: str) -> str | None:
    """Text of a document already read by an earlier run (no download); None if it has not been read."""
    f = TXT / (hashlib.sha1(str(url).encode()).hexdigest() + ".txt")
    try:
        return f.read_text() if f.exists() else None
    except OSError:
        return None


def new_documents(filings: list[dict] | None, since: str | None, text_of=cached_text) -> list[dict]:
    """Filings dated after `since` (the thesis's `updated` date) that are real documents. A document whose text is already cached
    and thin (cover letter, audio link) does not count. Without `since` every real document counts."""
    out = []
    for f in filings or []:
        d = str(f.get("date") or "")[:10]
        if not d or (since and d <= str(since)[:10]) or junk_filing(f):
            continue
        t = text_of(f["url"]) if f.get("url") and text_of else None
        if t is not None and thin_text(t):
            continue
        out.append(f)
    return out


def _text(url: str, ns) -> tuple[str | None, int | None]:
    if url.startswith("https://api.alphastreet.co.in/"):  # AlphaStreet transcript (JSON -> text, cached by narrativ.alphastreet)
        from .alphastreet import text as as_text
        t = as_text(url)
        return (t, None) if t else (None, None)
    TXT.mkdir(parents=True, exist_ok=True)
    f = TXT / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if f.exists():
        t = f.read_text()
        pg = f.with_suffix(".pages")
        return t, (int(pg.read_text()) if pg.exists() else None)
    try:
        from pypdf import PdfReader
        pdf = _pdf_bytes(url, ns)
        if not pdf:
            return _docling_only(url)
        rd = PdfReader(io.BytesIO(pdf))
        t = "\n".join((p.extract_text() or "") for p in rd.pages)
        if len(t.strip()) < 200:  # scanned: no text layer; docling's OCR text if it has run (narrativ/docread.py)
            return _docling_only(url, len(rd.pages))
        f.write_text(t)
        f.with_suffix(".pages").write_text(str(len(rd.pages)))
        return t, len(rd.pages)
    except Exception as e:  # noqa: BLE001
        print(f"[packs] {url[-60:]}: {str(e)[:80]}")
        return _docling_only(url)


_FETCHES = [0]  # PDF downloads this process: the polite pause follows a download, not a text-cache hit (cost audit 26 Nov 2026)


def _pdf_bytes(url: str, ns) -> bytes | None:
    _FETCHES[0] += 1
    rq = __import__("requests")
    bh = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/"}
    r = ns.s.get(url, timeout=60) if "nseindia" in url else rq.get(url, headers=bh, timeout=60)
    if r.status_code == 404 and "/AttachLive/" in url:  # BSE moves older attachments to its archive folder
        r = rq.get(url.replace("/AttachLive/", "/AttachHis/"), headers=bh, timeout=60)
    return r.content if r.ok and r.content.startswith(b"%PDF") else None


# ---------- Cover letters that point to the real document on the company's website (owner, 24 Nov 2026) ----------
# Some companies file only a one-page letter ("the transcript is available at <link>"): follow the link to the PDF.
LINK = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+", re.I)
EXCHANGE = re.compile(r"nseindia\.|bseindia\.", re.I)
DOC_WORDS = re.compile(r"transcript|presentation|concall|con-call|earnings|investor", re.I)


def letter_links(url: str, ns, txt: str | None) -> list[str]:
    """Links in a cover letter (PDF link annotations, then web addresses in its text), PDFs and document-like names first."""
    f = TXT / (hashlib.sha1(url.encode()).hexdigest() + ".links")
    if f.exists():
        return json.loads(f.read_text())
    found = []
    try:
        pdf = _pdf_bytes(url, ns)
        if pdf:
            from pypdf import PdfReader
            for pg in PdfReader(io.BytesIO(pdf)).pages:
                for a in pg.get("/Annots") or []:
                    act = a.get_object().get("/A")
                    u = act.get_object().get("/URI") if act is not None else None
                    if u:
                        found.append(str(u))
    except Exception as e:  # noqa: BLE001
        print(f"[packs] links {url[-50:]}: {str(e)[:80]}")
    found += [u for u in LINK.findall(txt or "")]
    out = []
    for u in found:
        u = u.strip().rstrip(".,;:")
        u = "https://" + u if u.lower().startswith("www.") else u
        if u.lower().startswith("http") and not EXCHANGE.search(u) and u not in out:
            out.append(u)
    out.sort(key=lambda u: (not u.lower().split("?")[0].endswith(".pdf"), not DOC_WORDS.search(u)))
    TXT.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out[:5]))
    return out[:5]


def doc_text(url: str, ns, kind: str | None = None) -> tuple[str | None, int | None, str]:
    """Text of a filed transcript / presentation. When the filing is only a cover letter, follow its link (up to 3) to the
    real document; returns (text, pages, url the text came from)."""
    txt, pages = _text(url, ns)
    if kind not in ("transcript", "presentation") or not txt or not thin_text(txt):
        return txt, pages, url
    for u in letter_links(url, ns, txt)[:3]:
        t2, p2 = _text(u, ns)
        if t2 and not thin_text(t2):
            return t2, p2, u
    return txt, pages, url


def _docling_only(url: str, pages: int | None = None) -> tuple[str | None, int | None]:
    from .docread import text_for
    t = text_for(url)
    return (t, pages) if t else (None, None)


def excerpts(text: str) -> list[str]:
    flat = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    flat = re.sub(r"\n(?!\n)", " ", flat)
    raw = [s.strip() for s in SENT.split(flat) if s.strip()]
    sents = []
    for x in raw:  # re-join splits after abbreviations (Rs. 120, Mr. X, No. 5, approx. 10)
        if sents and ABBR.search(sents[-1]):
            sents[-1] += " " + x
        else:
            sents.append(x)
    keep = set()
    for i, s in enumerate(sents):
        if NUM.search(s) and KEY.search(s) and len(s) < 600:
            keep.update({i - 1, i, i + 1})
    out, chars, run = [], 0, []
    for i in sorted(k for k in keep if 0 <= k < len(sents)):
        if run and i != run[-1] + 1:
            out.append(" ".join(sents[j] for j in run)); run = []
        run.append(i)
    if run:
        out.append(" ".join(sents[j] for j in run))
    res = []
    for x in out:
        if len(res) >= MAX_EXCERPTS or chars + len(x) > MAX_CHARS:
            break
        res.append(x); chars += len(x)
    return res


def notes(text: str) -> list[str]:
    """Verbatim sentences (with one either side) from a results filing that carry a note keyword: one-offs, auditor remarks,
    leases, disputes, fund raises. Code already reads the numbers from XBRL; these are what only the PDF says."""
    flat = re.sub(r"[ \t]+", " ", (text or "").replace("\r", ""))
    flat = re.sub(r"\n(?!\n)", " ", flat)
    sents = [s.strip() for s in SENT.split(flat) if s.strip()]
    keep = set()
    for i, s in enumerate(sents):
        if NOTE.search(s) and 30 < len(s) < 900:
            keep.update({i - 1, i, i + 1})
    out, run, chars = [], [], 0
    for i in sorted(k for k in keep if 0 <= k < len(sents)):
        if run and i != run[-1] + 1:
            out.append(" ".join(sents[j] for j in run)); run = []
        run.append(i)
    if run:
        out.append(" ".join(sents[j] for j in run))
    res = []
    for x in out:
        if chars + len(x) > NOTES_CHARS:
            break
        res.append(x); chars += len(x)
    return res


def _results_doc(sym: str, ann_st: dict, today: date, days: int = 150) -> dict | None:
    """Latest results filing (PDF) announced on NSE: source of the notes and the auditor's review report."""
    since = str(today - timedelta(days=days))
    rows = [r for r in (ann_st.get("rows") or {}).get(sym, []) if len(r) > 5 and r[5] == RESULTS_RULE and r[3] and r[0] >= since
            and str(r[3]).lower().endswith(".pdf")]
    if not rows:
        return None
    d, cat, txt, url, *_ = max(rows, key=lambda r: r[0])
    return {"kind": "results", "date": d, "title": (txt or cat)[:140], "url": url}


def _docs_for(sym: str, ann_st: dict, ex: dict, today: date, transcripts: int = 2, days: int = 400) -> list[dict]:
    """Latest 2 call transcripts and the latest investor presentation within `days`: NSE announcements, then exchange filings
    (BSE for BSE-only listings). Companies that hold no calls simply have none."""
    since = str(today - timedelta(days=days))
    cand = []
    for d, cat, txt, url, g, rule in (ann_st.get("rows") or {}).get(sym, []):
        if rule in DOC_RULES and url and d >= since and not junk_filing({"text": txt or cat, "url": url}):
            cand.append({"kind": "transcript" if rule == "Transcript" else "presentation", "date": d, "title": (txt or cat)[:140], "url": url})
    for x in (ex.get(sym) or {}).get("filings") or []:
        t = str(x.get("text") or "") + " " + str(x.get("category") or "")
        if x.get("url") and (x.get("date") or "") >= since and not junk_filing(x):
            cand.append({"kind": "transcript" if re.search(r"transcript", t, re.I) else "presentation", "date": x.get("date"),
                         "title": str(x.get("text"))[:140], "url": x["url"]})
    d24 = str(today - timedelta(days=730))
    from .announcements import DEV
    for d, cat, txt, url, *_ in (ann_st.get("rows") or {}).get(sym, []):  # G7: statement of deviation / monitoring agency report
        if url and d >= d24 and DEV.search(f"{cat} {txt}"):
            cand.append({"kind": "deviation", "date": d, "title": (txt or cat)[:140], "url": url})
    out, urls = [], set()
    for k, n in (("transcript", transcripts), ("presentation", 1), ("deviation", 2)):
        for c in sorted((c for c in cand if c["kind"] == k), key=lambda c: c["date"] or "", reverse=True):
            if c["url"] in urls or sum(1 for o in out if o["kind"] == k) >= n:
                continue
            urls.add(c["url"])
            out.append(c)
    return out


def _latest_call_docs(call: dict, docs: list, review: bool, time_left: bool) -> dict:
    """Idea 1 + AlphaStreet fallback (owner, 24 Nov 2026): when the pack has no transcript of the latest call from the
    exchange or the company, add AlphaStreet's (labelled), and its AlphaBrief as leads for a review. -> call + in_pack."""
    from .latest_call import EARLY_DAYS, summary
    lo = str(date.fromisoformat(call["results_filed"]) - timedelta(days=EARLY_DAYS))
    have = any(d.get("kind") == "transcript" and d.get("has_text") and str(d.get("date") or "") >= lo for d in docs)
    src = next((x for x in call.get("sources") or [] if x["src"] == "alphastreet"), None)
    out = {**call}
    if src and not have and time_left:
        txt, _ = _text(src["url"], None)
        if txt:
            d = {"kind": "transcript", "date": src["date"], "title": f"{call['quarter']} earnings call (AlphaStreet transcription)",
                 "url": src["url"], "source": "AlphaStreet India: third-party transcription of the call, not the company's own transcript",
                 "has_text": True, "quality": quality(txt, None), "excerpts": excerpts(txt),
                 "note": "quote with this url (the verifier reads the same text); prefer the company's own transcript once it is filed"}
            if review:
                for x in docs:
                    x.pop("full_text", None)  # the latest call gets the whole-call slot
                d["full_text"] = full_transcript(txt)
            attach_reader(d)
            docs.insert(0, d)
            have = True
            out["fallback"] = "alphastreet"
    if review and len(call.get("recent") or []) > 1 and time_left:
        # the previous quarter's call (owner, 24 Nov 2026): AlphaStreet has briefs for the latest call only, so Claude compares
        # quarters from the transcripts; added when no exchange / company transcript within 10 days of that call is in the pack
        prev = call["recent"][1]
        pd_ = date.fromisoformat(prev["date"])
        near = any(d.get("kind") == "transcript" and d.get("has_text") and d.get("date")
                   and abs((date.fromisoformat(str(d["date"])[:10]) - pd_).days) <= 10 for d in docs)
        if not near:
            from .alphastreet import transcript_url
            u = transcript_url(prev["id"])
            txt, _ = _text(u, None)
            if txt:
                docs.append({"kind": "transcript", "date": prev["date"], "title": f"{prev['call']} earnings call (AlphaStreet transcription, previous quarter)",
                             "url": u, "source": "AlphaStreet India: third-party transcription of the call, not the company's own transcript",
                             "has_text": True, "quality": quality(txt, None), "excerpts": excerpts(txt),
                             "note": "previous quarter: compare what management said then with the latest call; quote with this url"})
                out["previous_call"] = prev["call"]
    if review and call.get("recent"):  # AlphaBriefs of the last calls (latest first): how the story moved quarter to quarter
        from .alphastreet import brief
        bs = []
        for c in call["recent"]:
            b = brief(c["id"])
            if b:
                bs.append({**b, "call": c["call"], "date": c["date"]})
        if bs:
            out["brief"] = {"briefs": bs, "use": "AI-written by AlphaStreet: leads only. Confirm anything you use in the transcript and quote it "
                            "verbatim; never copy its numbers. Compare quarters: what management promised before and what it says now"}
    out["in_pack"] = have
    out["summary"] = summary(call) + ("" if have or call["state"] == "missing" else "; not readable here: open the source")
    return out


def quality(text: str, pages: int | None) -> dict:
    """Extraction quality: characters per page and share of letters. Scanned or garbled PDFs score 'poor'."""
    t = text or ""
    n = len(t)
    alpha = sum(ch.isalpha() for ch in t) / n if n else 0
    cpp = n / pages if pages else None
    grade = "poor" if (cpp is not None and cpp < 300) or alpha < 0.55 else "weak" if (cpp is not None and cpp < 900) or alpha < 0.65 else "good"
    return {"grade": grade, "chars_per_page": round(cpp) if cpp else None, "letters_pct": round(alpha * 100)}


QA = re.compile(r"question[- ]and[- ]answer|q\s*&\s*a session|first question|open the floor for questions|we will now begin the question", re.I)


def full_transcript(text: str, cap: int = 24_000) -> dict:
    """Cleaned text split into management remarks and the Q&A (where the split can be found). The Q&A gets two thirds:
    analysts' questions show what the market doubts; the opening remarks repeat the presentation."""
    t = re.sub(r"[ \t]+", " ", (text or "").replace("\r", ""))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    m = QA.search(t)
    rem, qa = (t[:m.start()], t[m.start():]) if m else (t, "")
    q_cap = cap * 2 // 3 if qa else 0
    return {"remarks": rem[: cap - q_cap], "qa": qa[:q_cap], "truncated": len(t) > cap,
            "note": "shortened: open the PDF (url) for anything not here"}


# Numbers code reads straight from the company's XBRL filing (exact tagged values): Claude does not re-check these.
MACHINE = {"revenue_ttm_cr": "Revenue, last 4 quarters", "pat_ttm_cr": "Profit, last 4 quarters", "equity_cr": "Equity",
           "mcap_cr": "Share count x price (market cap)"}


def machine_checks(Mx: dict) -> tuple[list[dict], list[str]]:
    """-> (numbers read by code from the XBRL filing, what Claude must still check by hand)."""
    mc, need = [], ["Total debt including lease liabilities: read the balance sheet in the results PDF (code has missed "
                    "lease liabilities for some companies, e.g. BANCOINDIA in Nov 2026). Record it as an audit check with "
                    "\"rule\": \"debt_leases\" (RULES.md R7: a pass without it stays at verification pending)"]
    for k, name in MACHINE.items():
        m = Mx.get(k)
        if isinstance(m, dict) and m.get("v") is not None and "NSE filing" in str(m.get("src") or ""):
            mc.append({"field": k, "name": name, "value": m["v"], "source": m.get("src"), "url": m.get("url"), "by": "code, from the XBRL filing"})
        elif isinstance(m, dict) and m.get("v") is not None:
            need.append(f"{name} ({k}): source is '{m.get('src')}', not the NSE XBRL filing: check it against the filing")
    oi = Mx.get("other_income_pct_pbt")
    if isinstance(oi, dict) and (oi.get("v") or 0) > 25:
        need.append(f"Other income is {oi['v']:.0f}% of pre-tax profit (Buy gate R2 needs ≤ 25%): is it recurring (e.g. JV profit)? "
                    "If yes, quote it in other_income_recurring")
    need.append("Related-party purchases and sales as % of turnover, quoted where disclosed (RULES.md R7): audit.related_party "
                "{status: quoted, text, quote, source} or {status: 'not disclosed', checked, source}")
    for k in ("cash_cr", "borrowings_cr"):
        m = Mx.get(k)
        if isinstance(m, dict) and m.get("v") is not None and "NSE filing" not in str(m.get("src") or ""):
            need.append(f"{k}: source is '{m.get('src')}': check it against the filing")
    return mc, need


def build(queue: list[dict], today: date, ann_st: dict, ex: dict, dec: dict, ev: dict, mx: dict, annc: dict, theses: dict,
          mem: dict, val, aflags: dict | None = None, max_minutes: float = 12, calls: dict | None = None) -> dict:
    """calls: {symbol: narrativ.latest_call.latest_call(...)}: the latest earnings call and where it is available."""
    from .filings import NSESession
    OUT.mkdir(parents=True, exist_ok=True)
    want = {q["symbol"] for q in queue}
    for f in OUT.glob("*.json"):
        if f.stem not in want:
            f.unlink()
    ns, t0, n_docs, n_ok = None, time.time(), 0, 0
    for q in queue:
        s = q["symbol"]
        L = (ev.get(s) or {}).get("L") or {}
        gaps = [{"level": k, "id": i["id"], "name": i["n"], "note": i.get("note")} for k, lv in L.items() for i in lv.get("items", [])
                if i.get("m") is None and (i.get("note") in ("needs research", "no order book quoted", "source not connected yet") or k == "out")]
        flags = [{"id": k, "value": v[1], "url": v[3]} for k, v in (annc.get(s) or {}).items()
                 if v and v[0] == 1 and k in ("A2", "A4", "A5", "G1", "G2", "G3", "G4")
                 and k not in ((theses.get(s) or {}).get("flag_reviews") or {})]
        docs, thin = [], []
        review = q.get("task") in ("audit", "review") or bool(q.get("requested"))
        if time.time() - t0 < max_minutes * 60:
            rd = _results_doc(s, ann_st, today) if review else None
            if rd:
                ns = ns or NSESession()
                txt, pages = _text(rd["url"], ns)
                n_docs += 1
                if txt and len(txt.strip()) > 200:
                    n_ok += 1
                    rd.update({"has_text": True, "pages": pages, "quality": quality(txt, pages), "notes": notes(txt),
                               "note": "notes and auditor's report sentences, verbatim; numbers in tables lose layout: open the PDF to quote a table"})
                else:
                    rd.update({"has_text": False, "notes": [], "note": "no text layer or not reachable: open the PDF yourself"})
                docs.append(rd)
            for d in _docs_for(s, ann_st, ex, today):
                ns = ns or NSESession()
                f0 = _FETCHES[0]
                txt, pages, src = doc_text(d["url"], ns, d["kind"])
                n_docs += 1
                if src != d["url"]:  # the filing was a cover letter: the document is on the company's website
                    d.update({"filing": d["url"], "url": src,
                              "source_note": "the exchange filing is a cover letter; this is the document it links to: quote with this url"})
                if txt and d["kind"] in ("transcript", "presentation") and thin_text(txt):
                    links = letter_links(d["url"], ns, txt)
                    thin.append({"date": d.get("date"), "title": d.get("title"), "url": d["url"],
                                 "why": "cover letter / audio link / intimation only: not a new document"
                                 + ("; it points to the links below (not a PDF we could read): open them if the document matters" if links else ""),
                                 **({"links": links} if links else {})})
                    continue
                if txt and len(txt.strip()) > 200:
                    n_ok += 1
                    qd = quality(txt, pages)
                    ex_ = excerpts(txt)
                    if not review:  # enrich / recheck: about half the excerpt text
                        cut, n = [], 0
                        for x in ex_:
                            if n + len(x) > SHORT_CHARS:
                                break
                            cut.append(x); n += len(x)
                        ex_ = cut
                    d.update({"has_text": True, "pages": pages, "quality": qd, "excerpts": ex_})
                    if d["kind"] == "transcript" and review and not any("full_text" in x for x in docs):
                        d["full_text"] = full_transcript(txt)  # whole call: context, tone and analysts' questions
                    if d["kind"] == "presentation":
                        d["note"] = "tables lose their layout in text: open the PDF before quoting any table number"
                    _docling(d)
                    attach_reader(d)
                    if qd["grade"] == "poor":
                        d["note"] = "poor text extraction (likely scanned or garbled): open the PDF yourself"
                else:
                    d.update({"has_text": False, "excerpts": [], "note": "no text layer or not reachable: open the PDF yourself or skip"})
                docs.append(d)
                if _FETCHES[0] != f0:
                    time.sleep(0.4)
        call = (calls or {}).get(s)
        if call:
            call = _latest_call_docs(call, docs, review, time.time() - t0 < max_minutes * 60)
        Mx = mx.get(s) or {}
        nums = {k: val(Mx, k) for k in ("price", "mcap_cr", "revenue_ttm_cr", "pat_ttm_cr", "pe", "ev_ebitda", "roce_pct", "rev_yoy_pct",
                                         "rev_cagr_3y_pct", "ebitda_margin_pct", "de", "promoter_pct")}
        th = theses.get(s) or {}
        pack = {"symbol": s, "date": str(today), "task": q.get("task"), "reason": q.get("reason"), "decision": dec.get(s),
                "broker_targets_wanted": q.get("task") in ("audit", "review", "enrich") and ((dec.get(s) or {}).get("d") in ("Buy", "Strong Buy") or bool((dec.get(s) or {}).get("candidate"))),
                "dossier": f"docs/data/fin/{s}.json", "chart": f"docs/data/charts/{s}.json",
                "broker_targets_have": [{k: b.get(k) for k in ("broker", "target", "date")} for b in (theses.get(s) or {}).get("broker_targets") or []],
                "levels": {k: lv.get("name") for k, lv in L.items()}, "numbers": {k: v for k, v in nums.items() if v is not None},
                "gaps": gaps, "documents": docs, "flags_to_review": flags,
                "open_promises": [{"id": p.get("id"), "promise": p.get("promise"), "due": p.get("due"), "status": p.get("status")}
                                  for p in th.get("promises", []) if p.get("status") in ("pending", "raised", "unverified")],
                "checkpoints": [c for c in (mem.get(s) or {}).get("checkpoints", []) if c.get("status") in ("open", "due")][:8],
                "events": q.get("events") or [], "filings": q.get("filings") or []}
        if call:
            pack["latest_call"] = {k: v for k, v in call.items() if k != "brief"}
            if call.get("brief") and review:
                pack["alphabrief"] = call["brief"]
        if thin:
            pack["thin_documents"] = thin
        if q.get("overdue"):  # kill switches / must-go-right items / promises past due: resolve each with filed evidence (or say none is filed)
            pack["overdue"] = q["overdue"]
        if q.get("scan_gaps"):  # scan items with no quote / source / due date
            pack["scan_gaps"] = q["scan_gaps"]
        if not any(d.get("kind") == "transcript" for d in docs):
            pack["no_call_note"] = "No call transcript in the last 400 days (the company may not hold calls): work from results filings, presentations and announcements"
        # every pack carries the numbers, machine checks and Claude's checklist (small): a task can be turned into a full review
        # at any time (owner request, one-off override) without the checks going missing; documents stay task-sized
        if True:  # everything the app claims, with formula, inputs and source, for an independent check
            keys = ("mcap_cr", "revenue_ttm_cr", "pat_ttm_cr", "ebitda_margin_pct", "pe", "ev_ebitda", "roce_pct", "roe_pct", "de",
                    "net_debt_ebitda", "interest_cover", "rev_yoy_pct", "pat_yoy_pct", "rev_cagr_3y_pct", "pat_cagr_3y_pct", "cfo_to_ebitda_pct",
                    "receivable_days", "equity_cr")
            pack["app_numbers"] = {k: {"value": Mx[k].get("v"), "formula": Mx[k].get("f"), "inputs": Mx[k].get("in"), "source": Mx[k].get("src"),
                                       "url": Mx[k].get("url")} for k in keys if isinstance(Mx.get(k), dict)}
            pack["app_basis"] = {k: Mx.get(k) for k in ("basis", "last_quarter", "bs_date", "filed", "kind")}
            pack["consistency_flags"] = (aflags or {}).get(s) or []
            from .funnel import audit_flag_items
            ids = audit_flag_items(Mx, (ev.get(s) or {}).get("lender"))  # the same flags, with the id audit.flag_notes[].flag names
            pack["consistency_flag_ids"] = [{"flag": i, "text": t} for i, t in ids]
            mc, need = machine_checks(Mx)
            pack["machine_checked"] = mc
            pack["claude_checks"] = need + [f"consistency flag [{i}]: {t} (explain it in audit.flag_notes with flag '{i}', note, quote, source)"
                                            for i, t in ids]
            if not s.endswith(".NS"):
                pack["claude_checks"].append("BSE-only stock: code has no shareholding or insider-trading data (R5, T14 promoter buying, "
                                             "T15 not evaluated). Say what you checked instead in audit.bse_only_note {text, source}")
            pack["decision_reasons"] = (dec.get(s) or {}).get("why")
        write_if_changed(OUT / f"{s}.json", json.dumps(pack, ensure_ascii=False, indent=0, default=str))
    print(f"[packs] {len(queue)} packs, {n_docs} documents ({n_ok} with text), {time.time() - t0:.0f}s")
    return {"packs": len(queue), "docs": n_docs, "with_text": n_ok}


# ---------- Reading pipeline (narrativ/reader.py): stage 1 Flash-Lite, stage 2 Flash, stage 3 Claude ----------
READER = Path("data/reader")
READER_NOTE = ("Found by a free model ({model}, read {read}). Each quote is verified word for word in this document by code; `text` is the model's "
               "summary (`text_not_in_quote` lists numbers it added from elsewhere). Not evidence until you confirm it in context: conditions, later withdrawal, management not "
               "analyst, materiality. Confirmed rows go into drivers/promises with the same quote; then check the Q&A for anything missed.")


def _docling(d: dict) -> None:
    """Layout-aware text from narrativ/docread.py: tables of a presentation, or the OCR flag of a scanned document."""
    from .docread import meta, tables, text_for
    md, m = text_for(d.get("url") or ""), meta(d.get("url") or "")
    if not md:
        return
    if m.get("ocr"):
        d["ocr"] = True
        d["note"] = ("scanned PDF read by OCR (docling): quotes are verbatim to the OCR text; check numbers against the PDF "
                     "image before relying on them")
    tb = tables(md)
    if tb:
        d["tables"] = tb
        if d.get("kind") == "presentation":
            d["note"] = ("`tables` are the presentation's tables with rows and columns kept (docling); quote table rows from "
                         "them (the verifier accepts them)")


def reader_store() -> dict:
    f = READER / "store.json"
    return json.loads(f.read_text()) if f.exists() else {}


_STORE: dict | None = None


def attach_reader(d: dict, store: dict | None = None) -> bool:
    """Add the best reader's verified rows to a pack document (Flash over Flash-Lite). Returns True if rows were attached."""
    global _STORE
    if store is None:
        if _STORE is None:
            _STORE = reader_store()
        store = _STORE
    e = store.get(d.get("filing") or d.get("url") or "") or {}  # the reader keys a followed cover letter by the filing url
    for m in ("flash", "lite"):
        r = e.get(m) or {}
        if "rows" in r:
            d["reader"] = {"model": r.get("model"), "read": r.get("at"), "rows": r["rows"],
                           "note": READER_NOTE.format(model=r.get("model"), read=r.get("at"))}
            return True
    return False


def doc_index(syms, ann_st: dict, ex: dict, today: date, rank_of: dict, queue: list[dict]) -> int:
    """data/reader/docs.json: the latest call transcript and investor presentation (400 days) of every scored stock, with its
    readiness rank and today's Claude task, for the reader (no downloads here)."""
    task = {q["symbol"]: q.get("task") for q in queue}
    rows = []
    for s in syms:
        for d in _docs_for(s, ann_st, ex, today, transcripts=1):
            if d["kind"] in ("transcript", "presentation") and str(d.get("url") or "").lower().endswith(".pdf"):
                rows.append({"s": s, "rk": rank_of.get(s), "task": task.get(s), "kind": d["kind"], "date": d["date"], "url": d["url"]})
    READER.mkdir(parents=True, exist_ok=True)
    (READER / "docs.json").write_text(json.dumps({"date": str(today), "docs": rows}, ensure_ascii=False, indent=0))
    print(f"[packs] reader index: {len(rows)} documents, {len({r['s'] for r in rows})} stocks")
    return len(rows)
