"""Generated data on its own branch `data`, history trimmed to the last days (owner, 26 Nov 2026: "build option A with 7 days
and R2 30 days"). main keeps code, rules and the files people and Claude write; `data` keeps docs/data and data.

    python -m narrativ.databranch checkout [--paths P ...]   # write the data tip into the work tree (stage 3+; else no-op)
    python -m narrativ.databranch commit -m MSG [--mine all|PREFIX] [--archive] -- PATHS   # publish to data (stage 3+)
    python -m narrativ.databranch follow                     # after a main push: data = main's data paths (stages 1-2)
    python -m narrativ.databranch resync --from main|--to main
    python -m narrativ.databranch parity                     # exit 1 when main and data differ (stages 1-2)
    python -m narrativ.databranch bootstrap                  # create `data` from origin/main (once)
    python -m narrativ.databranch trim [--days 7] [--test-ref NAME]   # stage 4, weekly (data-trim.yml)

Stages (Actions variable DATA_STAGE in narrativ-app; README "Data branch"):
  0  today: everything on main.                1  main + `follow` (dual write), readers on main.
  2  same writes, the app reads `data` (APP_REF=data: appsync and the Worker follow the data branch).
  3  generated files leave main (.gitignore); jobs `checkout` them from `data` and `commit` there.
  4  weekly trim of `data` to the last DAYS days (force push on `data` only; history kept 30 days as an R2 bundle).

How a commit works (no rebase, nothing ever stops half way): a second index (.git/data.index) holds the base tree the job
started from; the job's files are added to it and compared with the base (its change set C). Then, up to TRIES times: fetch
the tip, apply C onto it (a path someone else also changed since the base fails the commit unless it is under --mine),
write the tree, commit with the tip as parent and push without force. A rejected push (someone pushed meanwhile) starts
over from the new tip. The publish gate (scripts/publish_gate.py) checks the result against the base first.

Paths: DATA_ROOTS minus MAIN_OWNED (written by people / Claude, stay on main) minus NEVER (caches, never committed).
Token: GIT_PUSH_TOKEN, given to git as an extra header (same as scripts/push_retry.sh); a checkout that kept its
credentials is used as it is.
"""
import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRANCH = "data"
REF = f"refs/heads/{BRANCH}"
TRACK = f"refs/remotes/origin/{BRANCH}"
DATA_ROOTS = ("docs/data", "data")
MAIN_OWNED = ("docs/data/theses.json", "docs/data/lessons.jsonl", "docs/data/research_runs.jsonl",
              "docs/data/industry_why.json", "docs/data/schedule.json", "docs/data/claims.json", "docs/data/claims", "docs/data/issues", "data/industry_sources", "data/doc_rules.json", "data/scan_requests.txt")
NEVER = ("data/source_cache", "data/news_cache", "data/exchange_tmp", "data/study_cache")
TRIES = 5
DAYS = 7
BUNDLE_PREFIX = "archive/data-branch-"
BUNDLE_KEEP_DAYS = 30
ZERO = "0" * 40


# ---------------------------------------------------------------- paths
def in_data(p: str) -> bool:
    """True for a path the data branch owns."""
    p = p.strip("/")
    if not any(p == r or p.startswith(r + "/") for r in DATA_ROOTS):
        return False
    return not any(p == x or p.startswith(x + "/") for x in (*MAIN_OWNED, *NEVER))


def pathspec(paths=None) -> list[str]:
    """git pathspec for the data paths among `paths` (default: all data roots), main-owned files and caches excluded."""
    roots = [p for p in (paths or DATA_ROOTS) if any(p.strip("/") == r or p.strip("/").startswith(r + "/") or r.startswith(p.strip("/") + "/")
                                                     for r in DATA_ROOTS)]
    if not roots:
        return []
    return [*roots, *[f":(exclude){x}" for x in (*MAIN_OWNED, *NEVER)]]


def stage() -> int:
    try:
        return int(os.environ.get("DATA_STAGE") or 0)
    except ValueError:
        return 0


# ---------------------------------------------------------------- git
def _auth() -> list[str]:
    tok = os.environ.get("GIT_PUSH_TOKEN", "")
    have = subprocess.run(["git", "config", "--get-all", "http.https://github.com/.extraheader"], capture_output=True, text=True).stdout
    if not tok or have.strip():
        return []
    b = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {b}"]


