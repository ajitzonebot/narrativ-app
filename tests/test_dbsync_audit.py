"""D1 sync fixes from the Cloudflare audit (26 Nov 2026): starved events and quarters, partial company sends, bound-parameter
limits, catch-up of verdict_log, removed forward items, literal and statement-size rules. Offline (fake D1 / R2 HTTP)."""
import json
from datetime import date

import numpy as np
import pytest

from narrativ import dbsync, store
from test_dbsync_skip import FakeCF, universe


@pytest.fixture
def d1(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    fake = FakeCF()
    monkeypatch.setattr(store.requests, "Session", lambda: fake)
    monkeypatch.setattr(dbsync, "MANIFEST", tmp_path / "data" / "d1_manifest.json")
    monkeypatch.setattr(store, "WORKERS", 1)
    (tmp_path / "data").mkdir()
    return fake


def sync(day, s0i, picks, details, **kw):
    return dbsync.sync(date.fromisoformat(day), s0i, {}, {}, picks, details, kw.get("fins") or {}, kw.get("mem") or {},
                       kw.get("theses") or {}, {}, kw.get("ann_st") or {})


def manifest():
    return json.loads(dbsync.MANIFEST.read_text())


# ---------- events of a starved day are sent by a later run ----------
def test_events_of_a_failed_run_are_sent_later(d1):
    s0i, picks, details = universe()
    a = {"rows": {"S0.NS": [["2026-11-20", "Outcome", "Results", "u/1", "event", None]]}}
    sync("2026-11-20", s0i, picks, details, ann_st=a)
    assert manifest()["done"]["event_synced"] == "2026-11-20"
    d1.fail_if = "INSERT INTO event"  # 21 Nov: the event write fails (or the budget is gone)
    a["rows"]["S1.NS"] = [["2026-11-21", "Order", "Order win", "u/2", "event", None]]
    sync("2026-11-21", s0i, picks, details, ann_st=a)
    assert manifest()["done"]["event_synced"] == "2026-11-20"  # not marked synced
    d1.fail_if = None
    d1.sql.clear()
    # 26 Nov: 21 Nov is older than the last 3 days, still sent because it was never synced
    sync("2026-11-26", s0i, picks, details, ann_st=a)
    sent = " ".join(d1.inserts("event"))
    assert "u/2" in sent
    assert manifest()["done"]["event_synced"] == "2026-11-26"


def test_backfills_run_after_events_and_quarters(d1):
    order = []
    s0i, picks, details = universe()
    orig = store.Store.upsert

    def spy(self, table, *a, **k):
        order.append(table)
        return orig(self, table, *a, **k)
    store.Store.upsert = spy
    try:
        fins = {"S0.NS": {"checked": "2026-11-24", "quarters": {"2026-09-30": {"Consolidated": {"q": {"rev": 1e9, "exp": 8e8}, "bs": {}}}}}}
        a = {"rows": {"S0.NS": [["2026-11-24", "Outcome", "Results", "u/1", "event", None], ["2026-10-01", "Outcome", "Old", "u/0", "event", None]]}}
        sync("2026-11-24", s0i, picks, details, ann_st=a, fins=fins)
    finally:
        store.Store.upsert = orig
    ev = [i for i, t in enumerate(order) if t == "event"]
    assert order.index("quarter") < ev[-1]  # the older-history event backfill is the last event write
    assert ev[0] < order.index("quarter")


# ---------- company ----------
def test_partial_company_send_does_not_clear_in_universe(d1, monkeypatch):
    s0i, picks, details = universe()
    monkeypatch.setattr(store, "WRITE_BUDGET", 14)  # snapshot + detail use most of it: company is cut short
    sync("2026-11-24", s0i, picks, details)
    assert not any(s.startswith("UPDATE company SET in_universe = 0 WHERE last_seen") for s, _ in d1.sql)


def test_full_company_send_clears_departures(d1):
    s0i, picks, details = universe()
    sync("2026-11-24", s0i, picks, details)
    assert any(s.startswith("UPDATE company SET in_universe = 0 WHERE last_seen") for s, _ in d1.sql)


def test_departures_are_bound_at_most_90_a_statement_and_retried(d1):
    s0i, picks, details = universe(200)
    sync("2026-11-24", s0i, picks, details)
    d1.sql.clear()
    s1, p1, x1 = universe(5)  # 195 companies left
    d1.fail_if = "UPDATE company SET in_universe = 0 WHERE isin IN"
    sync("2026-11-25", s1, p1, x1)
    left = set(manifest()["tables"]["company"]["h"]) - {f"INE{i:03d}" for i in range(5)}
    assert len(left) == 195  # failed: kept in the manifest, so the next run flags them again
    d1.fail_if = None
    sync("2026-11-26", s1, p1, x1)
    ups = [p for s, p in d1.sql if s.startswith("UPDATE company SET in_universe = 0 WHERE isin IN")]
    assert ups and all(len(p) <= dbsync.IN_LIST for p in ups) and sum(len(p) for p in ups) == 195


# ---------- verdict_log ----------
def test_verdict_log_catches_up_and_keeps_old_tiers(d1):
    s0i, picks, details = universe()
    mem = {"S0.NS": {"verdicts": [{"d": "2026-11-20", "v": "Watch", "from": None}], "tiers": [1] * 7}}
    sync("2026-11-20", s0i, picks, details, mem=mem)  # first sync: full send
    d1.sql.clear()
    d1.rows["verdict_log"] = 500  # past the "new table" threshold
    mem["S0.NS"]["verdicts"].append({"d": "2026-11-21", "v": "Buy", "from": "Watch"})
    d1.fail_if = "INSERT INTO verdict_log"
    sync("2026-11-21", s0i, picks, details, mem=mem)
    d1.fail_if = None
    d1.sql.clear()
    mem["S0.NS"]["tiers"] = [2] * 7
    sync("2026-11-22", s0i, picks, details, mem=mem)
    sql = " ".join(d1.inserts("verdict_log"))
    assert "'2026-11-21','Watch','Buy'" in sql  # the failed day is sent
    hist = [s for s in d1.inserts("verdict_log") if "'2026-11-21'" in s]
    assert hist and "tiers=excluded.tiers" not in hist[0]  # an older row keeps its tiers
    assert "[2,2,2,2,2,2,2]" not in sql  # today's tiers are not written onto older rows


# ---------- forward items that left the source ----------
def test_removed_forward_item_is_marked_removed(d1):
    s0i, picks, details = universe()
    th = {"S0.NS": {"drivers": [{"text": "Capacity 2x by FY27", "due": "2027-03-31", "kind": "capacity"},
                                {"text": "Margin 20%", "due": "2027-03-31", "kind": "margin"}]}}
    sync("2026-11-24", s0i, picks, details, theses=th)
    d1.sql.clear()
    th["S0.NS"]["drivers"].pop()
    sync("2026-11-25", s0i, picks, details, theses=th)
    ups = [(s, p) for s, p in d1.sql if s.startswith("UPDATE forward_item SET status = 'removed'")]
    assert len(ups) == 1 and len(ups[0][1]) == 1


# ---------- literals and statement size ----------
def test_literals_for_non_finite_and_numpy():
    assert store._lit(float("inf")) == "NULL" and store._lit(float("-inf")) == "NULL" and store._lit(float("nan")) == "NULL"
    assert store._lit(np.int64(500325)) == "500325"
    assert store._lit(np.float64(1.5)) == "1.5"
    assert store._lit(np.bool_(True)) == "1"
    assert store._lit(np.float64("inf")) == "NULL"


def test_statements_are_sized_in_bytes(d1, monkeypatch):
    monkeypatch.setattr(store, "MAX_SQL", 2_000)
    st = store.Store()
    rows = [[f"k{i}", "₹" * 100] for i in range(40)]  # 100 characters, 300 bytes each
    st.upsert("t", ["k", "v"], rows, ["k"])
    stmts = d1.inserts("t")
    assert len(stmts) > 1 and all(len(s.encode()) <= 2_000 for s in stmts)
    assert sum(s.count("),(") + 1 for s in stmts) == 40
