from narrativ import falsealarms as FA
from narrativ import verify as V


def test_build_counts_by_rule_and_lists_repeats():
    th = {"A": {"flag_reviews": {"G2": {"verdict": "dismissed", "note": "subsidiary", "source": "u1", "date": "2026-11-20"}},
                "news_reviews": [{"url": "e1", "verdict": "false_alarm", "why": "scheme of arrangement"}]},
          "B": {"flag_reviews": {"G2": {"verdict": "dismissed", "note": "routine", "date": "2026-11-21"}},
                "news_reviews": [{"url": "e2", "verdict": "real", "why": "creditor petition admitted"}]}}
    ev = {"A": [{"url": "e1", "type": "Insolvency", "date": "2026-11-20", "text": "NCLT sanction of scheme"}],
          "B": [{"url": "e2", "type": "Insolvency", "date": "2026-11-22"}]}
    r = FA.build(th, ev, "2026-11-28")
    assert r["by_rule"]["flag G2"]["false"] == 2 and r["by_rule"]["flag G2"]["rate"] == 1.0
    assert r["by_rule"]["event Insolvency"] == {"real": 1, "false": 1, "rate": 0.5, "examples": [
        {"s": "A", "date": "2026-11-20", "text": "NCLT sanction of scheme", "why": "scheme of arrangement", "url": "e1"}]}
    assert r["repeat"] == ["flag G2"]
    assert r["by_rule"]["flag G2"]["examples"][0]["s"] == "B"  # newest first


def test_verify_news_reviews_rules():
    for bad in ({"verdict": "maybe"}, {"url": ""}, {"why": ""}):
        it = {"date": "2026-11-28", "url": "https://x/y.pdf", "verdict": "false_alarm", "why": "scheme", **bad}
        v, rep = V.verify_all({"S": {"news_reviews": [it]}})
        assert v["S"]["news_reviews"] == [] and rep["S"]["rejected"][0]["field"] == "news_reviews"
    v, rep = V.verify_all({"S": {"news_reviews": [{"url": "https://x/y.pdf", "verdict": "real", "why": "petition admitted"}]}})
    assert v["S"]["news_reviews"] == [] and "missing quote or source" in rep["S"]["rejected"][0]["reason"]


def test_verifier_reads_zip_filings():
    import io
    import zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("KMP.xml", "<x><Reason>Resigned due to pre-occupation with other assignments</Reason></x>")
        z.writestr("note.txt", "Effective close of business hours")
    t = V._doc_text(b.getvalue(), "https://nsearchives.nseindia.com/x_Doc.zip")
    assert V.quoted_in("Resigned due to pre-occupation with other assignments", t) and "close of business" in t


def test_due_periods_fy_then_quarter_and_month_ranges():
    from datetime import date
    d = date(2026, 11, 10)
    assert V.due_periods("revenue in financial year '29, Q1", d) == [("financial year '29, q1", date(2028, 6, 30))]
    assert V.due_periods("deliveries from October to December", d) == [("october to december", date(2026, 12, 31))]
    assert V.due_periods("January to March shipments", d) == [("january to march", date(2027, 3, 31))]


def test_reader_quote_widened_to_whole_words():
    from narrativ.reader import whole_words
    t = "We expect revenue of Rs 900-1,000 crores by FY30 from the new\n plant at Pune."
    assert whole_words("revenue of Rs 900-1,000 crore", t) == "revenue of Rs 900-1,000 crores"
    assert whole_words("new plant", t) == "new plant" and whole_words("absent", t) == "absent"
