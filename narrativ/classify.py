"""Industry classification from BSE (the 4-level scheme NSE and BSE share): macro sector > sector > industry > basic industry.
Per-stock BSE meta info (bse library, equityMetaInfo), keyed by ISIN in data/classification.json (in git, small).
Fetched once per company; each run re-checks the oldest REFRESH_PER_RUN entries (older than MAX_AGE_DAYS) for reclassifications.
Companies with no BSE listing keep a mapped value (from their old Yahoo industry, see build_nse_only) or stay unclassified."""
import json
import time
from datetime import date
from pathlib import Path

STORE = Path("data/classification.json")
MAX_AGE_DAYS = 120
REFRESH_PER_RUN = 60


def load() -> dict:
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def save(st: dict) -> None:
    STORE.write_text(json.dumps(st, indent=0, sort_keys=True, ensure_ascii=False))


def _meta(b, code: str) -> dict | None:
    x = b.equityMetaInfo(str(code)) or {}
    if not x.get("Sector") and not x.get("ISubGroup"):
        return None
    return {"m": x.get("Sector") or None, "s": x.get("IndustryNew") or None, "i": x.get("IGroup") or None,
            "b": x.get("ISubGroup") or x.get("Industry") or None, "src": "BSE", "d": date.today().isoformat()}


def refresh(rows: list[dict], max_minutes: float = 4) -> dict:
    """rows: universe rows with isin and bse_code. New companies first, then the oldest entries."""
    st = load()
    todo_new = [r for r in rows if r.get("isin") and r.get("bse_code") and r["isin"] not in st]
    old = sorted([r for r in rows if r.get("isin") in st and st[r["isin"]].get("src") == "BSE" and r.get("bse_code")
                  and (date.today() - date.fromisoformat(st[r["isin"]]["d"])).days > MAX_AGE_DAYS], key=lambda r: st[r["isin"]]["d"])
    todo = todo_new + old[:REFRESH_PER_RUN]
    if not todo:
        return st
    t0, got, fail = time.time(), 0, 0
    try:
        from bse import BSE
        with BSE(download_folder=Path("data/exchange_tmp")) as b:
            for r in todo:
                if time.time() - t0 > max_minutes * 60:
                    break
                try:
                    m = _meta(b, r["bse_code"])
                except Exception as e:  # noqa: BLE001
                    m = None
                    if fail < 3:
                        print(f"[classify] {r.get('symbol')}: {e}")
                if m:
                    st[r["isin"]] = m
                    got += 1
                else:
                    fail += 1
    except Exception as e:  # noqa: BLE001
        print(f"[classify] BSE session failed: {e}")
    save(st)
    print(f"[classify] {got} classified ({len(todo_new)} new, {min(len(old), REFRESH_PER_RUN)} re-checked), {fail} without data, "
          f"{time.time() - t0:.0f}s; {len(st)} companies stored")
    return st
