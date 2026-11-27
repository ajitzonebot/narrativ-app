import json

import pytest

from narrativ import docread, verify
from narrativ.verify import _same, check, due_periods, due_support, nums, quoted_in, unit_mismatch, value_check, verify_all


def test_quote_found_despite_pdf_spacing():
    doc = "We expect revenue of Rs. 1,000 crore in FY27, a40% yoygrowth driven by high -value orders."
    assert quoted_in("a 40% yoy growth", doc)
    assert quoted_in("high-value orders", doc)  # extraction added a space: whitespace is ignored
    assert quoted_in("Rs. 1,000 crore in FY27", doc)


def test_reworded_quote_rejected():
    assert not quoted_in("revenue of Rs 1000 crore", "We expect revenue of Rs. 1,000 crore in FY27.")


def test_curly_quotes_and_case_ignored():
    assert quoted_in("the ‘new’ plant starts in March", "The 'new' plant starts in March.")


def test_nums_strip_commas_and_trailing_dot():
    assert nums("Rs. 1,000 crore by 2027.") == {"1000", "2027"}


# ---- quote matches must start and end on a word / number boundary ----

def test_quote_may_not_end_inside_a_number():
    assert not quoted_in("order inflow of Rs 50", "We had an order inflow of Rs 500 crore this quarter.")
    assert quoted_in("order inflow of Rs 500", "We had an order inflow of Rs 500 crore this quarter.")
    assert not quoted_in("revenue grew 2", "revenue grew 2.5x in the year")
    assert not quoted_in("revenue grew 1", "revenue grew 1,500 crore")


def test_quote_may_not_start_inside_a_number_or_word():
    assert not quoted_in("20% revenue growth", "We delivered 120% revenue growth.")
    assert quoted_in("20% revenue growth", "We delivered 20% revenue growth.")
    assert not quoted_in("500 crore order from NTPC", "a Rs 1,500 crore order from NTPC")
    assert not quoted_in("5 crore order from NTPC", "a Rs 2.5 crore order from NTPC")
    assert not quoted_in("order inflow was strong", "Border inflow was strong this year.")
    assert not quoted_in("revenue growth of 15", "Strong revenue growth of 15x")  # ends inside the token '15x'


def test_another_occurrence_with_boundaries_still_matches():
    doc = "order inflow of Rs 500 crore; later an order inflow of Rs 50 crore"
    assert quoted_in("order inflow of Rs 50", doc)


def test_spacing_fallback_respects_number_boundaries():
    # whitespace-free match: 'rs50' sits inside 'rs500', and '50 0' reads as '500' once spaces go
    assert not quoted_in("order inflow of Rs 50", "orderinflow of Rs500 crore")
    assert not quoted_in("order inflow of Rs 50", "orderinflow of Rs 50 0 crore")
    assert not quoted_in("20% revenue growth", "we did 1 20%revenue growth")
    assert quoted_in("order inflow of Rs 50 crore", "orderinflow of Rs50crore")
    # spaced match keeps the document's own spacing, so a table row next to another number is fine
    assert quoted_in("Revenue 1,234 1,456 1,600", "Revenue 1,234 1,456 1,600 1,750")


def test_letters_run_into_digits_in_pdf_text():
    assert quoted_in("12,42611,977Total Equity", "right to use asset 12,42611,977Total Equity71355(iii) capital")
    assert quoted_in("500 crore order from NTPC", "an Rs500 crore order from NTPC")
    assert not quoted_in("order inflow of Rs 50", "order inflow of Rs 50mn")  # prose number running into a unit


def test_table_rows_with_spacing_artefacts_still_match():
    doc = "358.89 154.4 5 355 .01 307 .25 5.78 6.43"  # pypdf split cells; the row sits between other cells
    assert quoted_in("154.45 355.01 307.25", doc)
    assert quoted_in("Revenue from Operations 19834.24 17761.11 63208.65",
                     "revenue from operations 19834.24 17761.11 63208.65ii other income")


def test_trivially_short_quotes_never_verify():
    assert not quoted_in("Rs 50", "order of Rs 50 crore")
    assert not quoted_in("15% growth", "we saw 15% growth")
    assert not quoted_in("", "anything")
    assert quoted_in("2,187.19", "Total income 2,187.19 1,950.00")  # a statement figure: 6 digits


# ---- a blank fact value never matches ----

def test_blank_value_does_not_match():
    assert not _same("", 1234)
    assert not _same("   ", "Unqualified")
    assert not _same(None, "x")
    assert not _same("5 cr", "15 cr")
    assert _same("1,000", "1000.2")
    assert _same("unqualified", "Unqualified opinion")


# ---- units next to numbers: 50 lakh is not 50 crore ----

