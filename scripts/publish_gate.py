"""Pre-publish sanity gate for data commits (owner, 26 Nov 2026: a failed or broken run must never publish partial data).

    git add -A docs/data data RULES.md
    python3 scripts/publish_gate.py        # exit 1: nothing is committed, the step fails visibly, the last data stays live

    python3 scripts/publish_gate.py --base <rev>   # the data branch (narrativ/databranch.py): its index via GIT_INDEX_FILE

Run after `git add` and before `git commit`: it checks the index (what would be committed) against the base (HEAD unless
--base; what is live). Refuses when
- docs/data/picks.json is missing, unparsable or holds no picks (`--no-picks` skips this for jobs that never write it), its
  date goes back against the base, or it shrinks by more than PICKS_SHRINK (50%);
- the number of JSON files under docs/data, docs/data/fin/, docs/data/charts/, docs/data/stocks/ or data/financials/ drops
  more than MAX_DROP (10%) against the base, or more than MAX_DROP of all files under docs/data and data are deleted;
- any added or changed .json under docs/data or data in the index does not parse.
Pure git + JSON, no network. A first commit (no base files) only checks parsing and picks.
"""
import json
import subprocess
import sys

MAX_DROP = 0.10
PICKS_SHRINK = 0.50
ROOTS = ("docs/data", "data")
DIRS = ("docs/data/", "docs/data/fin/", "docs/data/charts/", "docs/data/stocks/", "data/financials/")


def _git(*a: str) -> bytes:
    return subprocess.run(["git", *a], capture_output=True, check=True).stdout


def _json_paths(names: bytes) -> list[str]:
    return [p for p in names.decode("utf-8", "surrogateescape").split("\0") if p.endswith(".json")]


def counts(paths: list[str]) -> dict[str, int]:
    return {d: sum(1 for p in paths if p.startswith(d)) for d in DIRS}


def drops(before: dict[str, int], after: dict[str, int], max_drop: float = MAX_DROP) -> list[str]:
    """Folders whose JSON file count fell more than max_drop (a folder empty before is never a drop)."""
    out = []
    for d in DIRS:
        b, a = before.get(d, 0), after.get(d, 0)
        if b and a < b * (1 - max_drop):
            out.append(f"{d}: {a} files, was {b} (more than {max_drop:.0%} fewer)")
    return out


def bad_json(blobs: dict[str, bytes]) -> list[str]:
    out = []
    for p, raw in blobs.items():
        try:
            json.loads(raw)
        except ValueError as e:
            out.append(f"{p}: {str(e)[:80]}")
    return out


def picks_problem(raw: bytes | None, before: bytes | None = None) -> str | None:
    if raw is None:
        return "docs/data/picks.json is missing"
    try:
        p = json.loads(raw)
    except ValueError as e:
        return f"docs/data/picks.json does not parse: {str(e)[:80]}"
    if not isinstance(p, dict) or not p.get("picks"):
        return "docs/data/picks.json holds no picks"
    if before:
        try:
            b = json.loads(before)
        except ValueError:
            return None
        if str(p.get("date") or "") < str(b.get("date") or ""):
            return f"docs/data/picks.json date {p.get('date')} is older than the live {b.get('date')}"
        if len(raw) < len(before) * (1 - PICKS_SHRINK):
            return f"docs/data/picks.json is {len(raw) / 1e6:.2f} MB, was {len(before) / 1e6:.2f} MB (more than {PICKS_SHRINK:.0%} smaller)"
    return None


def deleted_problem(live_all: list[str], staged_all: list[str], max_drop: float = MAX_DROP) -> str | None:
    gone = len(set(live_all) - set(staged_all))
    if live_all and gone > len(live_all) * max_drop:
        return f"{gone} of {len(live_all)} files under {' and '.join(ROOTS)} would be deleted (more than {max_drop:.0%})"
    return None


def _names(raw: bytes) -> list[str]:
    return [p for p in raw.decode("utf-8", "surrogateescape").split("\0") if p]


def main(argv: list[str]) -> int:
    base = argv[argv.index("--base") + 1] if "--base" in argv else "HEAD"
    staged_all = _names(_git("ls-files", "-z", "--", *ROOTS))
    staged = [p for p in staged_all if p.endswith(".json")]
    try:
        live_all = _names(_git("ls-tree", "-r", "-z", "--name-only", base, "--", *ROOTS))
    except subprocess.CalledProcessError:
        live_all = []
    live = [p for p in live_all if p.endswith(".json")]
    problems = drops(counts(live), counts(staged))
    dp = deleted_problem(live_all, staged_all)
    if dp:
        problems.append(dp)
    changed = _json_paths(_git("diff-index", "--cached", "-z", "--name-only", "--diff-filter=AM", base, "--", *ROOTS)) if live_all else staged
    blobs = {}
    for p in changed:
        try:
            blobs[p] = _git("show", f":{p}")
        except subprocess.CalledProcessError:
            problems.append(f"{p}: not readable from the index")
    problems += bad_json(blobs)
    if "--no-picks" not in argv:
        try:
            raw = _git("show", ":docs/data/picks.json")
        except subprocess.CalledProcessError:
            raw = None
        try:
            before = _git("show", f"{base}:docs/data/picks.json")
        except subprocess.CalledProcessError:
            before = None
        pp = picks_problem(raw, before)
        if pp:
            problems.append(pp)
    if problems:
        print("Publish gate: NOT publishing; the last published data stays live.")
        for x in problems:
            print("  - " + x)
        return 1
    print(f"Publish gate: ok ({len(staged)} JSON files under docs/data and data, {len(changed)} changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
