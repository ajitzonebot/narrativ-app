@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.drawBehind
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.NorthEast
import androidx.compose.material.icons.rounded.SouthEast
import androidx.compose.material.icons.rounded.RocketLaunch
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.json.JsonPrimitive
import java.time.LocalDate

/** Label shown for each metric key (pipeline names -> plain English). */
val METRIC_NAMES = mapOf(
    "rev_yoy_prev2_pct" to "Revenue growth YoY, two quarters ago",
    "mcap_cr" to "Market cap", "pe" to "P/E", "pb" to "P/B", "ev_ebitda" to "EV / EBITDA", "peg" to "PEG", "roe_pct" to "ROE",
    "roce_pct" to "ROCE", "de" to "Debt / equity", "ebitda_margin_pct" to "EBITDA margin", "ebitda_margin_q_pct" to "EBITDA margin (quarter)",
    "rev_yoy_pct" to "Revenue YoY (quarter)", "pat_yoy_pct" to "Profit YoY (quarter)", "rev_ttm_growth_pct" to "Revenue growth (4 quarters)",
    "pat_ttm_growth_pct" to "Profit growth (4 quarters)", "eps_cagr_3y_pct" to "EPS growth, 3 years", "pat_cagr_3y_pct" to "Profit growth a year (span in formula)",
    "cfo_to_ebitda_pct" to "Cash conversion", "other_income_pct_pbt" to "Other income % of PBT", "receivable_days" to "Receivable days",
    "inventory_days" to "Inventory days", "cwip_pct_ppe" to "Capital work in progress / fixed assets", "net_cash_pct_mcap" to "Net cash % of market cap",
    "fcf_yield_pct" to "FCF yield", "capex_pct_rev" to "Capex / revenue", "interest_cover" to "Interest cover",
    "free_float_mcap_cr" to "Free-float market cap", "revenue_ttm_cr" to "Revenue (4 quarters)", "pat_ttm_cr" to "Profit (4 quarters)",
    "asset_turnover" to "Fixed-asset turnover", "gnpa_pct_advances" to "Gross NPA % of advances",
    "rev_cagr_3y_pct" to "Revenue growth, 3-yr avg", "roce_3y_avg_pct" to "ROCE, avg of filed years", "net_debt_ebitda" to "Net debt / EBITDA",
    "current_ratio" to "Current ratio", "cfo_negative_years" to "Years of negative operating cash", "loss_quarters_4" to "Loss quarters (last 4)",
    "dilution_3y_pct" to "Share dilution, 3 years", "debt_chg_yoy_pct" to "Borrowings change, 1 year", "ev_sales" to "EV / sales",
    "ev_midcycle_ebitda" to "EV / mid-cycle EBITDA", "margin_chg_3y_pts" to "EBITDA margin change over filed years (pts)",
    "ebitda_margin_prev_pct" to "EBITDA margin a year ago", "margin_range_12q_pts" to "Margin range, 12 quarters (pts)",
    "investments_pct_assets" to "Investments % of assets", "roa_pct" to "ROA", "equity_cr" to "Shareholders' equity",
    "rev_yoy_prev_pct" to "Revenue YoY (previous quarter)", "rev_ttm_growth_prev_pct" to "Revenue growth a year ago (4 quarters)",
    "ebitda_margin_q_yago_pct" to "Quarter EBITDA margin a year ago",
)

@Composable
fun SectionHeader2(t: String, sub: String) = Column(Modifier.padding(top = 20.dp, bottom = 8.dp)) {
    if (Look.paper) PaperLabel(t, size = 12.sp) else T(t, SECTION_TITLE, weight = FontWeight.SemiBold); T(sub, LABEL, C.dim)
}

@Composable
fun MarkBox(m: Mark, onClick: () -> Unit) {
    val (sym, fg, bg) = when (m.mark) {
        "y" -> statusColor("Pass").let { Triple("✓", it, it.copy(alpha = 0.18f)) }; "p" -> statusColor("Partly").let { Triple("~", it, it.copy(alpha = 0.15f)) }
        "n" -> statusColor("Miss").let { Triple("✗", it, it.copy(alpha = 0.15f)) }; else -> Triple("–", C.dim, C.chip)
    }
    Box(Modifier.size(19.dp).clip(rr(5.dp)).background(bg).clickable(onClick = onClick), contentAlignment = Alignment.Center) { T(sym, 11.sp, fg, FontWeight.Bold) }
}

@Composable
fun WatchRow(n: String, w: Watch, col: Color, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 6.dp)) {
        Box(Modifier.size(24.dp).clip(CircleShape).background(col.copy(alpha = 0.15f)), contentAlignment = Alignment.Center) { T(n, 12.sp, col, FontWeight.Bold) }
        Spacer(Modifier.width(12.dp))
        Column { T(w.text, 14.sp, weight = FontWeight.SemiBold); T(w.check + (w.due?.let { " · due ${skDue(it)}" } ?: ""), 12.sp, C.dim) }
    }
}

/** Metric keys that are multiples ("23.0×"). */
private val MULT_KEYS = setOf("pe", "pb", "peg", "ev_ebitda", "ev_sales", "ev_midcycle_ebitda", "de", "net_debt_ebitda", "interest_cover", "asset_turnover")

/** The figure with its unit, as the Ratios sheet shows it: "%" for _pct keys, "×" for multiples, then the metric's own unit. */
fun metricUnit(key: String?, m: Metric): String = when {
    m.u != null -> " ${m.u}"
    key?.endsWith("_pct") == true -> "%"
    key != null && key in MULT_KEYS -> "×"
    else -> ""
}

/** The rule that tests a metric key: the check's mark (2 pass, 1 partly, 0 miss, null n/a) and its name ("ROCE ≥ 10%"). */
data class KeyRule(val m: Int?, val rule: String)

/** metric key -> the check that tests it, from every level item with a key; when several checks use one key, the worst mark. */
fun Detail.rulesByKey(): Map<String, KeyRule> {
    fun rank(m: Int?) = m ?: 3  // miss 0 < partly 1 < pass 2 < n/a
    val out = mutableMapOf<String, KeyRule>()
    levels.values.forEach { lv ->
        lv.items.forEach { i ->
            val k = i.k
            if (k != null) { val cur = out[k]; if (cur == null || rank(i.m) < rank(cur.m)) out[k] = KeyRule(i.m, i.n) }
        }
    }
    return out
}

/** Colour of a ratio by the check that tests it: pass light green, partly yellow, miss light red; no check (or n/a) white. */
fun ruleColor(r: KeyRule?): Color = when (r?.m) { 2 -> TierC.lightGreen; 1 -> TierC.yellow; 0 -> TierC.lightRed; else -> C.white }

@Composable
fun FormulaSheet(name: String, m: Metric, key: String? = null, det: Detail? = null, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val rule = remember(det, key) { key?.let { k -> det?.rulesByKey()?.get(k) } }
    BottomSheet(onClose, name) {
        T((if (m.nm) "n/m (outside the meaningful range) · " else "") + skFx(m.v, 2) + (if (m.v != null) metricUnit(key, m) else ""), 28.sp,
            if (m.nm) C.white else ruleColor(rule), FontWeight.Bold)
        rule?.rule?.let { T(it, LABEL, C.dim, maxLines = 2, modifier = Modifier.padding(top = 2.dp)) }  // feedback #166
        T("Formula", 13.sp, C.dim, FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp)); T(m.f, 14.sp, lineHeight = 19.sp)
        if (m.inputs.isNotEmpty()) {
            T("Inputs", 13.sp, C.dim, FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp))
            m.inputs.forEach { (k, v) -> KV(inputLabel(k), inputValue(k, v.content)) }
        }
        T("Source", 13.sp, C.dim, FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp))
        // feedback #167: the source itself opens the filing (no separate "Open the filing" line)
        val u = m.url
        if (u != null) Row(Modifier.clickable { openUrl(ctx, u) }, verticalAlignment = Alignment.CenterVertically) {
            T(m.src, 13.sp, C.blue, FontWeight.SemiBold, modifier = Modifier.weight(1f, false)); LinkIcon()
        }
        else T(m.src, 13.sp, C.grey)
    }
}

/** Formula inputs: full names and units instead of data keys (feedback: formulas looked inconsistent). */
val INPUT_LABELS = mapOf(
    "advances_cr" to "Loans given (advances)", "borrowings_cr" to "Borrowings", "lease_liabilities_cr" to "Lease liabilities", "assets_cr" to "Total assets", "avg_equity_cr" to "Average shareholders' equity",
    "avg_margin_pct" to "Average EBITDA margin", "capex_cr" to "Capital expenditure", "capital_employed_cr" to "Capital employed (equity + borrowings)",
    "cash_and_bank_cr" to "Cash and bank balances", "cash_cr" to "Cash and bank balances", "cfo_cr" to "Cash from operations",
    "cfo_fy22_cr" to "Cash from operations, FY22", "cfo_fy25_cr" to "Cash from operations, FY25", "cfo_fy26_cr" to "Cash from operations, FY26",
    "current_assets_cr" to "Current assets", "current_liabilities_cr" to "Current liabilities", "cwip_cr" to "Capital work in progress",
    "date" to "Date", "debt_cr" to "Borrowings", "debt_now_cr" to "Borrowings now", "debt_year_ago_cr" to "Borrowings a year ago",
    "ebit_cr" to "Operating profit (EBIT)", "ebit_ttm_cr" to "Operating profit (EBIT), last 4 quarters", "ebitda_cr" to "EBITDA",
    "ebitda_ttm_cr" to "EBITDA, last 4 quarters", "equity_cr" to "Shareholders' equity", "finance_cost_cr" to "Finance cost",
    "fy22_pct" to "FY22", "fy23_cr" to "FY23", "fy23_pct" to "FY23", "fy24_cr" to "FY24", "fy24_pct" to "FY24", "fy25_pct" to "FY25",
    "fy26_cr" to "FY26", "fy26_pct" to "FY26", "gnpa_cr" to "Gross non-performing assets", "inventory_cr" to "Inventories",
    "investments_cr" to "Investments", "mcap_cr" to "Market capitalisation", "midcycle_ebitda_cr" to "Mid-cycle EBITDA",
    "other_income_cr" to "Other income", "pat_ttm_cr" to "Net profit, last 4 quarters", "pbt_cr" to "Profit before tax",
    "ppe_cr" to "Property, plant and equipment", "prev_ttm_cr" to "Previous 4 quarters", "price" to "Share price",
    "profit_latest_fy_cr" to "Net profit, latest financial year", "profits_cr" to "Net profit", "promoter_pct" to "Promoter holding",
    "quarter" to "Quarter", "quarters" to "Quarters", "receivables_cr" to "Trade receivables", "revenue_cr" to "Revenue from operations",
    "revenue_ttm_cr" to "Revenue from operations, last 4 quarters", "shares" to "Shares outstanding", "shares_now" to "Shares outstanding now",
    "shares_then_adjusted" to "Shares outstanding then (split-adjusted)", "short_term_borrowings_cr" to "Short-term borrowings",
    "this_q_cr" to "This quarter", "ttm_cr" to "Last 4 quarters", "ttm_two_years_ago_cr" to "4 quarters to two years ago",
    "ttm_year_ago_cr" to "4 quarters to a year ago", "year_ago_cr" to "Same quarter a year ago", "years" to "Years",
)