def git(*a: str, index: str | None = None, inp: bytes | None = None, check: bool = True, env: dict | None = None) -> str:
    e = {**os.environ, **(env or {})}
    if index:
        e["GIT_INDEX_FILE"] = index
    r = subprocess.run(["git", *a], input=inp, capture_output=True, env=e)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a[:3])}: {r.stderr.decode(errors='replace').strip()[:300]}")
    return r.stdout.decode("utf-8", "surrogateescape")


def _ok(*a: str, index: str | None = None) -> bool:
    e = {**os.environ}
    if index:
        e["GIT_INDEX_FILE"] = index
    return subprocess.run(["git", *a], capture_output=True, env=e).returncode == 0


def gitdir() -> Path:
    return Path(git("rev-parse", "--absolute-git-dir").strip())


def index_path(name: str = "data.index") -> str:
    return str(gitdir() / name)


def fetch_tip(full: bool = False) -> str | None:
    """Fetch origin's `data` into refs/remotes/origin/data; its sha, or None when the branch does not exist."""
    # full: the branch's whole history only (a huge depth; --unshallow would also pull main's history into a shallow clone)
    a = [*_auth(), "fetch", "-q", "--no-tags", "--depth=1000000" if full else "--depth=1"]
    r = subprocess.run(["git", *a, "origin", f"+{REF}:{TRACK}"], capture_output=True, text=True)
    if r.returncode:
        if "couldn't find remote ref" in r.stderr or "not found" in r.stderr.lower():
            return None
        raise RuntimeError(f"fetch {BRANCH}: {r.stderr.strip()[:300]}")
    return git("rev-parse", TRACK).strip()


def tree_of(rev: str) -> str:
    return git("rev-parse", f"{rev}^{{tree}}").strip()


def entries(rev: str) -> dict[str, str]:
    """{path: 'mode sha'} of the data paths in rev's tree."""
    out = {}
    raw = git("ls-tree", "-r", "-z", "--full-tree", rev, "--", *DATA_ROOTS)
    for rec in raw.split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        mode, _typ, sha = meta.split()
        if in_data(path):
            out[path] = f"{mode} {sha}"
    return out


def index_entries(index: str, paths=None) -> dict[str, str]:
    out = {}
    raw = git("ls-files", "-s", "-z", "--", *(paths or DATA_ROOTS), index=index)
    for rec in raw.split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        mode, sha, _st = meta.split()
        if in_data(path):
            out[path] = f"{mode} {sha}"
    return out


def build_tree(ents: dict[str, str]) -> str:
    """A tree holding exactly these entries."""
    with tempfile.TemporaryDirectory() as d:
        idx = os.path.join(d, "idx")
        git("read-tree", "--empty", index=idx)
        lines = "".join(f"{v.split()[0]} {v.split()[1]}\t{p}\0" for p, v in sorted(ents.items()))
        if lines:
            git("update-index", "-z", "--index-info", index=idx, inp=lines.encode("utf-8", "surrogateescape"))
        return git("write-tree", index=idx).strip()


def commit_tree(tree: str, msg: str, parent: str | None = None, env: dict | None = None) -> str:
    a = ["commit-tree", tree, "-m", msg]
    if parent:
        a += ["-p", parent]
    e = {"GIT_AUTHOR_NAME": "github-actions[bot]", "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
         "GIT_COMMITTER_NAME": "github-actions[bot]", "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}
    for k in list(e):  # an identity configured in the environment wins (tests, local runs)
        if os.environ.get(k):
            e.pop(k)
    return git(*a, env={**e, **(env or {})}).strip()


def push(commit: str, force_lease: str | None = None, ref: str = REF) -> bool:
    a = [*_auth(), "push", "-q", "origin"]
    if force_lease:
        a.append(f"--force-with-lease={ref}:{force_lease}")
    r = subprocess.run(["git", *a, f"{commit}:{ref}"], capture_output=True, text=True)
    if r.returncode:
        print(f"[databranch] push {ref}: {r.stderr.strip()[:200]}")
    return r.returncode == 0


def _summary(line: str) -> None:
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write(line + "\n")


def after_push(commit: str, archive: bool = False) -> None:
    """R2 app copy and (daily) the dated archive, from the data commit; never fatal (same as push_retry.sh app_r2)."""
    if not os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("APP_R2", "1") == "0":
        return
    jobs = []
    if os.environ.get("APP_REF", "main") == BRANCH:
        jobs.append(("App files to R2", ["python3", "-m", "narrativ.appsync", "--rev", commit, "--ref", BRANCH], "[appsync]", 900))
    if archive:
        jobs.append(("Archive to R2", ["python3", "-m", "narrativ.archive", "--rev", commit], "[archive]", 600))
    for title, cmd, tag, tmo in jobs:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo)
            out, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            out, rc = f"{tag} timed out", 124
        print(out.rstrip())
        lines = [x for x in out.splitlines() if x.startswith(tag) and not x.startswith(f"{tag} put ")]
        _summary(f"{title} (exit {rc}): {' '.join(lines[-3:])}")
        if rc:
            print(f"::warning::{title.lower()} did not finish")


