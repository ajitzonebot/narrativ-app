"""Queue hygiene (overdue, scan gaps, recheck gating, thin documents), scan-request closing, research run log reader. Offline."""
import json
from datetime import date, datetime, timezone

from narrativ import overdue as OD
from narrativ import packs as PK
from narrativ import requests as RQ
from narrativ import runlog

TODAY = date(2026, 11, 20)


def _th(**kw):
    base = {"updated": "2026-11-10", "promises": [], "scan": {"date": "2026-11-01", "kill_switches": [], "must_go_right": []}}
    base.update(kw)
    return base


def _ks(due, quote="q", source="s", text="margin collapses"):
    return {"text": text, "due": due, "quote": quote, "source": source}


# ---------- thin / junk documents ----------

def test_thin_text_cover_letter_and_audio_link():
    assert PK.thin_text("Dear Sir, please find enclosed the transcript. Regards")
    assert PK.thin_text("")
    assert PK.thin_text(None)
    audio = "Intimation under Regulation 30. The audio recording of the call is available at the link below. " * 20
    assert len(audio) < PK.THIN_CHARS_WORDED and PK.thin_text(audio)
    real = "Operator: Thank you. We expect revenue growth of 20% next year. " * 100
    assert not PK.thin_text(real)


def test_thin_text_keeps_short_real_call_with_qa():
    t = ("Pursuant to regulation 30 we submit the transcript. " + "Management remarks about demand and capacity. " * 50
         + " We will now begin the question and answer session. " + "Analyst asks about margins. " * 20)
    assert not PK.thin_text(t)


def test_junk_filing_audio_intimation_cover_letter():
    f = lambda text, url: {"text": f"X Limited has informed the Exchange about {text}", "url": url}  # noqa: E731
    assert PK.junk_filing(f("Link of Recording", "https://x/A_AudioRecordingofAnalystMeeting16112026.pdf"))
    assert PK.junk_filing(f("Schedule of meet", "https://x/DSSL_INTIMATIONEARNINGCALLQ2FY27DSSL.pdf"))
    assert PK.junk_filing(f("Transcript", "https://x/APCOTEXIND_Covering_Letter_signed.pdf"))
    assert not PK.junk_filing(f("Transcript", "https://x/RAILTEL_Intimation_Earning-Call_Transcript.pdf"))
    assert not PK.junk_filing(f("Investor Presentation", "https://x/SRM_Investor_Presentation_Q2_Intimation.pdf"))
    assert not PK.junk_filing(f("Transcript", "https://x/BONDADA_Transcript_of_Concall.pdf"))


def test_new_documents_only_real_and_after_updated():
    fl = [{"date": "2026-11-18", "text": "A has informed the Exchange about Schedule of meet", "url": "https://x/intimation.pdf"},
          {"date": "2026-11-16", "text": "A has informed the Exchange about Link of Recording", "url": "https://x/audio.pdf"},
          {"date": "2026-11-12", "text": "A has informed the Exchange about Transcript", "url": "https://x/t.pdf"},
          {"date": "2026-11-05", "text": "A has informed the Exchange about Investor Presentation", "url": "https://x/p.pdf"}]
    got = PK.new_documents(fl, "2026-11-10", text_of=lambda u: None)
    assert [f["url"] for f in got] == ["https://x/t.pdf"]
    assert PK.new_documents(fl, "2026-11-10", text_of=lambda u: "Covering letter. Kindly find the transcript.") == []  # cached text is thin
    assert PK.new_documents(None, "2026-11-10") == []
    assert len(PK.new_documents(fl, None, text_of=lambda u: None)) == 2  # no `updated`: every real document counts


# ---------- overdue and gaps ----------

def test_past_due_orders_and_skips_resolved():
    th = _th(promises=[{"id": "p1", "due": "2026-10-01", "status": "unverified", "promise": "plant"},
                       {"id": "p2", "due": "2026-10-01", "status": "delivered"},
                       {"id": "p3", "due": "2027-01-01", "status": "pending"}],
             scan={"kill_switches": [_ks("2026-11-14"), _ks("2026-11-01")], "must_go_right": [_ks("2026-11-02", text="dso")]},
             resolved={"kill_switch-1-2026-11-01": {"status": "met"}})
    items = OD.past_due(th, None, TODAY)
    assert [(i["kind"], i["days_late"]) for i in items] == [("kill_switch", 6), ("must_go_right", 18), ("promise", 50)]
    assert OD.past_due(_th(), None, TODAY) == []


def test_past_due_results_checkpoint_and_resolved_checkpoint():
    mem = {"checkpoints": [{"id": "results-2026-09-30", "type": "results", "due": "2026-11-14", "status": "due", "what": "Q2"},
                           {"id": "kill_switch-0-2026-11-14", "type": "kill_switch", "due": "2026-11-14", "status": "met"}]}
    th = _th(scan={"kill_switches": [_ks("2026-11-14")]})
    assert [i["kind"] for i in OD.past_due(th, mem, TODAY)] == ["results"]  # the kill switch checkpoint is resolved


