"""NSE trading holidays (equity segment) from the exchange's own holiday master -> docs/data/holidays.json.

Output: {"source": url, "updated": "YYYY-MM-DD", "trading_holidays": ["YYYY-MM-DD", ...]}. Only dates NSE publishes are
written, never inferred ones. NSE lists one calendar year at a time (the next year appears around December), so dates
already stored for other years are kept: the file grows into a multi-year list as the daily run sees each year's master.
Any fetch failure leaves the file as it is.
"""
import json
from datetime import date, datetime
from pathlib import Path

URL = "https://www.nseindia.com/api/holiday-master?type=trading"
OUT = Path("docs/data/holidays.json")
SEGMENT = "CM"  # capital market (equities); other keys are F&O, currency, commodity, debt ...


def parse(payload: dict, segment: str = SEGMENT) -> list[str]:
    """NSE holiday-master JSON -> sorted ISO dates for one segment. Rows whose date cannot be read are skipped."""
    out = set()
    for row in (payload or {}).get(segment) or []:
        s = str((row or {}).get("tradingDate") or "").strip()
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
            try:
                out.add(datetime.strptime(s.title() if fmt != "%Y-%m-%d" else s, fmt).date().isoformat())
                break
            except ValueError:
                continue
    return sorted(out)


def merge(old: list[str], new: list[str]) -> list[str]:
    """New dates replace old ones for every year the new list covers (a holiday NSE moved or dropped goes away);
    years the new list does not cover keep their stored dates."""
    years = {d[:4] for d in new}
    return sorted({d for d in old if d[:4] not in years} | set(new))


def update(today: date | None = None, session=None, out: Path = OUT) -> dict | None:
    """Fetch, merge and write. Returns the written record, or None when nothing could be fetched (file untouched)."""
    today = today or date.today()
    try:
        if session is None:
            from .filings import NSESession
            session = NSESession()
        new = parse(session.get(URL) or {})
    except Exception as e:  # noqa: BLE001
        print(f"[holidays] fetch failed: {e}")
        return None
    if not new:
        print("[holidays] NSE holiday master empty or unreachable: file left as it is")
        return None
    old = []
    if out.exists():
        try:
            old = json.loads(out.read_text()).get("trading_holidays") or []
        except (ValueError, OSError):
            old = []
    rec = {"source": URL, "updated": str(today), "trading_holidays": merge(old, new)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    print(f"[holidays] {len(rec['trading_holidays'])} NSE trading holidays ({', '.join(sorted({d[:4] for d in rec['trading_holidays']}))})")
    return rec


if __name__ == "__main__":
    update()
