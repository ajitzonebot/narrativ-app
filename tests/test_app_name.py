"""The app shows the reviewer as "Narrativ.ai" (owner, 25 Nov 2026). New texts say Narrativ.ai; decisions stored before
the rename say "Claude" and are still matched (republish.py, funnel.apply_buy_rules)."""
import json
from datetime import date
from pathlib import Path

from narrativ import funnel as FN
from narrativ import republish

TODAY = date(2026, 11, 25)
GOOD = {"cfo_to_ebitda_pct": {"v": 80, "exact": 80.0, "in": {"years": 3}}}
TRIG = {"out": {"triggers": [{"id": "T11"}]}, "val": {"t": 2, "name": "Undervalued"}, "disc": {"t": 1, "name": "Undiscovered"}}
DEBT = {"item": "Borrowings and lease liabilities", "rule": "debt_leases", "ok": True}


def test_old_and_new_verified_texts_are_both_replaced():
    for old in ("Verified by Claude's full review on 2026-11-19", "Verified by Narrativ.ai's full review on 2026-11-19"):
        d = FN.apply_buy_rules({"d": "Buy", "why": [old], "verified": "pass"}, GOOD, False, TRIG,
                               {"audit": {"verdict": "pass", "checks": [DEBT]}}, TODAY)
        assert d["d"] == "Hold" and old not in d["why"]
        assert d["why"][0] == "Rules say Buy: Narrativ.ai's review passed but does not yet cover RULES.md R7"
        nd = republish.gate({"d": "Buy", "why": [old], "missing": []},
                            {"audit": {"verdict": "pass", "date": "2026-11-20", "changed_after": ["drivers"]}}, "2026-11-01", TODAY)
        assert nd["d"] == "Hold" and old not in nd["why"] and nd["why"][0] == "Rules say Buy: waiting for Narrativ.ai's full review"
        assert any(m.startswith("Verification pending: queued for Narrativ.ai's full review") for m in nd["missing"])


def test_republished_pass_is_verified_by_narrativ_ai():
    old = {"d": "Hold", "candidate": "Buy", "why": ["Rules say Buy: waiting for Claude's full review", "Verified by Claude's full review on 2026-11-01"]}
    nd = republish.gate(old, {"audit": {"verdict": "pass", "date": "2026-11-24"}}, "2026-11-01", TODAY)
    assert nd["d"] == "Buy" and nd["why"] == ["Verified by Narrativ.ai's full review on 2026-11-24"]


def test_schedule_names_narrativ_ai_not_claude():
    s = json.loads(Path("docs/data/schedule.json").read_text())
    assert "Claude" not in json.dumps(s)
    assert {j["by"] for j in s["jobs"]} >= {"Narrativ.ai"}
    # the app highlights the research job by `by` and a name starting "Research" (AccountScreens.kt)
    assert any(j["by"] == "Narrativ.ai" and j["name"].startswith("Research") for j in s["jobs"])
