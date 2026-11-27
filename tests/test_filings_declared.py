"""NSE's pre-2022 "_WEB" XBRL files reference OneD / FourD / OneI without defining them; `declared=True` takes the
periods from the filing's own DateOfStart/EndOfReportingPeriod facts (narrativ/filings._declared_contexts)."""
from narrativ.filings import parse_xbrl

WEB = """<xbrli:xbrl>
<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2018-10-01</in-bse-fin:DateOfStartOfReportingPeriod>
<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2018-12-31</in-bse-fin:DateOfEndOfReportingPeriod>
<in-bse-fin:DateOfStartOfReportingPeriod contextRef="FourD">2018-04-01</in-bse-fin:DateOfStartOfReportingPeriod>
<in-bse-fin:DateOfEndOfReportingPeriod contextRef="FourD">2018-12-31</in-bse-fin:DateOfEndOfReportingPeriod>
<in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-7">16912000000.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:ProfitLossForPeriod contextRef="OneD" unitRef="INR" decimals="-7">128700000.00</in-bse-fin:ProfitLossForPeriod>
<in-bse-fin:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-7">50582000000.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:Equity contextRef="OneI" unitRef="INR" decimals="-7">9000000000.00</in-bse-fin:Equity>
</xbrli:xbrl>"""


def test_web_file_without_contexts_needs_declared():
    assert parse_xbrl(WEB) == {}


def test_declared_periods():
    p = parse_xbrl(WEB, declared=True)
    assert (p["end"], p["q_start"], p["ytd_start"]) == ("2018-12-31", "2018-10-01", "2018-04-01")
    assert p["q"]["rev"] == 16912000000.0 and p["q"]["pat"] == 128700000.0
    assert p["ytd"]["rev"] == 50582000000.0
    assert p["bs"]["equity"] == 9000000000.0
