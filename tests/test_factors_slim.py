from narrativ.factors import slim


def test_slim_keeps_only_the_fields_the_factor_check_reads():
    d = {"date": "2026-11-01", "level_names": {"a": "A"}, "funnel": {"big": list(range(1000))},
         "picks": [{"s": "X", "p": 1.0, "rk": 3, "pr": 2.0, "dc": "Buy", "sc": [1, 2], "why": "long text", "sp": [1] * 30}]}
    out = slim(d)
    assert out["picks"] == [{"s": "X", "p": 1.0, "rk": 3, "pr": 2.0, "dc": "Buy", "sc": [1, 2]}]
    assert out["level_names"] == {"a": "A"} and "funnel" not in out
