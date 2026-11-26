"""Option C (owner, 26 Nov 2026): the Buy-tracking portfolio sizes each call by its conviction at entry."""
import pandas as pd

from narrativ.calls import daily_returns


def test_size_weighted_by_conviction():
    idx = pd.to_datetime(["2026-11-02", "2026-11-03"])
    px = {"A.NS": pd.DataFrame({"Close": [100.0, 110.0]}, index=idx), "B.NS": pd.DataFrame({"Close": [100.0, 90.0]}, index=idx)}
    calls = [{"kind": "verified", "symbol": "A.NS", "date": "2026-11-02", "price": 100.0, "conviction": "high"},
             {"kind": "verified", "symbol": "B.NS", "date": "2026-11-02", "price": 100.0, "conviction": "low"}]
    port, _ = daily_returns(calls, px, pd.Series([1.0, 1.0], index=idx))
    # +10% at full size, -10% at a quarter: (0.10 * 1 - 0.10 * 0.25) / 1.25 = +6%
    assert abs(port.iloc[-1] - 0.06) < 1e-9
