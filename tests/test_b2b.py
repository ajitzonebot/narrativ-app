from datetime import date

from narrativ import orders as ORD

T = date(2026, 11, 23)


def _row(d, txt):
    return [d, "Bagging/Receiving of orders/contracts", txt, f"https://x/{d}"]


def test_b2b_proves_above_one():
    rows = [_row("2026-10-01", "Company has received an order worth Rs 600 crore"), _row("2026-03-01", "Secured a contract of ₹500 crore")]
    st, val, note, url = ORD.b2b(rows, 1000.0, T, True)
    assert st is True and "1.10×" in val and url


def test_b2b_cannot_prove_below_one():
    st, val, note, _ = ORD.b2b([_row("2026-10-01", "received an order worth Rs 200 crore")], 1000.0, T, True)
    assert st is None and "0.20×" in val and "cannot show" in note


def test_b2b_not_applicable_outside_order_industries():
    assert ORD.b2b([], 1000.0, T, False)[2] == "not applicable"
    assert ORD.b2b([], 1000.0, T, True)[2] == "no order announcement in 12 months"
    old = [_row("2025-06-01", "received an order worth Rs 5,000 crore")]
    assert ORD.b2b(old, 1000.0, T, True)[0] is None  # older than 12 months
