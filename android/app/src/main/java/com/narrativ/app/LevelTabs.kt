@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/*
 * Level tabs of the stock page (redesign mockups s03 Stability, s11 Quality, s04 Valuation, s05 Management, s06 Momentum,
 * s07 Discovery, s08 Outlook) and the Promises sheet (s10). Each tab: level head (tier, score, one line), the key checks
 * with bullet bars (every check with its formula one tap away), then the level's charts. Figures come from fin/<SYM>.json
 * (metrics, the checks' own value texts), charts/<SYM>.json, rotation.json and research.json; missing data shows a dash
 * or leaves the card out.
 */
const val PENDING = "source not connected yet"

val LEVEL_RULES = listOf(
    "Is the company financially stable? Removed on any hard flag (negative equity, default, audit doubt, insolvency) or 2+ debt-service flags.",
    "Is it a good business? Removed on 2+ quality flags unless revenue and margins are turning around.",
    "Is the price fair for this type of business? Three anchors: own history, peers, what the price implies. Removed only if all 3 say expensive.",
    "Can management be trusted? Removed on a red flag, or a low conviction score with enough data. Missing data never removes.",
    "Is the market noticing? No removals; used to prioritise research.",
    "How many institutions and analysts already own and cover it? No removals.",
    "What could grow the business from here? Needs Claude's research of filings and transcripts.",
)

val TYPE_WHY = mapOf(
    "Bank" to "Lenders are valued on book value: P/B against the return they earn on it (ROE).",
    "NBFC" to "Lenders are valued on book value: P/B against the return they earn on it (ROE).",
    "Insurer" to "Insurers are valued on book value (embedded value needs research).",
    "Holding company" to "Investments are over half its assets, so book value is the anchor (listed holdings value needs research).",
    "Real estate developer" to "Profits are lumpy with project timing, so book value is the anchor.",
    "Cyclical" to "Earnings swing with the cycle, so EV is compared with EBITDA at the average margin of the last 3 years.",
    "Order-book" to "Revenue follows orders; EV / EBITDA with the order book as a research check.",
    "Asset-heavy steady" to "Large fixed assets and debt: EV / EBITDA counts debt that P/E ignores.",
    "Loss-making / early" to "No profit yet, so EV / sales.",
    "Compounder" to "High returns with little capex: P/E against growth.",
    "Standard" to "P/E, the default for steady profitable companies.",
)

private val MUTED_BAR = TierC.grey  // comparison bars (sector, industry, a year ago)

// ---------------------------------------------------------------- one level tab
@Composable
fun LevelTab(st: AppState, sym: String, p: P?, det: Detail?, chart: Chart?, i: Int) {
    val k = LEVELS[i]
    val lv = det?.levels?.get(k)
    var formula by remember { mutableStateOf<Triple<String, String, Metric>?>(null) }
    val open: (String?) -> Unit = { key -> key?.let { kk -> det?.m(kk)?.let { formula = Triple(METRIC_NAMES[kk] ?: kk, kk, it) } } }
    var all by remember { mutableStateOf(false) }
    val t = lv?.t ?: p?.tier(i) ?: 0
    val turn = i == 1 && (lv?.turn ?: p?.turn ?: false) && t != 0
    val name = if (turn) "Turnaround watch" else lv?.name?.ifBlank { null } ?: p?.levelTierName(st, i) ?: "–"
    val score = (lv?.s ?: p?.sc?.getOrNull(i))?.takeIf { t != 0 }
    val line = if (lv != null && det != null) runCatching { headLine(k, lv, det, st, sym) }.getOrNull() ?: lv.why else lv?.why ?: p?.why
    LevelHead(st.levelName(k), name, t, score, line)
    // owner feedback #81: Claude's own outlook score sits under the Outlook head; the tier counts only dated triggers already filed
    if (k == "out") st.research[sym]?.let { r -> r.outlookScore?.let { os ->
        val oc = when { os >= 55 -> TierC.lightGreen; os >= 40 -> TierC.yellow; else -> TierC.lightRed }
        Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                T("Claude's research outlook", SECTION_TITLE, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f), maxLines = 1)
                T("$os/100", SECTION_TITLE, oc, FontWeight.Bold, maxLines = 1)
            }
            T("From Claude's reading of filings and calls" + (r.updated?.let { " (${skDay(it)})" } ?: "") +
                ". The tier above counts only dated triggers already filed.", LABEL, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 4.dp))
        }
    } }
    if (lv?.out == true || p?.out?.l == i + 1) {
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(S.tile)).background(TierC.red.copy(alpha = 0.12f)).padding(S.cardPad)) {
            T("Removed at this level: ${lv?.rm ?: p?.out?.w ?: ""}", 13.sp, TierC.lightRed)
        }
    }
    if (lv == null || det == null) {
        EmptyNote(if (det == null && p != null) "Loading the checks…" else "The checks are published for stocks in the funnel and researched stocks.")
        return
    }
    val onAll = { all = true }
    when (k) {
        "surv" -> StabilityBody(det, lv, open, onAll)
        "qual" -> QualityBody(det, lv, onAll)
        "val" -> ValuationBody(det, lv, onAll)
        "mgmt" -> ManagementBody(st, sym, det, lv, onAll)
        "mom" -> MomentumBody(st, p, det, lv, chart, onAll)
        "disc" -> DiscoveryBody(p, det, lv, onAll)
        "out" -> OutlookBody(st, sym, det, lv, open, onAll)
    }
    if (all) AllChecksSheet(st, i, lv, { all = false }, open)
    formula?.let { (n, kk, m) -> FormulaSheet(n, m, kk, det) { formula = null } }
}

/** The one line under the tier: always "X of N checks pass" first, the level's key figures in brackets. */
private fun headLine(k: String, lv: Level, det: Detail, st: AppState, sym: String): String? {
    val n = lv.items.size; val pass = lv.items.count { it.m == 2 }
    fun lead(extra: List<String?>): String = "$pass of $n checks pass" +
        extra.filterNotNull().filter { it.isNotBlank() }.joinToString(", ").let { if (it.isEmpty()) "" else " ($it)" } + "."
    return when (k) {
        "surv" -> {
            val ncm = det.m("net_cash_pct_mcap")
            val cash = ncm?.inputs?.get("cash_cr")?.content?.toDoubleOrNull(); val debt = ncm?.inputs?.get("debt_cr")?.content?.toDoubleOrNull()
            lead(listOf(if (cash != null && debt != null) (if (cash >= debt) "net cash ₹${fmt(cash - debt, 0)} cr" else "net debt ₹${fmt(debt - cash, 0)} cr") else null))
        }
        "qual" -> {
            val r3 = det.v("roce_3y_avg_pct"); val r4 = det.v("roce_pct"); val rt = det.v("rev_ttm_growth_pct")
            lead(listOf(r3?.let { "ROCE ${skFx(it, 1)}% avg of filed years" }, r4?.let { "${skFx(it, 1)}% last 4 quarters" }, rt?.let { "revenue ${skSgn(it)} last 4 quarters" }))
        }
        "val" -> {
            val v1 = lv.item("V1")?.v
            val pct = skFind(v1, "\\((\\d+)\\w\\w percentile"); val nq = skFind(v1, "percentile, (\\d+) quarters")
            lead(listOf(if (lv.metric == null || lv.mval == null) null
                else "${lv.type ?: "this"} business, ${lv.metric} ${mult(lv.mval)}" +
                    (if (pct != null && nq != null) ", ${skOrd(pct.toInt())} percentile of its own ${nq.toInt()} quarters" else "")))
        }
        "mgmt" -> {
            val scored = lv.items.count { it.m != null }
            lead(listOf("$scored scored", lv.item("C1")?.v?.let { "promoter $it" }, lv.item("C4")?.v, lv.item("C9")?.n?.lowercase()))
        }
        "mom" -> lead(listOf(det.stock.stage, "${lv.items.count { it.m == 0 }} miss"))
        "disc" -> {
            val an = skNums(lv.item("D2")?.v).firstOrNull()?.toInt(); val mf = skNums(lv.item("D6")?.v).firstOrNull()?.toInt()
            val inst = skNums(lv.item("D5")?.v).firstOrNull()  // NSE shareholding, the figure the checks use
            lead(listOf(an?.let { "$it analyst${if (it == 1) "" else "s"}" }, inst?.let { "institutions ${skFx(it, 1)}%" }, mf?.let { "$it mutual funds" }))
        }
        "out" -> lead(listOf(lv.wind?.let { "$it industry" }, lv.nlive?.let { "$it live trigger${if (it == 1) "" else "s"}" },
            if (lv.cov.size == 2) "${lv.cov[0]} of ${lv.cov[1]} with data" else null))
        else -> null
    }
}