def _base_file() -> Path:
    return gitdir() / "data-base"


def base_sha() -> str | None:
    f = _base_file()
    return f.read_text().strip() if f.exists() else None


# ---------------------------------------------------------------- checkout
def main_tracks_data() -> bool:
    """Stages 0-2: main still tracks the generated files (picks.json is the marker)."""
    return _ok("ls-files", "--error-unmatch", "docs/data/picks.json")


def checkout(paths=None, force: bool = False, even_if_tracked: bool = False) -> int:
    """Write the data tip's files (or only `paths`) into the work tree and remember it as the base for `commit`.
    A no-op while main still tracks the generated files (stages 0-2); never overwrites a file main tracks unless --force."""
    if main_tracks_data() and not even_if_tracked:
        print("[databranch] main tracks the data files (stage 0-2): nothing to check out")
        return 0
    tip = fetch_tip()
    if tip is None:
        print(f"[databranch] no `{BRANCH}` branch yet: nothing to check out")
        return 0
    idx = index_path()
    git("read-tree", tip, index=idx)
    want = [p for p in index_entries(idx) if not paths or any(p == x.rstrip("/") or p.startswith(x.rstrip("/") + "/") for x in paths)]
    if not force:
        tracked = set(git("ls-files", "-z", "--", *DATA_ROOTS).split("\0"))
        want = [p for p in want if p not in tracked]
    if want:
        git("checkout-index", "-f", "-z", "--stdin", index=idx, inp="\0".join(want).encode("utf-8", "surrogateescape"))
    _base_file().write_text(tip + "\n")
    print(f"[databranch] {len(want)} files from {BRANCH} {tip[:8]}")
    return 0


# ---------------------------------------------------------------- commit
def change_set(base_ents: dict, new_ents: dict, scope=None) -> dict[str, str | None]:
    """{path: new entry, or None when deleted} for paths that differ (only inside `scope` prefixes when given)."""
    def inside(p):
        return not scope or any(p == s.rstrip("/") or p.startswith(s.rstrip("/") + "/") for s in scope)
    out = {}
    for p in set(base_ents) | set(new_ents):
        if not inside(p):
            continue
        if base_ents.get(p) != new_ents.get(p):
            out[p] = new_ents.get(p)
    return out


def overlap(mine_changes: dict, base_ents: dict, tip_ents: dict, mine: str | None) -> list[str]:
    """Paths this job changed that someone else also changed since the base, minus those this job may overwrite."""
    out = []
    for p in mine_changes:
        if base_ents.get(p) == tip_ents.get(p):
            continue
        if mine == "all" or (mine and p.startswith(mine)):
            continue
        out.append(p)
    return sorted(out)


def apply(tip_ents: dict, changes: dict) -> dict:
    out = dict(tip_ents)
    for p, v in changes.items():
        if v is None:
            out.pop(p, None)
        else:
            out[p] = v
    return out


def gate(base: str, idx: str, picks: bool = True) -> bool:
    gate_py = Path(__file__).resolve().parents[1] / "scripts" / "publish_gate.py"
    a = [sys.executable, str(gate_py), "--base", base]
    if not picks:
        a.append("--no-picks")
    r = subprocess.run(a, env={**os.environ, "GIT_INDEX_FILE": idx}, capture_output=True, text=True)
    print(r.stdout.rstrip())
    if r.returncode:
        print(r.stderr.rstrip())
    return r.returncode == 0


