"""Change detection in the D1 sync: row-hash manifest, schema skip, R2 skip, concurrent upsert. Everything offline (fake D1 / R2 HTTP)."""
import json
import re
from datetime import date

import pandas as pd
import pytest

from narrativ import dbsync, store
from narrativ.util import digest, prune, write_if_changed


class FakeResp:
    def __init__(self, js=None, status=200, content=b""):
        self._js, self.status_code, self.ok, self.text, self.content = js or {}, status, status < 300, "", content

    def json(self):
        return self._js


class FakeCF:
    """Records every D1 statement and R2 put; answers COUNT(*) from the rows it was sent. `bucket` is the R2 content
    (get / list / delete read it); `puts` records this run's uploads."""

    def __init__(self):
        self.sql, self.puts, self.rows, self.bucket, self.deleted = [], {}, {}, {}, []
        self.headers = {}
        self.fail_if = None  # substring of a statement that should fail
        self.usage_today = None  # JSON usage the run_log row of today holds (an earlier run the same day)
        self.lists = 0

    def get(self, url, params=None, timeout=None):
        if "/r2/buckets/" in url:
            if url.endswith("/objects"):
                self.lists += 1
                pre = (params or {}).get("prefix", "")
                return FakeResp({"success": True, "result": [{"key": k} for k in sorted(self.bucket) if k.startswith(pre)],
                                 "result_info": {"is_truncated": False}})
            k = url.rsplit("/objects/", 1)[1]
            return FakeResp(content=self.bucket[k]) if k in self.bucket else FakeResp(status=404)
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
        elif s.startswith("SELECT usage FROM run_log") and self.usage_today:
            res = [{"results": [{"usage": self.usage_today}], "meta": {"rows_written": 0}}]
        else:
            res = [{"results": [], "meta": {"rows_written": 1}}]
        return FakeResp({"success": True, "result": res})

    def put(self, url, data=None, headers=None, timeout=None):
        k = url.rsplit("/objects/", 1)[1]
        self.puts[k] = self.bucket[k] = data
        return FakeResp()

    def delete(self, url, timeout=None):
        k = url.rsplit("/objects/", 1)[1]
        self.deleted.append(k)
        return FakeResp() if self.bucket.pop(k, None) is not None else FakeResp(status=404)

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


def run(day, s0i, picks, details, theses=None, mem=None, ann_st=None, fins=None):
    return dbsync.sync(date.fromisoformat(day), s0i, {}, {}, picks, details, fins or {}, mem or {}, theses or {}, {}, ann_st or {})


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


def test_forward_items_and_narrativ_sheets_reach_d1(cf, tmp_path):
    s0i, picks, details = universe()
    (tmp_path / "data" / "reader").mkdir()
    (tmp_path / "data" / "reader" / "store.json").write_text(json.dumps({
        "u1": {"s": "S1.NS", "kind": "transcript", "date": "2026-11-10",
               "lite": {"model": "lite-x", "rows": [{"kind": "guidance", "text": "Loan book Rs 2 lakh crore", "value": 2.0, "unit": "lakh cr", "due": "2027-03-31"}]}}}))
    (tmp_path / "data" / "story.json").write_text(json.dumps({"stocks": {"S0.NS": {"date": "2026-11-25", "what": "A maker", "money": "Sells",
                                                                                   "plans": ["Grow"], "model": "m"}}, "held": {}}))
    th = {"S0.NS": {"updated": "x", "drivers": [{"kind": "order", "text": "Plant starts", "due": "2027-01-31", "due_verified": True, "quote": "q", "source": "u"}],
                    "promises": [{"id": "p1", "promise": "Double-digit growth", "due": "2027-03-31", "status": "raised"}]}}
    run("2026-11-25", s0i, picks, details, theses=th)
    assert cf.rows_sent("forward_item") == 3 and cf.rows_sent("narrativ_sheet") == 1
    cf.sql.clear()
    run("2026-11-26", s0i, picks, details, theses=th)
    assert cf.inserts("forward_item") == [] and cf.inserts("narrativ_sheet") == []  # unchanged: nothing resent


# ---------- snapshot: one row per stock per date, reruns skip unchanged rows ----------
def test_snapshot_rerun_same_day_sends_only_changed_rows(cf):
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    assert cf.rows_sent("snapshot") == 6
    cf.sql.clear()
    run("2026-11-24", s0i, picks, details)  # rerun, nothing changed
    assert cf.inserts("snapshot") == []
    picks2 = [dict(p) for p in picks]
    picks2[3]["vd"] = "Buy"
    cf.sql.clear()
    run("2026-11-24", s0i, picks2, details)
    assert cf.rows_sent("snapshot") == 1 and "INE003" in cf.inserts("snapshot")[0]
    cf.sql.clear()
    run("2026-11-25", s0i, picks2, details)  # a new trading date: every stock gets its row
    assert cf.rows_sent("snapshot") == 6 and "'2026-11-25'" in cf.inserts("snapshot")[0]


