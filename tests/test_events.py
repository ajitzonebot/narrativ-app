"""Exchange announcement typing (narrativ/events.py): regulatory inspection outcomes and the false order wins.
Subjects are taken from stored NSE / BSE filings (company names shortened)."""
import pytest

from narrativ.events import classify, from_announcements, retype


def sev(text: str, category: str = "") -> str:
    return classify(f"{text} {category}")[1]


OAI = ("Caplin Point Laboratories Limited has informed the Exchange about Classification of US FDA Inspection at the facility "
       "of Caplin Steriles Limited (Company's Subsidiary) as OAI")
SPURT = ("Significant increase in volume has been observed in Caplin Point Laboratories Limited. The Exchange, in order to ensure "
         "that investors have latest relevant information about the company and to inform the market place so ")


@pytest.mark.parametrize("text", [
    OAI,
    "USFDA classifies the Halol facility as Official Action Indicated",
    "Receipt of Warning Letter from USFDA for the Pithampur facility",
    "USFDA places the Unit-II facility under Import Alert 66-40",
    "Establishment Inspection Report (EIR) received from USFDA with OAI status",
    "Receipt of Statement of Non-Compliance with EU GMP from the Hungarian authority",
    "EU GMP certificate of the Ahmedabad plant withdrawn",
    "CDSCO orders suspension of the manufacturing licence of the Baddi unit",
    "Suspension of drug manufacturing licence by the State Licensing Authority",
    "Closure direction issued by Gujarat Pollution Control Board for the Dahej unit",
    "Receipt of closure order for the Tarapur plant",
    "USFDA inspection concluded with Form 483 citing data integrity and repeat observations",
])
def test_regulatory_inspection_adverse_is_red(text):
    t, s = classify(text)
    assert s == "red", (t, text)


@pytest.mark.parametrize("text", [
    "Zydus receives EIR from the USFDA for its injectable facility with VAI classification",
    "Granules India s Gagillapur facility completes USFDA inspection with eleven observations",
    "USFDA inspection concluded with 3 observations",
    "Issuance of Form 483 with two observations by USFDA",
    "Completion of Unannounced US FDA Inspection at the facility of Caplin Steriles Limited (Company s Subsidiary)",
])
def test_inspection_observations_or_no_outcome_is_watch(text):
    assert sev(text) == "watch", classify(text)


@pytest.mark.parametrize("text", [
    "Strides receives USFDA Establishment Inspection Report (EIR) for flagship facility in Bengaluru",
    "USFDA inspection at the Sanand facility concludes with zero observations",
    "USFDA inspection of pharmacovigilance and post marketing system concludes at Zydus USA Office with nil observations",
    "Inspection classified NAI (No Action Indicated) by USFDA",
    "Successful completion of unannounced USFDA onsite inspection at the Bioequivalence Facility",
    "Closure of USFDA inspection at Zydus LiqMeds, UK",
    "USFDA upgrades the Halol facility status from OAI to VAI",
    "Receipt of close-out letter from USFDA for the warning letter at the Goa plant",
    "USFDA lifts import alert on the Mohali facility",
])
def test_inspection_cleared_is_green(text):
    assert sev(text) == "green", classify(text)


def test_inspection_rules_need_a_regulator():
    # Rs 483 crore is an order size, not a Form 483; "no adverse observations" letters are scheme approvals
    assert classify("being declared as L1 (Lowest First) for order valued at Rs. 483.7 Crore incl GST") == ("Order / contract win", "green")
    assert sev("Receipt of Observation Letters with no adverse observations from BSE and NSE for the Scheme of Amalgamation") == "green"
    assert classify("Inspection/Search operation initiated by GST Department at the factory")[1] == "red"  # still search / seizure
    assert sev("Intimation of Trading Window closure pursuant to SEBI (PIT) Regulations", "Trading Window") == "info"


@pytest.mark.parametrize("text,category", [
    (SPURT, "Spurt in Volume"),
    ("Significant movement in price has been observed in Arrow Greentech Limited. The Exchange, in order to ensure that investors "
     "have latest relevant information", "Price movement"),
    ("The Exchange has sought clarification from iStreet Network Ltd with reference to significant movement in price, in order to "
     "ensure that investors", "Company Update / Clarification"),
])
def test_volume_price_clarification_is_info_not_order(text, category):
    assert classify(f"{text} {category}") == ("Exchange clarification", "info")


