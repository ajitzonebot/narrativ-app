"""Publish Claude's research within about 30 minutes (the public repo's republish job polls every 30 minutes) instead of at the evening run.

Runs after each research push (.github/workflow-src/republish.yml). For the stocks whose entry in docs/data/theses.json changed:
verify them (same verifier as the daily run), update their research entry, and apply the Claude gate to the decision the
daily run already computed: rules said Buy / Strong Buy + verdict pass -> Buy / Strong Buy; caution / fail -> Hold.
No market data is downloaded and no other stock is touched; the evening run recomputes everything as usual.
A review that logged a data issue keeps the stock at Hold until the evening run re-scores it with the corrected value."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from narrativ import conviction as CV
from narrativ import funnel as FN
from narrativ import verify

OUT = Path("docs/data")
BUY = ("Buy", "Strong Buy")


def changed(before: str | None) -> list[str]:
    now = json.loads((OUT / "theses.json").read_text())
    try:
        old = json.loads(subprocess.run(["git", "show", f"{before}:docs/data/theses.json"], capture_output=True, text=True,
                                        check=True).stdout) if before and set(before) != {"0"} else {}
    except Exception:  # noqa: BLE001
        old = {}
    return sorted(s for s, v in now.items() if old.get(s) != v)


def gate(dec: dict, v: dict, filed: str | None, today, Mx: dict | None = None, L: dict | None = None, lender: bool = False,
         issues: list | None = None) -> dict | None:
    """New decision for one stock, or None when Claude's work does not change it. With the stock's levels `L`, the same
    open-data-issue hold and Buy gates as the daily run (FN.apply_buy_rules) are applied on top, with the new research:
    R2's quoted recurring other income and R4's dated drivers are re-checked, and a verified pass cannot release a stock
    an open data issue (docs/data/data_issues.json) holds.
    A stock the daily run's gates held (`gated_label`) is taken back to its pre-gate decision (FN.ungate) and gated again,
    so research that now meets a gate releases it between daily runs (25 Nov 2026: before, it waited for the evening run)."""
    orig = dec
    dec = FN.ungate(dec) if L is not None else dec
    nd = _verify(dec, v, filed, today)
    if L is None or not (dec.get("candidate") or dec.get("d") in BUY):
        return nd
    base = nd or dec
    ruled = FN.apply_buy_rules(base, Mx or {}, lender, L, v, today, issues)
    return ruled if (nd is not None or ruled != orig) else None


def _verify(dec: dict, v: dict, filed: str | None, today) -> dict | None:
    label = dec.get("candidate") or (dec.get("d") if dec.get("d") in BUY else None)
    if not label:
        return None  # rules did not say Buy: the review informs, it does not change the rating
    ver = FN.verification(v.get("audit"), filed, today, dec.get("call_since"))  # same latest-call rule as the daily run
    why = [w for w in dec.get("why") or [] if not w.startswith(("Rules say", *FN.VERIFIED_BY, "Independent audit", "Audit issue"))]
    if v.get("data_issues"):
        return {**dec, "d": "Hold", "candidate": label, "verified": ver["state"],
                "why": [f"Rules say {label}, but Narrativ.ai found a number to correct: "
                        + ", ".join(str(x.get("field")) for x in v["data_issues"][:3]) + " (re-scored at the evening run)"] + why}
    if ver["state"] == "pass":
        d = {**dec, "d": label, "verified": "pass", "why": why + [f"Verified by Narrativ.ai's full review on {ver['date']}"]}
        d.pop("candidate", None)
        d["missing"] = [m for m in dec.get("missing") or [] if not m.startswith("Verification pending")]
        return d
    if ver["state"] in ("caution", "fail"):
        d = {**dec, "d": "Hold", "verified": ver["state"],
             "why": [f"Independent audit ({ver.get('date')}): {ver['state']}" + (f" · {ver.get('summary')}" if ver.get("summary") else "")]
             + [f"Audit issue: {x}" for x in ver.get("issues") or []] + why}
        d.pop("candidate", None)
        d["missing"] = [m for m in dec.get("missing") or [] if not m.startswith("Verification pending")]
        return d
    if dec.get("d") in BUY:  # pending now (research changed after the audit, audit future-dated or stale): no longer a Buy
        return {**dec, "d": "Hold", "candidate": label, "verified": "pending",
                "why": [f"Rules say {label}: waiting for Narrativ.ai's full review"] + [w for w in why if not w.startswith(FN.VERIFIED_BY)],
                "missing": [m for m in dec.get("missing") or [] if not m.startswith("Verification pending")]
                + ["Verification pending: queued for Narrativ.ai's full review" + (f" ({ver['why']})" if ver.get("why") else "")]}
    return None


def open_issues(sym: str) -> list:
    """Open data issues that hold this stock from Buy: the daily run's own rule (corrections.apply on its filings)."""
    from narrativ import corrections as CORR, filings
    try:
        return CORR.apply({sym: filings.load(sym)})[2].get(sym) or []
    except Exception as e:  # noqa: BLE001
        print(f"[republish] data issues check failed for {sym}: {e}")
        return []


