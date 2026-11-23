from narrativ.portfolio import multibagger, top10


def row(s, rk, i="A", sec="X", mc=10000, dc="Buy", vf="pass"):
    return {"s": s, "rk": rk, "i": i, "sec": sec, "mc": mc, "dc": dc, "vf": vf}


def test_only_verified_buys_in_rank_order():
    rows = [row("B", 2, i="I2"), row("A", 1, i="I1"), row("C", 3, vf="caution", i="I3"), row("D", 4, dc="Hold", i="I4")]
    assert top10(rows) == ["A", "B"]


def test_caps_per_industry_and_sector():
    rows = [row(f"S{k}", k, i="Same", sec=f"X{k}") for k in range(1, 5)]  # ranks start at 1
    assert top10(rows) == ["S1", "S2"]  # 2 per industry
    rows = [row(f"T{k}", k, i=f"I{k}", sec="Same") for k in range(1, 6)]
    assert top10(rows) == ["T1", "T2", "T3"]  # 3 per sector


def test_multibagger_needs_trigger():
    assert multibagger(5000, 1, 25, False, 18, True, 1)
    assert not multibagger(5000, 1, 25, False, 18, False, 1)
