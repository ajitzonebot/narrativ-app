@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.NumberFormat
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/*
 * DISCOVERY group (mockups out_discovery/h01..h08, screens_discovery.py): shared bits of Home, Market, Stocks, and the new
 * Search (h03), quadrant list (h05) and IPO detail (h08) screens. The older HomeSearch / QuadrantScreen / IpoScreen stay
 * in ExtraScreens.kt until the lead removes them.
 */

// ---------------------------------------------------------------- formatting and small helpers
private val INR = NumberFormat.getNumberInstance(Locale("en", "IN"))

/** Price as in the mockups: ₹254.55 below 1,000, ₹2,084.6 to 10,000, ₹12,345 above. */
fun priceStr(v: Double?): String {
    if (v == null) return "–"
    val d = if (v < 1000) 2 else if (v < 10000) 1 else 0
    return "₹" + INR.apply { maximumFractionDigits = d; minimumFractionDigits = d }.format(v)
}

/** Day move with two decimals and a real minus: +0.45% / −0.45%. */
fun pct2(v: Double?): String = if (v == null) "–" else (if (v >= 0) "+" else "−") + String.format(Locale.US, "%.2f", abs(v)) + "%"

/** Signed one decimal: +12.2% / −2.8% (suffix configurable). */
fun sg1(v: Double?, suf: String = "%"): String = if (v == null) "–" else (if (v >= 0) "+" else "−") + String.format(Locale.US, "%.1f", abs(v)) + suf

/** Gains light green, losses light red (mockup pcol). */
fun gainColor(v: Double?): Color = if ((v ?: 0.0) >= 0) TierC.lightGreen else TierC.lightRed

/** Entry setup as words (mockup SETUP). */
fun setupLabel(su: String?): String = when (su) { "Breakout" -> "Breaking out"; "Pullback" -> "Dip in uptrend"; "Base" -> "Near entry"; else -> "Wait" }

/** Verified by Claude: the verification of the rating passed. */
fun P.verified(): Boolean = vf == "pass"

/** Researched by Claude: in research.json, or carries a verification state. */
fun AppState.researched(p: P): Boolean = p.s in research || p.vf != null

fun isBuy(p: P) = p.dc == "Buy" || p.dc == "Strong Buy"

fun sentence(s: String): String = s.lowercase().replaceFirstChar { it.uppercase() }

/** Claude's tick next to a code: filled = verified, outline = researched not verified, nothing otherwise. */
@Composable
fun StockTick(st: AppState, p: P, size: Dp = 15.dp) {
    when {
        p.verified() -> VerifiedTick(true, Modifier.padding(start = 5.dp), size)
        st.researched(p) -> VerifiedTick(false, Modifier.padding(start = 5.dp), size)
    }
}

/** "MB" tag (multibagger potential), yellow outline. */
@Composable
fun MbTag() {
    Box(Modifier.padding(start = 6.dp).clip(RoundedCornerShape(6.dp)).border(1.dp, TierC.yellow.copy(alpha = 0.4f), RoundedCornerShape(6.dp))
        .padding(horizontal = 4.dp)) { T("MB", 10.sp, TierC.yellow, maxLines = 1) }
}

/** Rule-built conviction (P.cv) as a 3-segment meter; nothing when null. */
@Composable
fun ConvictionMeter(cv: String?, modifier: Modifier = Modifier) {
    val n = when (cv) { "High" -> 3; "Medium" -> 2; "Low" -> 1; else -> return }
    Meter(3, n, modifier.padding(start = 6.dp))
}

