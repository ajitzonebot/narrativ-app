from narrativ.story import _nums, check, check_line


def test_fy_counts_as_full_year():
    facts = "Reach 500 crore of revenue by FY27."
    assert 2027 in _nums(facts)
    out = {"what": "A maker of pumps for farms.", "money": "It sells pumps.", "plans": ["Reach 500 crore of revenue by 2027"]}
    assert check(out, facts) == []


def test_line_checks():
    facts = "A microfinance lender. Loans grow 20%."
    assert check_line("A village lender with strong books, priced cheap, still waiting for the market.", facts) == []
    assert any("advice" in b for b in check_line("A lender you should buy now.", facts))
    assert any("number not in facts" in b for b in check_line("A lender growing 45% a year.", facts))
    assert any("too long" in b for b in check_line("x" * 130, facts))


def test_label_and_line():
    from narrativ.story import check_label, line_of
    facts = "Hero makes motorcycles and scooters."
    assert check_label("A maker of motorcycles and scooters", facts) == []
    assert "label judges" in check_label("A strong motorcycle maker", facts)
    assert line_of("A maker of motorcycles and scooters", "A strong business at a cheap price.") == \
        "A maker of motorcycles and scooters; a strong business at a cheap price."
    assert line_of(None, "A strong business.") == "A strong business."
