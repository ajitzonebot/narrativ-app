from narrativ.filings import _leases

XML = """<xbrli:context id="C1"><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
<in-bse-fin:DescriptionOfOtherNoncurrentLiabilities contextRef="C1">Lease liabilities</in-bse-fin:DescriptionOfOtherNoncurrentLiabilities>
<in-bse-fin:OtherNoncurrentLiabilities contextRef="C1" unitRef="INR" decimals="-5">12500000</in-bse-fin:OtherNoncurrentLiabilities>
<in-bse-fin:DescriptionOfOtherCurrentFinancialLiabilities contextRef="C1">Security deposits</in-bse-fin:DescriptionOfOtherCurrentFinancialLiabilities>
<in-bse-fin:OtherCurrentFinancialLiabilities contextRef="C1" unitRef="INR" decimals="-5">900000</in-bse-fin:OtherCurrentFinancialLiabilities>"""


def test_lease_read_from_other_noncurrent_liabilities():
    out = _leases(XML, "2026-09-30")
    assert out["lease_ncur"] == 12500000
    assert "lease_cur" not in out  # not described as a lease
    assert out["lease_chk"] == 2.0


def test_lease_other_period_ignored():
    assert "lease_ncur" not in _leases(XML, "2026-03-31")