def test_snapshot_drift_guard_probes_keys_instead_of_counting_the_table(cf):
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    cf.sql.clear()
    run("2026-11-24", s0i, picks, details)
    counts = [(s, p) for s, p in cf.sql if s.startswith("SELECT COUNT(*) AS n FROM snapshot")]
    assert counts and all(" WHERE (isin = ? AND date = ?)" in s for s, _ in counts)
    assert counts[0][1][:2] == ["INE000", "2026-11-24"]
    cf.rows["snapshot"] = 0  # rows gone from D1: today's rows are sent again
    cf.sql.clear()
    run("2026-11-24", s0i, picks, details)
    assert cf.rows_sent("snapshot") == 6


def test_snapshot_retention_runs_once_a_day(cf):
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    run("2026-11-24", s0i, picks, details)
    assert sum(1 for s, _ in cf.sql if s.startswith("DELETE FROM snapshot")) == 1
    run("2026-11-25", s0i, picks, details)
    assert sum(1 for s, _ in cf.sql if s.startswith("DELETE FROM snapshot")) == 2


# ---------- events: recent window hash-skipped, backfill on the first sync of the day only ----------
def ann(rows_by_sym):
    return {"rows": rows_by_sym}


def test_recent_events_rerun_sends_only_new_and_no_backfill(cf):
    s0i, picks, details = universe()
    a = ann({"S0.NS": [["2026-11-24", "Outcome", "Results", "u/1", "event", None], ["2026-11-01", "Outcome", "Old", "u/0", "event", None]],
             "S1.NS": [["2026-11-23", "Order", "Order win", "u/2", "event", None]]})
    run("2026-11-24", s0i, picks, details, ann_st=a)
    assert cf.rows_sent("event") == 3  # 2 recent + the older one as backfill
    assert any(s.startswith("SELECT MIN(date) AS m FROM event") for s, _ in cf.sql)
    cf.sql.clear()
    cf.usage_today = json.dumps({"d1_rows_written_today": 500})  # a rerun the same day
    a["rows"]["S2.NS"] = [["2026-11-24", "Order", "New order", "u/3", "event", None]]
    run("2026-11-24", s0i, picks, details, ann_st=a)
    assert cf.rows_sent("event") == 1 and "u/3" in cf.inserts("event")[0]
    assert not any(s.startswith("SELECT MIN(date) AS m FROM event") for s, _ in cf.sql)
    man = json.loads(dbsync.MANIFEST.read_text())
    assert all(len(k) == 12 for k in man["tables"]["event"]["h"])  # long ids stored as short hashes
    assert man["tables"]["event"]["p"] == [["u/3"]]  # drift probe: rows D1 accepted most recently


def test_quarter_rerun_skips_unchanged_rows(cf):
    s0i, picks, details = universe()
    fins = {"S0.NS": {"checked": "2026-11-24", "quarters": {"2026-09-30": {"Consolidated": {"q": {"rev": 1e9, "exp": 8e8, "pat": 1e8}, "bs": {}}}}}}
    run("2026-11-24", s0i, picks, details, fins=fins)
    assert cf.rows_sent("quarter") == 1
    cf.sql.clear()
    run("2026-11-24", s0i, picks, details, fins=fins)
    assert cf.inserts("quarter") == []


# ---------- verdict_log.priority ----------
def test_verdict_log_priority_from_memory_snapshots(cf):
    s0i, picks, details = universe()
    picks[0]["pr"] = 7.5
    mem = {"S0.NS": {"verdicts": [{"d": "2026-11-20", "v": "Watch", "from": None}, {"d": "2026-11-24", "v": "Buy", "from": "Watch"}],
                     "snapshots": [{"d": "2026-11-20", "pr": 3.25}], "tiers": [1] * 7},
           "S1.NS": {"verdicts": [{"d": "2025-01-02", "v": "Avoid", "from": None}], "snapshots": []}}
    run("2026-11-24", s0i, picks, details, mem=mem)
    sql = " ".join(cf.inserts("verdict_log"))
    assert "('INE000','2026-11-20',NULL,'Watch',3.25," in sql and "('INE000','2026-11-24','Watch','Buy',7.5," in sql
    assert "('INE001','2025-01-02',NULL,'Avoid',NULL," in sql  # no snapshot left for that day
    assert json.loads(dbsync.MANIFEST.read_text())["done"]["verdict_priority_backfill"] == "2026-11-24"


