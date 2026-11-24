"""Simulation (owner, 24 Nov 2026): what happens to today's "Not rated" stocks under two rule ideas. Changes no rule.

Idea 1: a live code trigger on the Outlook tab (T1-T15 except T4: results beat, estimates up, mutual funds entering,
        promoter buying, revenue acceleration ...) counts as the forward driver, the way a Claude-verified driver does,
        so the decision ladder rates the stock (Hold, or a Buy candidate that still needs Claude's review and the gates).
Idea 2: a stock with no driver of any kind whose levels did not remove it is "Hold: no trigger yet" instead of Not rated.

Stocks with too little filed data ("Not enough data") stay Not rated in both ideas.
Inputs: today's docs/data/picks.json, docs/data/fin/<symbol>.json (levels, metrics, setup) and docs/data/theses.json.
Output: docs/data/sim_notrated.json and docs/research/sim_notrated.md.
python -m narrativ.sim_notrated
"""
import json
from collections import Counter
from datetime import date
from pathlib import Path

from narrativ import funnel as FN

OUT_JSON, OUT_MD = Path("docs/data/sim_notrated.json"), Path("docs/research/sim_notrated.md")


def live_triggers(L: dict) -> list[dict]:
    return [x for x in ((L.get("out") or {}).get("triggers") or []) if x.get("id") != "T4"]


def main() -> None:
    picks = json.loads(Path("docs/data/picks.json").read_text())
    today = date.fromisoformat(picks["date"])
    theses = json.loads(Path("docs/data/theses.json").read_text())
    rows = {p["s"]: p for p in picks["picks"]}
    nr = [s for s, p in rows.items() if p.get("dc") == "Not rated"]
    out = {"date": str(today), "not_rated_now": len(nr), "groups": Counter(), "idea1": Counter(), "idea2": 0,
           "candidates": [], "trigger_ids": Counter(), "errors": 0}
    for s in nr:
        p = rows[s]
        if p.get("vd") == "Not enough data":
            out["groups"]["not enough data (stays Not rated)"] += 1
            continue
        f = Path(f"docs/data/fin/{s}.json")
        if not f.exists():
            out["groups"]["no detail file"] += 1
            continue
        d = json.loads(f.read_text())
        L, Mx = d.get("levels") or {}, d.get("metrics") or {}
        if not all(k in L for k in FN.LEVELS):
            out["groups"]["levels incomplete"] += 1
            continue
        th = dict(theses.get(s) or {})
        live = live_triggers(L)
        if not live:
            out["groups"]["no trigger: idea 2 -> Hold, no trigger yet"] += 1
            out["idea2"] += 1
            continue
        out["groups"]["code trigger: idea 1 rates it"] += 1
        out["trigger_ids"].update({x["id"] for x in live})
        th["drivers"] = list(th.get("drivers") or []) + [{"kind": "signal", "text": f"{x['id']} {x.get('n') or ''}".strip()} for x in live]
        try:
            dec = FN.decision(L, None, th, th.get("scan"), d.get("setup"), p.get("p"), None, today=today, filed=Mx.get("filed"))
            lender = (d.get("stock") or {}).get("lender") or False
            if dec.get("candidate") or dec.get("d") in FN.BUY:
                dec = FN.apply_buy_rules(dec, Mx, lender, L, theses.get(s), today)
        except Exception as e:  # noqa: BLE001
            out["errors"] += 1
            print(f"[sim] {s}: {type(e).__name__}: {e}")
            continue
        label = dec.get("candidate") and f"{dec['candidate']} candidate (needs Claude's review)" or dec.get("d")
        if dec.get("gates"):
            label = f"Hold (scores say Buy, gates fail: {', '.join(g[:2] for g in dec['gates'])})"
        out["idea1"][label] += 1
        if dec.get("candidate"):
            out["candidates"].append({"s": s, "c": p.get("c"), "label": dec["candidate"], "rk": p.get("rk"), "i": p.get("i"),
                                      "mc": p.get("mc"), "vd": p.get("vd"), "triggers": [x["id"] for x in live]})
    out["candidates"].sort(key=lambda x: x.get("rk") or 10 ** 9)
    still = out["groups"]["not enough data (stays Not rated)"] + out["groups"]["no detail file"] + out["groups"]["levels incomplete"] + out["errors"]
    out["not_rated_after"] = still
    out = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in out.items()}
    OUT_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    md = [f"# Not rated: ideas 1 and 2 simulated on {today}", "",
          f"Not rated today: {out['not_rated_now']}. After both ideas: {out['not_rated_after']} (only stocks that cannot be scored).", "",
          "| Group | Stocks |", "|---|---|"] + [f"| {k} | {v} |" for k, v in out["groups"].items()] + [
          "", "## Idea 1: stocks with a code trigger, rated by today's ladder and gates", "", "| New rating | Stocks |", "|---|---|"] + [
          f"| {k} | {v} |" for k, v in sorted(out["idea1"].items(), key=lambda kv: -kv[1])] + [
          "", "Triggers seen: " + ", ".join(f"{k} {v}" for k, v in sorted(out["trigger_ids"].items(), key=lambda kv: -kv[1])), "",
          f"## New Buy candidates for Claude's review ({len(out['candidates'])})", "", "| Rank | Stock | Industry | Rules say | Triggers |", "|---|---|---|---|---|"] + [
          f"| {c['rk']} | {c['c']} | {c['i'] or '–'} | {c['label']} | {', '.join(c['triggers'])} |" for c in out["candidates"]] + [
          "", f"Idea 2: {out['idea2']} stocks become \"Hold: no trigger yet\".", f"Errors: {out['errors']}."]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