/** Rounded horizontal bar 0..1 on a faint track, optional thin white mark (e.g. the 50% or 1× line). */
@Composable
fun HBar(frac: Double, color: Color, modifier: Modifier = Modifier, height: Dp = 6.dp, mark: Double? = null) {
    Canvas(modifier.height(height + 6.dp)) {
        val h = height.toPx(); val top = (size.height - h) / 2
        drawRoundRect(Color.White.copy(alpha = 0.07f), Offset(0f, top), Size(size.width, h), CornerRadius(h / 2))
        val w = (frac.coerceIn(0.0, 1.0) * size.width).toFloat()
        if (w > 0) drawRoundRect(color, Offset(0f, top), Size(max(w, h), h), CornerRadius(h / 2))
        mark?.let { m ->
            val x = (m.coerceIn(0.0, 1.0) * size.width).toFloat()
            drawRect(Color.White.copy(alpha = 0.55f), Offset(x - 0.75.dp.toPx(), 0f), Size(1.5.dp.toPx(), size.height))
        }
    }
}

/** Bar from a centre line: right for gains, left for losses, scaled to [span] (quadrant list 1M / 3M). */
@Composable
fun CentreBar(v: Double?, span: Double, color: Color, modifier: Modifier = Modifier) {
    Canvas(modifier.height(10.dp)) {
        val cx = size.width / 2; val h = 6.dp.toPx(); val top = (size.height - h) / 2
        drawRect(Color.White.copy(alpha = 0.25f), Offset(cx - 0.5.dp.toPx(), 0f), Size(1.dp.toPx(), size.height))
        if (v == null) return@Canvas
        val w = max((abs(v) / span).toFloat() * cx, 2.dp.toPx())
        drawRoundRect(color, Offset(if (v >= 0) cx else cx - w, top), Size(w, h), CornerRadius(h / 2))
    }
}

/** Grouped rounded bars (How we know: Top 10 vs any stock by horizon). Values over bars, group names (and a small second line) under. */
@Composable
fun GroupedBars(groups: List<Pair<String, String?>>, series: List<Pair<Color, List<Double?>>>, modifier: Modifier,
                valueFmt: (Double) -> String, ref: Double? = null, refLabel: String? = null) {
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val gut = if (ref != null) 30.dp.toPx() else 0f
        val top = 20.dp.toPx(); val bot = (if (groups.any { it.second != null }) 32 else 20).dp.toPx()
        val all = series.flatMap { it.second }.filterNotNull() + listOfNotNull(ref) + 0.0
        val hi = all.max() * 1.12; val lo = min(all.min(), 0.0)
        fun y(v: Double) = ChartMath.lerp(v, lo, if (hi > lo) hi else lo + 1, size.height - bot, top)
        val y0 = y(0.0)
        drawLine(Color.White.copy(alpha = 0.12f), Offset(gut, y0), Offset(size.width, y0), 1.dp.toPx())
        if (ref != null) {
            drawLine(C.dim.copy(alpha = 0.7f), Offset(gut, y(ref)), Offset(size.width, y(ref)), 1.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 4.dp.toPx())))
            refLabel?.let { chartText(tm, it, 0f, y(ref) + 3.5.dp.toPx(), C.dim, 10.sp) }
        }
        val gw = (size.width - gut) / groups.size
        val gap = 6.dp.toPx(); val bw = min(30.dp.toPx(), gw / (series.size + 1.4f))
        groups.forEachIndexed { gi, (name, sub) ->
            val x0 = gut + gi * gw + (gw - bw * series.size - gap * (series.size - 1)) / 2
            series.forEachIndexed { si, (c, vs) ->
                val v = vs.getOrNull(gi) ?: return@forEachIndexed
                val x = x0 + si * (bw + gap); val a = min(y(v), y0); val b = max(y(v), y0)
                drawRoundRect(c, Offset(x, a), Size(bw, max(b - a, 2.dp.toPx())), CornerRadius(6.dp.toPx()))
                chartText(tm, valueFmt(v), x + bw / 2, a - 5.dp.toPx(), if (si == 0) C.white else C.dim, 11.sp,
                    if (si == 0) FontWeight.Bold else FontWeight.Medium, Anchor.Middle)
            }
            val cx = gut + gi * gw + gw / 2
            chartText(tm, name, cx, size.height - (if (sub != null) 16 else 4).dp.toPx(), C.muted, 11.sp, anchor = Anchor.Middle)
            sub?.let { chartText(tm, it, cx, size.height - 3.dp.toPx(), C.dim, 10.sp, anchor = Anchor.Middle) }
        }
    }
}

