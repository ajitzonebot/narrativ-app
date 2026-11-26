"""narrativ/databranch.py and scripts/publish.sh against a local bare remote (no network)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from narrativ import databranch as DB

ROOT = Path(__file__).resolve().parents[1]
PICKS = {"date": "2026-11-26", "picks": [{"s": "A.NS", "p": 1.0}]}


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _write(repo: Path, files: dict):
    for f, t in files.items():
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t if isinstance(t, str) else json.dumps(t))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                 "HOME": str(tmp_path), "GIT_PUSH_TOKEN": "", "CLOUDFLARE_API_TOKEN": "", "DATA_STAGE": "0", "APP_REF": "main",
                 "PYTHONPATH": str(ROOT)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    remote, a = tmp_path / "remote.git", tmp_path / "a"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", "-q", str(remote), str(a))
    _write(a, {"docs/data/picks.json": PICKS, "docs/data/packs/X.json": {"v": 0}, "docs/data/fin/A.json": {"v": 0},
               "docs/data/fin/B.json": {"v": 0}, "docs/data/theses.json": {"t": 0}, "data/a.json": {"v": 0},
               "data/financials/A.json": {"v": 0}, "RULES.md": "rules\n", "run.py": "print(1)\n"})
    _git(a, "add", "-A")
    _git(a, "commit", "-qm", "base")
    _git(a, "push", "-q", "origin", "HEAD:main")
    monkeypatch.chdir(a)
    assert DB.bootstrap() == 0
    return tmp_path, remote, a


def _clone(tmp_path, name):
    b = tmp_path / name
    _git(tmp_path, "clone", "-q", str(tmp_path / "remote.git"), str(b))
    return b


def _show(remote, path, ref="data"):
    return json.loads(_git(remote, "show", f"{ref}:{path}"))


def test_bootstrap_holds_only_data_paths_with_main_trailer(env):
    _, remote, _ = env
    names = _git(remote, "ls-tree", "-r", "--name-only", "data").split()
    assert "docs/data/picks.json" in names and "data/financials/A.json" in names
    assert "docs/data/theses.json" not in names and "run.py" not in names and "RULES.md" not in names
    assert "Main: " in _git(remote, "log", "-1", "--format=%B", "data")


def test_two_jobs_on_different_files_both_land(env, monkeypatch):
    tmp, remote, a = env
    b = _clone(tmp, "b")
    monkeypatch.chdir(b)
    _write(b, {"data/a.json": {"v": "b"}})
    assert DB.commit("b", ["data/a.json"], wait=0) == 0
    monkeypatch.chdir(a)
    _write(a, {"docs/data/fin/A.json": {"v": "a"}})
    assert DB.commit("a", ["docs/data/fin/A.json"], wait=0) == 0  # its base is older: applied onto the new tip
    assert _show(remote, "data/a.json") == {"v": "b"} and _show(remote, "docs/data/fin/A.json") == {"v": "a"}
    assert not _git(remote, "rev-list", "--merges", "data").strip()


def test_overlap_in_packs_keeps_this_runs_copy_elsewhere_fails(env, monkeypatch):
    tmp, remote, a = env
    b = _clone(tmp, "b")
    monkeypatch.chdir(b)
    _write(b, {"docs/data/packs/X.json": {"v": "reader"}, "docs/data/fin/B.json": {"v": "reader"}})
    assert DB.commit("reader", ["docs/data/packs", "docs/data/fin/B.json"], wait=0) == 0
    monkeypatch.chdir(a)
    _write(a, {"docs/data/packs/X.json": {"v": "daily"}})
    assert DB.commit("daily packs", ["docs/data/packs"], wait=0) == 0
    assert _show(remote, "docs/data/packs/X.json") == {"v": "daily"}
    _write(a, {"docs/data/fin/B.json": {"v": "daily"}})
    (Path(DB.gitdir()) / "data-base").write_text(_git(remote, "rev-parse", "data~2").strip() + "\n")  # started before the reader
    assert DB.commit("daily fin", ["docs/data/fin/B.json"], wait=0, tries=1) == 1
    assert _show(remote, "docs/data/fin/B.json") == {"v": "reader"}


def test_mine_all_overwrites_like_theirs(env, monkeypatch):
    tmp, remote, a = env
    b = _clone(tmp, "b")
    monkeypatch.chdir(b)
    _write(b, {"data/a.json": {"v": "other"}})
    assert DB.commit("other", ["data/a.json"], wait=0) == 0
    monkeypatch.chdir(a)
    _write(a, {"data/a.json": {"v": "mine"}})
    assert DB.commit("mine", ["data/a.json"], mine="all", wait=0) == 0
    assert _show(remote, "data/a.json") == {"v": "mine"}


def test_gate_refusal_publishes_nothing(env, monkeypatch):
    _, remote, a = env
    tip = _git(remote, "rev-parse", "data").strip()
    _write(a, {"docs/data/picks.json": {"date": "2026-11-26", "picks": []}})
    assert DB.commit("broken", ["docs/data"], wait=0) == 1
    assert _git(remote, "rev-parse", "data").strip() == tip


def test_follow_copies_main_and_never_goes_back(env, monkeypatch):
    _, remote, a = env
    _write(a, {"docs/data/fin/A.json": {"v": 1}})
    _git(a, "commit", "-qam", "m1")
    m1 = _git(a, "rev-parse", "HEAD").strip()
    _write(a, {"docs/data/fin/A.json": {"v": 2}, "docs/data/theses.json": {"t": 2}})
    _git(a, "commit", "-qam", "m2")
    assert DB.follow() == 0
    assert _show(remote, "docs/data/fin/A.json") == {"v": 2}
    tip = _git(remote, "rev-parse", "data").strip()
    assert DB._mirror_main(m1, "late", regress_check=True) == 0  # an older main commit arrives late: skipped
    assert _git(remote, "rev-parse", "data").strip() == tip
    assert "docs/data/theses.json" not in _git(remote, "ls-tree", "-r", "--name-only", "data")


def test_checkout_is_a_no_op_while_main_tracks_the_data(env, monkeypatch):
    _, remote, a = env
    _write(a, {"docs/data/fin/A.json": {"v": "local"}})
    assert DB.checkout() == 0
    assert json.loads((a / "docs/data/fin/A.json").read_text()) == {"v": "local"}
    # forced past the guard but without --force: tracked files are left alone, untracked ones are written
    _git(a, "rm", "-q", "--cached", "docs/data/fin/B.json")
    (a / "docs/data/fin/B.json").unlink()
    assert DB.checkout(even_if_tracked=True) == 0
    assert json.loads((a / "docs/data/fin/A.json").read_text()) == {"v": "local"}
    assert (a / "docs/data/fin/B.json").exists()


def test_trim_keeps_the_tip_tree_and_recent_history(env, monkeypatch):
    _, remote, a = env
    import time
    now = time.time()
    for k, age in enumerate((20, 10, 3, 1)):
        when = f"@{int(now - age * 86400)} +0000"
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        monkeypatch.setenv("GIT_AUTHOR_DATE", when)
        _write(a, {"data/a.json": {"v": k}})
        assert DB.commit(f"c{k}", ["data/a.json"], wait=0) == 0
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    monkeypatch.delenv("GIT_AUTHOR_DATE")
    tip = DB.fetch_tip(full=True)
    new, n = DB.rewrite(tip, 7, now)
    assert DB.tree_of(new) == DB.tree_of(tip)
    assert n == 3  # root = state of the 10-days-old commit, then the 3- and 1-day ones
    msgs = _git(a, "log", "--format=%s", new).split("\n")
    assert msgs[0] == "c3" and msgs[1] == "c2" and msgs[2].startswith("data: history starts here")
    assert not DB.push(new, "0" * 40)  # a stale lease is refused
    assert DB.push(new, tip)
    assert _git(remote, "rev-parse", "data^{tree}").strip() == DB.tree_of(tip)
    assert DB.trim(test_ref=None) == 0  # below stage 4: does nothing


def test_gitignore_matches_the_path_lists():
    for p in DB.NEVER:
        assert subprocess.run(["git", "check-ignore", "-q", f"{p}/x"], cwd=ROOT).returncode == 0, p
    for p in DB.MAIN_OWNED:
        assert subprocess.run(["git", "check-ignore", "-q", p], cwd=ROOT).returncode == 1, p
        assert not DB.in_data(p)
    assert DB.in_data("docs/data/picks.json") and DB.in_data("data/financials/A.json") and not DB.in_data("RULES.md")


def _publish(cwd, stage, *args):
    e = {**os.environ, "DATA_STAGE": str(stage)}
    return subprocess.run(["bash", str(ROOT / "scripts/publish.sh"), *args], cwd=cwd, env=e, capture_output=True, text=True)


def test_publish_stage0_is_a_plain_main_commit(env):
    _, remote, a = env
    tip = _git(remote, "rev-parse", "data").strip()
    _write(a, {"docs/data/fin/A.json": {"v": 9}})
    r = _publish(a, 0, "-m", "daily", "--gate", "--", "docs/data", "data", "RULES.md", "missing/path")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _show(remote, "docs/data/fin/A.json", "main") == {"v": 9}
    assert _git(remote, "rev-parse", "data").strip() == tip  # stage 0 never touches the data branch


def test_publish_stage1_follows(env):
    _, remote, a = env
    _write(a, {"docs/data/fin/A.json": {"v": 7}})
    r = _publish(a, 1, "-m", "daily", "--", "docs/data", "data")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _show(remote, "docs/data/fin/A.json", "main") == _show(remote, "docs/data/fin/A.json") == {"v": 7}


def test_publish_stage3_splits_data_and_main(env):
    _, remote, a = env
    main_before = _show(remote, "docs/data/fin/A.json", "main")
    _write(a, {"docs/data/fin/A.json": {"v": 3}, "RULES.md": "rules 3\n"})
    # stage 3 has the generated files ignored on main: simulate with an info/exclude
    (a / ".git/info/exclude").write_text("/docs/data/fin/\n")
    _git(a, "rm", "-q", "-r", "--cached", "docs/data/fin")
    _git(a, "commit", "-qm", "untrack")
    _git(a, "push", "-q", "origin", "HEAD:main")
    r = _publish(a, 3, "-m", "daily", "--gate", "--", "docs/data/fin", "RULES.md")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _show(remote, "docs/data/fin/A.json") == {"v": 3}
    assert _git(remote, "show", "main:RULES.md") == "rules 3\n"
    assert main_before == {"v": 0} and "docs/data/fin/A.json" not in _git(remote, "ls-tree", "-r", "--name-only", "main")