private fun short(s: String?, n: Int = 22): String = s?.let { if (it.length > n) it.take(n - 1) + "…" else it } ?: "–"
private fun orGeneric(rows: List<KeyCheck>, lv: Level): List<KeyCheck> = if (rows.size >= 2) rows else genericChecks(lv)

// ---------------------------------------------------------------- Stability (s03)
@Composable
private fun StabilityBody(det: Detail, lv: Level, open: (String?) -> Unit, onAll: () -> Unit) {
    val rows = listOfNotNull(
        lv.item("B2")?.let { it0 -> val v = det.v("net_debt_ebitda")
            KeyCheck(lv.status("B2"), "Net debt / EBITDA", v?.let { mult(it) } ?: short(it0.v), "pass ≤ 5×", v?.let { Bullet(it, -1.0, 6.0, 5.0, higher = false, unit = "×") }) },
        lv.item("B1")?.let { it0 -> val v = det.v("interest_cover")
            KeyCheck(lv.status("B1"), "Interest cover", v?.let { mult(it, if (abs(it) >= 100) 0 else 1) } ?: short(it0.v), "pass ≥ 1.5×", v?.let { Bullet(it, 0.0, 6.0, 1.5, unit = "×") }) },
        lv.item("B4")?.let { it0 -> val v = det.v("current_ratio")
            KeyCheck(lv.status("B4"), "Current ratio", v?.let { skFx(it, 2) } ?: short(it0.v), "pass ≥ 0.8", v?.let { Bullet(it, 0.0, 3.0, 0.8) }) },
        lv.item("B5")?.let { it0 -> val v = skNums(it0.v).firstOrNull()
            KeyCheck(lv.status("B5"), "Promoter pledge", v?.let { "${skFx(it, 1)}%" } ?: short(it0.v), "pass ≤ 50%", v?.let { Bullet(it, 0.0, 100.0, 50.0, higher = false, unit = "%") }) },
    )
    KeyChecksCard(orGeneric(rows, lv), lv.items.size, onAll)
    val ncm = det.m("net_cash_pct_mcap")
    val cash = ncm?.inputs?.get("cash_cr")?.content?.toDoubleOrNull(); val debt = ncm?.inputs?.get("debt_cr")?.content?.toDoubleOrNull()
    if (cash != null && debt != null) SectionCard("Cash vs debt", det.str("bs_date")?.let { skDay(it) }, onClick = { open("net_cash_pct_mcap") }) {
        PairBars(listOf(Triple("Cash and bank", cash, TierC.darkGreen), Triple("Borrowings + leases", debt, TierC.lightRed))) {
            if (it < 10) "₹${skFx(it, 1)} cr" else "₹${fmt(it, 0)} cr"
        }
        val de = det.m("de")
        val bor = de?.inputs?.get("borrowings_cr")?.content?.toDoubleOrNull(); val lea = de?.inputs?.get("lease_liabilities_cr")?.content?.toDoubleOrNull()
        if (bor != null) T("Borrowings ₹${skFx(bor, 2)} cr" + (lea?.let { " · leases ₹${skFx(it, 2)} cr" } ?: ""), 12.sp, C.dim, modifier = Modifier.padding(top = 10.dp))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatTile("Equity", det.v("equity_cr")?.let { "₹${fmt(it, 0)} cr" } ?: "–", Modifier.weight(1f), onClick = { open("equity_cr") })
        StatTile("Debt / equity", mult(det.v("de"), 2), Modifier.weight(1f), onClick = { open("de") })
        StatTile("Net cash / mcap", det.v("net_cash_pct_mcap")?.let { "${skFx(it, 1)}%" } ?: "–", Modifier.weight(1f), onClick = { open("net_cash_pct_mcap") })
    }
    val flags = (det.metrics["flags"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }.orEmpty()
    val exc = flags.firstOrNull { it.contains("exceptional", ignoreCase = true) }
    val neg = det.v("cfo_negative_years"); val loss = det.v("loss_quarters_4")
    // feedback #89: operating cash by full year and net profit by quarter as small bar charts (formula one tap away)
    val cfoIn = det.m("cfo_negative_years")?.inputs.orEmpty()
    val cfo = cfoIn.mapNotNull { (k, v) -> CFO_KEY.matchEntire(k)?.groupValues?.get(1)?.toIntOrNull()?.let { y -> v.content.toDoubleOrNull()?.let { y to it } } }
        .sortedBy { it.first }
    val lossIn = det.m("loss_quarters_4")?.inputs.orEmpty()
    val profits = lossIn["profits_cr"]?.content?.split(",")?.mapNotNull { it.trim().replace("−", "-").toDoubleOrNull() }.orEmpty().reversed()
    val qNames = lossIn["quarters"]?.content?.split(",")?.map { it.trim() }.orEmpty().reversed()
    if (cfo.isNotEmpty()) SectionCard("Operating cash", "₹ cr, full years", onClick = { open("cfo_negative_years") }) {
        MiniBars(cfo.map { it.second }, cfo.map { "FY%02d".format(it.first % 100) })
        val profit = cfoIn["profit_latest_fy_cr"]?.content?.toDoubleOrNull()
        val (ly, lc) = cfo.last()
        if (profit != null) T("FY%02d profit ₹${skFx(profit, 1)} cr".format(ly % 100) + (if (profit > 0) " · cash from operations ${skFx(lc / profit * 100, 0)}% of it" else ""),
            LABEL, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 8.dp))
    }
    if (profits.isNotEmpty()) SectionCard("Net profit", "₹ cr, last ${profits.size} quarters", onClick = { open("loss_quarters_4") }) {
        val labels = if (qNames.size == profits.size) qNames.map { qShort(it) } else profits.indices.map { "Q${it + 1}" }
        MiniBars(profits, labels)
    }
    val oldRows = cfo.isEmpty() || profits.isEmpty()
    if (oldRows || exc != null || flags.isNotEmpty()) Card(Modifier.fillMaxWidth()) {
        if (cfo.isEmpty()) KvRow("Operating cash, last 3 years", trailing = { if (neg != null) Meter(3, 3 - neg.toInt(), color = TierC.lightGreen, style = MeterStyle.Dot) else T("–", 13.sp) },
            divider = profits.isEmpty() || exc != null || flags.isNotEmpty(), onClick = { open("cfo_negative_years") })
        if (profits.isEmpty()) KvRow("Profitable quarters, last 4", trailing = { if (loss != null) Meter(4, 4 - loss.toInt(), color = TierC.lightGreen, style = MeterStyle.Dot) else T("–", 13.sp) },
            divider = exc != null || flags.isNotEmpty(), onClick = { open("loss_quarters_4") })
        exc?.let { KvRow("Exceptional items, 4Q", skNums(it).firstOrNull()?.let { v -> "₹${skFx(v, 1)} cr" } ?: "–", divider = flags.size > 1) }
        flags.filter { it != exc }.forEach { T("• $it", 12.sp, C.amber, lineHeight = 17.sp, modifier = Modifier.padding(top = 6.dp)) }
    }
}

