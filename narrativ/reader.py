"""Reading pipeline, stages 1 and 2 (stage 3 is Claude). Free Gemini models read whole filed documents (call transcripts,
investor presentations) and return forward-looking items with exact quotes. Code keeps an item only if its quote is found word
for word in the document; a number in its summary text that is not in the quote is flagged. The readers find; they never rate: Buy rules count
a trigger only after Claude confirms it in its review (RULES.md R4).

  Stage 1 Flash-Lite (gemini-3.5-flash-lite, free 500/day): the latest transcript and presentation of every scored stock, new
          documents first, Claude's queue first, then readiness order; up to LITE_MAX a day until the whole universe is read.
  Stage 2 Flash (gemini-3.8-flash, free 20/day, ~5 min a document): the latest transcript of the stocks Claude reviews next
          (queue order: full reviews, enrich, rechecks), then the top-ranked stocks Claude has not reviewed; up to FLASH_MAX a day.
  Stage 3 Claude: research packs carry the best reader's rows on each document (Flash over Flash-Lite); Claude confirms or
          rejects each in context and looks for anything missed (RESEARCH.md).

Daily (python -m narrativ.reader --daily), after the daily run (.github/workflow-src/reader.yml). Files:
  data/reader/docs.json   documents to read (written by run.py through narrativ.packs.doc_index)
  data/reader/store.json  per document URL: rows kept, rows dropped by reason, model, date, seconds, errors
  data/reader/stats.jsonl one line a day: documents read per stage, verified %, errors, agreement with Claude's reviews
  docs/data/forward.json  per stock: latest document read, rows, dated triggers (orders the enrich queue in run.py)
Test (python -m narrativ.reader --test MODEL [LIMIT]): compare a model with Claude's items on the stocks Claude reviewed
(data/reader_test/; results 19 Nov 2026: Flash-Lite found 51% of Claude's items on 56 stocks, 95% quotes verified, 13 s a
document; Flash found 74% on 4 stocks, 97% verified, 317 s a document).
Lanes (owner, 26 Nov 2026; narrativ/quota.py guards the free allowance per model per Pacific day, data/reader/usage.json):
  lite  = stage 1: Gemini 3.5 Flash-Lite, then 3.1 Flash-Lite (400, the rest is the story job's), then 2.5 Flash-Lite.
  flash = stage 2: Gemini 4 Hydrogen, 3.8, 3.6, 3, 2.5 Flash, 19 a day each.
  agreement: on a document both lanes read, a row either model found in the other's rows is marked agree=True; agreed rows
         go first in forward.json and the packs. Claude still confirms every row it uses.
  check = Gemma 4 31B, then 26B: each dated row against the text around its quote; the row keeps check "ok" / "doubt: ...".
Key: GEMINI_API_KEY (GitHub secret). Free-tier limits (owner's project, 19 Nov 2026): gemini-3.8-flash 5/min, 20/day;
gemini-3.5-flash-lite 15/min, 500/day; 250K tokens a minute each; daily limits reset at midnight Pacific (~13:30 IST).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from collections import Counter
from pathlib import Path

import requests

from narrativ import packs
from narrativ.quota import USAGE, Quota, resolve, tokens
from narrativ.verify import nums, quoted_in

API = "https://generativelanguage.googleapis.com/v1beta"
LITE, FLASH = "gemini-3.5-flash-lite", "gemini-3.8-flash"
LITE_MAX, FLASH_MAX = 450, 18  # requests a day, under the free 500 and 20 (room for retries); --test only
# Lanes (owner, 26 Nov 2026): each lane walks its models in order; when one model's free allowance for the day is used (or it
# is refused twice), the lane moves to the next. Ids are matched against the key's model list (quota.resolve).
LITE_LANE = [r"^gemini-3\.5-flash-lite", r"^gemini-3\.1-flash-lite", r"^gemini-2\.5-flash-lite"]
FLASH_LANE = [r"hydrogen", r"^gemini-3\.8-flash(?!-lite)", r"^gemini-3\.6-flash(?!-lite)", r"^gemini-3-flash(?!-lite)",
              r"^gemini-2\.5-flash(?!-lite)"]
CHECK_LANE = [r"^gemma-4-31b", r"^gemma-4-26b"]
LANE_CAP = {"gemini-3.1-flash-lite": 400}  # leave ~100 of its 500 a day for the story job's fallback
MINUTES = 170  # stop starting new documents after this (job limit 200)
STORE, DOCS, STATS = Path("data/reader/store.json"), Path("data/reader/docs.json"), Path("data/reader/stats.jsonl")
FORWARD = Path("docs/data/forward.json")
DATED = {"guidance", "order", "capacity", "capex", "product", "margin"}  # kinds that can be a dated trigger (RULES.md R4)
PACE = {"flash-lite": 4.5, "flash": 13.0}  # seconds between requests: under 15/min and 5/min
OUT = Path("data/reader_test")
MAX_DOC_CHARS = 400_000  # a long transcript is ~100K characters; anything far larger is not a call
SAVE_EVERY = 20 * 60  # seconds between saves to main during a run (READER_SAVE=1, set by reader.yml)
OWN = (STORE, STATS, FORWARD, USAGE)  # files only the reader writes: a save puts these back on the latest main, never merges them
_last_save = [time.time()]

KINDS = ["guidance", "order", "capacity", "capex", "margin", "product", "demand", "risk", "other"]
SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "text": {"type": "string"},
        "value": {"type": "number", "nullable": True},
        "unit": {"type": "string", "nullable": True},
        "due": {"type": "string", "nullable": True},
        "speaker": {"type": "string", "nullable": True},
        "conditions": {"type": "string", "nullable": True},
        "quote": {"type": "string"}},
        "required": ["kind", "text", "quote"]}}},
    "required": ["items"]}

PROMPT = """You read one filed document of an Indian listed company (an earnings call transcript or an investor presentation).
List every forward-looking statement by management that could move future earnings: revenue or profit guidance, order wins and
order book, capacity additions and commissioning dates, capex plans, margin outlook, new products or markets, demand
commentary, and risks management names. Read the whole document, including the analysts' questions, so that you keep
qualifiers and conditions that appear later ("only if", "subject to approval", "we have withdrawn that guidance").

