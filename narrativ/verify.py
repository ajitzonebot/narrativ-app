"""Source verification for Claude research.

Rule: a figure is shown in the app only if
  1. its `quote` is found word-for-word (whitespace-insensitive, starting and ending on a word or number boundary,
     at least `long_enough`) in the document at `source`, and
  2. every number in the display text (`promise`, `actual`, `text`) also appears in that quote, with the same unit
     (crore / lakh / million / % / bps) when the text gives one.
A driver's `due` date counts as a dated trigger (RULES.md R4) only if the quote states it (`due_support`).
Anything that fails is withheld from the app and listed in docs/data/verification.json with the reason.
"""
import hashlib
from functools import lru_cache
from datetime import date, timedelta
import io
import json
import re
from pathlib import Path

import requests

CACHE = Path("data/source_cache")
UA = {"User-Agent": "Mozilla/5.0 (research verifier)"}
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[‐-―−]", "-", s)
    s = re.sub(r"[‘’‚‛]", "'", s)
    s = re.sub(r"[“”„]", '"', s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


MIN_QUOTE_ALNUM, MIN_QUOTE_DIGITS = 12, 5  # shorter quotes ('Rs 50', '15% growth') turn up in almost any document


def long_enough(q: str) -> bool:
    """A quote must carry at least 12 letters/digits, or (a statement figure such as '2,187.19') at least 5 digits."""
    return sum(c.isalnum() for c in q) >= MIN_QUOTE_ALNUM or sum(c.isdigit() for c in q) >= MIN_QUOTE_DIGITS


def _in_number(b: str, i: int, step: int) -> bool:
    """b[i] is a '.' or ',' next to a digit: True if a digit also sits on its other side (inside '1,500' or '2.5')."""
    k = i + step
    return b[i] in ".," and 0 <= k < len(b) and b[k].isdigit()


def _same_class(x: str, y: str) -> bool:
    return (x.isalpha() and y.isalpha()) or (x.isdigit() and y.isdigit())


def _edges_ok(b: str, i: int, j: int, squeezed: bool, table: bool) -> bool:
    """The match b[i:j] neither starts nor ends inside a word or a number ('rs 50' in 'rs 500', '20%' in '120%').
    A letter next to a digit is a boundary (PDF text runs cells together: 'total equity71355', 'rs500'), except
    a number running into letters at the end of a prose quote ('rs 50' in 'rs 50mn', '15' in '15x').
    squeezed (whitespace-free match, which already reads '50 0' as '500'): a prose quote's edge number also may not
    continue, past spaces, into another digit. Table rows (`table`: 2+ numbers) are exempt from both: their edge cell
    sits next to the next cell or the next row's label."""
    first, last = b[i], b[j - 1]
    before = b[i - 1] if i > 0 else " "
    after = b[j] if j < len(b) else " "
    if _same_class(first, before) or _same_class(last, after) or (last.isdigit() and after.isalpha() and not table):
        return False
    if first.isdigit() and i >= 1 and _in_number(b, i - 1, -1):  # '500' inside '1,500'
        return False
    if last.isdigit() and j < len(b) and _in_number(b, j, +1):  # '1' inside '1.5'
        return False
    if first in ".," and before.isdigit() and j - i > 1 and b[i + 1].isdigit():  # '.5' inside '2.5'
        return False
    if last in ".," and after.isdigit() and j - i > 1 and b[j - 2].isdigit():  # '2.' inside '2.5'
        return False
    if squeezed and not table:
        k = i - 1
        while k >= 0 and b[k] == " ":
            k -= 1
        if first.isdigit() and k >= 0 and (b[k].isdigit() or _in_number(b, k, -1)):
            return False
        k = j
        while k < len(b) and b[k] == " ":
            k += 1
        if last.isdigit() and k < len(b) and (b[k].isdigit() or _in_number(b, k, +1)):
            return False
    return True


def _finds(a: str, b: str):
    i = b.find(a)
    while i >= 0:
        yield i
        i = b.find(a, i + 1)


@lru_cache(maxsize=8)
def _squeezed(b: str) -> tuple[str, tuple[int, ...]]:
    """b without spaces, and for each kept character its index in b."""
    idx = tuple(i for i, c in enumerate(b) if c != " ")
    return "".join(b[i] for i in idx), idx


def quoted_in(q: str, text: str) -> bool:
    """Verbatim match, ignoring spacing: PDF text extraction adds or drops spaces ('high -value', 'a40% yoygrowth'),
    so if the quote is not found as spaced, both sides are compared with all whitespace removed. Words, digits and
    punctuation must still match exactly, and the match may not start or end inside a word or a number:
    'Rs 50' is not found in 'Rs 500', '20% growth' not in '120% growth'. Quotes shorter than `long_enough` never match."""
    a, b = norm(q), norm(text)
    if not a or not long_enough(a):
        return False
    table = len(NUM.findall(a)) >= 2
    if any(_edges_ok(b, i, i + len(a), False, table) for i in _finds(a, b)):
        return True
    a2 = a.replace(" ", "")
    b2, idx = _squeezed(b)
    return any(_edges_ok(b, idx[i], idx[i + len(a2) - 1] + 1, True, table) for i in _finds(a2, b2))


def nums(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(s or "")}


def _numkey(n: str) -> str:
    n = n.replace(",", "").rstrip(".")
    return n.rstrip("0").rstrip(".") if "." in n else n


# unit words that change a number's size or meaning: 50 lakh is not 50 crore, 20% is not 20 bps
UNITS = (("lakh crore", r"la(?:kh|c)s?\s*crores?"), ("crore", r"crores?|crs?"), ("lakh", r"lakhs?|lacs?"),
         ("million", r"millions?|mn|mio"), ("billion", r"billions?|bn"), ("trillion", r"trillions?|tn"),
         ("thousand", r"thousands?"), ("pct", "%"), ("pct", r"per\s*cent|percent"), ("bps", r"bps|basis\s*points?"))
_UNIT_ALT = "|".join(f"(?P<u{i}>{p}{'' if p == '%' else '(?![a-z])'})" for i, (_, p) in enumerate(UNITS))
_NUM_UNIT = re.compile(r"(\d[\d,]*(?:\.\d+)?)(?:\s*-?\s*(?:" + _UNIT_ALT + "))?")
UNIT_TEXT = {"lakh crore": "lakh crore", "crore": "crore", "lakh": "lakh", "million": "million", "billion": "billion",
             "trillion": "trillion", "thousand": "thousand", "pct": "%", "bps": "bps"}
_UNIT_WORD = re.compile(r"(?<![a-z])(?:" + _UNIT_ALT + ")")


def _unit_name(m: re.Match) -> str | None:
    return next((UNITS[i][0] for i in range(len(UNITS)) if m.group(f"u{i}")), None)


def num_units(s: str) -> dict[str, set]:
    """Each number in s with the unit word right after it (None when there is none)."""
    out: dict[str, set] = {}
    for m in _NUM_UNIT.finditer(norm(s or "")):
        out.setdefault(_numkey(m.group(1)), set()).add(_unit_name(m))
    return out


def unit_of(u: str | None) -> str | None:
    """Unit class of a field's `unit` ('cr', '₹ cr', 'USD mn', '%'); None for units outside UNITS ('MW', 'tonnes')."""
    m = _UNIT_WORD.search(norm(str(u or "")))
    return _unit_name(m) if m else None


@lru_cache(maxsize=8)
def units_in(s: str) -> frozenset:
    """Unit classes whose words appear anywhere in s."""
    return frozenset(_unit_name(m) for m in _UNIT_WORD.finditer(norm(s or "")))


def unit_mismatch(text: str, quote: str, doc: str = "") -> list[str]:
    """Numbers that carry a unit in `text` but not in the quote: there the number has a different unit, or none and
    the unit word is neither elsewhere in the quote nor in the source document (a statement row such as
    'Revenues 574.34 420.51' takes its unit from the table header '(Rs in crore)'). Returns them as '50 lakh'."""
    qu = num_units(quote)
    bad = []
    for n, us in num_units(text).items():
        for u in us - {None}:
            got = qu.get(n, set())
            if u in got or (None in got and (u in units_in(quote) or u in units_in(doc))):
                continue
            bad.append(f"{n} {u}")
    return sorted(bad)


DEAD: set[str] = set()  # failed this run: logged once, not fetched again


def fetch_text(url: str) -> str | None:
    """Source text for quote checks: pypdf text, plus docling's layout-aware or OCR text when it exists
    (narrativ/docread.py), so a quote copied from a pack's `tables` or a scanned document is found. Docling text
    (committed in git) counts even when the link is dead, but only from a file that records this same URL."""
    from .docread import source_text
    t, extra = _fetch_text(url), source_text(url)
    return t + "\n" + extra if t and extra else t or extra


def _fetch_text(url: str) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if key.exists():
        return key.read_text()
    if url in DEAD:
        return None
    try:
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 404 and "/AttachLive/" in url:  # BSE moves older attachments to its archive folder
            r = requests.get(url.replace("/AttachLive/", "/AttachHis/"), headers=UA, timeout=60)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[verify] fetch failed {url}: {e}")
        DEAD.add(url)
        return None
    if r.content[:4] == b"%PDF" or url.lower().endswith(".pdf"):
        from pypdf import PdfReader
        parts = []
        try:  # damaged PDFs: keep the pages that read; a file with none is treated as unreachable
            for p in PdfReader(io.BytesIO(r.content), strict=False).pages:
                try:
                    parts.append(p.extract_text() or "")
                except Exception:  # noqa: BLE001
                    continue
        except Exception as e:  # noqa: BLE001
            print(f"[verify] unreadable PDF {url}: {e}")
        if not any(x.strip() for x in parts):
            return None
        text = "\n".join(parts)
    else:
        text = re.sub(r"<[^>]+>", " ", r.text)
    key.write_text(text)
    return text


_DOS: dict = {}


def _dossier(sym: str) -> dict:
    if sym not in _DOS:
        p = Path(f"docs/data/fin/{sym}.json")
        _DOS[sym] = json.loads(p.read_text()) if p.exists() else {}
    return _DOS[sym]


def machine_count(sym: str) -> int:
    """How many of the code-checked numbers (packs.MACHINE) the dossier has from the NSE XBRL filing."""
    from .packs import MACHINE
    mt = (_dossier(sym) or {}).get("metrics") or {}
    return sum(1 for k in MACHINE if isinstance(mt.get(k), dict) and mt[k].get("v") is not None and "NSE filing" in str(mt[k].get("src") or ""))


def resolve(d, path: str):
    """Dot path into the dossier; inside a list, a part selects the item whose `id` (or `k`) equals it."""
    cur = d
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            lst = cur
            cur = next((x for x in lst if isinstance(x, dict) and str(x.get("id", x.get("k"))) == part), None)
            if cur is None and part.isdigit() and int(part) < len(lst):
                cur = lst[int(part)]
        else:
            return None
        if cur is None:
            return None
    return cur


def _same(a, b) -> bool:
    """A stated fact value matches the dossier value: numbers within 0.5%, else the same text. A blank value never matches."""
    if a is None or not str(a).strip() or b is None or not str(b).strip():
        return False
    try:
        x, y = float(str(a).replace(",", "")), float(str(b).replace(",", ""))
        return abs(x - y) <= 0.005 * max(abs(y), 1e-9)
    except (TypeError, ValueError):
        pass
    na, nb = nums(str(a)), nums(str(b))
    ta, tb = norm(str(a)), norm(str(b))  # text inside text only as whole words / numbers: '5 cr' is not in '15 cr'
    return bool(na and na <= nb) or ta == tb or re.search(r"(?<![\w.,])" + re.escape(ta) + r"(?![\w])", tb) is not None


def _check_point(pt: dict, dos: dict) -> str | None:
    facts = pt.get("facts") or []
    if not dos:
        return "dossier not found (run after the daily Action)"
    for f in facts:
        got = resolve(dos, f.get("path"))
        if got is None:
            return f"path not in dossier: {f.get('path')}"
        if isinstance(got, (dict, list)):
            return f"path points to a group, not a value: {f.get('path')}"
        if not _same(f.get("value"), got):
            return f"{f.get('path')} is {got} in the dossier, not {f.get('value')}"
    if len(facts) < 2 and not (pt.get("quote") and facts):
        return "needs two dossier facts, or one fact and a quote"
    cited = set().union(*[nums(str(f.get("value"))) for f in facts]) if facts else set()
    if pt.get("quote"):
        w = check(pt, ())
        if w:
            return w
        cited |= nums(pt["quote"])
    extra = nums(pt.get("text") or "") - cited
    return f"numbers {sorted(extra)} in text are not cited" if extra else None


def check(item: dict, display_keys: tuple[str, ...]) -> str | None:
    """Return None if verified, else the reason."""
    q, src = item.get("quote"), item.get("source")
    if not q or not src:
        return "missing quote or source"
    text = fetch_text(src)
    if text is None:
        return f"source not reachable: {src}"
    if not quoted_in(q, text):
        return "quote not found in source"
    qn = nums(q)
    for k in display_keys:
        extra = nums(item.get(k, "")) - qn
        if extra:
            return f"numbers {sorted(extra)} in '{k}' not in quote"
        bad = unit_mismatch(item.get(k, ""), q, text)  # 50 lakh in the quote is not 50 crore in the text
        if bad:
            return f"units {bad} in '{k}' not in quote"
    return None


def value_check(value, unit, quote: str, doc: str = "") -> str | None:
    """A field's number (`value`, `found_value`, `value_cr`) must sit in the quote, with its unit when the unit changes
    the number's size or meaning (crore, lakh, million, %, bps): None if it does, else the reason."""
    if value is None or str(value).strip() == "":
        return None
    try:
        f = float(str(value).replace(",", ""))
    except ValueError:
        return f"value {value} is not a number"
    n = str(int(f)) if f == int(f) else repr(f)
    if n not in {_numkey(x) for x in nums(quote)}:
        return f"value {value} not in quote"
    u = unit_of(unit)
    bad = unit_mismatch(f"{n} {UNIT_TEXT[u]}", quote, doc) if u else []
    return f"value {value} {unit}: the quote has {n} with another unit or none" if bad else None


# ---------- driver due dates (RULES.md R4): a due date counts only if the quote states it ----------
_MON = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:[a-z]*)\.?"
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
        "one": 1, "two": 2, "three": 3, "four": 4}