@pytest.mark.parametrize("text", [
    "Receipt of order of the Hon'ble High Court of Delhi in the trademark matter",
    "Order passed by the Hon'ble National Company Law Appellate Tribunal in the matter of the arbitration",
    "Supreme Court order in the matter of the land acquisition dispute",
    "Intimation of court order regarding the recovery suit",
    "Receipt of GST Order Levying Tax Demand and Penalty",
    "Order received from the Assistant Commissioner, State Goods and Services Tax, Trichy",
    "Assessment order under section 143(3) of the Income Tax Act, 1961",
    "Bajaj Auto Limited has informed the Exchange about Order passed Action(s) taken or orders passed",
    "Order passed by the Uttarakhand Pollution Control Board",
])
def test_legal_and_tax_orders_are_watch_not_growth(text):
    t, s = classify(text)
    assert s == "watch" and t != "Order / contract win", (t, text)


def test_legal_red_rules_still_win():
    assert classify("Order of the tribunal admitting the petition under the Insolvency and Bankruptcy Code")[1] == "red"
    assert classify("Administrative warning letter received from SEBI Action(s) taken or orders passed")[1] == "red"


@pytest.mark.parametrize("text", [
    "Bagging/Receiving of orders/contracts worth Rs.483.72 Crore",
    "being declared as L1 (First Lowest) in order valued at Rs. 97.31 Crore",
    "Receipt of order to supply 200 electric buses",
    "Orders aggregating approx. Rs 25 crore received",
    "Order for construction of the District Court complex worth Rs 120 crore",
])
def test_real_order_wins_stay_green(text):
    assert classify(text) == ("Order / contract win", "green")


def test_scheme_sanctioned_by_tribunal_stays_corporate_action():
    t, s = classify("First Motion Order passed by the Hon ble National Company Law Tribunal on the Scheme of Amalgamation")
    assert (t, s) == ("Buyback / demerger / acquisition", "green")


def test_retype_reaches_stored_events_and_stamps_red():
    url = "https://nsearchives.nseindia.in/corporate/CAPLINPOINT_17112026135959_Stock_Exchange_intimation_of_USFDA_Audit.pdf"
    stored = [  # as kept in memory by the old rules
        {"date": "2026-11-17", "type": "Other", "sev": "info", "text": OAI, "category": "General Updates", "url": url},
        {"date": "2026-09-24", "type": "Order / contract win", "sev": "green", "text": SPURT, "category": "Spurt in Volume", "url": "u2"},
        {"date": "2025-01-01", "type": "Order / contract win", "sev": "green", "text": "x" * 220, "category": "", "url": "u3"},
    ]
    src = from_announcements([{"date": "2026-11-17", "text": OAI, "category": "General Updates", "url": url}])
    turned = retype(stored, src, "2026-11-21")
    assert [e["url"] for e in turned] == [url]
    assert stored[0]["sev"] == "red" and stored[0]["red_seen"] == "2026-11-21"
    assert stored[1]["sev"] == "info"  # not in the source: re-typed from its stored (cut) text, which still matches a rule
    assert stored[2]["sev"] == "green"  # cut text matching no rule: left as it was
    assert retype(stored, src, "2026-11-22") == []  # already red: no second alert, red_seen kept
    assert stored[0]["red_seen"] == "2026-11-21"


def test_retype_never_raises_or_clears_red_from_a_cut_text():
    cut = ("This is in reference to our earlier disclosure dated 09th August,2024. Now we inform that, in one of the SCN matter an "
           "order has been passed. We hereby submit the details of the said order under Regulation 30 of SEBI (Li")
    assert len(cut) == 220
    stored = [  # the cut joins "SEBI (Li" to the category "... orders passed": a false SEBI order on the cut text
        {"date": "2025-02-07", "type": "Order / contract win", "sev": "green", "text": cut,
         "category": "Action(s) taken or orders passed", "url": "a"},
        {"date": "2025-02-07", "type": "Fraud / forensic", "sev": "red", "text": SPURT, "category": "Spurt in Volume", "url": "b"},
    ]
    assert retype(stored, [], "2026-11-21") == []
    assert [e["sev"] for e in stored] == ["green", "red"]