private val OWN_PROMOTER = Color(0xFFE8E9EA)
private val OWN_PUBLIC = Color(0xFF4A4E53)

/** Shareholding ring (~130dp): one arc per holder group, promoter % in the centre. */
@Composable
private fun OwnerRing(parts: List<Triple<String, Double, Color>>, promoter: Double) {
    val total = parts.sumOf { it.second }.takeIf { it > 0 } ?: 100.0
    Box(Modifier.size(130.dp), contentAlignment = Alignment.Center) {
        androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
            val w = 18.dp.toPx(); val gap = if (parts.size > 1) 1.5f else 0f
            val tl = androidx.compose.ui.geometry.Offset(w / 2, w / 2)
            val sz = androidx.compose.ui.geometry.Size(size.width - w, size.height - w)
            var start = -90f
            parts.forEach { (_, v, c) ->
                val sweep = (v / total * 360.0).toFloat()
                if (sweep > gap) drawArc(c, start + gap / 2, sweep - gap, false, tl, sz, style = androidx.compose.ui.graphics.drawscope.Stroke(w))
                start += sweep
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            T("${skFx(promoter, 1)}%", 18.sp, weight = FontWeight.Bold, maxLines = 1)
            T("promoter", LABEL, C.dim, maxLines = 1)
        }
    }
}

private val CFO_KEY = Regex("cfo_fy(\\d+)_cr")

/** "2026-09-30" -> "Sep 26". */
private fun qShort(iso: String): String = skDate(iso)?.let { d ->
    d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH) + " " + "%02d".format(d.year % 100)
} ?: iso

/** Small column chart: value label above each bar (below for a negative one), zero line, label under each column.
 *  Positive bars light green, negative light red below the zero line. */
@Composable
private fun MiniBars(values: List<Double>, labels: List<String>, plot: androidx.compose.ui.unit.Dp = 64.dp) {
    val maxPos = values.maxOf { max(it, 0.0) }; val maxNeg = values.maxOf { max(-it, 0.0) }
    val total = (maxPos + maxNeg).takeIf { it > 0 } ?: 1.0
    val posH = plot * (maxPos / total).toFloat(); val negH = plot * (maxNeg / total).toFloat()
    val lab = 18.dp
    Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        values.forEachIndexed { i, v ->
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                Column(Modifier.fillMaxWidth().height(posH + lab), verticalArrangement = Arrangement.Bottom, horizontalAlignment = Alignment.CenterHorizontally) {
                    if (v >= 0) {
                        T(skFx(v, 1), 12.sp, C.white, FontWeight.SemiBold, maxLines = 1)
                        Box(Modifier.padding(top = 2.dp).fillMaxWidth(0.6f).height((plot * (v / total).toFloat()).coerceAtLeast(2.dp))
                            .clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp)).background(TierC.lightGreen))
                    }
                }
                Box(Modifier.fillMaxWidth().height(1.dp).background(C.line))
                if (maxNeg > 0) Column(Modifier.fillMaxWidth().height(negH + lab), horizontalAlignment = Alignment.CenterHorizontally) {
                    if (v < 0) {
                        Box(Modifier.fillMaxWidth(0.6f).height((plot * (-v / total).toFloat()).coerceAtLeast(2.dp))
                            .clip(RoundedCornerShape(bottomStart = 3.dp, bottomEnd = 3.dp)).background(TierC.lightRed))
                        T(skFx(v, 1), 12.sp, TierC.lightRed, FontWeight.SemiBold, maxLines = 1, modifier = Modifier.padding(top = 2.dp))
                    }
                }
                T(labels.getOrElse(i) { "" }, LABEL, C.dim, maxLines = 1, modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}

// ---------------------------------------------------------------- Quality (s11)
@Composable
private fun QualityBody(det: Detail, lv: Level, onAll: () -> Unit) {
    val cc = det.v("cfo_to_ebitda_pct"); val r3 = det.v("roce_3y_avg_pct"); val r4 = det.v("roce_pct"); val em = det.v("ebitda_margin_pct")
    val rg = det.v("rev_cagr_3y_pct"); val rt = det.v("rev_ttm_growth_pct")
    val rows = listOfNotNull(
        if (lv.item("Q7") != null && cc != null) KeyCheck(lv.status("Q7"), "Cash conversion", "${skFx(cc, 0)}%", "pass ≥ 70%", Bullet(cc, 0.0, 100.0, 70.0, partly = 50.0, unit = "%")) else null,
        // the check scores the lower of the two: the figure printed is the one plotted, the other is named beside the pass line
        if (lv.item("Q1") != null && r3 != null) {
            val last = r4 != null && r4 < r3; val shown = if (last) r4!! else r3
            KeyCheck(lv.status("Q1"), if (last) "ROCE, last 4 quarters" else "ROCE, avg of filed years", "${skFx(shown, 1)}%",
                "pass ≥ 15%" + (if (last) " · avg ${skFx(r3, 1)}%" else r4?.let { " · last 4Q ${skFx(it, 1)}%" } ?: ""),
                Bullet(shown, 0.0, 30.0, 15.0, partly = 10.0, unit = "%"))
        } else null,
        if (lv.item("Q2") != null && em != null) KeyCheck(lv.status("Q2"), "EBITDA margin", "${skFx(em, 1)}%", "pass ≥ 12%", Bullet(em, 0.0, 40.0, 12.0, partly = 8.0, unit = "%")) else null,
        if (lv.item("Q3") != null && rg != null) {
            val last = rt != null && rt < rg; val shown = if (last) rt!! else rg
            KeyCheck(lv.status("Q3"), if (last) "Revenue growth, last 4 quarters" else "Revenue growth, 3-yr avg", "${skFx(shown, 1)}%",
                "pass ≥ 10%" + (if (last) " · 3-yr avg ${skFx(rg, 1)}%" else rt?.let { " · last 4Q ${skFx(it, 1)}%" } ?: ""),
                Bullet(shown, 0.0, 25.0, 10.0, partly = 5.0, unit = "%"))
        } else null,
    )
    KeyChecksCard(orGeneric(rows, lv), lv.items.size, onAll)
    val q = det.quarterly.zip(det.quarterNames).filter { (r, _) -> r.getOrNull(1) != null }.takeLast(8)
    if (q.size >= 4) SectionCard("Revenue and margin", "${q.size} quarters · ₹ cr") {
        val withMargin = q.all { it.first.getOrNull(3) != null }
        BarsWithLine(q.map { it.first[1]!! }, if (withMargin) q.map { it.first[3]!! } else emptyList(), q.map { shortMonth(it.second) }, barColor = C.muted,
            lastBarLabel = "₹${fmt(q.last().first[1], 0)} cr", lineEndLabel = if (withMargin) "margin ${skFx(q.last().first[3], 1)}%" else null)
        val prof = q.mapNotNull { it.first.getOrNull(2) }
        if (prof.size == q.size) {
            var open by remember { mutableStateOf(false) }
            ToggleRow("Profit by quarter", "₹${fmt(prof.last(), 0)} cr latest", open, { open = !open }, Modifier.padding(top = 8.dp))
            if (open) Bars(prof, Modifier.fillMaxWidth().height(96.dp), labels = q.map { shortMonth(it.second) }, valueFmt = { fmt(it, 0) }, colors = prof.map { if (it >= 0) TierC.lightGreen else TierC.lightRed })
        }
    }
    RoceCard(det, det.v("roce_pct")?.let { "last 4 quarters ${skFx(it, 1)}%" })
}