# ---------- document table ----------
def docs_fixture(tmp_path):
    import hashlib
    sha = lambda u: hashlib.sha1(u.encode()).hexdigest()  # noqa: E731
    (tmp_path / "data" / "reader").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "docling").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "data" / "packs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "source_cache" / "doctext").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "reader" / "docs.json").write_text(json.dumps({"docs": [
        {"s": "S0.NS", "kind": "transcript", "date": "2026-11-02", "url": "https://x/a.pdf"},
        {"s": "S1.NS", "kind": "presentation", "date": "2026-11-03", "url": "https://x/b.pdf"},
        {"s": "S2.NS", "kind": "transcript", "date": "2026-11-04", "url": "https://x/c.pdf"},
        {"s": "ZZ.NS", "kind": "transcript", "date": "2026-11-05", "url": "https://x/d.pdf"}]}))
    (tmp_path / "data" / "reader" / "store.json").write_text(json.dumps({
        "https://x/a.pdf": {"s": "S0.NS", "kind": "transcript", "date": "2026-11-02", "lite": {"model": "m", "rows": [], "dropped": []}},
        "https://x/c.pdf": {"s": "S2.NS", "kind": "transcript", "date": "2026-11-04", "lite": {"model": "m", "error": "no text layer", "fails": 1}}}))
    (tmp_path / "data" / "docling" / "index.json").write_text(json.dumps({"https://x/b.pdf": {"s": "S1.NS", "kind": "presentation", "ok": True}}))
    (tmp_path / "data" / "docling" / f"{sha('https://x/b.pdf')}.md").write_text("<!-- source: https://x/b.pdf -->\ntext")
    (tmp_path / "data" / "source_cache" / "doctext" / f"{sha('https://x/a.pdf')}.txt").write_text("t" * 300)
    (tmp_path / "data" / "source_cache" / "doctext" / f"{sha('https://x/a.pdf')}.pages").write_text("12")
    (tmp_path / "docs" / "data" / "packs" / "S3.json").write_text(json.dumps({"symbol": "S3.NS", "documents": [
        {"kind": "results", "date": "2026-11-06", "url": "https://x/e.pdf", "has_text": True, "pages": 15}]}))
    return sha


def test_document_rows_from_reader_docling_and_packs(cf, tmp_path):
    sha = docs_fixture(tmp_path)
    s0i, _, _ = universe()
    rows = {r[0]: r for r in dbsync.document_rows({s: s0i.loc[s, "isin"] for s in s0i.index})}
    assert rows["https://x/a.pdf"] == ["https://x/a.pdf", "INE000", "2026-11-02", "transcript", 12, 1, None, "read"]
    assert rows["https://x/b.pdf"] == ["https://x/b.pdf", "INE001", "2026-11-03", "presentation", None, 1,
                                       f"data/docling/{sha('https://x/b.pdf')}.md", "converted"]
    assert rows["https://x/c.pdf"][5:] == [0, None, "failed"]
    assert rows["https://x/d.pdf"] == ["https://x/d.pdf", None, "2026-11-05", "transcript", None, None, None, "listed"]
    assert rows["https://x/e.pdf"][1:] == ["INE003", "2026-11-06", "results", 15, 1, None, "listed"]


def test_document_table_written_once_then_only_changes(cf, tmp_path):
    docs_fixture(tmp_path)
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    assert cf.rows_sent("document") == 5
    cf.sql.clear()
    run("2026-11-25", s0i, picks, details)
    assert cf.inserts("document") == []
    st_ = json.loads((tmp_path / "data" / "reader" / "store.json").read_text())
    st_["https://x/c.pdf"]["flash"] = {"model": "f", "rows": [{"text": "x"}], "dropped": []}
    (tmp_path / "data" / "reader" / "store.json").write_text(json.dumps(st_))
    run("2026-11-25", s0i, picks, details)
    assert cf.rows_sent("document") == 1 and "'read'" in cf.inserts("document")[0]


# ---------- schema: unused indexes dropped ----------
def test_schema_drops_unused_indexes_and_keeps_history_ones():
    stmts = store.Store._schema_statements()
    joined = "\n".join(stmts)
    assert "CREATE INDEX IF NOT EXISTS snapshot_date" not in joined and "DROP INDEX IF EXISTS snapshot_date" in joined
    assert "CREATE INDEX IF NOT EXISTS event_sev_date" not in joined and "DROP INDEX IF EXISTS event_sev_date" in joined
    assert "CREATE INDEX IF NOT EXISTS event_isin_date ON event(isin, date)" in joined