fun inputLabel(k: String): String = INPUT_LABELS[k] ?: k.removeSuffix("_cr").removeSuffix("_pct").split('_')
    .joinToString(" ") { w -> if (w.matches(Regex("fy\\d+|ttm|ebitda|ebit|pat|pbt|cfo"))) w.uppercase() else w }.replaceFirstChar { it.uppercase() }

fun inputValue(k: String, raw: String): String {
    val x = raw.toDoubleOrNull() ?: return raw
    return when {
        k.endsWith("_cr") -> "₹${fmt(x, 2)} cr"
        k.endsWith("_pct") -> "${skFx(x, 1)}%"
        k == "price" -> "₹${fmt(x, 2)}"
        k.startsWith("shares") -> fmt(x, 0)
        k in setOf("quarters", "years") -> fmt(x, 0)
        else -> fmt(x, 2)
    }
}

fun pct1(v: Double?) = v?.let { "${fmt(it, 1)}%" } ?: "–"
fun pct0(v: Double?) = v?.let { "${fmt(it, 0)}%" } ?: "–"


// ---------------------------------------------------------------- research blocks (Outlook tab)
/** A card on its own; inside another card ([nested]) the same content without a second card around it. */
@Composable
private fun ListBlock(nested: Boolean, content: @Composable ColumnScope.() -> Unit) {
    if (nested) Column(Modifier.fillMaxWidth(), content = content) else Card(Modifier.fillMaxWidth(), content = content)
}

@Composable
fun ResearchLists(scan: Scan, nested: Boolean = false) {
    val ctx = LocalContext.current
    if (scan.mustGoRight.isNotEmpty()) {
        SectionHeader2("Must go right", "Each one is a checkpoint with a date")
        ListBlock(nested) { scan.mustGoRight.forEachIndexed { i, w -> WatchRow("${i + 1}", w, TierC.lightGreen) { w.source.takeIf { it.isNotBlank() }?.let { openUrl(ctx, it) } } } }
    }
    if (scan.killSwitches.isNotEmpty()) {
        SectionHeader2("Kill switches", "Thesis breaks if any of these happen")
        ListBlock(nested) { scan.killSwitches.forEach { w -> WatchRow("✗", w, TierC.red) { w.source.takeIf { it.isNotBlank() }?.let { openUrl(ctx, it) } } } }
    }
    if (scan.checklist.isNotEmpty()) {
        var mark by remember { mutableStateOf<Mark?>(null) }
        SectionHeader2("Research checklist", "multibagger-scan rubric · tap a mark for its quote")
        ListBlock(nested) {
            listOf("fundamentals", "valuation", "management", "outlook", "flow").forEach { lens ->
                val ms = scan.checklist[lens].orEmpty()
                if (ms.isNotEmpty()) Row(Modifier.padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                    T(lens.replaceFirstChar { it.uppercase() }, 13.sp, C.grey, modifier = Modifier.width(96.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) { ms.forEach { m -> MarkBox(m) { mark = m } } }
                }
            }
            mark?.let { m ->
                Column(Modifier.padding(top = 8.dp).fillMaxWidth().clip(rr(S.inner)).background(C.card2).padding(10.dp)) {
                    T("${m.id} ${m.name}", 13.sp, weight = FontWeight.SemiBold); if (m.note.isNotBlank()) T(m.note, 12.sp, C.grey)
                    if (m.quote.isNotBlank()) Quote(ctx, m.quote, m.source)
                }
            }
        }
    }
    if (scan.derived.isNotEmpty()) {
        SectionHeader2("Derived from research", "Quoted figure ÷ filed figure")
        ListBlock(nested) {
            scan.derived.forEach { d ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Column(Modifier.weight(1f)) { T(d.name, 14.sp, weight = FontWeight.Medium); T(d.formula + " · " + d.src, 11.sp, C.dim, maxLines = 3) }
                    T(d.value, 15.sp, if (d.good == true) TierC.lightGreen else C.white, FontWeight.SemiBold)
                }
            }
        }
    }
}

// ================================================================ Summary tab (redesign s01) and the decision sheet (s02)
private val LENDERS = setOf("bank", "nbfc", "insurance")
/** Lines of a decision's `why` that are management's own quoted statements (funnel.decide prefixes: driver kinds, "Guidance
 *  quoted: ...", "Guidance reaffirmed (date): ...", "Order book 1.2x revenue (quoted)"); everything else is ours (review 26 Nov 2026). */
private val MGMT_PREFIXES = listOf("Guidance", "Demand", "Margin", "Order", "Capacity", "Capex", "Product", "Driver", "Promise:")
internal fun isMgmtLine(w: String) = (MGMT_PREFIXES.any { w.startsWith(it) } || w.contains(" guidance raised (") || w.contains(" guidance cut (")) &&
    !w.startsWith("Promises kept")
private fun mgmtText(w: String) = if (w.contains(": ")) w.substringAfter(": ") else w
/** The setup's trend-broken flag, from the rule note. */
private fun Setup.trendBroken(): Boolean = note?.startsWith("No entry: trend broken") == true
/** Plain setup name (Look.kt setupName, the same words as every list). */
fun planName(s: Setup): String = setupName(s.type, s.trendBroken())

@Composable
fun SummaryTab(st: AppState, sym: String, p: P?, det: Detail?, chart: Chart?, loaded: Boolean = true, chartLoaded: Boolean = true, openTab: (Int) -> Unit) {
    var formula by remember { mutableStateOf<Triple<String, String, Metric>?>(null) }
    val open: (String?) -> Unit = { k -> k?.let { key -> det?.m(key)?.let { formula = Triple(METRIC_NAMES[key] ?: key, key, it) } } }
    var sheet by rememberSaveable { mutableStateOf("") }  // "decision", "research", "ratios"
    LaunchedEffect(sym) { if (AppRef.openWhy == sym) { AppRef.openWhy = null; sheet = "decision" } }
    val loading = det == null && !loaded  // the stock file is still loading: placeholders, not "missing"
    if (Look.paper) {
        // Paper: the Buy box, the 1-year chart, the plan (#139: before the checks), the seven checks, sector and industry (#140),
        // then the dates to watch (#140: at the end); the rest below
        DecisionCard(st, sym, p, det) { sheet = "decision" }   // feedback #128 + 26 Nov: the Buy box first, tags and lead inside
        PriceCard(p, det, chart, chartLoaded)
        det?.let { PaperPlan(it.setup, it.analyst, p?.p, it.exitHit) }
        p?.let { PaperChecks(st, it, openTab) }
        RotationCard(st, p, det)
        p?.let { PaperDates(it) }
    } else {
        DecisionCard(st, sym, p, det) { sheet = "decision" }
        RotationCard(st, p, det)
        PriceCard(p, det, chart, chartLoaded)
    }
    if (loading) {
        Card(Modifier.fillMaxWidth()) { Skel(90.dp, 15.dp); Spacer(Modifier.height(12.dp)); Skel(null, 12.dp); Spacer(Modifier.height(8.dp)); Skel(null, 12.dp) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(2) { Card(Modifier.weight(1f), radius = S.tile) { Skel(70.dp, 11.dp); Spacer(Modifier.height(8.dp)); Skel(50.dp, 16.dp) } }
        }
    }
    if (!Look.paper) det?.let { PlanCard(it.setup, it.analyst, it.exitHit) }  // Paper (#129): the plan line above is the plan
    det?.let { KeyTiles(it, open) }
    if (!Look.paper) WatchCard(st, sym, p, det)  // Paper (#130): its dates are on the dates line
    Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
        val log = det?.researchLog.orEmpty()
        if (loading) Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            T("Narrativ.ai's research", 14.sp, modifier = Modifier.weight(1f), maxLines = 1); Skel(90.dp, 12.dp)
        }
        else LinkRow("Narrativ.ai's research", if (log.isEmpty()) "not studied yet" else "${log.size} entr${if (log.size == 1) "y" else "ies"} · last ${skDay(log.maxOf { it.date })}") { sheet = "research" }
        if (det != null) LinkRow("All ratios and formulas", divider = true) { sheet = "ratios" }
    }
    when (sheet) {
        "decision" -> DecisionDetailsSheet(st, sym, p, det) { sheet = "" }
        "research" -> ResearchSheet(st, sym, det) { sheet = "" }
        "ratios" -> det?.let { RatiosSheet(it, { sheet = "" }, open) }
    }
    formula?.let { (n, k, m) -> FormulaSheet(n, m, k, det) { formula = null } }
}

/** The seven checks as five-step scales (tap a row for its tab). */
@Composable
private fun PaperChecks(st: AppState, p: P, openTab: (Int) -> Unit) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(5.dp)) {
        // owner, 27 Nov 2026 (board o-S-Score): the overall score in a ring beside the title, moved here from the Why sheet
        Row(Modifier.fillMaxWidth().padding(bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                PaperLabel("The seven checks", size = 11.sp)
                T("Overall score, out of 100", 11.sp, C.dim, maxLines = 1, modifier = Modifier.padding(top = 2.dp))
            }
            ScoreRing(kotlin.math.round(p.pr).toInt())
        }
        LEVEL_SHORT.forEachIndexed { i, name ->
            val t = p.tier(i)
            Row(Modifier.fillMaxWidth().clickable { openTab(i + 1) }, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                T(name, 12.sp, C.grey, modifier = Modifier.width(88.dp), maxLines = 1)
                FiveStep(t, Modifier.width(110.dp))
                T(p.levelTierName(st, i), 12.sp, if (t == 0) C.dim else tierColor(t), FontWeight.SemiBold, maxLines = 1)
            }
        }
    }
}

/** The overall score in a ring: a track, an arc from the top clockwise filled to the score in the verdict colour (70+ pass,
 *  45-69 partly, below 45 miss: the conviction bands), the number centred in lining figures. */
@Composable
fun ScoreRing(score: Int, size: androidx.compose.ui.unit.Dp = 54.dp, stroke: androidx.compose.ui.unit.Dp = 5.dp) {  // 64 -> 54 (feedback #200)
    val v = score.coerceIn(0, 100)
    val col = fillColor(if (v >= 70) "Pass" else if (v >= 45) "Partly" else "Miss")
    val track = C.line
    Box(Modifier.size(size).drawBehind {
        val sw = stroke.toPx()
        val d = this.size.minDimension - sw
        val tl = Offset(sw / 2, sw / 2)
        val sz = androidx.compose.ui.geometry.Size(d, d)
        drawArc(track, 0f, 360f, false, tl, sz, style = androidx.compose.ui.graphics.drawscope.Stroke(sw))
        if (v > 0) drawArc(col, -90f, 360f * v / 100f, false, tl, sz, style = androidx.compose.ui.graphics.drawscope.Stroke(sw, cap = StrokeCap.Round))
    }, contentAlignment = Alignment.Center) {
        // optical centre: a touch above the mathematical centre (owner, 27 Nov 2026), 2% of the ring
        Text("$v", color = C.white, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, fontSize = (size.value * 0.36f).sp, maxLines = 1,
            modifier = Modifier.offset(y = -(size * 0.02f)),
            style = androidx.compose.ui.text.TextStyle(fontFeatureSettings = "lnum",
                platformStyle = androidx.compose.ui.text.PlatformTextStyle(includeFontPadding = false),
                lineHeight = (size.value * 0.36f).sp, lineHeightStyle = androidx.compose.ui.text.style.LineHeightStyle(
                    androidx.compose.ui.text.style.LineHeightStyle.Alignment.Center, androidx.compose.ui.text.style.LineHeightStyle.Trim.Both)))
    }
}

