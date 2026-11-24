"""Publish Claude's research within minutes instead of at the evening run.

Runs after each research push (.github/workflows/republish.yml). For the stocks whose entry in docs/data/theses.json changed:
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
    an open data issue (docs/data/data_issues.json) holds."""
    nd = _verify(dec, v, filed, today)
    if L is None or not (dec.get("candidate") or dec.get("d") in BUY):
        return nd
    base = nd or dec
    ruled = FN.apply_buy_rules(base, Mx or {}, lender, L, v, today, issues)
    return ruled if (nd is not None or ruled != base) else None


def _verify(dec: dict, v: dict, filed: str | None, today) -> dict | None:
    label = dec.get("candidate") or (dec.get("d") if dec.get("d") in BUY else None)
    if not label:
        return None  # rules did not say Buy: the review informs, it does not change the rating
    ver = FN.verification(v.get("audit"), filed, today, dec.get("call_since"))  # same latest-call rule as the daily run
    why = [w for w in dec.get("why") or [] if not w.startswith(("Rules say", "Verified by Claude", "Independent audit", "Audit issue"))]
    if v.get("data_issues"):
        return {**dec, "d": "Hold", "candidate": label, "verified": ver["state"],
                "why": [f"Rules say {label}, but Claude found a number to correct: "
                        + ", ".join(str(x.get("field")) for x in v["data_issues"][:3]) + " (re-scored at the evening run)"] + why}
    if ver["state"] == "pass":
        d = {**dec, "d": label, "verified": "pass", "why": why + [f"Verified by Claude's full review on {ver['date']}"]}
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
                "why": [f"Rules say {label}: waiting for Claude's full review"] + [w for w in why if not w.startswith("Verified by Claude")],
                "missing": [m for m in dec.get("missing") or [] if not m.startswith("Verification pending")]
                + ["Verification pending: queued for Claude's full review" + (f" ({ver['why']})" if ver.get("why") else "")]}
    return None


def open_issues(sym: str) -> list:
    """Open data issues that hold this stock from Buy: the daily run's own rule (corrections.apply on its filings)."""
    from narrativ import corrections as CORR, filings
    try:
        return CORR.apply({sym: filings.load(sym)})[2].get(sym) or []
    except Exception as e:  # noqa: BLE001
        print(f"[republish] data issues check failed for {sym}: {e}")
        return []


def main(before: str | None) -> None:
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
        r.pop("cand", None)
        if nd.get("candidate"):
            r["cand"] = nd["candidate"]
        try:
            det["verdict"] = r["vd"] = FN.verdict(det["levels"], nd["d"])
        except Exception:  # noqa: BLE001
            pass
        try:  # conviction follows the new decision (same rule as the daily run; shareholding streak from the evening run)
            cv = CV.assess(nd, det["levels"], det.get("setup"), ver[s], det.get("metrics"), today,
                           reader=fwd_rows.get(s),
                           open_issues=sum(1 for x in issues.values() if x.get("symbol") == s and x.get("status") == "open"))
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
    if touched:
        dc = {}
        for p in picks["picks"]:
            dc[p.get("dc")] = dc.get(p.get("dc"), 0) + 1
        picks.setdefault("funnel", {})["decisions"] = dc
        from narrativ import portfolio as PF
        picks["top10"] = PF.top10(picks["picks"])  # a newly passed stock joins the Top 10 within minutes
        picks["research_updated"] = datetime.now(timezone.utc).isoformat()
        (OUT / "picks.json").write_text(json.dumps(picks, separators=(",", ":"), ensure_ascii=False))
    (OUT / "research.json").write_text(json.dumps(research, ensure_ascii=False, separators=(",", ":")))
    rej = {s: len(rep[s]["rejected"]) for s in syms if rep[s]["rejected"]}
    print(f"[republish] {len(syms)} stocks: {', '.join(syms)}; rating changes: {moved or 'none'}; verifier rejections: {rej or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