def test_unit_mismatch():
    assert unit_mismatch("order of Rs 50 crore", "order of Rs 50 lakh") == ["50 crore"]
    assert unit_mismatch("margin up 20%", "margin up 20 basis points") == ["20 pct"]
    assert unit_mismatch("Rs 1.2 lakh crore", "Rs 1.2 crore") == ["1.2 lakh crore"]
    assert unit_mismatch("Rs 50 crore order", "order worth INR50 Crs.") == []
    assert unit_mismatch("15% growth", "growth of 15 per cent") == []
    assert unit_mismatch("Rs 50 crore", "Revenue (Rs crore) 50 60") == []  # unit in a table header
    assert unit_mismatch("50 MW plant", "50 megawatt plant") == []  # not a size unit: number only


@pytest.fixture
def doc(monkeypatch):
    texts = {}
    monkeypatch.setattr(verify, "fetch_text", lambda url: texts.get(url))
    return texts


def test_check_rejects_display_unit_not_in_quote(doc):
    doc["u"] = "We won an order worth Rs 50 lakh from NTPC this quarter."
    it = {"text": "Order of Rs 50 crore from NTPC", "quote": "We won an order worth Rs 50 lakh from NTPC", "source": "u"}
    assert "units" in check(it, ("text",))
    assert check({**it, "text": "Order of Rs 50 lakh from NTPC"}, ("text",)) is None


def test_value_check():
    assert value_check(310, "cr", "we expect FY'27 EBITDA to be at least  INR 310 crores") is None
    assert value_check(50, "cr", "an order of Rs 50 lakh") is not None
    assert value_check(18, "%", "We are at about 18% now") is None
    assert value_check(11, "MW", "11-megawatt ground solar") is None
    assert value_check(1000, "cr", "orders of Rs 1 crore") is not None  # not '1000'.rstrip('0') == '1'
    assert value_check(None, None, "anything") is None


def test_driver_value_unit_checked(doc):
    doc["u"] = "We have received orders worth Rs 120 lakh from a large customer."
    th = {"X.NS": {"drivers": [{"kind": "order", "text": "Orders from a large customer", "value": 120, "unit": "cr",
                                "quote": "received orders worth Rs 120 lakh from a large customer", "source": "u"}]}}
    out, rep = verify_all(th)
    assert out["X.NS"]["drivers"] == []
    assert "value 120 cr" in rep["X.NS"]["rejected"][0]["reason"]


# ---- driver due dates (R4) ----

def test_due_periods_absolute():
    got = {p for p, _ in due_periods("by March 2027, Q3FY28, 3QFY27, Mar-27, FY'27, H1 FY2027, fiscal 2026-27", None)}
    assert {"march 2027", "q3fy28", "3qfy27", "mar-27", "fy'27", "h1 fy2027", "fiscal 2026-27"} <= got
    assert due_support("2027-03-31", "we expect FY’27 EBITDA to be at least INR 310 crores", None) == "fy'27"
    assert due_support("2027-12-31", "commissioning in Q3FY28", None) == "q3fy28"


def test_due_relative_needs_date_said_on():
    q = "We will complete the entire investment in the next quarter, and by the fourth quarter, we expect the full revenue"
    assert due_support("2027-03-31", q, None) is None
    assert due_support("2027-03-31", q, "2026-08-11") == "fourth quarter"  # Q4 of FY27, the fiscal year it was said in
    assert due_support("2026-12-31", q, "2026-08-11") == "next quarter"
    assert due_support("2027-06-30", q, "2026-08-11") is None


def test_due_relative_phrases():
    assert due_support("2026-11-30", "a mandate that bills from November.", "2026-11-04")
    assert due_support("2026-12-31", "expansion will be completed in Q3", "2026-11-05") == "q3"
    assert due_support("2027-06-30", "supply starts from the first quarter or the second quarter of next calendar year",
                       "2026-08-11") == "second quarter of next calendar year"
    assert due_support("2028-05-31", "to be commissioned within 18 months", "2026-11-05") == "within 18 months"
    assert due_support("2027-09-30", "Q2 margins were weak", "2026-11-05") is None  # a quarter already over is history
    assert due_support("2027-05-31", "we may see growth", "2026-11-05") is None  # 'may' the verb
    assert due_support("2027-05-31", "Phase 1 for 5 MW Data Centre to be completed by May’2027.", None)
    assert due_support("2030-03-31", "~INR 700 crore EBITDA by FY29/30", None) == "fy29/30"
    assert due_support("2030-03-31", "we are on track to achieve the target of 30% by 2030.", None) == "2030"
    assert due_support("2028-03-31", "regular production is expected in 2027-28.", None) == "2027-28"
    assert due_support("2027-03-31", "it is going to fully cover in a Quarter 4.", "2026-11-02") == "quarter 4"
    assert due_support("2026-12-31", "capacities, which is coming in the quarter three.", "2026-10-19") == "quarter three"
    assert due_support("2027-11-30", "the launch of the drug in the coming 12 months", "2026-11-04") == "in the coming 12 months"
    # said in Q3 FY27: the two quarters after it end June 2027
    assert due_support("2027-06-30", "in the next two quarters, turnover will increase", "2026-10-30") == "next two quarters"
    # 'this year' / 'next year' / 'year-end': fiscal or calendar cannot be told apart
    assert due_support("2026-12-31", "that will happen sometime end of this year.", "2026-10-30") is None
    assert due_support("2027-03-31", "that will happen sometime end of this year.", "2026-10-30") is None
    assert due_support("2027-09-30", "on stream in the 2nd Quarter of next year", "2026-11-02") is None