/** Mini stock card (Market: Buys in leading industries). */
@Composable
fun MiniStockCard(st: AppState, p: P) {
    Column(Modifier.width(150.dp).clip(RoundedCornerShape(12.dp)).background(C.chip).clickable { st.go(Screen.Stock(p.s)) }
        .padding(horizontal = 10.dp, vertical = 9.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) { T(p.c, 13.sp, weight = FontWeight.Bold, maxLines = 1, modifier = Modifier.weight(1f, false)); StockTick(st, p, 14.dp) }
        T(p.i ?: "–", 11.sp, C.dim, maxLines = 1)
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.Bottom) {
            Column(Modifier.weight(1f)) { T(priceStr(p.p), 12.sp, maxLines = 1); T(pct2(p.d1), 12.sp, gainColor(p.d1), maxLines = 1) }
            Sparkline(p.sp, Modifier.size(52.dp, 24.dp))
        }
    }
}

// ================================================================ h03 SEARCH
/** Search the whole universe by code, name or industry (opened from the Home header). */
@Composable
fun SearchScreen(st: AppState) {
    val all = st.picks?.picks ?: return
    var q by rememberSaveable { mutableStateOf("") }
    val qq = q.trim()
    val hits = remember(qq, all) {
        if (qq.isEmpty()) emptyList() else all.filter { "${it.c} ${it.n} ${it.i ?: ""}".contains(qq, true) }
            .sortedWith(compareByDescending<P> { it.c.startsWith(qq, true) }.thenBy { it.out != null }.thenByDescending { it.pr })
    }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, "Search", context = "Search") }
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp))
                .background(Color.White.copy(alpha = 0.08f)).border(1.5.dp, C.teal, RoundedCornerShape(14.dp)).padding(horizontal = 12.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Search, null, tint = C.dim, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                BasicTextField(q, { q = it }, singleLine = true, textStyle = TextStyle(color = C.white, fontSize = 16.sp), cursorBrush = SolidColor(C.blue),
                    modifier = Modifier.weight(1f).focusRequester(focus),
                    decorationBox = { inner -> if (q.isEmpty()) T("Code, name or industry", 16.sp, C.dim); inner() })
                if (q.isNotEmpty()) Icon(Icons.Rounded.Close, "Clear", tint = C.dim, modifier = Modifier.clip(CircleShape).clickable { q = "" }.size(20.dp))
            }
        }
        if (qq.isEmpty()) return@LazyColumn
        item { T("${fmt(hits.size.toDouble(), 0)} matches · code, name or industry", 13.sp, C.dim, modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp)) }
        if (hits.isEmpty()) { item { Empty("No stock matches “$qq”.") }; return@LazyColumn }
        item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth(), pad = 0.dp) {
                hits.take(8).forEachIndexed { i, p ->
                    Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(p.s)) }.padding(horizontal = S.cardPad, vertical = 9.dp).heightIn(min = 40.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(highlight(p.c, qq), fontSize = 15.sp, color = C.white, fontWeight = FontWeight.Bold, maxLines = 1)
                                StockTick(st, p)
                            }
                            val ind = p.i ?: ""
                            val sub = when {
                                p.n.contains(qq, true) -> p.n
                                ind.contains(qq, true) -> "$ind · ${p.n}"
                                else -> p.n
                            }
                            Text(highlight(sub, qq, C.muted), fontSize = 13.sp, color = C.dim, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Spacer(Modifier.width(8.dp))
                        if (p.out != null) TierChip("Removed", TierC.red, 11.sp) else DecisionChip(p.dc ?: "Not rated", 11.sp)
                        Column(Modifier.widthIn(min = 76.dp).padding(start = 10.dp), horizontalAlignment = Alignment.End) {
                            T(priceStr(p.p), 14.sp, weight = FontWeight.Bold, maxLines = 1)
                            T(pct2(p.d1), 12.sp, gainColor(p.d1), maxLines = 1)
                        }
                    }
                    if (i < min(hits.size, 8) - 1) HLineDivider(Modifier.padding(horizontal = S.cardPad))
                }
                if (hits.size > 8) Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Screener("q:$qq")) }.padding(vertical = 12.dp),
                    horizontalArrangement = Arrangement.Center) { T("All ${fmt(hits.size.toDouble(), 0)} results in Stocks ›", 14.sp, C.blue) }
            }
        }
    }
}

