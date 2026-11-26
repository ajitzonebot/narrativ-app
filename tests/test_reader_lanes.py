from narrativ import quota as q
from narrativ.reader import FLASH_LANE, LITE_LANE, CHECK_LANE, label_agreement


AVAIL = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-preview-tts",
         "gemini-3-flash-preview", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-4-hydrogen", "gemma-4-31b-it", "gemma-4-26b-a4b-it",
         "gemini-3.8-flash-lite-tts"]


def test_resolve_lanes():
    assert q.resolve(LITE_LANE, AVAIL) == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
    assert q.resolve(FLASH_LANE, AVAIL) == ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-2.5-flash"]
    assert q.resolve(CHECK_LANE, AVAIL) == ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]


def test_quota_caps_and_counts(tmp_path):
    g = q.Quota(tmp_path / "u.json")
    assert q.limits("gemini-3.8-flash")[2] == 19 and q.limits("gemma-4-31b-it")[1] == 15_000
    for _ in range(3):
        assert g.take("gemini-3.1-flash-lite", 1000, cap=3)
    assert not g.take("gemini-3.1-flash-lite", 1000, cap=3)
    assert g.used("gemini-3.1-flash-lite") == 3
    assert g.refused("gemma-4-31b-it") is True and g.refused("gemma-4-31b-it") is False
    assert g.left("gemma-4-31b-it") == 0


def test_agreement_labels():
    store = {"u": {"lite": {"rows": [{"quote": "We expect revenue to grow 20% in FY27."}, {"quote": "Margins will stay flat."}]},
                   "flash": {"rows": [{"quote": "We expect revenue to grow 20% in FY27."}]}}}
    assert label_agreement(store) == 2
    assert [r["agree"] for r in store["u"]["lite"]["rows"]] == [True, False]