@Composable
private fun RoceCard(det: Detail, right: String?) {
    val roce = det.roceFy
    if (roce.isEmpty()) return
    SectionCard("ROCE by year", right) {
        Bars(roce.map { it.second }, Modifier.fillMaxWidth().height(90.dp), labels = roce.map { "FY${it.first % 100}" }, valueFmt = { "${skFx(it, 1)}%" }, color = C.muted,
            base = roce.minOf { it.second }.let { if (it > 0) it * 0.8 else null })
    }
}

// ---------------------------------------------------------------- Valuation (s04)
@Composable
private fun ValuationBody(det: Detail, lv: Level, onAll: () -> Unit) {
    val key = lv.mkey ?: METRIC_KEY_OF[lv.metric] ?: "pe"
    val metric = lv.metric ?: METRIC_NAMES[key] ?: key
    val v1 = lv.item("V1"); val v2 = lv.item("V2"); val v3 = lv.item("V3")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf(v1 to "Own history", v2 to "Peers", v3 to "Implied growth").forEach { (it0, n) ->
            it0?.let { DotChip("$n · ${statusOf(it.m)}", statusColor(statusOf(it.m))) }
        }
        if (lv.cheap != null || lv.exp != null) ValChip("${lv.cheap ?: 0} cheap · ${lv.exp ?: 0} expensive")
    }
    val pts = det.hist.mapNotNull { h -> h[key]?.content?.toDoubleOrNull()?.let { (h["q"]?.content ?: "") to it } }
    val mval = lv.mval
    val qs = ChartMath.quartiles(pts.map { it.second })
    if (pts.size >= 4 && qs != null) {
        val pct = skFind(v1?.v, "\\((\\d+)\\w\\w percentile")?.toInt()
        SectionCard("$metric, own history", listOfNotNull(v1?.let { statusOf(it.m) }, pct?.let { "${skOrd(it)} pct of ${pts.size} quarters" }).joinToString(" · ")) {
            val (q25, med, q75) = qs
            AreaLine(pts.map { it.second }, Modifier.fillMaxWidth().height(170.dp), color = C.muted, fillAlpha = 0.22f,
                cheapBelow = q25, cheapLabel = "cheap ≤ ${mult(q25)}", expensiveAbove = q75, expensiveLabel = "expensive ≥ ${mult(q75)}",
                median = med, medianLabel = "median ${mult(med)}", today = mval, todayLabel = mval?.let { mult(it) },
                todayColor = v1?.let { statusColor(statusOf(it.m)) } ?: TierC.lightGreen,
                xLabels = listOf(shortMonth(pts.first().first), shortMonth(pts.last().first)))
        }
    }
    val peer = skFind(v2?.v, "median (-?[\\d.]+)"); val peerN = skFind(v2?.v, "\\((\\d+) compan")?.toInt()
    val ipe = det.stock.indPe?.takeIf { key == "pe" }
    if (peer != null && mval != null && peer > 0) SectionCard("Vs peers", listOfNotNull(v2?.let { statusOf(it.m) }, peerN?.let { "$it peers" }, "cheap < 0.8× median").joinToString(" · ")) {
        val hi = max(max(peer, ipe ?: 0.0), mval) * 1.25
        RangeBar(0.0, hi, listOfNotNull(RangeMark(mval, "$metric ${mult(mval)}", v2?.let { statusColor(statusOf(it.m)) } ?: TierC.lightGreen, above = true),
            RangeMark(peer, "peers ${mult(peer)}", C.dim), ipe?.let { RangeMark(it, "industry ${mult(it)}", TierC.yellow, above = true) }),
            Modifier.fillMaxWidth().height(50.dp), band = HBand(0.0, peer * 0.8, TierC.darkGreen))
    }
    val impl = skFind(v3?.v, "implies (-?[\\d.]+)%"); val deliv = skFind(v3?.v, "vs (-?[\\d.]+)% delivered")
    if (impl != null && deliv != null) SectionCard("Growth the price needs", listOfNotNull(v3?.let { statusOf(it.m) }, "a year, 10 years").joinToString(" · ")) {
        DivergingBars(listOf(DivRow("Price implies", impl, C.muted), DivRow("Delivered", deliv, if (deliv >= impl) TierC.lightGreen else TierC.lightRed)),
            span = max(25.0, max(abs(impl), abs(deliv)) * 1.1))
    }
    SectionCard("Business type: ${lv.type ?: "–"}", more = "All ${lv.items.size} checks with formulas", onMore = onAll) {
        TYPE_WHY[lv.type]?.let { T(it, 13.sp, C.dim, lineHeight = 18.sp) }
        val others = listOf("ev_ebitda" to "EV / EBITDA", "pb" to "P/B", "pe" to "P/E", "ev_sales" to "EV / sales").filter { it.first != key }
            .mapNotNull { (k, n) -> det.v(k)?.let { "$n ${mult(it)}" } }
        if (others.isNotEmpty()) FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            others.forEach { ValChip(it) }
        }
    }
}

// ---------------------------------------------------------------- Management (s05)
private fun promColor(s: String): Color = when (s) {
    "delivered", "beat", "raised" -> TierC.lightGreen; "partly", "delayed" -> TierC.yellow; "missed", "off_track" -> TierC.lightRed; else -> C.grey  // pending: grey, never blue
}

@Composable
private fun ManagementBody(st: AppState, sym: String, det: Detail, lv: Level, onAll: () -> Unit) {
    val r = st.research[sym]
    val c8 = lv.item("C8"); val c8n = skNums(c8?.v)
    val rows = listOfNotNull(
        lv.item("G1")?.let { g -> KeyCheck(lv.status("G1"), "Exchange action",
            if (g.v?.matches(Regex("^\\d{4}-\\d{2}-\\d{2}.*")) == true) skDay(g.v) else short(g.v, 16),
            r?.flagReviews?.get("G1")?.verdict?.let { "$it by Claude" } ?: "24 months") },
        if (c8 != null && c8n.size >= 4) KeyCheck(lv.status("C8"), "ROCE held", skSgn(c8n[3] - c8n[1], 1, " pts"),
            "FY${c8n[0].toInt()}→${c8n[2].toInt()} · pass ≥ −2 pts", Bullet(c8n[3] - c8n[1], -6.0, 2.0, -2.0, partly = -5.0, unit = " pts")) else null,
        lv.item("C3")?.let { c -> KeyCheck(lv.status("C3"), "Promoter buying", if (c.v?.startsWith("no ") == true) "no trades" else short(c.v, 16), "12 months") },
        lv.item("C1")?.let { c -> val v = skNums(c.v).firstOrNull()
            KeyCheck(lv.status("C1"), "Promoter holding", v?.let { "${skFx(it, 1)}%" } ?: short(c.v), "pass ≥ 50%", v?.let { Bullet(it, 0.0, 100.0, 50.0, partly = 25.0, unit = "%") }) },
    )
    KeyChecksCard(orGeneric(rows, lv), lv.items.size, onAll)
    val pro = det.stock.promoter.sortedBy { it.date }
    if (pro.size >= 2) SectionCard("Promoter holding", "${pro.size} quarters · ${skSgn(pro.last().pct - pro.first().pct, 2, " pts")}") {
        val vs = pro.map { it.pct }
        AreaLine(vs, Modifier.fillMaxWidth().height(110.dp), color = TierC.lightGreen, fillAlpha = 0.22f,
            lo = min(45.0, vs.min() - 5), hi = min(100.0, max(vs.max() + 10, 55.0)), median = 50.0, medianLabel = "50% pass line",
            endLabel = "${skFx(vs.last(), 2)}%", endLabelPos = EndLabel.Right, xLabels = listOf(shortMonth(pro.first().date), shortMonth(pro.last().date)))
    }
    RoceCard(det, det.v("rev_cagr_3y_pct")?.let { "revenue ${skFx(it, 1)}%/yr meanwhile" })
    var sheet by remember { mutableStateOf(false) }
    val proms = r?.promises.orEmpty()
    val firstDue = proms.mapNotNull { it.due }.minOrNull()
    SectionCard("Promises", if (proms.isEmpty()) null else "${proms.size} from ${skDue(proms.minOf { it.madeOn })}" + (firstDue?.let { " · first due ${skDue(it)}" } ?: ""),
        more = "Promises timeline", onMore = { sheet = true }) {
        if (proms.isEmpty()) T(r?.noConcall ?: "No promises on record yet.", 13.sp, C.dim, lineHeight = 18.sp)
        else PromiseMeter(r!!)
    }
    if (sheet) PromisesSheet(st, sym) { sheet = false }
}