/** [text] with every match of [q] in white and underlined (search results). */
private fun highlight(text: String, q: String, base: Color = C.white) = buildAnnotatedString {
    var i = 0
    while (i < text.length) {
        val j = if (q.isEmpty()) -1 else text.indexOf(q, i, ignoreCase = true)
        if (j < 0) { pushStyle(SpanStyle(color = base)); append(text.substring(i)); pop(); break }
        pushStyle(SpanStyle(color = base)); append(text.substring(i, j)); pop()
        pushStyle(SpanStyle(color = C.white, textDecoration = TextDecoration.Underline)); append(text.substring(j, j + q.length)); pop()
        i = j + q.length
    }
}

// ================================================================ h05 QUADRANT LIST
private val QUAD_WHAT = mapOf("Leading" to "money flowing in", "Improving" to "money starting to flow in",
    "Weakening" to "book profits, tighten stops", "Lagging" to "money flowing out", "Rising" to "leading or improving")

/**
 * One rotation quadrant (q = Leading / Improving / Weakening / Lagging, or "Rising" = Leading + Improving) as a list by
 * momentum: stocks and Buys in each, the top three codes, 1-month and 3-month returns as bars from a centre line.
 */
@Composable
fun QuadrantListScreen(st: AppState, q: String, sectors: Boolean) {
    val rot = st.rotation
    val src = (if (sectors) rot?.sectors else rot?.industries).orEmpty()
    val qs = if (q == "Rising") setOf("Leading", "Improving") else setOf(q)
    val list = src.entries.filter { it.value.q in qs }.sortedByDescending { it.value.mom }
    val live = st.picks?.picks.orEmpty().filter { it.out == null }
    val kind = if (sectors) "sectors" else "industries"
    val span = list.maxOfOrNull { max(abs(it.value.r1m ?: 0.0), abs(it.value.r3m ?: 0.0)) }?.takeIf { it > 0 } ?: 1.0
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, "$q $kind", context = "Quadrant $q", subtitle = "${list.size} $kind · ${QUAD_WHAT[q] ?: ""} · by momentum") }
        if (list.isEmpty()) { item { Spacer(Modifier.height(8.dp)); Empty("Nothing in this quadrant today.") }; return@LazyColumn }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                Legend(listOf("1 month" to C.teal, "3 months" to TierC.yellow), Modifier.padding(start = S.cardPad, top = 12.dp, bottom = 4.dp))
                list.forEachIndexed { idx, (name, r) ->
                    val members = live.filter { if (sectors) SECTOR_OF[it.i ?: ""] == name else it.i == name }
                    val tops = members.sortedByDescending { it.pr }.take(3)
                    val nb = members.count { isBuy(it) }
                    val open = { st.go(Screen.Screener(if (sectors) "sec:$name" else "ind:$name")) }
                    Row(Modifier.fillMaxWidth().clickable(onClick = open).padding(horizontal = S.cardPad, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            T(name, 15.sp, weight = FontWeight.Medium, maxLines = 1)
                            Row {
                                T("${r.n ?: members.size} stocks", 12.sp, C.dim, maxLines = 1)
                                if (nb > 0) T(" · $nb Buy", 12.sp, TierC.lightGreen, maxLines = 1)
                            }
                            if (tops.isNotEmpty()) T(tops.joinToString(" · ") { it.c } + " ›", 12.sp, C.blue, maxLines = 1, modifier = Modifier.padding(top = 3.dp))
                            else T("No stock in the funnel", 12.sp, C.dim)
                        }
                        Column(Modifier.width(140.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            listOf(r.r1m to C.teal, r.r3m to TierC.yellow).forEach { (v, c) ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    CentreBar(v, span, c, Modifier.weight(1f))
                                    T(sg1(v), 11.sp, if (v == null) C.dim else gainColor(v), FontWeight.SemiBold, Modifier.width(48.dp), maxLines = 1,
                                        align = androidx.compose.ui.text.style.TextAlign.End)
                                }
                            }
                        }
                    }
                    if (idx < list.lastIndex) HLineDivider(Modifier.padding(horizontal = S.cardPad))
                }
            }
        }
        if (sectors) item { T("NSE sector indices; tap one for the stocks in its industries.", 12.sp, C.dim, modifier = Modifier.padding(16.dp)) }
    }
}

