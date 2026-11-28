"""Every screen tells the same story (narrativ/consistency.py, owner 28 Nov 2026)."""
import json

from narrativ import consistency as K


def test_finds_a_stale_decision_card_and_a_missing_scan(tmp_path):
    d = tmp_path
    (d / "fin").mkdir()
    (d / "picks.json").write_text(json.dumps({"date": "2026-11-27", "updated": "2026-11-27T18:00:00+00:00",
                                              "picks": [{"s": "HPL.NS", "dc": "Hold", "vf": None}, {"s": "OK.NS", "dc": "Hold"}]}))
    card = {"decision": {"d": "Hold", "why": ["No trigger yet: no forward driver"], "missing": []},
            "levels": {"out": {"t": 0, "name": "Not scanned yet"}}}
    (d / "fin" / "HPL.NS.json").write_text(json.dumps(card))
    (d / "fin" / "OK.NS.json").write_text(json.dumps({"decision": {"d": "Hold"}, "levels": {"out": {"t": 3}}}))
    (d / "research.json").write_text(json.dumps({"HPL.NS": {"updated": "2026-11-28", "drivers": [
        {"text": "Data centre cables from Jun 2027", "due": "2027-06-30", "due_verified": True}]}}))
    (d / "theses.json").write_text(json.dumps({}))
    r = K.run(d)["checks"]
    assert r["K1"]["n"] == 1 and r["K3"]["n"] == 1 and r["K6"]["n"] == 1        # 28 Nov research after the 27 Nov rebuild
    assert all(v["n"] == 0 for k, v in r.items() if k not in ("K1", "K3", "K6"))
    assert K._ist_day("2026-11-27T19:00:00+00:00") == "2026-11-28"               # 00:30 IST is the next IST day
