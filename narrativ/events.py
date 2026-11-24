"""Exchange announcements -> typed events. Exchange-filed records only (no media), each with its filing link.

Severity: red = can break a thesis (re-check first) · watch = possibly bad, open the filing (re-check) ·
green = possible trigger (re-check) · info = routine (stored only).
"""
import re

# "order" as a business order: not the "in order to" of exchange volume/price clarifications
_ORD = r"\borders?\b(?!(?<=\bin order)\s+(?:to|that)\b)"
# a drug / GMP regulator or an inspection named in the subject (context for the inspection rules below)
_REG = (r"\bus ?fda\b|\bu\.s\. ?fda\b|\bfda\b|food and drug|\bmhra\b|\bedqm\b|\beu[- ]?gmp\b|\beuropean\b|\bwho[- ]?gmp\b|\banvisa\b|"
        r"\btga\b|\bpmda\b|health canada|\bcdsco\b|\bdcgi\b|drugs? control|\bc?gmp\b|\binspection\b|\beir\b|establishment inspection|form[- ]?483")
_NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|several|few|minor|procedural)"

# owner, 24 Nov 2026: "Issuer Default Rating" (a rating name), ESG ratings, SAST / pledge disclosures, appointments and
# "senior secured" ratings were typed as defaults, upgrades, acquisitions, approvals and order wins
_NOT_DEFAULT = r"(?<!issuer )(?<!probability of )\bdefault(?!\s+(rating|risk|probability))"
_RATING = r"credit rating|\brating(s)?\b.{0,60}\b(crisil|icra|care|careedge|india ratings|ind-?ra|brickwork|acuite|infomerics|fitch|moody|s&p)\b|" \
          r"\b(crisil|icra|careedge|india ratings|brickwork|acuite|infomerics|fitch|moody'?s|s&p)\b.{0,80}\brating|rating rationale"