// ================================================================ h08 IPO DETAIL
private fun ipoActionColor(a: String): Color = when (a) {
    "APPLY" -> TierC.lightGreen; "SELECTIVE APPLY" -> TierC.yellow; "WAIT" -> C.dim; "AVOID" -> TierC.lightRed; else -> C.white
}

/** One IPO from today's 08:30 check (or upcoming): call, days, band vs implied listing, GMP trend, subscription, why / risk / missing, sources. */
@Composable
fun IpoDetailScreen(st: AppState, name: String) {
    val x = st.ipo
    val u = x?.upcoming?.firstOrNull { it.name == name }
    val i = x?.actionable?.firstOrNull { it.name == name }
        ?: x?.laterToday?.firstOrNull { it.name == name }?.let { IpoOpen(name = it.name, board = it.board, lastDate = it.lastDate ?: "", upcoming = true, why = "Opens today ${it.opens ?: ""}".trim()) }
        ?: u?.let { IpoOpen(name = it.name, board = it.board, priceLow = it.priceLow, priceHigh = it.priceHigh, openDate = it.openDate ?: "", lastDate = it.lastDate ?: "",
            upcoming = true, gmpNote = it.note, gmpObserved = it.gmpObserved, sources = listOfNotNull(it.source)) }
    val uri = LocalUriHandler.current
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, name, context = "IPO $name", subtitle = listOfNotNull("IPO", i?.board?.ifBlank { null }, i?.symbol).joinToString(" · ")) }
        if (i == null) { item { Spacer(Modifier.height(8.dp)); Empty("This IPO is not in today's report.") }; return@LazyColumn }
        val acol = if (i.upcoming) C.dim else ipoActionColor(i.action)
        // call card
        item {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth().clip(RoundedCornerShape(S.card))
                .background(Brush.verticalGradient(listOf(acol.copy(alpha = 0.16f), C.card), endY = 600f)).padding(S.cardPad)) {
                if (i.rating.isNotEmpty()) StatusChip("Rating ${sentence(i.rating)}", color = acol)
                T(if (i.upcoming) "Not open yet" else sentence(i.action.ifBlank { "No call" }), 26.sp, acol, FontWeight.ExtraBold, maxLines = 2,
                    modifier = Modifier.padding(top = 6.dp))
                val days = i.days; val day = i.day
                if (days != null && days > 0 && day != null) Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    repeat(days) { k -> Box(Modifier.weight(1f).height(6.dp).clip(RoundedCornerShape(3.dp)).background(if (k < day) TierC.yellow else Color.White.copy(alpha = 0.1f))) }
                }
                T(listOfNotNull(if (day != null && days != null) "Day $day of $days" else null,
                    i.openDate.ifBlank { null }?.let { "opened ${shortDate(it)}" },
                    i.lastDate.ifBlank { null }?.let { "closes ${shortDate(it)}" + (i.closeTime?.let { t -> ", $t" } ?: "") }).joinToString(" · "),
                    12.sp, if (i.finalDay) TierC.lightRed else C.dim, modifier = Modifier.padding(top = 2.dp))
                if (i.finalDay) T("Final day", 12.sp, TierC.lightRed, FontWeight.Bold)
                if (i.priceLow != null && i.priceHigh != null) BandChart(i.priceLow, i.priceHigh, i.impliedHigh, i.gmpPctHigh, Modifier.padding(top = 12.dp).fillMaxWidth().height(54.dp))
                KvRow("Lot", i.lot?.let { l -> "$l shares" + (i.priceHigh?.let { " · ₹${fmt(it * l, 0)}" } ?: "") } ?: "–")
                KvRow("Issue size", i.issueCr?.let { "₹${fmt(it, 0)} cr" } ?: "–", divider = false)
            }
        }
        // GMP
        item {
            SectionCard(modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    T("GMP", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Box(Modifier.clip(RoundedCornerShape(6.dp)).border(1.dp, TierC.yellow.copy(alpha = 0.4f), RoundedCornerShape(6.dp)).padding(horizontal = 6.dp, vertical = 1.dp)) {
                        T("unofficial", 10.sp, TierC.yellow, FontWeight.SemiBold)
                    }
                }
                if (i.gmpHigh != null) Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.Bottom) {
                    T(if (i.gmpLow != null && i.gmpLow != i.gmpHigh) "₹${fmt(i.gmpLow, 0)}–${fmt(i.gmpHigh, 0)}" else "₹${fmt(i.gmpHigh, 0)}", 26.sp, weight = FontWeight.Bold)
                    i.gmpPctHigh?.let { T("  ${sg1(it)}", 14.sp, gainColor(it), modifier = Modifier.padding(bottom = 4.dp)); T(" on upper band", 14.sp, modifier = Modifier.padding(bottom = 4.dp)) }
                } else T(u?.gmp ?: "No GMP seen", 14.sp, C.dim, modifier = Modifier.padding(top = 4.dp))
                val trend = gmpTrend(i)
                if (trend.size >= 2) GmpLine(trend, Modifier.padding(top = 6.dp).fillMaxWidth().height(96.dp))
                val obs = i.gmpObserved?.let { istTime(it).takeIf { t -> t != "–" } ?: it.take(16) }
                if (obs != null) T("Observed $obs" + (if (i.gmpNote?.contains("agree") == true) " · ${i.gmpSources.size} sources agree" else "") +
                    (if (i.gmpStale) " · not today (stale)" else ""), 12.sp, if (i.gmpStale) C.amber else C.dim, modifier = Modifier.padding(top = 4.dp))
            }
        }
        i.subscription?.let { sb ->
            item {
                val mx = listOfNotNull(sb.qib, sb.nii, sb.retail, sb.overall, 1.0).max() * 1.08
                SectionCard("Subscription", "${sb.asOf?.let { istTime(it) } ?: "–"} · line = 1×", Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                    listOf("QIB" to sb.qib, "NII" to sb.nii, "Retail" to sb.retail, "Overall" to sb.overall).forEach { (k, v) ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                            T(k, 13.sp, C.muted, modifier = Modifier.width(60.dp))
                            HBar((v ?: 0.0) / mx, if ((v ?: 0.0) < 1) TierC.lightRed else C.teal, Modifier.weight(1f), 8.dp, 1 / mx)
                            T(v?.let { String.format(Locale.US, "%.2f×", it) } ?: "–", 13.sp, if (v != null && v < 1) TierC.lightRed else C.white, FontWeight.SemiBold,
                                Modifier.width(58.dp), maxLines = 1, align = androidx.compose.ui.text.style.TextAlign.End)
                        }
                    }
                    i.pmUpdate?.let { pm -> T("14:10 update: call ${pm.callBefore ?: "–"} → ${pm.callAfter ?: "–"}", 12.sp,
                        if (pm.callBefore != pm.callAfter) C.amber else C.dim, modifier = Modifier.padding(top = 6.dp)) }
                }
            }
        }
        item {
            var full by remember { mutableStateOf(false) }
            SectionCard(modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                if (i.upcoming) T("Rated at the 08:30 check on its opening day.", 13.sp, C.dim)
                i.why?.takeIf { !i.upcoming && it.isNotBlank() }?.let {
                    T("Why", 15.sp, weight = FontWeight.SemiBold); T(it, 13.sp, lineHeight = 19.sp, modifier = Modifier.padding(top = 2.dp, bottom = 10.dp))
                }
                if (i.keyRisk.isNotBlank()) {
                    val parts = i.keyRisk.split(";").map { it.trim() }.filter { it.isNotEmpty() }
                    val short = if (parts.size > 2) parts.take(2).joinToString("; ").trimEnd('.') + "." else i.keyRisk
                    T("Key risk", 15.sp, weight = FontWeight.SemiBold)
                    T(if (full) i.keyRisk else short, 13.sp, C.muted, lineHeight = 19.sp, modifier = Modifier.padding(top = 2.dp))
                    if (parts.size > 2) MoreLink(if (full) "Short risk note" else "Full risk note") { full = !full }
                    Spacer(Modifier.height(10.dp))
                }
                if (i.missing.isNotEmpty()) {
                    T("Missing", 15.sp, weight = FontWeight.SemiBold)
                    FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        i.missing.forEach { m -> Box(Modifier.clip(RoundedCornerShape(9.dp)).background(C.amber.copy(alpha = 0.13f)).padding(horizontal = 9.dp, vertical = 4.dp)) { T(m, 12.sp, C.amber) } }
                    }
                }
            }
        }
        val src = (i.sources + i.gmpSources + listOfNotNull(i.subscription?.source)).distinct()
        if (src.isNotEmpty()) item {
            var open by remember { mutableStateOf(false) }
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                Box(Modifier.padding(horizontal = S.cardPad)) { ToggleRow("Sources", "${src.size} links", open, { open = !open }, divider = false) }
                if (open) Column(Modifier.padding(start = S.cardPad, end = S.cardPad, bottom = 10.dp)) {
                    src.forEach { s -> T(s.removePrefix("https://").removePrefix("www.").take(64) + " ›", 12.sp, C.blue, maxLines = 1,
                        modifier = Modifier.fillMaxWidth().clickable { runCatching { uri.openUri(s) } }.padding(vertical = 6.dp)) }
                }
            }
        }
        item { T("GMP is unofficial grey-market data, not a guaranteed return.", 11.sp, C.dim, modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp)) }
    }
}

