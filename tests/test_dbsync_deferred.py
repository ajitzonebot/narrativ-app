"""D1 after the publish: with DEFER_D1=1 run.py saves the sync inputs and `python -m narrativ.dbsync --deferred` runs them."""
from narrativ import dbsync


def test_defer_then_run_calls_sync_once_and_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_DEFER_FILE", str(tmp_path / "d1.pkl"))
    monkeypatch.setenv("DEFER_D1", "1")
    assert dbsync.deferred()
    seen = []
    monkeypatch.setattr(dbsync, "sync", lambda *a, **k: seen.append((a, k)) or {"ok": True})
    dbsync.defer(("2026-11-26", {"x": 1}), {"breadth_in": ([1, 2], {"A": "IN1"})})
    assert dbsync.run_deferred() == {"ok": True}
    assert seen == [(("2026-11-26", {"x": 1}), {"breadth_in": ([1, 2], {"A": "IN1"})})]
    assert not (tmp_path / "d1.pkl").exists()


def test_no_deferred_file_is_a_quiet_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_DEFER_FILE", str(tmp_path / "none.pkl"))
    assert dbsync.run_deferred() == {"ok": False}


def test_failed_sync_never_raises_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("D1_DEFER_FILE", str(tmp_path / "d1.pkl"))
    dbsync.defer((), {})

    def boom(*a, **k):
        raise RuntimeError("d1 down")
    monkeypatch.setattr(dbsync, "sync", boom)
    assert dbsync.run_deferred() == {"ok": False} and not (tmp_path / "d1.pkl").exists()


def test_without_defer_env_run_py_syncs_inline(monkeypatch):
    monkeypatch.delenv("DEFER_D1", raising=False)
    assert not dbsync.deferred()
