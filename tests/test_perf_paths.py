"""Speed-ups that must not change results (cost audit 26 Nov 2026): AlphaStreet prefetch, story usage counting."""
import json
import threading
import time
from datetime import date

from narrativ import alphastreet as AS
from narrativ import quota as Q


class _Resp:
    def __init__(self, j, code=200):
        self._j, self.status_code = j, code

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _fake(calls_log, lock):
    class S:
        def get(self, url, timeout=30):
            with lock:
                calls_log.append((time.time(), url))
            time.sleep(0.05)
            if "/transcripts?ticker=" in url:
                t = url.rsplit("=", 1)[1]
                if t == "NONE":
                    return _Resp(None, 404)
                return _Resp({"items": [{"id": f"id-{t}", "fiscal_period": "Q2", "fiscal_year": 2027, "event_type": "earnings_conference",
                                         "event_utc_datetime": "2026-11-10T10:00:00", "transcript_status": "FINAL"}]})
            if "/alphacall/" in url:
                cid = url.rsplit("/", 1)[1]
                if cid.endswith("B"):
                    return _Resp({})  # no brief for this call
                return _Resp({"headline": f"h {cid}", "metrics": [["Revenue", "INR10 crores"]], "bullets": ["x"]})
            return _Resp(None, 404)
    return S()


def _setup(tmp_path, monkeypatch, pause=0.02):
    log, lock = [], threading.Lock()
    monkeypatch.setattr(AS, "CACHE", tmp_path / "as")
    monkeypatch.setattr(AS, "CARDS", tmp_path / "cards.json")
    monkeypatch.setattr(AS, "PAUSE", pause)
    monkeypatch.setattr(AS, "_session", lambda: _fake(log, lock))
    monkeypatch.setattr(AS, "_brief_run", {})
    AS._last[0] = 0.0
    return log


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def test_prefetch_fills_the_same_caches_as_the_sequential_path(tmp_path, monkeypatch):
    today = date(2026, 11, 26)
    tick = ["A.NS", "B.NS", "C.NS", "NONE.NS", "A.NS"]
    _setup(tmp_path / "seq", monkeypatch)
    seq = [AS.calls(t, today) for t in tick]
    seq_files = _snapshot(tmp_path / "seq")
    _setup(tmp_path / "par", monkeypatch)
    AS.prefetch(tick, today)
    par = [AS.calls(t, today) for t in tick]
    assert par == seq
    assert _snapshot(tmp_path / "par") == seq_files


def test_prefetch_keeps_request_starts_apart(tmp_path, monkeypatch):
    log = _setup(tmp_path, monkeypatch, pause=0.03)
    AS.prefetch([f"S{i}.NS" for i in range(12)], date(2026, 11, 26))
    starts = sorted(t for t, _ in log)
    assert len(starts) == 12
    assert min(b - a for a, b in zip(starts, starts[1:])) >= 0.03 - 0.005


def test_cards_same_with_parallel_briefs_and_a_missing_brief_asked_once(tmp_path, monkeypatch):
    today = date(2026, 11, 26)
    log = _setup(tmp_path, monkeypatch)
    st = AS.refresh_cards(["A.NS", "B.NS"], ["C.NS"], today)
    assert set(st) == {"A.NS", "C.NS"} and st["A.NS"]["headline"] == "h id-A"  # B's call has no brief: no card
    assert sum(1 for _, u in log if u.endswith("/alphacall/id-B")) == 1
    assert json.loads((tmp_path / "cards.json").read_text()) == st


def test_story_calls_counted_without_holding_anything_back(tmp_path):
    q = Q.Quota(tmp_path / "usage.json")
    q.count("gemini-3.1-flash-lite", 1000)
    q.count("gemini-3.1-flash-lite", 0, refused=True)
    rec = q.day()["gemini-3.1-flash-lite"]
    assert rec["calls"] == 1 and rec["refused"] == 1 and rec["tokens"] == 1000 and rec["story"] == 2
    assert json.loads((tmp_path / "usage.json").read_text())