RULES = [  # (type, severity, regex on headline + category[, context regex that must also match]), first match wins
    ("ESG rating", "info", r"\besg\b|sustainability rating|environmental, social"),
    ("Default / delayed payment", "red", _NOT_DEFAULT + r"|delay(ed)? in (payment|servicing)|non-?payment of (interest|principal)"),
    ("Insolvency", "red", r"insolvency|\bnclt\b|\bibc\b|\bcirp\b|resolution professional|winding up"),
    ("Auditor resigned", "red", r"(statutory )?auditors?.{0,40}resign|resign.{0,40}auditor"),
    ("Auditor change", "info", r"change (in|of) (the )?(statutory )?auditors?|(appointment|re-?appointment) of (the )?(new )?statutory auditors?"),
    ("Auditor appointment (routine)", "info", r"(appointment|re-?appointment) of (the )?(secretarial|internal|cost) auditors?"),
    ("Search / seizure", "red", r"\bsearch\b|seizure|\bsurvey\b.{0,30}(income tax|gst)|enforcement directorate|\bed\b raid|\bcbi\b"),
    ("Regulatory action", "red", r"sebi.{0,30}(" + _ORD + r"|penalty)|show cause|adjudicat|penalty imposed|debarred|suspension of trading"),
    ("Fraud / forensic", "red", r"fraud|forensic|misappropriat|siphon"),
    ("Rating downgrade", "red", r"downgrad|rating.{0,40}negative|outlook.{0,30}negative|credit watch.{0,20}negative|issuer not cooperating"),
    ("Rating withdrawn", "watch", r"rating.{0,40}withdraw|withdraw\w*.{0,40}rating"),
    ("Rating upgrade", "green", r"upgrad|upward revision|outlook.{0,30}positive|credit watch.{0,20}positive", _RATING),
    ("Credit rating revised (direction in the filing)", "watch", r"rating.{0,5}revision|revision (in|of) (the )?(credit )?rating|revised", _RATING),
    ("Credit rating", "info", _RATING),
    ("Pledge invoked", "red", r"invocation of pledge|pledge.{0,20}invok"),
    ("Pledge / encumbrance created", "watch", r"creation of (pledge|encumbrance)|encumbrance|regulation 31\b|reg\.? ?31\b|pledge of shares|pledged? shares"),
    ("SAST disclosure", "info", r"substantial acquisition of shares|\bsast\b|regulation 29\b|reg\.? ?29\b|regulation 10\s*\(\s*[67]"),
    ("Top management exit", "red", r"resign.{0,60}(chief financial|cfo|chief executive|ceo|managing director|whole[- ]time director)|"
                                   r"(chief financial|cfo|chief executive|ceo|managing director).{0,60}resign"),
    # drug / plant regulators: a lifted sanction first (it names the sanction), then the sanction itself
    ("Regulatory sanction lifted", "green", r"\boai\b.{0,40}\b(to|into)\b.{0,15}\b(vai|nai)\b|close-?out letter|"
                                            r"warning letter.{0,40}\b(closed|lifted|withdrawn|resolved)\b|"
                                            r"\b(closure|lifting|removal|revocation|withdrawal) of (the )?(usfda |us fda |fda )?(warning letter|import alert)|"
                                            r"import alert.{0,30}\b(lifted|removed|revoked|withdrawn)\b|"
                                            r"\b(lifts?|lifted|removes?|removed|revokes?|revoked|withdraws?|withdrawn)\b.{0,20}import alert|"
                                            r"\b(revocation|withdrawal|lifting) of (the )?suspension\b.{0,60}licen[cs]e|licen[cs]e.{0,40}\b(restored|reinstated)\b"),
    ("Regulatory inspection: adverse", "red", r"\boai\b|official action indicated|warning letter|import alert|"
                                              r"statement of non-?compliance|\b(eu[- ]?)?c?gmp\b.{0,40}non-?complian|non-?complian\w*.{0,40}\b(eu[- ]?)?c?gmp\b|"
                                              r"\bc?gmp (certificate|certification).{0,40}\b(withdrawn|suspended|revoked|cancell?ed)\b|"
                                              r"\b(cdsco|dcgi|drugs? control\w*|licensing authority|state fda)\b.{0,80}\b(suspen|cancell?|revo[ck])|"
                                              r"\b(suspen\w*|cancell?ation|revocation)\b.{0,60}\b(manufacturing|drug|product)\s+licen[cs]e|"
                                              r"(?<!window )(?<!book )\b(closure|shut ?down|cessation)\s+(order|direction|notice)s?\b|"
                                              r"\b(order|direction|notice)s?\b.{0,40}\b(closure|shut ?down|sealing)\b.{0,30}\b(plant|unit|factory|facility|premises|operations)\b|"
                                              r"\b(pollution control (board|committee)|[a-z]{0,3}pcb)\b.{0,120}\b(closure|shut ?down|seal\w*|stoppage|cease|disconnect\w*)\b"),
    ("Regulatory inspection: adverse", "red", r"\b(critical|major|repeat(ed)?) observations?\b|\bdata integrity\b", _REG),
    ("Regulatory inspection: observations", "watch", r"\bvai\b|voluntary action indicated|form[- ]?483|\b483\b.{0,20}observation|"
                                                     r"(?<!\bno )(?<!\bnil )(?<!\bzero )\b" + _NUM + r"\s+(\w+\s+)?observations?\b", _REG),
    ("Regulatory inspection cleared", "green", r"\bnai\b|no action indicated|\b(zero|nil|no|0)\s+(\w+\s+)?(483\s+)?observations?\b|"
                                               r"without any (\w+\s+)?observations?|\beir\b|establishment inspection report|"
                                               r"successful(ly)? (completion|completed|concluded|closed)|closure of .{0,40}inspection", _REG),
    ("Regulatory inspection: outcome not in subject", "watch", r"\binspection\b|\baudit\b",
     r"\bus ?fda\b|\bu\.s\. ?fda\b|\bfda\b|\bmhra\b|\bedqm\b|\beu[- ]?gmp\b|\bwho[- ]?gmp\b|\banvisa\b|\btga\b|\bpmda\b|health canada|\bcdsco\b|\bdcgi\b|\bc?gmp\b"),
    # court / tribunal orders that sanction a scheme (first motion, meeting, final order) stay corporate actions
    ("Buyback / demerger / acquisition", "green", r"demerg|amalgamat|\bmerger\b|scheme of (arrangement|merger|amalgamation|demerger)|first motion|court[- ]convened meeting",
     r"court|tribunal|national company law|\bnclt\b"),
    # legal and tax orders are orders against the company, not order wins
    ("Court / tax order", "watch", r"\b(high court|supreme court|district court|civil court|commercial court|court|tribunal|nclat|itat|cestat|drt)('s)?\s+"
                                   r"((has\s+)?(passed|issued|pronounced)\s+(an?\s+)?)?((interim|final|ex[- ]?parte)\s+)?(order|judge?ment|verdict|ruling)s?\b|"
                                   r"\bcourt orders?\b|\borders?\s+(of|by|from|passed by|issued by)\s+(the\s+)?(hon'*ble\s+)?"
                                   r"(high court|supreme court|district court|civil court|commercial court|court|tribunal|nclat|itat|cestat|drt|national company law)|"
                                   r"\b(stay|interim|ex[- ]?parte|injunction|attachment|restraint|recovery)\s+orders?\b|"
                                   r"\baction\(s\) (taken|initiated)|\borders? passed\b|\borders?\s+(under|u/s)\b.{0,40}\b(act|section|rules)\b|"
                                   r"\b(tax|gst|demand|assessment|penalty|adjudication|reassessment)\s+orders?\b|"
                                   r"\borders?\s+(received\s+)?(from|by|of|issued by)\s+(the\s+)?(office of (the )?)?(income[- ]tax|gst|cgst|sgst|igst|customs|"
                                   r"central excise|excise|service tax|assessing officer|((deputy|assistant|joint|additional|principal|chief) )?commissioner|"
                                   r"tax authorit|(gst|tax|customs|excise) department|directorate general of gst)"),
    ("Pollution board notice", "watch", r"pollution control (board|committee)|\b[a-z]{0,3}pcb\b"),
    ("Exchange clarification", "info", r"spurt in (volume|price)|price movement|movement in (the )?price|increase in (the )?volume|"
                                       r"significant (increase|movement)|sought clarification|news verification|clarification (sought|on|regarding|with reference)"),
    ("KMP / senior management exit", "watch",
     r"(resign|cessation|step(ped|s)? down|retirement of|removal of|demise of).{0,60}(\bkmp\b|key managerial|senior management|\bsmp\b|chief|head of)|"
     r"(\bkmp\b|key managerial|senior management|chief \w+ officer).{0,60}(resign|cessation)|resignation of director/kmp"),
    ("Director exit", "info",
     r"(resign|cessation|step(ped|s)? down|retirement of|removal of|demise of).{0,60}(director|company secretary|compliance officer)|"
     r"(director|company secretary|compliance officer).{0,60}(resign|cessation)"),
    ("Management appointment", "info",
     r"(appoint|re-?appoint|designat|elevat|continuation).{0,60}(director|\bkmp\b|key managerial|company secretary|compliance officer|senior management|"
     r"chief|\bceo\b|\bcfo\b|\bcoo\b|\bcto\b|managing director|chairman|chairperson)|"
     r"(director|\bkmp\b|key managerial|company secretary|chief|\bceo\b|\bcfo\b|managing director|chairman).{0,60}(appoint|re-?appoint)|change in (directors|management|kmp)"),
    ("Order / contract win", "green", _ORD + r"|contract|letter of (award|intent)|\bloa\b|\bloi\b|bagged|(?<!senior )(?<!un)secured|work order|purchase order"),
    ("Capacity / commissioning", "green", r"commission|commercial (production|operation)|capacity expansion|new (plant|facility|unit)|capex"),
    ("Approval / launch", "green", r"usfda|approval|launch|patent|certification|qualif"),
    ("Rating upgrade", "green", r"upgrad"),
    ("Buyback / demerger / acquisition", "green", r"buy-?back|demerg|acqui|amalgamat|scheme of arrangement|divest"),
    ("Fund raise", "info", r"preferential|warrant|qip|rights issue|fund rais|allotment"),
    ("Results / meeting", "info", r"financial results|board meeting|outcome of board|investor (meet|presentation)|analyst|transcript|earnings call|agm|egm"),
]
_RX = [(r[0], r[1], re.compile(r[2], re.I), re.compile(r[3], re.I) if len(r) > 3 else None) for r in RULES]