@Composable
private fun PromiseMeter(r: Research) {
    val proms = r.promises
    SegmentedBar(proms.map { Segment(1.0, promColor(it.status)) }, height = 10.dp, legend = SegLegend.None)
    val kept = proms.count { it.status in setOf("delivered", "beat", "raised") }; val missed = proms.count { it.status in setOf("missed", "off_track") }
    val partly = proms.count { it.status in setOf("partly", "delayed") }; val pending = proms.size - kept - missed - partly
    FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        DotChip("$pending pending", C.grey); DotChip("$kept kept", TierC.lightGreen)
        if (partly > 0) DotChip("$partly partly or late", TierC.yellow)
        DotChip("$missed missed", TierC.lightRed)
        ValChip(r.credibility?.let { "kept-rate ${it.pct}% of ${it.due}" } ?: "kept-rate after 2 resolve")
    }
}

// ---------------------------------------------------------------- Promises sheet (s10)
private val ISO_DATE = Regex("\\d{4}-\\d{2}-\\d{2}")
private val KIND_LABEL = mapOf("product" to "Product", "factory" to "Factory", "capacity" to "Capacity")

@Composable
fun PromisesSheet(st: AppState, sym: String, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val r = st.research[sym]
    val proms = r?.promises.orEmpty()
    val hist by produceState(st.repo.peek<StockHistory>("data/stocks/${Repo.seg(sym)}.json"), sym) {
        val path = "data/stocks/${Repo.seg(sym)}.json"
        value = st.repo.peek<StockHistory>(path)  // another symbol: never keep the previous stock's history
        st.repo.cacheFirst<StockHistory>(path) { if (it != null) value = it }
    }
    BottomSheet(onDismiss, "Promises", aside = "Management") {
        if (r != null && proms.isNotEmpty()) SheetSection { PromiseMeter(r) }
        r?.noConcall?.let { T(it, 13.sp, C.dim, lineHeight = 18.sp, modifier = Modifier.padding(bottom = 10.dp)) }
        if (proms.isEmpty() && r?.noConcall == null) T("Not researched yet. Request a full review from the Summary tab; only figures quoted from primary filings are shown.",
            13.sp, C.dim, lineHeight = 18.sp, modifier = Modifier.padding(bottom = 10.dp))
        proms.groupBy { it.madeOn to it.call }.toSortedMap(compareBy({ it.first }, { it.second })).forEach { (k, ps) ->
            SheetSection(k.second, skDay(k.first)) {
                T("${ps.size} promise${if (ps.size == 1) "" else "s"}" + if (ps.all { it.dueVerified == true }) " · due dates verified" else "", 12.sp, C.dim,
                    modifier = Modifier.padding(top = 0.dp, bottom = 4.dp))
                ps.forEach { pr ->
                    HLineDivider()
                    Column(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T((KIND_LABEL[pr.kind] ?: pr.kind.replaceFirstChar { it.uppercase() }) + (pr.due?.let { " · due ${skDue(it)}" } ?: ""),
                                LABEL, C.dim, FontWeight.Medium, Modifier.weight(1f), maxLines = 1)
                            StatusChip(STATUS_LABEL[pr.status] ?: pr.status, color = promColor(pr.status), minWidth = 0.dp)
                        }
                        T(pr.promise, 14.sp, weight = FontWeight.Medium, lineHeight = 19.sp, modifier = Modifier.padding(top = 3.dp))
                        var q by remember { mutableStateOf(false) }
                        Row(Modifier.padding(top = 4.dp).clip(RoundedCornerShape(6.dp)).clickable { q = !q }, verticalAlignment = Alignment.CenterVertically) {
                            T("Quote and source", 12.sp, C.blue)
                            Icon(if (q) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore, null, tint = C.blue, modifier = Modifier.size(14.dp))
                        }
                        if (q) Quote(ctx, pr.quote, pr.source)
                        pr.updates.forEach { u ->
                            Column(Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(S.inner)).background(C.card).padding(10.dp)) {
                                T("${UPDATE_LABEL[u.type] ?: u.type} · ${u.call}", LABEL, C.dim, FontWeight.Medium)
                                T(u.text, 13.sp, weight = FontWeight.Medium)
                                Quote(ctx, u.quote, u.source)
                            }
                        }
                    }
                }
            }
        }
        val cps = hist?.checkpoints.orEmpty()
        if (cps.isNotEmpty()) {
            val today = skToday().toString()
            fun tidy(t: String) = t.replace("Quarterly results for quarter ending", "Results, quarter to").replace("Shareholding pattern for quarter ending", "Shareholding, quarter to")
                .replace(ISO_DATE) { skDay(it.value) }
            val past = cps.filter { it.status != "open" && it.status != "due" }.sortedBy { it.resolved ?: it.due }.map { c ->
                val q = ISO_DATE.find(c.what)?.value
                val title = when (c.type) { "results" -> "Results"; "shareholding" -> "Shareholding"; else -> tidy(c.what) } +
                    (if (c.type in setOf("results", "shareholding") && q != null) " ${shortMonth(q)}" else "") + " · ${c.status.replaceFirstChar { it.uppercase() }}"
                TimelineItem(skDay(c.resolved ?: c.due), title, c.outcome, if (c.status == "met") TierC.lightGreen else if (c.status == "missed") TierC.lightRed else C.dim)
            }
            val ahead = cps.filter { it.status == "open" || it.status == "due" }.sortedBy { it.due }.map { c ->
                val (sub, col) = when (c.type) {
                    "results" -> "Results" to C.dim; "shareholding" -> "Shareholding" to C.dim; "must_go_right" -> "Must go right" to TierC.lightGreen
                    "kill_switch" -> "Kill switch" to TierC.red; "promise" -> "Promise due" to C.grey; else -> c.type.replace('_', ' ') to C.dim
                }
                TimelineItem(skDue(c.due), tidy(c.what), if (c.status == "due") "$sub · review due" else sub, col, hollow = c.type in setOf("results", "shareholding"))
            }
            SheetSection("Timeline", "${past.size} checked · ${ahead.size} ahead") {
                DotTimeline(past + TimelineItem(skDay(today), "Today", today = true) + ahead, ring = C.sheet)
            }
        }
        if (r != null && r.redFlags.isNotEmpty()) SheetSection("Red flags") {
            r.redFlags.forEach { f ->
                Column(Modifier.fillMaxWidth().clickable { openUrl(ctx, f.source) }.padding(vertical = 5.dp)) {
                    T(f.text, 13.sp, TierC.lightRed, lineHeight = 18.sp); if (f.quote.isNotBlank()) Quote(ctx, f.quote, f.source)
                }
            }
        }
        if (r != null && r.catalysts.isNotEmpty()) SheetSection("Catalysts") {
            r.catalysts.forEach { c -> T("• ${c.text}", 13.sp, lineHeight = 18.sp, modifier = Modifier.padding(vertical = 3.dp)) }
        }
        T("Every promise is a verbatim quote from a primary filing, re-checked against the source daily.", 11.sp, C.dim, lineHeight = 15.sp)
    }
}