/** GMP points (date, ₹) read from the note ("₹20 (15 Nov) to ₹37 (18 Nov)") plus the observed value; empty when the note has none. */
fun gmpTrend(i: IpoOpen): List<Pair<java.time.LocalDate, Double>> {
    val obs = runCatching { java.time.OffsetDateTime.parse(i.gmpObserved!!).atZoneSameInstant(java.time.ZoneId.of("Asia/Kolkata")).toLocalDate() }.getOrNull()
        ?: runCatching { java.time.LocalDate.parse(i.gmpObserved!!.take(10)) }.getOrNull() ?: return emptyList()
    val fm = java.time.format.DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH)
    val pts = Regex("₹(\\d+(?:\\.\\d+)?) \\((\\d{1,2} [A-Z][a-z]{2})\\)").findAll(i.gmpNote ?: "").mapNotNull { m ->
        val d = runCatching { java.time.LocalDate.parse("${m.groupValues[2]} ${obs.year}", fm) }.getOrNull() ?: return@mapNotNull null
        (if (d.isAfter(obs)) d.minusYears(1) else d) to m.groupValues[1].toDouble()
    }.toMutableList()
    if (pts.isEmpty()) return emptyList()
    if (pts.last().first != obs && i.gmpHigh != null) pts += obs to i.gmpHigh
    return pts.sortedBy { it.first }
}