# ---------- R2: durable copies of the Actions-cache stores ----------
def cache_fixture(tmp_path):
    sc = tmp_path / "data" / "source_cache"
    (sc / "alphastreet" / "transcripts").mkdir(parents=True)
    (sc / "alphastreet" / "briefs").mkdir(parents=True)
    (tmp_path / "data" / "news_cache").mkdir(parents=True)
    import gzip
    (tmp_path / "data" / "news_cache" / "news.json.gz").write_bytes(gzip.compress(b'{"items":{}}', mtime=0))
    (sc / "ratings_sdd.json.gz").write_bytes(gzip.compress(b'{"rows":{}}', mtime=0))
    (sc / "ibbi.json.gz").write_bytes(gzip.compress(b'{"n":[]}', mtime=0))
    (sc / "bse_list.json").write_text('{"date":"2026-11-20","rows":{}}')
    (sc / "alphastreet" / "transcripts" / "id1.txt").write_text("call text")
    (sc / "alphastreet" / "briefs" / "id1.json").write_text('{"headline":"h"}')
    return sc


def test_actions_cache_stores_get_an_r2_copy_only_when_changed(cf, tmp_path):
    sc = cache_fixture(tmp_path)
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    want = {"news/news.json.gz", "nse/ratings_sdd.json.gz", "ibbi/ibbi.json.gz", "bse/bse_list.json.gz",
            "alphastreet/transcripts.json.gz", "alphastreet/briefs.json.gz"}
    assert want <= set(cf.puts)
    cf.puts.clear()
    run("2026-11-25", s0i, picks, details)
    assert not (want & set(cf.puts))
    (sc / "alphastreet" / "transcripts" / "id2.txt").write_text("second call")
    run("2026-11-25", s0i, picks, details)
    assert want & set(cf.puts) == {"alphastreet/transcripts.json.gz"}


def test_restore_caches_brings_back_every_store_from_r2(cf, tmp_path):
    import shutil
    sc = cache_fixture(tmp_path)
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / "data").rglob("*")
              if p.is_file() and ("source_cache" in p.parts or "news_cache" in p.parts)}
    shutil.rmtree(sc)
    shutil.rmtree(tmp_path / "data" / "news_cache")
    dbsync.restore_caches()
    after = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / "data").rglob("*")
             if p.is_file() and ("source_cache" in p.parts or "news_cache" in p.parts)}
    assert after == before


def test_restore_only_one_store(cf, tmp_path):
    sc = cache_fixture(tmp_path)
    s0i, picks, details = universe()
    run("2026-11-24", s0i, picks, details)
    (tmp_path / "data" / "news_cache" / "news.json.gz").unlink()
    (sc / "ibbi.json.gz").unlink()
    dbsync.restore_caches(only={"data/news_cache/news.json.gz"})
    assert (tmp_path / "data" / "news_cache" / "news.json.gz").exists() and not (sc / "ibbi.json.gz").exists()


# ---------- R2 retention ----------
def test_r2_prune_keeps_90_days_of_surveillance_and_12_weekly_backups(cf):
    from datetime import timedelta
    today = date(2026, 11, 24)
    for n in range(0, 120, 10):
        cf.bucket[f"nse/surveillance-{today - timedelta(days=n)}.json.gz"] = b"x"
    for n in range(15):
        cf.bucket[f"backups/memory-{today - timedelta(weeks=n)}.json.gz"] = b"x"
    cf.bucket["nse/delivery.json.gz"] = b"x"
    out, ok = dbsync.prune_r2(mkstore(cf), today)
    assert ok and out == {"surveillance": 2, "backups": 3}
    sv = sorted(k for k in cf.bucket if k.startswith("nse/surveillance-"))
    assert sv[0] == f"nse/surveillance-{today - timedelta(days=90)}.json.gz" and len(sv) == 10
    bk = sorted(k for k in cf.bucket if k.startswith("backups/"))
    assert len(bk) == 12 and bk[-1] == f"backups/memory-{today}.json.gz"
    assert "nse/delivery.json.gz" in cf.bucket


def test_r2_prune_runs_weekly_from_sync(cf):
    s0i, picks, details = universe()
    cf.bucket["nse/surveillance-2026-01-01.json.gz"] = b"x"
    run("2026-11-24", s0i, picks, details)
    assert "nse/surveillance-2026-01-01.json.gz" not in cf.bucket and cf.lists == 2
    cf.bucket["nse/surveillance-2026-01-02.json.gz"] = b"x"
    run("2026-11-25", s0i, picks, details)
    assert cf.lists == 2 and "nse/surveillance-2026-01-02.json.gz" in cf.bucket  # not due again for a week
    run("2026-12-01", s0i, picks, details)
    assert "nse/surveillance-2026-01-02.json.gz" not in cf.bucket


def test_weekly_memory_backup_not_reuploaded_on_a_rerun(cf):
    s0i, picks, details = universe()
    mem = {"S0.NS": {"verdicts": []}}
    run("2026-11-23", s0i, picks, details, mem=mem)  # a Monday
    assert "backups/memory-2026-11-23.json.gz" in cf.puts
    cf.puts.clear()
    run("2026-11-23", s0i, picks, details, mem=mem)
    assert "backups/memory-2026-11-23.json.gz" not in cf.puts
