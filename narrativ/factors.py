"""Factor check (alphalens-style, own code): do our scores predict returns? Uses the daily picks.json snapshots in git
history (each day's scores and closes for every scored stock) and measures, for each score:

  IC   rank correlation (Spearman) between the score on a day and the stock's return over the next h snapshots,
       averaged over start days; > 0 means higher scores were followed by higher returns
  spread  average return of the top fifth by score minus the bottom fifth
  hit  share of start days with IC > 0

and the average forward return by decision (Strong Buy .. Strong Sell) minus the universe average. Horizons are in daily
snapshots (trading days). Few start days = noise: `conclusive` needs MIN_DATES start days per horizon.
Output docs/data/factors.json; read by the weekly review (rules change only on repeated evidence, RULES.md).
python -m narrativ.factors   (needs the full commit history of docs/data/picks.json: fetch-depth 0, `filter: blob:none` is fine)
"""
import json
import subprocess
from pathlib import Path

import pandas as pd

OUT = Path("docs/data/factors.json")
HORIZONS = (1, 5, 10, 20, 60)
MIN_STOCKS, MIN_DATES = 30, 20
DEC = {"Strong Buy": 2, "Buy": 1, "Hold": 0, "Sell": -1, "Strong Sell": -2}


KEEP = ("s", "p", "rk", "pr", "dc", "sc")  # the only pick fields the factor check reads


def slim(d: dict) -> dict:
    """One day's picks.json reduced to what frames() needs: a 1.3 MB document becomes ~0.25 MB, and the parsed original is freed."""
    return {"date": d.get("date"), "level_names": d.get("level_names") or {},
            "picks": [{k: r[k] for k in KEEP if k in r} for r in d.get("picks") or []]}


def _prefetch(shas: list[str]) -> None:
    """In a blobless clone (checkout filter: blob:none) fetch every picks.json blob in a few batches instead of one request per
    `git show`. Best effort: without it git still fetches each blob on demand."""
    try:
        blobs = []
        for h in shas:
            r = subprocess.run(["git", "rev-parse", f"{h}:docs/data/picks.json"], capture_output=True, text=True)
            if r.returncode == 0:
                blobs.append(r.stdout.strip())
        for i in range(0, len(blobs), 100):
            subprocess.run(["git", "fetch", "--no-tags", "--no-write-fetch-head", "origin", *blobs[i:i + 100]],
                           capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        print(f"[factors] prefetch skipped: {e}")


def snapshots() -> dict[str, dict]:
    """{date: slim picks.json} from git history, the last commit of each data date."""
    shas = subprocess.run(["git", "log", "--format=%H", "--", "docs/data/picks.json"], capture_output=True, text=True,
                          check=True).stdout.split()
    if subprocess.run(["git", "config", "--get", "remote.origin.promisor"], capture_output=True, text=True).stdout.strip() == "true":
        _prefetch(shas)
    out = {}
    for h in reversed(shas):  # oldest first: a later commit of the same date wins
        try:
            d = json.loads(subprocess.run(["git", "show", f"{h}:docs/data/picks.json"], capture_output=True, text=True,
                                          check=True).stdout)
        except Exception:  # noqa: BLE001
            continue
        if d.get("date") and d.get("picks"):
            out[d["date"]] = slim(d)
    return dict(sorted(out.items()))


def frames(snaps: dict) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Prices (dates x stocks) and one frame per factor (dates x stocks)."""
    names = None
    px, fac = {}, {}
    for dt, d in snaps.items():
        names = names or list((d.get("level_names") or {}).keys())
        rows = d["picks"]
        px[dt] = {r["s"]: r.get("p") for r in rows if r.get("p")}
        f = {"readiness (rank, best first)": {r["s"]: -r["rk"] for r in rows if r.get("rk")},
             "overall priority": {r["s"]: r.get("pr") for r in rows if r.get("pr") is not None},
             "decision": {r["s"]: DEC[r["dc"]] for r in rows if r.get("dc") in DEC}}
        for i, k in enumerate(names or []):  # keyed by level id: display names changed over time
            f[f"level:{k}"] = {r["s"]: r["sc"][i] for r in rows if len(r.get("sc") or []) > i and r["sc"][i] is not None}
        for k, v in f.items():
            fac.setdefault(k, {})[dt] = v
    P = pd.DataFrame(px).T.sort_index()
    return P, {k: pd.DataFrame(v).T.reindex(P.index) for k, v in fac.items()}


def measure(P: pd.DataFrame, F: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for name, X in F.items():
        out[name] = {}
        for h in HORIZONS:
            fwd = P.shift(-h) / P - 1
            ics, spreads = [], []
            for dt in P.index[:-h] if h < len(P) else []:
                x, y = X.loc[dt], fwd.loc[dt]
                ok = x.notna() & y.notna()
                if ok.sum() < MIN_STOCKS or x[ok].nunique() < 3:
                    continue
                if y[ok].nunique() < 3:
                    continue
                ics.append(x[ok].rank().corr(y[ok].rank()))
                q = pd.qcut(x[ok].rank(method="first"), 5, labels=False)
                spreads.append((y[ok][q == 4].mean() - y[ok][q == 0].mean()) * 100)
            n = len(ics)
            out[name][f"{h}d"] = {"dates": n, "ic": round(float(pd.Series(ics).mean()), 3) if n else None,
                                  "hit_pct": round(100 * sum(i > 0 for i in ics) / n) if n else None,
                                  "spread_pct": round(float(pd.Series(spreads).mean()), 2) if n else None,
                                  "conclusive": n >= MIN_DATES}
    return out


def by_decision(P: pd.DataFrame, D: pd.DataFrame) -> dict:
    out = {}
    inv = {v: k for k, v in DEC.items()}
    for h in HORIZONS:
        fwd = (P.shift(-h) / P - 1) * 100
        rows = []
        for dt in P.index[:-h] if h < len(P) else []:
            y, d = fwd.loc[dt], D.loc[dt]
            ok = y.notna() & d.notna()
            if ok.sum() < MIN_STOCKS:
                continue
            avg = y[ok].mean()
            for v, g in y[ok].groupby(d[ok]):
                rows.append((inv[int(v)], g.mean() - avg, len(g)))
        if rows:
            df = pd.DataFrame(rows, columns=["d", "ex", "n"])
            out[f"{h}d"] = {k: {"vs_universe_pct": round(float(g["ex"].mean()), 2), "stock_days": int(g["n"].sum()),
                                "dates": len(g)} for k, g in df.groupby("d")}
    return out


def run() -> dict:
    snaps = snapshots()
    P, F = frames(snaps)
    res = {"dates": [P.index[0], P.index[-1]] if len(P) else [], "snapshots": len(P), "min_dates": MIN_DATES,
           "note": "IC > 0: higher score, higher next returns. Not conclusive until a horizon has min_dates start days.",
           "factors": measure(P, F), "by_decision": by_decision(P, F["decision"])}
    names = (list(snaps.values())[-1].get("level_names") or {}) if snaps else {}
    res["factors"] = {(f"level: {names.get(k[6:], k[6:])}" if k.startswith("level:") else k): v for k, v in res["factors"].items()}
    OUT.write_text(json.dumps(res, indent=1))
    for k, v in res["factors"].items():
        print(f"[factors] {k}: " + ", ".join(f"{h} IC {x['ic']} ({x['dates']}d)" for h, x in v.items() if x["dates"]))
    return res


if __name__ == "__main__":
    run()
