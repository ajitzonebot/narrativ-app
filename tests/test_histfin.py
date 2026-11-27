"""History backfill (narrativ/histfin.py): an empty NSE listing or a failed download is retried, not marked done."""
from narrativ import histfin as H


class _NS:
    calls = 0

    def __init__(self, rows=None, text=None):
        self.rows, self.text = rows, text

    def get(self, url, params=None, as_json=True, tries=3):
        return self.text


def _patch(monkeypatch, tmp_path, rows, live=None):
    monkeypatch.setattr(H, "DIR", tmp_path)
    monkeypatch.setattr(H.F, "_listings", lambda ns, code, index="equities": rows)
    monkeypatch.setattr(H.F, "load", lambda sym: live or {})
    monkeypatch.setattr(H.config, "FILINGS_SLEEP_SEC", 0)


def test_empty_listing_is_retried(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, [])
    rec = H.backfill("ABC.NS", _NS())
    assert rec["done"] is None and rec["status"] == "listing empty (retry)"


def test_empty_listing_final_when_daily_store_agrees(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, [], live={"status": "no NSE filings"})
    assert H.backfill("ABC.NS", _NS())["done"] == H.VERSION


def test_failed_download_is_retried(monkeypatch, tmp_path):
    rows = [{"qe": "2020-03-31", "basis": "Standalone", "url": "https://x/a.xml", "filed": "2020-06-01", "src": "s", "audited": None}]
    _patch(monkeypatch, tmp_path, rows, live={"basis": "Standalone", "quarters": {}})
    rec = H.backfill("ABC.NS", _NS(text=None))
    assert rec["done"] is None and "not downloaded" in rec["status"]


def test_old_quarters_skipped(monkeypatch, tmp_path):
    rows = [{"qe": "2018-03-31", "basis": "Standalone", "url": "https://x/a.xml", "filed": "2018-06-01", "src": "s", "audited": None}]
    _patch(monkeypatch, tmp_path, rows, live={"basis": "Standalone", "quarters": {}})
    rec = H.backfill("ABC.NS", _NS(text=None))
    assert rec["done"] == H.VERSION and rec["quarters"] == {}
