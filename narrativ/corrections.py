"""The loop's correction step: a wrong number Claude found in a review (logged in docs/data/data_issues.json, quote-verified)
replaces our value on the next run, and the stock is re-scored with it.

Balance-sheet inputs (equity, borrowings, lease liabilities, cash) are written into the latest balance sheet before the
metrics are computed, so every ratio that uses them changes consistently. Other fields (sums over quarters, derived figures)
cannot be patched safely: while such an issue is open the stock cannot be shown as Buy (decision capped at Hold).
A correction stays in force until the pipeline itself reads the same value from the filing (then it is no longer needed)."""
import copy
import json
from pathlib import Path

REG = Path("docs/data/data_issues.json")
CR = 1e7
BS = {"equity_cr": (("equity",), ()), "borrowings_cr": (("borr_ncur",), ("borr_cur",)),
      "lease_liabilities_cr": (("lease_ncur",), ("lease_cur",)), "cash_cr": (("cash",), ("bank_bal",))}


# the quote is in the filing's own unit (the verifier requires found_value to appear in it): convert to ₹ crore here
_SCALE = {"cr": 1, "crs": 1, "crore": 1, "crores": 1, "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01, "mn": 0.1,
          "million": 0.1, "millions": 0.1, "bn": 100, "billion": 100, "billions": 100, "thousand": 1e-4, "thousands": 1e-4,
          "000": 1e-4, "000s": 1e-4, "'000": 1e-4}
_CURRENCY = {"rs", "inr", "rupee", "rupees", "₹"}
_FILLER = {"in", "of"}


def to_cr(value, unit) -> float | None:
    """found_value in its logged unit -> ₹ crore; None for a unit we cannot read (the issue then blocks instead of patching).

    "₹ lakh", "Rs. in lakhs", "INR mn", "crore" -> scaled by that word. A currency with no scale word ("INR", "Rs.", "₹",
    "rupees") is plain rupees (÷ 10^7). A blank unit is NOT read as crore: it cannot be told apart from a forgotten unit,
    and guessing wrong moves the number 10^2-10^7x, so it returns None and the issue holds the stock instead of patching."""
    u = str(unit or "").lower().replace("₹", " ₹ ").replace("rs.", " rs ").replace("(", " ").replace(")", " ").replace(",", " ")
    words = [w.strip(" .'") or w for w in u.split()]
    words = [w for w in words if w and w not in _FILLER]
    scale = [_SCALE[w] for w in words if w in _SCALE]
    other = [w for w in words if w not in _SCALE and w not in _CURRENCY]
    if other or len(scale) > 1:
        return None
    if scale:
        return float(value) * scale[0]
    if any(w in _CURRENCY for w in words):
        return float(value) * 1e-7
    return None


def _key(field: str) -> str:
    return str(field or "").split(".")[-1]


def load() -> dict:
    try:
        return (json.loads(REG.read_text()) if REG.exists() else {}).get("issues") or {}
    except Exception:  # noqa: BLE001
        return {}


def apply(fins: dict) -> tuple[dict, dict, dict]:
    """-> (fins with corrections applied, {symbol: [applied]}, {symbol: [open issues that block a Buy]})."""
    applied, blocking = {}, {}
    out = dict(fins)
    for iid, r in load().items():
        if r.get("status") not in ("open", "corrected") or r.get("found_value") is None:
            continue
        s, k = r.get("symbol"), _key(r.get("field"))
        try:
            fv = float(r["found_value"])
        except (TypeError, ValueError):
            continue
        if k.endswith("_cr"):
            fv = to_cr(fv, r.get("unit"))
            if fv is None:  # unknown unit: never patch with a guess; hold the stock instead
                if r.get("status") == "open":
                    blocking.setdefault(s, []).append({"id": iid, "field": r.get("field"), "found": r.get("found"), "app": r.get("app"),
                                                       "why": f"unit '{r.get('unit')}' not readable"})
                continue
        rec = fins.get(s)
        if k in BS and rec and rec.get("quarters"):
            if s not in applied:
                out[s] = rec = copy.deepcopy(rec)
            basis = rec.get("basis")
            for qe in sorted(rec["quarters"], reverse=True):
                p = rec["quarters"][qe].get(basis) or next(iter(rec["quarters"][qe].values()))
                bs = p.get("bs") or {}
                if bs.get("equity") is not None:
                    put, zero = BS[k]
                    old = sum((bs.get(x) or 0) for x in put + zero) / CR
                    if abs(old - fv) <= 0.05 * max(abs(fv), 1e-9):
                        break  # the pipeline already reads the filed value: correction no longer needed (issue closes as fixed)
                    bs[put[0]] = fv * CR
                    for z in zero:
                        bs[z] = 0.0
                    p.setdefault("flags", []).append(f"corrected from filing: {k.replace('_cr', '').replace('_', ' ')} ₹{fv:,.2f} cr "
                                                     f"(we had ₹{old:,.2f} cr); see data issue {iid}")
                    applied.setdefault(s, []).append({"id": iid, "field": k, "was": round(old, 2), "now": fv, "quarter": qe})
                    break
        elif r.get("status") == "open":
            blocking.setdefault(s, []).append({"id": iid, "field": r.get("field"), "found": r.get("found"), "app": r.get("app")})
    if applied or blocking:
        print(f"[corrections] applied {sum(len(v) for v in applied.values())} to {len(applied)} stocks; "
              f"{sum(len(v) for v in blocking.values())} open issues hold {len(blocking)} stocks back from Buy")
    return out, applied, blocking
