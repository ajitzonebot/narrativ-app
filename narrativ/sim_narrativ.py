"""Probe (owner, 24 Nov 2026): can free Gemini / Gemma models write the app's 'Narrativ' sheet? Changes no rule, no app data.

Split agreed with the owner:
- What they do + How they make money: a cheap model, from the company description (all stocks).
- How it's going: code, from the latest results (revenue and profit vs the same quarter a year ago).
- In one line: code, a phrase set from the stability / quality / valuation / momentum tiers.
- Plans to grow: the model rephrases plans already extracted with quotes (Claude's drivers, the reader's rows).
- What could go wrong: Claude's kill switches where researched; else a stronger model from the same facts.
Checks: length caps (one screen), every number in a model's text must appear in the facts given to it.
Writes docs/data/sim_narrativ.json and docs/research/sim_narrativ.md.   python -m narrativ.sim_narrativ
"""
import json
import os
import re
import time
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
STOCKS = ["SATIN.NS", "TALBROAUTO.NS", "HEROMOTOCO.NS", "CAPLIPOINT.NS", "POLYCAB.NS", "ARROWGREEN.NS", "GPTHEALTH.NS",
          "MPSLTD.NS", "HUDCO.NS", "RELIANCE.NS"]
CHEAP = ["gemma-4-31b-it", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]  # 3.5-flash-lite is the reader's
STRONG = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]  # 3.8-flash is the reader's
CAPS = {"what": 230, "money": 150, "plan": 70, "risk": 140}
OUT = []


def p(*a):
    OUT.append(" ".join(str(x) for x in a))


def models(key):
    import requests
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    return sorted(m["name"].removeprefix("models/") for m in r.json().get("models", [])
                  if "generateContent" in (m.get("supportedGenerationMethods") or []))


def ask(key, model, prompt):
    import requests
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
    if not model.startswith("gemma"):
        body["generationConfig"]["responseMimeType"] = "application/json"
    t0 = time.time()
    for wait in (0, 15):  # 503 "high demand" is temporary
        time.sleep(wait)
        r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=90)
        if r.status_code != 503:
            break
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:160]}", time.time() - t0
    try:
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
        return json.loads(txt[txt.find("{"): txt.rfind("}") + 1]), None, time.time() - t0
    except Exception as e:  # noqa: BLE001
        return None, f"parse: {e}", time.time() - t0


def nums(s):
    out = set()
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", str(s or "")):
        try:
            v = float(m.replace(",", ""))
        except ValueError:
            continue
        out.add(v)
    return out


def unsupported(text, facts_text):
    have = nums(facts_text)
    bad = []
    for v in nums(text):
        if v in have or v <= 12 or any(abs(v - h) <= 0.051 * max(1, abs(h)) and abs(v - h) < 1 for h in have):
            continue
        bad.append(v)
    return bad


# ---------------------------------------------------------------- code-written sections
def going(m):
    def v(k):
        x = m.get(k)
        return x.get("v") if isinstance(x, dict) else None
    r, pr = v("rev_yoy_pct"), v("pat_yoy_pct")
    if r is None and pr is None:
        return None
    word = lambda x, what: f"{what} {'up' if x >= 0 else 'down'} {abs(x):.0f}%"  # noqa: E731
    parts = [word(pr, "Profit") if pr is not None else None, word(r, "revenue" if pr is not None else "Revenue") if r is not None else None]
    s = " and ".join(x for x in parts if x) + " on the same quarter last year."
    good = (pr if pr is not None else r) >= 0
    return {"text": s, "tone": "good" if good else "bad"}


def one_line(t):
    """Phrase set from the tiers (1 best .. 5 worst; 0 = not enough data): quality + stability, valuation, momentum."""
    t = (list(t) + [0] * 7)[:7]
    st, q, va, mo = t[0], t[1], t[2], t[4]
    biz = {1: "A strong business", 2: "A strong business", 3: "A decent business", 4: "A weak business", 5: "A weak business"}.get(q, "A business we can't judge yet")
    if st in (4, 5):
        biz += " with a shaky balance sheet"
    price = {1: " at a cheap price", 2: " at a cheap price", 3: " at a fair price", 4: " at a rich price", 5: " at a very rich price"}.get(va, "")
    good = q in (1, 2) or va in (1, 2)
    mood = {1: ", and the market is buying in.", 2: ", and the market is starting to notice.", 3: ", and the price is starting to move.",
            4: (", but the price is going nowhere yet." if good else ", and the price is going nowhere."),
            5: (", but the price is weak." if good else ", and the price is weak.")}.get(mo, ".")
    return biz + price + mood