def test_due_not_in_quote():
    assert due_support("2027-03-31", "Orders to be executed over a period; strong visibility", "2026-11-11") is None
    assert due_support("2027-06-30", "commissioning by March 2027", "2026-11-11") is None
    assert due_support("not a date", "FY27", None) is None


def test_driver_due_verified_in_verify_all(doc, monkeypatch):
    monkeypatch.setattr(verify, "_PACK_DATES", {"X.NS": {"p": "2026-11-05"}})
    doc["u"] = doc["p"] = "Our planned knitting expansion will be completed in Q3 with receipt of balance machines."
    q = "Our planned knitting expansion will be completed in Q3 with receipt of balance machines."
    th = {"X.NS": {"drivers": [
        {"kind": "capacity", "text": "Knitting expansion done in Q3", "due": "2026-12-31", "date": "2026-11-05", "quote": q, "source": "u"},
        {"kind": "capacity", "text": "Knitting expansion done in Q3", "due": "2027-03-31", "date": "2026-11-05", "quote": q, "source": "u"},
        {"kind": "capacity", "text": "Knitting expansion done in Q3", "due": "2026-12-31", "quote": q, "source": "u"},  # no date said on
        {"kind": "capacity", "text": "Knitting expansion done in Q3", "due": "2026-12-31", "quote": q, "source": "p"},  # pack has it
        {"kind": "capacity", "text": "Knitting expansion done in Q3", "due": None, "quote": q, "source": "u"}]}}
    out, rep = verify_all(th)
    d = out["X.NS"]["drivers"]
    assert len(d) == 5  # a driver stays; only its due date stops counting
    assert [x.get("due_verified") for x in d] == [True, False, False, True, None]
    assert sum(r["id"] == "driver due" for r in rep["X.NS"]["rejected"]) == 2


def test_promise_due_verified_like_drivers(doc, monkeypatch):
    """Promise due dates use due_support (25 Nov 2026): a number equal to the year's digits ("27%") no longer verifies a
    2027 due date; the results date that settles a named period still does."""
    monkeypatch.setattr(verify, "_PACK_DATES", {})
    doc["u"] = ("We expect revenue growth of 27% this year. Growth Outlook - In FY27 Revenue Guidance Rs 1400- 1750crores. "
                "So, comfortably we will reach our 30% to 35% of growth '27. The plant will start in the next quarter for sure.")
    base = {"made_on": "2026-08-14", "call": "Q1 FY27 call", "kind": "results", "status": "pending", "source": "u", "updates": []}
    th = {"X.NS": {"promises": [
        {**base, "id": "a", "promise": "Revenue growth 27%", "due": "2027-03-31", "quote": "We expect revenue growth of 27% this year."},
        {**base, "id": "b", "promise": "FY27 revenue Rs 1400-1750 crores", "due": "2027-05-30",
         "quote": "Growth Outlook - In FY27 Revenue Guidance Rs 1400- 1750crores"},
        {**base, "id": "c", "promise": "FY27 revenue Rs 1400-1750 crores", "due": "2027-03-31",
         "quote": "Growth Outlook - In FY27 Revenue Guidance Rs 1400- 1750crores"},
        {**base, "id": "d", "promise": "Growth 30% to 35%", "due": "2027-03-31",
         "quote": "So, comfortably we will reach our 30% to 35% of growth '27."},  # '27 alone: fiscal or calendar?
        {**base, "id": "e", "promise": "Plant starts", "due": "2026-12-31", "quote": "The plant will start in the next quarter for sure."},
        {**base, "id": "f", "promise": "FY27 revenue", "due": "2027-08-31", "quote": "Growth Outlook - In FY27 Revenue Guidance Rs 1400- 1750crores"}]}}
    out, _ = verify_all(th)
    got = {p["id"]: p["due_verified"] for p in out["X.NS"]["promises"]}
    assert got == {"a": False, "b": True, "c": True, "d": False, "e": True, "f": False}
    assert due_support("2027-05-30", "In FY27 Revenue Guidance", None) is None  # drivers: same month as the period end only


