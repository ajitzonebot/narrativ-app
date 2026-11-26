"""The app's 'Narrativ' sheet: a company's story in plain words, on one screen (owner, 25 Nov 2026; first version).

Who writes what (split agreed with the owner):
- What they do + How they make money: a free model (Gemini Flash-Lite 3.1, Gemma 4 as fallback; the reader keeps
  3.5 Flash-Lite and 3.8 Flash), from the company description and the plans already extracted. Written once per stock,
  rewritten yearly or when the description changes. `python -m narrativ.story --write` (story.yml, mornings IST when
  the free tier is least busy), resumable: stocks that matter first (Buys, candidates, the review queue, then rank).
- How it's going: code, from the latest results (profit and revenue vs the same quarter a year ago) and cash conversion
  (cash from operations / EBITDA over the full years; owner 26 Nov 2026, feedback #113).
- Plans to grow: Claude's dated drivers, else the reader's quoted plans; the model's plain rewording when it has one.
- What could go wrong: Claude's kill switches (researched stocks only in this version).
- In one line: code, a phrase set from the stability / quality / valuation / momentum tiers.
Checks on model text: length caps (one screen), no number that is not in the facts, no banned jargon; a failed text is
not stored. Store: data/story.json (committed, small). The daily run puts `narrativ` on each dossier.
"""
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
STORE = Path("data/story.json")
# Order is the owner's pick after the side-by-side test (--compare); STORY_MODELS (comma list) overrides it for a run.
MODELS = [m for m in os.environ.get("STORY_MODELS", "gemini-3.1-flash-lite,gemma-4-31b-it,gemma-4-26b-a4b-it,gemini-flash-lite-latest").split(",") if m]
COMPARE = ["gemma-4-31b-it", "gemini-3.1-flash-lite"]  # the side-by-side test (owner, 26 Nov 2026)
CAPS = {"what": 240, "money": 170, "plan": 80, "line": 120}
BANNED = re.compile(r"\b(AUM|capex|consolidated|EBITDA|PAT|YoY|QoQ|bps|basis points|guidance|guided|synerg\w*|leverag\w*|robust|"
                    r"diversified portfolio|value chain|end-to-end|solutions provider)\b", re.I)
EXAMPLE = {"what": "A microfinance company. It lends small amounts to women in villages and small towns so they can run a shop, "
                   "buy livestock or grow a small business. A fifth of its loans are now small-business and home loans.",
           "money": "Interest. It borrows from banks at a lower rate and lends at a higher one; the gap, less loans that go bad, is its profit.",
           "plans": ["Grow its loans by 20-25% this year", "Reach ₹32,000 crore of loans by 2030"]}


# ---------------------------------------------------------------- code-written sections
def going(m: dict) -> dict | None:
    def v(k):
        x = m.get(k)
        return x.get("v") if isinstance(x, dict) else None
    r, pr = v("rev_yoy_pct"), v("pat_yoy_pct")
    if r is None and pr is None:
        return None
    w = lambda x, what: f"{what} {'up' if x >= 0 else 'down'} {abs(x):.0f}%"  # noqa: E731
    parts = [w(pr, "Profit") if pr is not None else None, w(r, "revenue" if pr is not None else "Revenue") if r is not None else None]
    text = " and ".join(x for x in parts if x) + " on the same quarter last year."
    # feedback #113 (owner, 26 Nov 2026): cash conversion too, the same figure as the Quality tab's check (cash from
    # operations / EBITDA over the full years filed); not shown for lenders and insurers, where it does not apply
    from narrativ.funnel import cash_conversion
    cc, yrs = cash_conversion(m)
    if cc is not None:
        text += f" {cc:.0f}% of its operating profit came in as cash" + (f" over {yrs} years." if yrs else ".")
    return {"text": text, "tone": "good" if (pr if pr is not None else r) >= 0 else "bad"}


def one_line(t) -> str | None:
    """Phrase set from the tiers (1 best .. 5 worst; 0 = not enough data)."""
    t = (list(t or []) + [0] * 7)[:7]
    st, q, va, mo = t[0], t[1], t[2], t[4]
    if not q and not va:
        return None
    biz = {1: "A strong business", 2: "A strong business", 3: "A decent business", 4: "A weak business", 5: "A weak business"}.get(q, "A business we can't judge yet")
    if st in (4, 5):
        biz += " with a shaky balance sheet"
    price = {1: " at a cheap price", 2: " at a cheap price", 3: " at a fair price", 4: " at a rich price", 5: " at a very rich price"}.get(va, "")
    good = q in (1, 2) or va in (1, 2)
    mood = {1: ", and the market is buying in.", 2: ", and the market is starting to notice.", 3: ", and the price is starting to move.",
            4: (", but the price is going nowhere yet." if good else ", and the price is going nowhere."),
            5: (", but the price is weak." if good else ", and the price is weak.")}.get(mo, ".")
    return biz + price + mood


