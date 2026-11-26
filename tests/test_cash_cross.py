"""Feedback #155 (cash statement) and #170 (50/200-day cross), owner 26 Nov 2026."""
import json

import numpy as np
import pandas as pd

from narrativ.story import cash_position
from narrativ.technicals import ma_cross


def _fin(tmp_path, q):
    (tmp_path / "X.NS.json").write_text(json.dumps({"quarters": q}))
    return tmp_path


def test_cash_with_year_ago_and_borrowings(tmp_path):
    q = {"2025-09-30": {"Consolidated": {"bs": {"cash": 18854e6, "bank_bal": 6841e6, "borr_total": 79411e6}}},
         "2026-09-30": {"Consolidated": {"bs": {"cash": 17856e6, "bank_bal": 6999e6, "borr_total": 92846e6}}}}
    t = cash_position("X.NS", _fin(tmp_path, q))
    assert t.startswith("On 30 Sep 2026, cash and bank balances were ₹2,486 cr, 3% lower than a year earlier")
    assert "borrowings rose 17% to ₹9,285 cr" in t and "covers 27% of them, down from 32%" in t


def test_cash_without_borrowings_or_history(tmp_path):
    q = {"2026-09-30": {"Standalone": {"bs": {"cash": 50e7, "borr_total": 0}}}}
    assert cash_position("X.NS", _fin(tmp_path, q)) == "On 30 Sep 2026, cash and bank balances were ₹50 cr; no borrowings."
    assert cash_position("Y.NS", tmp_path) is None


def test_ma_cross_golden():
    c = pd.Series(np.r_[np.linspace(100, 60, 300), np.linspace(60, 140, 120)])
    above, days = ma_cross(c)
    assert above == 1 and days is not None and days < 120


def test_ma_cross_needs_200_days():
    assert ma_cross(pd.Series(np.linspace(1, 2, 100))) is None
