from pathlib import Path

import vcr

from narrativ import packs, reader

DOC = "Good morning, everyone. Our new 10,000 tonne plant will start in March 2027. Margins should improve to 18% next year."
CASS = Path(__file__).parent / "cassettes"


def test_clean_keeps_verbatim_flags_added_numbers_drops_reworded():
    rows = [
        {"kind": "capacity", "text": "Plant of 10,000 tonnes starts March 2027", "due": "2027-03-31",
         "quote": "Our new 10,000 tonne plant will start in March 2027."},
        {"kind": "margin", "text": "Margins to 18% in FY27", "quote": "Margins should improve to 18% next year."},
        {"kind": "order", "text": "Orders of 500 crore", "quote": "We won orders of 500 crore."},
        {"kind": "bogus", "text": "x", "due": "March 2027", "quote": "Good morning, everyone."},
    ]
    keep, drop = reader.clean(rows, DOC)
    assert [r["kind"] for r in keep] == ["capacity", "margin", "other"]
    assert keep[1]["text_not_in_quote"] == ["27"]  # model added FY27: flagged, kept
    assert "text_not_in_quote" not in keep[0]
    assert keep[2]["due"] is None  # not YYYY-MM-DD
    assert drop["quote not verbatim"] == 1


def test_matches_same_statement():
    c = {"quote": "Our new 10,000 tonne plant will start in March 2027."}
    assert reader.matches(c, {"quote": "Our new 10,000 tonne plant will start in March 2027. More text follows here."})
    assert not reader.matches(c, {"quote": "Margins should improve to 18% next year."})


def test_agreement_matches_nse_in_and_com():
    url = "https://nsearchives.nseindia.in/corporate/X_TRANSCRIPT.pdf"
    q = "Our new 10,000 tonne plant will start in March 2027."
    store = {url: {"s": "X.NS", "flash": {"at": "2026-11-19", "rows": [{"quote": q}]}}}
    theses = {"X.NS": {"audit": {"date": "2026-11-19", "verdict": "pass"},
                       "drivers": [{"quote": q, "source": url.replace(".in/", ".com/")}]}}
    a = reader.agreement(store, theses)
    assert a["flash"] == {"claude_items": 1, "found_pct": 100, "reader_rows": 1, "used_pct": 100}


def test_plan_orders_claude_queue_first_and_flash_one_doc_per_stock():
    docs = [{"s": "B.NS", "rk": 1, "task": None, "kind": "transcript", "date": "2026-11-01", "url": "b"},
            {"s": "A.NS", "rk": 50, "task": "review", "kind": "presentation", "date": "2026-11-01", "url": "a1"},
            {"s": "A.NS", "rk": 50, "task": "review", "kind": "transcript", "date": "2026-11-01", "url": "a2"}]
    lite, flash = reader._plan(docs, {"b": {"lite": {"rows": []}}}, {})
    assert [d["url"] for d in lite] == ["a2", "a1"]  # b already read; transcript first
    assert [d["url"] for d in flash] == ["a2", "b"]


def test_attach_prefers_flash():
    store = {"u": {"lite": {"model": "lite", "at": "d", "rows": [1]}, "flash": {"model": "flash", "at": "d", "rows": [2]}}}
    d = {"url": "u"}
    assert packs.attach_reader(d, store) and d["reader"]["rows"] == [2]


def test_read_retries_overloaded_model(monkeypatch):
    monkeypatch.setattr(reader.time, "sleep", lambda s: None)
    with vcr.use_cassette(str(CASS / "gemini_503_then_ok.yaml"), record_mode="none"):
        items, meta = reader.read("test-key", "gemini-3.5-flash-lite", DOC)
    assert meta["finish"] == "STOP"
    assert items[0]["due"] == "2027-03-31"