_WORDN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty-four": 24, "twenty four": 24, "thirty-six": 36}
BARE_QUARTERS = True  # 'Q4' / 'fourth quarter' with no year = that quarter of the Indian fiscal year it was said in
_FYW = r"(?:fy|f\.y\.|fiscal(?:\s+year)?|financial\s+year)"
# a quarter or half: Q3, 3Q, H1, 1H, third quarter, first half, quarter 4, quarter three
_QH = (r"(?<![a-z0-9])(?:(?P<k1>q|h)(?P<n1>[1-4])|(?P<n2>[1-4])(?P<k2>q|h)|(?P<n3>first|second|third|fourth|1st|2nd|3rd|4th)\s+"
       r"(?P<k3>quarter|half)|(?P<k4>quarter)\s*(?P<n4>[1-4]|one|two|three|four)(?![a-z0-9]))")
# a year, or a fiscal range: 27, '27, 2027, 2026-27, 29/30 (the range ends in its second year)
_YR = r"'?\s*(?P<y1>\d{4}|\d{2})(?:\s*[-/]\s*'?(?P<y2>\d{4}|\d{2}))?(?!\d)"


def _month_end(y: int, m: int) -> date:
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def _yr(s: str) -> int:
    return int(s) if len(s) == 4 else 2000 + int(s)