def test_gaps_quote_source_and_due():
    th = _th(scan={"kill_switches": [_ks("2026-12-01"), _ks("2026-12-01", quote=""), _ks(None)],
                   "must_go_right": [_ks("2026-12-01", source=None)]})
    g = OD.gaps(th)
    assert [(x["kind"], x["n"], x["missing"]) for x in g] == [("kill_switch", 1, ["quote"]), ("kill_switch", 2, ["due"]),
                                                              ("must_go_right", 0, ["source"])]
    assert OD.gaps(_th()) == []


def test_plan_priority_cooldown_and_new_document_gating():
    raw = {"HOLDKS.NS": _th(scan={"kill_switches": [_ks("2026-11-14")]}),
           "OLDPROM.NS": _th(promises=[{"id": "a", "due": "2026-03-31", "status": "unverified", "promise": "x"}]),
           "MGR.NS": _th(scan={"must_go_right": [_ks("2026-11-10")]}),
           "TODAY.NS": _th(updated="2026-11-20", promises=[{"id": "a", "due": "2026-03-31", "status": "unverified"}]),
           "TODAYDOC.NS": _th(updated="2026-11-20", promises=[{"id": "a", "due": "2026-03-31", "status": "unverified"}]),
           "KSOTHER.NS": _th(scan={"kill_switches": [_ks("2026-11-14")]}),
           "RES.NS": _th(), "RESDOC.NS": _th(),
           "GAP.NS": _th(scan={"kill_switches": [_ks("2027-01-01", quote="")]}),
           "GAPNEW.NS": _th(updated="2026-11-20", scan={"kill_switches": [_ks("2027-01-01", quote="")]})}
    cp = {"checkpoints": [{"id": "results-x", "type": "results", "due": "2026-11-14", "status": "due"}]}
    mem = {"RES.NS": cp, "RESDOC.NS": cp}
    docs = {"TODAYDOC.NS": [{"date": "2026-11-21"}], "RESDOC.NS": [{"date": "2026-11-19"}]}
    p = OD.plan(raw, mem, TODAY, lambda s: docs.get(s, []), {"HOLDKS.NS"}, 3)
    order = [s for s, _, _ in p["overdue"]]
    assert order[0] == "HOLDKS.NS" and p["overdue"][0][2] is True  # kill switch on a Hold: first
    assert order.index("KSOTHER.NS") < order.index("MGR.NS") < order.index("OLDPROM.NS")  # kill switch > must-go-right > promise
    assert "TODAY.NS" not in order  # researched today and nothing new filed: nothing to check
    assert "TODAYDOC.NS" in order  # a new document came in: back in
    assert "RES.NS" not in order  # results checkpoint alone does not qualify (results document not out)
    assert "RESDOC.NS" in order and order[-1] == "RESDOC.NS"
    assert [s for s, _ in p["gaps"]] == ["GAP.NS"]  # GAPNEW was researched today: cooldown


def test_reason_texts():
    items = OD.past_due(_th(promises=[{"id": "p", "due": "2026-10-01", "status": "unverified"}],
                            scan={"kill_switches": [_ks("2026-11-14")]}), None, TODAY)
    r = OD.reason(items)
    assert r.startswith("overdue: 1 kill switch, 1 promise") and "50 days late" in r
    assert "1 without a quote or source" in OD.gap_reason(OD.gaps(_th(scan={"kill_switches": [_ks("2026-12-01", quote="")]})))


# ---------- scan requests ----------

class _Resp:
    def __init__(self, ok=True, status=200):
        self.ok, self.status_code = ok, status


class _Http:
    def __init__(self, comment_ok=True):
        self.calls, self.comment_ok = [], comment_ok

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json))
        return _Resp(self.comment_ok, 200 if self.comment_ok else 403)

    def patch(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("PATCH", url, json))
        return _Resp()


def test_ist_date_converts_utc_evening_to_next_day():
    assert RQ._ist_date("2026-11-19T22:00:00Z") == "2026-11-20"
    assert RQ._ist_date("2026-11-19T10:00:00Z") == "2026-11-19"
    assert RQ._ist_date(None) is None


def test_done_requests_updated_on_or_after_request_date():
    reqs = [{"symbol": "A.NS", "via": "issue #1", "issue": 1, "date": "2026-11-18"},
            {"symbol": "B.NS", "via": "issue #2", "issue": 2, "date": "2026-11-18"},
            {"symbol": "C.NS", "via": "issue #3", "issue": 3, "date": "2026-11-18"},
            {"symbol": "D.NS", "via": "issue #4", "issue": 4, "date": "2026-11-18"},
            {"symbol": "F.NS", "via": "file"}]
    th = {"A.NS": {"updated": "2026-11-18"},
          "B.NS": {"updated": "2026-11-10", "audit": {"date": "2026-11-19", "verdict": "caution"}},
          "C.NS": {"updated": "2026-11-17", "audit": {"date": "2026-11-17"}},
          "F.NS": {"updated": "2026-11-20"}}
    got = {r["symbol"]: r for r in RQ.done(reqs, th)}
    assert set(got) == {"A.NS", "B.NS"}  # C older, D never researched, F is a file request (no issue to close)
    assert got["B.NS"]["verdict"] == "caution" and got["B.NS"]["reviewed"] == "2026-11-19"


