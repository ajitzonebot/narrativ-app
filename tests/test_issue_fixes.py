"""Fixes for the shared issue log rows of 28 Nov 2026 (docs/data/issues/fixer-2026-11-28-reports.jsonl)."""
import json
from datetime import date

import requests

from narrativ import announcements, ibbi, issues, verify
from narrativ.verify import scaled_in, value_check

HUDCO_Q = "By 2030, we had given an initial guidance two years back that we will be achieving around INR3 lakh crores loan book."


def test_lakh_crore_quote_matches_crore_value():  # 9e29b9c983
    assert value_check(300000, "cr", HUDCO_Q) is None
    assert value_check(3, "lakh crore", HUDCO_Q) is None
    assert value_check(30000, "cr", HUDCO_Q) == "value 30000 not in quote"
    assert scaled_in(300000, "crore", HUDCO_Q) == "3 lakh crore"


def test_no_conversion_across_counting_systems():
    assert value_check(12, "cr", "we won orders of $120 million") == "value 12 not in quote"
    assert value_check(1200, "million", "a 1.2 billion plan") is None
    assert value_check(12, "cr", "a 1,200 lakh order") is None


def test_other_nse_host_on_failure(monkeypatch):  # ba6f426bfb
    seen = []

    class R:
        status_code = 200

    def get(url, **_):
        seen.append(url)
        if "nseindia.in/" in url:
            raise requests.ConnectionError("HTTP/2 INTERNAL_ERROR")
        return R()

    monkeypatch.setattr(verify.requests, "get", get)
    assert verify._get("https://nsearchives.nseindia.in/corporate/X.pdf").status_code == 200
    assert seen == ["https://nsearchives.nseindia.in/corporate/X.pdf", "https://nsearchives.nseindia.com/corporate/X.pdf"]


def test_flag_takes_newest_hit_with_a_link():  # 2626cc8427
    subj = "Quarterly Disclosures By Listed Entities Of Defaults On Payment Of Interest/ Repayment Of Principal Amount On Loans"
    rows = [["2026-10-02", "Company Update", subj, None, "x", None],
            ["2026-07-02", "Company Update", subj, "https://www.bseindia.com/xml-data/corpfiling/AttachLive/a.pdf", "x", None]]
    st = {"rows": {"FOO.BO": rows}}
    r = announcements.checks({}, "FOO.BO", date(2026, 11, 28), {"loaded": {"FOO.BO": 1}, "rows": st["rows"]})
    a2 = r["A2"]
    assert a2[0] == 1 and a2[3].endswith("/a.pdf") and a2[1].startswith("2026-07-02") and "(+1 more)" in a2[1]


def test_rupee_found_value_closes_when_app_reads_it(tmp_path, monkeypatch):  # 28e675b3dc
    out = tmp_path / "data_issues.json"
    out.write_text(json.dumps({"issues": {"i1": {"symbol": "B.NS", "field": "de.lease_liabilities_cr", "found_value": 1128500000,
                                                  "unit": "₹", "status": "corrected"}}}))
    monkeypatch.setattr(issues, "OUT", out)
    mx = {"B.NS": {"de": {"in": {"lease_liabilities_cr": 112.85}}}}
    r = issues.update({}, mx, lambda m, f: None, date(2026, 11, 29))
    assert r["issues"]["i1"]["status"] == "fixed"


def test_ibbi_pdf_link_unquoted_and_private_debtor(monkeypatch):  # 2776d3d5f0
    html = ("<table><tr><td>Public Announcement of Corporate Insolvency Resolution Process</td><td>21-06-2026</td><td>02-07-2026</td>"
            "<td>VIKRAM SOLAR LIMITED</td><td>Tripti Agarwal</td><td>Tripti Agarwal</td>"
            "<td><a href=https://ibbi.gov.in//uploads/announcement/187c.pdf download>x</a></td></tr></table>")

    class R:
        text = html

        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    rows = ibbi.page(1)
    assert rows[0]["pdf"] == "https://ibbi.gov.in//uploads/announcement/187c.pdf"
    st = {"rows": {"a": {**rows[0]}, "b": {**rows[0], "debtor": "Vikram Solar Private Limited", "date": "2026-07-01"}}}
    m = ibbi.match(st, {"VIKRAMSOLR.NS": "Vikram Solar Limited"}, date(2026, 11, 28))
    assert [x["url"] for x in m["VIKRAMSOLR.NS"]["as_debtor"]] == ["https://ibbi.gov.in//uploads/announcement/187c.pdf"]