def commit(msg: str, paths: list[str], mine: str | None = "docs/data/packs/", archive: bool = False,
           picks: bool = True, tries: int = TRIES, wait: float = 3.0) -> int:
    """Publish this job's changes under `paths` to the data branch (see the module doc). 0 = published or nothing to do."""
    spec = pathspec(paths)
    if not spec:
        print("[databranch] no data paths given")
        return 0
    base = base_sha() or fetch_tip()
    if base is None:
        print(f"::error::no `{BRANCH}` branch: run `python -m narrativ.databranch bootstrap` first")
        return 1
    idx = index_path()
    if not _ok("cat-file", "-e", base):
        base = fetch_tip()
    git("read-tree", base, index=idx)
    git("add", "-A", "-f", "--", *spec, index=idx)
    base_ents = entries(base)
    scope = [p for p in paths if pathspec([p])]
    mine_changes = change_set(base_ents, index_entries(idx), scope)
    if not mine_changes:
        print("[databranch] nothing to publish")
        return 0
    if not gate(base, idx, picks=picks):
        print("::error::publish gate refused the data: nothing published, the last data stays live")
        return 1
    for i in range(tries):
        tip = fetch_tip()
        if tip is None:
            print(f"::error::`{BRANCH}` branch disappeared")
            return 1
        tip_ents = entries(tip)
        clash = overlap(mine_changes, base_ents, tip_ents, mine)
        if clash:
            print(f"::error::{BRANCH}: {len(clash)} file(s) also changed by another job since this one started: {', '.join(clash[:5])}")
            return 1
        tree = build_tree(apply(tip_ents, mine_changes))
        if tree == tree_of(tip):
            print("[databranch] the data branch already holds these files")
            _base_file().write_text(tip + "\n")
            return 0
        c = commit_tree(tree, msg, tip)
        if push(c):
            _base_file().write_text(c + "\n")
            git("read-tree", c, index=idx)
            print(f"[databranch] published {len(mine_changes)} file(s) to {BRANCH} {c[:8]} (attempt {i + 1})")
            _summary(f"Data branch: {len(mine_changes)} file(s), commit {c[:8]}")
            after_push(c, archive)
            return 0
        time.sleep(wait * (i + 1))
    print(f"::error::push to {BRANCH} failed after {tries} attempts")
    return 1


# ---------------------------------------------------------------- dual write (stages 1-2), resync, parity, bootstrap
MAIN_TRAILER = re.compile(r"^Main: ([0-9a-f]{40}) (\d+)\s*$", re.M)


def main_mark(rev: str) -> tuple[str, int] | None:
    m = MAIN_TRAILER.search(git("log", "-1", "--format=%B", rev))
    return (m.group(1), int(m.group(2))) if m else None


def _mirror_main(rev: str, msg: str, regress_check: bool, tries: int = 3) -> int:
    sha = git("rev-parse", rev).strip()
    if not _ok("cat-file", "-e", f"{sha}:docs/data/picks.json"):  # stage 3+: main no longer holds the data; copying it would empty `data`
        print(f"[databranch] main {sha[:8]} holds no data files: not copied to {BRANCH}")
        return 0
    ct = int(git("log", "-1", "--format=%ct", sha).strip())
    tree = build_tree(entries(sha))
    for i in range(tries):
        tip = fetch_tip()
        if tip is None:
            print(f"[databranch] no `{BRANCH}` branch: nothing to follow (run bootstrap)")
            return 0
        mark = main_mark(tip)
        if regress_check and mark and (mark[0] == sha or mark[1] > ct or (
                _ok("cat-file", "-e", f"{mark[0]}^{{commit}}") and _ok("merge-base", "--is-ancestor", sha, mark[0]))):
            print(f"[databranch] {BRANCH} already follows main {mark[0][:8]}: skipped")
            return 0
        if tree == tree_of(tip) and mark and mark[0] == sha:
            return 0
        c = commit_tree(tree, f"{msg} {sha[:8]}\n\nMain: {sha} {ct}", tip)
        if push(c):
            print(f"[databranch] {BRANCH} {c[:8]} = main {sha[:8]}")
            after_push(c)
            return 0
        time.sleep(3 * (i + 1))
    print(f"::warning::{BRANCH}: could not follow main {sha[:8]}")
    return 1


