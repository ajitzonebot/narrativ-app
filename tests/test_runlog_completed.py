import json
from datetime import datetime, timezone

from narrativ import runlog


def test_completed_lists_recent_runs_newest_first(tmp_path):
    f = tmp_path / "runs.jsonl"
    # every real line has start and end (ISO); a line without them is dated by its neighbours (runlog.read)
    f.write_text("\n".join(json.dumps(x) for x in [
        {"start": "2026-11-10T04:05+05:30", "end": "2026-11-10T04:30+05:30", "done": ["OLD:pass"]},
        {"task": "review", "start": "2026-11-24T18:05+05:30", "end": "2026-11-24T18:30+05:30", "done": ["EPL:pass", "CEATLTD.NS:fail"]},
        {"task": "catalyst", "start": "2026-11-25T07:05+05:30", "end": "2026-11-25T07:40+05:30", "done": ["ACE:enrich", "industries:Gas,Media (none found)"]},
        {"start": "2026-11-25T09:05+05:30", "end": "2026-11-25T09:10+05:30", "done": []}]))
    out = runlog.completed(7, now=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc), path=f, out_path=tmp_path / "done.json")
    assert [r["task"] for r in out["runs"]] == ["catalyst", "review"]
    assert out["runs"][0]["items"] == [{"s": "ACE.NS", "r": "enrich"}, {"industries": "Gas,Media (none found)"}]
    assert out["runs"][1]["items"][1] == {"s": "CEATLTD.NS", "r": "fail"}


def test_one_note_for_two_stocks_becomes_two_rows(tmp_path):
    # feedback #136: "BONDADA.NS/CAPLIPOINT.NS" opened an empty stock page
    f = tmp_path / "runs.jsonl"
    f.write_text(json.dumps({"start": "2026-11-25T09:05+05:30", "end": "2026-11-25T09:30+05:30",
                             "done": ["BONDADA.NS/CAPLIPOINT.NS:already covered by earlier run, no change"]}))
    out = runlog.completed(7, now=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc), path=f, out_path=tmp_path / "done.json")
    assert [i["s"] for i in out["runs"][0]["items"]] == ["BONDADA.NS", "CAPLIPOINT.NS"]


def test_ampersand_inside_a_symbol_is_kept(tmp_path):
    # review 26 Nov 2026: J&KBANK and M&M are symbols; only a spaced "&" or "and" joins two stocks
    f = tmp_path / "runs.jsonl"
    f.write_text(json.dumps({"start": "2026-11-25T09:05+05:30", "end": "2026-11-25T09:30+05:30",
                             "done": ["J&KBANK.NS:pass", "M&M:enrich", "TCS & INFY:pass"]}))
    out = runlog.completed(7, now=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc), path=f, out_path=tmp_path / "done.json")
    assert [i["s"] for i in out["runs"][0]["items"]] == ["J&KBANK.NS", "M&M.NS", "TCS.NS", "INFY.NS"]