def _fy_of(d: date) -> int:
    return d.year + 1 if d.month > 3 else d.year


def _fq_end(fy: int, q: int) -> date:
    """Last day of fiscal quarter q (1-4) of Indian fiscal year fy (FY27 = April 2026 to March 2027)."""
    return _month_end(fy - 1, 3 + 3 * q)


def _qh_end(m: re.Match, fy: int) -> date | None:
    """Last day of the quarter / half matched by _QH in fiscal year fy."""
    kind = m.group("k1") or m.group("k2") or ("q" if (m.group("k3") or m.group("k4")) == "quarter" else "h")
    n = next(m.group(g) for g in ("n1", "n2", "n3", "n4") if m.group(g))
    n = int(n) if n.isdigit() else _ORD[n]
    return _fq_end(fy, n) if kind[0] == "q" else _fq_end(fy, 2 * n) if n <= 2 else None


def due_periods(quote: str, said_on: date | None) -> list[tuple[str, date]]:
    """Periods the quote names, as (phrase, last day). Phrases with a year ('FY27', 'Q3 FY27', 'FY29/30',
    'March 2027', 'CY2027', '2027-28', '2027') stand alone; relative ones ('next quarter', 'Q4', 'next two quarters',
    'from November', 'in the coming 12 months', 'next calendar year') are read against the date the source was said
    on, and skipped without it. A quarter or half without a year is the Indian fiscal one of the year it was said in,
    and only if it has not ended by then (a past quarter is history, not a due date); BARE_QUARTERS = False requires a
    stated year. 'This year', 'next year' and 'year-end' are left out: fiscal or calendar cannot be told apart."""
    q = norm(quote)
    out: list[tuple[str, date]] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(a < m.end() and m.start() < b for a, b in taken)

    def add(m: re.Match, end: date | None) -> None:
        taken.append(m.span())
        if end:
            out.append((m.group(0).strip(), end))

    def fy_year(m: re.Match) -> int:
        return _yr(m.group("y2") or m.group("y1"))

    # quarter / half of a fiscal year: Q3 FY27, Q3FY27, 3QFY27, Q4 of FY'27, H1 FY2027, fourth quarter of FY27
    for m in re.finditer(_QH + r"\s*(?:of\s+)?(?:the\s+)?" + _FYW + r"\s*" + _YR, q):
        add(m, _qh_end(m, fy_year(m)))
    # quarter of a calendar year: Q2 2027, Q2 CY27, second quarter of 2027, second quarter of next calendar year
    for m in re.finditer(r"(?<![a-z0-9])(?:q([1-4])|(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter)\s*(?:of\s+)?(?:the\s+)?"
                         r"(?:(?:cy|calendar(?:\s+year)?)\s*'?\s*(\d{4}|\d{2})|(\d{4})|(next|this|current)\s+calendar\s+year)(?![\d-])", q):
        if not free(m) or (m.group(5) and not said_on):
            continue
        y = said_on.year + (m.group(5) == "next") if m.group(5) else _yr(m.group(3) or m.group(4))
        add(m, _month_end(y, 3 * int(m.group(1) or _ORD[m.group(2)])))
    # fiscal year: FY27, FY'27, FY 2027, FY2026-27, FY29/30, fiscal 2027, financial year 2026-27
    for m in re.finditer(r"(?<![a-z0-9])" + _FYW + r"\s*" + _YR, q):
        if free(m):
            add(m, date(fy_year(m), 3, 31))
    # calendar year: CY27, calendar year 2027
    for m in re.finditer(r"(?<![a-z0-9])(?:cy|calendar\s+year|calendar)\s*'?\s*(\d{4}|\d{2})(?!\d)", q):
        if free(m):
            add(m, date(_yr(m.group(1)), 12, 31))
    # month and year: March 2027, Mar'27, May'2027, Mar-27, March 31, 2027, 31st March 2027
    for m in re.finditer(r"(?<![a-z])" + _MONTH + r"\s*(?:(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})|,?\s*(\d{4})|['-]\s*(\d{4}|\d{2}))(?!\d)", q):
        if free(m):
            add(m, _month_end(_yr(m.group(3) or m.group(4) or m.group(5)), _MON[m.group(1)]))
    # a fiscal year written as a range: 2027-28 (ends March 2028)
    for m in re.finditer(r"(?<![\d.,])(20\d{2})\s*[-/]\s*(\d{2})(?!\d|[.,]\d)", q):
        if free(m) and int(m.group(2)) == (int(m.group(1)) + 1) % 100:
            add(m, date(int(m.group(1)) + 1, 3, 31))
    # a bare year: 2027 (calendar 2027, or FY2027 as Indian companies also say it)
    for m in re.finditer(r"(?<![\d.,])(?<!\d[.,])(20[2-4]\d)(?!\d|[.,]\d|%)", q):
        if free(m):
            add(m, date(int(m.group(1)), 12, 31))
            out.append((m.group(0), date(int(m.group(1)), 3, 31)))
    if not said_on:
        return out
    fy = _fy_of(said_on)
    cur_q = (said_on.month - 4) % 12 // 3 + 1  # fiscal quarter it was said in
    for m in re.finditer(r"(?<![a-z])(?:next|coming)\s+(\d|" + "|".join(_WORDN) + r")\s+quarters(?![a-z])", q):
        if free(m):  # next N quarters: to the end of the Nth quarter after the current one
            n = int(m.group(1)) if m.group(1).isdigit() else _WORDN[m.group(1)]
            add(m, _month_end(_fq_end(fy, cur_q).year, _fq_end(fy, cur_q).month + 3 * n))
    for m in re.finditer(_QH + r"(?![a-z0-9])", q):  # a quarter or half with no year
        end = _qh_end(m, fy) if free(m) and BARE_QUARTERS else None
        if end and end >= said_on:
            add(m, end)
        elif free(m):
            taken.append(m.span())
    rel = (
        (r"(?:next|coming|following)\s+quarter", _fq_end(fy + (cur_q == 4), cur_q % 4 + 1)),
        (r"(?:this|current|ongoing)\s+quarter", _fq_end(fy, cur_q)),
        (r"(?:this|current|ongoing)\s+(?:fiscal|financial\s+year)(?:\s+year)?", date(fy, 3, 31)),
        (r"(?:next|coming|following)\s+(?:fiscal|financial\s+year)(?:\s+year)?", date(fy + 1, 3, 31)),
        (r"(?:this|current)\s+calendar\s+year|end\s+of\s+(?:this|the)\s+calendar\s+year", date(said_on.year, 12, 31)),
        (r"next\s+calendar\s+year", date(said_on.year + 1, 12, 31)),
    )
    for pat, end in rel:
        for m in re.finditer(r"(?<![a-z])(?:" + pat + r")(?![a-z])", q):
            if free(m):
                add(m, end)
    # within / in / over the next (or coming) N months (or years)
    for m in re.finditer(r"(?<![a-z])(?:within|in|over|next)\s+(?:the\s+)?(?:next\s+|coming\s+)?(\d{1,2}|" + "|".join(_WORDN)
                         + r")\s*-?\s*(months?|years?)(?![a-z])", q):
        if free(m):
            n = int(m.group(1)) if m.group(1).isdigit() else _WORDN[m.group(1)]
            add(m, _month_end(said_on.year, said_on.month + n * (12 if m.group(2).startswith("year") else 1)))
    # a month with no year after a time word ('from November', 'by March'): its next occurrence from the date said on.
    # 'may' only as 'month of May' (otherwise it is the verb)
    for m in re.finditer(r"(?<![a-z])(?:from|by|in|till|until|before|since|starting|during|end\s+of)\s+(?:the\s+)?(month\s+of\s+)?"
                         + _MONTH + r"(?![a-z\d'-])", q):
        if free(m) and (m.group(2) != "may" or m.group(1)):
            mo = _MON[m.group(2)]
            add(m, _month_end(said_on.year + (mo < said_on.month), mo))
    return out


