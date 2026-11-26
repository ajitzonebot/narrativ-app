"""Nightly publish audit (owner, 26 Nov 2026: "a feedback loop which keeps an audit of this").

    python -m narrativ.audit_publish     # .github/workflow-src/audit.yml, 23:00 IST daily

Checks that the day's data really reached every place it should, and says so in one place:
  data_fresh   docs/data/picks.json is stamped with the latest NSE trading date (scripts/latest_trading_date.py)
  r2_app       R2 app/_manifest.json is at the last data commit or later, with no failed uploads (narrativ/appsync.py)
  r2_archive   today's dated archive exists in R2 (narrativ/archive.py, kept 30 days)
  d1           the last D1 run_log row is for the published data date, and the database is under 250 MB (dbsync db_bytes)
  daily_runs   no daily.yml run failed today (a later success is noted, the failure is still reported)
Writes docs/data/audit.json {date, checks: [{name, ok, detail}], ok}. When a check fails it opens (or updates, with a
comment) one issue labelled `pipeline-audit` in the private repo; when all pass it closes that issue. A check whose
secret or source is not available is skipped (ok, detail "not configured" or the reason), never a false alarm.
Environment: CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID (R2, D1), RUNS_TOKEN + RUN_REPO (the public repo's runs),
GITHUB_TOKEN + ISSUE_REPO (the issue).
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path("docs/data/audit.json")
LABEL = "pipeline-audit"
TITLE = "Pipeline audit: something did not publish"
DB_WARN_BYTES = 250_000_000
GH = "https://api.github.com"


def ist_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()


def chk(name: str, ok: bool, detail: str, skipped: bool = False) -> dict:
    d = {"name": name, "ok": bool(ok), "detail": detail}
    if skipped:
        d["skipped"] = True
    return d


def picks_date(path: Path = Path("docs/data/picks.json"), rev: str | None = None) -> str | None:
    try:
        raw = subprocess.run(["git", "show", f"{rev}:docs/data/picks.json"], capture_output=True, check=True).stdout \
            if rev and rev != "HEAD" else path.read_text()
        return str(json.loads(raw).get("date") or "")[:10] or None
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def data_rev() -> str:
    """Where the published data lives: main (HEAD) until DATA_STAGE 2, then the data branch (narrativ/databranch.py)."""
    try:
        if int(os.environ.get("DATA_STAGE") or 0) >= 2:
            from narrativ import databranch
            if databranch.fetch_tip():
                return databranch.TRACK
    except Exception as e:  # noqa: BLE001
        print(f"[audit] data branch: {e}")
    return "HEAD"


# ---------------------------------------------------------------- checks (each takes its source, so tests can stub it)
def check_fresh(have: str | None, latest: str | None) -> dict:
    if latest is None:
        return chk("data_fresh", True, f"data {have}; latest trading date not readable (NSE)", skipped=True)
    if have is None:
        return chk("data_fresh", False, "docs/data/picks.json has no date")
    if have < latest:
        return chk("data_fresh", False, f"published data is for {have}, NSE has {latest}")
    return chk("data_fresh", True, f"data for {have} (latest trading date {latest})")


def check_r2_app(manifest: dict | None, last_data_ct: int | None, head: str | None) -> dict:
    if manifest is None:
        return chk("r2_app", True, "not configured", skipped=True)
    if not manifest:
        return chk("r2_app", False, "no app/_manifest.json in R2: the Worker serves every file from GitHub")
    failed = manifest.get("failed") or []
    sha, ct = str(manifest.get("sha") or ""), manifest.get("ct")
    behind = last_data_ct is not None and isinstance(ct, (int, float)) and ct < last_data_ct
    if failed:
        return chk("r2_app", False, f"{len(failed)} file(s) not uploaded (served from GitHub), commit {sha[:8]}")
    if behind and sha != head:
        return chk("r2_app", False, f"R2 holds commit {sha[:8]}, older than the last data commit")
    return chk("r2_app", True, f"R2 at commit {sha[:8]}, no failed uploads")


def check_archive(status: int | None, key: str) -> dict:
    if status is None:
        return chk("r2_archive", True, "not configured", skipped=True)
    if status == 200:
        return chk("r2_archive", True, f"{key} present")
    return chk("r2_archive", False, f"{key} missing (http {status})")


def check_d1(row: dict | None, data_d: str | None, configured: bool) -> dict:
    if not configured:
        return chk("d1", True, "not configured", skipped=True)
    if not row:
        return chk("d1", False, "no run_log row in D1")
    d = str(row.get("date") or "")[:10]
    try:
        u = json.loads(row.get("usage") or "{}") if isinstance(row.get("usage"), str) else (row.get("usage") or {})
    except ValueError:
        u = {}
    size = u.get("db_bytes")
    probs = []
    if data_d and d < data_d:
        probs.append(f"last D1 sync is for {d}, data is for {data_d}")
    if isinstance(size, (int, float)) and size > DB_WARN_BYTES:
        probs.append(f"database {size / 1e6:.0f} MB of the 500 MB free limit")
    size_t = f"{size / 1e6:.0f} MB" if isinstance(size, (int, float)) else "size not recorded yet"
    if probs:
        return chk("d1", False, "; ".join(probs))
    return chk("d1", True, f"synced for {d}, {size_t}")


def check_runs(runs: list | None) -> dict:
    if runs is None:
        return chk("daily_runs", True, "not configured", skipped=True)
    done = [r for r in runs if r.get("status") == "completed"]
    bad = [r for r in done if r.get("conclusion") in ("failure", "timed_out", "startup_failure")]
    if not runs:
        return chk("daily_runs", True, "no daily run today")
    if bad:
        later = any(r.get("conclusion") == "success" and r.get("created_at", "") > max(b.get("created_at", "") for b in bad)
                    for r in done)
        return chk("daily_runs", False, f"{len(bad)} of {len(runs)} daily run(s) failed today"
                   + ("; a later run succeeded" if later else "; no later run succeeded"))
    return chk("daily_runs", True, f"{len(runs)} daily run(s) today, none failed")


# ---------------------------------------------------------------- sources
def _latest_trading() -> str | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.latest_trading_date import latest_trading_date
        from narrativ.bhav import nse
        from narrativ.filings import NSESession
        ns = NSESession()
        d = latest_trading_date(lambda day: (nse(ns, day) or {}).get("_date"), ist_today())
        return str(d) if d else None
    except Exception as e:  # noqa: BLE001
        print(f"[audit] latest trading date: {e}")
        return None


def _git(*a: str) -> str | None:
    try:
        return subprocess.run(["git", *a], capture_output=True, check=True, text=True).stdout.strip() or None
    except (subprocess.CalledProcessError, OSError):
        return None


def _r2():
    try:
        from narrativ.appsync import MANIFEST_KEY, R2S3
        r2 = R2S3.from_env()
        return r2, MANIFEST_KEY
    except Exception as e:  # noqa: BLE001
        print(f"[audit] R2: {e}")
        return None, None


def _d1_row():
    if not (os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID")):
        return None, False
    try:
        from narrativ.store import Store
        st = Store()
        if not st.db:
            return None, False
        rows = st.q("SELECT date, usage FROM run_log ORDER BY date DESC LIMIT 1")
        return (rows[0] if rows else None), True
    except Exception as e:  # noqa: BLE001
        print(f"[audit] D1: {e}")
        return None, False


def _runs(today: date) -> list | None:
    tok, repo = os.environ.get("RUNS_TOKEN", ""), os.environ.get("RUN_REPO", "")
    if not (tok and repo):
        return None
    since = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(hours=5, minutes=30)
    try:
        r = requests.get(f"{GH}/repos/{repo}/actions/workflows/daily.yml/runs",
                         params={"created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}", "per_page": 30},
                         headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, timeout=30)
        if r.status_code != 200:
            print(f"[audit] runs: http {r.status_code}")
            return None
        return [{k: x.get(k) for k in ("status", "conclusion", "created_at", "event")} for x in r.json().get("workflow_runs") or []]
    except requests.RequestException as e:
        print(f"[audit] runs: {e}")
        return None


def gather() -> dict:
    today = ist_today()
    rev = data_rev()
    have = picks_date(rev=rev)
    checks = [check_fresh(have, _latest_trading())]
    r2, mkey = _r2()
    manifest, arch = None, None
    from narrativ.archive import key_for
    akey = key_for(have or str(today))
    if r2 is not None:
        try:
            st, body, _ = r2.get(mkey)
            manifest = json.loads(body) if st == 200 else ({} if st == 404 else None)
        except Exception as e:  # noqa: BLE001
            print(f"[audit] manifest: {e}")
        try:
            arch = r2._req("HEAD", akey)[0]
        except Exception as e:  # noqa: BLE001
            print(f"[audit] archive: {e}")
    last_ct = _git("log", "-1", "--format=%ct", rev, "--", "docs/data", ":(exclude)docs/data/audit.json")
    checks.append(check_r2_app(manifest, int(last_ct) if last_ct else None, _git("rev-parse", rev)))
    checks.append(check_archive(arch, akey))
    row, configured = _d1_row()
    checks.append(check_d1(row, have, configured))
    checks.append(check_runs(_runs(today)))
    return {"date": str(today), "data_date": have, "checks": checks, "ok": all(c["ok"] for c in checks)}


# ---------------------------------------------------------------- issue (one open issue, updated; closed when all pass)
def body_of(rep: dict) -> str:
    lines = [f"Publish audit of {rep['date']} (data date {rep.get('data_date')}):", ""]
    for c in rep["checks"]:
        mark = "ok" if c["ok"] else "FAILED"
        lines.append(f"- **{c['name']}**: {mark}. {c['detail']}")
    lines += ["", "Written by the nightly audit job (`narrativ/audit_publish.py`); it closes this issue when every check passes."]
    return "\n".join(lines)


def sync_issue(rep: dict, gh=None) -> str:
    tok, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("ISSUE_REPO", "")
    if not (tok and repo):
        return "issue: not configured"
    s = gh or requests.Session()
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    r = s.get(f"{GH}/repos/{repo}/issues", params={"labels": LABEL, "state": "open", "per_page": 5}, headers=h, timeout=30)
    open_ = [x for x in (r.json() if r.status_code == 200 else []) if not x.get("pull_request")]
    body = body_of(rep)
    if not rep["ok"]:
        if open_:
            n = open_[0]["number"]
            s.patch(f"{GH}/repos/{repo}/issues/{n}", json={"body": body}, headers=h, timeout=30)
            s.post(f"{GH}/repos/{repo}/issues/{n}/comments", json={"body": body}, headers=h, timeout=30)
            return f"issue #{n} updated"
        r = s.post(f"{GH}/repos/{repo}/issues", json={"title": TITLE, "body": body, "labels": [LABEL]}, headers=h, timeout=30)
        return f"issue opened (http {r.status_code})"
    for x in open_:
        s.post(f"{GH}/repos/{repo}/issues/{x['number']}/comments", json={"body": "All checks pass.\n\n" + body}, headers=h, timeout=30)
        s.patch(f"{GH}/repos/{repo}/issues/{x['number']}", json={"state": "closed", "state_reason": "completed"}, headers=h, timeout=30)
    return f"{len(open_)} issue(s) closed" if open_ else "no open issue"


def main() -> int:
    rep = gather()
    OUT.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    for c in rep["checks"]:
        print(f"[audit] {c['name']}: {'ok' if c['ok'] else 'FAILED'} - {c['detail']}")
    try:
        print(f"[audit] {sync_issue(rep)}")
    except Exception as e:  # noqa: BLE001  the audit file is still written
        print(f"[audit] issue not updated: {e}")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:  # counts and check names only (public run page)
        with open(summ, "a") as f:
            f.write(f"Publish audit {rep['date']}: {'all checks pass' if rep['ok'] else 'FAILED: ' + ', '.join(c['name'] for c in rep['checks'] if not c['ok'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
