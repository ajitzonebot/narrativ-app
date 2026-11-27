"""Forward ledger, stage 1 (owner, 27 Nov 2026): every forward statement typed, sized against the company's filed numbers
as of the day it was made, marked material or not, and linked to its earlier version.

Stage 1 only describes; nothing here changes a rating, a gate or conviction. Later stages monitor progress, link events and
feed conviction (see KNOWLEDGE.md, 27 Nov 2026).

Fields per item (`size_item`):
  ftype     financial / operational / event
  measure   revenue / ebitda / pat / margin / growth:<what> / capex / order_book / order / part / capacity / ... / other
  period    fiscal year end the target refers to (31 Mar), when known
  amount    the target in its unit (midpoint of a quoted range)
  base      the comparable filed figure as of the statement date (last full fiscal year filed on or before it)
  size_pct  implied change: annual growth % for revenue / EBITDA / profit, points for margins, % of revenue for capex,
            orders and parts of the business, x of revenue (as %) for order books
  trend_pct the company's own 3-year growth of that measure, as filed by the statement date
  material  1 / 0 by MATERIAL below; None when the size is unknown (`why` says what is missing)
  direction up / down / flat
Lineage (`link`): the same financial target (stock, measure, period) restated later points to its earlier version
(`prev`) and says how it changed (`change`: raised / lowered / reaffirmed); other targets are linked by
conviction._same_target.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import filings as F
from . import metrics as MX

OUT = Path("data/ledger.json")

# Starting thresholds, to be calibrated against returns (ledger stage 5). Growth: relative to the company's own trend with
# a floor (owner's choice, 27 Nov 2026): a target is material when it implies growth of at least FLOOR_GROWTH a year AND at
# least TREND_MARGIN points above the company's 3-year rate (a fast grower guiding below its trend is not new upside).
FLOOR_GROWTH = 15.0
TREND_MARGIN = 5.0
MARGIN_PTS = 2.0        # EBITDA margin up (or down) by 2+ points
CAPEX_PCT = 10.0        # capex of 10%+ of last year's revenue
ORDER_PCT = 10.0        # a single order of 10%+ of last year's revenue (as R4 T3)
BOOK_X = 100.0          # an order book or yearly inflow of 1x+ last year's revenue (book-to-bill > 1, as T2)
PART_PCT = 10.0         # a segment / plant / subsidiary target worth 10%+ of company revenue
SAME_PCT = 2.0
CAPACITY_PCT = 20.0     # capacity up 20%+ on today's figure as management states it (target.now)
PART_OF = 0.8           # a "revenue" target below 80% of last year's company revenue is a part of the business          # a restated figure within 2% of the earlier one is "reaffirmed"

_NUM = r"\d[\d,]*(?:\.\d+)?"
_RS = re.compile(rf"(?:₹|rs\.?|inr)\s*({_NUM})(?:\s*(?:to|-|–|—)\s*(?:₹|rs\.?|inr)?\s*({_NUM}))?\s*(crores?|cr\b|lakh|lakhs|billion|bn|million|mn)?|"
                 rf"({_NUM})(?:\s*(?:to|-|–|—)\s*({_NUM}))?\s*(crores?|cr\b)", re.I)
_RANGE_TAIL = re.compile(rf"\s*(?:to|-|–|—)\s*(?:₹|rs\.?|inr)?\s*({_NUM})\s*(?:crores?|cr\b)", re.I)
_PCT = re.compile(rf"({_NUM})\s*%?(?:\s*(?:to|-|–|—)\s*({_NUM}))?\s*%", re.I)
_FY = re.compile(r"\bfy\s?'?(\d{2,4})(?:\s*[-–/]\s*'?(\d{2,4}))?\b", re.I)
_RANGE_FY = re.compile(r"\bfy\s?'?(\d{2})\s*(?:-|–|to)\s*(\d{2})\b", re.I)

# measure words (checked on the lower-cased text, in this order)
_PART = re.compile(r"\b(segment|division|subsidiar|business|unit|plant|vertical|portfolio|arm|operations|contribut|region|africa|"
                   r"export|domestic|us\b|europe|joint venture|jv)\b")
_ORDER_BOOK = re.compile(r"order ?book|order inflow|inflows?|bookings|orders on hand|unexecuted|backlog")
_ORDER_ONE = re.compile(r"\border\b|contract|letter of award|\bloa\b|\bloi\b|work order|purchase order")
_PIPELINE = re.compile(r"pipeline|enquir|bidding|bids?\b|tender")
_CAPEX = re.compile(r"capex|capital expenditure|invest(ment)?|spend|outlay")
_DEBT = re.compile(r"\bdebt\b|borrowing|net cash|cash surplus|leverage")
_AUM = re.compile(r"\baum\b|loan book|assets under|disburs|advances|deposits|book size")
_MARGIN = re.compile(r"margin")
_EBITDA = re.compile(r"ebitda|operating profit")
_PAT = re.compile(r"\bpat\b|net profit|profit after tax|\bprofit\b|earnings|eps")
_REV = re.compile(r"revenue|sales|top ?line|turnover|total income|income from operations")
_GROWTH = re.compile(r"growth|grow|increase|cagr|rise|up by")
_CAPACITY = re.compile(r"capacity|utili[sz]ation|commission|plant|facility|line|mw\b|gw\b|tonnes|tpa|beds|stores|centres|centers|branches")
_EVENT = re.compile(r"approval|launch|acquisition|acquire|merger|demerger|listing|licen[cs]e|clearance|ipo|fund ?rais|qip|rights issue")


def _d(x) -> date | None:
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _f(x: str) -> float:
    return float(x.replace(",", ""))


def rupees_cr(text: str, after: int = 0) -> float | None:
    """The first rupee amount in crore at or after position `after` (midpoint of a quoted range); None when the text has none in
    crore / lakh / bn / mn."""
    for m in _RS.finditer(text or ""):
        if m.end() <= after:
            continue
        if m.group(1):
            a, b, u = m.group(1), m.group(2), (m.group(3) or "").lower()
        else:
            a, b, u = m.group(4), m.group(5), (m.group(6) or "").lower()
        if not u:
            continue
        if not b:  # "Rs1,400 crores to Rs1,500 crores": the unit after each end
            m2 = _RANGE_TAIL.match(text, m.end())
            b = m2.group(1) if m2 else None
        v = (_f(a) + _f(b)) / 2 if b else _f(a)
        k = {"lakh": 0.01, "lakhs": 0.01, "billion": 100.0, "bn": 100.0, "million": 0.1, "mn": 0.1}.get(u, 1.0)
        return v * k
    return None


def percent(text: str) -> float | None:
    """The first percentage (midpoint of a quoted range: "18% to 20%" -> 19)."""
    m = _PCT.search(text or "")
    if not m:
        return None
    return (_f(m.group(1)) + _f(m.group(2))) / 2 if m.group(2) else _f(m.group(1))


def fiscal_end(text: str, due, made: date | None) -> date | None:
    """31 March of the fiscal year the target refers to: an FY in the text (the later one of "FY29/30"), else the fiscal year
    holding the due date, else None."""
    m = _RANGE_FY.search(text or "") or _FY.search(text or "")
    if m:
        y = int(m.group(2) or m.group(1))
        y = y + 2000 if y < 100 else y
        if 2000 < y < 2100:
            return date(y, 3, 31)
    dd = _d(due)
    if dd:
        return date(dd.year if dd.month <= 3 else dd.year + 1, 3, 31)
    return None


def fy_year(fy) -> int | None:
    """"FY27" / "FY2027" / "FY 2026-27" / 2027 -> 2027 (the year the fiscal year ends in)."""
    m = _FY.search(f"FY{fy}" if isinstance(fy, int) or str(fy).strip()[:1].isdigit() else str(fy))
    if not m:
        return None
    y = int(m.group(2) or m.group(1))
    y = y + 2000 if y < 100 else y
    return y if 2000 < y < 2100 else None


def fiscal_years(text: str) -> set:
    """Every fiscal year a statement names: FY27, FY 2026-27, FY29/30 (both), and a calendar year (2027 -> FY27 or FY28:
    "by March 2027" ends FY27, "by December 2027" falls in FY28)."""
    out = set()
    for m in _FY.finditer(text or ""):
        for g in (m.group(1), m.group(2)):
            if g:
                y = int(g)
                out.add(y + 2000 if y < 100 else y)
    for m in re.finditer(r"(?<!\d)(20\d\d)(?!\d)", text or ""):
        y = int(m.group(1))
        out |= {y, y + 1}
    return out


def classify(text: str, kind: str | None, unit: str | None) -> tuple[str, str]:
    """(ftype, measure) from the statement's words; kind and unit only break ties."""
    t = (text or "").lower()
    pct = unit == "%" or "%" in t
    rs = rupees_cr(t) is not None or unit == "cr"
    if _DEBT.search(t):
        return "financial", "debt"
    if _AUM.search(t):
        return "financial", "growth:aum" if pct and _GROWTH.search(t) else "aum"
    if _PIPELINE.search(t) and not _ORDER_BOOK.search(t.replace("pipeline", "")):
        return "operational", "pipeline"
    if _MARGIN.search(t) and pct:
        return "financial", "margin" if _EBITDA.search(t) or "operating" in t or "ebitda" in t else "margin:other"
    if rs and _ORDER_BOOK.search(t):
        return "financial", "order_book"
    if rs and (_ORDER_ONE.search(t) or kind == "order"):
        return "financial", "order"
    if rs and _CAPEX.search(t) or (kind == "capex" and rs):
        return "financial", "capex"
    hits = sorted((m.start(), name) for rx, name in ((_EBITDA, "ebitda"), (_PAT, "pat"), (_REV, "revenue")) for m in [rx.search(t)] if m)
    for _, name in hits[:1]:  # the measure named first ("revenue about Rs800 cr and PAT around Rs125 cr" is a revenue target)
        if pct and _GROWTH.search(t) and not rs:
            return "financial", f"growth:{name}"
        if rs:
            return "financial", "part" if _PART.search(t) else name
    if pct and _GROWTH.search(t) and ("volume" in t or "tonnage" in t):
        return "operational", "growth:volume"
    if _CAPACITY.search(t) or kind == "capacity":
        return "operational", "capacity"
    if _EVENT.search(t) or kind == "product":
        return "event", "event"
    if rs:
        return "financial", "other"
    return ("operational", "other") if re.search(_NUM, t) else ("event", "event")


