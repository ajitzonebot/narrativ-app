from narrativ.packs import excerpts, quality


def test_excerpts_keep_forward_sentences_with_neighbours():
    t = ("Thank you. We expect revenue growth of 20% next year. The board met. "
         "Unrelated remark here. Weather was fine. Nothing else.")
    ex = excerpts(t)
    assert len(ex) == 1 and "20%" in ex[0] and ex[0].startswith("Thank you.")


def test_quality_poor_for_garbage():
    assert quality("@@@@ #### $$$$" * 10, 5)["grade"] == "poor"
