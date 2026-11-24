from narrativ.packs import excerpts, quality


def test_excerpts_keep_forward_sentences_with_neighbours():
    t = ("Thank you. We expect revenue growth of 20% next year. The board met. "
         "Unrelated remark here. Weather was fine. Nothing else.")
    ex = excerpts(t)
    assert len(ex) == 1 and "20%" in ex[0] and ex[0].startswith("Thank you.")


def test_quality_poor_for_garbage():
    assert quality("@@@@ #### $$$$" * 10, 5)["grade"] == "poor"


def test_cover_letter_followed_to_company_pdf(monkeypatch, tmp_path):
    import narrativ.packs as P
    letter = "Dear Sir, please note that the transcript of the earnings call is available at https://www.example.com/ir/Transcript-Q2.pdf."
    real = "Moderator: Good evening. " + "We expect revenue growth of 20% next year with margin expansion. " * 60
    texts = {"https://nsearchives.nseindia.com/corporate/X_letter.pdf": letter, "https://www.example.com/ir/Transcript-Q2.pdf": real}
    monkeypatch.setattr(P, "TXT", tmp_path)
    monkeypatch.setattr(P, "_text", lambda u, ns: (texts.get(u), 3))
    monkeypatch.setattr(P, "_pdf_bytes", lambda u, ns: None)
    t, pages, src = P.doc_text("https://nsearchives.nseindia.com/corporate/X_letter.pdf", None, "transcript")
    assert src == "https://www.example.com/ir/Transcript-Q2.pdf" and t == real
    assert P.letter_links("https://nsearchives.nseindia.com/corporate/X_letter.pdf", None, letter) == ["https://www.example.com/ir/Transcript-Q2.pdf"]
    t, _, src = P.doc_text("https://www.example.com/ir/Transcript-Q2.pdf", None, "transcript")
    assert src == "https://www.example.com/ir/Transcript-Q2.pdf"  # a real document is not followed anywhere


def test_cover_letter_without_readable_link_stays(monkeypatch, tmp_path):
    import narrativ.packs as P
    letter = "Dear Sir, the transcript is on our website www.example.com/investors and on the exchange www.nseindia.com."
    monkeypatch.setattr(P, "TXT", tmp_path)
    monkeypatch.setattr(P, "_text", lambda u, ns: (letter, 1) if "nse" in u else (None, None))
    monkeypatch.setattr(P, "_pdf_bytes", lambda u, ns: None)
    t, _, src = P.doc_text("https://nsearchives.nseindia.com/corporate/Y.pdf", None, "transcript")
    assert t == letter and src.endswith("Y.pdf")
    assert P.letter_links("https://nsearchives.nseindia.com/corporate/Y.pdf", None, letter) == ["https://www.example.com/investors"]


def test_latest_call_matching_and_waiting():
    from datetime import date
    from narrativ import latest_call as LC
    assert LC.fiscal_quarter("2026-09-30") == ("Q2", 2027) and LC.fiscal_quarter("2026-03-31") == ("Q4", 2026)
    ann = {"rows": {"X.NS": [
        ("2026-09-03", "Transcript", "Transcript of 37th AGM", "https://n/agm.pdf", 0, "Transcript"),
        ("2026-08-05", "Transcript", "Transcript of Q1 call", "https://n/q1.pdf", 0, "Transcript")]}}
    today = date(2026, 11, 24)
    c = LC.latest_call("X.NS", "2026-09-30", "2026-10-30", ann, {}, today, [])
    assert c["state"] == "missing" and c["quarter"] == "Q2 FY27"  # the AGM and the Q1 call are not the latest call
    asc = [{"id": "a" * 8 + "-1111-2222-3333-" + "b" * 12, "fiscal_period": "Q2", "fiscal_year": 2027, "event_type": "earnings_conference",
            "event_utc_datetime": "2026-11-02T06:00:00Z", "transcript_status": "FINAL"}]
    c = LC.latest_call("X.NS", "2026-09-30", "2026-10-30", ann, {}, today, asc)
    assert c["state"] == "found" and c["since"] == "2026-11-02" and c["sources"][0]["src"] == "alphastreet"
    ann["rows"]["X.NS"].append(("2026-11-06", "Transcript", "Transcript of Q2 call", "https://n/q2.pdf", 0, "Transcript"))
    c = LC.latest_call("X.NS", "2026-09-30", "2026-10-30", ann, {}, today, asc)
    assert c["since"] == "2026-11-02" and [x["src"] for x in c["sources"]] == ["exchange", "alphastreet"]
    miss = {"state": "missing", "results_filed": "2026-11-20", "quarter": "Q2 FY27"}
    assert LC.waiting(miss, today) and not LC.waiting({**miss, "results_filed": "2026-11-10"}, today)