class Bases:
    """Filed full-year figures per stock, as of a date (only filings filed on or before it)."""

    def __init__(self, fins: dict | None = None):
        self.fins = fins or {}
        self.cache: dict = {}

    def series(self, sym: str) -> dict:
        if sym not in self.cache:
            fin = self.fins.get(sym) or F.load(sym)
            try:
                self.cache[sym] = MX.series(fin) if fin else {}
            except Exception:  # noqa: BLE001
                self.cache[sym] = {}
        return self.cache[sym]

    def fy(self, sym: str, made: date | None) -> dict:
        """{fiscal year: {rev, ebitda, pat}} in crore, from filings filed on or before `made` (today when None)."""
        s = self.series(sym)
        if not s or not s.get("q"):
            return {}
        cut = str(made or date.today())
        q = {qe: p for qe, p in s["q"].items() if str(p.get("filed") or qe) <= cut}
        s2 = {**s, "q": q}
        rev, pat, ebitda = MX._fy_values(s2, "rev"), MX._fy_values(s2, "pat"), MX._fy_ebitda(s2)
        return {y: {"rev": rev[y] / MX.CR, "pat": (pat.get(y) / MX.CR) if pat.get(y) is not None else None,
                    "ebitda": (ebitda.get(y) / MX.CR) if ebitda.get(y) is not None else None} for y in rev}


