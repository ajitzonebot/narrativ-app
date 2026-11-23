@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.RocketLaunch
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
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
    "rev_cagr_3y_pct" to "Revenue growth a year (span in formula)", "roce_3y_avg_pct" to "ROCE, average of filed years", "net_debt_ebitda" to "Net debt / EBITDA",
    "current_ratio" to "Current ratio", "cfo_negative_years" to "Years of negative operating cash", "loss_quarters_4" to "Loss quarters (last 4)",
    "dilution_3y_pct" to "Share dilution, 3 years", "debt_chg_yoy_pct" to "Borrowings change, 1 year", "ev_sales" to "EV / sales",
    "ev_midcycle_ebitda" to "EV / mid-cycle EBITDA", "margin_chg_3y_pts" to "EBITDA margin change over filed years (pts)",
    "ebitda_margin_prev_pct" to "EBITDA margin a year ago", "margin_range_12q_pts" to "Margin range, 12 quarters (pts)",
    "investments_pct_assets" to "Investments % of assets", "roa_pct" to "ROA", "equity_cr" to "Shareholders' equity",
    "rev_yoy_prev_pct" to "Revenue YoY (previous quarter)", "rev_ttm_growth_prev_pct" to "Revenue growth a year ago (4 quarters)",
    "ebitda_margin_q_yago_pct" to "Quarter EBITDA margin a year ago",
)

@Composable
fun SectionHeader2(t: String, sub: String) = Column(Modifier.padding(top = 20.dp, bottom = 8.dp)) { T(t, 18.sp, weight = FontWeight.SemiBold); T(sub, 12.sp, C.grey) }

@Composable
fun MarkBox(m: Mark, onClick: () -> Unit) {
    val (sym, fg, bg) = when (m.mark) {
        "y" -> Triple("✓", C.teal, C.teal.copy(alpha = 0.18f)); "p" -> Triple("~", C.blue, C.blue.copy(alpha = 0.15f))
        "n" -> Triple("✗", C.red, C.red.copy(alpha = 0.15f)); else -> Triple("–", C.dim, C.chip)
    }
    Box(Modifier.size(19.dp).clip(RoundedCornerShape(5.dp)).background(bg).clickable(onClick = onClick), contentAlignment = Alignment.Center) { T(sym, 11.sp, fg, FontWeight.Bold) }
}

@Composable
fun WatchRow(n: String, w: Watch, col: Color, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 6.dp)) {
        Box(Modifier.size(24.dp).clip(CircleShape).background(col.copy(alpha = 0.15f)), contentAlignment = Alignment.Center) { T(n, 12.sp, col, FontWeight.Bold) }
        Spacer(Modifier.width(12.dp))
        Column { T(w.text, 14.sp, weight = FontWeight.SemiBold); T(w.check + (w.due?.let { " · due $it" } ?: ""), 12.sp, C.grey) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FormulaSheet(name: String, m: Metric, onClose: () -> Unit) {
    val ctx = LocalContext.current
    ModalBottomSheet(onDismissRequest = onClose, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = C.card) {
        Column(Modifier.padding(horizontal = 18.dp).padding(bottom = 28.dp).verticalScroll(rememberScrollState())) {
            T(name, 20.sp, weight = FontWeight.Bold)
            T((if (m.nm) "n/m (outside the meaningful range) · " else "") + fmt(m.v, 2) + (m.u?.let { " $it" } ?: ""), 28.sp, C.teal, FontWeight.Bold)
            T("Formula", 13.sp, C.grey, FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp)); T(m.f, 14.sp, lineHeight = 19.sp)
            if (m.inputs.isNotEmpty()) {
                T("Inputs", 13.sp, C.grey, FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp))
                m.inputs.forEach { (k, v) -> KV(inputLabel(k), inputValue(k, v.content)) }
            }
            T("Source", 13.sp, C.grey, FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp)); T(m.src, 13.sp, C.grey)
            m.url?.let { u -> T("Open the filing", 14.sp, C.blue, FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp).clickable { openUrl(ctx, u) }) }
        }
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
        k.endsWith("_pct") -> "${fmt(x, 1)}%"
        k == "price" -> "₹${fmt(x, 2)}"
        k.startsWith("shares") -> "%,.0f".format(x)
        k in setOf("quarters", "years") -> fmt(x, 0)
        else -> fmt(x, 2)
    }
}

