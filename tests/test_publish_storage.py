"""Stage 1 storage safety (owner, 26 Nov 2026): publish gate, R2 archive, nightly publish audit."""
import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from narrativ import archive as AR  # noqa: E402
from narrativ import audit_publish as AP  # noqa: E402

GATE = ROOT / "scripts" / "publish_gate.py"


def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, check=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    d = tmp_path / "docs" / "data"
    (d / "fin").mkdir(parents=True)
    (d / "charts").mkdir()
    (d / "picks.json").write_text(json.dumps({"date": "2026-11-26", "picks": [{"s": "A.NS"}]}))
    for i in range(20):
        (d / "fin" / f"S{i}.json").write_text("{}")
        (d / "charts" / f"S{i}.json").write_text("{}")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _gate(repo, *args):
    return subprocess.run([sys.executable, str(GATE), *args], cwd=repo, capture_output=True, text=True)


def test_gate_passes_a_normal_build(repo):
    (repo / "docs/data/fin/S1.json").write_text('{"x": 1}')
    _git(repo, "add", "-A")
    r = _gate(repo)
    assert r.returncode == 0, r.stdout


def test_gate_refuses_lost_files(repo):
    for i in range(5):  # 25% of fin/ gone
        (repo / f"docs/data/fin/S{i}.json").unlink()
    _git(repo, "add", "-A")
    r = _gate(repo)
    assert r.returncode == 1 and "docs/data/fin/" in r.stdout


def test_gate_refuses_broken_json_and_empty_picks(repo):
    (repo / "docs/data/charts/S3.json").write_text("{broken")
    (repo / "docs/data/picks.json").write_text(json.dumps({"date": "2026-11-26", "picks": []}))
    _git(repo, "add", "-A")
    r = _gate(repo)
    assert r.returncode == 1 and "S3.json" in r.stdout and "no picks" in r.stdout


def test_gate_refuses_older_picks_date_and_checks_against_a_base(repo):
    (repo / "docs/data/picks.json").write_text(json.dumps({"date": "2026-11-25", "picks": [{"s": "A.NS"}]}))
    _git(repo, "add", "-A")
    r = _gate(repo)
    assert r.returncode == 1 and "older than the live" in r.stdout
    _git(repo, "commit", "-qm", "older")
    assert _gate(repo, "--base", "HEAD").returncode == 0  # same as HEAD now
    assert _gate(repo, "--base", "HEAD~1").returncode == 1  # against the earlier base it still goes back


def test_gate_checks_data_dir_json(repo):
    (repo / "data").mkdir()
    (repo / "data/x.json").write_text("{not json")
    _git(repo, "add", "-A")
    r = _gate(repo)
    assert r.returncode == 1 and "data/x.json" in r.stdout


def test_gate_refuses_missing_picks_unless_told(repo):
    (repo / "docs/data/picks.json").unlink()
    _git(repo, "add", "-A")
    assert _gate(repo).returncode == 1
    assert _gate(repo, "--no-picks").returncode == 0


class FakeR2:
    def __init__(self):
        self.puts, self.deletes = {}, []

    def put(self, key, data, ctype=None, **_):
        self.puts[key] = (data, ctype)
        return 200, '"e"'

    def delete(self, key):
        self.deletes.append(key)
        return 204


def test_archive_uploads_the_published_tree_and_prunes_past_30_days(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "docs/data/fin/S1.json").write_text('{"uncommitted": true}')  # work tree edits never reach the archive
    r2 = FakeR2()
    res = AR.run(r2=r2)
    assert res["ok"] and res["key"] == "archive/data-2026-11-26.tar.gz"
    data, ctype = r2.puts[res["key"]]
    assert ctype == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as t:
        names = t.getnames()
        assert "docs/data/picks.json" in names
        assert t.extractfile("docs/data/fin/S1.json").read() == b"{}"
    assert r2.deletes[0] == "archive/data-2026-10-26.tar.gz"  # 31 days before the data date
    assert "archive/data-2026-10-27.tar.gz" not in r2.deletes and len(r2.deletes) == AR.PRUNE_SPAN


def test_audit_checks():
    assert not AP.check_fresh("2026-11-25", "2026-11-26")["ok"]
    assert AP.check_fresh("2026-11-26", "2026-11-26")["ok"]
    assert AP.check_fresh("2026-11-26", None).get("skipped")
    assert not AP.check_r2_app({}, 100, "h")["ok"]
    assert not AP.check_r2_app({"sha": "a", "ct": 50, "failed": []}, 100, "h")["ok"]
    assert not AP.check_r2_app({"sha": "h", "ct": 200, "failed": ["data/x.json"]}, 100, "h")["ok"]
    assert AP.check_r2_app({"sha": "h", "ct": 200, "failed": []}, 100, "h")["ok"]
    assert AP.check_r2_app(None, 100, "h").get("skipped")
    assert not AP.check_archive(404, "k")["ok"] and AP.check_archive(200, "k")["ok"]
    row = {"date": "2026-11-26", "usage": json.dumps({"db_bytes": 300_000_000})}
    assert not AP.check_d1(row, "2026-11-26", True)["ok"]
    assert not AP.check_d1({"date": "2026-11-25", "usage": "{}"}, "2026-11-26", True)["ok"]
    assert AP.check_d1({"date": "2026-11-26", "usage": "{}"}, "2026-11-26", True)["ok"]
    assert AP.check_d1(None, "2026-11-26", False).get("skipped")
    runs = [{"status": "completed", "conclusion": "failure", "created_at": "2026-11-26T11:40:00Z"},
            {"status": "completed", "conclusion": "success", "created_at": "2026-11-26T14:40:00Z"}]
    c = AP.check_runs(runs)
    assert not c["ok"] and "later run succeeded" in c["detail"]
    assert AP.check_runs([])["ok"] and AP.check_runs(None).get("skipped")


class FakeGH:
    def __init__(self, open_issues):
        self.open, self.calls = open_issues, []

    def _r(self, code, body):
        r = type("R", (), {})()
        r.status_code, r.json = code, (lambda: body)
        return r

    def get(self, url, **kw):
        self.calls.append(("GET", url, None))
        return self._r(200, self.open)

    def post(self, url, json=None, **kw):
        self.calls.append(("POST", url, json))
        return self._r(201, {})

    def patch(self, url, json=None, **kw):
        self.calls.append(("PATCH", url, json))
        return self._r(200, {})


def test_audit_issue_opened_updated_closed(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("ISSUE_REPO", "o/r")
    bad = {"date": "2026-11-26", "data_date": "2026-11-25", "ok": False,
           "checks": [AP.chk("data_fresh", False, "published data is for 2026-11-25")]}
    gh = FakeGH([])
    AP.sync_issue(bad, gh)
    assert gh.calls[-1][0] == "POST" and gh.calls[-1][2]["labels"] == [AP.LABEL]
    gh = FakeGH([{"number": 7}])
    assert AP.sync_issue(bad, gh) == "issue #7 updated"
    good = {**bad, "ok": True, "checks": [AP.chk("data_fresh", True, "ok")]}
    gh = FakeGH([{"number": 7}])
    AP.sync_issue(good, gh)
    assert ("PATCH", "https://api.github.com/repos/o/r/issues/7", {"state": "closed", "state_reason": "completed"}) in gh.calls
    for k in ("GITHUB_TOKEN", "ISSUE_REPO"):
        os.environ.pop(k, None)
    assert AP.sync_issue(bad, FakeGH([])) == "issue: not configured"
