@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Sort
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer

/**
 * Screener filter. minTier[i] = 0 means any; otherwise the stock's tier must be 1..minTier[i].
 * research: "Any" / "Researched" (in research.json or with a verification state) / "Verified" (verification passed).
 */
@Serializable
data class Filt(
    val name: String = "", val minTier: List<Int> = List(7) { 0 }, val disc: List<Int> = emptyList(), val setup: String = "Any",
    val mcap: String = "Any", val industry: String = "", val includeGrey: Boolean = true, val showRemoved: Boolean = false,
    val verdict: String? = null, val turnaround: Boolean = false, val sort: String = "Score", val q: String = "", val bq: Boolean = false,
    val dc: String? = null, val syms: List<String> = emptyList(), val research: String = "Any",
    /** true for an industry opened from a list (ind: preset): exact name, so the count matches the list; the typed "Industry contains" field stays a substring. */
    val industryExact: Boolean = false,
) {
    /** How many filters beyond the category are set (shown on the Filters button). */
    fun active(): Int = minTier.count { it != 0 } + (if (disc.isNotEmpty()) 1 else 0) + (if (setup != "Any") 1 else 0) + (if (mcap != "Any") 1 else 0) +
        (if (industry.isNotBlank()) 1 else 0) + (if (!includeGrey) 1 else 0) + (if (showRemoved) 1 else 0) + (if (turnaround) 1 else 0)

    /** Same filter as [o] apart from name, sort, search text and the chips outside the sheet (preset highlight). */
    fun sameAs(o: Filt): Boolean = copy(name = "", sort = "Score", q = "", research = "Any", dc = null, syms = emptyList()) ==
        o.copy(name = "", sort = "Score", q = "", research = "Any", dc = null, syms = emptyList())
}

val PRESETS = listOf(
    Filt("Top tiers", verdict = "Prime candidate"),
    Filt("Quality + cheap", minTier = listOf(0, 2, 2, 0, 0, 0, 0), includeGrey = false),
    Filt("Under-owned quality", minTier = listOf(0, 3, 0, 0, 0, 0, 0), disc = listOf(1, 2), includeGrey = false),
    Filt("Turnaround", turnaround = true),
    Filt("Beaten-up quality", bq = true),
)
val MCAP = listOf("Any", "< 1k cr", "1k–5k cr", "5k–20k cr", "> 20k cr")
val SETUPS = listOf("Any", "Breakout", "Pullback", "Base", "No setup")
val SORTS = listOf("Score", "Quality", "Momentum", "Change today", "Market cap")
private val RESEARCH = listOf("Any", "Researched", "Verified")

/** [researched] tells whether Claude has research on a stock (AppState.researched); only the "Researched" filter uses it. */
fun Filt.match(p: P, researched: (P) -> Boolean = { it.vf != null }): Boolean {
    if (p.out != null && !showRemoved) return false
    if (q.isNotBlank() && !"${p.c} ${p.n} ${p.i ?: ""}".contains(q.trim(), true)) return false
    if (research == "Verified" && !p.verified()) return false
    if (research == "Researched" && !researched(p)) return false
    if (verdict != null && p.vd != verdict) return false
    if (turnaround && !p.turn) return false
    if (bq && p.bq == null) return false
    if (syms.isNotEmpty() && p.s !in syms) return false
    if (dc != null && (p.dc ?: "Not rated") != dc) return false
    minTier.forEachIndexed { i, m ->
        if (m == 0 || i == 5) return@forEachIndexed
        val t = p.tier(i)
        if (t == 0) { if (!includeGrey) return false } else if (t > m) return false
    }
    if (disc.isNotEmpty() && p.tier(5) !in disc) return false
    if (setup != "Any" && p.su != setup) return false
    val mc = p.mc
    if (mcap != "Any") {
        if (mc == null) return false
        val ok = when (mcap) { "< 1k cr" -> mc < 1000; "1k–5k cr" -> mc in 1000.0..5000.0; "5k–20k cr" -> mc in 5000.0..20000.0; else -> mc > 20000 }
        if (!ok) return false
    }
    if (industry.isNotBlank() && !(if (industryExact) (p.i ?: "").equals(industry.trim(), true) else (p.i ?: "").contains(industry.trim(), true))) return false
    return true
}