fun pct1(v: Double?) = v?.let { "${fmt(it, 1)}%" } ?: "–"
fun pct0(v: Double?) = v?.let { "${fmt(it, 0)}%" } ?: "–"


// ---------------------------------------------------------------- research blocks (Outlook tab)
@Composable
fun ScenariosCard(scan: Scan) {
    SectionHeader2("Bull · Base · Bear", "Price from quoted guidance × own P/E band. A scenario, not a target")
    Card(Modifier.fillMaxWidth()) {
        scan.scenarios.forEach { s ->
            val col = when (s.name.lowercase()) { "bull" -> C.teal; "bear" -> C.red; else -> C.blue }
            Row(Modifier.padding(vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(C.card2).height(IntrinsicSize.Min)) {
                Box(Modifier.width(3.dp).fillMaxHeight().background(col))
                Column(Modifier.padding(10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        T(s.name, 14.sp, col, FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        T("₹${fmt(s.price, 0)} ", 16.sp, weight = FontWeight.SemiBold); T(pctStr(s.pct), 12.sp, col)
                    }
                    if (s.theory.isNotBlank()) T(s.theory, 13.sp, Color(0xFFDFE3E6), lineHeight = 17.sp)
                    T(s.formula, 12.sp, C.grey, lineHeight = 16.sp); T(s.src, 11.sp, C.dim)
                }
            }
        }
        scan.settles?.let { T("Settles at $it", 11.sp, C.dim, modifier = Modifier.padding(top = 6.dp)) }
    }
}

@Composable
fun ResearchLists(scan: Scan) {
    val ctx = LocalContext.current
    if (scan.mustGoRight.isNotEmpty()) {
        SectionHeader2("Must go right", "Each one is a checkpoint with a date")
        Card(Modifier.fillMaxWidth()) { scan.mustGoRight.forEachIndexed { i, w -> WatchRow("${i + 1}", w, C.teal) { w.source.takeIf { it.isNotBlank() }?.let { openUrl(ctx, it) } } } }
    }
    if (scan.killSwitches.isNotEmpty()) {
        SectionHeader2("Kill switches", "Thesis breaks if any of these happen")
        Card(Modifier.fillMaxWidth()) { scan.killSwitches.forEach { w -> WatchRow("✗", w, C.red) { w.source.takeIf { it.isNotBlank() }?.let { openUrl(ctx, it) } } } }
    }
    if (scan.checklist.isNotEmpty()) {
        var mark by remember { mutableStateOf<Mark?>(null) }
        SectionHeader2("Research checklist", "multibagger-scan rubric · tap a mark for its quote")
        Card(Modifier.fillMaxWidth()) {
            listOf("fundamentals", "valuation", "management", "outlook", "flow").forEach { lens ->
                val ms = scan.checklist[lens].orEmpty()
                if (ms.isNotEmpty()) Row(Modifier.padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                    T(lens.replaceFirstChar { it.uppercase() }, 13.sp, C.grey, modifier = Modifier.width(96.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) { ms.forEach { m -> MarkBox(m) { mark = m } } }
                }
            }
            mark?.let { m ->
                Column(Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(C.card2).padding(10.dp)) {
                    T("${m.id} ${m.name}", 13.sp, weight = FontWeight.SemiBold); if (m.note.isNotBlank()) T(m.note, 12.sp, C.grey)
                    if (m.quote.isNotBlank()) Quote(ctx, m.quote, m.source)
                }
            }
        }
    }
    if (scan.derived.isNotEmpty()) {
        SectionHeader2("Derived from research", "Quoted figure ÷ filed figure")
        Card(Modifier.fillMaxWidth()) {
            scan.derived.forEach { d ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Column(Modifier.weight(1f)) { T(d.name, 14.sp, weight = FontWeight.Medium); T(d.formula + " · " + d.src, 11.sp, C.dim, maxLines = 3) }
                    T(d.value, 15.sp, if (d.good == true) C.teal else C.white, FontWeight.SemiBold)
                }
            }
        }
    }
}

// ================================================================ Summary tab (redesign s01) and the decision sheet (s02)
private val LENDERS = setOf("bank", "nbfc", "insurance")
private val FORWARD_KEYS = setOf("Capacity", "Order", "Guidance", "Driver", "Product", "Demand")
/** Plain setup names (mockup kit SETUP). */
fun planName(s: Setup): String = when (s.type) {
    "Breakout" -> "Breaking out"; "Pullback" -> "Dip in uptrend"; "Base" -> "Near entry"
    "No setup" -> if (s.note?.startsWith("No entry: trend broken") == true) "Avoid" else "Wait"
    else -> "No data"
}

@Composable
fun SummaryTab(st: AppState, sym: String, p: P?, det: Detail?, chart: Chart?, openTab: (Int) -> Unit) {
    var formula by remember { mutableStateOf<Pair<String, Metric>?>(null) }
    val open: (String?) -> Unit = { k -> k?.let { key -> det?.m(key)?.let { formula = (METRIC_NAMES[key] ?: key) to it } } }
    var sheet by rememberSaveable { mutableStateOf("") }  // "decision", "research", "ratios"
    DecisionCard(st, sym, p, det) { sheet = "decision" }
    RotationCard(st, p, det)
    PriceCard(p, det, chart)
    det?.let { PlanCard(it.setup) }
    det?.let { KeyTiles(it, open) }
    WatchCard(st, sym, p, det)
    Card(Modifier.fillMaxWidth(), pad = 14.dp) {
        val log = det?.researchLog.orEmpty()
        LinkRow("Claude's research", if (log.isEmpty()) "not studied yet" else "${log.size} entr${if (log.size == 1) "y" else "ies"} · last ${skDay(log.maxOf { it.date })}") { sheet = "research" }
        if (det != null) LinkRow("All ratios and formulas", divider = true) { sheet = "ratios" }
    }
    when (sheet) {
        "decision" -> DecisionDetailsSheet(st, sym, p, det) { sheet = "" }
        "research" -> ResearchSheet(st, sym, det) { sheet = "" }
        "ratios" -> det?.let { RatiosSheet(it, { sheet = "" }, open) }
    }
    formula?.let { (n, m) -> FormulaSheet(n, m) { formula = null } }
}

// ---------------------------------------------------------------- decision card
@Composable
private fun DecisionCard(st: AppState, sym: String, p: P?, det: Detail?, onOpen: () -> Unit) {
    val dd = det?.decision ?: p?.dc?.let { Decision(it) }
    val d = dd?.d ?: "Not rated"
    val dcol = decisionColor(d)
    val rv = reviewState(st, sym)
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(S.card)).background(C.card)
        .background(Brush.linearGradient(listOf(dcol.copy(alpha = 0.16f), Color.Transparent))).clickable(onClick = onOpen).padding(16.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            T(d.uppercase(), if (d.length <= 6) 40.sp else 26.sp, dcol, FontWeight.ExtraBold, maxLines = 1, lineHeight = 44.sp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f).padding(top = 4.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                when {
                    rv.verdict == "pass" -> Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.Check, null, tint = TierC.lightGreen, modifier = Modifier.size(15.dp)); Spacer(Modifier.width(4.dp))
                        T("Claude verified" + (rv.date?.let { " ${skDay(it)}" } ?: ""), 13.sp, TierC.lightGreen, maxLines = 1)
                    }
                    rv.verdict != null -> T("Claude's review: ${rv.verdict}" + (rv.date?.let { " · ${skDay(it)}" } ?: ""), 13.sp, reviewColor(rv.verdict), maxLines = 1)
                    rv.pos > 0 -> T("Queued #${rv.pos} for Claude's full review", 13.sp, C.dim, maxLines = 2)
                    rv.pos != 0 -> T("In Claude's research queue", 13.sp, C.dim, maxLines = 1)
                    rv.studied != null -> T("Claude's notes only, no full review yet", 13.sp, C.dim, maxLines = 2)
                    else -> T("Rules only: not studied by Claude", 13.sp, C.dim, maxLines = 2)
                }
                val cv = det?.conviction?.takeIf { it.level != null }
                val level = cv?.level ?: p?.cv
                if (level != null) {
                    Row(verticalAlignment = Alignment.CenterVertically) { T("Conviction ", 13.sp, C.dim, maxLines = 1); T(level, 13.sp, weight = FontWeight.SemiBold, maxLines = 1) }
                    if (cv?.met != null && cv.of != null && cv.of > 0) Meter(cv.of, cv.met, color = TierC.lightGreen, style = MeterStyle.Dot)
                }
                st.picks?.top10?.indexOf(sym)?.takeIf { it >= 0 }?.let { T("#${it + 1} in Top 10", 13.sp, C.dim, maxLines = 1) }
            }
        }
        val why = dd?.why.orEmpty()
        val missing = dd?.missing.orEmpty()
        val fwd = why.filter { it.substringBefore(":") in FORWARD_KEYS }.map { it.substringAfter(": ") }.take(2)
        val lv = det?.levels
        fun tierWord(k: String, pre: String) = lv?.get(k)?.takeIf { it.t != 0 }?.name?.let { if (pre.isEmpty()) it else "$pre ${it.lowercase()}" }
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
    Card(Modifier.fillMaxWidth(), pad = 12.dp) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            RotationMap(listOfNotNull(sec?.let { RotPoint(it.ratio, it.mom, it.q, "S") }, ir?.let { RotPoint(it.ratio, it.mom, it.q, "I") }),
                Modifier.size(128.dp, 104.dp), mini = true)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                sec?.let { RotBlock("S", it.ticker ?: "Nifty $secKey", it) }
                ir?.let { RotBlock("I", "Industry", it) }
            }
        }
    }
}

