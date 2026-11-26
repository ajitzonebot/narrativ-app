"""Feedback #113: the story's "How it's going" adds cash conversion (the Quality tab's figure); none for lenders."""
from narrativ.story import going


def test_cash_conversion_added():
    g = going({"rev_yoy_pct": {"v": 19.8}, "pat_yoy_pct": {"v": 231}, "cfo_to_ebitda_pct": {"v": 61, "exact": 61.2, "in": {"years": 3}}})
    assert g["text"].endswith("Most of the profit turns into cash: 61% cash conversion over 3 years (cash from operations ÷ operating profit).")


def test_no_cash_line_when_not_meaningful():
    g = going({"rev_yoy_pct": {"v": -5}, "cfo_to_ebitda_pct": {"nm": True, "v": None}})
    assert "cash" not in g["text"]


def test_going_leaves_out_growth_that_is_not_meaningful():
    from narrativ.story import going
    g = going({"rev_yoy_pct": {"v": 1826.4, "nm": True}, "pat_yoy_pct": {"v": 12.0}})
    assert g["text"] == "Profit up 12% on the same quarter last year."
    assert going({"rev_yoy_pct": {"v": 1826.4, "nm": True}}) is None


def test_reworded_plans_paired_with_their_own_plan():
    from narrativ.story import pair_plans
    plans = [{"text": "Ashiana Aranya in Chennai expected to launch in Q4 FY27", "due": "2027-03-31"},
             {"text": "FY27 target of INR700 crores plus of value of area booked", "due": "2027-03-31"},
             {"text": "Target of INR1,500 crores annual value of area booked by 2030", "due": "2030-03-31"}]
    old = ["Launch the Ashiana Aranya project in Chennai by early 2027", "Reach 1,500 crore rupees in annual home sales by 2030"]
    pl = pair_plans(plans, old)
    assert pl[0]["text"] == old[0] and pl[1]["text"] == plans[1]["text"]  # the 1,500 crore rewording is not of plan 2
    new = [{"src": plans[1]["text"], "text": "Book homes worth 700 crore rupees in FY27"}]
    assert pair_plans(plans, new)[1]["text"] == "Book homes worth 700 crore rupees in FY27"
    assert pair_plans([{"text": "changed plan", "due": None}], new)[0]["text"] == "changed plan"  # stored for another plan