def _cagr(a, b, years):
    if a is None or b is None or a <= 0 or b <= 0 or years <= 0:
        return None
    return ((b / a) ** (1 / years) - 1) * 100


def _from_target(t: dict) -> tuple[str, str, float | None, date | None]:
    """(ftype, measure, amount, period) from Narrativ.ai's verified target (verify.target_check)."""
    m, of = t.get("measure"), str(t.get("of") or "company")
    lo, hi = t.get("low"), t.get("high")
    amt = (lo + hi) / 2 if lo is not None and hi is not None else (lo if lo is not None else hi)
    y = fy_year(t["fy"]) if t.get("fy") else None
    per = date(y, 3, 31) if y else None
    if m in ("revenue", "ebitda", "pat") and of.startswith("part"):
        return "financial", "part", amt, per
    if m == "growth":
        g = t.get("growth_of") or "revenue"
        return ("operational" if g == "volume" else "financial"), f"growth:{g}", amt, per
    if m == "capacity":
        return "operational", "capacity", amt, per
    return "financial", m, amt, per


def size_item(sym: str, kind: str | None, text: str, value, unit: str | None, due, made, bases: Bases, target: dict | None = None) -> dict:
    """Sized as below; only a verified target can mark an item material (owner, 27 Nov 2026: only Narrativ.ai's verified
    quotes count). A size read from the text keeps its estimate in `est_material` and leaves `material` empty."""
    out = _size(sym, kind, text, value, unit, due, made, bases, target)
    if out.get("src") == "parsed":
        out["est_material"], out["material"] = out.get("material"), None
    return out