def due_support(due, quote: str, said_on) -> str | None:
    """The phrase in the quote that states the due date (same month as the end of a period the quote names), or None."""
    try:
        d = date.fromisoformat(str(due)[:10])
    except ValueError:
        return None
    try:
        s = date.fromisoformat(str(said_on)[:10]) if said_on else None
    except ValueError:
        s = None
    if s and s > date.today():
        s = None
    return next((ph for ph, end in due_periods(quote or "", s) if (end.year, end.month) == (d.year, d.month)), None)


_PACK_DATES: dict = {}


def doc_date(sym: str, url: str) -> str | None:
    """Date of a source document as the stock's research pack lists it (docs/data/packs/<sym>.json)."""
    if sym not in _PACK_DATES:
        p = Path(f"docs/data/packs/{sym}.json")
        docs = (json.loads(p.read_text()).get("documents") or []) if p.exists() else []
        _PACK_DATES[sym] = {d.get("url"): d.get("date") for d in docs if d.get("url") and d.get("date")}
    return _PACK_DATES[sym].get(url)


def outlook_score(promises, catalysts, red_flags, cred) -> int | None:
    """Rule-based, computed only from verified items (no model judgment)."""
    if not promises and not catalysts:
        return None
    s = 40
    types = [u["type"] for p in promises for u in p["updates"]]
    s += 20 if "raised" in types else 0
    s += min(30, 15 * sum(p["status"] in ("delivered", "beat") for p in promises))
    s -= 15 * sum(p["status"] == "missed" for p in promises)
    s -= 8 * sum(p["status"] == "delayed" for p in promises)
    s += 10 if any(p["status"] in ("pending", "raised") for p in promises) else 0
    s += 5 * min(2, len(catalysts))
    s -= 5 * min(3, len(red_flags))
    s += 10 if cred and cred["pct"] >= 75 else 0
    return max(0, min(100, s))