@Composable
private fun RotBlock(letter: String, name: String, r: Rot) {
    val qc = QUAD_MINI[r.q] ?: C.dim
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(buildAnnotatedString {
            withStyle(SpanStyle(color = qc)) { append(letter) }; append(" · $name · "); withStyle(SpanStyle(color = qc)) { append(r.q.ifBlank { "–" }) }
        }, color = C.white, fontSize = 13.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            r.r1m?.let { ValChip("1M ${skSgn(it)}", gainColor(it)) }
            r.r3m?.let { ValChip("3M ${skSgn(it)}", gainColor(it)) }
        }
    }
}

// ---------------------------------------------------------------- price chart with the plan levels
private val RANGES = listOf("1M" to 22, "3M" to 65, "6M" to 130, "1Y" to 260)

@Composable
private fun PriceCard(p: P?, det: Detail?, chart: Chart?) {
    var range by rememberSaveable { mutableIntStateOf(3) }
    val all = chart?.c.orEmpty()
    val s = det?.setup
    Card(Modifier.fillMaxWidth(), pad = 12.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SegmentedControl(RANGES.map { it.first }, range, { range = it }, compact = true)
            Spacer(Modifier.weight(1f))
            val lo = det?.stock?.lo52; val hi = det?.stock?.hi52
            if (lo != null && hi != null) T("52w ${skRs(lo)}–${fmt(hi, 0)}", 12.sp, C.dim, maxLines = 1)
        }
        if (all.size < 2) { T("Chart is published for stocks in the funnel.", 12.sp, C.dim, modifier = Modifier.padding(8.dp)); return@Card }
        val n = RANGES[range].second
        val vals = all.takeLast(n)
        val col = if (vals.last() >= vals.first()) TierC.lightGreen else TierC.lightRed
        val bands = mutableListOf<HBand>(); val lines = mutableListOf<HLine>()
        if (s?.lo != null && s.hi != null) bands += HBand(s.lo, s.hi, TierC.darkGreen, "Buy zone ${skRs(s.lo)}–${fmt(s.hi, 0)}")
        else if (s?.watchLo != null && s.watchHi != null) bands += HBand(s.watchLo, s.watchHi, C.teal, "Buy on a dip ${skRs(s.watchLo)}–${fmt(s.watchHi, 0)}")
        s?.add?.let { lines += HLine(it, C.blue, "Buy rest above ${skRs(it)}") }
        if (s?.add == null && s?.watchLo != null) s.sma50?.let { lines += HLine(it, C.amber, "50-day ${skRs(it)}") }
        s?.stop?.let { lines += HLine(it, TierC.lightRed, "Exit ${skRs(it)}", labelBelow = true) }
        val months = mapOf(22 to 1L, 65 to 3L, 130 to 6L, 260 to 12L)[n] ?: 12L
        val start = if (n >= all.size && chart?.d0 != null) skDate(chart.d0) else skToday().minusMonths(months)
        val startLabel = start?.let { if (months <= 3) skDay(it.toString()) else shortMonth(it.toString()) } ?: ""
        AreaLine(vals, Modifier.fillMaxWidth().height(190.dp).padding(top = 10.dp), color = col, fillAlpha = 0.22f, strokeWidth = 1.8.dp,
            bands = bands, lines = lines, hollowEnd = true, xLabels = listOf(startLabel, "Now ${skRs(p?.p ?: vals.last())}"))
    }
}