def _size(sym: str, kind: str | None, text: str, value, unit: str | None, due, made, bases: Bases, target: dict | None = None) -> dict:
    """Type, base, size and materiality of one forward statement (see the module docstring). With Narrativ.ai's verified
    `target` the figures are hers (src "narrativ"); without it they are read from the text (src "parsed", provisional: the
    next review records the target)."""
    md = _d(made)
    tg = target if isinstance(target, dict) and target.get("measure") else None
    if tg:
        ftype, measure, t_amt, per = _from_target(tg)
        per = per or fiscal_end(text, due, md)
    else:
        ftype, measure = classify(text, kind, unit)
        t_amt, per = None, fiscal_end(text, due, md)
    out = {"ftype": ftype, "measure": measure, "period": None, "amount": None, "base": None, "size_pct": None,
           "trend_pct": None, "material": None, "direction": None, "why": None, "src": "narrativ" if tg else "parsed"}
    out["period"] = str(per) if per else None
    fy = bases.fy(sym, md) if ftype == "financial" else {}
    last = max(fy) if fy else None
    L = fy.get(last) or {}
    rev = L.get("rev")

    def trend(key):
        """Own growth a year over the last 3 filed fiscal years, else 2 (the filings store starts in 2022-23)."""
        for n in (3, 2):
            if last is not None and (last - n) in fy:
                return _cagr((fy[last - n] or {}).get(key), L.get(key), n)
        return None

    pos = {"revenue": _REV, "ebitda": _EBITDA, "pat": _PAT}.get(measure)
    m0 = pos.search((text or "").lower()) if pos else None
    rs = rupees_cr(text, m0.start() if m0 else 0)
    if rs is None:
        rs = rupees_cr(text)
    if rs is None and unit == "cr" and isinstance(value, (int, float)):
        rs = float(value)
    pc = percent(text)
    if pc is None and unit == "%" and isinstance(value, (int, float)):
        pc = float(value)
    if tg:  # her figures, never the text's
        rs = t_amt if str(tg.get("unit") or "").lower() in ("cr", "crore", "crores", "₹ cr") else None
        pc = t_amt if str(tg.get("unit") or "") in ("%", "pct") else None

    def done(size, mat, direction=None, base=None, tr=None, amount=None):
        out.update({"size_pct": None if size is None else round(size, 1), "material": None if mat is None else int(mat),
                    "direction": direction or (None if size is None else "up" if size > 0.5 else "down" if size < -0.5 else "flat"),
                    "base": None if base is None else round(base, 1), "trend_pct": None if tr is None else round(tr, 1),
                    "amount": None if amount is None else round(amount, 2)})
        return out

    key = {"revenue": "rev", "ebitda": "ebitda", "pat": "pat"}
    if measure.startswith("growth:"):
        what = measure.split(":")[1]
        if pc is None:
            out["why"] = "no growth figure in the statement"
            return out
        tr = trend(key.get(what, "rev")) if what in key or what == "aum" else None  # lenders: AUM against the revenue trend
        mat = pc >= FLOOR_GROWTH and (tr is None or pc >= tr + TREND_MARGIN)
        return done(pc, mat, tr=tr, amount=pc)
    if measure == "capacity" and tg and tg.get("now") and t_amt is not None:
        now = float(tg["now"])
        ch = (t_amt / now * 100) if tg.get("adds") else (t_amt / now - 1) * 100
        return done(ch, ch >= CAPACITY_PCT, base=now, amount=t_amt)
    if ftype != "financial":
        out["why"] = "base not in the filings (needs the current figure quoted by management)" if measure in ("capacity", "growth:volume", "other") \
            else "no number to size" if ftype == "event" else "not sized"
        return out
    if not fy or rev is None or rev <= 0:
        out["why"] = "no full fiscal year filed before the statement"
        return out
    if measure == "revenue" and not tg and rs is not None and rs < PART_OF * rev:
        measure = out["measure"] = "part"  # a division / plant figure (TALBROAUTO forging Rs345 cr vs Rs870 cr company revenue)
    if measure in key:
        if rs is None:
            out["why"] = "no rupee figure"
            return out
        b = L.get(key[measure])
        if b is None or b <= 0 or per is None:
            out["why"] = "no positive base" if per else "no fiscal year for the target"
            return done(None, None, amount=rs)
        years = max(1, per.year - last)
        g = _cagr(b, rs, years)
        tr = trend(key[measure])
        mat = g is not None and g >= FLOOR_GROWTH and (tr is None or g >= tr + TREND_MARGIN)
        return done(g, mat, base=b, tr=tr, amount=rs)
    if measure == "margin":
        e = L.get("ebitda")
        if pc is None or e is None:
            out["why"] = "no margin figure or no filed EBITDA"
            return out
        base = e / rev * 100
        ch = pc - base
        return done(ch, abs(ch) >= MARGIN_PTS, base=base, amount=pc)
    if rs is None:
        out["why"] = "no rupee figure"
        return out
    share = rs / rev * 100
    if measure == "capex":
        return done(share, share >= CAPEX_PCT, "up", base=rev, amount=rs)
    if measure == "order":
        return done(share, share >= ORDER_PCT, "up", base=rev, amount=rs)
    if measure == "order_book":
        return done(share, share >= BOOK_X, "up", base=rev, amount=rs)
    if measure == "part":
        return done(share, share >= PART_PCT, "up", base=rev, amount=rs)
    out["why"] = "measure has no filed base (debt, AUM, other)"
    return done(None, None, amount=rs)


