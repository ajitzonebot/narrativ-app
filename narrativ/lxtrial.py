"""Trial (owner request 20 Nov 2026): google/langextract as the stage-1 reader, on the same stocks and documents as the
reader test (data/reader_test/gemini-3.5-flash-lite.json: our single-call reader found 51% of Claude's items).

langextract splits a document into chunks, reads each chunk in several passes for recall, and locates every extraction in
the source text (`char_interval`; None = not found, dropped). The extraction text is the quote; our verifier
(verify.quoted_in) re-checks it. Requests: about ceil(chars / BUFFER) x PASSES per document against the free 500/day, so the
trial runs LIMIT documents a day and resumes. Output data/reader_test/langextract-<model>.json (+ .summary.json), same
measures as the reader test.
python -m narrativ.lxtrial [LIMIT]
"""
import json
import os
import sys
import time

from narrativ import packs, reader
from narrativ.verify import quoted_in

MODEL, BUFFER, PASSES, WORKERS = "gemini-3.5-flash-lite", 25_000, 2, 1  # 1 worker: stay under 250K tokens a minute
BASE = reader.OUT / f"{MODEL}.json"

PROMPT = """From an Indian listed company's earnings call transcript or investor presentation, extract every forward-looking
statement by management that could move future earnings: guidance, order wins and order book, capacity additions and
commissioning dates, capex plans, margin outlook, new products or markets, demand commentary, and risks management names.
Use the exact text of the document for each extraction (1 to 3 full sentences, copied character for character, never
paraphrased). Only management statements, not analysts' questions. Attributes: summary (one plain sentence), due (YYYY-MM-DD
end of the period it refers to, e.g. FY27 -> 2027-03-31, or none), conditions (any qualifier stated, or none)."""


def _examples():
    import langextract as lx
    t = ("Analyst: What about capacity? Management: Our new plant in Gujarat with 12,000 tonnes capacity will be commissioned "
         "by March 2027. We are guiding for revenue growth of about 18% to 20% in FY27, subject to raw material prices staying "
         "stable. Our order book stands at Rs. 2,450 crore, which is 2.1 times last year's revenue.")
    E = lx.data.Extraction
    return [lx.data.ExampleData(text=t, extractions=[
        E(extraction_class="capacity", extraction_text="Our new plant in Gujarat with 12,000 tonnes capacity will be commissioned by March 2027.",
          attributes={"summary": "A 12,000 tonne Gujarat plant is due by March 2027.", "due": "2027-03-31", "conditions": "none"}),
        E(extraction_class="guidance", extraction_text="We are guiding for revenue growth of about 18% to 20% in FY27, subject to raw material prices staying stable.",
          attributes={"summary": "Revenue growth guided at 18% to 20% for FY27.", "due": "2027-03-31", "conditions": "raw material prices stable"}),
        E(extraction_class="order", extraction_text="Our order book stands at Rs. 2,450 crore, which is 2.1 times last year's revenue.",
          attributes={"summary": "Order book of Rs. 2,450 crore, 2.1 times last year's revenue.", "due": "none", "conditions": "none"}),
    ])]


def run(limit: int) -> None:
    import langextract as lx
    key = os.environ["GEMINI_API_KEY"]
    base = json.loads(BASE.read_text())
    out_f = reader.OUT / f"langextract-{MODEL}.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    ns, n = None, 0
    for s, b in base.items():  # same stocks, same document, same order as the reader test
        if s in done and "rows" in done[s] or "rows" not in b:
            continue
        if n >= limit:
            break
        if ns is None:
            from narrativ.filings import NSESession
            ns = NSESession()
        text, _ = packs._text(b["url"], ns)
        if not text:
            continue
        t0 = time.time()
        n += 1
        res = None
        for attempt in range(2):  # 429 is usually the per-minute token limit (250K/min): wait a minute, retry once
            try:
                res = lx.extract(text_or_documents=text[:reader.MAX_DOC_CHARS], prompt_description=PROMPT, examples=_examples(),
                             model_id=MODEL, api_key=key, extraction_passes=PASSES, max_workers=WORKERS,
                                 max_char_buffer=BUFFER)
                break
            except Exception as e:  # noqa: BLE001  quota or model errors: retried on the next run
                err = f"{type(e).__name__}: {str(e)[:160]}"
                print(f"[lx] {s}: {err}")
                if attempt == 0 and ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)):
                    time.sleep(65)
        if res is None:
            done[s] = {"url": b["url"], "error": err}
            out_f.write_text(json.dumps(done, ensure_ascii=False, indent=1))
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                break
            continue
        rows = []
        for x in res.extractions or []:
            a = x.attributes or {}
            rows.append({"kind": x.extraction_class, "text": a.get("summary"), "due": a.get("due"), "conditions": a.get("conditions"),
                         "quote": x.extraction_text, "located": x.char_interval is not None,
                         "verified": x.char_interval is not None and quoted_in(x.extraction_text or "", text)})
        claude = [dict(c) for c in b["claude"]]
        for c in claude:
            c["found"] = any(reader.matches(c, r) for r in rows if r["verified"])
        done[s] = {"url": b["url"], "chars": len(text), "secs": round(time.time() - t0, 1), "rows": rows, "claude": claude}
        out_f.write_text(json.dumps(done, ensure_ascii=False, indent=1))
        print(f"[lx] {s}: {len(rows)} rows ({sum(r['verified'] for r in rows)} verified), Claude {len(claude)}, "
              f"found {sum(c['found'] for c in claude)} (single-call reader found {sum(c['found'] for c in b['claude'])})")
    s = reader.summary(f"langextract-{MODEL}", done)
    run_ = [k for k, d in done.items() if "rows" in d]
    same = [c for k in run_ for c in base[k]["claude"]]
    s["baseline_same_stocks_found_pct"] = round(100 * sum(c["found"] for c in same) / len(same)) if same else None
    (reader.OUT / f"langextract-{MODEL}.summary.json").write_text(json.dumps(s, indent=1))
    print("[lx] vs single-call reader on the same stocks: " + json.dumps(s))


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 28)
