"""Feedback #113: the story's "How it's going" adds cash conversion (the Quality tab's figure); none for lenders."""
from narrativ.story import going


def test_cash_conversion_added():
    g = going({"rev_yoy_pct": {"v": 19.8}, "pat_yoy_pct": {"v": 231}, "cfo_to_ebitda_pct": {"v": 61, "exact": 61.2, "in": {"years": 3}}})
    assert g["text"].endswith("Most of the profit turns into cash: 61% cash conversion over 3 years (cash from operations ÷ operating profit).")


def test_no_cash_line_when_not_meaningful():
    g = going({"rev_yoy_pct": {"v": -5}, "cfo_to_ebitda_pct": {"nm": True, "v": None}})
    assert "cash" not in g["text"]