// ---------------------------------------------------------------- Momentum (s06)
@Composable
private fun MomentumBody(st: AppState, p: P?, det: Detail, lv: Level, chart: Chart?, onAll: () -> Unit) {
    val s = det.stock
    val p4 = skNums(lv.item("P4")?.v).firstOrNull(); val e2 = skNums(lv.item("E2")?.v).firstOrNull(); val p3 = skNums(lv.item("P3")?.v).firstOrNull()?.toInt()
    val e1 = skNums(lv.item("E1")?.v)
    val rows = listOfNotNull(
        p4?.let { KeyCheck(lv.status("P4"), "52-week high", skSgn(it), "pass within −10%", Bullet(it, -40.0, 0.0, -10.0, unit = "%")) },
        e2?.let { KeyCheck(lv.status("E2"), "Results reaction", skSgn(it), "3 days · pass > +5%", Bullet(it, -10.0, 10.0, 5.0, partly = -5.0, unit = "%")) },
        p3?.let { KeyCheck(lv.status("P3"), "Industry rank", "${skOrd(it)} pct", "pass: top third", Bullet(it.toDouble(), 0.0, 100.0, 67.0, unit = "th")) },
        if (e1.size >= 2) KeyCheck(lv.status("E1"), "Growth trend", "${skFx(e1[0], 1)}% vs ${skFx(e1[1], 1)}%", "revenue YoY, faster") else null,
    )
    KeyChecksCard(orGeneric(rows, lv), lv.items.size, onAll)
    if (s.rsPct != null || s.stage != null) Card(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            s.rsPct?.let { ArcGauge(it, "RS pct", color = C.muted) }
            Column(Modifier.weight(1f)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    s.stage?.let { stg -> DotChip(stg, when { stg.contains("Advanc", true) || stg.contains("Uptrend", true) -> TierC.lightGreen
                        stg.contains("Declin", true) || stg.contains("Downtrend", true) -> TierC.lightRed; else -> TierC.yellow }) }
                    s.dist200?.let { ValChip("vs 200-day ${skSgn(it)}", gainColor(it)) }
                }
                T("Relative strength vs all stocks" + (p3?.let { "; industry rank ${skOrd(it)}." } ?: "."), 12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
    val c = chart?.c.orEmpty()
    val now = p?.p ?: c.lastOrNull()
    val s50 = chart?.sma50?.lastOrNull { it != null }; val s200 = chart?.sma200?.lastOrNull { it != null }
    if (s.lo52 != null && s.hi52 != null && s.hi52 > s.lo52) SectionCard("52-week range") {
        RangeBar(s.lo52, s.hi52, listOfNotNull(RangeMark(s.lo52, skRs(s.lo52), C.dim), s200?.let { RangeMark(it, "200-day", C.muted, above = true) },
            s50?.let { RangeMark(it, "50-day", TierC.yellow, above = true) }, now?.let { RangeMark(it, "now ${skRs(it)}", C.white) }, RangeMark(s.hi52, skRs(s.hi52), C.dim)))
    }
    if (c.size >= 30) SectionCard("6 months") {
        val n = min(130, c.size)
        AreaLine(c.takeLast(n), Modifier.fillMaxWidth().height(140.dp), color = C.muted, fillAlpha = 0.12f, strokeWidth = 1.6.dp,
            overlays = listOfNotNull(chart?.sma50?.takeIf { it.size == c.size }?.let { Series(it.takeLast(n), TierC.yellow, s50?.let { v -> "50-day ${skRs(v)}" }) },
                chart?.sma200?.takeIf { it.size == c.size }?.let { Series(it.takeLast(n), C.white, s200?.let { v -> "200-day ${skRs(v)}" }) }),
            endLabel = "now ${skRs(c.last())}", endLabelPos = EndLabel.Right, hollowEnd = true)
    }
    val ind = p?.i ?: s.industry
    val secKey = ind?.let { SECTOR_OF[it] }
    val sec = secKey?.let { st.rotation?.sectors?.get(it) }; val ir = ind?.let { st.rotation?.industries?.get(it) }
    val ret1m = if (c.size >= 23) (c.last() / c[c.size - 22] - 1) * 100 else null
    val code = p?.c ?: ""
    val secName = sec?.ticker ?: "Nifty ${secKey ?: ""}"
    val rows2 = buildList {
        add(DivRow(code, ret1m, gainColor(ret1m), "1 month"))
        sec?.let { add(DivRow(secName, it.r1m, MUTED_BAR)) }; ir?.let { add(DivRow("Industry", it.r1m, MUTED_BAR)) }
        add(DivRow(code, s.ret3m, gainColor(s.ret3m), "3 months"))
        sec?.let { add(DivRow(secName, it.r3m, MUTED_BAR)) }; ir?.let { add(DivRow("Industry", it.r3m, MUTED_BAR)) }
        add(DivRow(code, s.ret6m, gainColor(s.ret6m), "6 months"))
    }
    SectionCard("Returns", "price; sector and industry from rotation") {
        DivergingBars(rows2, mutedColor = MUTED_BAR)
        s.tradedValueCr?.let { T("Traded value ₹${skFx(it, 1)} cr a day (20-day avg)", 12.sp, C.dim, modifier = Modifier.padding(top = 6.dp)) }
    }
    if (s.bulkDeals.isNotEmpty()) SectionCard("Bulk and block deals", "1 month · NSE") {
        s.bulkDeals.forEachIndexed { i, d ->
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                val buy = d.side.equals("BUY", true)
                StatusChip(if (buy) "Buy" else "Sell", color = if (buy) TierC.lightGreen else TierC.lightRed)
                Column(Modifier.weight(1f)) { T(d.client ?: "", 13.sp, maxLines = 1); T("${skDay(d.date)} · ${fmt(d.qty, 0)} @ ${skRs(d.price, 2)}", 11.sp, C.dim) }
            }
            if (i < s.bulkDeals.lastIndex) HLineDivider()
        }
    }
}

// ---------------------------------------------------------------- Discovery (s07)
@Composable
private fun DiscoveryBody(p: P?, det: Detail, lv: Level, onAll: () -> Unit) {
    val s = det.stock
    val d5 = lv.item("D5")?.v
    val inst = skNums(d5).firstOrNull(); val mf = skFind(d5, "MF (-?[\\d.]+)%"); val fii = skFind(d5, "foreign (-?[\\d.]+)%")
    val c1q = skFind(d5, "1Q (-?[\\d.]+) pts"); val c4q = skFind(d5, "4Q (-?[\\d.]+) pts")
    val rows = listOfNotNull(
        c1q?.let { KeyCheck(lv.status("D5"), "Institutions, 1 quarter", skSgn(it, 1, " pts"), "pass ≥ +0.5 pts", Bullet(it, -1.0, 1.0, 0.5, partly = -2.0, unit = " pts")) },
        lv.volRatio?.let { KeyCheck(lv.status("D3"), "Volume 50-day / 200-day", mult(it), "pass ≥ 1.3×", Bullet(it, 0.0, 2.0, 1.3, unit = "×")) },
        lv.item("D8")?.let { d -> KeyCheck(lv.status("D8"), "Index", short(d.v?.substringBefore(" (")?.removePrefix("Nifty "), 18), "pass: in no Nifty index") },
        // NSE shareholding (D5), the one institutional figure on the page
        inst?.let { KeyCheck(lv.status("D1"), "Institutional holding", "${skFx(it, 1)}%", "pass < 10%", Bullet(it, 0.0, 30.0, 10.0, higher = false, partly = 25.0, unit = "%")) },
    )
    KeyChecksCard(orGeneric(rows, lv), lv.items.size, onAll)
    val pro = s.promoter.maxByOrNull { it.date }
    if (pro != null && inst != null) SectionCard("Who owns it", skDate(pro.date)?.let { d ->
        d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH) + " ${d.year} quarter, NSE" } ?: "NSE shareholding") {
        val other = if (mf != null && fii != null) Math.round((inst - mf - fii) * 10) / 10.0 else null
        val public = 100 - pro.pct - inst
        // feedback #84: a ring instead of the stacked bar, legend at the right
        val parts = listOfNotNull(Triple("Promoter", pro.pct, OWN_PROMOTER),
            mf?.takeIf { fii != null }?.let { Triple("Mutual funds", it, C.blue) },
            fii?.takeIf { mf != null }?.let { Triple("Foreign", it, TierC.violet) },
            other?.takeIf { it > 0 }?.let { Triple("Other institutions", it, TierC.yellow) },
            if (fii == null || mf == null) Triple("Institutions", inst, C.blue) else null,
            Triple("Public", public, OWN_PUBLIC)).filter { it.second > 0 }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OwnerRing(parts, pro.pct)
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                parts.forEach { (n, v, c) ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(c)); Spacer(Modifier.width(8.dp))
                        T(n, 13.sp, C.muted, modifier = Modifier.weight(1f), maxLines = 1)
                        T("${skFx(v, 1)}%", 13.sp, weight = FontWeight.Bold, maxLines = 1)
                    }
                }
            }
        }
    }
    if (inst != null && pro != null) T("Institutional holding from NSE shareholding, quarter to ${skDay(pro.date)}", LABEL, C.dim,
        modifier = Modifier.padding(horizontal = S.cardPad))
    val d6 = lv.item("D6")?.v
    if (inst != null && c1q != null && c4q != null) SectionCard("Institutional holding",
        skNums(d6).firstOrNull()?.let { n -> "${n.toInt()} mutual funds" + (skFind(d6, "\\(([+-]?\\d+) in a quarter")?.let { " (${if (it >= 0) "+" else ""}${it.toInt()})" } ?: "") }) {
        AreaLine(listOf(inst - c4q, inst - c1q, inst), Modifier.fillMaxWidth().height(100.dp), color = TierC.yellow, fillAlpha = 0.22f, pointDots = true,
            endLabel = "${skFx(inst, 1)}%", endLabelPos = EndLabel.Right, rightGutter = 56.dp,
            xLabels = listOf("4Q ago", "1Q ago", pro?.let { shortMonth(it.date) } ?: "now"))
    }
    val a = det.analyst
    val price = p?.p
    if (a != null && a.mean > 0) SectionCard("Analyst target", listOfNotNull(a.mix, if (a.low != null && a.high != null) "range ${rangeStr(a.low, a.high)}" else null,
        a.fresh?.lowercase()).joinToString(" · ")) {
        val lo = listOfNotNull(price, a.low, a.mean).min() * 0.97; val hi = listOfNotNull(price, a.high, a.mean).max() * 1.02
        RangeBar(lo, hi, listOfNotNull(price?.let { RangeMark(it, "now ${skRs(it)}", C.white) },
            RangeMark(a.mean, "avg ${skRs(a.mean)}" + (a.upside?.let { " ${skSgn(it)}" } ?: ""), gainColor(a.upside), above = true)),
            Modifier.fillMaxWidth().height(50.dp), band = if (a.low != null && a.high != null) HBand(a.low, a.high, TierC.darkGreen) else null)
        T("${a.n ?: "–"} analyst${if (a.n == 1) "" else "s"} · ${a.src ?: "Yahoo consensus"} · tracked since ${skDay(a.firstTracked)}" +
            (a.lastChange?.let { " · changed ${skDay(it)}" } ?: ""), 11.sp, C.dim, modifier = Modifier.padding(top = 4.dp))
    } else EmptyNote("No analyst target on record.")
    val d7 = lv.item("D7")?.v; val d9 = lv.item("D9")?.v
    val del1 = skFind(d7, "1-month (-?[\\d.]+)%"); val del3 = skFind(d7, "3-month (-?[\\d.]+)%")
    val holders = skNums(d9).firstOrNull(); val hChg = skFind(d9, "\\(([+-]?[\\d.]+)%")
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatTile("Delivery 1M / 3M", if (del1 != null) "${skFx(del1, 0)}%" + (del3?.let { " / ${skFx(it, 0)}%" } ?: "") else "–", Modifier.weight(1f))
        StatTile("Small holders", holders?.let { if (it >= 1000) "${skFx(it / 1000, 1)}k" else fmt(it, 0) } ?: "–", Modifier.weight(1f)) {
            hChg?.let { T(skSgn(it, 0), 12.sp, gainColor(it), FontWeight.SemiBold) }
        }
        StatTile("Inst. bulk buys", short(lv.item("D4")?.v, 10), Modifier.weight(1f))
    }
}