/** The plan on one number line: stop, now, buy zone, analyst target. */
@Composable
private fun PaperPlan(s: Setup, an: Analyst?, now: Double?, exitHit: ExitHit? = null) {
    val lo = s.lo; val hi = s.hi
    // review 26 Nov 2026: Paper had no exit-hit warning and no plan at all without a stop or zone (Classic's PlanCard has both)
    val hitLine = exitHitLine(exitHit)
    if (s.stop == null && lo == null) {
        Column(Modifier.fillMaxWidth()) {
            PaperLabel("The plan", size = 11.sp)
            hitLine?.let { T(it, 13.sp, TierC.red, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp)) }
            T(s.note ?: "No buy zone today.", 13.sp, C.dim, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp))
            // the no-setup zone and the 50-day line, as on the chart (audit 26 Nov 2026)
            if (s.watchLo != null && s.watchHi != null) T("${watchLabel(s)} ${rangeStr(s.watchLo, s.watchHi)}", 13.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp))
            if (s.watchLo != null) s.sma50?.let { T("Weakens below ${skRs(it)} (50-day)", 13.sp, C.amber, lineHeight = 18.sp, modifier = Modifier.padding(top = 2.dp)) }
        }
        return
    }
    val brk = s.type == "Breakout"
    val plan = listOfNotNull(
        s.stop?.let { PlanMark("Stop", it, TierC.red) },
        (now ?: s.price)?.let { PlanMark("Now", it, C.white) },
        lo?.let { PlanMark(if (brk) "Buy above" else "Buy from", it, TierC.darkGreen) },
        hi?.takeIf { it != lo }?.let { PlanMark(if (brk) "+5%" else "to", it, TierC.darkGreen) },
        // feedback #141: the target carries its upside from today's price
    )
    val an1 = an?.mean?.takeIf { it > 0 }?.let { PlanMark("Analyst" + (an.n?.let { n -> " ($n)" } ?: ""), it, TierC.lime, upside(it, now ?: s.price)) }
    // feedback #164 (option A): when stop, price and buy zone sit within 10% of each other, the line zooms on them, labels
    // alternate above and below, and the analyst target becomes a label with its upside (an arrow to its side)
    val pMin = plan.minOfOrNull { it.value }; val pMax = plan.maxOfOrNull { it.value }
    val zoom = an1 != null && pMin != null && pMax != null && pMin > 0 && (pMax - pMin) / pMin <= 0.10 &&
        (an1.value > pMax + (pMax - pMin) || an1.value < pMin - (pMax - pMin))
    val marks = (if (zoom) plan else plan + listOfNotNull(an1)).sortedBy { it.value }
    Column(Modifier.fillMaxWidth()) {
        PaperLabel("The plan", size = 11.sp)
        // labels always alternate above and below (screenshot 26 Nov: IIFL "BUY FROM" and "TO" touched at 520 / 546)
        PlanLine(marks, if (lo != null && hi != null) lo to hi else null, Modifier.fillMaxWidth().height(96.dp),
            zoneLabel = setupName(s.type).uppercase() + if (brk) " ↑" else "", stagger = marks.size > 2)
        if (zoom && an1 != null) {
            val up = an1.value > (pMax ?: 0.0)
            androidx.compose.material3.Text((if (up) "" else "← ") + an1.label.uppercase() + " ₹" + fmt(an1.value, if (an1.value >= 100) 0 else 2) +
                (an1.extra?.let { " · $it" } ?: "") + (if (up) " →" else ""), fontSize = 9.5.sp, color = TierC.lime, fontFamily = PaperFonts.label,
                fontWeight = FontWeight.Bold, maxLines = 1, modifier = Modifier.align(if (up) Alignment.End else Alignment.Start))
        }
        hitLine?.let { T(it, 12.sp, TierC.red, lineHeight = 17.sp, modifier = Modifier.padding(top = 4.dp)) }
        val extra = listOfNotNull(
            s.add?.let { "Buy rest above ${skRs(it)}" },
            if (s.add == null && s.watchLo != null) s.sma50?.let { "Weakens below ${skRs(it)} (50-day)" } else null,
            when { s.rrNote == "Above analyst target" -> "Upside vs risk: above target"; s.rr != null -> "Upside vs risk ${mult(s.rr)}"; else -> null })
        if (extra.isNotEmpty()) T(extra.joinToString(" · "), 11.5.sp, C.dim, maxLines = 2, modifier = Modifier.padding(top = 2.dp))
    }
}

/** The stock's open dated checkpoints on one line: results, shareholding, kill switch, promises. */
@Composable
private fun PaperDates(p: P) {
    val today = skToday()
    // one mark per date (the most serious event on it), at most three
    val rank = listOf("kill_switch", "promise", "must_go_right", "results", "shareholding")
    val cps = p.cp.filter { it.status != "closed" }.mapNotNull { c -> skDate(c.due)?.takeIf { !it.isBefore(today) }?.let { it to c } }
        .groupBy { it.first }.map { (d, l) -> Triple(d, l.minByOrNull { rank.indexOf(it.second.type).let { i -> if (i < 0) 9 else i } }!!.second, l.size) }
        .sortedBy { it.first }.take(3).map { (d, c, n) -> d to c.copy(what = if (n > 1) "+${n - 1}" else null) }
    if (cps.isEmpty()) return
    Column(Modifier.fillMaxWidth()) {
        PaperLabel("Dates to watch", size = 11.sp)
        Box(Modifier.fillMaxWidth().padding(top = 6.dp)) {
            Box(Modifier.padding(start = 6.dp, end = 6.dp, top = 6.dp).fillMaxWidth().height(1.dp).background(C.white))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                cps.forEachIndexed { i, (d, c) ->
                    val ink = when (c.type) { "kill_switch" -> TierC.red; "promise" -> TierC.darkGreen; "must_go_right" -> TierC.yellow; else -> C.white }
                    Column(horizontalAlignment = when (i) { 0 -> Alignment.Start; cps.lastIndex -> Alignment.End; else -> Alignment.CenterHorizontally }) {
                        Box(Modifier.size(13.dp).clip(androidx.compose.foundation.shape.CircleShape)
                            .then(if (c.type == "shareholding") Modifier.background(C.bg).border(2.dp, C.white, androidx.compose.foundation.shape.CircleShape) else Modifier.background(ink)))
                        T("${d.dayOfMonth} ${d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)}", 10.sp, C.white, FontWeight.Bold, maxLines = 1)
                        T(cpWord(c.type) + (c.what?.let { " $it" } ?: ""), 10.sp, if (ink == C.white) C.grey else ink, maxLines = 1)
                    }
                }
            }
        }
        // review 26 Nov 2026: what the exit check is (the strip shows only the date and the word)
        p.cp.firstOrNull { it.type == "kill_switch" && it.status != "closed" }?.what?.let { w ->
            T("Exit check: $w", 11.5.sp, TierC.red, lineHeight = 16.sp, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

// ---------------------------------------------------------------- Paper: the decision box (owner, 26 Nov 2026)
/** A ruled box with a double top rule (no tint): decision, conviction and Top 10 rank, a ticked circle with the review date
 *  (top right), the verdict and setup tags, the lead sentence, the reasons, and the link to all reasons and checks. */
@Composable
private fun PaperDecisionBox(st: AppState, sym: String, p: P?, det: Detail?, onOpen: () -> Unit) {
    val dd = det?.decision ?: p?.dc?.let { Decision(it) }
    val d = dd?.d ?: "Not rated"
    val dcol = decisionColor(d)
    val rv = reviewState(st, sym)
    val ink = C.white
    Column(Modifier.fillMaxWidth().border(1.dp, ink).drawBehind {
            drawRect(ink, size = androidx.compose.ui.geometry.Size(size.width, 2.dp.toPx()))
            drawRect(ink, topLeft = androidx.compose.ui.geometry.Offset(0f, 4.dp.toPx()), size = androidx.compose.ui.geometry.Size(size.width, 1.dp.toPx()))
        }.clickable(onClick = onOpen).padding(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 10.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
        // feedback #199 (owner, 27 Nov 2026): the decision word, its two lines and the seal on one band, the height of the
        // word's capitals: line 1 on its top edge, line 2 on its bottom edge, the seal as tall as the letters
        val big = if (d.length <= 6) 44.sp else 28.sp
        val cv = det?.conviction?.takeIf { it.level != null }
        val l1 = (cv?.level ?: p?.cv)?.let { lvl -> Pair("$lvl conviction" + (cv?.score?.let { " · $it/100" } ?: ""),
            if (lvl == "High") TierC.darkGreen else if (lvl == "Low") TierC.red else TierC.yellow) }
        val l2 = listOfNotNull(
            topTenRank(st, sym)?.let { "#$it in today's Top 10" },
            when {
                rv.verdict == "pass" -> rv.date?.let { skDay(it) }
                rv.verdict != null -> "Review: ${reviewWord(rv.verdict)}"
                rv.pos > 0 -> "Review #${rv.pos} of ${rv.of} in queue"
                rv.pos != 0 -> "In the research queue"
                rv.studied == null -> "Rules only, not studied"
                else -> null
            }).joinToString(" · ").ifBlank { null }
        val density = androidx.compose.ui.platform.LocalDensity.current
        val bandDp = with(density) { (CAP_PLAYFAIR * big.toPx()).let { kotlin.math.round(it) }.toDp() }
        Row(Modifier.padding(vertical = 2.dp).height(bandDp), verticalAlignment = Alignment.CenterVertically) {
            Text(d.uppercase(), fontSize = big, color = dcol, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1,
                modifier = Modifier.capBand(CAP_PLAYFAIR, big))
            Spacer(Modifier.width(12.dp))
            val lines = listOfNotNull(l1?.let { Triple(it.first, it.second, true) }, l2?.let { Triple(it, C.grey, false) })
            Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = if (lines.size == 2) Arrangement.SpaceBetween else Arrangement.Center) {
                lines.forEach { (t, c, bold) ->
                    val fs = if (bold) 12.5.sp else 11.5.sp
                    Text(t.uppercase(), fontSize = fs, color = c, fontFamily = PaperFonts.label, fontWeight = if (bold) FontWeight.Bold else FontWeight.Medium,
                        letterSpacing = 0.25.sp, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        modifier = Modifier.capBand(CAP_ARCHIVO, fs))
                }
            }
            if (rv.verdict == "pass") { Spacer(Modifier.width(8.dp)); VerifiedSeal(bandDp + 0.5.dp) }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(ink))
        if (p != null) androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (p.vd.isNotBlank()) PaperTag(p.vd, verdictColor(p.vd))
            p.su?.let { PaperTag(setupName(it, p.tb == 1), C.white) }
        }
        val lead = p?.why ?: dd?.why?.firstOrNull()
        lead?.let { Text(it, fontSize = 15.sp, lineHeight = 20.sp, color = C.white, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Bold) }  // feedback #150: upright, not italic
        val why = dd?.why.orEmpty(); val missing = dd?.missing.orEmpty()
        val fwd = why.filter { isMgmtLine(it) }.map { mgmtText(it) }.take(3)
        val reasons = (if (fwd.isNotEmpty()) fwd else why.filter { !it.startsWith("Verified") }.take(2)) + missing.take(1)
        if (reasons.isNotEmpty()) {
            HLineDivider()
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                reasons.forEach { r -> Row { T("▪", 12.sp, C.white, modifier = Modifier.width(14.dp)); T(r, 13.sp, if (r in missing) C.amber else C.white, lineHeight = 18.sp) } }
            }
        }
        MoreLink("All reasons and checks", onClick = onOpen)
    }
}

// ---------------------------------------------------------------- decision card
@Composable
private fun DecisionCard(st: AppState, sym: String, p: P?, det: Detail?, onOpen: () -> Unit) {
    if (Look.paper) { PaperDecisionBox(st, sym, p, det, onOpen); return }
    val dd = det?.decision ?: p?.dc?.let { Decision(it) }
    val d = dd?.d ?: "Not rated"
    val dcol = decisionColor(d)
    val rv = reviewState(st, sym)
    Column(Modifier.fillMaxWidth().clip(rr(S.card)).background(C.card)
        .background(Brush.linearGradient(listOf(dcol.copy(alpha = 0.16f), Color.Transparent))).clickable(onClick = onOpen).padding(S.cardPad)) {
        Row(verticalAlignment = Alignment.Top) {
            T(d.uppercase(), if (d.length <= 6) 40.sp else 26.sp, dcol, FontWeight.ExtraBold, maxLines = 1, lineHeight = 44.sp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f).padding(top = 4.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                when {
                    rv.verdict == "pass" -> Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.Check, null, tint = reviewColor(rv.verdict), modifier = Modifier.size(15.dp)); Spacer(Modifier.width(4.dp))
                        T("Narrativ.ai verified" + (rv.date?.let { " ${skDay(it)}" } ?: ""), 13.sp, reviewColor(rv.verdict), maxLines = 1)
                    }
                    rv.verdict != null -> T("Narrativ.ai's review: ${reviewWord(rv.verdict)}" + (rv.date?.let { " · ${skDay(it)}" } ?: ""), 13.sp, reviewColor(rv.verdict), maxLines = 1)
                    rv.pos > 0 -> T("Narrativ.ai's review: #${rv.pos} of ${rv.of} in the queue", 13.sp, C.dim, maxLines = 2)
                    rv.pos != 0 -> T("In Narrativ.ai's research queue", 13.sp, C.dim, maxLines = 1)
                    rv.studied != null -> T("Narrativ.ai's notes only, no full review yet", 13.sp, C.dim, maxLines = 2)
                    else -> T("Rules only: not studied by Narrativ.ai", 13.sp, C.dim, maxLines = 2)
                }
                val cv = det?.conviction?.takeIf { it.level != null }
                val level = cv?.level ?: p?.cv
                if (level != null) {
                    Row(verticalAlignment = Alignment.CenterVertically) { T("Conviction ", 13.sp, C.dim, maxLines = 1); T(level, 13.sp, weight = FontWeight.SemiBold, maxLines = 1) }
                    if (cv?.score != null) T("${cv.score}/100" + (cv.size?.let { " · $it position" } ?: ""), 12.sp, C.dim, maxLines = 1)
                    else if (cv?.met != null && cv.of != null && cv.of > 0) Meter(cv.of, cv.met, color = TierC.lightGreen, style = MeterStyle.Dot)
                }
                topTenRank(st, sym)?.let { T("#$it in today's Top 10", 13.sp, C.dim, maxLines = 1) }
            }
        }
        val why = dd?.why.orEmpty()
        val missing = dd?.missing.orEmpty()
        val fwd = why.filter { isMgmtLine(it) }.map { mgmtText(it) }.take(2)
        val lv = det?.levels
        // tier words as the level tabs name them (a quality turnaround is "turnaround watch", P.levelTierName / LevelTab)
        fun tierWord(k: String, pre: String) = lv?.get(k)?.takeIf { it.t != 0 }?.let { l ->
            if (k == "qual" && (l.turn || p?.turn == true)) "Turnaround watch" else l.name.ifBlank { null }
        }?.let { if (pre.isEmpty()) it else "$pre ${it.lowercase()}" }
        val tiers = listOfNotNull(tierWord("val", ""), tierWord("surv", "stability"), tierWord("qual", "quality")).joinToString(" · ")
        val reasons = (if (fwd.isNotEmpty()) fwd else why.filter { !it.startsWith("Verified") }.take(2)) + listOfNotNull(tiers.ifBlank { null }) + missing.take(1)
        if (reasons.isNotEmpty()) Column(Modifier.padding(top = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            reasons.forEach { r ->
                Row { T("•", 14.sp, C.white, modifier = Modifier.width(14.dp)); T(r, 14.sp, if (r in missing) C.amber else C.white, lineHeight = 20.sp) }
            }
        }
        MoreLink("All reasons and checks", onClick = onOpen)
    }
}