Rules:
- quote: copy the sentence(s) exactly as written in the document, character for character, 1 to 3 sentences. Never
  paraphrase, fix grammar or join text from different places. A quote that is not found verbatim is discarded.
- text: one plain sentence saying what was said. Numbers in text must appear in the quote.
- value/unit: the main number and its unit as stated (e.g. 1000, "Rs crore"; 20, "%"); null if none.
- due: the date or period it refers to, as YYYY-MM-DD (end of that period, e.g. FY27 -> 2027-03-31, Q3 FY27 -> 2026-12-31);
  null if none.
- conditions: any qualifier or condition stated anywhere in the document; null if none.
- Only management statements, not analysts' assumptions. Facts only; if nothing qualifies, return an empty list.
"""


def models(key: str) -> list[str]:
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, timeout=30)
    r.raise_for_status()
    return sorted(m["name"].removeprefix("models/") for m in r.json().get("models", [])
                  if "generateContent" in (m.get("supportedGenerationMethods") or []))


def read(key: str, model: str, text: str) -> tuple[list[dict], dict]:
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT + "\n\nDOCUMENT:\n" + text[:MAX_DOC_CHARS]}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0}}
    err = ""
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body,
                              timeout=(30, 900))
        except requests.RequestException as e:  # a slow model can exceed the read timeout; retry, then record the error
            err = f"{type(e).__name__}"
            time.sleep(20)
            continue
        if r.status_code in (429, 404, 400, 403):  # refused or not available: the caller's quota decides (no blind retries)
            return [], {"error": f"HTTP {r.status_code}"}
        if r.status_code >= 500:
            err = f"HTTP {r.status_code}"
            if attempt >= 1:
                break
            time.sleep(20)
            continue
        r.raise_for_status()
        js = r.json()
        cand = (js.get("candidates") or [{}])[0]
        parts = ((cand.get("content") or {}).get("parts") or [])
        raw = "".join(p.get("text", "") for p in parts)
        try:
            items = json.loads(raw).get("items") or []
        except Exception:  # noqa: BLE001
            items = []
        return items, {"usage": js.get("usageMetadata"), "finish": cand.get("finishReason")}
    return [], {"error": err}


_W = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
STOP = set("the a an and or of to in on for by with we our is are be will this that it as at from have has was were".split())


def _toks(s: str) -> set:
    return {w for w in _W.findall(str(s).lower()) if w not in STOP}


def matches(claude: dict, row: dict) -> bool:
    """Same statement: one quote inside the other, or most words shared and every number of the shorter quote present."""
    a, b = str(claude.get("quote") or ""), str(row.get("quote") or "")
    if not a or not b:
        return False
    if quoted_in(a, b) or quoted_in(b, a):
        return True
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    nums = {w for w in short if w[0].isdigit()}
    return len(short & long_) / len(short) >= 0.6 and nums <= long_


def test(model: str, limit: int) -> None:
    key = os.environ["GEMINI_API_KEY"]
    have = models(key)
    print(f"[reader] models with generateContent: {', '.join(m for m in have if 'gemini' in m)}")
    if model not in have:
        print(f"[reader] {model} not available to this key")
        sys.exit(1)
    pace = PACE["flash-lite" if "lite" in model else "flash"]
    th = json.loads(Path("docs/data/theses.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    out_f = OUT / f"{model}.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    # readiness order (picks.json "rk"): the stocks closest to a Buy are tested first
    rk = {r["s"]: r.get("rk") or 10 ** 9 for r in json.loads(Path("docs/data/picks.json").read_text()).get("picks") or []}
    reviewed = sorted((s for s, x in th.items() if (x.get("audit") or {}).get("verdict")), key=lambda s: (rk.get(s, 10 ** 9), s))
    ns, n_req = None, 0
    for s in reviewed:
        if s in done:
            continue
        if n_req >= limit:
            break
        x = th[s]
        items = [("driver", d) for d in x.get("drivers") or []] + [("promise", p) for p in x.get("promises") or []]
        src = Counter(str(it.get("source") or "") for _, it in items if str(it.get("source") or "").lower().endswith(".pdf"))
        if not src:
            done[s] = {"skip": "no PDF source in Claude's items"}
            continue
        url = src.most_common(1)[0][0]
        if ns is None:
            from narrativ.filings import NSESession
            ns = NSESession()
        text, pages = packs._text(url, ns)
        if not text or len(text.strip()) < 500:
            done[s] = {"url": url, "skip": "no text layer"}
            continue
        t0 = time.time()
        rows, meta = read(key, model, text)
        n_req += 1
        if meta.get("error"):  # not stored, so a later run retries this stock
            print(f"[reader] {s}: error {meta['error']} after {round(time.time() - t0)}s")
            time.sleep(pace)
            continue
        for r in rows:
            r["verified"] = bool(r.get("quote")) and quoted_in(r["quote"], text)
        claude = [{"type": k, "text": it.get("text") or it.get("promise"), "quote": it.get("quote")}
                  for k, it in items if str(it.get("source") or "") == url and it.get("quote")]
        for c in claude:
            c["found"] = any(matches(c, r) for r in rows if r.get("verified"))
        done[s] = {"url": url, "pages": pages, "chars": len(text), "secs": round(time.time() - t0, 1), "meta": meta,
                   "rows": rows, "claude": claude}
        out_f.write_text(json.dumps(done, ensure_ascii=False, indent=1))
        print(f"[reader] {s}: {len(rows)} rows ({sum(r['verified'] for r in rows)} verified), "
              f"Claude {len(claude)}, found {sum(c['found'] for c in claude)}")
        time.sleep(pace)
    out_f.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    summary(model, done)


def summary(model: str, done: dict) -> dict:
    run = {s: d for s, d in done.items() if "rows" in d}
    rows = [r for d in run.values() for r in d["rows"]]
    cl = [c for d in run.values() for c in d["claude"]]
    extra = sum(1 for d in run.values() for r in d["rows"] if r.get("verified")
                and not any(matches(c, r) for c in d["claude"]))
    s = {"model": model, "stocks_read": len(run), "skipped": {k: v for k, v in Counter(d.get("skip") for d in done.values() if d.get("skip")).items()},
         "reader_rows": len(rows), "verified_pct": round(100 * sum(r.get("verified", False) for r in rows) / len(rows)) if rows else None,
         "claude_items": len(cl), "claude_found_pct": round(100 * sum(c["found"] for c in cl) / len(cl)) if cl else None,
         "extra_verified_rows": extra, "avg_secs": round(sum(d["secs"] for d in run.values()) / len(run), 1) if run else None}
    print("[reader] summary " + json.dumps(s))
    (OUT / f"{model}.summary.json").write_text(json.dumps(s, indent=1))
    return s


IST = timezone(timedelta(hours=5, minutes=30))
DUE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean(rows: list[dict], text: str) -> tuple[list[dict], dict]:
    """Keep a row only if its quote is verbatim in the document. A number in the model's text that is not in the quote is
    flagged (`text_not_in_quote`): the quote is the fact, the text is the model's summary."""
    keep, drop = [], Counter()
    for r in rows:
        q = str(r.get("quote") or "")
        if not q or not quoted_in(q, text):
            drop["quote not verbatim"] += 1
            continue
        extra = sorted(nums(str(r.get("text") or "")) - nums(q))
        if extra:  # the model added context from elsewhere (e.g. "FY27"): kept for Claude, flagged; show the quote, not the text
            drop["flagged: number in text not in quote"] += 1
        if r.get("kind") not in KINDS:
            r["kind"] = "other"
        if r.get("due") and not DUE.match(str(r["due"])):
            r["due"] = None
        row = {k: r.get(k) for k in ("kind", "text", "value", "unit", "due", "speaker", "conditions", "quote")}
        if extra:
            row["text_not_in_quote"] = extra
        keep.append(row)
    return keep, dict(drop)


