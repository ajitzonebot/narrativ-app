import subprocess
from datetime import date
from pathlib import Path

from scripts.latest_trading_date import latest_trading_date, parse_date


def test_parse_date_formats():
    assert parse_date("19-Nov-2026") == date(2026, 11, 19)
    assert parse_date("19-NOV-2026") == date(2026, 11, 19)
    assert parse_date("2026-11-19") == date(2026, 11, 19)
    assert parse_date("junk") is None and parse_date(None) is None


def test_latest_is_todays_file_when_published():
    files = {date(2026, 11, 20): "20-Nov-2026", date(2026, 11, 19): "19-Nov-2026"}
    assert latest_trading_date(files.get, date(2026, 11, 20)) == date(2026, 11, 20)


def test_backup_run_after_midnight_ist_sees_previous_trading_day():
    # 21 Nov 2026 (Saturday) 01:10 IST: no file for the 21st or 20th-night; the 20th's file is the newest
    files = {date(2026, 11, 20): "20-Nov-2026"}
    assert latest_trading_date(files.get, date(2026, 11, 21)) == date(2026, 11, 20)


def test_holiday_file_that_repeats_the_previous_day_uses_the_printed_date():
    files = {date(2026, 11, 23): "20-Nov-2026"}  # served on a holiday, printed with the earlier trading date
    assert latest_trading_date(files.get, date(2026, 11, 23)) == date(2026, 11, 20)


def test_nothing_published_or_probe_failure_returns_none():
    assert latest_trading_date(lambda d: None, date(2026, 11, 20)) is None


def test_future_dated_file_is_ignored():
    assert latest_trading_date(lambda d: "25-Nov-2026", date(2026, 11, 20)) is None


def test_push_retry_script_exits_1_and_leaves_no_rebase(tmp_path):
    """No remote: every attempt fails; the script must abort the rebase and exit non-zero."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "push_retry.sh"
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
    fast = script.read_text().replace("sleep 5", "sleep 0")
    fast_path = tmp_path / "push_retry_fast.sh"
    fast_path.write_text(fast)
    r = subprocess.run(["bash", str(fast_path)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode == 1
    assert "failed after 3 attempts" in r.stdout
    assert not (tmp_path / ".git" / "rebase-merge").exists()