// ---------------------------------------------------------------- sector / industry rotation
@Composable
private fun RotationCard(st: AppState, p: P?, det: Detail?) {
    val ind = p?.i ?: det?.stock?.industry ?: return
    val secKey = SECTOR_OF[ind]
    val sec = secKey?.let { st.rotation?.sectors?.get(it) }
    val ir = st.rotation?.industries?.get(ind)
    if (sec == null && ir == null) return
    // feedback #78: one line each, where it stands vs the market and which way it is heading (no quadrant map)
    Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            sec?.let { RotLine("Sector · ${it.ticker ?: "Nifty $secKey"}", it) }
            ir?.let { RotLine("Industry · $ind", it) }
        }
    }
}

@Composable
private fun RotLine(label: String, r: Rot) {
    val qc = quadC(r.q)
    val up = r.mom >= 100.0
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Column(Modifier.weight(1f)) {
            T(label, 11.sp, C.dim, maxLines = 1)
            Row(verticalAlignment = Alignment.CenterVertically) {
                T(r.q.ifBlank { "–" }, 15.sp, qc, FontWeight.Bold, maxLines = 1)
                if (r.q.isNotBlank()) Icon(if (up) Icons.Rounded.NorthEast else Icons.Rounded.SouthEast, null,
                    tint = if (up) TierC.lightGreen else TierC.lightRed, modifier = Modifier.padding(start = 4.dp).size(16.dp))
            }
        }
        r.r1m?.let { ValChip("1M ${skSgn(it)}", gainColor(it)) }
        r.r3m?.let { ValChip("3M ${skSgn(it)}", gainColor(it)) }
    }
}

// ---------------------------------------------------------------- price chart with the plan levels
private val RANGES = listOf("1M" to 22, "3M" to 65, "6M" to 130, "1Y" to 260)

@Composable
private fun PriceCard(p: P?, det: Detail?, chart: Chart?, chartLoaded: Boolean = true) {
    var range by rememberSaveable { mutableIntStateOf(3) }
    val all = chart?.c.orEmpty()
    val s = det?.setup
    Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SegmentedControl(RANGES.map { it.first }, range, { range = it }, compact = true)
            Spacer(Modifier.weight(1f))
            val lo = det?.stock?.lo52; val hi = det?.stock?.hi52
            if (lo != null && hi != null) Range52(lo, hi, p?.p ?: all.lastOrNull())
        }
        if (all.size < 2) {
            if (!chartLoaded) Skel(null, 190.dp, Modifier.padding(top = 10.dp))
            else T("Chart is published for stocks in the funnel.", 12.sp, C.dim, modifier = Modifier.padding(8.dp))
            return@Card
        }
        val n = RANGES[range].second
        val vals = all.takeLast(n)
        val col = if (vals.last() >= vals.first()) TierC.lightGreen else TierC.lightRed
        val bands = mutableListOf<HBand>(); val lines = mutableListOf<HLine>()
        // the dip zone and "buy rest above" take the Plan card's colour (white), never blue
        if (s?.lo != null && s.hi != null) bands += HBand(s.lo, s.hi, TierC.darkGreen, "Buy zone ${rangeStr(s.lo, s.hi)}")
        else if (s?.watchLo != null && s.watchHi != null) bands += HBand(s.watchLo, s.watchHi, C.white, "${watchLabel(s)} ${rangeStr(s.watchLo, s.watchHi)}", alpha = 0.12f)
        s?.add?.let { lines += HLine(it, C.white, "Buy rest above ${skRs(it)}") }
        if (s?.add == null && s?.watchLo != null) s.sma50?.let { lines += HLine(it, C.amber, "50-day ${skRs(it)}") }
        s?.stop?.let { lines += HLine(it, TierC.lightRed, "Exit ${skRs(it)}", labelBelow = true) }
        // analyst target (feedback #87): only when it sits inside the chart's range or up to 15% above it (the range grows to it)
        det?.analyst?.takeIf { it.mean > 0 }?.let { an ->
            val base = vals + lines.map { it.value } + bands.flatMap { listOf(it.lo, it.hi) }
            val bLo = base.minOrNull() ?: an.mean; val bHi = base.maxOrNull() ?: an.mean
            if (an.mean >= bLo && an.mean <= bHi + 0.15 * (bHi - bLo).coerceAtLeast(bHi * 0.02))
                lines += HLine(an.mean, TierC.lime.takeIf { Look.paper } ?: C.white, "Analyst target ${skRs(an.mean)}" + (upside(an.mean, p?.p ?: vals.last())?.let { " · $it" } ?: "") + (an.n?.let { " · $it analyst" + (if (it == 1) "" else "s") } ?: ""), labelRight = true)
        }
        // feedback #105: "H" / "L" dots at the highest and lowest close of the last 250 sessions, only when the shown window includes them
        val marks = hiLoMarks(all, vals.size)
        val months = mapOf(22 to 1L, 65 to 3L, 130 to 6L, 260 to 12L)[n] ?: 12L
        val start = if (n >= all.size && chart?.d0 != null) skDate(chart.d0) else skToday().minusMonths(months)
        val startLabel = start?.let { if (months <= 3) skDay(it.toString()) else shortMonth(it.toString()) } ?: ""
        AreaLine(vals, Modifier.fillMaxWidth().height(190.dp).padding(top = 10.dp), color = col, fillAlpha = 0.22f, strokeWidth = 1.8.dp,
            bands = bands, lines = lines, hollowEnd = true, xLabels = listOf(startLabel, "Now ${skRs(p?.p ?: vals.last())}"), marks = marks)
    }
}

