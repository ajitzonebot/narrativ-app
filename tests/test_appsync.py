"""App files -> R2 (narrativ/appsync.py): only changed blobs are uploaded, deletions follow git, failures and concurrent
uploaders leave the manifest conservative (the Worker then reads those paths from GitHub). Offline: a real git repo in a
temp folder and a fake S3 endpoint."""
import hashlib
import json
import os
import subprocess

import pytest

from narrativ import appsync


class FakeS3:
    """In-memory bucket behind the S3 HTTP interface, with ETags and If-Match / If-None-Match on PUT."""

    def __init__(self):
        self.objs, self.calls = {}, []
        self.fail = set()       # keys whose PUT answers 500
        self.on_put = None      # hook(key) run before a PUT is applied (simulates another writer)
        self.verify_id = "tok-id"

    def etag(self, k):
        return '"' + hashlib.md5(self.objs[k]).hexdigest() + '"'

    def __call__(self, method, url, headers=None, data=None, timeout=None):
        headers = headers or {}
        if "api.cloudflare.com" in url:
            return 200, {}, json.dumps({"success": True, "result": {"id": self.verify_id, "status": "active"}}).encode()
        assert url.startswith("https://acc.r2.cloudflarestorage.com/narrativ-data/")
        assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=")
        k = url.split("/narrativ-data/", 1)[1].replace("%26", "&")
        self.calls.append((method, k))
        if method == "GET":
            return (200, {"etag": self.etag(k)}, self.objs[k]) if k in self.objs else (404, {}, b"")
        if method == "DELETE":
            self.objs.pop(k, None)
            return 204, {}, b""
        if self.on_put:
            self.on_put(k)
        if k in self.fail:
            return 500, {}, b""
        if headers.get("If-None-Match") == "*" and k in self.objs:
            return 412, {}, b""
        if "If-Match" in headers and (k not in self.objs or self.etag(k) != headers["If-Match"]):
            return 412, {}, b""
        self.objs[k] = data
        return 200, {"etag": self.etag(k)}, b""

    def puts(self, prefix="app/data/"):
        return [k for m, k in self.calls if m == "PUT" and k.startswith(prefix)]

    def manifest(self):
        return json.loads(self.objs[appsync.MANIFEST_KEY])


def git(*a, t=None):
    env = dict(os.environ)
    if t:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{t} +0000"
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "main")
    d = tmp_path / "docs" / "data"
    (d / "fin").mkdir(parents=True)
    (d / "picks.json").write_text('{"v":2}')
    (d / "fin" / "M&M.NS.json").write_text('{"a":1}')
    (d / "fin" / "TCS.NS.json").write_text('{"a":2}')
    (d / "notes.md").write_text("not served")
    (tmp_path / "docs" / "app").mkdir()
    (tmp_path / "docs" / "app" / "version.json").write_text("{}")
    git("add", "-A")
    git("commit", "-qm", "one", t=1_700_000_000)
    monkeypatch.setattr(appsync, "WORKERS", 2)
    monkeypatch.setattr(appsync.time, "sleep", lambda s: None)
    return d


@pytest.fixture
def s3():
    return FakeS3()


def client(s3):
    return appsync.R2S3("acc", "kid", "secret", http=s3)


def test_first_run_uploads_every_servable_file_then_nothing(repo, s3):
    r = appsync.sync(r2=client(s3))
    assert r["ok"] and r["uploaded"] == 3 and r["puts"] == 5  # 3 files + claim + final manifest
    assert sorted(s3.puts()) == ["app/data/fin/M&M.NS.json", "app/data/fin/TCS.NS.json", "app/data/picks.json"]
    assert s3.objs["app/data/fin/M&M.NS.json"] == b'{"a":1}'
    m = s3.manifest()
    assert m["sha"] == git("rev-parse", "HEAD") and m["failed"] == [] and set(m["blobs"]) == {"data/picks.json", "data/fin/M&M.NS.json", "data/fin/TCS.NS.json"}
    s3.calls.clear()
    r = appsync.sync(r2=client(s3))
    assert r["ok"] and r["puts"] == 0 and [c for c in s3.calls if c[0] != "GET"] == []


