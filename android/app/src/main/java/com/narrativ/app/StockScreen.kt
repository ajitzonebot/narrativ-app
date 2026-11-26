package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.TrendingDown
import androidx.compose.material.icons.automirrored.rounded.TrendingUp
import androidx.compose.material.icons.rounded.AutoStories
import androidx.compose.material.icons.rounded.CurrencyRupee
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.RocketLaunch
import androidx.compose.material.icons.rounded.Storefront
import androidx.compose.material.icons.rounded.WarningAmber
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

/*
 * Stock page (redesign, mockups s01..s11 in scratchpad/mock/out_stock): header with code, name and the watch heart
 * (plus feedback), price on the Summary tab, nine pill tabs with tier dots, one pager.
 * Summary: SummaryTab.kt. Level tabs and the Promises sheet: LevelTabs.kt. Filings and the Summary sheets: StockScreens2.kt.
 */
val STOCK_TABS = listOf("Summary") + LEVEL_SHORT + "Filings"

@Composable
fun StockScreen(st: AppState, sym: String, startTab: Int = 0) {
    val p = st.pick(sym)
    // loading vs missing: placeholders until each load attempt has finished, only then "not in today's data" / "no chart"
    var detLoaded by remember(sym) { mutableStateOf(false) }
    var chartLoaded by remember(sym) { mutableStateOf(false) }
    val det by produceState<Detail?>(null, sym) {
        try {
            st.cachedDetail(sym)?.let { value = it }  // instant from the phone copy
            st.detail(sym)?.let { value = it }        // then today's data
        } finally { detLoaded = true }
    }
    // held / phone copy at once (no placeholder while the network answers), then the network copy if it changed
    val chart by produceState(cachedChart(sym), sym) {
        value = cachedChart(sym)  // another symbol on the same screen: never keep the previous stock's chart
        try { loadChart(st, sym) { value = it; chartLoaded = true } } finally { chartLoaded = true }
    }
    val code = p?.c ?: sym.substringBeforeLast(".")
    // the company name only; never the industry in its place (that is under the price)
    val name = (p?.n ?: "").removeSuffix(" Limited").removeSuffix(" Ltd.").removeSuffix(" Ltd")
    val pager = rememberPagerState(initialPage = startTab.coerceIn(0, STOCK_TABS.lastIndex)) { STOCK_TABS.size }
    val scope = rememberCoroutineScope()
    var narrativOpen by remember(sym) { mutableStateOf(false) }
    val tabs = STOCK_TABS.mapIndexed { i, t ->
        TabSpec(t, if (i in 1..LEVEL_SHORT.size && (p != null || det != null)) tierColor(det?.levels?.get(LEVELS[i - 1])?.t ?: p?.tier(i - 1) ?: 0) else null)
    }
    Column(Modifier.fillMaxSize().background(C.bg).pageBackground()) {
        TopBar(st, code, "Stock · $code · ${STOCK_TABS[pager.currentPage]}", subtitle = name.ifBlank { null }) {
            val on = sym in st.watch
            IconBtn(if (on) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder, if (on) "Remove from watchlist" else "Add to watchlist",
                tint = if (on) C.red else C.white) { st.toggleWatch(sym) }
        }
        val narr = det?.narrativ
        if (pager.currentPage == 0 && p != null) PriceBlock(p, if (narr != null) ({ narrativOpen = true }) else null)
        if (narrativOpen && narr != null) NarrativStorySheet(code, narr) { narrativOpen = false }
        TabStrip(tabs, pager.currentPage, { i -> scope.launch { pager.animateScrollToPage(i) } }, Modifier.padding(top = 8.dp, bottom = 6.dp))
        HorizontalPager(pager, Modifier.fillMaxWidth().weight(1f), beyondViewportPageCount = 1) { page ->
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 110.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                when {
                    p == null && det == null && !detLoaded -> {
                        Card(Modifier.fillMaxWidth()) {
                            Skel(160.dp, 18.dp); Spacer(Modifier.height(10.dp)); Skel(null, 12.dp); Spacer(Modifier.height(6.dp)); Skel(220.dp, 12.dp)
                        }
                        Card(Modifier.fillMaxWidth()) { Skel(null, 150.dp) }
                    }
                    p == null && det == null -> {
                        Card(Modifier.fillMaxWidth()) {
                            T("Not in today's data", 15.sp, weight = FontWeight.SemiBold)
                            st.memory?.stocks?.firstOrNull { it.symbol == sym }?.dropReason?.let { T(it, 13.sp, C.dim) }
                        }
                        var research by remember { mutableStateOf(false) }
                        Card(Modifier.fillMaxWidth(), pad = S.cardPad) { LinkRow("Narrativ.ai's research") { research = true } }
                        if (research) ResearchSheet(st, sym, null) { research = false }
                    }
                    page == 0 -> SummaryTab(st, sym, p, det, chart, detLoaded, chartLoaded) { i -> scope.launch { pager.animateScrollToPage(i) } }
                    page == STOCK_TABS.lastIndex -> FilingsTab(det)
                    else -> LevelTab(st, sym, p, det, chart, page - 1)
                }
            }
        }
    }
}