// ---------------------------------------------------------------- Outlook (s08)
/** Latest call: the AlphaBrief of the latest earnings call (owner, 24 Nov 2026: latest call only; full call opens AlphaStreet). */
@Composable
private fun CallCardView(cc: CallCard) {
    val ctx = LocalContext.current
    SectionCard("Latest call", listOfNotNull(cc.call.takeIf { it.isNotBlank() }, skDay(cc.date).takeIf { cc.date.isNotBlank() }).joinToString(" · ")) {
        cc.headline?.let { T(it, 13.sp, C.muted, lineHeight = 18.sp, modifier = Modifier.padding(bottom = 10.dp)) }
        if (cc.metrics.isNotEmpty()) Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            cc.metrics.forEach { m ->
                val dir = m.getOrNull(2).orEmpty()
                val col = when (dir) { "up" -> TierC.lightGreen; "down" -> TierC.lightRed; else -> C.white }
                Column(Modifier.weight(1f).clip(RoundedCornerShape(S.inner)).background(C.chip).padding(horizontal = 8.dp, vertical = 7.dp)) {
                    T(m[0], 11.sp, C.dim, maxLines = 1)
                    T(m[1].replace("INR", "₹").replace(" crore", " cr") + when (dir) { "up" -> " ↑"; "down" -> " ↓"; else -> "" }, 13.sp, col, FontWeight.Medium, maxLines = 1)
                }
            }
        }
        cc.bullets.take(3).forEach { b -> T("· $b", 12.5.sp, C.muted, lineHeight = 18.sp, modifier = Modifier.padding(bottom = 5.dp), maxLines = 4) }
        cc.url?.let { u ->
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.End) {
                T("Full call ↗", 12.sp, C.blue, modifier = Modifier.clickable { openUrl(ctx, u) })
            }
        }
    }
}