/** About 52 weeks of sessions, for the chart's "H" / "L" closes. */
const val SESSIONS_52W = 250

/**
 * feedback #105: index (in the last [shown] closes of [all]) of the highest close ("H", label above) and lowest close ("L", label below)
 * of the last [SESSIONS_52W] sessions; a mark outside the shown window is left out.
 */
fun hiLoMarks(all: List<Double>, shown: Int): List<PointMark> {
    if (all.size < 2 || shown < 2) return emptyList()
    val off = (all.size - SESSIONS_52W).coerceAtLeast(0)
    val w = all.subList(off, all.size)
    val ih = off + w.indices.maxBy { w[it] }; val il = off + w.indices.minBy { w[it] }
    if (ih == il) return emptyList()
    val start = all.size - shown.coerceAtMost(all.size)
    return listOfNotNull(
        PointMark(il - start, "L", above = false).takeIf { il >= start },
        PointMark(ih - start, "H", above = true).takeIf { ih >= start },
    )
}

/** feedback #105: "L ₹lo ──●── H ₹hi" in the chart's range row; the dot is today's price on the 52-week range. */
@Composable
private fun Range52(lo: Double, hi: Double, now: Double?) {
    val f = if (now == null || hi <= lo) null else ((now - lo) / (hi - lo)).coerceIn(0.0, 1.0).toFloat()
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        T("L ${skRs(lo)}", 12.sp, C.dim, maxLines = 1)
        Canvas(Modifier.size(42.dp, 12.dp)) {
            val x0 = 4.dp.toPx(); val x1 = size.width - 4.dp.toPx(); val cy = size.height / 2
            drawLine(C.hi.copy(alpha = 0.25f), Offset(x0, cy), Offset(x1, cy), 1.5.dp.toPx(), cap = StrokeCap.Round)
            f?.let { drawCircle(C.white, 4.dp.toPx(), Offset(x0 + it * (x1 - x0), cy)) }
        }
        T("H ${skRs(hi)}", 12.sp, C.dim, maxLines = 1)
    }
}

// ---------------------------------------------------------------- plan
/** The Plan card's sources line, shown under "How these are set" in the (i) sheet. */
const val PLAN_BASED = "Based on: Donchian / Turtle 55-day breakout; Wilder's average true range for the exit; O'Neil's 5% chase and 8% loss limits. " +
    "Our replay: stocks with a live setup beat the Nifty more often (51–53% vs 31–43%)."

/** The no-setup zone (10–21 day averages): "Buy on a dip to" only while the price is above it (audit 26 Nov 2026). */
fun watchLabel(s: Setup): String = if (s.price != null && s.watchLo != null && s.price >= s.watchLo) "Buy on a dip to" else "Watch zone"

/** feedback #92: the amber line while the stock cools off after its exit level broke; null when there is no exit_hit. */
fun exitHitLine(e: ExitHit?): String? {
    val stop = e?.stop ?: return null
    val lvl = "₹" + skFx(stop, 2)
    return "Exit level $lvl" + (e.date?.let { " hit on ${skDay(it)}" } ?: " hit") + ": no new call until a close back above $lvl" +
        (e.reentryAfter?.let { " or after ${skDay(it)}" } ?: " or 10 trading days")
}

