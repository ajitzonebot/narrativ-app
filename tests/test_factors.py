import pandas as pd

from narrativ.factors import measure


def test_ic_positive_when_score_predicts_next_return():
    dates = [f"2026-11-{d:02d}" for d in range(1, 5)]
    stocks = [f"S{i}" for i in range(40)]
    # each day, stock i rises by i/1000: a score equal to i predicts the next return perfectly
    P = pd.DataFrame({s: [100 * (1 + i / 1000) ** t for t in range(4)] for i, s in enumerate(stocks)}, index=dates)
    X = pd.DataFrame({s: [float(i)] * 4 for i, s in enumerate(stocks)}, index=dates)
    out = measure(P, {"score": X})["score"]["1d"]
    assert out["dates"] == 3 and out["ic"] == 1.0 and out["spread_pct"] > 0 and not out["conclusive"]