def plans_of(sym: str, theses: dict, forward: dict) -> list[dict]:
    th = theses.get(sym) or {}
    out = [{"text": x.get("text"), "due": x.get("due"), "quote": x.get("quote"), "source": x.get("source")}
           for x in th.get("drivers") or [] if x.get("text")]
    if not out:
        f = forward.get(sym) or {}
        out = [{"text": x.get("text"), "due": x.get("due"), "quote": x.get("quote"), "source": f.get("url")}
               for x in f.get("items") or [] if x.get("kind") in ("guidance", "capacity", "order", "demand", "product") and x.get("text")]
    return out[:4]


def risks_of(sym: str, theses: dict) -> list[str]:
    return [x["text"] for x in (((theses.get(sym) or {}).get("scan") or {}).get("kill_switches") or []) if x.get("text")][:2]


# ---------------------------------------------------------------- model-written sections
def _nums(s) -> set:
    out = set()
    s = re.sub(r"\bFY\s?'?(\d{2})\b", lambda m: f"FY{m.group(1)} 20{m.group(1)}", str(s or ""), flags=re.I)  # "FY27" is also 2027
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", s):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def check(out: dict, facts_text: str) -> list[str]:
    """Problems with a model's answer (empty = keep it)."""
    have, bad = _nums(facts_text), []
    for k in ("what", "money"):
        s = str(out.get(k) or "").strip()
        if not s:
            bad.append(f"{k} empty")
        elif len(s) > CAPS[k]:
            bad.append(f"{k} too long ({len(s)})")
    for s in [out.get("what"), out.get("money")] + list(out.get("plans") or []):
        if BANNED.search(str(s or "")):
            bad.append(f"jargon: {BANNED.search(str(s)).group(0)}")
        for v in _nums(s):
            if v > 12 and v not in have and not any(abs(v - h) < 1 for h in have):
                bad.append(f"number not in facts: {v:g}")
    for s in out.get("plans") or []:
        if len(str(s)) > CAPS["plan"]:
            bad.append(f"plan too long ({len(str(s))})")
    return bad


def check_line(line, facts_text: str) -> list[str]:
    """The model's one-line story (kept apart: a bad line is dropped, the code phrase stays)."""
    s, have, bad = str(line or "").strip(), _nums(facts_text), []
    if not s:
        return ["line empty"]
    if len(s) > CAPS["line"]:
        bad.append(f"line too long ({len(s)})")
    if BANNED.search(s):
        bad.append(f"jargon: {BANNED.search(s).group(0)}")
    if re.search(r"\b(buy|sell|must|should|will (?:rise|double|grow)|multibagger|guaranteed?)\b", s, re.I):
        bad.append("advice or prediction")
    for v in _nums(s):
        if v > 12 and v not in have and not any(abs(v - h) < 1 for h in have):
            bad.append(f"number not in facts: {v:g}")
    return bad


def prompt(name: str, industry: str | None, desc: str, plans: list[dict], verdict: str | None = None, fix: str | None = None) -> str:
    return f"""You write the 'story' sheet of an Indian stock app for ordinary people who are not investors.
Write like this example (another company), same length and style: {json.dumps(EXAMPLE, ensure_ascii=False)}
Rules: plain everyday words; say concretely what it sells and to whom; no jargon (never: AUM, capex, consolidated, EBITDA,
guidance, leverage, synergy, robust, value chain); if a technical word is unavoidable, explain it in 2-3 words in brackets;
do not copy the description's wording; do not praise, predict or advise; use only facts below; never add a number that is not below.
Company: {name} ({industry or 'industry not known'})
Description: {desc}
Plans management stated: {json.dumps([p['text'] for p in plans], ensure_ascii=False)}
Our verdict in words (do not change its judgement, do not add one): {verdict or 'none'}
Return JSON only: {{"what": "max {CAPS['what']} characters", "money": "max {CAPS['money']} characters",
"plans": ["each plan above reworded plainly, max {CAPS['plan']} characters, keep its numbers and dates, at most 2"],
"line": "one sentence, max {CAPS['line']} characters: what the company is, in a few words, joined to our verdict above; no advice, no prediction"}}""" + (f"\nYour last answer broke these limits; rewrite shorter: {fix}" if fix else "")