@Composable
private fun OutlookBody(st: AppState, sym: String, det: Detail, lv: Level, open: (String?) -> Unit, onAll: () -> Unit) {
    val ctx = LocalContext.current
    val cw = det.v("cwip_pct_ppe")
    val t7 = skNums(lv.item("T7")?.v)
    val rows = listOfNotNull(
        if (lv.item("T4") != null && cw != null) KeyCheck(lv.status("T4"), "Capacity (CWIP)", "${skFx(cw, 0)}%", "pass ≥ 20%", Bullet(cw, 0.0, 50.0, 20.0, unit = "%")) else null,
        if (t7.size >= 5) KeyCheck(lv.status("T7"), "Acceleration", t7.take(3).joinToString("→") { skFx(it, 0) } + "%", "pass: margin ≥ +2 pts",
            Bullet(t7[4] - t7[3], -2.0, 4.0, 2.0, unit = " pts")) else null,
        lv.item("T8")?.let { KeyCheck(lv.status("T8"), "Guidance raised", short(it.v ?: "none", 16), "a raised promise") },
        lv.item("W")?.let { KeyCheck(lv.status("W"), "Industry", lv.wind ?: "–", "median growth") },
    )
    KeyChecksCard(orGeneric(rows, lv), lv.items.size, onAll)
    det.callCard?.let { CallCardView(it) }
    val w = lv.item("W")?.v
    val gNow = skFind(w, "growth (-?[\\d.]+)%"); val gAgo = skFind(w, "a year ago (-?[\\d.]+)%")
    val share = skFind(w, "(\\d+)% growing"); val nco = skFind(w, "(\\d+) companies")
    if (gNow != null) SectionCard("Industry wind", listOfNotNull(nco?.let { "${it.toInt()} companies" }, share?.let { "${it.toInt()}% growing >10%" }).joinToString(" · ")) {
        DivergingBars(listOfNotNull(gAgo?.let { DivRow("A year ago", it, MUTED_BAR, "Median revenue growth") },
            DivRow("Now", gNow, gainColor(gNow), if (gAgo == null) "Median revenue growth" else null)),
            span = max(20.0, max(abs(gNow), abs(gAgo ?: 0.0)) * 1.1), mutedColor = MUTED_BAR)
    }
    // dated triggers: drivers, must-go-right, kill switches, promises (each once), from research
    val r = st.research[sym]
    val scan = r?.scan
    val items = buildList {
        val drivers = r?.drivers.orEmpty().filter { it.due != null }
        drivers.forEach { add(Triple(it.due!!, it.text, TimelineItem("", it.text, "${(it.kind ?: "driver").replaceFirstChar { c -> c.uppercase() }} · driver", C.muted))) }
        scan?.mustGoRight.orEmpty().filter { it.due != null }.forEach { add(Triple(it.due!!, it.text, TimelineItem("", it.text, "Must go right · ${it.check}", TierC.lightGreen))) }
        scan?.killSwitches.orEmpty().filter { it.due != null }.forEach { add(Triple(it.due!!, it.text, TimelineItem("", it.text, "Kill switch · ${it.check}", TierC.red))) }
        val dues = drivers.mapNotNull { it.due }.toSet()
        r?.promises.orEmpty().filter { it.due != null && it.due !in dues }.forEach { add(Triple(it.due!!, it.promise, TimelineItem("", it.promise, "Promise · ${it.call}", C.grey, hollow = true))) }
    }.sortedBy { it.first }.map { (d, _, ti) -> ti.copy(date = skDue(d)) }
    if (items.isNotEmpty()) SectionCard("Dated triggers", "drivers, checks, promises") {
        DotTimeline(listOf(TimelineItem(skDay(skToday().toString()), "Today", today = true)) + items)
    } else EmptyNote(if (lv.researched) "No dated trigger in filings or research yet." else "Dated triggers appear once Claude researches this stock.")
    Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
        lv.risks.forEachIndexed { i, rk ->
            if (i > 0) HLineDivider()
            val fig = rk.k?.let { k -> det.v(k)?.let { v -> if (k.endsWith("_days")) "${fmt(v, 0)} days" else skFx(v, 1) } }
            Row(Modifier.fillMaxWidth().clickable { if (rk.k != null) open(rk.k) else rk.src?.takeIf { it.startsWith("http") }?.let { openUrl(ctx, it) } }.padding(vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).clip(CircleShape).background(C.amber)); Spacer(Modifier.width(8.dp))
                T("Risk: " + rk.text.replaceFirstChar { it.lowercase() }, 13.sp, modifier = Modifier.weight(1f), maxLines = 2, lineHeight = 17.sp)
                fig?.let { T(it, 13.sp, weight = FontWeight.Bold, modifier = Modifier.padding(start = 8.dp), maxLines = 1) }
            }
        }
        var trig by remember { mutableStateOf(false) }
        ToggleRow("Live triggers", "${lv.triggers.size}", trig, { trig = !trig }, divider = lv.risks.isNotEmpty())
        if (trig) {
            if (lv.triggers.isEmpty()) T(if (lv.researched) "No live trigger found in filings or research." else "Computed triggers only until Claude researches this stock.", 12.sp, C.dim)
            lv.triggers.forEach { tr ->
                Column(Modifier.padding(vertical = 4.dp)) { T(tr.n, 13.sp, weight = if (tr.strong) FontWeight.SemiBold else FontWeight.Medium); tr.v?.let { T(it, 12.sp, C.dim) } }
            }
        }
        var bbb by remember { mutableStateOf(false) }
        val scen = scan?.scenarios.orEmpty()
        ToggleRow("Bull · Base · Bear", if (scen.isEmpty()) "no price scenarios yet" else "${scen.size} scenarios", bbb, { bbb = !bbb })
        if (bbb && scen.isNotEmpty()) scen.forEach { sc ->
            val col = when (sc.name.lowercase()) { "bull" -> TierC.lightGreen; "bear" -> TierC.lightRed; else -> C.muted }
            Column(Modifier.padding(vertical = 6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    T(sc.name, 14.sp, col, FontWeight.SemiBold, modifier = Modifier.weight(1f)); T(skRs(sc.price), 14.sp, weight = FontWeight.Bold); T(" ${skSgn(sc.pct)}", 12.sp, col)
                }
                if (sc.theory.isNotBlank()) T(sc.theory, 12.sp, C.muted, lineHeight = 17.sp)
                T(sc.formula, 11.sp, C.dim, lineHeight = 15.sp)
            }
        }
        if (scan != null && (scan.checklist.isNotEmpty() || scan.derived.isNotEmpty())) {
            var more by remember { mutableStateOf(false) }
            ToggleRow("Research checklist and derived figures", "", more, { more = !more })
            if (more) ResearchLists(scan, nested = true)
        }
    }
}

// ---------------------------------------------------------------- every check of a level (sheet)
@Composable
fun AllChecksSheet(st: AppState, i: Int, lv: Level, onDismiss: () -> Unit, open: (String?) -> Unit) {
    val k = LEVELS[i]
    val pend = lv.items.count { it.note == PENDING }; val na = lv.items.count { it.note == "not applicable" }; val checked = lv.items.count { it.m != null }
    BottomSheet(onDismiss, st.levelName(k), aside = "${lv.items.size} checks") {
        T(LEVEL_RULES[i], 12.sp, C.dim, lineHeight = 17.sp)
        T("Scored on $checked of ${lv.items.size}" + (if (pend > 0) " · $pend sources not connected yet" else "") + (if (na > 0) " · $na not applicable" else "") +
            (lv.covPct?.let { " · coverage $it%" } ?: ""), 12.sp, C.muted, modifier = Modifier.padding(top = 6.dp))
        var how by remember { mutableStateOf(false) }
        ToggleRow("How the score works", "", how, { how = !how }, Modifier.padding(top = 6.dp))
        if (how) T(if (k in setOf("mgmt", "mom"))
                "Score = points earned ÷ points available from the checks that have data (each check shows its points, e.g. 10/15). " +
                "Checks without data or not connected yet are left out, so they count neither for nor against. Coverage = share of the full 100 points that had data; " +
                "under 60% the tier stays grey (not enough data)."
            else
                "Score = Pass counts 2, Partly 1, Miss 0, divided by the maximum for the checks that have data. " +
                "Checks marked n/a (not checked or not connected yet) are left out, so 100 means every check with data passed, not that every check was done. " +
                "If fewer than 60% of the connected checks have data, the tier stays grey.",
            12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(bottom = 6.dp))
        HLineDivider()
        lv.items.forEach { item -> CheckItemRow(item) { open(item.k) } }
    }
}