// ---------------------------------------------------------------- plan
@Composable
private fun PlanCard(s: Setup) {
    Card(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            T("Plan", 17.sp, weight = FontWeight.Bold); Spacer(Modifier.width(8.dp))
            val nm = planName(s)
            StatusChip(nm, color = when (nm) { "Avoid" -> TierC.lightRed; "No data", "Wait" -> C.dim; else -> C.blue }, minWidth = 0.dp)
        }
        val rows = buildList {
            if (s.lo != null && s.hi != null) add(Triple(if (s.type == "Breakout") "Buy on a close above" else "Buy between",
                if (s.type == "Breakout") skRs(s.lo) else "${skRs(s.lo)} – ${skRs(s.hi)}", C.white))
            else if (s.watchLo != null && s.watchHi != null) add(Triple("Buy on a dip to", "${skRs(s.watchLo)} – ${skRs(s.watchHi)}", C.white))
            s.add?.let { add(Triple("Buy rest above", skRs(it), C.white)) }
            if (s.add == null && s.watchLo != null) s.sma50?.let { add(Triple("Weakens below (50-day)", skRs(it), C.amber)) }
            s.stop?.let { add(Triple("Exit if it closes below", skRs(it), TierC.lightRed)) }
            when {
                s.rrNote == "Above analyst target" -> add(Triple("Upside vs risk", "above target", C.amber))
                s.rr != null -> add(Triple("Upside vs risk", "${skFx(s.rr, 1)}×", C.white))
            }
        }
        if (rows.isEmpty()) T(s.note ?: "No buy zone today.", 13.sp, C.dim)
        rows.forEachIndexed { i, (k, v, c) -> KvRow(k, v, valueColor = c, divider = i < rows.lastIndex) }
    }
}

