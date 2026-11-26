"""Feedback #155 (cash statement) and #170 (50/200-day cross), owner 26 Nov 2026."""
import json

import numpy as np
import pandas as pd

from narrativ.story import cash_position
from narrativ.technicals import ma_cross


def _fin(tmp_path, q):
    for bases in q.values():  # metrics.series keeps quarters with a revenue line
        for p in bases.values():
            p.setdefault("q", {"rev": 1e9})
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


def test_lender_has_no_coverage_clause_and_indian_grouping(tmp_path):
    from narrativ.story import inr
    q = {"2025-09-30": {"Consolidated": {"bs": {"cash": 1e10, "borr_total": 1.0e12}}},
         "2026-09-30": {"Consolidated": {"bs": {"cash": 1e10, "borr_total": 1.3075e12}}}}
    t = cash_position("X.NS", _fin(tmp_path, q), lender=True)
    assert "covers" not in t and "₹1,30,750 cr" in t
    assert inr(12345678) == "1,23,45,678"


def test_year_ago_from_the_same_accounts(tmp_path):
    q = {"2025-09-30": {"Standalone": {"bs": {"cash": 5e9}}},
         "2026-09-30": {"Consolidated": {"bs": {"cash": 1e10}}}}
    assert "a year earlier" not in cash_position("X.NS", _fin(tmp_path, q))


def test_cash_uses_the_unit_corrected_series(tmp_path):
    # a quarter filed 100x too small (crore figures under a "Lakhs" label, METROBRAND Sep-2025): corrected before comparing
    def p(rev, cash, cap, rnd="Crores"):
        return {"Consolidated": {"q": {"rev": rev, "exp": rev * 0.8, "pat": rev * 0.1, "share_cap": cap}, "bs": {"cash": cash}, "rounding": rnd}}
    q = {"2025-03-31": p(1e10, 4e8, 1e8), "2025-06-30": p(1e10, 4e8, 1e8), "2025-09-30": p(1e8, 4e6, 1e6, "Lakhs"),
         "2025-12-31": p(1e10, 4e8, 1e8), "2026-03-31": p(1e10, 4e8, 1e8), "2026-06-30": p(1e10, 4e8, 1e8), "2026-09-30": p(1e10, 4.2e8, 1e8)}
    t = cash_position("X.NS", _fin(tmp_path, q))
    assert "₹42 cr" in t and "5% higher than a year earlier" in t