def test_close_done_comments_then_closes_with_signature():
    http = _Http()
    reqs = [{"symbol": "A.NS", "via": "issue #7", "issue": 7, "date": "2026-11-18"}]
    th = {"A.NS": {"updated": "2026-11-19", "audit": {"date": "2026-11-19", "verdict": "pass"}}}
    assert RQ.close_done(reqs, th, repo="o/r", tok="t", http=http) == [7]
    (m1, u1, body), (m2, u2, patch) = http.calls
    assert (m1, u1) == ("POST", "https://api.github.com/repos/o/r/issues/7/comments")
    assert body["body"].endswith("\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_")
    assert "A.NS" in body["body"] and "pass" in body["body"]
    assert (m2, u2, patch) == ("PATCH", "https://api.github.com/repos/o/r/issues/7", {"state": "closed", "state_reason": "completed"})


def test_close_done_without_issues_write_leaves_issue_open(capsys):
    http = _Http(comment_ok=False)
    reqs = [{"symbol": "A.NS", "via": "issue #7", "issue": 7, "date": "2026-11-18"}]
    assert RQ.close_done(reqs, {"A.NS": {"updated": "2026-11-19"}}, repo="o/r", tok="t", http=http) == []
    assert [c[0] for c in http.calls] == ["POST"]  # never closed without the comment
    assert "issues: write" in capsys.readouterr().out


def test_close_done_without_token_does_nothing(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    http = _Http()
    assert RQ.close_done([{"symbol": "A.NS", "issue": 1, "date": "2026-01-01"}], {"A.NS": {"updated": "2026-11-19"}}, http=http) == []
    assert http.calls == []


# ---------- research run log ----------

def test_parse_time_all_formats():
    day = "2026-11-20"
    iso = datetime(2026, 11, 20, 12, 36, tzinfo=timezone.utc)
    assert runlog.parse_time("2026-11-20T18:06+05:30") == iso
    assert runlog.parse_time("2026-11-20T12:36Z") == iso
    assert runlog.parse_time("2026-11-20 18:06 IST") == iso
    assert runlog.parse_time("18:06 IST", day) == iso
    assert runlog.parse_time("12:36 UTC", day) == iso
    assert runlog.parse_time("22:36 IST+0 (UTC 22:35)", day) == datetime(2026, 11, 20, 22, 35, tzinfo=timezone.utc)
    assert runlog.parse_time("08:36 UTC (14:06 IST)", day) == datetime(2026, 11, 20, 8, 36, tzinfo=timezone.utc)
    assert runlog.parse_time("18:06 IST") is None  # no date to put it on
    for bad in (None, "", "soon", "25:99 IST"):
        assert runlog.parse_time(bad, day) is None


def test_read_tolerates_mixed_formats_and_bad_lines(tmp_path):
    f = tmp_path / "runs.jsonl"
    f.write_text("\n".join([
        json.dumps({"start": "2026-11-19T23:05+05:30", "end": "2026-11-19T23:07+05:30", "queue_date": "2026-11-19", "done": []}),
        "not json at all",
        json.dumps({"start": "22:36 IST+0 (UTC 22:35)", "end": "23:00 UTC", "queue_date": "2026-11-20", "done": ["A:recheck"]}),
        json.dumps({"start": "08:36 UTC (14:06 IST)", "end": "08:55 UTC (14:25 IST)", "queue_date": "2026-11-20", "done": []}),
        json.dumps({"start": "garbled", "end": None, "queue_date": "2026-11-20"}),
        json.dumps([1, 2])]))
    runs = runlog.read(f)
    assert len(runs) == 4
    assert runs[0]["start_utc"] == "2026-11-19T17:35+00:00" and runs[0]["approx"] is False
    assert runs[1]["start_utc"] == "2026-11-19T22:35+00:00" and runs[1]["end_utc"] == "2026-11-19T23:00+00:00"  # day moved next to run 1
    assert runs[2]["start_utc"] == "2026-11-20T08:36+00:00" and runs[2]["end_utc"] == "2026-11-20T08:55+00:00"
    assert runs[3]["start_utc"] is None and runs[3]["end_utc"] is None
    assert runlog.read(tmp_path / "missing.jsonl") == []
    s = runlog.summary(runs)
    assert s["runs"] == 4 and s["last_end"] is None