def _plan(docs: list[dict], store: dict, theses: dict) -> tuple[list[dict], list[dict]]:
    """Stage 1 list (every document not yet read by Flash-Lite) and stage 2 list (Claude's next stocks, latest transcript)."""
    tp = {"review": 0, "audit": 0, "enrich": 1, "recheck": 2, "review_flag": 3}

    def order(d):
        return (tp.get(d.get("task"), 9), d.get("rk") or 10 ** 9, d["kind"] != "transcript", d["s"])
    tried = lambda d, m: (store.get(d["url"]) or {}).get(m) or {}  # noqa: E731
    from narrativ.docread import text_for  # a scanned document becomes readable once docling has OCR'd it

    def retry(d, m):
        e = tried(d, m)
        return (e.get("fails") or 0) < 3 or ("no text" in str(e.get("error") or "") and text_for(d["url"]) is not None)
    lite = sorted([d for d in docs if "rows" not in tried(d, "lite") and retry(d, "lite")], key=order)
    best = {}
    for d in docs:  # one document per stock: the transcript, else the presentation
        if d["s"] not in best or (best[d["s"]]["kind"] != "transcript" and d["kind"] == "transcript"):
            best[d["s"]] = d
    reviewed = {s for s, x in theses.items() if (x.get("audit") or {}).get("verdict")}
    flash = sorted([d for d in best.values() if "rows" not in tried(d, "flash") and retry(d, "flash")
                    and (d.get("task") in tp or (d["s"] not in reviewed and (d.get("rk") or 10 ** 9) <= 200))], key=order)
    return lite, flash