def follow() -> int:
    """After a successful main push (stages 1-2): make the data branch's paths equal main's HEAD. Never goes back to an
    older main commit (a late follow is skipped: the trailer `Main: <sha> <commit time>` records what it holds)."""
    return _mirror_main("HEAD", "data: follow main", regress_check=True)


def resync(direction: str) -> int:
    if direction == "from-main":
        subprocess.run(["git", *_auth(), "fetch", "-q", "origin", "main"], check=True)
        return _mirror_main("FETCH_HEAD", "data: resync from main", regress_check=False)
    tip = fetch_tip()
    if tip is None:
        print(f"::error::no `{BRANCH}` branch")
        return 1
    idx = index_path()
    git("read-tree", tip, index=idx)
    git("checkout-index", "-a", "-f", index=idx)
    keep = set(index_entries(idx))
    for p in git("ls-files", "-z", "--", *DATA_ROOTS).split("\0"):
        if p and in_data(p) and p not in keep and os.path.exists(p):
            os.remove(p)
    git("add", "-A", "-f", "--", *pathspec())
    if _ok("diff", "--cached", "--quiet"):
        print("[databranch] main already holds the data branch's files")
        return 0
    git("commit", "-q", "-m", f"data: resync from {BRANCH} {tip[:8]}")
    return subprocess.run(["bash", "scripts/push_retry.sh"]).returncode


def parity(main_rev: str = "origin/main") -> int:
    subprocess.run(["git", *_auth(), "fetch", "-q", "origin", "main:refs/remotes/origin/main"], capture_output=True)
    tip = fetch_tip()
    if tip is None:
        print(f"[databranch] no `{BRANCH}` branch")
        return 1
    a, b = entries(main_rev), entries(tip)
    diff = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))
    print(f"[databranch] parity main vs {BRANCH}: {len(diff)} file(s) differ" + (f": {', '.join(diff[:10])}" if diff else ""))
    return 1 if diff else 0