def ask(key: str, model: str, text: str) -> tuple[dict | None, str | None]:
    import requests
    body = {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"temperature": 0.2}}
    if not model.startswith("gemma"):
        body["generationConfig"]["responseMimeType"] = "application/json"
    for wait in (0, 15, 45):  # 503 = the free model is busy: wait and try again
        time.sleep(wait)
        try:
            r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=180)
        except requests.RequestException as e:
            return None, f"request: {str(e)[:80]}"
        if r.status_code != 503:
            break
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        # Gemma 4 can return its thinking as a first part (thought=true): use the answer parts only
        parts = r.json()["candidates"][0]["content"]["parts"]
        t = "".join(p.get("text", "") for p in parts if not p.get("thought")) or "".join(p.get("text", "") for p in parts)
        return json.loads(t[t.find("{"): t.rfind("}") + 1]), None
    except Exception as e:  # noqa: BLE001  keep the start of the answer so a format problem can be seen in the test file
        raw = ""
        try:
            raw = json.dumps(r.json()["candidates"][0]["content"]["parts"])[:160]
        except Exception:  # noqa: BLE001
            pass
        return None, f"parse: {str(e)[:40]} | {raw}"


def attempt(key: str, m: str, p: dict, desc: str, plans: list[dict], facts: str, verdict: str | None):
    """One model's answer for one stock, checked; when the only problems are lengths, one more try asking it to shorten."""
    out, err = ask(key, m, prompt(p.get("n") or p["s"], p.get("i"), desc, plans, verdict))
    if err:
        return None, [], err
    bad = check(out or {}, facts)
    if bad and all("too long" in b for b in bad):
        time.sleep(4)
        out2, err2 = ask(key, m, prompt(p.get("n") or p["s"], p.get("i"), desc, plans, verdict, fix="; ".join(bad)))
        if not err2:
            bad2 = check(out2 or {}, facts)
            if not bad2:
                return out2, [], None
    return out, bad, None


