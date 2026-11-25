"""scripts/push_retry.sh: a rebase conflict only in docs/data/packs/ keeps the pushing run's copy; any other conflict fails."""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push_retry.sh"


def _git(cwd, *a, env):
    return subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def _setup(tmp_path):
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_PUSH_TOKEN": "not-a-token"}
    remote, a, b = tmp_path / "remote.git", tmp_path / "a", tmp_path / "b"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote), env=env)
    _git(tmp_path, "clone", "-q", str(remote), str(a), env=env)
    (a / "docs/data/packs").mkdir(parents=True)
    (a / "docs/data/packs/X.json").write_text('{"v": 0}\n')
    (a / "docs/data/picks.json").write_text('{"v": 0}\n')
    _git(a, "add", "-A", env=env)
    _git(a, "commit", "-qm", "base", env=env)
    _git(a, "push", "-q", "origin", "HEAD:main", env=env)
    _git(tmp_path, "clone", "-q", str(remote), str(b), env=env)
    fast = tmp_path / "push_retry_fast.sh"
    fast.write_text(SCRIPT.read_text().replace("sleep 5", "sleep 0"))
    return env, remote, a, b, fast


def _commit(repo, files, msg, env):
    for f, t in files.items():
        (repo / f).write_text(t)
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", msg, env=env)


def test_packs_conflict_keeps_this_runs_copy(tmp_path):
    env, remote, a, b, fast = _setup(tmp_path)
    _commit(b, {"docs/data/packs/X.json": '{"v": "reader"}\n'}, "reader", env)
    _git(b, "push", "-q", "origin", "HEAD:main", env=env)
    _commit(a, {"docs/data/packs/X.json": '{"v": "daily"}\n', "docs/data/picks.json": '{"v": 1}\n'}, "daily", env)
    r = subprocess.run(["bash", str(fast)], cwd=a, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(remote, "show", "main:docs/data/packs/X.json", env=env) == '{"v": "daily"}\n'
    assert _git(remote, "show", "main:docs/data/picks.json", env=env) == '{"v": 1}\n'
    assert "reader" in _git(remote, "log", "--format=%s", "main", env=env)  # the reader's commit is kept in history


def test_conflict_outside_packs_fails_and_leaves_no_rebase(tmp_path):
    env, remote, a, b, fast = _setup(tmp_path)
    _commit(b, {"docs/data/picks.json": '{"v": "other"}\n'}, "other", env)
    _git(b, "push", "-q", "origin", "HEAD:main", env=env)
    _commit(a, {"docs/data/picks.json": '{"v": 1}\n'}, "daily", env)
    r = subprocess.run(["bash", str(fast)], cwd=a, env=env, capture_output=True, text=True)
    assert r.returncode == 1
    assert "failed after 3 attempts" in r.stdout
    assert not (a / ".git" / "rebase-merge").exists() and not (a / ".git" / "rebase-apply").exists()
    assert _git(remote, "show", "main:docs/data/picks.json", env=env) == '{"v": "other"}\n'
