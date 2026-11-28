from narrativ import issuelog as IL


def test_add_sighting_fix_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(IL, "DIR", tmp_path)
    monkeypatch.setattr(IL, "FIXES", tmp_path / "fixes.jsonl")
    a = IL.add("review", "pipeline", "pack points to a missing dossier", "BONDADA.BO has no fin file", "high", "BONDADA.BO",
               "docs/data/fin/BONDADA.BO.json missing", run="2026-11-28T12:26")
    IL.add("catalyst", "bug", "other", "x", run="2026-11-28T12:26")
    IL.add("review", "pipeline", "pack points to a missing dossier", "again", run="2026-11-28T18:05", same=a["id"])
    items = {i["id"]: i for i in IL.load(tmp_path)}
    it = items[a["id"]]
    assert it["seen"] == 2 and it["status"] == "open" and it["sightings"][0]["detail"] == "again"
    assert len(list(tmp_path.glob("*.jsonl"))) == 3  # one file per run
    IL.fix(a["id"], "fixed", "requests map .BO to the scored .NS listing", "https://github.com/x/pull/261")
    it = {i["id"]: i for i in IL.load(tmp_path)}[a["id"]]
    assert it["status"] == "fixed" and it["fix_ref"].endswith("/261")
    IL.add("review", "pipeline", "pack points to a missing dossier", "still there", run="2099-01-01T00:00", same=a["id"])
    monkeypatch.setattr(IL, "_now", lambda: IL.datetime(2099, 1, 1, tzinfo=IL.IST))
    IL.add("review", "pipeline", "seen after the fix", "y", run="z", same=a["id"])
    it = {i["id"]: i for i in IL.load(tmp_path)}[a["id"]]
    assert it["status"] == "open" and it["fix"].startswith("reopened")
    rows = IL.d1_rows(IL.load(tmp_path))
    assert len(rows[0]) == len(IL.COLS)


def test_auto_dedups_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(IL, "DIR", tmp_path)
    monkeypatch.setattr(IL, "FIXES", tmp_path / "fixes.jsonl")
    assert IL.auto("daily", "pipeline", "daily run: packs failed", "boom") is not None
    assert IL.auto("daily", "pipeline", "daily run: packs failed", "boom") is None  # same day: no new row
    assert len(IL.load(tmp_path)) == 1


def test_kind_and_severity_checked():
    import pytest
    with pytest.raises(ValueError):
        IL.add("review", "nonsense", "t", "d")
