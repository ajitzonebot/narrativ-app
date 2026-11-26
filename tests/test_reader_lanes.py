from narrativ import quota as q
from narrativ.reader import FLASH_LANE, LITE_LANE, CHECK_LANE, label_agreement


AVAIL = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-preview-tts",
         "gemini-3-flash-preview", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-4-hydrogen", "gemma-4-31b-it", "gemma-4-26b-a4b-it",
         "gemini-3.8-flash-lite-tts"]


def test_resolve_lanes():
    assert q.resolve(LITE_LANE, AVAIL) == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
    assert q.resolve(FLASH_LANE, AVAIL) == ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-2.5-flash"]
    assert q.resolve(CHECK_LANE, AVAIL) == ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]


def test_quota_caps_and_counts(tmp_path):
    g = q.Quota(tmp_path / "u.json")
    assert q.limits("gemini-3.8-flash")[2] == 19 and q.limits("gemma-4-31b-it")[1] == 15_000
    for _ in range(3):
        assert g.take("gemini-3.1-flash-lite", 1000, cap=3)
    assert not g.take("gemini-3.1-flash-lite", 1000, cap=3)
    assert g.used("gemini-3.1-flash-lite") == 3
    assert g.refused("gemma-4-31b-it") is True and g.refused("gemma-4-31b-it") is False
    assert g.left("gemma-4-31b-it") == 0


def test_agreement_labels():
    store = {"u": {"lite": {"rows": [{"quote": "We expect revenue to grow 20% in FY27."}, {"quote": "Margins will stay flat."}]},
                   "flash": {"rows": [{"quote": "We expect revenue to grow 20% in FY27."}]}}}
    assert label_agreement(store) == 2
    assert [r["agree"] for r in store["u"]["lite"]["rows"]] == [True, False]


def test_forward_keeps_rows_over_an_empty_flash_read_and_an_empty_newer_document(tmp_path, monkeypatch):
    from narrativ import reader as R
    monkeypatch.setattr(R, "FORWARD", tmp_path / "f.json")
    row = {"kind": "guidance", "text": "AUM up 20%", "quote": "we guided 20% to 25%", "due": "2027-03-31"}
    store = {"u1": {"s": "X.NS", "kind": "transcript", "date": "2026-11-03",
                    "flash": {"model": "f", "rows": []}, "lite": {"model": "l", "rows": [row]}},
             "u2": {"s": "X.NS", "kind": "presentation", "date": "2026-11-13", "lite": {"model": "l", "rows": []}}}
    x = R.forward(store)["stocks"]["X.NS"]
    assert x["url"] == "u1" and x["rows"] == 1 and x["model"] == "l"


# ---------------------------------------------------------------- lane errors and the story reserve (audit 26 Nov 2026)
import threading  # noqa: E402
from collections import Counter  # noqa: E402

LANE = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
DOC = {"s": "X.NS", "kind": "transcript", "date": "2026-11-20", "url": "u"}


def _run(monkeypatch, tmp_path, answers, lane=LANE, store=None):
    """_stage_run on one document with read() answering from `answers` (model -> list of (rows, meta)); returns
    (store, calls, quota, log)."""
    from narrativ import reader as R
    calls = []

    def fake_read(key, model, text):
        calls.append(model)
        return answers[model].pop(0)
    monkeypatch.setattr(R, "read", fake_read)
    monkeypatch.setattr(R, "STORE", tmp_path / "store.json")
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    monkeypatch.setattr(R.packs, "doc_text", lambda url, ns, kind=None: ("We expect revenue to grow 20% in FY27. " * 40, 1, "x"))
    g = q.Quota(tmp_path / "u.json")
    store = {} if store is None else store
    log: Counter = Counter()
    R._stage_run("lite", lane, [dict(DOC)], "k", store, threading.Lock(), 10 ** 12, [object()], log, g)
    return store, calls, g, log


OK = ([{"kind": "guidance", "text": "Revenue to grow 20% in FY27", "quote": "We expect revenue to grow 20% in FY27."}], {"finish": "STOP"})


def test_http_400_tries_the_next_model_and_is_not_a_fail(monkeypatch, tmp_path):
    store, calls, _, _ = _run(monkeypatch, tmp_path, {LANE[0]: [([], {"error": "HTTP 400"})], LANE[1]: [OK]})
    assert calls == LANE[:2] and store["u"]["lite"]["model"] == LANE[1] and len(store["u"]["lite"]["rows"]) == 1