LENS_ORDER = ("fundamentals", "valuation", "management", "outlook", "flow")


def _num_ok(text: str, quote: str) -> bool:
    return not (nums(text) - nums(quote))


def verify_scan(sc: dict, other_quotes: str) -> tuple[dict, list]:
    """multibagger-scan output. Every mark other than 'u' needs a verified quote, else it becomes 'u' (unproven).
    Guidance / order-book numbers must sit in their quote. Label, legs, arc and scenario prices are computed later
    (run.py) from these verified inputs plus filed numbers."""
    rej, out = [], {"date": sc.get("date"), "type": sc.get("type")}
    quotes = other_quotes
    cl = {}
    for lens in LENS_ORDER:
        marks = []
        for m in (sc.get("checklist") or {}).get(lens, []):
            m = {k: m.get(k, "") for k in ("id", "name", "mark", "note", "quote", "source")}
            if m["mark"] not in ("y", "p", "n", "u"):
                m["mark"] = "u"
            if m["mark"] != "u":
                why = check(m, ("note",)) if (m["quote"] and m["source"]) else "no quote"
                if why == "no quote" and m.get("note", "").startswith("pipeline:"):
                    why = None  # marks backed by a computed pipeline field, e.g. "pipeline: cfo_to_ebitda_pct"
                if why:
                    rej.append({"id": f"checklist {m['id']}", "field": m["name"], "reason": why + " -> shown as unproven"})
                    m["mark"] = "u"
                elif m["quote"]:
                    quotes += " " + m["quote"]
            marks.append(m)
        if marks:
            cl[lens] = marks
    out["checklist"] = cl
    for key in ("guidance", "order_book"):
        g = sc.get(key)
        if not g:
            continue
        why = check(g, ())
        vals = [str(g.get(k)) for k in ("low", "high", "value_cr") if g.get(k) is not None]
        if not why and any(_numkey(v) not in {_numkey(n) for n in nums(g["quote"])} for v in vals):
            why = f"numbers {vals} not in quote"
        if not why and g.get("value_cr") is not None:  # the field name carries the unit: crore
            why = value_check(g["value_cr"], "crore", g["quote"], fetch_text(g["source"]) or "")
        if why:
            rej.append({"id": key, "field": key, "reason": why})
        else:
            out[key] = g
            quotes += " " + g["quote"]
    for key in ("levers", "must_go_right", "kill_switches"):
        ok = []
        for it in sc.get(key) or []:
            if it.get("quote"):
                why = check(it, ("text",))
            else:
                why = None if not nums(it.get("text", "")) else "numbers without a quote"
            if why:
                rej.append({"id": key, "field": it.get("text", "")[:60], "reason": why})
            else:
                ok.append(it)
        out[key] = ok
    th = {}
    for k, t in (sc.get("theories") or {}).items():
        if _num_ok(t, quotes):
            th[k] = t
        else:
            rej.append({"id": "theory", "field": k, "reason": f"numbers {sorted(nums(t) - nums(quotes))} not in a verified quote"})
    out["theories"] = th
    return out, rej