/** Price, change today, industry and market cap (Summary tab only); the Narrativ pill on the right, under feedback and heart. */
@Composable
private fun PriceBlock(p: P, onNarrativ: (() -> Unit)? = null) {
  Row(Modifier.fillMaxWidth().padding(end = 16.dp), verticalAlignment = Alignment.CenterVertically) {
    Column(Modifier.weight(1f).padding(start = 16.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            T("₹${skFx(p.p, 2)}", 30.sp, weight = FontWeight.Bold, maxLines = 1)
            Spacer(Modifier.width(8.dp))
            T(skSgn(p.d1, 2), 15.sp, gainColor(p.d1), modifier = Modifier.padding(bottom = 5.dp), maxLines = 1)
            T(" today", 15.sp, C.muted, modifier = Modifier.padding(bottom = 5.dp), maxLines = 1)
        }
        T(listOfNotNull(p.i, p.mc?.let { "₹${fmt(it, 0)} cr" }).joinToString(" · "), 12.sp, C.dim, maxLines = 1)
    }
    if (onNarrativ != null) {
        Spacer(Modifier.width(S.s))
        NarrativButton(onNarrativ)
    }
  }
}

/** Pill button that opens the Narrativ story sheet. */
@Composable
private fun NarrativButton(onClick: () -> Unit) {
    Row(Modifier.height(34.dp).clip(CircleShape).background(C.teal.copy(alpha = 0.13f)).border(1.dp, C.teal, CircleShape)
        .clickable(onClick = onClick).padding(horizontal = S.m), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Icon(Icons.Rounded.AutoStories, null, tint = C.blue, modifier = Modifier.size(16.dp))
        T("Narrativ", 13.sp, C.blue, FontWeight.SemiBold, maxLines = 1)
    }
}

private val NARR_MONTHS = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

/** "2030-03-31" -> "Mar 2030"; null when it doesn't parse. */
private fun narrDue(due: String?): String? {
    val parts = due?.split("-") ?: return null
    val y = parts.getOrNull(0)?.toIntOrNull() ?: return null
    val m = parts.getOrNull(1)?.toIntOrNull()?.takeIf { it in 1..12 } ?: return "$y"
    return "${NARR_MONTHS[m - 1]} $y"
}

/** The one-screen Narrativ sheet: compact rows split by thin lines, each a small heading with an icon and a short body. */
@Composable
private fun NarrativStorySheet(code: String, n: NarrativSheet, onDismiss: () -> Unit) {
    val name = code.removeSuffix(".NS").removeSuffix(".BO")
    BottomSheet(onDismiss, "$name's Narrativ") {
        var first = true
        n.what?.takeIf { it.isNotBlank() }?.let { t -> NarrSep(first); first = false; NarrRow(Icons.Rounded.Storefront, "What they do", C.dim) { NarrBody(t) } }
        n.money?.takeIf { it.isNotBlank() }?.let { t -> NarrSep(first); first = false; NarrRow(Icons.Rounded.CurrencyRupee, "How they make money", C.dim) { NarrBody(t) } }
        n.going?.takeIf { it.text.isNotBlank() }?.let { g ->
            val bad = g.tone == "bad"
            NarrSep(first); first = false
            NarrRow(if (bad) Icons.AutoMirrored.Rounded.TrendingDown else Icons.AutoMirrored.Rounded.TrendingUp, "How it's going",
                if (bad) TierC.lightRed else TierC.lightGreen) { NarrBody(g.text) }
        }
        val plans = n.plans.filter { it.text.isNotBlank() }.take(2)
        if (plans.isNotEmpty()) {
            NarrSep(first); first = false
            NarrRow(Icons.Rounded.RocketLaunch, "Plans to grow", TierC.lightGreen) {
                plans.forEach { pl ->
                    val due = narrDue(pl.due)?.takeIf { d -> !pl.text.contains(d, ignoreCase = true) }
                    if (due == null) NarrBody(pl.text)
                    else Text(buildAnnotatedString {
                        append(pl.text)
                        withStyle(SpanStyle(color = C.dim)) { append(" (by $due)") }
                    }, color = C.white, fontSize = 14.sp, lineHeight = 20.sp)
                }
            }
        }
        val risks = n.risks.filter { it.isNotBlank() }.take(2)
        if (risks.isNotEmpty()) {
            NarrSep(first); first = false
            NarrRow(Icons.Rounded.WarningAmber, "What could go wrong", TierC.lightRed) { risks.forEach { NarrBody(it) } }
        }
        n.oneLine?.takeIf { it.isNotBlank() }?.let { t ->
            NarrSep(first); first = false
            NarrRow(Icons.Rounded.Lightbulb, "In one line", TierC.yellow) { T(t, 15.sp, C.white, FontWeight.SemiBold, lineHeight = 20.sp) }
        }
    }
}