def bootstrap(rev: str = "origin/main", force: bool = False) -> int:
    subprocess.run(["git", *_auth(), "fetch", "-q", "origin", "main:refs/remotes/origin/main"], capture_output=True)
    if fetch_tip() is not None and not force:
        print(f"[databranch] `{BRANCH}` already exists: nothing to do")
        return 0
    sha = git("rev-parse", rev).strip()
    ct = git("log", "-1", "--format=%ct", sha).strip()
    c = commit_tree(build_tree(entries(sha)), f"data: start from main {sha[:8]}\n\nMain: {sha} {ct}")
    ok = push(c)
    print(f"[databranch] bootstrap {BRANCH} {c[:8]} from main {sha[:8]}: {'pushed' if ok else 'push failed'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- trim (stage 4)
def _meta(c: str) -> tuple[dict, str]:
    f = git("log", "-1", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B", c).split("\0")
    env = {"GIT_AUTHOR_NAME": f[0], "GIT_AUTHOR_EMAIL": f[1], "GIT_AUTHOR_DATE": f[2],
           "GIT_COMMITTER_NAME": f[3], "GIT_COMMITTER_EMAIL": f[4], "GIT_COMMITTER_DATE": f[5]}
    return env, f[6].rstrip("\n")


def rewrite(tip: str, days: int = DAYS, now: float | None = None) -> tuple[str | None, int]:
    """New history for `tip`: a root commit holding the tree of the newest commit older than `days`, then every later commit
    replayed with its own tree, message, authors and dates. (None, 0) when nothing is older than the window."""
    if git("rev-list", "--merges", tip).strip():
        raise RuntimeError(f"{BRANCH} has merge commits: not trimming")
    cutoff = (now or time.time()) - days * 86400
    rows = [x.split() for x in git("log", "--first-parent", "--format=%H %ct", tip).splitlines() if x.strip()]
    older = [h for h, ct in rows if int(ct) < cutoff]
    if not older:
        return None, 0
    c0 = older[0]  # rev-list is newest first: the newest commit before the cutoff
    if c0 == rows[-1][0]:
        return None, 0  # already the root: nothing to cut
    env0, _ = _meta(c0)
    prev = commit_tree(tree_of(c0), f"data: history starts here (state of {c0[:8]}, {env0['GIT_COMMITTER_DATE'][:10]})\n\nTrimmed-From: {c0}", env=env0)
    later = git("rev-list", "--reverse", "--first-parent", f"{c0}..{tip}").split()
    for c in later:
        env, msg = _meta(c)
        prev = commit_tree(tree_of(c), f"{msg}\n\nTrimmed-From: {c}", prev, env=env)
    if tree_of(prev) != tree_of(tip):
        raise RuntimeError("trimmed tip tree differs from the old tip")
    if int(git("rev-list", "--count", prev).strip()) != len(later) + 1:
        raise RuntimeError("trimmed history has the wrong number of commits")
    return prev, len(later) + 1


def _bundle_to_r2(tip: str, day: str) -> bool:
    from narrativ.appsync import R2S3
    r2 = R2S3.from_env()
    if r2 is None:
        print("[databranch] no Cloudflare credentials: the pre-trim history is not backed up")
        return False
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "data.bundle")
        git("bundle", "create", f, TRACK)
        st, _ = r2.put(f"{BUNDLE_PREFIX}{day}.bundle", Path(f).read_bytes(), ctype="application/octet-stream")
    base = datetime.fromisoformat(day).date()
    for i in range(10):  # older bundles past the window, by name (deletes are free; no listing)
        try:
            r2.delete(f"{BUNDLE_PREFIX}{base - timedelta(days=BUNDLE_KEEP_DAYS + 1 + i)}.bundle")
        except Exception:  # noqa: BLE001
            pass
    print(f"[databranch] history bundle to R2: http {st}")
    return st in (200, 201)


def trim(days: int = DAYS, test_ref: str | None = None, bundle: bool = True, tries: int = 3) -> int:
    if not test_ref and stage() < 4:
        print("[databranch] trim runs from stage 4 (DATA_STAGE); nothing done")
        return 0
    for i in range(tries):
        tip = fetch_tip(full=True)
        if tip is None:
            print(f"[databranch] no `{BRANCH}` branch")
            return 0
        new, n = rewrite(tip, days)
        if new is None:
            print(f"[databranch] nothing older than {days} days")
            return 0
        if bundle and not test_ref and not _bundle_to_r2(tip, datetime.now(timezone.utc).strftime("%Y-%m-%d")):
            print("::error::history bundle not stored in R2: not trimming")
            return 1
        if test_ref:  # a dry run: the result goes to its own ref, the data branch is not touched
            ref = f"refs/heads/{test_ref}"
            ok = subprocess.run(["git", *_auth(), "push", "-q", "-f", "origin", f"{new}:{ref}"], capture_output=True).returncode == 0
        else:
            ref = REF
            ok = push(new, tip, ref)  # force-with-lease: only when the branch is still at the tip this run rewrote
        if ok:
            print(f"[databranch] {ref}: trimmed to {n} commits (tip tree unchanged)")
            if not test_ref:
                after_push(new)
            return 0
        time.sleep(5)
    print("::error::trim: the branch kept moving (lease failed)")
    return 1


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m narrativ.databranch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("checkout")
    c.add_argument("--paths", nargs="*")
    c.add_argument("--force", action="store_true")
    c.add_argument("--even-if-tracked", action="store_true")
    m = sub.add_parser("commit")
    m.add_argument("-m", "--message", required=True)
    m.add_argument("--mine", default="docs/data/packs/")
    m.add_argument("--archive", action="store_true")
    m.add_argument("--no-picks", action="store_true")
    m.add_argument("paths", nargs="+")
    sub.add_parser("follow")
    r = sub.add_parser("resync")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--from", dest="frm", choices=["main"])
    g.add_argument("--to", choices=["main"])
    sub.add_parser("parity")
    b = sub.add_parser("bootstrap")
    b.add_argument("--force", action="store_true")
    t = sub.add_parser("trim")
    t.add_argument("--days", type=int, default=DAYS)
    t.add_argument("--test-ref")
    t.add_argument("--no-bundle", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "checkout":
        return checkout(a.paths, a.force, a.even_if_tracked)
    if a.cmd == "commit":
        return commit(a.message, a.paths, None if a.mine in ("", "none") else a.mine, a.archive, not a.no_picks)
    if a.cmd == "follow":
        return follow()
    if a.cmd == "resync":
        return resync("from-main" if a.frm else "to-main")
    if a.cmd == "parity":
        return parity()
    if a.cmd == "bootstrap":
        return bootstrap(force=a.force)
    return trim(a.days, a.test_ref, not a.no_bundle)


if __name__ == "__main__":
    sys.exit(main())