@Composable
private fun PlanCard(s: Setup, an: Analyst? = null, exitHit: ExitHit? = null) {
    var info by remember { mutableStateOf(false) }
    val target = an?.takeIf { it.mean > 0 }
    val rows = buildList {
        if (s.lo != null && s.hi != null) add(Triple(if (s.type == "Breakout") "Buy on a close above" else "Buy between",
            if (s.type == "Breakout") skRs(s.lo) else rangeStr(s.lo, s.hi), C.white))
        else if (s.watchLo != null && s.watchHi != null) add(Triple(watchLabel(s), rangeStr(s.watchLo, s.watchHi), C.white))
        s.add?.let { add(Triple("Buy rest above", skRs(it), C.white)) }
        if (s.add == null && s.watchLo != null) s.sma50?.let { add(Triple("Weakens below (50-day)", skRs(it), C.amber)) }
        s.stop?.let { add(Triple("Exit if it closes below", skRs(it), TierC.lightRed)) }
        when {
            s.rrNote == "Above analyst target" -> add(Triple("Upside vs risk", "above target", C.amber))
            s.rr != null -> add(Triple("Upside vs risk", mult(s.rr), C.white))
        }
        target?.let { a ->
            val extra = listOfNotNull(a.upside?.let { skSgn(it) }, a.n?.let { "$it analyst" + if (it == 1) "" else "s" })
            add(Triple("Analyst target", skRs(a.mean) + if (extra.isEmpty()) "" else " (${extra.joinToString(", ")})", C.white))
        }
    }
    val how = planHow(s, showNote = rows.isNotEmpty())
    Card(Modifier.fillMaxWidth()) {
        // feedback #98: "How these are set" moves from the card's foot into a sheet behind a small (i) in the header
        Row(Modifier.fillMaxWidth().padding(bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            T("Plan", SECTION_TITLE, weight = FontWeight.SemiBold); Spacer(Modifier.width(8.dp))
            StatusChip(planName(s), color = setupColor(s.type, s.trendBroken()), minWidth = 0.dp)
            Spacer(Modifier.weight(1f))
            if (how.isNotEmpty()) Box(Modifier.size(32.dp).clip(CircleShape).background(C.hi.copy(alpha = 0.07f)).clickable { info = true },
                contentAlignment = Alignment.Center) {
                Icon(Icons.Outlined.Info, "How these are set", tint = C.dim, modifier = Modifier.size(20.dp))
            }
        }
        exitHitLine(exitHit)?.let { line ->
            Row(Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 6.dp).clip(rr(10.dp)).background(C.amber.copy(alpha = 0.08f))
                .padding(horizontal = 10.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.padding(top = 5.dp).size(7.dp).clip(CircleShape).background(C.amber))
                T(line, 12.5.sp, C.amber, lineHeight = 17.sp)
            }
        }
        if (rows.isEmpty() || s.type == "No setup") T(s.note ?: "No buy zone today.", 13.sp, C.dim, modifier = Modifier.padding(bottom = if (rows.isEmpty()) 0.dp else 4.dp))
        rows.forEachIndexed { i, (k, v, c) -> KvRow(k, v, valueColor = c, divider = i < rows.lastIndex) }
    }
    if (info) BottomSheet({ info = false }, "How these are set") {
        how.forEach { T(it, 14.sp, C.white, lineHeight = 20.sp, modifier = Modifier.padding(bottom = 10.dp)) }
        T(PLAN_BASED, 12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

/** The Plan card's "How these are set" sentences from the setup's own numbers; a sentence whose numbers are missing is left out. */
fun planHow(s: Setup, showNote: Boolean = true): List<String> = buildList {
    val zoneExit = if (s.stopBasis == "zone" && s.atr != null && s.stop != null)
        "Exit: 1.5 × the average daily move (${priceStr(s.atr)}) under the buy zone's low, and never more than 8% under it: ${skRs(s.stop)}." else null
    when (s.type) {
        "Breakout" -> {
            val h = s.h55 ?: s.lo
            if (h != null && s.hi != null) add("Entry: a breakout. Buy on a close above the 55-day high, ${skRs(h)}, and not more than 5% above it (${skRs(s.hi)}).")
            if (s.stopBasis == "zone") zoneExit?.let { add(it) }
            else if (s.ref != null && s.atr != null && s.stop != null)
                add("Exit: ${skRs(s.ref)} less 1.5 × the average daily move (${priceStr(s.atr)}), and never more than 8% below it: ${skRs(s.stop)}.")
        }
        "Pullback" -> {
            if (s.lo != null && s.hi != null) add("Entry: a dip in an uptrend, to the 10–21 day averages (${rangeStr(s.lo, s.hi)}).")
            if (s.stopBasis == "zone") zoneExit?.let { add(it) }
            else s.sma50?.let { add("Exit: a close below the 50-day average (${skRs(it)}).") }
        }
        "Base" -> {
            if (s.lo != null && s.hi != null) add("Entry: near the 20-day low (${rangeStr(s.lo, s.hi)})" + (s.add?.let { "; add above the 50-day average (${skRs(it)})." } ?: "."))
            if (s.stopBasis == "zone") zoneExit?.let { add(it) }
            else s.stop?.let { add("Exit: 1.5 × the average daily move under the 20-day low, never more than 10% under it: ${skRs(it)}.") }
        }
        else -> if (showNote) s.note?.takeIf { it.isNotBlank() }?.let { add(it) }
    }
    s.rr?.let { rr -> add("Reward to risk: ${mult(rr)} to the analyst target" + (s.rrNote?.takeIf { it.isNotBlank() }?.let { " (${it.lowercase()})" } ?: "") + ".") }
}

// ---------------------------------------------------------------- four key numbers with small visuals
@Composable
private fun RowScope.KeyTile(label: String, value: String, onClick: () -> Unit, color: Color = C.white, content: (@Composable ColumnScope.() -> Unit)? = null) =
    StatTile(label, value, Modifier.weight(1f).heightIn(min = 86.dp), valueColor = color, onClick = onClick, content = content)

/** feedback #79: a key number takes its check's colour (Pass / Partly / Miss); white when the check is not scored. */
private fun checkColor(lv: Level?, id: String): Color = lv?.item(id)?.m?.let { statusColor(statusOf(it)) } ?: C.white

@Composable
private fun KeyTiles(det: Detail, open: (String?) -> Unit) {
    val lender = det.stock.kind in LENDERS
    val vl = det.levels["val"]
    val vkey = vl?.mkey ?: METRIC_KEY_OF[vl?.metric] ?: if (lender) "pb" else "pe"
    val hist = det.hist.mapNotNull { it[histKey(vkey)]?.content?.toDoubleOrNull() }
    val vnow = vl?.mval ?: det.v(vkey)
    val qual = det.levels["qual"]
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val metric = vl?.metric ?: METRIC_NAMES[vkey] ?: "P/E"
            // short label; the own range goes on a dim line under the figure (half-width tile)
            KeyTile(metric, mult(vnow), { open(vkey) }, checkColor(vl, "V1")) {
                val c = if (vl?.item("V1")?.m != null) statusColor(vl.status("V1")) else C.muted
                if (hist.size >= 2 && vnow != null) MiniRange(hist.min(), hist.max(), vnow, c)
                if (hist.size >= 2) T("own ${skFx(hist.min(), 1)}–${mult(hist.max())}", LABEL, C.dim, maxLines = 1)
            }
            if (lender) KeyTile("ROE", det.v("roe_pct")?.let { "${skFx(it, 1)}%" } ?: "–", { open("roe_pct") }, checkColor(qual, "Q1"))
            else {
                val roce = det.roceFy
                KeyTile(METRIC_NAMES.getValue("roce_3y_avg_pct"),
                    det.v("roce_3y_avg_pct")?.let { "${skFx(it, 1)}%" } ?: "–", { open("roce_3y_avg_pct") }, checkColor(qual, "Q1")) {
                    if (roce.size >= 2) {
                        Bars(roce.map { it.second }, Modifier.fillMaxWidth().height(26.dp), color = C.muted, base = roce.minOf { it.second } * 0.85, barFrac = 0.75f)
                        T("FY${roce.first().first % 100}–FY${roce.last().first % 100}", LABEL, C.dim, maxLines = 1)
                    }
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val rev = det.quarterly.mapNotNull { it.getOrNull(1) }
            KeyTile(METRIC_NAMES.getValue("rev_cagr_3y_pct"), det.v("rev_cagr_3y_pct")?.let { "${skFx(it, 1)}%" } ?: "–", { open("rev_cagr_3y_pct") }, checkColor(qual, "Q3")) {
                if (rev.size >= 2) {
                    Sparkline(rev, Modifier.fillMaxWidth().height(26.dp), color = C.muted, area = true, endDot = true)
                    T("revenue, last ${rev.size} quarters", LABEL, C.dim, maxLines = 1)
                }
            }
            if (lender) KeyTile("Gross NPA", det.v("gnpa_pct_advances")?.let { "${skFx(it, 1)}%" } ?: "–", { open("gnpa_pct_advances") }, checkColor(det.levels["surv"], "C1"))
            else {
                val cc = det.v("cfo_to_ebitda_pct")
                KeyTile("Cash conversion", cc?.let { "${skFx(it, 0)}%" } ?: "–", { open("cfo_to_ebitda_pct") }, checkColor(qual, "Q7")) {
                    if (cc != null) FillBar(cc, 0.0, 100.0, 70.0, fillColor(qual?.status("Q7") ?: "n/a"), Modifier.fillMaxWidth(), unit = "%")
                    else T("pass ≥ 70%", LABEL, C.dim, maxLines = 1)
                }
            }
        }
    }
}

// ---------------------------------------------------------------- what to watch
@Composable
private fun WatchCard(st: AppState, sym: String, p: P?, det: Detail?) {
    val today = skToday()
    val items = buildList {
        val nr = det?.stock?.nextResults
        val nd = skDate(nr?.date)
        if (nr != null && nd != null && !nd.isAfter(today)) {
            val filed = det.stock.events.any { e -> (skDate(e.date)?.let { d -> !d.isBefore(nd) } ?: false) &&
                Regex("result", RegexOption.IGNORE_CASE).containsMatchIn(e.category ?: e.type) }
            add(TimelineItem(skDay(nr.date), "Last results", if (filed) "filed" else nr.purpose, C.dim))
        }
        add(TimelineItem(skDay(today.toString()), "Today", today = true))
        if (nr != null && nd != null && nd.isAfter(today)) add(TimelineItem(skDay(nr.date), "Results", nr.purpose, C.muted, hollow = true))
        val ks = st.research[sym]?.scan?.killSwitches.orEmpty().filter { skDate(it.due)?.isAfter(today) ?: false }.minByOrNull { it.due ?: "" }
        if (ks != null) add(TimelineItem(skDay(ks.due), ks.text, "Kill switch · check: ${ks.check}", TierC.red))
        else p?.cp?.filter { (it.status == "open" || it.status == "due") && it.due != null && it.type != "results" }?.minByOrNull { it.due!! }?.let { c ->
            add(TimelineItem(skDay(c.due), c.what ?: c.type ?: "", (c.type ?: "").replace('_', ' ').replaceFirstChar { it.uppercase() }, C.muted))
        }
    }
    if (items.size < 2) return
    SectionCard("What to watch") { DotTimeline(items) }
}

// ---------------------------------------------------------------- decision details sheet (s02)
@Composable
fun DecisionDetailsSheet(st: AppState, sym: String, p: P?, det: Detail?, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val dd = det?.decision ?: p?.dc?.let { Decision(it) }
    val r = st.research[sym]
    val audit = r?.audit
    val dn = dd?.d ?: "Not rated"
    BottomSheet(onDismiss, "Why " + if (dn == "Not rated") "not rated" else dn) {
        if (Look.paper) { PaperWhyBody(st, sym, p, det, dd); return@BottomSheet }  // owner, 27 Nov 2026: boards o-A-Verdict + o-A2-Rest
        // feedback #165 (owner, 26 Nov 2026): "How sure are we?" first: the rule-built conviction and its seven checks
        val cv = det?.conviction
        val cvLevel = cv?.level
        if (cv != null && cvLevel != null && cv.score != null) SheetSection("How sure are we?", cv.date?.let { skDay(it) }) {
            // feedback #175 (owner, 26 Nov 2026): a score from proofs, no dots; each proof one line with its points; what is
            // missing as one statement each; the level sets the position size (option C)
            val col = if (cvLevel == "High") TierC.lightGreen else if (cvLevel == "Low") TierC.lightRed else TierC.yellow
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                T(cvLevel, 22.sp, col, FontWeight.Bold)
                T("${cv.score}/100", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.padding(bottom = 2.dp))
                cv.size?.let { T("· $it position", 13.sp, C.dim, modifier = Modifier.padding(bottom = 3.dp)) }
            }
            Row(Modifier.fillMaxWidth().padding(top = 6.dp).height(7.dp), horizontalArrangement = Arrangement.spacedBy(1.dp)) {
                // v4 bands (owner, 27 Nov 2026): High 55+, Medium 40-54
                listOf(40f to "Low", 15f to "Medium", 45f to "High").forEach { (w, l) ->
                    val c = if (l == "High") TierC.lightGreen else if (l == "Low") TierC.lightRed else TierC.yellow
                    Box(Modifier.weight(w).fillMaxHeight().background(c.copy(alpha = if (l == cvLevel) 0.95f else 0.22f)))
                }
            }
            Row(Modifier.fillMaxWidth().padding(top = 2.dp)) {
                T("Low", 9.sp, C.dim, modifier = Modifier.weight(40f)); T("40", 9.sp, C.dim, modifier = Modifier.weight(15f)); T("55 · High", 9.sp, C.dim, modifier = Modifier.weight(45f))
            }
            // review 26 Nov 2026: a score in the High band (55+ from v4) kept at Medium says why (open integrity item or incomplete data)
            if ((cv.score ?: 0) >= 55 && cvLevel != "High") cv.why?.substringAfter("; ", "")?.takeIf { it.isNotBlank() }?.let {
                T(it.replaceFirstChar { c -> c.uppercase() }, 12.sp, TierC.yellow, lineHeight = 16.sp, modifier = Modifier.padding(top = 4.dp))
            }
            if (cv.proofs.isNotEmpty()) T("PROOFS", 10.sp, C.dim, FontWeight.Bold, modifier = Modifier.padding(top = 10.dp, bottom = 2.dp))
            cv.proofs.forEach { pr ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.Top) {
                    T("+${pr.pts}", 13.sp, TierC.lightGreen, FontWeight.Bold, maxLines = 1, modifier = Modifier.width(38.dp))
                    Column(Modifier.weight(1f)) {
                        T(pr.t, 13.sp, lineHeight = 18.sp)
                        pr.v?.takeIf { it.isNotBlank() }?.let { T(it, 11.5.sp, C.dim, lineHeight = 16.sp) }
                    }
                }
            }
            if (cv.notYet.isNotEmpty()) T("NOT YET", 10.sp, C.dim, FontWeight.Bold, modifier = Modifier.padding(top = 10.dp, bottom = 2.dp))
            cv.notYet.forEach { t ->
                Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
                    T("0", 13.sp, C.dim, maxLines = 1, modifier = Modifier.width(38.dp)); T(t, 12.5.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.weight(1f))
                }
            }
        } else if (cv != null && cvLevel != null) SheetSection("How sure are we?", cv.date?.let { skDay(it) }) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                T("$cvLevel conviction", 18.sp, if (cvLevel == "High") TierC.lightGreen else if (cvLevel == "Low") TierC.lightRed else TierC.yellow, FontWeight.Bold)
                val oks = cv.checks.map { it.ok == true }
                if (oks.isNotEmpty()) Meter(oks.size, oks.count { it }, colors = oks.map { if (it) TierC.lightGreen else C.line }, style = MeterStyle.Dot)
                if (cv.met != null && cv.of != null) T("${cv.met} of ${cv.of}", 12.sp, C.dim)
            }
            // every check as a row: a status circle and its name; a check not met adds its figure or reason (feedback #88, no bare codes)
            cv.checks.forEach { c ->
                val ok = c.ok == true
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.Top) {
                    T(if (ok) "✓" else "–", 13.sp, if (ok) TierC.lightGreen else C.dim, FontWeight.Bold, maxLines = 1, modifier = Modifier.width(18.dp))
                    Text(buildAnnotatedString {
                        append(c.n.ifBlank { "Check" })
                        if (!ok) (c.v ?: c.why)?.takeIf { it.isNotBlank() }?.let { withStyle(SpanStyle(color = C.dim)) { append(" · $it") } }
                    }, color = C.white, fontSize = 13.sp, lineHeight = 18.sp, modifier = Modifier.weight(1f))
                }
            }
        } else p?.cv?.let { lv -> SheetSection("How sure are we?") { T("$lv conviction", 15.sp, weight = FontWeight.Bold) } }
        val why = dd?.why.orEmpty()
        val levelNames = LEVEL_SHORT.toSet()
        val lvl = why.filter { it.substringBefore(":") in levelNames }
        val valn = why.filter { it !in lvl && (it.contains("valuation", ignoreCase = true) || it.contains("base case")) }
        val rev = why.filter { it.startsWith("Verified") }
        // feedback #175 / review 26 Nov 2026: only management's own quoted statements under the guidance heading; our signals
        // and the setup are proofs (conviction); other rule notes go to "Other notes"; R1 / R2 lender notes are not shown
        val fwd = why.filter { it !in lvl && it !in valn && it !in rev && isMgmtLine(it) }
        val other = why.filter { it !in lvl && it !in valn && it !in rev && it !in fwd && !it.startsWith("R1 and R2 not applied") &&
            !it.startsWith("Re-scored") &&
            (cv?.proofs.isNullOrEmpty() || (!it.startsWith("Signal") && !it.startsWith("No entry setup") && !it.startsWith("Entry setup"))) }
        @Composable
        fun levelChips(keys: Set<String>) {
            val mine = lvl.filter { it.substringBefore(":") in keys }
            if (mine.isEmpty()) return
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                mine.forEach { w ->
                    val k = w.substringBefore(":"); val li = LEVEL_SHORT.indexOf(k); val lvd = det?.levels?.get(LEVELS[li])
                    // the same tier words as the level tab (a quality turnaround reads "Turnaround watch")
                    val nm = if (li == 1 && (lvd?.turn ?: p?.turn ?: false) && (lvd?.t ?: p?.tier(1) ?: 0) != 0) "Turnaround watch" else w.substringAfter(": ")
                    val c = tierColor(lvd?.t ?: 0)
                    Row(Modifier.clip(rr(S.inner)).background(C.chip).padding(horizontal = 10.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Box(Modifier.size(7.dp).clip(CircleShape).background(c)); T(k, 12.sp, C.muted, maxLines = 1); T(nm, 12.sp, c, FontWeight.Bold, maxLines = 1)
                    }
                }
            }
        }
        val bizKeys = setOf("Stability", "Quality", "Management", "Outlook"); val timeKeys = setOf("Momentum", "Discovery")
        if (lvl.any { it.substringBefore(":") in bizKeys }) SheetSection("Is it a good business?") { levelChips(bizKeys) }
        val vlv = det?.levels?.get("val")
        if (vlv != null || valn.isNotEmpty()) SheetSection("Is the price right?") {
            vlv?.let { v -> FlowRow { DotChip("Valuation · " + v.name, tierColor(v.t)) } }
            valn.forEach { T(it.substringBefore(";"), 12.sp, C.dim, modifier = Modifier.padding(top = 6.dp)) }
        }
        if (lvl.any { it.substringBefore(":") in timeKeys }) SheetSection("Is now the time?") { levelChips(timeKeys) }
        if (fwd.isNotEmpty()) SheetSection("Future guidance by management", "${fwd.size} quoted") {
            fwd.forEach { w ->
                Row(Modifier.padding(vertical = 4.dp)) {
                    if (w.contains(": ")) { T(w.substringBefore(": "), 13.sp, C.dim, modifier = Modifier.width(84.dp)); T(w.substringAfter(": "), 13.sp, lineHeight = 18.sp) }
                    else T(w, 13.sp, lineHeight = 18.sp)
                }
            }
        }
        if (other.isNotEmpty()) SheetSection("Other notes") { other.forEach { T(it, 12.5.sp, C.muted, lineHeight = 17.sp, modifier = Modifier.padding(vertical = 3.dp)) } }
        val missing = dd?.missing.orEmpty()
        if (missing.isNotEmpty()) SheetSection("Not a verified Buy yet") {
            missing.forEach { m ->
                Row(Modifier.padding(vertical = 4.dp)) {
                    Box(Modifier.padding(top = 6.dp).size(6.dp).clip(CircleShape).background(C.amber)); Spacer(Modifier.width(8.dp)); T(m, 13.sp, lineHeight = 18.sp)
                }
            }
        }
        // Claude's review
        SheetSection("Checked by Narrativ.ai", audit?.date?.let { skDay(it) }) {
            if (audit == null) {
                val rv = reviewState(st, sym)
                T(when { rv.verdict != null -> "Narrativ.ai's review: ${reviewWord(rv.verdict)}"; rv.pos > 0 -> queueLabel(st, sym) ?: "In Narrativ.ai's review queue"; rv.pos != 0 -> "In Narrativ.ai's research queue"
                         rv.studied != null -> "Narrativ.ai's notes only (${skDay(rv.studied)}), no full review yet"; else -> "Rules only: not studied by Narrativ.ai" }, 13.sp, C.dim)
            } else {
                val oks = audit.checks.map { (it["ok"] as? JsonPrimitive)?.content == "true" }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    audit.verdict?.let { StatusChip(reviewWord(it), color = reviewColor(it)) }
                    if (oks.isNotEmpty()) Meter(oks.size, oks.count { it }, colors = oks.map { if (it) TierC.lightGreen else TierC.lightRed }, style = MeterStyle.Dot)
                }
                val di = r.dataIssues.size
                T("${oks.count { it }} of ${oks.size} checks match the filing · $di data issue${if (di == 1) "" else "s"}", 12.sp, C.dim,
                    modifier = Modifier.padding(top = 6.dp))
                var shown by remember { mutableStateOf(false) }
                ToggleRow("What was checked", "${audit.checks.size} items", shown, { shown = !shown }, Modifier.padding(top = 6.dp))
                if (shown) {
                    audit.summary?.let { T(it, 12.sp, C.muted, lineHeight = 17.sp, modifier = Modifier.padding(bottom = 6.dp)) }
                    audit.checks.forEach { c ->
                        fun f(k: String) = (c[k] as? JsonPrimitive)?.content
                        val ok = f("ok") == "true"
                        Row(Modifier.fillMaxWidth().clickable(enabled = f("source") != null) { f("source")?.let { openUrl(ctx, it) } }.padding(vertical = 5.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            StatusChip(if (ok) "Pass" else "Miss")
                            Column(Modifier.weight(1f)) { T(f("item") ?: "", 13.sp, weight = FontWeight.Medium); f("found")?.let { T(it, 11.sp, C.dim, lineHeight = 15.sp) } }
                        }
                    }
                }
            }
        }
        val flags = det?.auditFlags.orEmpty()
        SheetSection("Automatic consistency flags", "${flags.size}") {
            if (flags.isEmpty()) T("None raised", 12.sp, C.dim) else flags.forEach { T("• $it", 12.sp, C.amber, lineHeight = 17.sp) }
        }
        p?.let { pk ->
            SheetSection("Overall score", "${fmt(pk.pr, 0)}/100") {
                ProgressLine((pk.pr / 100).toFloat())
                var how by remember { mutableStateOf(false) }
                ToggleRow("Formula", "", how, { how = !how }, Modifier.padding(top = 6.dp))
                if (how) T("Overall score (0–100) = 35% business quality + 25% management + 22% valuation + 18% momentum, each level's 0–100 score. " +
                    "A level without enough data counts as 50 (quality, momentum) or 40 (management, valuation). +5 to +10 when few institutions or analysts cover it, " +
                    "−10 when crowded, −15 when the price is extended. It ranks stocks in lists and the research queue; it is not a buy signal.",
                    12.sp, C.dim, lineHeight = 17.sp)
            }
        }
        val vl = det?.verdictLog.orEmpty()
        val stmt = det?.statement?.ifBlank { null } ?: p?.out?.takeIf { it.l in 1..7 }?.let { "Removed at L${it.l} ${LEVEL_TITLES[it.l - 1]}: ${it.w}." }
        if (vl.isNotEmpty() || stmt != null || r?.thesis != null) SheetSection("Rating history", if (vl.size > 1) "${vl.size - 1} changes" else null) {
            val dates = vl.mapNotNull { e -> skDate(e.d)?.let { it to e.v } }
            if (dates.isNotEmpty()) {
                val start = dates.minOf { it.first }; val end = maxOf(skToday(), start.plusDays(1))
                val labelDates = (dates.map { it.first }.distinct().sorted().filterIndexed { i, _ -> i % 2 == 0 } + end).distinct()
                DotStrip(dates.map { StripDot(it.first, verdictColor(it.second)) }, start, end, Modifier.fillMaxWidth().height(40.dp), stack = false,
                    labels = labelDates.map { it to skDay(it.toString()) }, ring = C.sheet)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    dates.map { it.second }.distinct().forEach { DotChip(it, verdictColor(it)) }
                }
            }
            var more by remember { mutableStateOf(false) }
            ToggleRow("Rule statement and Narrativ.ai's thesis", r?.updated?.let { skDay(it) } ?: "", more, { more = !more }, Modifier.padding(top = 8.dp))
            if (more) {
                stmt?.let { T(it, 13.sp, lineHeight = 19.sp) }
                r?.thesis?.let {
                    T("Narrativ.ai's thesis" + (r.updated?.let { u -> " · ${skDay(u)}" } ?: ""), LABEL, C.dim, modifier = Modifier.padding(top = 10.dp))
                    T(it, 13.sp, lineHeight = 19.sp)
                }
                vl.takeIf { it.size > 1 }?.last()?.let { v -> T("Changed ${skDay(v.d)}: " + (v.from?.let { "$it → " } ?: "") + "${v.v} (${v.cause})", 11.sp, C.amber, modifier = Modifier.padding(top = 8.dp)) }
                det?.stock?.events?.firstOrNull { it.sev == "red" && (skDate(it.date)?.let { d -> !d.isBefore(skToday().minusDays(45)) } ?: false) }?.let { e ->
                    T("${e.type} filed ${skDay(e.date)}: ${e.text.take(120)}", 12.sp, TierC.red, modifier = Modifier.padding(top = 8.dp))
                }
                T("Rule-built from filed numbers and quote-checked research; no AI-typed scores or targets. A decision aid, not advice.", 11.sp, C.dim,
                    modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}

/** "+18.6%" / "−4.2%": the target against a price (feedback #141); null without a price. */
internal fun upside(target: Double, price: Double?): String? = price?.takeIf { it > 0 }?.let { pr ->
    val u = (target / pr - 1) * 100
    (if (u >= 0) "+" else "−") + fmt(kotlin.math.abs(u), 1) + "%"
}

// ---------------------------------------------------------------- Why sheet, Paper (owner, 27 Nov 2026: boards o-A-Verdict + o-A2-Rest)
/** A small section head on the Paper Why sheet: the name in caps, an optional coloured tag beside it. */
@Composable
private fun WhyHead(text: String, tag: String? = null, tagColor: Color = C.grey) {
    Row(Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        PaperLabel(text, C.dim, 10.sp)
        tag?.let {
            Text(it.uppercase(), fontSize = 9.5.sp, letterSpacing = 0.6.sp, color = C.card, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold,
                maxLines = 1, modifier = Modifier.clip(rr(3.dp)).background(tagColor).padding(horizontal = 7.dp, vertical = 1.dp))
        }
    }
}

/** One line of the Why sheet: a coloured mark, a bold title and its evidence. */
@Composable
private fun WhyLine(mark: String, markColor: Color, title: String?, text: String?, onClick: (() -> Unit)? = null, markWidth: androidx.compose.ui.unit.Dp = 18.dp) {
    Row(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(vertical = 5.dp),
        verticalAlignment = Alignment.Top) {
        T(mark, 13.sp, markColor, FontWeight.Bold, maxLines = 1, modifier = Modifier.width(markWidth))
        Text(buildAnnotatedString {
            title?.takeIf { it.isNotBlank() }?.let { withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(it.trimEnd('.') + if (text.isNullOrBlank()) "" else ". ") } }
            text?.takeIf { it.isNotBlank() }?.let { append(it) }
        }, color = C.white, fontSize = 12.5.sp, lineHeight = 17.sp, fontFamily = PaperFonts.serif, modifier = Modifier.weight(1f))
    }
    HLineDivider()
}