def test_promise_target_checked_like_a_drivers(doc, monkeypatch):
    """A numeric promise carries a `target` (27 Nov 2026): kept when its numbers and fiscal year sit in the quote, dropped
    (the promise stays) when not."""
    monkeypatch.setattr(verify, "_PACK_DATES", {})
    q = "Growth Outlook - In FY27 Revenue Guidance Rs 1400- 1750crores"
    doc["u"] = q
    base = {"made_on": "2026-08-14", "call": "Q1 FY27 call", "kind": "results", "status": "pending", "source": "u", "updates": [],
            "promise": "FY27 revenue Rs 1400-1750 crores", "due": "2027-03-31", "quote": q}
    good = {"measure": "revenue", "of": "company", "low": 1400, "high": 1750, "unit": "cr", "fy": "FY27"}
    th = {"X.NS": {"promises": [{**base, "id": "a", "target": good},
                                {**base, "id": "b", "target": good | {"high": 1800}},
                                {**base, "id": "c"}]}}
    out, rep = verify_all(th)
    got = {p["id"]: p.get("target") for p in out["X.NS"]["promises"]}
    assert got["a"]["low"] == 1400 and got["a"]["fy"] == "FY27"
    assert got["b"] is None and got["c"] is None and len(out["X.NS"]["promises"]) == 3
    assert [r["field"] for r in rep["X.NS"]["rejected"]] == ["promise target"]


# ---- docling text: only from a file that records the same source URL ----

@pytest.fixture
def docling(tmp_path, monkeypatch):
    monkeypatch.setattr(docread, "DIR", tmp_path)
    monkeypatch.setattr(docread, "INDEX", tmp_path / "index.json")
    monkeypatch.setattr(verify, "_fetch_text", lambda url: None)  # the source link is dead

    def put(url, body, recorded=None, ok=True):
        head = "" if recorded is False else docread.HEAD.format(recorded or url)
        (tmp_path / f"{docread.key(url)}.md").write_text(head + body)
        idx = json.loads((tmp_path / "index.json").read_text()) if (tmp_path / "index.json").exists() else {}
        idx[url] = {"ok": ok}
        (tmp_path / "index.json").write_text(json.dumps(idx))
    return put


def test_docling_text_verifies_when_it_records_the_url(docling):
    docling("https://a/x.pdf", "Revenue for the quarter rose 40% to Rs 500 crore.")
    assert verify.fetch_text("https://a/x.pdf") == "Revenue for the quarter rose 40% to Rs 500 crore."
    assert docread.text_for("https://a/x.pdf") == "Revenue for the quarter rose 40% to Rs 500 crore."
    it = {"quote": "Revenue for the quarter rose 40%", "source": "https://a/x.pdf", "text": "Revenue up 40%"}
    assert check(it, ("text",)) is None


def test_docling_text_from_another_url_or_unrecorded_is_ignored(docling):
    docling("https://a/x.pdf", "Revenue for the quarter rose 40% to Rs 500 crore.", recorded="https://b/y.pdf")
    assert verify.fetch_text("https://a/x.pdf") is None
    assert docread.text_for("https://a/x.pdf") is None
    docling("https://a/z.pdf", "Revenue for the quarter rose 40% to Rs 500 crore.", recorded=False)
    assert verify.fetch_text("https://a/z.pdf") is None
    assert docread.text_for("https://a/z.pdf") is not None  # packs may still show an older file's tables
    docling("https://a/w.pdf", "Revenue for the quarter rose 40% to Rs 500 crore.", ok=False)
    assert verify.fetch_text("https://a/w.pdf") is None


def test_committed_docling_files_record_their_url():
    idx = json.loads(docread.INDEX.read_text()) if docread.INDEX.exists() else {}
    for url, e in idx.items():
        f = docread.DIR / f"{docread.key(url)}.md"
        if e.get("ok") and f.exists():
            assert f.read_text().startswith(docread.HEAD.format(url)), url


def test_bare_table_number_takes_unit_from_source_document(doc):
    it = {"text": "First-half revenue ₹574.34 cr", "quote": "Revenues 574.34 420.51 36.6%", "source": "u"}
    doc["u"] = "Statement of results (Rs in crore)\nRevenues 574.34 420.51 36.6%"
    assert check(it, ("text",)) is None
    doc["u"] = "Statement of results (Rs in lakh)\nRevenues 574.34 420.51 36.6%"
    assert "units" in check(it, ("text",))