/** GMP line by date: smooth line, soft yellow fill, every point labelled ₹ and dated underneath. */
@Composable
private fun GmpLine(pts: List<Pair<java.time.LocalDate, Double>>, modifier: Modifier) {
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val l = 16.dp.toPx(); val r = size.width - 16.dp.toPx(); val t = 20.dp.toPx(); val b = size.height - 18.dp.toPx()
        val d0 = pts.first().first; val span = max(1L, java.time.temporal.ChronoUnit.DAYS.between(d0, pts.last().first)).toFloat()
        val hi = pts.maxOf { it.second }
        val o = pts.map { (d, v) -> Offset(l + java.time.temporal.ChronoUnit.DAYS.between(d0, d) / span * (r - l), ChartMath.lerp(v, 0.0, hi, b, t)) }
        val line = smoothPath(o)
        val area = smoothPath(o).apply { lineTo(o.last().x, b); lineTo(o.first().x, b); close() }
        drawPath(area, Brush.verticalGradient(listOf(TierC.yellow.copy(alpha = 0.35f), TierC.yellow.copy(alpha = 0f)), startY = t, endY = b))
        drawPath(line, TierC.yellow, style = Stroke(2.dp.toPx(), cap = StrokeCap.Round))
        var lastX = -1e9f
        o.forEachIndexed { k, p ->
            drawCircle(TierC.yellow, 3.dp.toPx(), p)
            chartText(tm, "₹${fmt(pts[k].second, 0)}", p.x, p.y - 8.dp.toPx(), C.white, 11.sp, FontWeight.SemiBold, Anchor.Middle)
            if (p.x - lastX > 36.dp.toPx() || k == o.lastIndex) {
                chartText(tm, shortDate(pts[k].first.toString()), p.x, size.height - 2.dp.toPx(), C.dim, 10.sp, anchor = if (k == o.lastIndex) Anchor.End else Anchor.Middle)
                lastX = p.x
            }
        }
    }
}