/** A question card in the key-check card style: verdict band, the question, the answer large, one or two lines. */
@Composable
private fun QuestionCard(band: String, color: Color, question: String, answer: String, lines: List<String>, modifier: Modifier) {
    val shape = RoundedCornerShape(6.dp)
    Column(modifier.clip(shape).background(C.card).border(1.dp, C.line, shape)) {
        Text(band, fontSize = 9.5.sp, letterSpacing = 0.7.sp, color = C.card, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, maxLines = 1,
            modifier = Modifier.fillMaxWidth().background(color).padding(horizontal = 8.dp, vertical = 4.dp))
        Column(Modifier.padding(start = 8.dp, end = 8.dp, top = 7.dp, bottom = 9.dp)) {
            T(question, 11.sp, C.dim, maxLines = 1)
            Text(answer, fontSize = 17.sp, lineHeight = 20.sp, color = C.white, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 2,
                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp, bottom = 4.dp))
            lines.forEach { T(it, 10.5.sp, maxLines = 3, lineHeight = 14.sp) }
        }
    }
}

/** ✓ / ~ / ✗ and the band colour for a level tier (1-2 good, 3 middle, 4-5 weak, 0 not known). */
private fun tierMark(t: Int): Pair<String, Color> = when {
    t in 1..2 -> "✓" to fillColor("Pass"); t == 3 -> "~" to fillColor("Partly"); t >= 4 -> "✗" to fillColor("Miss"); else -> "–" to C.grey
}