def compare(n: int = 30) -> None:
    """Side-by-side test (owner, 26 Nov 2026): the same stocks written by each COMPARE model, checks applied, nothing stored
    in the sheets. Output data/story_compare.json for the review board."""
    key = os.environ["GEMINI_API_KEY"]
    picks = json.loads(Path("docs/data/picks.json").read_text())
    theses = json.loads(Path("docs/data/theses.json").read_text()) if Path("docs/data/theses.json").exists() else {}
    forward = (json.loads(Path("docs/data/forward.json").read_text()) if Path("docs/data/forward.json").exists() else {}).get("stocks", {})
    rows = sorted([p for p in picks["picks"] if not p.get("out")], key=lambda p: (p.get("rk") or 10 ** 6, -(p.get("pr") or 0)))
    out, t0 = {"date": str(date.today()), "models": COMPARE, "stocks": []}, time.time()
    for p in rows:
        if len(out["stocks"]) >= n or time.time() - t0 > 35 * 60:
            break
        f = Path(f"docs/data/fin/{p['s']}.json")
        desc = ((json.loads(f.read_text()).get("stock") or {}).get("summary") or "").strip() if f.exists() else ""
        if len(desc) < 60:
            continue
        plans = plans_of(p["s"], theses, forward)
        facts = desc + " " + " ".join(f"{x['text']} {x.get('due') or ''}" for x in plans) + " " + (p.get("n") or "")
        verdict = one_line(p.get("t"))
        row = {"s": p["s"], "n": p.get("n"), "i": p.get("i"), "verdict": verdict, "by": {}}
        for m in COMPARE:
            t1 = time.time()
            a, bad, err = attempt(key, m, p, desc, plans, facts, verdict)
            row["by"][m] = {"secs": round(time.time() - t1, 1), "error": err, "held": bad,
                            "line_held": check_line((a or {}).get("line"), facts) if a else None,
                            **{k: (a or {}).get(k) for k in ("what", "money", "plans", "line")}}
            time.sleep(4)
        out["stocks"].append(row)
        print(f"[story] compare {p['s']}: " + ", ".join(f"{m} {'ok' if not r['error'] and not r['held'] else (r['error'] or 'held')}" for m, r in row["by"].items()))
    Path("data/story_compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def _load() -> dict:
    return json.loads(STORE.read_text()) if STORE.exists() else {"stocks": {}}


def write(max_minutes: float = 30, limit: int = 300) -> None:
    """Write the business sections for stocks that have none (or a changed description / older than a year), in priority order."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("[story] no GEMINI_API_KEY")
        return
    st, today, t0 = _load(), str(date.today()), time.time()
    picks = json.loads(Path("docs/data/picks.json").read_text())
    theses = json.loads(Path("docs/data/theses.json").read_text()) if Path("docs/data/theses.json").exists() else {}
    forward = (json.loads(Path("docs/data/forward.json").read_text()) if Path("docs/data/forward.json").exists() else {}).get("stocks", {})
    queue = [x.get("symbol") for x in (json.loads(Path("docs/data/queue.json").read_text()).get("items") or [])] if Path("docs/data/queue.json").exists() else []
    rows = [p for p in picks["picks"] if not p.get("out")]
    first = set(queue) | {p["s"] for p in rows if p.get("dc") in ("Buy", "Strong Buy") or p.get("cand")} | set(picks.get("top10") or [])
    order = sorted(rows, key=lambda p: (p["s"] not in first, p.get("rk") or 10 ** 6, -(p.get("pr") or 0)))
    done = errs = held = 0
    dead: set = set()
    for p in order:
        if done >= limit or time.time() - t0 > max_minutes * 60:
            break
        sym = p["s"]
        f = Path(f"docs/data/fin/{sym}.json")
        if not f.exists():
            continue
        desc = ((json.loads(f.read_text()).get("stock") or {}).get("summary") or "").strip()
        if len(desc) < 60:
            continue
        old = st["stocks"].get(sym) or {}
        if old.get("desc_len") == len(desc) and str(old.get("date", "")) > str(int(today[:4]) - 1) + today[4:]:
            continue
        plans = plans_of(sym, theses, forward)
        facts = desc + " " + " ".join(f"{x['text']} {x.get('due') or ''}" for x in plans) + " " + (p.get("n") or "")  # due dates: "by March 2027"
        verdict = one_line(p.get("t"))
        for m in [x for x in MODELS if x not in dead]:
            out, bad, err = attempt(key, m, p, desc, plans, facts, verdict)
            if err:
                errs += 1
                if err in ("HTTP 429", "HTTP 404"):
                    dead.add(m)  # out of today's allowance (or gone): skip it for the rest of the run
                continue
            if bad:
                held += 1
                st.setdefault("held", {})[sym] = {"model": m, "date": today, "why": bad[:4]}
                continue
            st["stocks"][sym] = {"what": out["what"].strip(), "money": out["money"].strip(),
                                 "plans": [str(x).strip() for x in (out.get("plans") or [])[:2]],
                                 "model": m, "date": today, "desc_len": len(desc)}
            if out.get("line") and not check_line(out["line"], facts):
                st["stocks"][sym]["line"] = str(out["line"]).strip()  # stored only: the app shows the code phrase until the owner approves
            st.get("held", {}).pop(sym, None)
            done += 1
            break
        if len(dead) == len(MODELS):
            print("[story] every model is out of today's allowance")
            break
        time.sleep(4)
        if done and done % 10 == 0:
            STORE.write_text(json.dumps(st, ensure_ascii=False, indent=0, sort_keys=True))
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(st, ensure_ascii=False, indent=0, sort_keys=True))
    print(f"[story] wrote {done}, held {held} (failed checks), {errs} model errors; {len(st['stocks'])} stored; {time.time() - t0:.0f}s")


# ---------------------------------------------------------------- the dossier field
def sheet(sym: str, row: dict, metrics: dict, summary: str | None, theses: dict, forward: dict, st: dict | None = None) -> dict | None:
    st = st if st is not None else _load()
    w = (st.get("stocks") or {}).get(sym) or {}
    plans = plans_of(sym, theses, forward)
    plain = w.get("plans") or []
    pl = [{"text": plain[i] if i < len(plain) else x["text"], "due": x.get("due")} for i, x in enumerate(plans[:2])]
    what = w.get("what")
    if not what and summary:
        what = re.split(r"(?<=[.!?])\s", summary.strip())[0][:CAPS["what"]]  # first sentence of the description until the model writes it
    out = {"what": what, "money": w.get("money"), "going": going(metrics), "plans": pl, "risks": risks_of(sym, theses),
           "one_line": one_line(row.get("t")), "written": w.get("date"), "plain": bool(w)}
    return out if any(out[k] for k in ("what", "going", "one_line")) else None


if __name__ == "__main__":
    if "--write" in sys.argv:
        write()
    elif "--compare" in sys.argv:
        compare()
