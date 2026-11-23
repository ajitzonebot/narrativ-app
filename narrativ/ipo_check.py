"""Validates docs/data/ipo_today.json (IPO.md). Recomputes implied listing and GMP %, final day, and drops what the rules forbid."""
import json
from pathlib import Path

F = Path("docs/data/ipo_today.json")
TOP10_SUB = 2.0


def check(d: dict) -> tuple[dict, list]:
    errs, keep = [], []
    today = d.get("date")
    for i in d.get("actionable") or []:
        n = i.get("name", "?")
        miss = [k for k in ("name", "board", "price_high", "open_date", "last_date", "action", "rating", "key_risk") if not i.get(k)]
        if miss:
            errs.append(f"{n}: missing {miss}"); continue
        if i["last_date"] < today:
            errs.append(f"{n}: closed on {i['last_date']}: not actionable (removed)"); continue
        if i["open_date"] > today:
            errs.append(f"{n}: opens {i['open_date']}: not actionable (removed)"); continue
        i["final_day"] = i["last_date"] == today
        if i.get("action") == "SELECTIVE APPLY" and not i.get("missing"):
            errs.append(f"{n}: SELECTIVE APPLY needs 'missing'")
        lo, hi, up = i.get("gmp_low"), i.get("gmp_high"), i["price_high"]
        obs = str(i.get("gmp_observed") or "")
        i["gmp_stale"] = not obs.startswith(today)
        if lo is not None and hi is not None and up:
            i["implied_low"], i["implied_high"] = up + lo, up + hi
            i["gmp_pct_low"], i["gmp_pct_high"] = round(lo / up * 100, 1), round(hi / up * 100, 1)
            if i["gmp_pct_high"] < 15 and i["action"] == "APPLY":
                errs.append(f"{n}: GMP below 15% cannot be APPLY (set to SELECTIVE APPLY)"); i["action"] = "SELECTIVE APPLY"
                i.setdefault("missing", []).append("GMP cushion below the 15% target")
        if i["gmp_stale"] and i["action"] == "APPLY":
            errs.append(f"{n}: GMP not observed today: APPLY downgraded to WAIT"); i["action"] = "WAIT"
        sub = (i.get("subscription") or {}).get("overall")
        # Top 10 for today (feedback, 16 Nov): open now, SAFE, APPLY, at least 2x subscribed overall at the last check
        i["top10"] = i["rating"] == "SAFE" and i["action"] == "APPLY" and sub is not None and sub >= TOP10_SUB
        keep.append(i)
    d["actionable"] = keep
    return d, errs


if __name__ == "__main__":
    d, errs = check(json.loads(F.read_text()))
    F.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    for e in errs:
        print("-", e)
    print(f"{len(d['actionable'])} actionable, {len(errs)} notes")
