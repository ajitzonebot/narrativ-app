"""Commodity prices that move Indian industries' costs or selling prices (owner, 24 Nov 2026).

Source: World Bank "Pink Sheet" monthly prices (CMO-Historical-Data-Monthly.xlsx, CC BY 4.0), updated in the first
week of each month; the file link is read from the World Bank commodity-markets page. Each NSE basic industry maps to
the commodities that are its main input (-) or its product (+). The signal is the 3-month price change, signed for the
industry: a tailwind or headwind at +-15%. Shown on the stock's dossier and in Claude's pack only: no rule uses it until
the history replay shows it predicts returns (RULES.md).

python -m narrativ.commodities   -> docs/data/commodities.json
"""
import io
import json
import re
from datetime import date
from pathlib import Path

PAGE = "https://www.worldbank.org/en/research/commodity-markets"
CACHE = Path("data/source_cache/pinksheet.xlsx")
OUT = Path("docs/data/commodities.json")
UA = {"User-Agent": "Mozilla/5.0 (personal research; monthly)"}
FLAG = 15.0

# basic industry -> [(series, +1 product / -1 input)]; series are matched on a normalised name prefix
MAP = {
    "Oil Exploration & Production": [("crude oil, brent", 1)],
    "Offshore Support Solution Drilling": [("crude oil, brent", 1)],
    "Paints": [("crude oil, brent", -1)],
    "Tyres & Rubber Products": [("rubber, tsr20", -1), ("crude oil, brent", -1)],
    "Rubber": [("rubber, tsr20", -1)],
    "Airline": [("crude oil, brent", -1)],
    "Lubricants": [("crude oil, brent", -1)],
    "Carbon Black": [("crude oil, brent", -1)],
    "Plastic Products - Consumer": [("crude oil, brent", -1)],
    "Plastic Products - Industrial": [("crude oil, brent", -1)],
    "Packaging": [("crude oil, brent", -1)],
    "Cement & Cement Products": [("coal, australian", -1)],
    "Power Generation": [("coal, australian", -1)],
    "Integrated Power Utilities": [("coal, australian", -1)],
    "Coal": [("coal, australian", 1)],
    "Sponge Iron": [("iron ore", -1), ("coal, australian", -1)],
    "Pig Iron": [("iron ore", -1), ("coal, australian", -1)],
    "Industrial Minerals": [("iron ore", 1)],
    "Aluminium": [("aluminum", 1)],
    "Copper": [("copper", 1)],
    "Zinc": [("zinc", 1)],
    "Cables - Electricals": [("copper", -1), ("aluminum", -1)],
    "Precious Metals": [("gold", 1)],
    "Packaged Foods": [("palm oil", -1)],
    "Personal Care": [("palm oil", -1)],
    "Diversified FMCG": [("palm oil", -1)],
    "Garments & Apparels": [("cotton", -1)],
    "Other Textile Products": [("cotton", -1)],
    "Sugar": [("sugar, world", 1)],
    "Tea & Coffee": [("tea, kolkata", 1)],
    "LPG/CNG/PNG/LNG Supplier": [("liquefied natural gas, japan", -1)],
    "Gas Transmission/Marketing": [("liquefied natural gas, japan", -1)],
}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*†]", "", str(s or ""))).strip().lower()


def _file_url() -> str | None:
    import requests
    r = requests.get(PAGE, headers=UA, timeout=60)
    m = re.search(r'href="([^"]*CMO-Historical-Data-Monthly\.xlsx)"', r.text)
    return m.group(1) if m else None


def fetch(today: date) -> bytes | None:
    """The monthly file, re-downloaded at most once a month (cached in the Actions cache)."""
    import requests
    mark = CACHE.with_suffix(".month")
    if CACHE.exists() and mark.exists() and mark.read_text() == today.strftime("%Y-%m"):
        return CACHE.read_bytes()
    try:
        u = _file_url()
        if not u:
            raise RuntimeError("file link not found on the commodity-markets page")
        r = requests.get(u, headers=UA, timeout=120)
        r.raise_for_status()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(r.content)
        mark.write_text(today.strftime("%Y-%m"))
        return r.content
    except Exception as e:  # noqa: BLE001
        print(f"[commodities] fetch failed: {e}")
        return CACHE.read_bytes() if CACHE.exists() else None


def series(xlsx: bytes) -> dict[str, dict]:
    """Sheet 'Monthly Prices': names on row 5, units on row 6, months (e.g. 2026M10) from row 7 in column A."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True, data_only=True)["Monthly Prices"]
    rows = list(ws.iter_rows(values_only=True))
    names, units = rows[4], rows[5]
    out = {}
    for j, name in enumerate(names):
        if j == 0 or not name:
            continue
        pts = [(str(r[0]), r[j]) for r in rows[6:] if r and r[0] and isinstance(r[j], (int, float))]
        if pts:
            out[_norm(name)] = {"name": str(name).strip(" *"), "unit": str(units[j] or "").strip(), "pts": pts}
    return out


def _find(S: dict, key: str) -> dict | None:
    return next((v for k, v in S.items() if k.startswith(key)), None)


def _chg(pts, n) -> float | None:
    return round((pts[-1][1] / pts[-1 - n][1] - 1) * 100, 1) if len(pts) > n and pts[-1 - n][1] else None


def build(S: dict) -> dict:
    used, ind, missing = {}, {}, set()
    for b, links in MAP.items():
        items = []
        for key, sign in links:
            v = _find(S, key)
            if not v:
                missing.add(key)
                continue
            c3, c12 = _chg(v["pts"], 3), _chg(v["pts"], 12)
            used[v["name"]] = {"unit": v["unit"], "month": v["pts"][-1][0], "last": round(v["pts"][-1][1], 2), "chg3m": c3, "chg12m": c12}
            eff = None if c3 is None else sign * c3
            items.append({"series": v["name"], "role": "product" if sign > 0 else "input", "chg3m": c3, "chg12m": c12,
                          "effect": None if eff is None else "tailwind" if eff >= FLAG else "headwind" if eff <= -FLAG else "neutral"})
        if items:
            ind[b] = items
    month = max((u["month"] for u in used.values()), default=None)
    return {"source": "World Bank Pink Sheet, monthly prices (CC BY 4.0)", "month": month, "flag_pct": FLAG,
            "series": used, "industries": ind, "missing_series": sorted(missing)}


def refresh(today: date) -> dict | None:
    x = fetch(today)
    if not x:
        return None
    out = build(series(x))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"[commodities] {out['month']}: {len(out['series'])} series, {len(out['industries'])} industries"
          + (f"; not found: {', '.join(out['missing_series'])}" if out["missing_series"] else ""))
    return out


def for_industry(cm: dict | None, basic: str | None) -> list[dict] | None:
    return ((cm or {}).get("industries") or {}).get(basic or "") or None


if __name__ == "__main__":
    refresh(date.today())
