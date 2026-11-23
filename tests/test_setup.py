import numpy as np
import pandas as pd

from narrativ import funnel as FN

T = {"stage": "Stage 2", "bands": {"trail": 1.0}}


def frame(closes):
    c = pd.Series(closes, dtype=float)
    idx = pd.bdate_range("2025-01-01", periods=len(c))
    return pd.DataFrame({"Close": c.values, "High": c.values + 1, "Low": c.values - 1}, index=idx)


def test_breakout_below_the_high_keeps_the_stop_under_the_price():
    # price 100 is 0.9x the 55-day high (111): the old stop (111 - 1.5 ATR = 108) sat above the price
    su = FN.setup(frame(list(np.linspace(50, 100, 240)) + [110] * 5 + [100] * 15), T, None)
    assert su["type"] == "Breakout" and su["lo"] == 111.0
    assert su["stop"] == 97.0 < 100  # anchored on the price: 100 - 1.5 x ATR 2


def test_breakout_above_the_high_keeps_its_stop_under_the_breakout_level():
    su = FN.setup(frame(list(np.linspace(50, 100, 240)) + [110] * 54 + [114]), T, None)
    assert su["type"] == "Breakout" and su["lo"] == 111.0  # price 114 broke out: stop as before, under the 55-day high
    assert su["stop"] < su["lo"] < 114


def test_no_live_setup_when_the_exit_level_is_above_the_price():
    # pullback to the 10-21 day averages, but the 50-day average (the stop) is still above the price
    su = FN.setup(frame([60] * 150 + [130] * 25 + [104] * 35), T, None)
    assert su["type"] == "No setup" and su["note"].startswith("Wait")
    assert "stop" not in su