private fun Filt.sorted(l: List<P>): List<P> = when (sort) {
    "Quality" -> l.sortedByDescending { it.sc.getOrNull(1) ?: -1 }
    "Momentum" -> l.sortedByDescending { it.sc.getOrNull(4) ?: -1 }
    "Change today" -> l.sortedByDescending { it.d1 ?: -99.0 }
    "Market cap" -> l.sortedByDescending { it.mc ?: -1.0 }
    else -> l.sortedByDescending { it.pr }
}

/** Filter a preset string opens with (Home Explore chips, Market, Search, quadrant list). Plain Stocks tab: verified only. */
fun presetFilt(preset: String?, pf: PicksFile): Filt = when {
    preset == null -> Filt()  // all stocks; "Verified only" is one tap (verified Buys are pending re-review after the 20 Nov rules)
    preset.startsWith("v:") -> Filt(verdict = preset.removePrefix("v:"))
    preset.startsWith("ind:") -> Filt(industry = preset.removePrefix("ind:"), industryExact = true)
    preset.startsWith("q:") -> Filt(q = preset.removePrefix("q:"))
    preset == "bq" -> Filt(bq = true)
    preset.startsWith("syms:") -> preset.removePrefix("syms:").let { s ->  // "syms:Title|A,B" or "syms:A,B"
        val title = s.substringBefore("|", "").ifBlank { "Selected stocks" }
        Filt(name = title, syms = s.substringAfter("|").split(",").filter { it.isNotBlank() }.ifEmpty { listOf("-") })
    }
    preset.startsWith("d:") -> Filt(dc = preset.removePrefix("d:"), showRemoved = preset.endsWith("Sell"))
    preset.startsWith("sec:") -> preset.removePrefix("sec:").let { sec ->  // feedback #68: a sector opens its stocks
        Filt(name = "$sec sector", syms = pf.picks.filter { p -> p.i?.let { SECTOR_OF[it] } == sec }.map { it.s }.ifEmpty { listOf("-") }) }
    else -> Filt()
}

/**
 * Stocks (mockup h06): search, "Verified only" and decision chips with counts, research coverage bar, count with Sort and
 * Filters (sheet, h07), rows (code, Claude tick, decision, setup · industry, seven level dots, sparkline, price, day move),
 * today's funnel as bars.
 */