REVIEW_RESULTS = ("pass", "caution", "fail")


def prune_queue(done: dict, built_at: str | None, queue: dict) -> int:
    """Drop queue items a research run finished after the daily run built the queue (feedback #189 / #190, 27 Nov 2026:
    SURAKSHA was reviewed at 04:05 IST but stayed "in full review" until the next evening run). A full review (pass /
    caution / fail) clears review, review_flag and audit tasks; a flag review clears review_flag; any other result clears
    the task it names (enrich, recheck). Returns how many items were dropped."""
    if not built_at:
        return 0
    cleared: dict = {}
    for run in done.get("runs") or []:
        if not run.get("start") or run["start"] <= built_at[:16]:
            continue
        for it in run.get("items") or []:
            s, r = it.get("s"), str(it.get("r") or "")
            if not s:
                continue
            word = r.split()[0].split("(")[0].split("+")[0].lower() if r else ""
            tasks = {"review", "review_flag", "audit"} if word in REVIEW_RESULTS else {"review_flag"} if word == "review_flag" \
                else {word} if word in ("enrich", "recheck") else set()
            cleared.setdefault(s, set()).update(tasks)
    items = queue.get("items") or []
    keep = [x for x in items if x.get("task") not in cleared.get(x.get("symbol"), set())]
    queue["items"] = keep
    return len(items) - len(keep)


def prune_done_research(queue: dict, theses: dict, research: dict) -> int:
    """Drop queue items whose work is already in the research, whatever the run times (27 Nov 2026: a review run finished
    while the daily run was building the queue, so MOREPENLAB, PASUPTAC and MANAKSTEEL, reviewed at 23:05 IST, were queued
    again and the 09:05 and 14:05 review runs found nothing to do). A full review: an audit dated on or after the queue's
    date; a completion item (`complete`, RULES.md R8): the record is complete; a red-flag item: every flag has a review."""
    qd = str(queue.get("date") or "")[:10]
    keep = []
    for x in queue.get("items") or []:
        s, t = x.get("symbol"), x.get("task")
        th, rs = theses.get(s) or {}, research.get(s) or {}
        if t == "review" and x.get("complete"):
            if not FN.research_missing({**rs, "scan_raw": th.get("scan") or rs.get("scan_raw")}):
                continue
        elif t in ("review", "audit") and not x.get("requested"):
            a = str((th.get("audit") or {}).get("date") or "")[:10]
            if qd and a >= qd and not (rs.get("audit") or {}).get("changed_after"):
                continue
        elif t == "review_flag":
            fl = set(x.get("flags") or [])
            if fl and fl <= set((th.get("flag_reviews") or {}).keys()):
                continue
        keep.append(x)
    n = len(queue.get("items") or []) - len(keep)
    queue["items"] = keep
    return n