def _stage(fn, name: str, log: dict, *a):
    try:
        fn(*a)
    except Exception as e:  # noqa: BLE001  a crash in one lane must not lose the others' work
        log[f"{name}_crash"] += 1
        print(f"[reader] {name} lane stopped: {type(e).__name__}: {str(e)[:200]}")


def _stage_run(name: str, lane: list[str], todo: list[dict], key: str, store: dict, lock, stop_at: float, ns_box: list, log: dict,
               quota: Quota, checks: list | None = None):
    """One lane: documents in order, each read by the first model of the lane that still has today's allowance."""
    pace = 1.0  # the quota paces by requests and tokens; this only spaces calls a little
    errs: Counter = Counter()
    for d in todo:
        if time.time() > stop_at or not any(quota.left(m) for m in lane):
            break
        with lock:
            if ns_box[0] is None:
                from narrativ.filings import NSESession
                ns_box[0] = NSESession()
            text, pages, _src = packs.doc_text(d["url"], ns_box[0], d.get("kind"))  # follows a cover letter to the real document
            e = store.setdefault(d["url"], {"s": d["s"], "kind": d["kind"], "date": d["date"]})
            if not text or len(text.strip()) < 500:
                e[name] = {"model": lane[0], "at": str(datetime.now(IST).date()), "fails": 3, "error": "no text layer or not reachable"}
                log["no_text"] += 1
                continue
        est = tokens(min(len(text), MAX_DOC_CHARS) + len(PROMPT))
        raw = meta = model = None
        for model in lane:
            if not quota.take(model, est, stop_at, LANE_CAP.get(model)):
                continue
            t0 = time.time()
            raw, meta = read(key, model, text)
            if meta.get("error") == "HTTP 429" and quota.refused(model):  # first refusal: wait a minute, one more try
                time.sleep(60)
                if quota.take(model, est, stop_at, LANE_CAP.get(model)):
                    raw, meta = read(key, model, text)
            if meta.get("error") in ("HTTP 429",):
                quota.refused(model)
                continue  # next model in the lane
            if meta.get("error") in ("HTTP 404", "HTTP 400", "HTTP 403"):
                quota.gone(model)
                log[f"{name}_gone"] += 1
                continue
            break
        if raw is None and meta is None:
            break  # every model of the lane is out for today
        if meta.get("error"):
            errs[model] += 1
            if errs[model] >= 3:
                quota.gone(model)
            with lock:
                prev = e.get(name) or {}
                e[name] = {"model": model, "fails": (prev.get("fails") or 0) + 1, "error": meta["error"]}
            log[f"{name}_errors"] += 1
            print(f"[reader] {name} {d['s']} ({model}): {meta['error']}")
            continue
        errs[model] = 0
        rows, drop = clean(raw, text)
        with lock:
            e[name] = {"model": model, "at": str(datetime.now(IST).date()), "secs": round(time.time() - t0, 1), "rows": rows,
                       "dropped": drop, "finish": meta.get("finish")}
            STORE.write_text(json.dumps(store, ensure_ascii=False, indent=0))
            if os.environ.get("READER_SAVE") == "1" and time.time() - _last_save[0] > SAVE_EVERY:
                save(store)  # under the lock: the other lanes wait a few seconds
            if checks is not None:  # lane D: dated rows get a second look by Gemma, with the text around the quote
                for i, r in enumerate(rows):
                    if r.get("due") or r.get("value") is not None:
                        checks.append((d["url"], name, i, context(text, r["quote"]), r))
        log[f"{name}_read"] += 1
        log[f"{name}_rows"] += len(rows)
        log[f"{name}:{model}"] += 1
        log[f"{name}_dropped"] += sum(v for k, v in drop.items() if not k.startswith("flagged"))
        print(f"[reader] {name} {d['s']} {d['kind']} ({model}): {len(rows)} kept, {drop or 'none dropped'}, {time.time() - t0:.0f}s")
        time.sleep(pace)