# ---------------------------------------------------------------- inputs
def facts(sym, fin, theses, fwd, picks):
    d = json.loads((fin / f"{sym}.json").read_text())
    th = theses.get(sym) or {}
    pk = picks.get(sym) or {}
    plans = [{"text": x.get("text"), "due": x.get("due"), "quote": x.get("quote")} for x in th.get("drivers") or [] if x.get("text")]
    src = "Claude" if plans else None
    if not plans:
        plans = [{"text": x.get("text"), "due": x.get("due"), "quote": x.get("quote")} for x in ((fwd.get(sym) or {}).get("items") or [])
                 if x.get("kind") in ("guidance", "capacity", "order", "demand", "product")][:5]
        src = "reader" if plans else None
    kills = [x.get("text") for x in ((th.get("scan") or {}).get("kill_switches") or []) if x.get("text")]
    return {"symbol": sym, "name": pk.get("n") or sym, "industry": pk.get("i"), "description": (d.get("stock") or {}).get("summary"),
            "plans": plans, "plans_from": src, "claude_risks": kills, "metrics": d.get("metrics") or {}, "tiers": pk.get("t") or []}


def prompt_business(f):
    return f"""You write for an Indian stock app read by ordinary people. Plain words, no jargon (if a term is unavoidable, explain it in 3 words in brackets).
Company: {f['name']} ({f['industry']}).
Company description: {f['description']}
Plans management stated (with quotes): {json.dumps(f['plans'][:4], ensure_ascii=False)}
Return JSON only: {{"what": "what the company does, 1-2 sentences, max {CAPS['what']} characters, concrete (what it sells, to whom)",
"money": "how it makes money, 1-2 sentences, max {CAPS['money']} characters",
"plans": ["up to 2 plans to grow, each max {CAPS['plan']} characters, rephrased from the plans above only, keep their numbers and dates"]}}
Use only facts given above. Do not add any number that is not above. Do not praise or advise."""


def prompt_risk(f):
    return f"""You write for an Indian stock app read by ordinary people. Plain words, no jargon.
Company: {f['name']} ({f['industry']}). Description: {f['description']}
Plans: {json.dumps(f['plans'][:4], ensure_ascii=False)}
Return JSON only: {{"risk": "the single biggest thing that could break this company's story, max {CAPS['risk']} characters, specific to this business, no numbers"}}"""


def main():
    key = os.environ.get("GEMINI_API_KEY")
    fin = Path("docs/data/fin")
    theses = json.loads(Path("docs/data/theses.json").read_text())
    fwd = json.loads(Path("docs/data/forward.json").read_text()).get("stocks", {})
    picks = {x["s"]: x for x in json.loads(Path("docs/data/picks.json").read_text())["picks"]}
    have = models(key) if key else []
    p("## Models on the key with generateContent")
    p(", ".join(have) or "(no key)")
    cheap = [m for m in CHEAP if m in have][:3]
    strong = [m for m in STRONG if m in have][:1]
    p("cheap models tested:", cheap, "· strong model for risks:", strong)
    res = {}
    for sym in STOCKS:
        if not (fin / f"{sym}.json").exists():
            continue
        f = facts(sym, fin, theses, fwd, picks)
        ftxt = json.dumps({k: f[k] for k in ("description", "plans", "name")}, ensure_ascii=False)
        r = {"name": f["name"], "industry": f["industry"], "going": going(f["metrics"]), "one_line": one_line(f["tiers"]),
             "plans_from": f["plans_from"], "claude_risks": f["claude_risks"][:2], "models": {}}
        for m in cheap:
            out, err, sec = ask(key, m, prompt_business(f))
            chk = {}
            if out:
                for k in ("what", "money"):
                    chk[k] = {"len": len(str(out.get(k) or "")), "over": len(str(out.get(k) or "")) > CAPS[k], "unsupported": unsupported(out.get(k), ftxt)}
                chk["plans"] = [{"len": len(str(x)), "unsupported": unsupported(x, ftxt)} for x in out.get("plans") or []]
            r["models"][m] = {"out": out, "error": err, "seconds": round(sec, 1), "checks": chk}
            time.sleep(4.5)
        if not f["claude_risks"] and strong:
            out, err, sec = ask(key, strong[0], prompt_risk(f))
            r["risk_model"] = {"model": strong[0], "out": out, "error": err, "seconds": round(sec, 1)}
            time.sleep(13)
        res[sym] = r
        p(f"\n## {sym} {f['name']} · plans from {f['plans_from']} · Claude risks {len(f['claude_risks'])}")
        p("going:", r["going"], "| one line:", r["one_line"])
        for m, x in r["models"].items():
            p(f"  {m} ({x['seconds']}s) {x['error'] or ''}")
            if x["out"]:
                p("   what:", x["out"].get("what")); p("   money:", x["out"].get("money")); p("   plans:", x["out"].get("plans"))
                p("   checks:", json.dumps(x["checks"]))
        if r.get("risk_model"):
            p("  risk:", r["risk_model"])
        save(have, cheap, strong, res)  # after every stock: a timeout keeps what was done
    save(have, cheap, strong, res)


def save(have, cheap, strong, res):
    Path("docs/data/sim_narrativ.json").write_text(json.dumps({"models": have, "cheap": cheap, "strong": strong, "stocks": res}, ensure_ascii=False, indent=1))
    Path("docs/research/sim_narrativ.md").write_text("```\n" + "\n".join(OUT) + "\n```\n")


if __name__ == "__main__":
    main()
