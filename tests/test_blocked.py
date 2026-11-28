import json
from datetime import date

from narrativ import blocked as BL
from narrativ import next as NX

T = date(2026, 11, 30)


def line(d, *syms, task="catalyst"):
    return json.dumps({"task": task, "start": f"{d}T12:06+05:30", "blocked": [{"symbol": s, "why": f"why {s}"} for s in syms]})


def test_recent_and_stuck():
    lines = [line("2026-11-26", "OLD"), line("2026-11-28", "LICHSGFIN.NS"), line("2026-11-29", "LICHSGFIN", "ONCE.NS"), "not json"]
    b = BL.recent(lines, T)
    assert set(b) == {"LICHSGFIN.NS", "ONCE.NS"} and len(b["LICHSGFIN.NS"]) == 2
    assert list(BL.stuck(b, {})) == ["LICHSGFIN.NS"]
    assert BL.stuck(b, {"LICHSGFIN.NS": {"updated": "2026-11-29"}}) == {}  # research saved since the last block
    assert BL.stuck(b, {}, {"LICHSGFIN.NS": "2026-11-29"}) == {}  # owner closed the issue after the last block


class Http:
    def __init__(self, issues):
        self.issues, self.calls = issues, []

    def get(self, url, **k):
        return type("R", (), {"ok": True, "json": lambda s: self.issues})()

    def post(self, url, json=None, **k):
        self.calls.append(("post", url, json))

    def patch(self, url, json=None, **k):
        self.calls.append(("patch", url, json))


def test_sync_opens_issue_and_honours_close(tmp_path, monkeypatch):
    monkeypatch.setattr(BL, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.setattr(BL, "STATE", tmp_path / "blocked.json")
    BL.RUNS.write_text("\n".join([line("2026-11-29", "A.NS"), line("2026-11-30", "A.NS")]))
    h = Http([])
    st = BL.sync_issues({}, T, "o/r", "tok", h)
    assert list(st["stuck"]) == ["A.NS"] and h.calls[0][0] == "post" and h.calls[0][2]["title"] == "blocked: A.NS"
    h = Http([{"number": 9, "title": "blocked: A.NS", "state": "closed", "closed_at": "2026-11-30T10:00:00Z"}])
    st = BL.sync_issues({}, T, "o/r", "tok", h)
    assert st["stuck"] == {} and st["cleared"] == {"A.NS": "2026-11-30"} and h.calls == []


def test_feed_skips_blocked():
    q = {"date": "2026-11-29", "items": [{"symbol": "A.NS", "task": "recheck", "pos": "news"}, {"symbol": "B.NS", "task": "recheck", "pos": "news"}]}
    items, sk = NX.ladder(q, {}, {}, {}, {}.get, "catalyst", "2026-11-30", NX.datetime(2026, 11, 30, 10, tzinfo=NX.IST), {"A.NS"})
    assert [x["symbol"] for x in items] == ["B.NS"] and sum(sk.values()) == 1


def test_website_docs_finds_transcripts_one_level_deep(monkeypatch):
    from narrativ import packs as PK
    site = {"https://co.in/": [("https://co.in/investors", "Investors"), ("https://co.in/about", "About us")],
            "https://co.in/investors": [("https://co.in/f/Q1FY26-Concall-Transcript.pdf", "Q1 FY26 transcript"),
                                        ("https://co.in/f/Q2FY27-Concall-Transcript.pdf", "Q2 FY27 transcript"),
                                        ("https://co.in/f/Investor-Presentation-Q2FY27.pdf", "Investor presentation"),
                                        ("https://co.in/f/annual-report.pdf", "Annual report")]}
    monkeypatch.setattr(PK, "_page_links", lambda u: site.get(u, []))
    got = PK.website_docs(["https://co.in/"], cap=3)
    assert [d["url"].rsplit("/", 1)[-1] for d in got] == ["Q2FY27-Concall-Transcript.pdf", "Q1FY26-Concall-Transcript.pdf",
                                                         "Investor-Presentation-Q2FY27.pdf"]
    assert got[0]["kind"] == "transcript" and got[0]["page"] == "https://co.in/investors"


def test_request_suffix_maps_to_the_scored_listing():
    from narrativ.requests import _norm
    assert _norm("BONDADA.BO", {"BONDADA.NS"}) == "BONDADA.NS"
    assert _norm("X.BO", {"X.BO", "X.NS"}) == "X.BO" and _norm("Y.BO", set()) == "Y.BO"