@Composable
fun ScreenerScreen(st: AppState, preset: String?) {
    val pf = st.picks ?: return
    val ctx = LocalContext.current
    val prefs = remember { ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE) }
    var saved by remember { mutableStateOf(runCatching { json.decodeFromString(ListSerializer(Filt.serializer()), prefs.getString("filters", "[]")!!) }.getOrDefault(emptyList())) }
    var f by remember(preset) { mutableStateOf(presetFilt(preset, pf)) }
    var sheet by remember { mutableStateOf(false) }
    var sortMenu by remember { mutableStateOf(false) }
    var limit by remember { mutableStateOf(60) }
    val researched: (P) -> Boolean = { st.researched(it) }
    val res = remember(f, pf, st.research) { f.sorted(pf.picks.filter { f.match(it, researched) }) }
    val nVer = remember(pf) { pf.picks.count { it.verified() } }
    val nRes = remember(pf, st.research) { pf.picks.count { st.researched(it) } }
    // chip counts within the current list (search, preset, syms, sheet filters), each before its own filter
    val dec = remember(f, pf, st.research) {
        val base = pf.picks.filter { f.copy(dc = null).match(it, researched) }
        val withRemoved = pf.picks.filter { f.copy(dc = null, showRemoved = true).match(it, researched) }  // a Sell chip also shows removed stocks
        DECISION_ORDER.associateWith { d -> (if (d.endsWith("Sell")) withRemoved else base).count { (it.dc ?: "Not rated") == d } }
    }
    val nVerList = remember(f, pf, st.research) { pf.picks.count { it.verified() && f.copy(research = "Any").match(it, researched) } }
    val nLive = remember(pf) { pf.picks.count { it.out == null } }
    LazyColumn(Modifier.fillMaxSize().pageBackground(), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, "Stocks", back = st.stack.size > 1, big = st.stack.size == 1) }
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth().clip(rr(14.dp)).background(C.hi.copy(alpha = 0.07f))
                .padding(horizontal = 12.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Search, null, tint = C.dim, modifier = Modifier.size(20.dp)); Spacer(Modifier.width(8.dp))
                BasicTextField(f.q, { f = f.copy(q = it); limit = 60 }, singleLine = true, textStyle = TextStyle(color = C.white, fontSize = 15.sp), cursorBrush = SolidColor(C.blue),
                    modifier = Modifier.weight(1f),
                    decorationBox = { inner -> if (f.q.isEmpty()) T("Search ${fmt(nLive.toDouble(), 0)} stocks", 15.sp, C.dim); inner() })
                if (f.q.isNotEmpty()) Icon(Icons.Rounded.Close, "Clear", tint = C.dim, modifier = Modifier.clickable { f = f.copy(q = "") }.size(20.dp))
            }
        }
        item {
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                val on = f.research == "Verified"
                ToggleChip("Verified only", on, { f = f.copy(research = if (on) "Any" else "Verified"); limit = 60 }, count = nVerList, accent = TierC.lightGreen, icon = Icons.Rounded.Check)
                Box(Modifier.padding(horizontal = 2.dp).size(1.dp, 22.dp).background(C.line))
                DECISION_ORDER.filter { (dec[it] ?: 0) > 0 || f.dc == it }.forEach { d ->
                    ToggleChip(d, f.dc == d, { f = f.copy(dc = if (f.dc == d) null else d, showRemoved = if (f.dc == d) f.showRemoved else d.endsWith("Sell") || f.showRemoved); limit = 60 },
                        count = dec[d], dot = decisionColor(d), accent = decisionColor(d))
                }
            }
        }
        if (nRes > 0) item {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
                SegmentedBar(listOf(Segment(nVer.toDouble(), TierC.lightGreen), Segment((nRes - nVer).coerceAtLeast(0).toDouble(), C.hi.copy(alpha = 0.15f))),
                    height = 6.dp, legend = SegLegend.None)
                Row(Modifier.padding(top = 5.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    listOf(Triple("Verified by Narrativ.ai", nVer, TierC.lightGreen), Triple("Researched, not verified", nRes - nVer, C.hi.copy(alpha = 0.15f))).forEach { (k, n, c) ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(8.dp).clip(rr(2.dp)).background(c)); T(" $k ", 11.sp, C.dim, maxLines = 1); T("$n", 11.sp, weight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }
        item {
            // what narrows the list besides the sheet: preset list, verdict, industry, Beaten-up (tap to clear)
            val tags = listOfNotNull(
                f.syms.takeIf { it.isNotEmpty() }?.let { (f.name.ifBlank { "Selected stocks" }) to { f = f.copy(syms = emptyList(), name = "") } },
                f.verdict?.let { it to { f = f.copy(verdict = null) } },
                f.bq.takeIf { it }?.let { "Beaten-up quality" to { f = f.copy(bq = false) } },
                f.industry.takeIf { it.isNotBlank() }?.let { "Industry: $it" to { f = f.copy(industry = "") } })
            if (tags.isNotEmpty()) Row(Modifier.horizontalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                tags.forEach { (label, clear) -> ToggleChip(label, true, clear, icon = Icons.Rounded.Close) }
            }
        }
        item {
            Row(Modifier.padding(start = 18.dp, end = 16.dp, top = 12.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                T("${fmt(res.size.toDouble(), 0)} stocks", 17.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f), maxLines = 1)
                Box {
                    CtlButton(Icons.AutoMirrored.Rounded.Sort, f.sort) { sortMenu = true }
                    DropdownMenu(sortMenu, { sortMenu = false }, containerColor = C.chip) {
                        SORTS.forEach { s -> DropdownMenuItem(text = { Text(s, color = if (s == f.sort) C.blue else C.white, fontSize = 14.sp) }, onClick = { f = f.copy(sort = s); sortMenu = false }) }
                    }
                }
                val n = f.active()
                CtlButton(Icons.Rounded.Tune, if (n > 0) "Filters · $n" else "Filters", n > 0) { sheet = true }
            }
        }
        if (res.isEmpty()) item { Empty(if (f.research == "Verified") "No verified stock matches. Turn off “Verified only” to see every stock." else "No stock matches these filters.") }
        val shown = res.take(limit)
        itemsIndexed(shown, key = { _, p -> p.s }) { k, p ->
            val r = 20.dp
            val shape = RoundedCornerShape(topStart = if (k == 0) r else 0.dp, topEnd = if (k == 0) r else 0.dp,
                bottomStart = if (k == shown.lastIndex) r else 0.dp, bottomEnd = if (k == shown.lastIndex) r else 0.dp)
            // Paper: rows sit on the paper under a rule (no panel), like the mock-up
            Column(Modifier.padding(horizontal = 16.dp).fillMaxWidth().then(if (Look.paper) Modifier else Modifier.clip(shape).background(C.card))) {
                if (Look.paper && k == 0) Box(Modifier.fillMaxWidth().height(1.dp).background(C.white))
                StockRow(st, p)
                if (k < shown.lastIndex) HLineDivider(Modifier.padding(horizontal = S.cardPad))
            }
        }
        if (res.size > limit) item {
            MoreLink("Show more (${res.size - limit})", Modifier.padding(horizontal = 18.dp, vertical = 8.dp)) { limit += 60 }
        }
        item { FunnelCard(pf.funnel) }
    }
    if (sheet) FilterSheet(st, f, saved, onDismiss = { sheet = false }, onApply = { f = it; limit = 60; sheet = false }) { nf ->
        saved = saved + nf
        prefs.edit().putString("filters", json.encodeToString(ListSerializer(Filt.serializer()), saved)).apply()
        st.toast = "Saved as ${nf.name}"
    }
}

@Composable
private fun CtlButton(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, on: Boolean = false, onClick: () -> Unit) {
    Row(Modifier.clip(rr(16.dp)).background(if (on) C.teal.copy(alpha = 0.18f) else C.chip)
        .then(if (on) Modifier.border(1.dp, C.teal, rr(16.dp)) else Modifier).clickable(onClick = onClick)
        .padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Icon(icon, null, tint = C.white, modifier = Modifier.size(16.dp)); T(label, 13.sp, maxLines = 1)
    }
}

/** One stock in the list: code, Claude tick, decision; setup · industry (or why it was removed); seven level dots; sparkline, price, day move. */
@Composable
fun StockRow(st: AppState, p: P) {
    if (Look.paper) return PaperStockRow(st, p)
    Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(p.s)) }.padding(horizontal = S.cardPad, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                T(p.c, 16.sp, weight = FontWeight.Bold, maxLines = 1, modifier = Modifier.weight(1f, false))
                StockTick(st, p)
                Spacer(Modifier.width(6.dp))
                if (p.out != null) TierChip("Removed L${p.out.l}", TierC.red, 10.sp) else p.dc?.let { DecisionChip(it, 11.sp) }
            }
            if (p.out != null) T(p.out.w ?: p.n, 12.sp, TierC.lightRed, maxLines = 1)
            else Text(androidx.compose.ui.text.buildAnnotatedString {
                pushStyle(androidx.compose.ui.text.SpanStyle(color = C.white)); append(setupName(p.su, p.tb == 1)); pop(); append(" · " + (p.i ?: p.n))
            }, fontSize = 13.sp, color = C.dim, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Box(Modifier.padding(top = 5.dp)) { LevelDots(p, 7.dp) }
        }
        Sparkline(p.sp, Modifier.padding(horizontal = 8.dp).size(52.dp, 26.dp))
        Column(Modifier.widthIn(min = 76.dp), horizontalAlignment = Alignment.End) {
            T(priceStr(p.p), 15.sp, weight = FontWeight.Bold, maxLines = 1)
            T(pct2(p.d1), 12.sp, gainColor(p.d1), maxLines = 1)
        }
    }
}

