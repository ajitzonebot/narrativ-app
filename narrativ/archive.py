"""Daily archive of the published app data in R2 (owner, 26 Nov 2026: keep 30 days outside git as a restore point).

    python -m narrativ.archive [--rev <commit>]   # after a successful daily push (push_retry.sh with ARCHIVE_R2=1, or
                                                  # narrativ/databranch.py commit --archive); never fatal

One object a day: R2 `archive/data-<data date>.tar.gz` = `git archive <rev> docs/data data` (the app data AND the run's
state stores: filings, reader store, D1 manifest, analyst targets ...), gzip, from the pushed commit (never the work tree),
so it holds exactly what was published and everything needed to rebuild the next run. One PUT a day (Class A). Archives more than KEEP_DAYS days
older than the data date are deleted by name (deletes are free on R2; no bucket listing, which would be Class A): each
run deletes the PRUNE_SPAN dated keys just past the window, so a missed day is caught by the next runs.

Restore: download the object, `tar -xzf data-<date>.tar.gz` (it unpacks to docs/data/ and data/).
"""
import gzip
import json
import subprocess
import sys
from datetime import date, timedelta

from narrativ.appsync import R2S3

PREFIX = "archive/data-"
ROOTS = ("docs/data", "data")
KEEP_DAYS = 30
PRUNE_SPAN = 15  # dated keys checked past the window each run


def key_for(d: str) -> str:
    return f"{PREFIX}{d}.tar.gz"


def data_date(rev: str = "HEAD") -> str | None:
    """The data date stamped in the published picks.json (the last price date, not the calendar day)."""
    try:
        raw = subprocess.run(["git", "show", f"{rev}:docs/data/picks.json"], capture_output=True, check=True).stdout
        d = json.loads(raw).get("date")
        return str(date.fromisoformat(str(d)[:10])) if d else None
    except (subprocess.CalledProcessError, ValueError, TypeError):
        return None


def build(rev: str = "HEAD") -> bytes:
    have = [r for r in ROOTS if subprocess.run(["git", "cat-file", "-e", f"{rev}:{r}"], capture_output=True).returncode == 0]
    tar = subprocess.run(["git", "archive", "--format=tar", rev, *have], capture_output=True, check=True).stdout
    return gzip.compress(tar, compresslevel=6, mtime=0)


def prune_keys(d: str, keep: int = KEEP_DAYS, span: int = PRUNE_SPAN) -> list[str]:
    day = date.fromisoformat(d)
    return [key_for(str(day - timedelta(days=keep + 1 + i))) for i in range(span)]


def run(r2=None, rev: str = "HEAD") -> dict:
    r2 = r2 or R2S3.from_env()
    if r2 is None:
        print("[archive] no Cloudflare credentials; skipped")
        return {"ok": False, "why": "no credentials"}
    d = data_date(rev)
    if not d:
        print("[archive] no data date in docs/data/picks.json; skipped")
        return {"ok": False, "why": "no data date"}
    blob = build(rev)
    st, _ = r2.put(key_for(d), blob, ctype="application/gzip")
    ok = st in (200, 201)
    for k in prune_keys(d):  # R2 answers 204 whether or not the key existed
        try:
            r2.delete(k)
        except Exception:  # noqa: BLE001
            pass
    print(f"[archive] {key_for(d)}: http {st}, {len(blob) / 1e6:.1f} MB; archives older than {KEEP_DAYS} days removed")
    return {"ok": ok, "key": key_for(d), "bytes": len(blob), "status": st}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rev = argv[argv.index("--rev") + 1] if "--rev" in argv else "HEAD"
    try:
        run(rev=rev)
    except Exception as e:  # noqa: BLE001  never fails the step
        print(f"[archive] failed: {type(e).__name__}: {str(e)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