@Composable
private fun NarrRow(icon: ImageVector, heading: String, color: Color, body: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = S.s), verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(icon, null, tint = color, modifier = Modifier.size(14.dp))
            T(heading, 12.sp, color, FontWeight.SemiBold, maxLines = 1)
        }
        body()
    }
}

/** Thin line between rows (none above the first). */
@Composable
private fun NarrSep(first: Boolean) { if (!first) HorizontalDivider(thickness = 1.dp, color = C.line) }

@Composable
private fun NarrBody(text: String) = T(text, 14.sp, C.white, lineHeight = 20.sp)

// ---------------------------------------------------------------- ratios (All ratios sheet)
data class Ratio(val label: String, val key: String, val unit: String = "")

fun keyRatios(d: Detail): List<Pair<Ratio, String>> {
    val lender = d.stock.kind in setOf("bank", "nbfc", "insurance")
    val vk = d.levels["val"]?.let { lv -> lv.mkey ?: METRIC_KEY_OF[lv.metric] }
    val list = if (lender) listOf(Ratio("P/B", "pb", "x"), Ratio("ROE", "roe_pct", "%"), Ratio("ROA", "roa_pct", "%"), Ratio("Gross NPA", "gnpa_pct_advances", "%"),
        Ratio("P/E", "pe", "x"), Ratio("Profit growth (4Q)", "pat_ttm_growth_pct", "%"), Ratio(METRIC_NAMES.getValue("rev_cagr_3y_pct"), "rev_cagr_3y_pct", "%"), Ratio("Market cap", "mcap_cr", " cr"))
    else listOfNotNull(vk?.takeIf { it != "pe" }?.let { Ratio(METRIC_NAMES[it] ?: it, it, "x") }, Ratio("P/E", "pe", "x"), Ratio(METRIC_NAMES.getValue("roce_3y_avg_pct"), "roce_3y_avg_pct", "%"),
        Ratio(METRIC_NAMES.getValue("rev_cagr_3y_pct"), "rev_cagr_3y_pct", "%"), Ratio("EBITDA margin", "ebitda_margin_pct", "%"), Ratio("Net debt / EBITDA", "net_debt_ebitda", "x"),
        Ratio("Cash conversion", "cfo_to_ebitda_pct", "%"), Ratio("Market cap", "mcap_cr", " cr")).take(8)
    return list.map { r ->
        val m = d.m(r.key)
        r to when {
            m == null || m.v == null -> "–"
            m.nm -> "n/m"
            r.key == "mcap_cr" -> "₹${fmt(m.v, 0)} cr"
            r.unit == "%" -> "${skFx(m.v, 1)}%"
            r.unit == "x" -> mult(m.v)
            else -> skFx(m.v, 1)
        }
    }
}

val METRIC_KEY_OF = mapOf("P/B" to "pb", "EV / mid-cycle EBITDA" to "ev_midcycle_ebitda", "EV / EBITDA" to "ev_ebitda", "EV / sales" to "ev_sales", "P/E" to "pe")

// ---------------------------------------------------------------- shared small pieces (used across the app)
@Composable
fun KV(k: String, v: String) = Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
    T(k, 14.sp, C.grey); T(v, 14.sp, weight = FontWeight.SemiBold)
}

val STATUS_LABEL = mapOf("delivered" to "Delivered", "beat" to "Beat", "partly" to "Partly", "missed" to "Missed", "delayed" to "Delayed",
    "pending" to "Pending", "raised" to "Guidance raised", "off_track" to "Off track", "unverified" to "Not verified")
val UPDATE_LABEL = mapOf("actual" to "Actual", "raised" to "Raised", "reaffirmed" to "Reaffirmed", "lowered" to "Lowered", "delayed" to "Delayed")

@Composable
fun Quote(ctx: android.content.Context, q: String, src: String) {
    Row(Modifier.padding(top = 5.dp).clickable { openUrl(ctx, src) }) {
        T("“" + (if (q.length > 140) q.take(140) + "…" else q) + "”  ", 11.sp, C.dim, lineHeight = 15.sp,
            modifier = Modifier.weight(1f, fill = false))
        T("source", 11.sp, C.blue)
    }
}

fun shortMonth(iso: String): String = runCatching {
    val d = java.time.LocalDate.parse(iso.take(10))
    d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH) + " '" + (d.year % 100).toString().padStart(2, '0')
}.getOrDefault(iso.take(7))
