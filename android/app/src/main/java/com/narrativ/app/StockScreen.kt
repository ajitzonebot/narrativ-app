package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
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
    val det by produceState<Detail?>(null, sym) {
        st.cachedDetail(sym)?.let { value = it }  // instant from the phone copy
        st.detail(sym)?.let { value = it }        // then today's data
    }
    val chart by produceState<Chart?>(null, sym) { value = loadChart(st, sym) }
    val code = p?.c ?: sym.substringBeforeLast(".")
    val name = (p?.n ?: det?.stock?.industry ?: "").removeSuffix(" Limited").removeSuffix(" Ltd.").removeSuffix(" Ltd")
    val pager = rememberPagerState(initialPage = startTab.coerceIn(0, STOCK_TABS.lastIndex)) { STOCK_TABS.size }
    val scope = rememberCoroutineScope()
    val tabs = STOCK_TABS.mapIndexed { i, t ->
        TabSpec(t, if (i in 1..LEVEL_SHORT.size && (p != null || det != null)) tierColor(det?.levels?.get(LEVELS[i - 1])?.t ?: p?.tier(i - 1) ?: 0) else null)
    }
    Column(Modifier.fillMaxSize().background(C.bg).background(C.screen)) {
        TopBar(st, code, "Stock · $code · ${STOCK_TABS[pager.currentPage]}", subtitle = name.ifBlank { null }) {
            val on = sym in st.watch
            IconBtn(if (on) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder, if (on) "Remove from watchlist" else "Add to watchlist",
                tint = if (on) C.red else C.white) { st.toggleWatch(sym) }
        }
        if (pager.currentPage == 0 && p != null) PriceBlock(p)
        TabStrip(tabs, pager.currentPage, { i -> scope.launch { pager.animateScrollToPage(i) } }, Modifier.padding(top = 8.dp, bottom = 6.dp))
        HorizontalPager(pager, Modifier.fillMaxWidth().weight(1f), beyondViewportPageCount = 1) { page ->
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 110.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                when {
                    p == null && det == null -> {
                        Card(Modifier.fillMaxWidth()) {
                            T("Not in today's data", 15.sp, weight = FontWeight.SemiBold)
                            st.memory?.stocks?.firstOrNull { it.symbol == sym }?.dropReason?.let { T(it, 13.sp, C.dim) }
                        }
                        var research by remember { mutableStateOf(false) }
                        Card(Modifier.fillMaxWidth(), pad = 14.dp) { LinkRow("Claude's research") { research = true } }
                        if (research) ResearchSheet(st, sym, null) { research = false }
                    }
                    page == 0 -> SummaryTab(st, sym, p, det, chart) { i -> scope.launch { pager.animateScrollToPage(i) } }
                    page == STOCK_TABS.lastIndex -> FilingsTab(det)
                    else -> LevelTab(st, sym, p, det, chart, page - 1)
                }
            }
        }
    }
}

/** Price, change today, industry and market cap (Summary tab only). */
@Composable
private fun PriceBlock(p: P) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            T("₹${skFx(p.p, 2)}", 30.sp, weight = FontWeight.Bold, maxLines = 1)
            Spacer(Modifier.width(8.dp))
            T(skSgn(p.d1, 2), 15.sp, gainColor(p.d1), modifier = Modifier.padding(bottom = 5.dp), maxLines = 1)
            T(" today", 15.sp, C.muted, modifier = Modifier.padding(bottom = 5.dp), maxLines = 1)
        }
        T(listOfNotNull(p.i, p.mc?.let { "₹${fmt(it, 0)} cr" }).joinToString(" · "), 12.sp, C.dim, maxLines = 1)
    }
}

// ---------------------------------------------------------------- ratios (All ratios sheet)
data class Ratio(val label: String, val key: String, val unit: String = "")

fun keyRatios(d: Detail): List<Pair<Ratio, String>> {
    val lender = d.stock.kind in setOf("bank", "nbfc", "insurance")
    val vk = d.levels["val"]?.let { lv -> lv.mkey ?: METRIC_KEY_OF[lv.metric] }
    val list = if (lender) listOf(Ratio("P/B", "pb", "x"), Ratio("ROE", "roe_pct", "%"), Ratio("ROA", "roa_pct", "%"), Ratio("Gross NPA", "gnpa_pct_advances", "%"),
        Ratio("P/E", "pe", "x"), Ratio("Profit growth (4Q)", "pat_ttm_growth_pct", "%"), Ratio("Revenue growth (yearly)", "rev_cagr_3y_pct", "%"), Ratio("Market cap", "mcap_cr", " cr"))
    else listOfNotNull(vk?.takeIf { it != "pe" }?.let { Ratio(METRIC_NAMES[it] ?: it, it, "x") }, Ratio("P/E", "pe", "x"), Ratio("ROCE (avg of years)", "roce_3y_avg_pct", "%"),
        Ratio("Revenue growth (yearly)", "rev_cagr_3y_pct", "%"), Ratio("EBITDA margin", "ebitda_margin_pct", "%"), Ratio("Net debt / EBITDA", "net_debt_ebitda", "x"),
        Ratio("Cash conversion", "cfo_to_ebitda_pct", "%"), Ratio("Market cap", "mcap_cr", " cr")).take(8)
    return list.map { r ->
        val m = d.m(r.key)
        r to when {
            m == null || m.v == null -> "–"
            m.nm -> "n/m"
            r.key == "mcap_cr" -> "₹${fmt(m.v, 0)} cr"
            r.unit == "%" -> "${fmt(m.v, 1)}%"
            else -> fmt(m.v, if (kotlin.math.abs(m.v) < 10) 2 else 1)
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
