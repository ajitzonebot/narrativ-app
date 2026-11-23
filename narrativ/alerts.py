"""Push alerts to the ntfy Android app (https://ntfy.sh). Set NTFY_TOPIC secret to enable.
Sends: bad-news filings, verdict changes, stocks entering a breakout setup, checkpoints that became due."""
import json
import os
from pathlib import Path

import requests

STATE = Path("data/alert_state.json")


def send(picks: list[dict], due: list | None = None, changes: list | None = None, events: list | None = None) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    cur, msgs = {}, []
    for p in picks:
        sym, su = p["s"], p.get("su")
        cur[sym] = su
        if su == "Breakout" and prev.get(sym) != "Breakout":
            msgs.append(f"{p['c']} breakout setup @ {p['p']} · {p['vd']}")
    for sym, v in changes or []:
        msgs.append(f"{sym.rpartition('.')[0]}: {v.get('from')} → {v['v']} ({v.get('cause')})")
    for sym, e in events or []:
        msgs.insert(0, f"⚠ {sym.rpartition('.')[0]}: {e['type']} ({e.get('date')}) {e.get('text', '')[:80]}")
    for sym, c in due or []:
        msgs.append(f"{sym.rpartition('.')[0]} checkpoint due: {c['what']} ({c['due']})")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(cur))
    if not topic:
        print("[alerts] NTFY_TOPIC not set, skipping")
        return
    if not msgs:
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    try:
        requests.post(f"{server}/{topic}", data="\n".join(msgs[:20]).encode(),
                      headers={"Title": f"Narrativ: {len(msgs)} update(s)", "Tags": "chart_with_upwards_trend"}, timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"[alerts] failed: {e}")