def test_alphastreet_render_splits_remarks_and_qa():
    from narrativ.alphastreet import render
    from narrativ.packs import full_transcript
    j = {"items": {"transcript_data": {"call_data": {"company": "X Ltd", "period": "Q2", "year": "2027", "eventdatetime": "2026-11-02T06:00:00Z"},
         "presentation": [{"participant_name": "A", "participant_designation": "CEO", "participant_company": "X Ltd", "transcript_data": ["We expect 20% growth."]}],
         "questions_and_answers": [{"participant_name": "B", "transcript_data": ["What about margins?"]}]}}}
    t = render(j)
    assert "A (CEO, X Ltd): We expect 20% growth." in t and "B: What about margins?" in t
    ft = full_transcript(t)
    assert "20% growth" in ft["remarks"] and "margins" in ft["qa"]


def test_review_before_latest_call_is_pending():
    from datetime import date
    from narrativ import funnel as FN
    a = {"verdict": "pass", "date": "2026-11-01"}
    assert FN.verification(a, "2026-10-30", date(2026, 11, 24))["state"] == "pass"
    v = FN.verification(a, "2026-10-30", date(2026, 11, 24), call_since="2026-11-02")
    assert v["state"] == "pending" and "earnings call" in v["why"]
    assert FN.verification(a, "2026-10-30", date(2026, 11, 24), call_since="2026-10-31")["state"] == "pass"


def test_call_calendar_waits():
    from datetime import date
    from narrativ import latest_call as LC
    today = date(2026, 11, 24)
    assert LC.dates_in("call on Thursday, November 27, 2026 at 4 pm; 27th Nov 2026; 27/11/2026") == [date(2026, 11, 27)] * 3
    ann = {"rows": {"X.NS": [
        ("2026-11-20", "Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of earnings call for Q2 FY27 results", "https://n/int.pdf", 0, None),
        ("2026-11-21", "Analysts/Institutional Investor Meet/Con. Call Updates", "Audio recording of the earnings call", "https://n/aud.pdf", 0, None),
        ("2026-11-19", "Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meet with Motilal Oswal conference", "https://n/conf.pdf", 0, None)]}}
    texts = {"https://n/int.pdf": "The earnings conference call is scheduled on December 1, 2026.", "https://n/conf.pdf": "Meeting on 26 Nov 2026"}
    sc = LC.scheduled_call("X.NS", ann, today, texts.get)
    assert sc == {"date": "2026-12-01", "url": "https://n/int.pdf", "filed": "2026-11-20"}  # the broker conference is not the earnings call
    found = {"state": "found", "results_filed": "2026-11-10", "quarter": "Q2 FY27"}
    miss = {"state": "missing", "results_filed": "2026-11-20", "quarter": "Q2 FY27"}
    assert LC.waiting(found, today, results_due="2026-11-30").startswith("Results due 2026-11-30")
    assert LC.waiting(found, today, results_due="2026-12-20") is None  # too far ahead to wait
    assert LC.waiting({**miss, "results_filed": "2026-11-01"}, today, call_date="2026-12-01").startswith("Earnings call scheduled")
    assert LC.waiting(found, today, call_date="2026-12-01") is None  # the latest call is already in


def test_call_card_drops_repeated_values():
    from narrativ.alphastreet import card_metrics
    ms = [["Revenue", "INR1,794 crores", "up"], ["EBITDA", "INR543 crores", "up"], ["PAT", "INR 543 crores", "up"],
          ["Margin", "30%", ""], ["Bad"]]
    assert [m[0] for m in card_metrics(ms)] == ["Revenue", "EBITDA", "Margin"]
    assert [m[0] for m in card_metrics([["A", "400 million"], ["B", "400 crores"]])] == ["A", "B"]
