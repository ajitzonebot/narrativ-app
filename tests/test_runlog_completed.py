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
