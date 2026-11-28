"""False alarms by rule (owner, 28 Nov 2026: "on the false positive errors, is it getting logged in feedback loop").

docs/data/false_alarms.json, written by the daily run from verified research:
  - subject-line flags (A2, A4, A5, G1-G4; narrativ/announcements.py): flag_reviews confirmed = real, dismissed = false alarm
  - typed filings (narrativ/events.py RULES, red and watch): news_reviews real / false_alarm, matched to the stored event by url
by_rule: {rule: {"real", "false", "rate" (false share), "examples": newest false alarms first (stock, date, text, why, url)}}
repeat: rules with 2 or more false alarms, worst first: the weekly task (tasks/weekly.md) proposes a rule fix for each.
"""
EXAMPLES = 5


def build(theses: dict, events: dict, today: str) -> dict:
    """theses: verified research by symbol; events: {symbol: stored events (url, type, sev, text, date)}."""
    rules: dict[str, dict] = {}

    def add(rule, real, ex):
        r = rules.setdefault(rule, {"real": 0, "false": 0, "examples": []})
        if real:
            r["real"] += 1
        else:
            r["false"] += 1
            r["examples"].append(ex)
    for s, th in theses.items():
        for fid, fr in (th.get("flag_reviews") or {}).items():
            if (fr or {}).get("verdict") in ("confirmed", "dismissed"):
                add(f"flag {fid}", fr["verdict"] == "confirmed",
                    {"s": s, "date": fr.get("date"), "why": fr.get("note"), "url": fr.get("source")})
        by_url = {e.get("url"): e for e in events.get(s) or [] if e.get("url")}
        for nr in th.get("news_reviews") or []:
            e = by_url.get(nr.get("url")) or {}
            add(f"event {e.get('type') or 'unknown'}", nr.get("verdict") == "real",
                {"s": s, "date": e.get("date") or nr.get("filed"), "text": (e.get("text") or "")[:160], "why": nr.get("why"), "url": nr.get("url")})
    for r in rules.values():
        n = r["real"] + r["false"]
        r["rate"] = round(r["false"] / n, 2) if n else None
        r["examples"] = sorted(r["examples"], key=lambda x: str(x.get("date") or ""), reverse=True)[:EXAMPLES]
    repeat = sorted((k for k, r in rules.items() if r["false"] >= 2), key=lambda k: (-rules[k]["false"], k))
    return {"date": today, "by_rule": dict(sorted(rules.items())), "repeat": repeat}
