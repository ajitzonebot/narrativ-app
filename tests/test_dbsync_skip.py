"""Change detection in the D1 sync: row-hash manifest, schema skip, R2 skip, concurrent upsert. Everything offline (fake D1 / R2 HTTP)."""
import json
import re
from datetime import date

import pandas as pd
import pytest

from narrativ import dbsync, store
from narrativ.util import digest, prune, write_if_changed


class FakeResp:
    def __init__(self, js=None, status=200):
        self._js, self.status_code, self.ok, self.text = js or {}, status, status < 300, ""

    def json(self):
        return self._js


class FakeCF:
    """Records every D1 statement and R2 put; answers COUNT(*) from the rows it was sent."""

    def __init__(self):
        self.sql, self.puts, self.rows = [], {}, {}
        self.headers = {}
        self.fail_if = None  # substring of a statement that should fail

    def get(self, url, params=None, timeout=None):
        return FakeResp({"result": [{"name": "narrativ", "uuid": "u1"}]})

    def post(self, url, json=None, timeout=None):  # noqa: A002
        s = json["sql"]
        if self.fail_if and self.fail_if in s:
            return FakeResp({"success": False, "errors": ["boom"]}, 400)
        self.sql.append((s, json.get("params")))
        res = []
        m = re.match(r"INSERT INTO (\w+)", s)
        if m:
            n = s.count("),(") + 1 if "?" not in s.split("VALUES", 1)[1][:3] else 1
            self.rows[m[1]] = self.rows.get(m[1], 0) + n
        c = re.match(r"SELECT COUNT\(\*\) AS n FROM (\w+)", s)
        if c:
            res = [{"results": [{"n": self.rows.get(c[1], 0)}], "meta": {"rows_written": 0}}]
        else:
            res = [{"results": [], "meta": {"rows_written": 1}}]
        return FakeResp({"success": True, "result": res})

    def put(self, url, data=None, headers=None, timeout=None):
        self.puts[url.rsplit("/objects/", 1)[1]] = data
        return FakeResp()

    def inserts(self, table):
        return [s for s, _ in self.sql if s.startswith(f"INSERT INTO {table} ")]

    def rows_sent(self, table):
        return sum(s.count("),(") + 1 for s in self.inserts(table))