def verify_all(theses: dict) -> tuple[dict, dict]:
    """Returns (verified theses for the app, report)."""
    out, report = {}, {}
    for sym, th in theses.items():
        rej = []
        v = {k: th.get(k) for k in ("updated", "quarter", "source_type", "outlook_score", "sentiment_score",
                                    "sentiment", "tone", "no_concall", "sources", "checkpoints", "resolved")}
        all_quotes = ""
        # promises and their updates
        promises = []
        for p in th.get("promises", []):
            why = check(p, ("promise",))
            if why:
                rej.append({"id": p.get("id"), "field": "promise", "reason": why})
                continue
            all_quotes += " " + p["quote"]
            # a due date is shown only if its year is stated in the quote (e.g. 2026, '26, FY27)
            d = p.get("due")
            if d:
                y = int(d[:4]); fy = y + 1 if int(d[5:7]) > 3 else y
                qn = nums(p["quote"])
                p = {**p, "due_verified": bool({str(y), str(y)[2:], str(fy)[2:], str(fy)} & qn)}
            ups = []
            for u in p.get("updates", []):
                w = check(u, ("text",))
                if w:
                    rej.append({"id": p.get("id"), "field": f"update {u.get('date')}", "reason": w})
                    continue
                all_quotes += " " + u["quote"]
                ups.append(u)
            promises.append({**p, "updates": ups})
        v["promises"] = promises
        # catalysts / unlock triggers / red flags / guidance: same rule
        for key in ("catalysts", "unlock_triggers", "red_flags", "guidance_items"):
            ok = []
            for it in th.get(key, []):
                w = check(it, ("text",))
                if w:
                    rej.append({"id": key, "field": it.get("text", "")[:60], "reason": w})
                else:
                    all_quotes += " " + it["quote"]
                    ok.append(it)
            v[key] = ok
        # forward drivers (capacity, capex, orders, margin, demand, product): display numbers must sit in the quote,
        # `value` too, with its `unit` when that is a size (crore, lakh, million) or a rate (%, bps)
        drivers = []
        for it in th.get("drivers", []):
            w = check(it, ("text",)) or value_check(it.get("value"), it.get("unit"), it["quote"], fetch_text(it["source"]) or "")
            if w:
                rej.append({"id": "driver", "field": it.get("text", "")[:60], "reason": w})
                continue
            all_quotes += " " + it["quote"]
            d = {k: it.get(k) for k in ("kind", "text", "value", "unit", "due", "quote", "source", "date")}
            if it.get("due"):  # R4 counts a due date only if the quote states it (with the date it was said on for 'Q4', 'next quarter')
                basis = due_support(it["due"], it["quote"], it.get("date") or doc_date(sym, it["source"]))
                d |= {"due_verified": basis is not None, "due_basis": basis}
                if basis is None:
                    rej.append({"id": "driver due", "field": it.get("text", "")[:60],
                                "reason": f"due {it['due']} not stated in the quote -> not a dated trigger (R4)"})
            drivers.append(d)
        v["drivers"] = drivers
        # red-flag reviews: Claude opened the flagged filing; verdict needs a verbatim quote from it
        fr = {}
        for fid, it in (th.get("flag_reviews") or {}).items():
            if (it or {}).get("verdict") not in ("confirmed", "dismissed"):
                rej.append({"id": f"flag {fid}", "field": "verdict", "reason": "verdict must be confirmed or dismissed"})
                continue
            w = check(it, ("note",))
            if w:
                rej.append({"id": f"flag {fid}", "field": "note", "reason": w})
                continue
            fr[fid] = {k: it.get(k) for k in ("verdict", "note", "quote", "source", "date")}
        v["flag_reviews"] = fr
        # story check and integrity items: same rule (verbatim quote; numbers in the text must sit in the quote)
        sto = th.get("story")
        if sto:
            if sto.get("status") not in ("intact", "weakening", "broken"):
                rej.append({"id": "story", "field": "status", "reason": "status must be intact, weakening or broken"})
            else:
                w = check(sto, ("text",))
                if w:
                    rej.append({"id": "story", "field": "text", "reason": w})
                else:
                    v["story"] = {k: sto.get(k) for k in ("status", "text", "date", "quote", "source")}
        ig = {}
        for iid, it in (th.get("integrity") or {}).items():
            if (it or {}).get("status") not in ("open", "resolved", "confirmed"):
                rej.append({"id": f"integrity {iid}", "field": "status", "reason": "status must be open, resolved or confirmed"})
                continue
            w = check(it, ("note",))
            if w:
                rej.append({"id": f"integrity {iid}", "field": "note", "reason": w})
                continue
            ig[iid] = {k: it.get(k) for k in ("status", "type", "note", "date", "quote", "source")}
        v["integrity"] = ig
        bt = []  # named broker targets (research, decision-relevant stocks): the target number must sit in the verbatim quote
        for i, x in enumerate(th.get("broker_targets") or []):
            try:
                tgt = float(str(x.get("target")).replace(",", ""))
                dt = date.fromisoformat(str(x.get("date"))[:10])
            except (TypeError, ValueError):
                rej.append({"id": f"broker_targets {i}", "field": "target/date", "reason": "target must be a number and date YYYY-MM-DD"})
                continue
            if not x.get("broker") or (date.today() - dt).days > 180 or dt > date.today():
                rej.append({"id": f"broker_targets {i}", "field": "broker/date", "reason": "needs the broker's name and a date within 180 days"})
                continue
            tnum = f"{tgt:,.0f}" if tgt == int(tgt) else f"{tgt:,.2f}"
            w = check({**x, "text": f"target {tnum}"}, ("text",))
            if w:
                rej.append({"id": f"broker_targets {i}", "field": "quote", "reason": w})
                continue
            bt.append({k: x.get(k) for k in ("broker", "rating", "date", "quote", "source")} | {"target": tgt})
        if bt:
            v["broker_targets"] = sorted(bt, key=lambda x: x["date"], reverse=True)
        sy = th.get("synthesis")  # review: connect the dots; facts must match the dossier, numbers in text must be cited
        if sy:
            pts, dos = [], _dossier(sym)
            for i, pt in enumerate(sy.get("points") or []):
                w = _check_point(pt, dos)
                if w:
                    rej.append({"id": f"synthesis {i}", "field": "facts/text", "reason": w})
                else:
                    pts.append({k: pt.get(k) for k in ("kind", "text", "facts", "quote", "source")})
            one = sy.get("one_line") or ""
            cited = set().union(*[nums(str(f.get("value"))) | nums(p_.get("quote") or "") for p_ in pts for f in (p_.get("facts") or [])]) if pts else set()
            if nums(one) - cited:
                rej.append({"id": "synthesis", "field": "one_line", "reason": f"numbers {sorted(nums(one) - cited)} not cited in any point"})
                one = ""
            if pts:
                v["synthesis"] = {"date": sy.get("date"), "conviction": sy.get("conviction") if sy.get("conviction") in ("high", "medium", "low") else None,
                                  "one_line": one, "points": pts}
        fu = th.get("fund_use")  # G7: statement of deviation / monitoring agency report, quoted
        if fu:
            if fu.get("status") not in ("no deviation", "deviation"):
                rej.append({"id": "fund_use", "field": "status", "reason": "status must be 'no deviation' or 'deviation'"})
            else:
                w = check(fu, ("note",))
                if w:
                    rej.append({"id": "fund_use", "field": "note", "reason": w})
                else:
                    v["fund_use"] = {k: fu.get(k) for k in ("status", "note", "period", "date", "quote", "source")}
        au = th.get("audit")
        if au:
            chk, iss = [], []
            for c in au.get("checks") or []:
                w = check(c, ("found",))
                if w:
                    rej.append({"id": "audit", "field": c.get("item", "")[:60], "reason": w})
                else:
                    chk.append({k: c.get(k) for k in ("item", "app", "found", "ok", "quote", "source", "rule") if k != "rule" or c.get("rule")})
            for it in au.get("issues") or []:
                w = check(it, ("text",))
                if w:
                    rej.append({"id": "audit issue", "field": it.get("text", "")[:60], "reason": w})
                else:
                    iss.append({k: it.get(k) for k in ("text", "kind", "quote", "source")})
            verdict = au.get("verdict")
            if verdict not in ("pass", "caution", "fail"):
                rej.append({"id": "audit", "field": "verdict", "reason": "verdict must be pass, caution or fail"})
                verdict = None
            # numbers code reads from the XBRL filing count as checks (packs.MACHINE): Claude's own checks cover the rest
            mfields = machine_count(sym)
            if verdict == "pass" and (len(chk) + mfields < 3 or len(chk) < 1 or any(c.get("ok") is False for c in chk) or iss):
                rej.append({"id": "audit", "field": "verdict", "reason": "pass needs >= 1 own verified check (>= 3 with the code-read filing numbers), none failed, no verified issue -> caution"})
                verdict = "caution" if len(chk) + mfields >= 3 and len(chk) >= 1 else None
            dis = []
            for di in au.get("data_issues") or []:
                w = check(di, ("found",))
                fv = di.get("found_value")
                if not w and fv is not None and _numkey(str(fv)) not in {_numkey(n) for n in nums(di.get("quote", ""))}:
                    w = f"found_value {fv} not in quote"
                if not w and fv is not None and unit_of(di.get("unit")):
                    w = value_check(fv, di.get("unit"), di.get("quote", ""), fetch_text(di.get("source")) or "")
                if not w and di.get("scope") not in ("stock", "systemic"):
                    w = "scope must be stock or systemic"
                if w:
                    rej.append({"id": "data issue", "field": str(di.get("field", ""))[:60], "reason": w})
                else:
                    dis.append({k: di.get(k) for k in ("field", "app", "found", "found_value", "unit", "cause", "scope", "quote", "source")})
            v["data_issues"] = dis
            v["audit"] = {"date": au.get("date"), "verdict": verdict, "summary": au.get("summary") if _num_ok(au.get("summary") or "", " ".join(c["quote"] for c in chk + iss)) else None,
                          "checks": chk, "issues": iss} if verdict else None
            if v["audit"]:
                v["audit"].update(audit_r7(au, rej))  # RULES.md R7 and BSE-only items, quote-checked
        oir = th.get("other_income_recurring")  # RULES.md R2: other income shown to be recurring (e.g. JV profit), quoted
        if oir:
            w = check(oir, ("text",))
            if w:
                rej.append({"id": "other_income_recurring", "field": "text", "reason": w})
            v["other_income_recurring"] = None if w else {k: oir.get(k) for k in ("text", "quote", "source")}
        # thesis sentence: any number must appear in some verified quote of this stock
        t = th.get("thesis") or ""
        extra = nums(t) - nums(all_quotes)
        if extra:
            rej.append({"id": "thesis", "field": "thesis", "reason": f"numbers {sorted(extra)} not backed by a verified quote"})
            v["thesis"] = None
        else:
            v["thesis"] = t or None
        # credibility from verified promises only
        due = [p for p in promises if p.get("status") in ("delivered", "beat", "partly", "missed", "delayed")]
        if len(due) >= 2:
            pts = sum(1 if p["status"] in ("delivered", "beat") else 0.5 if p["status"] in ("partly", "delayed") else 0 for p in due)
            v["credibility"] = {"pct": round(pts / len(due) * 100), "due": len(due),
                                "delivered": sum(p["status"] in ("delivered", "beat") for p in due),
                                "partly": sum(p["status"] == "partly" for p in due),
                                "missed": sum(p["status"] == "missed" for p in due),
                                "delayed": sum(p["status"] == "delayed" for p in due)}
        else:
            v["credibility"] = None
        v["outlook_score"] = outlook_score(promises, v["catalysts"], v["red_flags"], v["credibility"])
        if th.get("scan"):
            v["scan_raw"], rj = verify_scan(th["scan"], all_quotes)
            rej += rj
        tr = th.get("triage")
        if tr:
            t2 = {k: tr.get(k) for k in ("date", "outcome", "type", "story", "fails_on", "quote", "source")}
            why = check(tr, ("story",)) if tr.get("quote") else (None if not nums(tr.get("story", "")) else "story numbers without a quote")
            if why:
                rej.append({"id": "triage", "field": "story", "reason": why})
                t2["story"] = None
            v["triage"] = t2
        v["sentiment_score"] = None  # not shown until a sourced news-sentiment method exists
        out[sym] = v
        report[sym] = {"rejected": rej, "promises_verified": len(promises)}
    return out, report