def test_only_changed_files_and_deletions_follow_git(repo, s3):
    appsync.sync(r2=client(s3))
    (repo / "picks.json").write_text('{"v":3}')
    (repo / "fin" / "TCS.NS.json").unlink()
    git("add", "-A")
    git("commit", "-qm", "two", t=1_700_000_100)
    (repo / "fin" / "M&M.NS.json").write_text('{"uncommitted":1}')  # work tree only: never uploaded
    s3.calls.clear()
    r = appsync.sync(r2=client(s3))
    assert s3.puts() == ["app/data/picks.json"] and r["deletes"] == 1 and r["puts"] == 3
    assert "app/data/fin/TCS.NS.json" not in s3.objs and s3.objs["app/data/fin/M&M.NS.json"] == b'{"a":1}'
    m = s3.manifest()
    assert m["sha"] == git("rev-parse", "HEAD") and "data/fin/TCS.NS.json" not in m["blobs"]


def test_failed_upload_is_flagged_and_retried(repo, s3):
    s3.fail.add("app/data/picks.json")
    r = appsync.sync(r2=client(s3))
    assert r["failed"] == 1
    m = s3.manifest()
    assert m["failed"] == ["data/picks.json"] and m["blobs"]["data/picks.json"] == "?"
    s3.fail.clear()
    s3.calls.clear()
    r = appsync.sync(r2=client(s3))
    assert s3.puts() == ["app/data/picks.json"] and s3.manifest()["failed"] == []


def test_run_that_dies_after_the_claim_leaves_paths_flagged(repo, s3, monkeypatch):
    appsync.sync(r2=client(s3))
    first = s3.manifest()["sha"]
    (repo / "picks.json").write_text('{"v":9}')
    git("commit", "-qam", "two", t=1_700_000_100)

    def boom(_):
        raise RuntimeError("runner killed")
    monkeypatch.setattr(appsync, "read_blobs", boom)
    assert not appsync.sync(r2=client(s3))["ok"]
    m = s3.manifest()
    assert m["sha"] == first and m["failed"] == ["data/picks.json"] and m["blobs"]["data/picks.json"] == "?"


def test_concurrent_uploader_merges_to_the_older_commit(repo, s3):
    appsync.sync(r2=client(s3))
    base = s3.manifest()
    (repo / "picks.json").write_text('{"v":5}')
    git("commit", "-qam", "two", t=1_700_000_100)
    other = {**base, "sha": "f" * 40, "ct": 1_700_000_050, "blobs": {**base["blobs"], "data/fin/TCS.NS.json": "b" * 40}}

    def interloper(k):  # another uploader writes its final manifest while this run uploads
        if k == "app/data/picks.json" and s3.on_put:
            s3.on_put = None
            s3.objs[appsync.MANIFEST_KEY] = json.dumps(other).encode()
    s3.on_put = interloper
    r = appsync.sync(r2=client(s3))
    assert r["ok"]
    m = s3.manifest()
    assert m["sha"] == "f" * 40  # the older of the two commits
    assert {"data/picks.json", "data/fin/TCS.NS.json"} <= set(m["failed"])
    assert m["blobs"]["data/fin/TCS.NS.json"] == "?" and m["blobs"]["data/fin/M&M.NS.json"] == base["blobs"]["data/fin/M&M.NS.json"]


def test_older_checkout_does_not_overwrite_a_newer_upload(repo, s3):
    appsync.sync(r2=client(s3))
    m = s3.manifest()
    s3.objs[appsync.MANIFEST_KEY] = json.dumps({**m, "ct": m["ct"] + 999, "blobs": {}}).encode()
    s3.calls.clear()
    assert appsync.sync(r2=client(s3))["ok"] and s3.puts() == [] and s3.puts("app/_") == []


def test_merge_conflict_rules():
    a = {"sha": "a", "ct": 2, "failed": ["x"], "blobs": {"p": "1", "q": "2", "r": "3"}}
    b = {"sha": "b", "ct": 1, "failed": ["y"], "blobs": {"p": "1", "q": "9"}}
    m = appsync.merge_conflict(a, b)
    assert m["sha"] == "b" and m["blobs"] == {"p": "1", "q": "?", "r": "?"} and m["failed"] == ["q", "r", "x", "y"]


def test_credentials_derived_from_the_api_token(monkeypatch, s3):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "secret-token")
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    c = appsync.R2S3.from_env(http=s3)
    assert c.key_id == "tok-id" and c.secret == hashlib.sha256(b"secret-token").hexdigest()
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN")
    assert appsync.R2S3.from_env(http=s3) is None


def test_no_credentials_is_a_quiet_skip(repo, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    assert appsync.sync() == {"ok": False, "puts": 0, "uploaded": 0, "deletes": 0, "failed": 0, "unchanged": 0}