/** Paper look, one stock in the list (mock-up): code + verdict in its ink and the decision tag; seven dots, setup in capitals,
 *  conviction squares, industry; a 30-day line; price over the day's move with an arrow. Same facts as Classic's row. */
@Composable
fun PaperStockRow(st: AppState, p: P) {
    val col = if ((p.d1 ?: 0.0) >= 0) TierC.darkGreen else TierC.red
    Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(p.s)) }.padding(horizontal = S.cardPad, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            // feedback #120: two lines: code, tick, call, setup, conviction / dots, verdict · industry
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                // the code never shrinks; the setup word gives way first (screenshot 26 Nov: codes were cut to "ARRO…")
                Text(p.c, fontSize = 15.sp, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Bold, color = C.white, maxLines = 1, softWrap = false)
                StockTick(st, p)
                if (p.out != null) TierChip("Removed L${p.out.l}", TierC.red, 10.sp) else p.dc?.let { DecisionChip(it, 10.sp) }
                if (p.out == null) PaperLabel(setupName(p.su, p.tb == 1), if (p.tb == 1) TierC.lightRed else C.grey, 8.5.sp, bold = false, modifier = Modifier.weight(1f, false))
                p.cv?.let { cv -> Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    (1..3).forEach { k -> Box(Modifier.size(6.dp).background(if (k <= (if (cv == "High") 3 else if (cv == "Medium") 2 else 1)) C.white else C.line)) }
                } }
            }
            if (p.out != null) T(p.out.w ?: p.n, 12.sp, TierC.lightRed, maxLines = 1)
            else Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                InkDots(p.t, 6.dp, 2.dp)
                Text(androidx.compose.ui.text.buildAnnotatedString {
                    if (p.vd.isNotBlank()) { pushStyle(androidx.compose.ui.text.SpanStyle(color = verdictColor(p.vd), fontStyle = androidx.compose.ui.text.font.FontStyle.Italic)); append(p.vd); pop(); append(" · ") }
                    append(p.i ?: p.n)
                }, fontSize = 11.sp, color = C.dim, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        InkSpark(p.sp, col, Modifier.padding(horizontal = 6.dp).size(54.dp, 22.dp))
        Column(Modifier.widthIn(min = 70.dp), horizontalAlignment = Alignment.End) {
            T(priceStr(p.p), 13.sp, weight = FontWeight.SemiBold, maxLines = 1)
            T(arrowPct(p.d1), 11.sp, col, maxLines = 1)
        }
    }
}