@pytest.fixture
def cf(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    fake = FakeCF()
    monkeypatch.setattr(store.requests, "Session", lambda: fake)
    monkeypatch.setattr(dbsync, "MANIFEST", tmp_path / "data" / "d1_manifest.json")
    (tmp_path / "data").mkdir()
    return fake


def universe(n=6):
    syms = [f"S{i}.NS" for i in range(n)]
    s0i = pd.DataFrame({"isin": [f"INE{i:03d}" for i in range(n)], "longName": [f"Co {i}" for i in range(n)], "shortName": syms,
                        "sector": "Tech", "industry": "Software", "marketCap": [1e9 * (i + 1) for i in range(n)], "bse_code": None},
                       index=syms)
    picks = [{"s": s, "p": 100.0 + i, "rk": i + 1, "sc": [1] * 7, "t": [1] * 7} for i, s in enumerate(syms)]
    details = {s: {"levels": {"a": i}, "decision": "Hold"} for i, s in enumerate(syms)}
    return s0i, picks, details


def run(day, s0i, picks, details, theses=None, mem=None):
    return dbsync.sync(date.fromisoformat(day), s0i, {}, {}, picks, details, {}, mem or {}, theses or {}, {}, {})


def test_second_identical_day_sends_no_stock_rows_and_skips_schema(cf):
    s0i, picks, details = universe()
    run("2026-11-18", s0i, picks, details, theses={"S0.NS": {"updated": "x", "thesis": "t"}})
    n_schema = sum(1 for s, _ in cf.sql if s.startswith("CREATE"))
    assert n_schema >= 10 and cf.rows_sent("stock_detail") == 6 and cf.rows_sent("company") == 6 and cf.rows_sent("research") == 1
    cf.sql.clear()
    run("2026-11-19", s0i, picks, details, theses={"S0.NS": {"updated": "x", "thesis": "t"}})
    for t in ("stock_detail", "company", "research", "checkpoint"):
        assert cf.inserts(t) == [], t
    assert not any(s.startswith(("CREATE", "PRAGMA", "ALTER")) for s, _ in cf.sql)
    assert cf.rows_sent("snapshot") == 6  # history still gets today's row for every stock
    assert not any("UPDATE company SET in_universe = 0 WHERE last_seen" in s for s, _ in cf.sql)


def test_only_changed_rows_are_sent_and_rank_alone_does_not_count(cf):
    s0i, picks, details = universe()
    run("2026-11-18", s0i, picks, details)
    cf.sql.clear()
    picks2 = [dict(p, rk=p["rk"] + 10) for p in picks]  # every rank moved
    run("2026-11-19", s0i, picks2, details)
    assert cf.inserts("stock_detail") == []
    picks3 = [dict(p) for p in picks2]
    picks3[2]["p"] = 999.0
    d3 = dict(details, **{"S4.NS": {"levels": {"a": 99}}})
    run("2026-11-19", s0i, picks3, d3)
    sent = cf.inserts("stock_detail")
    assert cf.rows_sent("stock_detail") == 2 and "INE002" in sent[0] and "INE004" in sent[0]
    assert "'rk'" not in sent[0] and '"rk":13' in sent[0].replace(" ", "")  # the current rank travels with a written row


def test_missing_manifest_means_full_sync(cf):
    s0i, picks, details = universe()
    run("2026-11-18", s0i, picks, details)
    dbsync.MANIFEST.unlink()
    cf.sql.clear()
    run("2026-11-19", s0i, picks, details)
    assert cf.rows_sent("stock_detail") == 6 and cf.rows_sent("company") == 6
    assert any(s.startswith("CREATE") for s, _ in cf.sql)
    assert any("UPDATE company SET in_universe = 0 WHERE last_seen < ?" in s for s, _ in cf.sql)


def test_corrupt_manifest_means_full_sync(cf):
    s0i, picks, details = universe()
    dbsync.MANIFEST.write_text("{not json")
    run("2026-11-18", s0i, picks, details)
    assert cf.rows_sent("stock_detail") == 6


def test_d1_with_fewer_rows_than_manifest_is_resent(cf):
    s0i, picks, details = universe()
    run("2026-11-18", s0i, picks, details)
    cf.rows.clear()  # database was wiped
    cf.sql.clear()
    run("2026-11-19", s0i, picks, details)
    assert cf.rows_sent("stock_detail") == 6 and cf.rows_sent("company") == 6


def test_weekly_refresh_rewrites_everything(cf):
    s0i, picks, details = universe()
    run("2026-11-10", s0i, picks, details)
    cf.sql.clear()
    run("2026-11-18", s0i, picks, details)  # 8 days later >= REFRESH_DAYS
    assert cf.rows_sent("stock_detail") == 6


def test_company_departure_is_flagged_by_name_without_full_table_update(cf):
    s0i, picks, details = universe()
    run("2026-11-18", s0i, picks, details)
    cf.sql.clear()
    s1, p1, d1 = universe(5)  # S5 / INE005 left the universe
    run("2026-11-19", s1, p1, d1)
    ups = [(s, p) for s, p in cf.sql if s.startswith("UPDATE company SET in_universe = 0 WHERE isin IN")]
    assert len(ups) == 1 and ups[0][1] == ["INE005"]
    assert cf.inserts("company") == []


def test_manifest_records_only_accepted_rows(cf, monkeypatch):
    monkeypatch.setattr(store, "WORKERS", 1)
    s0i, picks, details = universe()
    cf.fail_if = "INSERT INTO stock_detail"
    run("2026-11-18", s0i, picks, details)
    man = json.loads(dbsync.MANIFEST.read_text())
    assert man["tables"].get("stock_detail", {"h": {}})["h"] == {}  # nothing accepted: retried tomorrow
    cf.fail_if = None
    cf.sql.clear()
    run("2026-11-19", s0i, picks, details)
    assert cf.rows_sent("stock_detail") == 6


def test_r2_objects_skipped_when_unchanged(cf):
    s0i, picks, details = universe()
    sc = dbsync.Path("data/source_cache")
    sc.mkdir(parents=True)
    (sc / "delivery.json").write_text('{"a":1}')
    (dbsync.Path("data") / "analyst.json").write_text('{"b":1}')
    run("2026-11-18", s0i, picks, details)
    assert {"nse/delivery.json.gz", "git/analyst.json.gz"} <= set(cf.puts)
    cf.puts.clear()
    run("2026-11-19", s0i, picks, details)
    assert "nse/delivery.json.gz" not in cf.puts and "git/analyst.json.gz" not in cf.puts
    (sc / "delivery.json").write_text('{"a":2}')
    run("2026-11-19", s0i, picks, details)
    assert set(cf.puts) == {"nse/delivery.json.gz"}


def test_manifest_file_is_deterministic(cf):
    s0i, picks, details = universe()
    run("2026-11-18", s0i, picks, details)
    a = dbsync.MANIFEST.read_bytes()
    run("2026-11-18", s0i, picks, details)
    assert dbsync.MANIFEST.read_bytes() == a


# ---------- Store.upsert ----------
def mkstore(cf):
    st = store.Store()
    assert st.db == "u1"
    return st


@pytest.mark.parametrize("workers", [1, 4])
def test_upsert_sends_every_row_once_and_reports_indexes(cf, monkeypatch, workers):
    monkeypatch.setattr(store, "WORKERS", workers)
    monkeypatch.setattr(store, "MAX_SQL", 400)  # force many statements
    st = mkstore(cf)
    rows = [[f"k{i}", "x" * 20] for i in range(100)]
    seen = []
    n = st.upsert("t", ["id", "v"], rows, ["id"], on_sent=seen.extend)
    assert n == 100 and sorted(seen) == list(range(100))
    assert cf.rows_sent("t") == 100 and len(cf.inserts("t")) >= 5
    assert all(len(s) <= 400 for s in cf.inserts("t"))


def test_upsert_budget_stops_with_concurrency(cf, monkeypatch):
    monkeypatch.setattr(store, "WORKERS", 3)
    monkeypatch.setattr(store, "MAX_SQL", 300)
    st = mkstore(cf)
    st.budget = 20
    rows = [[f"k{i}", "x" * 20] for i in range(500)]
    seen = []
    n = st.upsert("t", ["id", "v"], rows, ["id"], on_sent=seen.extend)
    assert 0 < n < 100 and n == len(seen)  # stopped near the budget, nowhere near all 500
    assert st.upsert("t", ["id", "v"], rows[:3], ["id"], force=True) == 3


def test_upsert_failure_reports_what_was_accepted(cf, monkeypatch):
    monkeypatch.setattr(store, "WORKERS", 1)
    monkeypatch.setattr(store, "MAX_SQL", 300)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    st = mkstore(cf)
    rows = [[f"k{i:03d}", "x" * 20] for i in range(60)]
    seen = []
    cf.fail_if = "k030"
    with pytest.raises(RuntimeError):
        st.upsert("t", ["id", "v"], rows, ["id"], on_sent=seen.extend)
    assert seen and max(seen) < 30 and sorted(seen) == list(range(len(seen)))


def test_schema_fingerprint_ignores_comments(tmp_path, monkeypatch):
    f = tmp_path / "s.sql"
    f.write_text("CREATE TABLE a (x TEXT); -- c\n")
    monkeypatch.setattr(store, "SCHEMA", f)
    h1 = store.Store.schema_fingerprint()
    f.write_text("-- header\nCREATE TABLE a (x TEXT); -- other comment\n")
    assert store.Store.schema_fingerprint() == h1
    f.write_text("CREATE TABLE a (x TEXT, y TEXT);")
    assert store.Store.schema_fingerprint() != h1


# ---------- util ----------
def test_write_if_changed_keeps_unchanged_files(tmp_path):
    p = tmp_path / "d" / "a.json"
    assert write_if_changed(p, '{"a":1}') is True
    m = p.stat().st_mtime_ns
    assert write_if_changed(p, '{"a":1}') is False and p.stat().st_mtime_ns == m
    assert write_if_changed(p, '{"a":2}') is True and p.read_text() == '{"a":2}'


def test_prune_removes_only_stale_files(tmp_path):
    for n in ("a.json", "b.json", "c.json"):
        (tmp_path / n).write_text("{}")
    assert prune(tmp_path, {"a.json", "c.json"}) == 1
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a.json", "c.json"]


def test_digest_is_key_order_independent():
    assert digest({"a": 1, "b": [1, 2]}) == digest({"b": [1, 2], "a": 1}) and digest({"a": 1}) != digest({"a": 2})
