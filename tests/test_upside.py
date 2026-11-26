from narrativ import upside as UP


def q(revs, pats, margins, last="2026-09-30"):
    n = len(revs)
    return [[UP._back(last, n - 1 - i), r, p, m] for i, (r, p, m) in enumerate(zip(revs, pats, margins))]


def test_profit_speeding():
    rows = q([100] * 4 + [112, 113, 114, 115], [10, 10, 10, 10, 11, 12, 13, 14], [15] * 8)
    ok, v = UP.profit_speeding(rows)
    assert ok is True and "40%" in v
    flat = q([100] * 8, [10] * 8, [15] * 8)
    assert UP.profit_speeding(flat)[0] is False
    assert UP.profit_speeding(rows[:5]) == (None, None)


def test_operating_leverage():
    rows = q([100] * 4 + [115] * 4, [10] * 8, [10] * 4 + [13] * 4)
    ok, _ = UP.operating_leverage(rows)
    assert ok is True  # revenue +15%, EBITDA +49.5%
    assert UP.operating_leverage(q([100] * 8, [10] * 8, [10] * 7 + [None]))[0] is None


def test_rerating_setup():
    peer = {"median": 30, "n": 8}
    hist = [25, 28, 30, 32, 35, 40]
    assert UP.rerating_setup([[2024, 15], [2025, 18]], -5, None, 20, hist, peer)[0] is True
    assert UP.rerating_setup([[2024, 18], [2025, 15]], -5, None, 20, hist, peer)[0] is False  # ROCE down
    assert UP.rerating_setup([[2024, 15], [2025, 18]], 40, 2.0, 20, hist, peer)[0] is False  # debt rising
    assert UP.rerating_setup([[2024, 15], [2025, 18]], -5, None, 20, hist, {"median": 30, "n": 3})[0] is None


def test_overhang_over():
    h = [{"promoter_pct": x} for x in (60, 59.5, 59, 58.5, 58, 58)]
    assert UP.overhang_over(h)[0] is True
    h2 = [{"promoter_pct": x} for x in (60, 59.5, 59, 58.5, 58, 57.5)]
    assert UP.overhang_over(h2)[0] is False
    assert UP.overhang_over([], pledge=0.0, pledge_1q=-12.0)[0] is True
    assert UP.overhang_over(h[:4]) == (None, None)


def test_both_engines():
    rows = q([100] * 4 + [112, 113, 114, 115], [10, 10, 10, 10, 11, 12, 13, 14], [15] * 8)
    c = UP.checks(rows, [[2024, 15], [2025, 18]], -5, None, 20, [25, 28, 30, 32, 35, 40], {"median": 30, "n": 8}, [])
    assert c["U1"][0] and c["U3"][0] and c["U5"][0] is True
    assert c["U4"] == (None, None)


def test_replay_u1_boost_is_a_variant_only():
    from narrativ import replay as R
    rows = {s: {"eligible": True, "mos": True, "trend": True, "driver": True, "fwd": True, "R1": True, "R2": True, "R4": True, "R6": True, "rs": 50, "near": 50, "vs": 50,
                "pr": 0, "setup": 0, "mb": False, "U1": s == "B", "i": s, "sec": s, "mc": 10000} for s in ("A", "B")}
    rows["A"]["rs"] = 60  # A leads by 4.5 points without the boost
    assert R._pick(rows, R.CUR, {**R.BASE_W, "_boost": {"U1": 10}})[0] == "B"
    assert R._pick(rows, R.CUR, R.BASE_W)[0] == "A"  # live ranking: no U1 boost (removed 25 Nov 2026)


def test_quarters_matched_by_date_not_position():
    assert UP._back("2026-09-30", 4) == "2025-09-30" and UP._back("2026-03-31", 1) == "2025-12-31"
    rows = q([100] * 4 + [112, 113, 114, 115], [10, 10, 10, 10, 11, 12, 13, 14], [15] * 8)
    gap = rows[:3] + rows[4:]  # one quarter not filed: the last 7 are no longer 7 consecutive quarters
    assert UP.profit_speeding(gap) == (None, None)
    assert UP.operating_leverage(gap) == (None, None)