@Composable
private fun PaperWhyBody(st: AppState, sym: String, p: P?, det: Detail?, dd: Decision?) {
    val ctx = LocalContext.current
    val r = st.research[sym]
    val audit = r?.audit
    val dn = dd?.d ?: "Not rated"
    val cv = det?.conviction
    // 1 · one box cut in half (feedback #196, owner 27 Nov 2026): the decision on the left in its colour, conviction on the
    // right in its level colour (High green, Medium amber, Low red) with the score out of 100; each half has its own label
    @Composable
    fun Half(lbl: String, bg: Color, m: Modifier, body: @Composable RowScope.() -> Unit) =
        Column(m.background(bg).padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(lbl, fontSize = 9.5.sp, letterSpacing = 1.sp, color = C.card.copy(alpha = 0.9f), fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, maxLines = 1)
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp), content = body)
        }
    Row(Modifier.fillMaxWidth().clip(rr(6.dp)).height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        Half("DECISION", decisionColor(dn), Modifier.weight(1f).fillMaxHeight()) {
            Text(dn, fontSize = 30.sp, color = C.card, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1)
        }
        cv?.level?.let { lvl ->
            val cc = when (lvl) { "High" -> TierC.darkGreen; "Low" -> TierC.red; else -> C.amber }
            Half("CONVICTION", cc, Modifier.weight(1f).fillMaxHeight()) {
                Text(lvl, fontSize = 30.sp, color = C.card, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1)
                cv?.score?.let {
                    Text(buildAnnotatedString { append("$it"); withStyle(SpanStyle(fontSize = 12.sp)) { append("/100") } }, fontSize = 20.sp, color = C.card,
                        fontFamily = PaperFonts.headline, fontWeight = FontWeight.Bold, maxLines = 1, modifier = Modifier.padding(bottom = 4.dp))
                }
            }
        }
    }
    // 2 · three questions as cards
    val lv = det?.levels.orEmpty()
    fun tierOf(i: Int): Int = lv[LEVELS[i]]?.t ?: p?.tier(i) ?: 0
    fun nameOf(i: Int): String = lv[LEVELS[i]]?.name?.ifBlank { null } ?: p?.levelTierName(st, i) ?: "–"
    Row(Modifier.fillMaxWidth().padding(top = 10.dp).height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        // business: the worse of stability and quality
        val bt = listOf(tierOf(0), tierOf(1)).filter { it > 0 }.maxOrNull() ?: 0
        val (bm, bc) = tierMark(bt)
        QuestionCard("$bm BUSINESS", bc, "Good business?", when { bt == 0 -> "Not known"; bt <= 2 -> "Yes"; bt == 3 -> "Mixed"; else -> "No" },
            listOf("Stability ${nameOf(0)}", "Quality ${nameOf(1)}"), Modifier.weight(1f).fillMaxHeight())
        // price: the valuation multiple, then the verdict and the peer comparison (V2), else the own-history line (V1)
        val v = lv["val"]
        val vt = tierOf(2)
        val (vm, vc) = tierMark(vt)
        val vans = if (v?.mval != null && v.metric != null) "${mult(v.mval)} ${if (v.metric == "P/B") "book" else v.metric}" else nameOf(2)  // owner: "0.9× book"
        val vline = (v?.item("V2")?.v ?: v?.item("V1")?.v)?.takeIf { it.isNotBlank() }
        QuestionCard("$vm PRICE", vc, "Price right?", vans, listOfNotNull(nameOf(2), vline), Modifier.weight(1f).fillMaxHeight())
        // timing: the entry setup and momentum
        val s = det?.setup
        val live = s != null && s.lo != null && s.type in setOf("Breakout", "Pullback", "Base")
        val tc = if (live) fillColor("Pass") else fillColor("Partly")
        val buy = if (live && s != null) { if (s.type == "Breakout") "buy above ${skRs(s.lo!!)}" else if (s.hi != null) "buy ${rangeStr(s.lo!!, s.hi)}" else null } else null
        QuestionCard("${if (live) "✓" else "~"} TIMING", tc, "Now the time?", s?.let { planName(it) } ?: "No setup",
            listOfNotNull("Momentum ${nameOf(4)}" + (buy?.let { "; $it" } ?: "")), Modifier.weight(1f).fillMaxHeight())
    }
    // 3 · conviction signals (no points), what is not there yet, what a verified Buy still needs
    if (cv != null && (cv.proofs.isNotEmpty() || cv.notYet.isNotEmpty())) {
        WhyHead("Conviction signals", cv.date?.let { skDay(it) }, C.grey)
        // the points that make the score; what is missing shows as 0 (feedback #196)
        cv.proofs.forEach { pr -> WhyLine(if (pr.pts > 0) "+${pr.pts}" else "✓", fillColor("Pass"), pr.t, pr.v, markWidth = 30.dp) }
        if (cv.notYet.isNotEmpty()) WhyHead("Not yet")
        cv.notYet.forEach { WhyLine(if (cv.proofs.any { it.pts > 0 }) "0" else "–", C.dim, null, it, markWidth = 30.dp) }
    }
    val missing = dd?.missing.orEmpty()
    if (missing.isNotEmpty()) {
        WhyHead("Not a verified Buy yet")
        missing.forEach { WhyLine("–", C.amber, null, it) }
    }
    // 4 · management: the level word as a tag, then what management said (quoted guidance)
    val why = dd?.why.orEmpty()
    val fwd = why.filter { isMgmtLine(it) }
    val mt = tierOf(3)
    if (fwd.isNotEmpty() || mt > 0) {
        WhyHead("Management", "${tierMark(mt).first} ${nameOf(3)}", tierColor(mt))
        fwd.forEach { w ->
            Row(Modifier.padding(vertical = 3.dp)) {  // label and text on one baseline (feedback #197)
                if (w.contains(": ")) {
                    T(w.substringBefore(": ").substringBefore(" ("), 10.5.sp, C.dim, maxLines = 2, modifier = Modifier.width(72.dp).alignByBaseline())
                    T(w.substringAfter(": "), 12.5.sp, lineHeight = 17.sp, modifier = Modifier.weight(1f).alignByBaseline())
                } else T(w, 12.5.sp, lineHeight = 17.sp, modifier = Modifier.weight(1f))
            }
        }
    }
    // 5 · Narrativ.ai's check: verdict and date as a tag, up to 3 checks, the rest behind a toggle
    if (audit == null) {
        WhyHead("Checked by Narrativ.ai")
        val rv = reviewState(st, sym)
        T(when { rv.verdict != null -> "Narrativ.ai's review: ${reviewWord(rv.verdict)}"; rv.pos > 0 -> queueLabel(st, sym) ?: "In Narrativ.ai's review queue"; rv.pos != 0 -> "In Narrativ.ai's research queue"
                 rv.studied != null -> "Narrativ.ai's notes only (${skDay(rv.studied)}), no full review yet"; else -> "Rules only: not studied by Narrativ.ai" }, 12.5.sp, C.dim)
    } else {
        val ok = audit.verdict == "pass"
        WhyHead("Checked by Narrativ.ai", listOfNotNull((if (ok) "✓ " else if (audit.verdict == "fail") "✗ " else "~ ") + reviewWord(audit.verdict),
            audit.date?.let { skDay(it) }).joinToString(" · "), reviewColor(audit.verdict))
        var all by remember { mutableStateOf(false) }
        val checks = audit.checks
        (if (all) checks else checks.take(3)).forEach { c ->
            fun f(k: String) = (c[k] as? JsonPrimitive)?.content
            val good = f("ok") == "true"
            WhyLine(if (good) "✓" else "✗", fillColor(if (good) "Pass" else "Miss"), f("item"), f("found"),
                f("source")?.let { src -> { openUrl(ctx, src) } })
        }
        if (checks.size > 3) T(if (all) "Show fewer" else "All ${checks.size} checks ›", 12.sp, C.blue, maxLines = 1,
            modifier = Modifier.padding(top = 4.dp).clickable { all = !all })
    }
    // 6 · what to watch: the stock's watch standouts, then other rule notes
    val watch = det?.standouts?.watch.orEmpty()
    val levelNames = LEVEL_SHORT.toSet()
    val other = why.filter { it.substringBefore(":") !in levelNames && !isMgmtLine(it) && !it.startsWith("Verified") &&
        !it.startsWith("R1 and R2 not applied") && !it.startsWith("Re-scored") && !it.contains("valuation", ignoreCase = true) &&
        !it.contains("base case") && (cv?.proofs.isNullOrEmpty() || (!it.startsWith("Signal") && !it.startsWith("No entry setup") && !it.startsWith("Entry setup"))) }
    if (watch.isNotEmpty() || other.isNotEmpty()) {
        WhyHead("What to watch")
        watch.forEach { WhyLine("~", C.amber, it.n, it.v) }
        other.forEach { WhyLine("~", C.amber, null, it) }
    }
    // 7 · rating history: rating changes and this stock's calls, latest first; two shown, the rest behind a toggle
    val cf by produceState(st.repo.peek<CallsFile>("data/calls.json")) { st.repo.cacheFirst<CallsFile>("data/calls.json") { if (it != null) value = it } }
    val events = buildList {
        det?.verdictLog.orEmpty().forEach { e ->
            add(Triple(e.d, verdictColor(e.v), (e.from?.let { "$it → " } ?: "") + e.v + (if (e.from == null) " (first rating)" else e.cause?.let { " ($it)" } ?: "")))
        }
        cf?.calls.orEmpty().filter { it.symbol == sym }.forEach { c ->
            val what = (if (c.kind == "verified") "Verified ${c.decision ?: "Buy"} call" else "${c.decision ?: "Buy"}-candidate call") +
                (c.price?.let { " at ${skRs(it)}" } ?: "") +
                (c.ended?.let { e -> ", ended ${skDay(e)}" + (c.toEnd?.let { " (${if (it >= 0) "+" else "−"}${fmt(kotlin.math.abs(it), 1)}%)" } ?: "") } ?: "")
            add(Triple(c.date, if (c.ended == null) fillColor("Pass") else C.amber, what))
        }
    }.sortedByDescending { it.first }
    if (events.isNotEmpty()) {
        WhyHead("Rating history")
        var more by remember { mutableStateOf(false) }
        (if (more) events else events.take(2)).forEach { (d, c, t) -> WhyLine("●", c, skDay(d), t) }
        if (events.size > 2) T(if (more) "Show fewer" else "Show ${events.size - 2} earlier ›", 12.sp, C.blue, maxLines = 1,
            modifier = Modifier.padding(top = 4.dp).clickable { more = !more })
    }
}