def main(before: str | None) -> None:
    try:  # Research queue > Completed in the app, also after runs that changed no research
        from narrativ import runlog
        rp = OUT / "research.json"
        done = runlog.completed(theses=json.loads(rp.read_text()) if rp.exists() else None)
        qp, pp = OUT / "queue.json", OUT / "picks.json"
        if qp.exists() and pp.exists():
            q = json.loads(qp.read_text())
            n = prune_queue(done or {}, json.loads(pp.read_text()).get("updated"), q)
            tp = OUT / "theses.json"
            if tp.exists() and rp.exists():
                n += prune_done_research(q, json.loads(tp.read_text()), json.loads(rp.read_text()))
            if n:
                qp.write_text(json.dumps(q, indent=1, ensure_ascii=False))
                print(f"[republish] queue: {n} item(s) finished since the daily run removed")
    except Exception as e:  # noqa: BLE001
        print(f"[republish] research_done.json / queue failed: {e}")
    syms = changed(before)
    if not syms:
        print("[republish] no research changes")
        return
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    th = json.loads((OUT / "theses.json").read_text())
    ver, rep = verify.verify_all({s: th[s] for s in syms})
    stamps_path = OUT / "audit_stamps.json"  # re-audit trigger, same store and rule as the daily run
    stamps = json.loads(stamps_path.read_text()) if stamps_path.exists() else {}
    FN.mark_changed(ver, FN.stamp_audits(th, stamps, today, syms))
    stamps_path.write_text(json.dumps(stamps, indent=0, sort_keys=True))
    research = json.loads((OUT / "research.json").read_text())
    picks = json.loads((OUT / "picks.json").read_text())
    rows = {p["s"]: p for p in picks.get("picks", [])}
    fwd_rows = json.loads((OUT / "forward.json").read_text()).get("stocks", {}) if (OUT / "forward.json").exists() else {}
    issues = (json.loads((OUT / "data_issues.json").read_text()).get("issues") or {}) if (OUT / "data_issues.json").exists() else {}
    moved, touched = [], []
    try:
        from narrativ import researchlog
        rlog = researchlog.update({s: th[s] for s in syms})
    except Exception as e:  # noqa: BLE001
        print(f"[republish] research log failed: {e}")
        rlog = {}
    for s in syms:  # scan history in the app (Claude's research list) updates with every push
        f = OUT / "fin" / f"{s}.json"
        if f.exists() and rlog.get(s):
            det = json.loads(f.read_text())
            det["research_log"] = rlog[s]
            f.write_text(json.dumps(det, separators=(",", ":"), ensure_ascii=False))
    for s in syms:
        old = research.get(s) or {}
        research[s] = {k: x for k, x in ver[s].items() if k != "scan_raw"} | ({"scan": old["scan"]} if "scan" in old else {})
        f = OUT / "fin" / f"{s}.json"
        if not f.exists() or s not in rows:
            continue
        det = json.loads(f.read_text())
        Mx, st = det.get("metrics") or {}, det.get("stock") or {}
        # the daily run's R1 / R2 exemption label (FN.lender_type: "bank", "nbfc", "hfc", "insurer", ... or "")
        lender = st["lender"] if "lender" in st else FN.lender_type(Mx.get("kind"), Mx.get("source"), rows[s].get("sec"), rows[s].get("i"), None)
        nd = gate(det.get("decision") or {}, ver[s], Mx.get("filed"), today, Mx, det.get("levels"), lender, open_issues(s))
        if not nd:
            continue
        was = det["decision"].get("d")
        det["decision"] = nd
        r = rows[s]
        r["dc"], r["vf"] = nd["d"], nd.get("verified")
        r.pop("ic", None)
        if nd.get("incomplete"):  # RULES.md R8: a Buy without the verified badge until the research is complete
            r["ic"] = 1
        r.pop("cand", None)
        if nd.get("candidate"):
            r["cand"] = nd["candidate"]
        try:
            det["verdict"] = r["vd"] = FN.verdict(det["levels"], nd["d"])
        except Exception:  # noqa: BLE001
            pass
        try:  # conviction follows the new decision (same rule as the daily run; shareholding streak from the evening run)
            cv = CV.assess(nd, det["levels"], det.get("setup"), ver[s], det.get("metrics"), today,
                           reader=fwd_rows.get(s), lender=(det.get("stock") or {}).get("lender"),
                           shp={"inst_down_q": (det.get("stock") or {}).get("inst_down_q")},
                           open_issues=sum(1 for x in issues.values() if x.get("symbol") == s and x.get("status") == "open"), sym=s)
        except Exception as e:  # noqa: BLE001
            print(f"[republish] conviction failed for {s}: {e}")
            cv = None
        det["conviction"] = cv
        r.pop("cv", None)
        if cv:
            r["cv"] = cv["level"]
        f.write_text(json.dumps(det, separators=(",", ":"), ensure_ascii=False))
        touched.append(s)
        if was != nd["d"]:
            moved.append(f"{s} {was}->{nd['d']}")
    # "stories studied" follows Claude's runs too, same count as the daily run (owner, 26 Nov 2026: it stayed at 162 all day
    # while 199 stocks had been studied)
    studied = sum(1 for x in th if x in rows)
    if studied != (picks.get("funnel") or {}).get("researched"):
        picks.setdefault("funnel", {})["researched"] = studied
        if not touched:
            (OUT / "picks.json").write_text(json.dumps(picks, separators=(",", ":"), ensure_ascii=False))
    if touched:
        dc = {}
        for p in picks["picks"]:
            dc[p.get("dc")] = dc.get(p.get("dc"), 0) + 1
        picks.setdefault("funnel", {})["decisions"] = dc
        from narrativ import portfolio as PF
        picks["top10"] = PF.top10(picks["picks"])  # a newly passed stock joins the Top 10 at the next poll
        picks["research_updated"] = datetime.now(timezone.utc).isoformat()
        (OUT / "picks.json").write_text(json.dumps(picks, separators=(",", ":"), ensure_ascii=False))
        try:  # the same date's factor history follows the published decisions (narrativ/factors.py)
            from narrativ import factors as FX
            FX.record(picks)
        except Exception as e:  # noqa: BLE001
            print(f"[republish] factor history: {e}")
    # funnel.json carries the same counts (audit 26 Nov 2026: it kept the evening's Buy 29 / researched 199 all day)
    fp = OUT / "funnel.json"
    if fp.exists():
        fj = json.loads(fp.read_text())
        fn = fj.get("funnel") or {}
        new = {k: (picks.get("funnel") or {}).get(k) for k in ("decisions", "researched") if (picks.get("funnel") or {}).get(k) is not None}
        if any(fn.get(k) != v for k, v in new.items()):
            fj["funnel"] = {**fn, **new}
            fp.write_text(json.dumps(fj, ensure_ascii=False, separators=(",", ":")))
    (OUT / "research.json").write_text(json.dumps(research, ensure_ascii=False, separators=(",", ":")))
    rej = {s: len(rep[s]["rejected"]) for s in syms if rep[s]["rejected"]}
    print(f"[republish] {len(syms)} stocks: {', '.join(syms)}; rating changes: {moved or 'none'}; verifier rejections: {rej or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
