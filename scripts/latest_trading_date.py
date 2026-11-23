"""Print the latest NSE trading date (YYYY-MM-DD) whose end-of-day file is published, or nothing when it cannot be told.

Used by .github/workflows/daily.yml to decide whether a scheduled run has anything new to build: if this date equals the date
already in docs/data/picks.json (which run.py stamps with the last price date, not the IST calendar day), the rerun is skipped.
The date comes from the file itself ("DATE1" column, see narrativ/bhav.py), never from the file name: on a holiday NSE can
serve the previous day's file. Probes today (IST) and the previous days, newest first. Any failure prints nothing, so the
workflow runs normally (fails open)."""
import sys
from datetime import date, datetime, timedelta, timezone

LOOKBACK_DAYS = 7


def parse_date(x) -> date | None:
    for f in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(x).strip().title(), f).date()
        except ValueError:
            continue
    return None


def latest_trading_date(probe, today: date) -> date | None:
    """probe(day) -> the "_date" string printed in that day's exchange file, or None when not published / failed."""
    best = None
    for i in range(LOOKBACK_DAYS + 1):
        td = parse_date(probe(today - timedelta(days=i)))
        if td and td <= today and (best is None or td > best):
            best = td
        if best:  # newest published file found; older files can only hold older dates
            break
    return best


def main() -> None:
    from narrativ.bhav import nse
    from narrativ.filings import NSESession
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    ns = NSESession()
    d = latest_trading_date(lambda day: (nse(ns, day) or {}).get("_date"), today)
    if d:
        print(d)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"latest_trading_date failed: {e}", file=sys.stderr)