def link(items: list[dict]) -> list[dict]:
    """Earlier version of each item (same stock): financial targets by (measure, period), others by conviction._same_target.
    Each item: {"id", "sym", "made", "text", "due", "measure", "period", "amount"}. Adds "prev" and "change"."""
    from .conviction import _same_target
    by_sym: dict = {}
    for it in items:
        by_sym.setdefault(it["sym"], []).append(it)
    for rows in by_sym.values():
        rows.sort(key=lambda r: (str(r.get("made") or ""), r["id"]))
        for i, r in enumerate(rows):
            r["prev"], r["change"] = None, None
            for p in reversed(rows[:i]):
                if str(p.get("made") or "") >= str(r.get("made") or ""):
                    continue
                fin_match = (r.get("measure") == p.get("measure") and r.get("period") and r.get("period") == p.get("period")
                             and r.get("measure") not in ("other", "event", "capacity", "pipeline"))
                if fin_match or (not fin_match and r.get("due") and p.get("due")
                                 and _same_target({"text": p["text"], "due": p["due"]}, {"text": r["text"], "due": r["due"]})):
                    r["prev"] = p["id"]
                    a, b = p.get("amount"), r.get("amount")
                    if a and b:
                        d = (b / a - 1) * 100
                        r["change"] = "raised" if d > SAME_PCT else "lowered" if d < -SAME_PCT else "reaffirmed"
                    else:
                        r["change"] = "restated"
                    break
    return items


