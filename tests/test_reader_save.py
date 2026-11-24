"""narrativ.reader.save: the reader's work reaches main even when main moved meanwhile (23 Nov 2026: the daily run rewrote and
deleted packs while the reader ran; the old rebase-and-push failed and ~2 hours of reading was lost)."""
import json
import subprocess

from narrativ import packs
from narrativ import reader as R


def _git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _setup(tmp_path, monkeypatch):
    remote, a, b = tmp_path / "remote.git", tmp_path / "a", tmp_path / "b"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", "-q", str(remote), str(a))
    (a / "docs/data/packs").mkdir(parents=True)
    (a / "data/reader").mkdir(parents=True)
    for s in ("AAA", "BBB"):
        (a / f"docs/data/packs/{s}.json").write_text(json.dumps({"symbol": s, "v": 1}))
    (a / "data/reader/store.json").write_text("{}")
    (a / "data/reader/docs.json").write_text(json.dumps({"docs": [], "v": 1}))
    _git(a, "add", "-A")
    _git(a, "commit", "-q", "-m", "init")
    _git(a, "push", "-q", "origin", "HEAD:main")
    _git(tmp_path, "clone", "-q", str(remote), str(b))
    monkeypatch.chdir(a)
    rel = lambda p: a / p  # noqa: E731
    monkeypatch.setattr(R, "STORE", rel("data/reader/store.json"))
    monkeypatch.setattr(R, "STATS", rel("data/reader/stats.jsonl"))
    monkeypatch.setattr(R, "FORWARD", rel("docs/data/forward.json"))
    monkeypatch.setattr(R, "OWN", (R.STORE, R.STATS, R.FORWARD))
    monkeypatch.setattr(packs, "OUT", rel("docs/data/packs"))
    return remote, a, b


def test_save_survives_main_rewriting_packs(tmp_path, monkeypatch):
    remote, a, b = _setup(tmp_path, monkeypatch)
    # the reader patched both packs locally (uncommitted) ...
    for s in ("AAA", "BBB"):
        (a / f"docs/data/packs/{s}.json").write_text(json.dumps({"symbol": s, "v": 1, "reader": True}))
    # ... while the daily run deleted one, rewrote the other and the document index, and pushed
    (b / "docs/data/packs/AAA.json").unlink()
    (b / "docs/data/packs/BBB.json").write_text(json.dumps({"symbol": "BBB", "v": 2}))
    (b / "data/reader/docs.json").write_text(json.dumps({"docs": [], "v": 2}))
    _git(b, "add", "-A")
    _git(b, "commit", "-q", "-m", "daily")
    _git(b, "push", "-q", "origin", "HEAD:main")

    patched = []
    monkeypatch.setattr(R, "patch_packs", lambda store: patched.append(sorted(p.name for p in packs.OUT.glob("*.json"))) or 1)
    store = {"https://x/doc.pdf": {"s": "BBB", "kind": "transcript", "date": "2026-11-20",
                                    "lite": {"model": "m", "at": "2026-11-23", "rows": [{"kind": "order", "quote": "q"}]}}}
    assert R.save(store)

    _git(b, "pull", "-q", "origin", "main")
    assert json.loads((b / "data/reader/store.json").read_text()) == store  # the reading reached main
    assert (b / "docs/data/forward.json").exists()
    assert not (b / "docs/data/packs/AAA.json").exists()  # main's packs win; rows re-attached on top of them
    assert json.loads((b / "docs/data/packs/BBB.json").read_text())["v"] == 2
    assert json.loads((b / "data/reader/docs.json").read_text())["v"] == 2  # the daily run's file is not overwritten
    assert patched == [["BBB.json"]]


def test_save_nothing_new_is_ok(tmp_path, monkeypatch):
    remote, a, b = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "patch_packs", lambda store: 0)
    assert R.save({})
    before = _git(a, "rev-parse", "HEAD")
    assert R.save({})  # second save: nothing changed, no empty commit
    assert _git(a, "rev-parse", "HEAD") == before
