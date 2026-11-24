import json

import numpy as np
import pandas as pd

from narrativ import breadth as BR


def _px(trend, n=320, start=100.0):
    idx = pd.bdate_range("2025-06-02", periods=n)
    c = pd.Series(start * np.cumprod(np.full(n, 1 + trend)), index=idx)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1000.0})


def _setup(tmp_path):
    cl = {f"INE{k}": {"s": sec, "i": ind, "b": ind + " basic"} for k, sec, ind in
          [("UP1", "Up", "Rising"), ("UP2", "Up", "Rising"), ("UP3", "Up", "Rising"),
           ("DN1", "Down", "Falling"), ("DN2", "Down", "Falling"), ("DN3", "Down", "Falling"), ("SOLO", "Solo", "Alone")]}
    p = tmp_path / "classification.json"
    p.write_text(json.dumps(cl))
    px = {f"{k}.NS": _px(0.004 if k.startswith("UP") else -0.004) for k in ("UP1", "UP2", "UP3", "DN1", "DN2", "DN3", "SOLO")}
    isin = {s: "INE" + s[:-3] for s in px}
    return px, isin, p


def test_rows_equal_weighted(tmp_path):
    px, isin, p = _setup(tmp_path)
    grp = BR.groups(isin, p)
    fl, close = BR.flags(px)
    rows = BR.rows_for([close.index[-1]], fl, close, grp, {s: 1000.0 for s in px}, {s: 70 for s in px})
    by = {(r[1], r[2]): dict(zip(BR.COLS, r)) for r in rows}
    up, dn = by[("sector", "Up")], by[("sector", "Down")]
    assert up["n"] == 3 and up["mcap_cr"] == 3000.0 and up["momentum"] == 70
    for k in ("above20", "above50", "above200", "golden", "day_up", "week_up", "rsi50"):
        assert up[k] == 100.0 and dn[k] == 0.0, k
    assert ("sector", "Solo") not in by  # fewer than MIN_STOCKS
    assert {r[1] for r in rows} == {"sector", "industry", "basic_industry"}


def test_sma200_needs_history(tmp_path):
    px, isin, p = _setup(tmp_path)
    fl, close = BR.flags(px)
    early = BR.rows_for([close.index[100]], fl, close, BR.groups(isin, p), {})
    up = next(dict(zip(BR.COLS, r)) for r in early if r[2] == "Up")
    assert up["above200"] is None and up["golden"] is None and up["above50"] == 100.0
    assert up["momentum"] is None and up["mcap_cr"] is None


def test_backfill_dates_daily_then_weekly():
    idx = pd.bdate_range("2023-01-02", periods=BR.BACKFILL_DAILY + 60)
    want = BR.backfill_dates(idx, set())
    assert want[0] == idx[-2]  # newest past day first; today is the daily step's
    assert len([d for d in want if d >= idx[-BR.BACKFILL_DAILY - 1]]) == BR.BACKFILL_DAILY
    older = [d for d in want if d < idx[-BR.BACKFILL_DAILY - 1]]
    assert 10 <= len(older) <= 13 and len({d.to_period("W") for d in older}) == len(older)
    assert str(idx[-2].date()) not in {str(d.date()) for d in BR.backfill_dates(idx, {str(idx[-2].date())})}


class FakeStore:
    def __init__(self):
        self.rows = {}

    def upsert(self, table, cols, rows, keys, **_):
        for r in rows:
            self.rows[(r[0], r[1], r[2])] = r
        return len(rows)

    def q(self, sql, params=None):
        return [{"date": d} for d in sorted({k[0] for k in self.rows})]


def test_sync_today_and_budget(tmp_path, monkeypatch):
    px, isin, p = _setup(tmp_path)
    real = BR.groups
    monkeypatch.setattr(BR, "groups", lambda i: real(i, p))
    monkeypatch.setattr(BR, "BACKFILL_BUDGET", 60)
    st = FakeStore()
    last = px["UP1.NS"].index[-1].date()
    r = BR.sync(st, last, px, isin, {}, {})
    assert r["today"] == 6 and r["backfill_days"] == 10 and r["backfill_rows"] == 60 and r["days_left"] > 0
    assert any(k[0] == str(last) for k in st.rows)
    r2 = BR.sync(st, last, px, isin, {}, {})
    assert r2["backfill_days"] == 10 and r2["days_left"] == r["days_left"] - 10