/** Price band (blue) and the GMP-implied listing (yellow dot) on one scale, gain to it underneath. */
@Composable
private fun BandChart(lo: Double, hi: Double, implied: Double?, pct: Double?, modifier: Modifier) {
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val a0 = min(lo, implied ?: lo); val b0 = max(hi, implied ?: hi); val pad = (b0 - a0).takeIf { it > 0 }?.times(0.08) ?: 1.0
        fun X(v: Double) = ChartMath.lerp(v, a0 - pad, b0 + pad, 0f, size.width)
        val cy = 26.dp.toPx(); val h = 8.dp.toPx()
        drawRoundRect(Color.White.copy(alpha = 0.07f), Offset(0f, cy - h / 2), Size(size.width, h), CornerRadius(h / 2))
        drawRoundRect(C.teal, Offset(X(lo), cy - h / 2), Size(max(X(hi) - X(lo), h), h), CornerRadius(h / 2))
        chartText(tm, "Band ₹${fmt(lo, 0)}–${fmt(hi, 0)}", X(lo), cy - 12.dp.toPx(), C.muted, 11.sp)
        if (implied != null) {
            val a = min(X(hi), X(implied)); val b = max(X(hi), X(implied))
            drawRect(TierC.yellow.copy(alpha = 0.5f), Offset(a, cy - 2.dp.toPx()), Size(b - a, 4.dp.toPx()))
            drawCircle(TierC.yellow, 6.dp.toPx(), Offset(X(implied), cy))
            chartText(tm, "Implied ₹${fmt(implied, 0)}", X(implied).coerceAtLeast(110.dp.toPx()), cy - 12.dp.toPx(), TierC.yellow, 11.sp, FontWeight.Bold, Anchor.End)
            pct?.let { chartText(tm, sg1(it), (a + b) / 2, size.height - 4.dp.toPx(), gainColor(it), 11.sp, FontWeight.SemiBold, Anchor.Middle) }
        }
    }
}