/** Today's funnel as bars: listed, companies, then each level. */
@Composable
private fun FunnelCard(fn: FunnelV2) {
    val listed = fn.listed ?: return
    val vals = listOfNotNull(fn.listed, fn.companies).map { it.toDouble() } + fn.levels.map { it.toDouble() }
    val labs = (listOf("Listed", "Companies").take(listOfNotNull(fn.listed, fn.companies).size) + LEVEL_SHORT.take(fn.levels.size))
    SectionCard("Funnel today", "${fmt(listed.toDouble(), 0)} listed → ${fn.levels.lastOrNull()?.let { fmt(it.toDouble(), 0) } ?: "–"} pass all levels",
        Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp)) {
        // full level names need ~72dp a bar: scroll sideways on narrow screens
        Box(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
            Bars(vals, Modifier.width((72 * vals.size).dp).height(70.dp), labels = labs, color = C.grey, highlightLast = false, barFrac = 0.6f)
        }
    }
}

/** Filters (mockup h07): Claude research, presets, level tiers, setup, market cap, industry, toggles; Save / Show N stocks. */
@Composable
fun FilterSheet(st: AppState, start: Filt, saved: List<Filt>, onDismiss: () -> Unit, onApply: (Filt) -> Unit, onSave: (Filt) -> Unit) {
    val pf = st.picks ?: return
    var d by remember { mutableStateOf(start) }
    val n = remember(d, pf, st.research) { pf.picks.count { d.match(it) { p -> st.researched(p) } } }
    val nVer = remember(pf) { pf.picks.count { it.verified() } }
    val nRes = remember(pf, st.research) { pf.picks.count { st.researched(it) } }
    BottomSheet(onDismiss, "Filters", titleExtra = {
        T("Reset", 14.sp, C.blue, modifier = Modifier.clip(rr(8.dp)).clickable { d = Filt(sort = d.sort, q = d.q) }.padding(4.dp))
    }) {
        Label("Narrativ.ai research")
        Row(Modifier.fillMaxWidth().clip(rr(14.dp)).background(C.chip).padding(3.dp), horizontalArrangement = Arrangement.spacedBy(3.dp)) {
            RESEARCH.forEach { r ->
                val on = d.research == r
                Row(Modifier.weight(1f).clip(rr(11.dp)).background(if (on) TierC.lightGreen.copy(alpha = 0.15f) else Color.Transparent)
                    .then(if (on) Modifier.border(1.dp, TierC.lightGreen, rr(11.dp)) else Modifier).clickable { d = d.copy(research = r) }
                    .padding(vertical = 9.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                    if (r == "Verified") Icon(Icons.Rounded.Check, null, tint = TierC.lightGreen, modifier = Modifier.padding(end = 4.dp).size(14.dp))
                    T(r, 13.sp, if (on) C.white else C.muted, maxLines = 1)
                    when (r) { "Researched" -> nRes; "Verified" -> nVer; else -> null }?.let { T(" $it", 13.sp, C.dim, maxLines = 1) }
                }
            }
        }
        Label("Presets")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            (PRESETS + saved).forEach { p ->
                ToggleChip(p.name, d.sameAs(p), { d = p.copy(name = "", sort = d.sort, q = d.q, research = d.research, dc = d.dc, syms = d.syms) })
            }
        }
        Row(Modifier.padding(top = 14.dp, bottom = 4.dp)) { T("Level at least", 12.sp, C.dim); T(" · tiers best to worst", 12.sp, C.dim.copy(alpha = 0.7f)) }
        LEVELS.indices.forEach { i ->
            val names = (1..5).map { tierName(st, i, it) }
            val sub = if (i == 5) (if (d.disc.isEmpty()) "any stage" else d.disc.sorted().joinToString(", ") { names[it - 1] })
                else d.minTier[i].let { m -> if (m == 0) "Any" else if (m == 1) names[0] else "${names[m - 1]} or better" }
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.width(124.dp)) {
                    T(LEVEL_SHORT[i], 14.sp, weight = FontWeight.Medium, maxLines = 1)
                    T(sub, 11.sp, if (sub == "Any" || sub == "any stage") C.dim else C.white, maxLines = 1)
                }
                Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                    val anyOn = if (i == 5) d.disc.isEmpty() else d.minTier[i] == 0
                    Box(Modifier.weight(1.4f).height(30.dp).clip(rr(7.dp)).background(C.hi.copy(alpha = if (anyOn) 0.15f else 0.05f))
                        .clickable { d = if (i == 5) d.copy(disc = emptyList()) else d.copy(minTier = d.minTier.toMutableList().also { it[i] = 0 }) },
                        contentAlignment = Alignment.Center) { T("Any", 11.sp, if (anyOn) C.white else C.dim, if (anyOn) FontWeight.SemiBold else FontWeight.Normal) }
                    (1..5).forEach { t ->
                        val inn = if (i == 5) t in d.disc else d.minTier[i].let { it != 0 && t <= it }
                        Box(Modifier.weight(1f).height(30.dp).clip(rr(7.dp)).background(C.hi.copy(alpha = if (inn) 0.10f else 0.05f))
                            .clickable {
                                d = if (i == 5) d.copy(disc = if (t in d.disc) d.disc - t else d.disc + t)
                                else d.copy(minTier = d.minTier.toMutableList().also { it[i] = if (it[i] == t) 0 else t })
                            }, contentAlignment = Alignment.Center) {
                            Box(Modifier.fillMaxWidth(0.6f).height(5.dp).clip(rr(3.dp)).background(tierColor(t).copy(alpha = if (inn) 1f else 0.28f)))
                        }
                    }
                }
            }
            HLineDivider()
        }
        Label("Setup")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            SETUPS.forEach { s -> ToggleChip(if (s == "Any") "Any" else setupLabel(s), d.setup == s, { d = d.copy(setup = s) }) }
        }
        Label("Market cap")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            MCAP.forEach { s -> ToggleChip(s, d.mcap == s, { d = d.copy(mcap = s) }) }
        }
        Label("Industry contains")
        Box(Modifier.fillMaxWidth().clip(rr(12.dp)).background(C.chip).padding(horizontal = 12.dp, vertical = 11.dp)) {
            BasicTextField(d.industry, { d = d.copy(industry = it, industryExact = false) }, singleLine = true, textStyle = TextStyle(color = C.white, fontSize = 14.sp), cursorBrush = SolidColor(C.blue),
                modifier = Modifier.fillMaxWidth(), decorationBox = { inner -> if (d.industry.isEmpty()) T("e.g. Chemicals", 14.sp, C.dim); inner() })
        }
        Spacer(Modifier.height(8.dp))
        listOf(Triple("Include stocks not checked at a level", d.includeGrey) { v: Boolean -> d = d.copy(includeGrey = v) },
            Triple("Show removed stocks", d.showRemoved) { v: Boolean -> d = d.copy(showRemoved = v) },
            Triple("Turnarounds only", d.turnaround) { v: Boolean -> d = d.copy(turnaround = v) }).forEachIndexed { k, (label, on, set) ->
            Row(Modifier.fillMaxWidth().clickable { set(!on) }.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                T(label, 14.sp, modifier = Modifier.weight(1f))
                Switch(on, { set(it) }, colors = SwitchDefaults.colors(checkedTrackColor = C.teal, uncheckedTrackColor = C.chip, uncheckedThumbColor = C.dim,
                    uncheckedBorderColor = Color.Transparent))
            }
            if (k < 2) HLineDivider()
        }
        Row(Modifier.fillMaxWidth().padding(top = 16.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.clip(rr(16.dp)).border(1.dp, C.teal, rr(16.dp))
                .clickable { onSave(d.copy(name = "Saved ${saved.size + 1}")) }.padding(horizontal = 18.dp, vertical = 13.dp)) {
                T("Save", 15.sp, C.blue, FontWeight.SemiBold)
            }
            PrimaryButton("Show ${fmt(n.toDouble(), 0)} stock${if (n == 1) "" else "s"}", Modifier.weight(1f)) { onApply(d) }
        }
    }
}

@Composable
private fun Label(text: String) = T(text, 12.sp, C.dim, modifier = Modifier.padding(top = 14.dp, bottom = 6.dp))

@Composable
fun FChip(text: String, on: Boolean, color: Color, onClick: () -> Unit) {
    Box(Modifier.clip(rr(16.dp)).then(if (Look.paper) Modifier.border(1.dp, if (on) color else C.line) else Modifier.background(if (on) color.copy(alpha = 0.22f) else C.card2))
        .then(if (on && !Look.paper) Modifier.border(1.dp, color, rr(16.dp)) else Modifier).clickable(onClick = onClick)
        .heightIn(min = 40.dp).padding(horizontal = 12.dp, vertical = 10.dp), contentAlignment = Alignment.Center) { T(text, 12.sp, if (on) C.white else C.grey, FontWeight.Medium, maxLines = 1) }
}

@Composable
fun ChipRow(items: List<String>, selected: String?, pad: androidx.compose.ui.unit.Dp = 16.dp, onClick: (String) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = pad, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        items.forEach { FChip(it, it == selected, C.teal) { onClick(it) } }
    }
}
