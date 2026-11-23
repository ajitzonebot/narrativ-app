"""Layout-aware reading with docling (docling-project/docling, MIT), for what pypdf cannot read well:
  - scanned PDFs (no text layer): OCR
  - investor presentations: tables keep their rows and columns (pypdf runs table cells together)
Runs after the daily run (.github/workflows/docling.yml), at most MAX_DOCS documents and MAX_MINUTES a day, in this order:
documents of stocks in Claude's queue (presentations, and transcripts with poor text), then documents the readers could
not read (no text layer). Output data/docling/<sha1(url)>.md (git, so every job sees the same text; its first line
records the source URL, HEAD) and an index.

Used by: packs (`tables` on a presentation, full text for a scanned document), the reader (scanned documents become
readable), and verify.fetch_text (a quote is accepted if it is verbatim in the pypdf text or in this text). OCR text can
contain recognition errors; a quote copied from it is verbatim to the OCR text, which packs flag as `ocr`.
"""
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DIR = Path("data/docling")
INDEX = DIR / "index.json"
MAX_DOCS, MAX_MINUTES = 40, 60
IST = timezone(timedelta(hours=5, minutes=30))


def key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


HEAD = "<!-- source: {} -->\n"  # first line of every converted file: the URL it was read from


def _read(url: str) -> tuple[str | None, str | None]:
    """(text without the source line, URL the file records or None for a file written before the line existed)."""
    f = DIR / f"{key(url)}.md"
    if not f.exists():
        return None, None
    t = f.read_text()
    first, _, rest = t.partition("\n")
    if first.startswith("<!-- source: ") and first.endswith(" -->"):
        return rest, first[len("<!-- source: "):-len(" -->")]
    return t, None


def text_for(url: str) -> str | None:
    t, src = _read(url)
    return None if src is not None and src != url else t


def source_text(url: str) -> str | None:
    """Text for quote checks (narrativ/verify.py): only from a file that records this same URL and that the index
    lists as converted from it, so text from another document can never verify a quote whose link is dead."""
    t, src = _read(url)
    return t if t is not None and src == url and meta(url).get("ok") else None


def meta(url: str) -> dict:
    if not INDEX.exists():
        return {}
    return json.loads(INDEX.read_text()).get(url) or {}


def tables(md: str, cap: int = 6000) -> list[str]:
    """Markdown tables from docling output, in order, up to `cap` characters."""
    out, cur, n = [], [], 0
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            cur.append(line)
        elif cur:
            t = "\n".join(cur)
            if n + len(t) > cap:
                break
            out.append(t); n += len(t); cur = []
    return out


def convert(pdf: bytes, ocr: bool) -> str:
    from docling.datamodel.base_models import DocumentStream, InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    opts = PdfPipelineOptions()
    opts.do_ocr = ocr
    opts.do_table_structure = True
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    res = conv.convert(DocumentStream(name="doc.pdf", stream=io.BytesIO(pdf)))
    return res.document.export_to_markdown()


def plan() -> list[dict]:
    docs = json.loads(Path("data/reader/docs.json").read_text())["docs"] if Path("data/reader/docs.json").exists() else []
    store = json.loads(Path("data/reader/store.json").read_text()) if Path("data/reader/store.json").exists() else {}
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    poor = set()
    for f in Path("docs/data/packs").glob("*.json"):
        for d in json.loads(f.read_text()).get("documents") or []:
            if d.get("url") and ((d.get("quality") or {}).get("grade") == "poor" or d.get("has_text") is False):
                poor.add(d["url"])
    no_text = {u for u, e in store.items() if any("no text" in str((e.get(m) or {}).get("error") or "") for m in ("lite", "flash"))}
    todo = []
    for d in docs:
        u = d["url"]
        if u in idx and (idx[u].get("ok") or (idx[u].get("tries") or 0) >= 2):
            continue
        scanned = u in poor or u in no_text
        if d.get("task") and (d["kind"] == "presentation" or scanned):
            todo.append({**d, "ocr": scanned, "why": "Claude's queue"})
        elif scanned:
            todo.append({**d, "ocr": True, "why": "no text layer"})
    todo.sort(key=lambda d: (d["why"] != "Claude's queue", d.get("rk") or 10 ** 9))
    return todo


def run() -> None:
    from narrativ.filings import NSESession
    from narrativ.packs import _pdf_bytes
    DIR.mkdir(parents=True, exist_ok=True)
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    todo, t0, ns, n = plan(), time.time(), NSESession(), 0
    print(f"[docling] {len(todo)} documents to read; this run up to {MAX_DOCS} / {MAX_MINUTES} min")
    for d in todo[:MAX_DOCS]:
        if time.time() - t0 > MAX_MINUTES * 60:
            break
        u, t1 = d["url"], time.time()
        e = idx.setdefault(u, {"s": d["s"], "kind": d["kind"]})
        try:
            pdf = _pdf_bytes(u, ns)
            if not pdf:
                raise ValueError("not reachable")
            md = convert(pdf, d["ocr"])
            if not d["ocr"]:  # slides that are images: little text without OCR (SEAMECLTD: 2,509 characters) -> OCR them
                from pypdf import PdfReader
                pages = len(PdfReader(io.BytesIO(pdf)).pages) or 1
                if len(md) / pages < 300:
                    d["ocr"] = True
                    md = convert(pdf, True)
            if len(md.strip()) < 200:
                raise ValueError("no text after conversion")
            (DIR / f"{key(u)}.md").write_text(HEAD.format(u) + md)
            e.update({"ok": True, "ocr": d["ocr"], "at": str(datetime.now(IST).date()), "chars": len(md),
                      "tables": len(tables(md, 10 ** 9)), "secs": round(time.time() - t1)})
            n += 1
            print(f"[docling] {d['s']} {d['kind']}{' (OCR)' if d['ocr'] else ''}: {len(md)} chars, {e['tables']} tables, {e['secs']}s")
        except Exception as ex:  # noqa: BLE001
            e.update({"ok": False, "tries": (e.get("tries") or 0) + 1, "error": f"{type(ex).__name__}: {str(ex)[:120]}"})
            print(f"[docling] {d['s']}: {e['error']}")
        INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=0))
    print(f"[docling] {n} converted in {round((time.time() - t0) / 60)} min")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        MAX_DOCS = int(sys.argv[1])
    run()