def test_http_400_from_every_model_keeps_the_fail_count(monkeypatch, tmp_path):
    bad = {m: [([], {"error": "HTTP 400"})] for m in LANE}
    store, calls, _, _ = _run(monkeypatch, tmp_path, bad, store={"u": {"lite": {"fails": 1, "error": "x"}}})
    assert calls == LANE and store["u"]["lite"]["fails"] == 1 and store["u"]["lite"]["error"] == "HTTP 400"


def test_404_then_next_model_out_records_nothing_against_either(monkeypatch, tmp_path):
    from narrativ import reader as R
    monkeypatch.setattr(R, "lane_cap", lambda m: 0 if m == LANE[1] else None)  # model 2 has no allowance left
    store, calls, g, _ = _run(monkeypatch, tmp_path, {LANE[0]: [([], {"error": "HTTP 404"})]}, lane=LANE[:2])
    assert calls == [LANE[0]] and "lite" not in store.get("u", {}) and g.left(LANE[0]) == 0


def test_404_then_next_model_reads(monkeypatch, tmp_path):
    store, calls, g, _ = _run(monkeypatch, tmp_path, {LANE[0]: [([], {"error": "HTTP 404"})], LANE[1]: [OK]})
    assert calls == LANE[:2] and store["u"]["lite"]["model"] == LANE[1] and LANE[0] in g.out


def test_429_retry_then_a_later_single_429_is_retried_again(monkeypatch, tmp_path):
    from narrativ import reader as R
    r429 = ([], {"error": "HTTP 429"})
    # doc 1: a 429, then read on the retry
    store, calls, g, _ = _run(monkeypatch, tmp_path, {LANE[0]: [r429, OK]})
    assert calls == [LANE[0], LANE[0]] and store["u"]["lite"]["model"] == LANE[0]
    # doc 2, same quota: one more 429 is a first refusal again (retried), not the second that ends the model
    answers, calls2 = [r429, OK], []
    monkeypatch.setattr(R, "read", lambda k, m, t: (calls2.append(m), answers.pop(0))[1])
    R._stage_run("lite", LANE, [dict(DOC, url="u2")], "k", store, threading.Lock(), 10 ** 12, [object()], Counter(), g)
    assert calls2 == [LANE[0], LANE[0]] and LANE[0] not in g.out and store["u2"]["lite"]["model"] == LANE[0]
    assert g.day()[LANE[0]]["refused"] == 2  # one per refusal, never counted twice


def test_two_429s_in_a_row_end_the_model_and_move_on_without_a_fail(monkeypatch, tmp_path):
    r429 = ([], {"error": "HTTP 429"})
    store, calls, g, _ = _run(monkeypatch, tmp_path, {LANE[0]: [r429, r429], LANE[1]: [OK]})
    assert calls == [LANE[0], LANE[0], LANE[1]] and LANE[0] in g.out and g.day()[LANE[0]]["refused"] == 2
    assert store["u"]["lite"]["model"] == LANE[1]


def test_every_model_refused_is_not_the_documents_fail(monkeypatch, tmp_path):
    r429 = ([], {"error": "HTTP 429"})
    store, _, g, _ = _run(monkeypatch, tmp_path, {m: [r429, r429] for m in LANE})
    assert "lite" not in store.get("u", {}) and all(m in g.out for m in LANE)


def test_reader_leaves_the_story_reserve(tmp_path):
    from narrativ import story
    assert q.reader_cap("gemini-3.1-flash-lite") == q.limits("gemini-3.1-flash-lite")[2] - q.STORY_RESERVE
    assert q.reader_cap("gemini-3.1-flash-lite-preview") == q.reader_cap("gemini-3.1-flash-lite")  # resolved ids too
    assert q.reader_cap("gemini-3.5-flash-lite") is None
    for m in story.MODELS:  # every model the story job calls is reserved
        assert q.reader_cap(m) is not None, m
    g = q.Quota(tmp_path / "u.json")
    assert not g.take("gemini-flash-lite-latest", 100, cap=0)  # a zero cap is a cap, not "no cap"
