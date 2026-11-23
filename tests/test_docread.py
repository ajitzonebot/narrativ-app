from narrativ.docread import tables


def test_tables_extracted_in_order_and_capped():
    md = "# Results\n\n| Item | FY26 |\n|---|---|\n| Revenue | 1,200 |\n\nText.\n\n| Plant | Capacity |\n|---|---|\n| A | 10,000 |\n"
    t = tables(md)
    assert len(t) == 2 and t[0].startswith("| Item") and "10,000" in t[1]
    assert tables(md, cap=40) == [t[0]] if len(t[0]) <= 40 else tables(md, cap=40) == []