def audit_r7(au: dict, rej: list) -> dict:
    """The audit items RULES.md R7 needs (funnel.r7_missing), verified like every other quoted item:
    - related_party: {"status": "quoted", "text", "quote", "source"} (numbers in text sit in the quote), or
      {"status": "not disclosed", "checked": "what was read", "source"} (+ optional quote of the related-party note);
    - flag_notes: [{"flag": consistency-flag id from the pack, "note", "quote", "source"}];
    - bse_only_note (BSE-only stocks): {"text", "source"} (+ optional quote; numbers in text need the quote).
    Rejected items are left out (the stock then stays at verification pending), never failed."""
    out = {}
    rp = au.get("related_party")
    if rp:
        st = rp.get("status")
        if st == "quoted":
            w = check(rp, ("text",))
        elif st == "not disclosed":
            w = None if rp.get("checked") and rp.get("source") else "'not disclosed' needs `checked` (what was read) and `source`"
            if not w and rp.get("quote"):
                w = check(rp, ("checked",))
        else:
            w = "status must be 'quoted' or 'not disclosed'"
        if w:
            rej.append({"id": "audit", "field": "related_party", "reason": w})
        else:
            out["related_party"] = {k: rp.get(k) for k in ("status", "text", "checked", "quote", "source") if rp.get(k) is not None}
    notes = []
    for fn in au.get("flag_notes") or []:
        w = None if fn.get("flag") else "flag id missing"
        w = w or check(fn, ("note",))
        if w:
            rej.append({"id": "audit", "field": f"flag_notes {fn.get('flag')}"[:60], "reason": w})
        else:
            notes.append({k: fn.get(k) for k in ("flag", "note", "quote", "source")})
    if notes:
        out["flag_notes"] = notes
    bn = au.get("bse_only_note")
    if bn:
        w = None if bn.get("text") and bn.get("source") else "bse_only_note needs text and source"
        if not w and bn.get("quote"):
            w = check(bn, ("text",))
        elif not w and nums(bn.get("text", "")):
            w = "numbers in bse_only_note text need a quote"
        if w:
            rej.append({"id": "audit", "field": "bse_only_note", "reason": w})
        else:
            out["bse_only_note"] = {k: bn.get(k) for k in ("text", "quote", "source") if bn.get(k) is not None}
    return out


if __name__ == "__main__":
    import sys
    th = json.loads(Path("docs/data/theses.json").read_text())
    only = {a if a.endswith((".NS", ".BO")) else a + ".NS" for a in sys.argv[1:] if a != "--only"}
    if only:  # research runs: check just the stocks edited this run; files are not written (the daily run writes them)
        th = {k: x for k, x in th.items() if k in only}
    v, rep = verify_all(th)
    if not only:
        Path("docs/data/research.json").write_text(json.dumps(v, ensure_ascii=False, separators=(",", ":")))
        Path("docs/data/verification.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    for s, r in rep.items():
        print(s, "verified promises:", r["promises_verified"], "rejected:", len(r["rejected"]))
        for x in r["rejected"]:
            print("   -", x)