def context(text: str, quote: str, around: int = 1500) -> str:
    """The quote with the text around it (for the row check); the quote alone when its place is not found exactly."""
    i = text.find(quote[:80])
    if i < 0:
        return quote
    return text[max(0, i - around): i + len(quote) + around]


CHECK_PROMPT = """You check one row extracted from an Indian company's filed document. Use only the text below.
Extracted: value={value} unit={unit} due={due} (due = end of the period the statement refers to, YYYY-MM-DD)
Quote: {quote}
Text around the quote: {ctx}
Is the value and unit what the quote states, and does the due date match the period it refers to (FY27 ends 2027-03-31,
Q3 FY27 ends 2026-12-31)? Is it a management statement, not an analyst's question? Reply with JSON only:
{{"ok": true or false, "why": "if not ok, the problem in at most 12 words"}}"""


def check_rows(lane: list[str], checks: list, done_flag: threading.Event, key: str, store: dict, lock, stop_at: float,
               log: dict, quota: Quota) -> None:
    """Lane D: Gemma 4 checks each dated row against the text around its quote. The row keeps `check`: "ok" or "doubt: ...";
    Claude sees it in the pack. A row not checked by the end of the run stays unchecked."""
    while time.time() < stop_at:
        if not checks:
            if done_flag.is_set():
                return
            time.sleep(5)
            continue
        url, name, i, ctx, r = checks.pop(0)
        p = CHECK_PROMPT.format(value=r.get("value"), unit=r.get("unit"), due=r.get("due"), quote=r.get("quote"), ctx=ctx[:6000])
        model = next((m for m in lane if quota.take(m, tokens(len(p), 150), stop_at)), None)
        if not model:
            return
        try:
            res = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, timeout=(30, 120),
                                json={"contents": [{"parts": [{"text": p}]}], "generationConfig": {"temperature": 0}})
        except requests.RequestException:
            log["check_errors"] += 1
            continue
        if res.status_code == 429:
            if quota.refused(model):
                time.sleep(60)
            checks.insert(0, (url, name, i, ctx, r))
            continue
        if res.status_code != 200:
            log["check_errors"] += 1
            if res.status_code in (400, 403, 404):
                quota.gone(model)
            continue
        try:
            t = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            v = json.loads(t[t.find("{"): t.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            log["check_errors"] += 1
            continue
        verdict = "ok" if v.get("ok") is True else "doubt: " + str(v.get("why") or "not confirmed")[:90]
        with lock:
            rows = ((store.get(url) or {}).get(name) or {}).get("rows") or []
            if i < len(rows) and rows[i].get("quote") == r.get("quote"):
                rows[i]["check"] = verdict
        log["check_ok" if verdict == "ok" else "check_doubt"] += 1


def agreement(store: dict, theses: dict) -> dict:
    """For documents Claude reviewed after a reader read them: share of Claude's items the reader found, and share of the
    reader's rows Claude used (quotes matched as in the test)."""
    out = {}
    for m in ("lite", "flash"):
        found = total = used = rows_n = 0
        for url, e in store.items():
            r = e.get(m) or {}
            th = theses.get(e.get("s")) or {}
            a = str((th.get("audit") or {}).get("date") or "")[:10]
            if "rows" not in r or not a or a < (r.get("at") or "9"):
                continue
            fn = url.rsplit("/", 1)[-1].lower()  # same file on nsearchives.nseindia.in and .com
            cl = [it for it in (th.get("drivers") or []) + (th.get("promises") or [])
                  if str(it.get("source") or "").rsplit("/", 1)[-1].lower() == fn and it.get("quote")]
            if not cl:
                continue
            total += len(cl); rows_n += len(r["rows"])
            found += sum(1 for c in cl if any(matches(c, x) for x in r["rows"]))
            used += sum(1 for x in r["rows"] if any(matches(c, x) for c in cl))
        out[m] = {"claude_items": total, "found_pct": round(100 * found / total) if total else None,
                  "reader_rows": rows_n, "used_pct": round(100 * used / rows_n) if rows_n else None}
    return out


def label_agreement(store: dict) -> int:
    """Lane C: on a document both lanes read, each row is marked agree=True when the other lane's model found the same
    statement (matches()), else False. Rows both found go first for Claude; a single-model row is still shown. Returns the
    number of rows marked agreed."""
    n = 0
    for e in store.values():
        a, b = (e.get("lite") or {}).get("rows"), (e.get("flash") or {}).get("rows")
        if not a or not b:
            continue
        for x, other in ((a, b), (b, a)):
            for r in x:
                r["agree"] = any(matches(r, o) for o in other)
                n += r["agree"]
    return n


def forward(store: dict) -> dict:
    """docs/data/forward.json: per stock, the latest document read and its rows (Flash over Flash-Lite)."""
    label_agreement(store)
    st = {}
    for url, e in store.items():
        r = next((e[m] for m in ("flash", "lite") if "rows" in (e.get(m) or {})), None)
        if r is None:
            continue
        cur = st.get(e["s"])
        if cur and (cur["date"], cur["kind"] == "transcript") >= (e["date"], e["kind"] == "transcript"):
            continue
        st[e["s"]] = {"date": e["date"], "kind": e["kind"], "url": url, "model": r.get("model"), "read": r.get("at"),
                      "rows": len(r["rows"]), "dated": sum(1 for x in r["rows"] if x.get("due") and x.get("kind") in DATED),
                      "agreed": sum(1 for x in r["rows"] if x.get("agree")),
                      "items": sorted(r["rows"], key=lambda x: not x.get("agree"))}
    doc = {"date": str(datetime.now(IST).date()),
           "note": "Found by free models; quotes verified verbatim by code. Not confirmed by Narrativ.ai unless the stock's review uses them.",
           "stocks": st}
    FORWARD.write_text(json.dumps(doc, ensure_ascii=False, indent=0))
    return doc


def patch_packs(store: dict) -> int:
    n = 0
    for f in packs.OUT.glob("*.json"):
        pk = json.loads(f.read_text())
        hit = [packs.attach_reader(d, store) for d in pk.get("documents") or [] if d.get("kind") in ("transcript", "presentation")]
        if any(hit):
            f.write_text(json.dumps(pk, ensure_ascii=False, indent=0, default=str))
            n += 1
    return n


def _git(*a: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], capture_output=True, text=True, check=check)


def save(store: dict, tries: int = 5) -> bool:
    """Commit the reader's work onto the latest main and push, conflict-free by construction: the work tree is reset to
    origin/main, the reader's own files (OWN; nothing else writes them) are put back, and reader rows are attached to main's
    current packs. A rebase of the whole run's commit failed on 23 Nov 2026 (the daily run had rewritten packs meanwhile)
    and lost ~2 hours of reading and the day's free quota; saving every SAVE_EVERY also caps what a crash can lose."""
    _last_save[0] = time.time()
    label_agreement(store)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=0))
    forward(store)
    keep = {p: p.read_bytes() for p in OWN if p.exists()}
    for i in range(tries):
        try:
            _git("fetch", "-q", "origin", "main")
            _git("reset", "-q", "--hard", "origin/main")
            for p, b in keep.items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b)
            n = patch_packs(store)
            _git("add", "-A", "--", *[str(p) for p in (*OWN, packs.OUT) if p.exists()])
            if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
                return True
            _git("-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                 "commit", "-q", "-m", f"data: reader {datetime.now(IST):%Y-%m-%d %H:%M} IST")
            if _git("push", "-q", "origin", "HEAD:main", check=False).returncode == 0:
                print(f"[reader] saved to main ({sum(1 for e in store.values() for m in ('lite', 'flash') if 'rows' in (e.get(m) or {}))} documents read, {n} packs patched)")
                if os.environ.get("CLOUDFLARE_API_TOKEN"):  # patched packs to R2, after the push (never fatal)
                    from . import appsync
                    appsync.sync()
                return True
        except subprocess.CalledProcessError as e:
            print(f"[reader] save attempt {i + 1}: git {' '.join(e.cmd[1:3])}: {(e.stderr or '').strip()[:200]}")
        time.sleep(5 * (i + 1))
    print("::error::reader: saving to main failed after retries")
    return False


def daily() -> None:
    key = os.environ["GEMINI_API_KEY"]
    t0 = time.time()
    docs = json.loads(DOCS.read_text())["docs"] if DOCS.exists() else []
    store = json.loads(STORE.read_text()) if STORE.exists() else {}
    theses = json.loads(Path("docs/data/theses.json").read_text())
    lite, flash = _plan(docs, store, theses)
    try:
        have = models(key)
    except Exception as e:  # noqa: BLE001  the list call failing must not stop the run: use the known ids
        print(f"[reader] model list failed ({type(e).__name__}); using known ids")
        have = [LITE, "gemini-3.1-flash-lite", FLASH, "gemma-4-31b-it"]
    lanes = {"lite": resolve(LITE_LANE, have), "flash": resolve(FLASH_LANE, have), "check": resolve(CHECK_LANE, have)}
    print(f"[reader] {len(docs)} documents indexed; to read: lite lane {len(lite)}, flash lane {len(flash)}; lanes {lanes}")
    log, lock, ns_box, quota = Counter(), threading.Lock(), [None], Quota()
    stop_at = t0 + MINUTES * 60
    checks, lanes_done = [], threading.Event()
    th = [threading.Thread(target=_stage, args=(_stage_run, "lite", log, "lite", lanes["lite"], lite, key, store, lock, stop_at, ns_box, log, quota, checks)),
          threading.Thread(target=_stage, args=(_stage_run, "flash", log, "flash", lanes["flash"], flash, key, store, lock, stop_at, ns_box, log, quota, checks))]
    ck = threading.Thread(target=_stage, args=(check_rows, "check", log, lanes["check"], checks, lanes_done, key, store, lock, stop_at, log, quota))
    for t in th:
        t.start()
    ck.start()
    for t in th:
        t.join()
    lanes_done.set()
    ck.join()
    label_agreement(store)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=0))
    fw = forward(store)
    n_packs = patch_packs(store)
    read_all = lambda m: sum(1 for e in store.values() if "rows" in (e.get(m) or {}))  # noqa: E731
    line = {"date": str(datetime.now(IST).date()), "minutes": round((time.time() - t0) / 60), **dict(log),
            "lite_left": len(lite) - log["lite_read"], "flash_left": len(flash) - log["flash_read"],
            "docs_indexed": len(docs), "read_lite_total": read_all("lite"), "read_flash_total": read_all("flash"),
            "stocks_with_rows": len(fw["stocks"]), "packs_patched": n_packs, "agreement": agreement(store, theses),
            "rows_agreed": sum(s.get("agreed") or 0 for s in fw["stocks"].values()), "checks_left": len(checks),
            "lanes": lanes, "usage": quota.day()}
    with STATS.open("a") as f:
        f.write(json.dumps(line) + "\n")
    print("[reader] " + json.dumps(line))
    if os.environ.get("READER_SAVE") == "1" and not save(store):
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1] == "--test":
        test(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1000)
    elif sys.argv[1] == "--daily":
        daily()
    elif sys.argv[1] == "--save":  # after a crash: save whatever the run wrote to data/reader/store.json
        sys.exit(0 if save(json.loads(STORE.read_text()) if STORE.exists() else {}) else 1)
    elif sys.argv[1] == "--models":
        print("\n".join(models(os.environ["GEMINI_API_KEY"])))