def classify(text: str) -> tuple[str, str]:
    s = text or ""
    for t, sev, rx, ctx in _RX:
        if rx.search(s) and (ctx is None or ctx.search(s)):
            return t, sev
    return "Other", "info"


def _key(e: dict) -> str:
    return e.get("url") or f"{e.get('date')}|{e.get('text')}"


_RANK = {}
for _i, _r in enumerate(RULES):
    _RANK.setdefault(_r[0], _i)


def retype(stored: list[dict], src: list[dict], today: str) -> list[dict]:
    """Re-type events already kept in memory with the current rules, so a rule change reaches them (in place).
    The source's fresh type is used while the filing is still in the source, else the stored text when it is complete.
    Stored text is cut at 220 characters, and the cut can drop the words that typed it (or join the cut text to the
    category into a false match), so a cut text only moves a non-red event to a rule that comes earlier than its stored
    type (first match wins, so the full text cannot have matched the later stored rule): e.g. an old "in order to" order win
    becomes an exchange clarification; a red is never raised or cleared from a cut text.
    An event that turns red gets red_seen = today: the red re-check compares it with the last research date, because the
    filing itself may predate research that never saw it as red. -> the events that turned red."""
    by = {_key(e): e for e in src}
    turned = []
    for e in stored:
        x = by.get(_key(e))
        if x is not None:
            t, s = x.get("type"), x.get("sev")
        else:
            t, s = classify(f"{e.get('text') or ''} {e.get('category') or ''}")
            if len(e.get("text") or "") >= 220 and ("red" in (s, e.get("sev")) or t == "Other"
                                                    or _RANK.get(t, len(RULES)) >= _RANK.get(e.get("type"), len(RULES))):
                continue
        if (t, s) == (e.get("type"), e.get("sev")):
            continue
        if s == "red" and e.get("sev") != "red":
            e["red_seen"] = today
            turned.append(e)
        elif s != "red":
            e.pop("red_seen", None)
        e["type"], e["sev"] = t, s
    return turned


def from_announcements(rows: list[dict]) -> list[dict]:
    """rows: [{date, text, category, url}] -> events with type and severity, newest first, de-duplicated by url."""
    out, seen = [], set()
    for r in rows:
        key = _key(r)
        if key in seen:
            continue
        seen.add(key)
        t, s = classify(f"{r.get('text') or ''} {r.get('category') or ''}")
        out.append({"date": r.get("date"), "type": t, "sev": s, "text": (r.get("text") or r.get("category") or "")[:220],
                    "category": r.get("category"), "url": r.get("url")})
    return sorted(out, key=lambda e: e.get("date") or "", reverse=True)