// ---------------------------------------------------------------- four key numbers with small visuals
@Composable
private fun RowScope.KeyTile(label: String, value: String, onClick: () -> Unit, content: (@Composable ColumnScope.() -> Unit)? = null) =
    StatTile(label, value, Modifier.weight(1f).heightIn(min = 86.dp), onClick = onClick, content = content)

@Composable
private fun KeyTiles(det: Detail, open: (String?) -> Unit) {
    val lender = det.stock.kind in LENDERS
    val vl = det.levels["val"]
    val vkey = vl?.mkey ?: METRIC_KEY_OF[vl?.metric] ?: if (lender) "pb" else "pe"
    val hist = det.hist.mapNotNull { it[vkey]?.content?.toDoubleOrNull() }
    val vnow = vl?.mval ?: det.v(vkey)
    val qual = det.levels["qual"]
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val metric = vl?.metric ?: METRIC_NAMES[vkey] ?: "P/E"
            KeyTile(if (hist.size >= 2) "$metric · own ${skFx(hist.min(), 1)}–${skFx(hist.max(), 1)}" else metric, skFx(vnow, 1), { open(vkey) }) {
                val c = if (vl?.item("V1")?.m != null) statusColor(vl.status("V1")) else C.blue
                if (hist.size >= 2 && vnow != null) MiniRange(hist.min(), hist.max(), vnow, c)
            }
            if (lender) KeyTile("ROE", det.v("roe_pct")?.let { "${skFx(it, 1)}%" } ?: "–", { open("roe_pct") })
            else {
                val roce = det.roceFy
                KeyTile(if (roce.size >= 2) "ROCE avg · FY${roce.first().first % 100}–${roce.last().first % 100}" else "ROCE avg",
                    det.v("roce_3y_avg_pct")?.let { "${skFx(it, 1)}%" } ?: "–", { open("roce_3y_avg_pct") }) {
                    if (roce.size >= 2) Bars(roce.map { it.second }, Modifier.fillMaxWidth().height(26.dp), color = C.teal, base = roce.minOf { it.second } * 0.85, barFrac = 0.75f)
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val rev = det.quarterly.mapNotNull { it.getOrNull(1) }
            KeyTile(if (rev.size >= 2) "Revenue growth · ${rev.size}Q" else "Revenue growth", det.v("rev_cagr_3y_pct")?.let { "${skFx(it, 1)}%/yr" } ?: "–", { open("rev_cagr_3y_pct") }) {
                if (rev.size >= 2) Sparkline(rev, Modifier.fillMaxWidth().height(26.dp), color = C.teal, area = true, endDot = true)
            }
            if (lender) KeyTile("Gross NPA", det.v("gnpa_pct_advances")?.let { "${skFx(it, 1)}%" } ?: "–", { open("gnpa_pct_advances") })
            else {
                val cc = det.v("cfo_to_ebitda_pct")
                KeyTile("Cash conversion · pass 70%", cc?.let { "${skFx(it, 0)}%" } ?: "–", { open("cfo_to_ebitda_pct") }) {
                    if (cc != null) BulletBar(cc, 0.0, 100.0, 70.0, statusColor(qual?.status("Q7") ?: "n/a"), Modifier.fillMaxWidth().height(12.dp), partly = 50.0)
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
        if (nr != null && nd != null && nd.isAfter(today)) add(TimelineItem(skDay(nr.date), "Results", nr.purpose, C.blue, hollow = true))
        val ks = st.research[sym]?.scan?.killSwitches.orEmpty().filter { skDate(it.due)?.isAfter(today) ?: false }.minByOrNull { it.due ?: "" }
        if (ks != null) add(TimelineItem(skDay(ks.due), ks.text, "Kill switch · check: ${ks.check}", TierC.red))
        else p?.cp?.filter { (it.status == "open" || it.status == "due") && it.due != null && it.type != "results" }?.minByOrNull { it.due!! }?.let { c ->
            add(TimelineItem(skDay(c.due), c.what ?: c.type ?: "", (c.type ?: "").replace('_', ' ').replaceFirstChar { it.uppercase() }, C.blue))
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
    val verified = (dd?.verified ?: p?.vf) == "pass"
    val badge: (@Composable () -> Unit)? = if (verified) ({ StatusChip("Verified", color = TierC.lightGreen) }) else null
    BottomSheet(onDismiss, "Why ${dd?.d ?: "not rated"}", titleExtra = badge) {
        FlowRow(Modifier.padding(bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            val vd = det?.verdict?.ifBlank { null } ?: p?.vd?.ifBlank { null }
            vd?.let { DotChip(it, verdictColor(it)) }
            p?.cp?.filter { (it.status == "open" || it.status == "due") && it.due != null }?.minByOrNull { it.due!! }?.let { c ->
                ValChip("next check ${skDay(c.due)} · ${(c.type ?: "").replace('_', ' ')}")
            }
            if (p?.mb == true) DotChip("Multibagger potential", TierC.yellow)
        }
        val why = dd?.why.orEmpty()
        val levelNames = LEVEL_SHORT.toSet()
        val lvl = why.filter { it.substringBefore(":") in levelNames }
        val valn = why.filter { it !in lvl && it.contains("valuation", ignoreCase = true) }
        val rev = why.filter { it.startsWith("Verified") || it.contains("review", ignoreCase = true) }
        val fwd = why.filter { it !in lvl && it !in valn && it !in rev }
        if (lvl.isNotEmpty()) SheetSection("Levels") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                lvl.forEach { w ->
                    val k = w.substringBefore(":"); val nm = w.substringAfter(": ")
                    val c = tierColor(det?.levels?.get(LEVELS[LEVEL_SHORT.indexOf(k)])?.t ?: 0)
                    Row(Modifier.clip(RoundedCornerShape(9.dp)).background(Color.White.copy(alpha = 0.063f)).padding(horizontal = 10.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Box(Modifier.size(7.dp).clip(CircleShape).background(c)); T(k, 12.sp, C.muted, maxLines = 1); T(nm, 12.sp, c, FontWeight.Bold, maxLines = 1)
                    }
                }
            }
        }
        if (fwd.isNotEmpty()) SheetSection("Forward evidence", "${fwd.size} quoted") {
            fwd.forEach { w ->
                Row(Modifier.padding(vertical = 4.dp)) {
                    Box(Modifier.padding(top = 6.dp).size(6.dp).clip(CircleShape).background(TierC.lightGreen)); Spacer(Modifier.width(8.dp))
                    Text(buildAnnotatedString {
                        if (w.contains(": ")) { withStyle(SpanStyle(color = C.dim)) { append(w.substringBefore(": ")) }; append(" · " + w.substringAfter(": ")) } else append(w)
                    }, color = C.white, fontSize = 13.sp, lineHeight = 18.sp)
                }
            }
        }
        val missing = dd?.missing.orEmpty()
        if (missing.isNotEmpty()) SheetSection("Not a verified Buy yet") {
            missing.forEach { m ->
                Row(Modifier.padding(vertical = 4.dp)) {
                    Box(Modifier.padding(top = 6.dp).size(6.dp).clip(CircleShape).background(C.amber)); Spacer(Modifier.width(8.dp)); T(m, 13.sp, lineHeight = 18.sp)
                }
            }
        }
        val vlv = det?.levels?.get("val")
        if (vlv != null || valn.isNotEmpty()) SheetSection("Valuation") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                vlv?.let { DotChip(it.name, tierColor(it.t)) }
                valn.firstOrNull()?.substringBefore(";")?.let { ValChip(it) }
            }
        }
        // Claude's review
        SheetSection("Review · Claude", audit?.date?.let { skDay(it, true) }) {
            if (audit == null) {
                val rv = reviewState(st, sym)
                T(when { rv.verdict != null -> "Review ${rv.verdict}"; rv.pos > 0 -> "Queued #${rv.pos} of ${rv.of} for a full review"; rv.pos != 0 -> "In Claude's research queue"
                         rv.studied != null -> "Claude's notes only (${skDay(rv.studied)}), no full review yet"; else -> "Rules only: not studied by Claude" }, 13.sp, C.dim)
            } else {
                val oks = audit.checks.map { (it["ok"] as? JsonPrimitive)?.content == "true" }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    audit.verdict?.let { StatusChip(it.uppercase(), color = if (it == "pass") TierC.lightGreen else reviewColor(it)) }
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
        // conviction (rule-built, verified Buys only)
        val cv = det?.conviction
        val cvLevel = cv?.level
        if (cv != null && cvLevel != null) SheetSection("Conviction", listOfNotNull(cv.rule?.let { "rule $it" }, cv.date?.let { skDay(it) }).joinToString(" · ").ifBlank { null }) {
            Row(Modifier.padding(bottom = 8.dp), verticalAlignment = Alignment.Bottom) {
                T(cvLevel, 15.sp, weight = FontWeight.Bold); if (cv.met != null && cv.of != null) T(" · ${cv.met} of ${cv.of} met", 13.sp)
            }
            if (cv.checks.isNotEmpty()) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                cv.checks.forEach { c ->
                    val col = if (c.ok == true) TierC.lightGreen else Color.White.copy(alpha = 0.13f)
                    Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(col))
                        T(c.id, 9.5.sp, if (c.ok == true) TierC.lightGreen else C.dim, modifier = Modifier.padding(top = 3.dp), maxLines = 1)
                    }
                }
            }
            cv.checks.filter { it.ok != true }.forEach { c ->
                Row(Modifier.padding(top = 6.dp)) {
                    Box(Modifier.padding(top = 6.dp).size(6.dp).clip(CircleShape).background(TierC.yellow)); Spacer(Modifier.width(8.dp))
                    Text(buildAnnotatedString { append("${c.id} ${c.n}: "); withStyle(SpanStyle(color = C.dim)) { append(c.v ?: c.why ?: "not met") } },
                        color = C.white, fontSize = 13.sp, lineHeight = 18.sp)
                }
            }
        } else p?.cv?.let { lv -> SheetSection("Conviction") { T(lv, 15.sp, weight = FontWeight.Bold) } }
        val flags = det?.auditFlags.orEmpty()
        SheetSection("Automatic consistency flags", "${flags.size}") {
            if (flags.isEmpty()) T("None raised", 12.sp, C.dim) else flags.forEach { T("• $it", 12.sp, C.amber, lineHeight = 17.sp) }
        }
        p?.let { pk ->
            SheetSection("Overall score", fmt(pk.pr, 0)) {
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
            ToggleRow("Rule statement and Claude's thesis", r?.updated?.let { skDay(it) } ?: "", more, { more = !more }, Modifier.padding(top = 8.dp))
            if (more) {
                stmt?.let { T(it, 13.sp, lineHeight = 19.sp) }
                r?.thesis?.let {
                    T("CLAUDE'S THESIS" + (r.updated?.let { u -> " · ${skDay(u)}" } ?: ""), 10.sp, C.blue, FontWeight.Bold, modifier = Modifier.padding(top = 10.dp))
                    T(it, 13.sp, lineHeight = 19.sp)
                }
                vl.takeIf { it.size > 1 }?.last()?.let { v -> T("Changed ${skDay(v.d)}: ${v.from} → ${v.v} (${v.cause})", 11.sp, C.amber, modifier = Modifier.padding(top = 8.dp)) }
                det?.stock?.events?.firstOrNull { it.sev == "red" && (skDate(it.date)?.let { d -> !d.isBefore(skToday().minusDays(45)) } ?: false) }?.let { e ->
                    T("${e.type} filed ${skDay(e.date)}: ${e.text.take(120)}", 12.sp, TierC.red, modifier = Modifier.padding(top = 8.dp))
                }
                T("Rule-built from filed numbers and quote-checked research; no AI-typed scores or targets. A decision aid, not advice.", 11.sp, C.dim,
                    modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}