def rows_from_theses(theses: dict) -> list[dict]:
    """Narrativ.ai's drivers and tracked promises as ledger inputs (the free readers' rows are sized in dbsync only)."""
    out = []
    for s, t in (theses or {}).items():
        for i, x in enumerate(t.get("drivers") or []):
            if x.get("text"):
                out.append({"id": f"{s}|d{i}", "sym": s, "origin": "claude", "kind": x.get("kind"), "text": x["text"], "value": x.get("value"),
                            "unit": x.get("unit"), "due": x.get("due"), "made": x.get("date"), "verified": bool(x.get("due_verified")),
                            "target": x.get("target")})
        for x in t.get("promises") or []:
            if x.get("promise"):
                out.append({"id": f"{s}|p:{x.get('id') or x['promise'][:40]}", "sym": s, "origin": "promise", "kind": x.get("kind"),
                            "text": x["promise"], "value": None, "unit": None, "due": x.get("due"), "made": x.get("made_on"),
                            "status": x.get("status"), "verified": bool(x.get("due_verified"))})
    return out


def annotate(rows: list[dict], bases: Bases | None = None) -> list[dict]:
    """Size every row and link versions; returns the rows with the ledger fields added."""
    bases = bases or Bases()
    for r in rows:
        r.update(size_item(r["sym"], r.get("kind"), r["text"], r.get("value"), r.get("unit"), r.get("due"), r.get("made"), bases,
                           r.get("target")))
    return link(rows)


def build(theses: dict, today: date, fins: dict | None = None) -> dict:
    """data/ledger.json: Narrativ.ai's forward items with type, size, materiality and lineage; summary counts."""
    rows = annotate(rows_from_theses(theses), Bases(fins))
    keep = ("id", "sym", "origin", "text", "due", "made", "verified", "status", "src", "ftype", "measure", "period", "amount", "base",
            "size_pct", "trend_pct", "material", "est_material", "direction", "why", "prev", "change", "target")
    items = [{k: r.get(k) for k in keep if r.get(k) is not None} for r in rows]
    summ = {"items": len(items),
            "by_type": {t: sum(1 for r in rows if r["ftype"] == t) for t in ("financial", "operational", "event")},
            "sized": sum(1 for r in rows if r.get("size_pct") is not None),
            "material": sum(1 for r in rows if r.get("material") == 1),
            "est_material_parsed": sum(1 for r in rows if r.get("est_material") == 1),
            "from_target": sum(1 for r in rows if r.get("src") == "narrativ"),
            "material_from_target": sum(1 for r in rows if r.get("src") == "narrativ" and r.get("material") == 1),
            "linked": sum(1 for r in rows if r.get("prev")),
            "changes": {c: sum(1 for r in rows if r.get("change") == c) for c in ("raised", "lowered", "reaffirmed", "restated")}}
    doc = {"date": str(today), "rule": "ledger stage 1 (2026-11-27)", "thresholds": {
        "floor_growth_pct": FLOOR_GROWTH, "trend_margin_pts": TREND_MARGIN, "margin_pts": MARGIN_PTS, "capex_pct_rev": CAPEX_PCT,
        "order_pct_rev": ORDER_PCT, "book_pct_rev": BOOK_X, "part_pct_rev": PART_PCT}, "summary": summ, "items": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    return summ


if __name__ == "__main__":
    import sys
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/data/research.json")
    print(build(json.loads(src.read_text()), date.today()))
