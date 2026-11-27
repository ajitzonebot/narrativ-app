package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.material3.Text
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.serializer
import kotlin.math.abs
import kotlin.math.max

/*
 * Account screens of the redesign (mockups a03, a06, a07, a09, a10): Track record, Data and pipeline, Research queue,
 * Release notes, Feedback list. The old versions in ExtraScreens.kt / StockParts.kt stay until the lead removes them.
 */

// ---------------------------------------------------------------- helpers shared by the account screens
/** Signed figure with a real minus: +1.69% / −0.57 / – when missing. */
fun sg(v: Double?, d: Int = 2, unit: String = "%"): String =
    if (v == null) "–" else (if (v < 0) "−" else "+") + fmt(abs(v), d) + unit
/** Green for gains, red for losses, grey when there is no number. */
fun plColor(v: Double?): Color = when { v == null -> C.dim; v < 0 -> TierC.lightRed; else -> TierC.lightGreen }

@Composable
fun StatusDot(color: Color, modifier: Modifier = Modifier, size: Dp = 8.dp) = Box(modifier.size(size).clip(CircleShape).background(color))

/** Screen scaffold: gradient background, top bar (back arrow unless [back] is false) and the rows in [content]. */
@Composable
fun AccScreen(st: AppState, title: String, subtitle: String? = null, context: String = title, back: Boolean = true, big: Boolean = false,
              actions: @Composable RowScope.() -> Unit = {}, modifier: Modifier = Modifier, content: LazyListScope.() -> Unit) {
    LazyColumn(Modifier.fillMaxSize().pageBackground().then(modifier), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, title, context, subtitle, back, big, actions = actions) }
        content()
    }
}

/** Darker cell inside a card: small grey label, bold figure. */
@Composable
fun Cell(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = C.white, note: String? = null) {
    Column(modifier.clip(rr(12.dp)).background(C.sheet).padding(horizontal = 12.dp, vertical = 10.dp)) {
        T(label, 11.sp, C.dim, maxLines = 1)
        T(value, 17.sp, valueColor, FontWeight.Bold, maxLines = 1)
        note?.let { T(it, 10.sp, C.dim, maxLines = 2) }
    }
}

/** Rounded progress bar on a track. */
@Composable
fun ProgBar(fraction: Float, color: Color, modifier: Modifier = Modifier, height: Dp = 8.dp, track: Color = C.hi.copy(alpha = 0.10f)) {
    Box(modifier.height(height).clip(rr(height / 2)).background(track)) {
        Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).fillMaxHeight().clip(rr(height / 2)).background(color))
    }
}

/** A card holding a row that opens more below it ("Today's schedule  11 jobs · next 17:10"). */
@Composable
fun CollapseCard(title: String, right: String = "", modifier: Modifier = Modifier, startOpen: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    var open by remember { mutableStateOf(startOpen) }
    Card(modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
        Column(Modifier.padding(horizontal = 14.dp)) { ToggleRow(title, right, open, { open = !open }, divider = false) }
        if (open) Column(Modifier.padding(start = 14.dp, end = 14.dp, bottom = 12.dp)) { HLineDivider(Modifier.padding(bottom = 8.dp)); content() }
    }
}

/** Small tinted label (feedback type, checkpoint type). */
@Composable
fun TypeTag(text: String, color: Color) = StatusChip(text, color = color, minWidth = 0.dp)

/** A load that has finished: [v] is null when it failed or found nothing. A null Fetched means still loading. */
data class Fetched<T>(val v: T?)

/** Placeholder card while a screen's data loads (grey bars in the shape of a figure card). */
@Composable
fun LoadingCard(lines: Int = 3) {
    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
        Skel(120.dp, 12.dp)
        Skel(160.dp, 30.dp, Modifier.padding(top = 10.dp))
        repeat(lines) { Skel(null, 14.dp, Modifier.padding(top = 10.dp)) }
    }
}

/** Grey placeholder lines inside a card section while it loads. */
@Composable
fun SkelLines(n: Int = 3) = Column { repeat(n) { Skel(null, 14.dp, Modifier.padding(vertical = 5.dp)) } }

// ---------------------------------------------------------------- extra fields of calls.json / health.json / data_issues.json
@Serializable data class MatStat(val n: Int = 0, @SerialName("avg_pct") val avgPct: Double? = null, @SerialName("hit_pct") val hitPct: Double? = null,
                                 @SerialName("avg_vs_nifty") val avgVsNifty: Double? = null)
@Serializable data class CallsMatSummary(val verified: Map<String, MatStat> = emptyMap())
/** calls.json summary.verified: returns of verified Buys by age (1m, 3m, 6m, 12m), n = 0 until a Buy is that old. */
@Serializable data class CallsMat(val summary: CallsMatSummary = CallsMatSummary())
/** health.json "universe": number of companies the coverage figures are measured against. */
@Serializable data class HealthU(val universe: Int? = null)
/** data_issues.json "corrected". */
@Serializable data class IssuesU(val corrected: Int = 0)

/** One file read as two types (cache-first, see Repo.cacheFirst): decoded once per text, off the main thread. */
private suspend inline fun <reified A : Any, reified B : Any> Repo.cacheFirst2(path: String, noinline emit: (Pair<A, B>?) -> Unit) {
    val sa = serializer<A>(); val sb = serializer<B>()
    cacheFirstBy(path, sa.descriptor.serialName + "+" + sb.descriptor.serialName, { t -> json.decodeFromString(sa, t) to json.decodeFromString(sb, t) }, emit)
}
@Suppress("UNCHECKED_CAST")
private inline fun <reified A : Any, reified B : Any> Repo.peek2(path: String): Pair<A, B>? =
    (Repo.memoPeek(path, serializer<A>().descriptor.serialName + "+" + serializer<B>().descriptor.serialName) as? Pair<*, *>)
        ?.takeIf { it.first is A && it.second is B } as Pair<A, B>?

/** produceState start value for a [Fetched] file: the decoded copy already in memory, else null (loading). */
inline fun <reified T : Any> Repo.peekF(path: String): Fetched<T>? = peek<T>(path)?.let { Fetched(it) }

// ---------------------------------------------------------------- a03 Track record
/** Outcome buckets, better = darker green (Home's How-we-know bar uses the same names and colours). */
private val MIX_GOAL get() = listOf(Triple("Multibagger", 2, TierC.darkGreen), Triple("Beat Nifty", 3, TierC.lightGreen),
    Triple("Near Nifty", 3, C.grey), Triple("Behind Nifty", 2, TierC.lightRed))

@Composable
fun TrackRecordScreen(st: AppState) {
    // cache-first; the two reads of calls.json share one request
    val cf by produceState(st.repo.peekF<CallsFile>("data/calls.json")) { st.repo.cacheFirst<CallsFile>("data/calls.json") { value = Fetched(it) } }
    val mat by produceState(st.repo.peek<CallsMat>("data/calls.json")) { st.repo.cacheFirst<CallsMat>("data/calls.json") { value = it } }
    val c = cf?.v
    val v = c?.calls.orEmpty().filter { it.kind == "verified" }
    AccScreen(st, "Track record", if (v.isEmpty()) "Verified Buys vs Nifty" else "Verified Buys since ${skDay(v.minOf { it.date })}", "Track record") {
        if (cf == null) { item { LoadingCard() }; item { LoadingCard(4) }; return@AccScreen }
        if (c == null) { item { Empty("The track record loads with an internet connection.") }; return@AccScreen }
        val sm = c.summary.now
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                T("Average vs Nifty, per Buy", LABEL, C.dim)
                T(vsNifty(sm?.avgVsNifty), 36.sp, plColor(sm?.avgVsNifty), FontWeight.ExtraBold, modifier = Modifier.padding(top = 2.dp, bottom = 12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Cell("Verified Buys", "${v.size}", Modifier.weight(1f))
                    Cell("Avg return", sg(sm?.avgPct), Modifier.weight(1f), plColor(sm?.avgPct))
                    Cell("Beat Nifty", sm?.beatPct?.let { "$it%" } ?: "–", Modifier.weight(1f))
                }
                sm?.beatPct?.let { b ->
                    SegmentedBar(listOf(Segment(b.toDouble(), TierC.lightGreen), Segment((100 - b).toDouble(), C.hi.copy(alpha = 0.18f))),
                        Modifier.padding(top = 12.dp).fillMaxWidth(), height = 6.dp, legend = SegLegend.None)
                }
                val ms = mat?.summary?.verified.orEmpty()
                Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    T("Matured:", 12.sp, C.dim)
                    listOf("1m", "3m", "6m", "12m").forEach { k ->
                        val s = ms[k]
                        Row(Modifier.clip(rr(8.dp)).background(C.sheet).padding(horizontal = 8.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                            T(k.uppercase(), 12.sp, C.dim)
                            T(if (s != null && s.n > 0) vsNifty(s.avgVsNifty) else "–", 12.sp, if (s != null && s.n > 0) plColor(s.avgVsNifty) else C.white, FontWeight.Medium)
                        }
                    }
                }
                if (ms.values.none { it.n > 0 }) T("Not enough history yet", 12.sp, C.dim, modifier = Modifier.padding(top = 8.dp))
            }
        }
        item { OnePortfolioCard(c.summary.portfolio) }
        item {
            val m = sm?.mix ?: CallMix()
            val now = listOf(m.multibagger + m.onTrack, m.beat, m.near, m.loser)
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    T("Outcome mix vs goal", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    T("${m.n} Buys", 12.sp, C.dim)
                }
                T("Goal per 10", 12.sp, C.dim, modifier = Modifier.padding(top = 10.dp, bottom = 4.dp))
                SegmentedBar(MIX_GOAL.map { Segment(it.second.toDouble(), it.third) }, height = 6.dp, legend = SegLegend.None)
                T("Now", 12.sp, C.dim, modifier = Modifier.padding(top = 10.dp, bottom = 4.dp))
                if (m.n > 0) SegmentedBar(now.mapIndexed { i, n -> Segment(n.toDouble(), MIX_GOAL[i].third) }, height = 14.dp, legend = SegLegend.None)
                else T("Fills in once calls are a day old (vs Nifty needs two closes)", 12.sp, C.dim)
                Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    MIX_GOAL.forEachIndexed { i, (name, goal, col) ->
                        Column(Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                StatusDot(col, size = 7.dp); T(name, 11.sp, C.dim, maxLines = 1)
                            }
                            Row(verticalAlignment = Alignment.Bottom) {
                                T(if (m.n > 0) "${now[i]}" else "–", 15.sp, weight = FontWeight.Bold); T(" / $goal", 12.sp, C.dim)
                            }
                        }
                    }
                }
            }
        }
        item { EveryBuyCard(st, v) }
    }
}

/** "As one portfolio": the verified Buys as one portfolio, sized by conviction (High 1, Medium ½, Low ¼), vs Nifty (calls.json summary.portfolio), or an empty state. */
@Composable
private fun OnePortfolioCard(p: CallPortfolio?) {
    val a = p?.curve.orEmpty().mapNotNull { it.getOrNull(1)?.content?.toDoubleOrNull() }
    val b = p?.curve.orEmpty().mapNotNull { it.getOrNull(2)?.content?.toDoubleOrNull() }
    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            T("As one portfolio", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            T(if (p != null) "sized by conviction · ${p.days} day${if (p.days == 1) "" else "s"}" else "sized by conviction", 12.sp, C.dim)
        }
        if (p == null || a.size < 2 || b.size != a.size) {
            T("Not enough history yet", 13.sp, C.dim, modifier = Modifier.padding(top = 10.dp, bottom = 2.dp))
            return@Card
        }
        Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.Bottom) {
            T(sg(p.returnPct), 20.sp, plColor(p.returnPct), FontWeight.Bold); T(" Buys    ", 13.sp, C.dim)
            T(sg(p.niftyPct), 20.sp, C.white, FontWeight.Bold); T(" Nifty", 13.sp, C.dim)
        }
        AreaLine(a, Modifier.padding(top = 8.dp).fillMaxWidth().height(110.dp), color = C.blue,
            overlays = listOf(Series(b, C.grey, "Nifty", 1.6.dp)), endLabel = "Buys", endLabelPos = EndLabel.Right, endLabelColor = C.blue,
            xLabels = listOfNotNull(p.since?.let { shortDate(it) }, "today"))
        Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Cell("Ahead of Nifty", p.excessPct?.let { sg(it, 1, " pts") } ?: "–", Modifier.weight(1f), plColor(p.excessPct))
            Cell("Days ahead", p.daysAheadPct?.let { "${it.toInt()}%" } ?: "–", Modifier.weight(1f))
        }
        Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Cell("Worst fall", p.maxDdPct?.let { fmt(it, 1) + "%" } ?: "–", Modifier.weight(1f), note = p.niftyMaxDdPct?.let { "Nifty ${fmt(it, 1)}%" })
            Cell("Sharpe", p.sharpe?.let { fmt(it, 2) } ?: "–", Modifier.weight(1f),
                note = if (p.sharpe == null) "after ${p.minDays} days (${p.days} of ${p.minDays})" else p.niftySharpe?.let { "Nifty ${fmt(it, 2)}" })
        }
    }
}

private fun callVs(c: CallRec): Double? = if (c.ended != null) c.toEndVsNifty else c.nowVsNifty

@Composable
private fun EveryBuyCard(st: AppState, v: List<CallRec>) {
    val sorted = v.sortedWith(compareBy<CallRec> { callVs(it) == null }.thenByDescending { callVs(it) ?: 0.0 })
    val mx = sorted.mapNotNull { callVs(it)?.let { x -> abs(x) } }.maxOrNull()?.takeIf { it > 0 } ?: 1.0
    var all by remember { mutableStateOf(false) }
    val shown = if (all) sorted else sorted.take(15)
    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            T("Every Buy vs Nifty", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            T("${v.count { it.ended == null }} open · ${v.count { it.ended != null }} closed", 12.sp, C.dim)
        }
        if (v.isEmpty()) { T("No verified Buy yet.", 13.sp, C.dim, modifier = Modifier.padding(top = 8.dp)); return@Card }
        Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.width(100.dp))
            Row(Modifier.weight(1f)) {
                T("← behind", 11.sp, C.dim, modifier = Modifier.weight(1f)); T("ahead →", 11.sp, C.dim)
            }
            T("pts", 11.sp, C.dim, modifier = Modifier.width(56.dp), align = TextAlign.End)
        }
        shown.forEachIndexed { i, c ->
            HLineDivider()
            BuyRow(c, mx, st.pick(c.symbol)) { st.go(Screen.Stock(c.symbol)) }
        }
        if (sorted.size > 15) MoreLink(if (all) "Show fewer" else "${sorted.size - 15} more Buys") { all = !all }
    }
}

/** One Buy: code and date, a bar left (behind Nifty) or right (ahead) of the centre line, points vs Nifty. Hollow bar = closed, "day 0" = no return yet. */
@Composable
private fun BuyRow(c: CallRec, mx: Double, p: P? = null, onClick: () -> Unit) = Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
    BuyBarRow(c, mx)
    exitLevelLines(c, p)?.let { (hit, still) ->
        Column(Modifier.padding(bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            ExitLine(C.amber) { T(hit, 11.5.sp, C.amber, lineHeight = 17.sp) }
            still?.let { (lead, rest) ->
                ExitLine(TierC.lightGreen) {
                    Text(buildAnnotatedString {
                        withStyle(SpanStyle(color = TierC.lightGreen, fontWeight = FontWeight.SemiBold)) { append(lead) }
                        withStyle(SpanStyle(color = C.muted)) { append(rest) }
                    }, fontSize = 11.5.sp, lineHeight = 17.sp)
                }
            }
        }
    }
}

@Composable
private fun ExitLine(dot: Color, content: @Composable () -> Unit) = Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
    Box(Modifier.padding(top = 6.dp).size(6.dp).clip(CircleShape).background(dot))
    content()
}

/**
 * feedback #92: a call closed on its exit level: "Closed · exit level ₹X hit on 20 Nov" and, while the stock is still rated Buy
 * (or still a candidate, for a candidate row), the re-entry rule as (bold lead, rest). Null when the call did not end on its exit level.
 */
fun exitLevelLines(c: CallRec, p: P?): Pair<String, Pair<String, String>?>? {
    if (c.ended == null || c.endDecision?.startsWith("Exit level") != true) return null
    val lvl = c.stop?.let { "₹" + skFx(it, 2) }
    val hit = "Closed · exit level" + (lvl?.let { " $it" } ?: "") + " hit on ${skDay(c.ended)}"
    val stillBuy = if (c.kind == "candidate") p?.cand == "Buy" || p?.dc == "Buy" else p?.dc == "Buy"
    val still = if (!stillBuy) null else {
        val lead = if (c.kind == "candidate" && p?.dc != "Buy") "Still a Buy candidate" else "Still rated Buy"
        val parts = listOfNotNull(lvl?.let { "above $it" }, c.reentryAfter?.let { "after ${skDay(it)}" })
        lead to (if (parts.isEmpty()) "" else " · re-entry " + parts.joinToString(" or "))
    }
    return hit to still
}

@Composable
private fun BuyBarRow(c: CallRec, mx: Double) {
    val closed = c.ended != null
    val v = callVs(c)
    val col = plColor(v)
    Row(Modifier.fillMaxWidth().defaultMinSize(minHeight = 46.dp).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.width(100.dp)) {
            T(c.symbol.substringBeforeLast("."), 13.sp, weight = FontWeight.SemiBold, maxLines = 1)
            T(skDay(c.date) + if (closed) " · closed" else "", 10.5.sp, C.dim, maxLines = 1)
        }
        Box(Modifier.weight(1f).height(20.dp)) {
            Canvas(Modifier.fillMaxSize()) {
                val cx = size.width / 2
                drawLine(C.hi.copy(alpha = 0.2f), Offset(cx, 0f), Offset(cx, size.height), 1.dp.toPx())
                if (v != null) {
                    val k = (cx - 4.dp.toPx()) / mx.toFloat(); val bh = 12.dp.toPx(); val top = (size.height - bh) / 2
                    val w = max(abs(v.toFloat()) * k, 3.dp.toPx()); val x = if (v >= 0) cx else cx - w
                    if (closed) {
                        drawRoundRect(col.copy(alpha = 0.2f), Offset(x, top), Size(w, bh), CornerRadius(bh / 2))
                        drawRoundRect(col, Offset(x, top), Size(w, bh), CornerRadius(bh / 2), style = Stroke(1.5.dp.toPx()))
                    } else drawRoundRect(col, Offset(x, top), Size(w, bh), CornerRadius(bh / 2))
                }
            }
            if (v == null) Row(Modifier.fillMaxSize()) {
                Spacer(Modifier.weight(1f))
                Box(Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.CenterStart) { T("day 0", 11.sp, C.dim, modifier = Modifier.padding(start = 6.dp)) }
            }
        }
        T(if (v == null) "–" else sg(v, 2, ""), 13.sp, col, FontWeight.SemiBold, modifier = Modifier.width(56.dp), maxLines = 1, align = TextAlign.End)
    }
}

// ---------------------------------------------------------------- a06 Data and pipeline
private fun coverageColor(p: Double) = if (p >= 0.95) TierC.lightGreen else C.amber

private data class SrcRow(val name: String, val figure: String, val pct: Double?)

@Composable
fun DataPipelineScreen(st: AppState) {
    // Fetched: null while loading (placeholders), Fetched(null) when the file is missing or offline (empty text)
    // cache-first: memory / phone copy at once, then the network copy if it changed
    val hhF by produceState(st.repo.peek2<Health, HealthU>("data/health.json")?.let { Fetched(it) }) {
        st.repo.cacheFirst2<Health, HealthU>("data/health.json") { value = Fetched(it) } }
    val iiF by produceState(st.repo.peek2<IssuesFile, IssuesU>("data/data_issues.json")?.let { Fetched(it) }) {
        st.repo.cacheFirst2<IssuesFile, IssuesU>("data/data_issues.json") { value = Fetched(it) } }
    val schedF by produceState(st.repo.peekF<Schedule>("data/schedule.json")) { st.repo.cacheFirst<Schedule>("data/schedule.json") { value = Fetched(it) } }
    val runsF by produceState(st.repo.peekF<List<RunRec>>("data/runs.json")) { st.repo.cacheFirst<List<RunRec>>("data/runs.json") { value = Fetched(it) } }
    val hh = hhF?.v; val ii = iiF?.v; val sched = schedF?.v; val runs = runsF?.v
    val scope = rememberCoroutineScope()
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    // feedback #208 (owner, 27 Nov 2026): one screen: a status card (state, last and next run, the run chart shrunk into it),
    // the sources as a 2-column grid of numbers, one tab row for the four lists (one open at a time)
    var tab by rememberSaveable { mutableStateOf("Problems") }
    AccScreen(st, "Data and pipeline", null, "Data") {
        val h = hh?.first
        val next = nextDailyRun()
        val nProb = h?.problems?.size ?: 0
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 14.dp) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    StatusDot(if (h == null) C.grey else if (nProb > 0) C.amber else TierC.lightGreen, size = 9.dp)
                    if (hhF == null) Skel(130.dp, 22.dp, Modifier.weight(1f))
                    else T(if (h == null) "Data of ${shortDate(st.picks?.date)}" else if (nProb == 0) "No problems" else "$nProb problem${if (nProb > 1) "s" else ""}",
                        18.sp, weight = FontWeight.Bold, maxLines = 1, modifier = Modifier.weight(1f))
                    runs?.takeIf { it.size >= 2 }?.let { MiniRuns(it.reversed().takeLast(30), 120.dp, 22.dp) }
                }
                T(listOfNotNull(h?.let { "Last run ${istTime(it.finished)} IST" }, h?.minutes?.let { "${fmt(it, 1)} min" },
                    "next daily run ${next.removePrefix("today ")}").joinToString(" · "),
                    12.5.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 4.dp))
                Row(Modifier.padding(top = 10.dp)) {
                    HeaderPill(Icons.Rounded.Refresh, "Check for data") {
                        scope.launch {
                            val before = st.picks?.updated
                            st.load()
                            st.toast = if (st.picks?.updated == before) "Already latest: data of ${shortDate(st.picks?.date)}. Next update $next"
                                       else "Updated to data of ${shortDate(st.picks?.date)}"
                        }
                    }
                }
            }
        }
        item { SecHead("Sources", "coverage of the universe") }
        item {
            val rows = if (hh == null) emptyList() else sourceRows(hh.first, hh.second)
            Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (hhF == null) SkelLines(4)
                else if (rows.isEmpty()) T("Source coverage appears after the next daily run.", 13.sp, C.dim)
                rows.chunked(2).forEach { pair ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        pair.forEach { r ->
                            Column(Modifier.weight(1f).clip(rr(6.dp)).background(C.card).border(1.dp, C.line, rr(6.dp)).padding(horizontal = 10.dp, vertical = 7.dp)) {
                                T(r.name, 12.sp, C.dim, maxLines = 1)
                                Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    if (r.pct != null) T("${fmt(r.pct * 100, 1)}%", 17.sp, coverageColor(r.pct), FontWeight.Bold, maxLines = 1)
                                    else T("✓", 17.sp, TierC.lightGreen, FontWeight.Bold, maxLines = 1)
                                    T(r.figure, 11.sp, C.dim, maxLines = 1, modifier = Modifier.padding(bottom = 2.dp))
                                }
                            }
                        }
                        if (pair.size == 1) Spacer(Modifier.weight(1f))
                    }
                }
            }
        }
        val s = sched
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth().clip(rr(6.dp)).border(1.dp, C.line, rr(6.dp))) {
                listOf("Problems" to (h?.let { "$nProb" } ?: ""), "Schedule" to (s?.let { "${it.jobs.size}" } ?: ""), "Runs" to (runs?.let { "${it.size}" } ?: ""),
                    "Details" to "").forEach { (k, n) ->
                    val on = tab == k
                    Box(Modifier.weight(1f).background(if (on) C.white else Color.Transparent).clickable { tab = k }.padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
                        T(if (n.isEmpty()) k else "$k $n", 12.sp, if (on) C.bg else C.dim, FontWeight.SemiBold, maxLines = 1)
                    }
                }
            }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 14.dp) {
              when (tab) {
              "Problems" -> {
                if (hhF == null) SkelLines(3)
                else if (h != null) {
                    T(if (h.problems.isEmpty()) "No problems in the last run" else "Lines flagged in the last run", LABEL, C.dim, FontWeight.SemiBold)
                    h.problems.take(40).forEach { T(it, 12.sp, C.amber, lineHeight = 16.sp, modifier = Modifier.padding(vertical = 3.dp)) }
                }
                val iss = ii
                T("Data issues", LABEL, C.dim, FontWeight.SemiBold,
                    Modifier.padding(top = 12.dp))
                if (iiF == null) SkelLines(3)
                else if (iss == null || iss.first.issues.isEmpty()) T("No data issue logged yet. Audits add them as they find wrong numbers.", 13.sp, C.dim)
                else {
                    T("${iss.first.open} open (${iss.first.openSystemic} systemic) · ${iss.first.corrected} corrected", 13.sp, weight = FontWeight.SemiBold)
                    iss.first.issues.values.sortedWith(compareBy<DataIssue> { it.status != "open" }.thenByDescending { it.firstSeen }).take(30).forEach { d ->
                        Column(Modifier.padding(top = 8.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                T(d.symbol.substringBeforeLast("."), 13.sp, weight = FontWeight.SemiBold)
                                TypeTag(d.scope, if (d.scope == "systemic") C.amber else C.grey)
                                val done = d.status == "corrected" || d.status == "fixed"
                                T(if (done) d.status + (d.fixedOn?.let { " " + skDay(it) } ?: "") else d.status, 11.sp, if (done) TierC.lightGreen else TierC.lightRed)
                            }
                            T("${d.field}: app ${d.app ?: "–"} → filed ${d.found ?: "–"}", 12.sp, C.dim)
                            d.cause?.let { T(it.replaceFirstChar { c -> c.uppercase() }, 12.sp) }
                        }
                    }
                }
              }
              "Schedule" -> {
                if (schedF == null) SkelLines(4)
                else if (s == null) T("The schedule appears after the next daily run.", 13.sp, C.dim) else {
                    s.note?.let { T(it, 11.sp, C.dim, lineHeight = 15.sp, modifier = Modifier.padding(bottom = 6.dp)) }
                    val reviewsToday = st.research.values.count { it.updated == today }
                    s.jobs.forEach { j ->
                        val status = when {
                            j.name.startsWith("Daily run") && st.picks?.date == today -> "done" to TierC.lightGreen
                            (j.by == "Claude" || j.by == "Narrativ.ai") && j.name.startsWith("Research") && reviewsToday > 0 -> "$reviewsToday stocks" to TierC.lightGreen
                            else -> null
                        }
                        Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                            Column(Modifier.width(118.dp)) { T(j.time, 12.sp, weight = FontWeight.SemiBold); T(j.days, 11.sp, C.dim) }
                            T(j.name, 12.sp, modifier = Modifier.weight(1f).padding(horizontal = 6.dp), lineHeight = 15.sp)
                            if (status != null) T(status.first, 11.sp, status.second, FontWeight.SemiBold) else T(if (j.by == "Claude") "Narrativ.ai" else j.by, 11.sp, C.dim)
                        }
                    }
                }
              }
              "Runs" -> {
                val rs = runs
                if (runsF == null) SkelLines(4)
                else if (rs.isNullOrEmpty()) T("Run history appears after the next daily run.", 13.sp, C.dim)
                else rs.forEach { x ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                        T("${shortDate(x.date)} · finished ${istTime(x.finished)}", 13.sp, modifier = Modifier.weight(1f), maxLines = 1)
                        T("${fmt(x.minutes, 1)} min", 13.sp, C.dim); Spacer(Modifier.width(12.dp))
                        T(if (x.problems == 0) "OK" else "${x.problems} problem${if (x.problems > 1) "s" else ""}", 13.sp, if (x.problems == 0) TierC.lightGreen else C.amber)
                    }
                }
              }
              else -> {
                if (hhF == null) SkelLines(4)
                else if (h == null) T("Pipeline health appears after the next daily run.", 13.sp, C.dim)
                else {
                T("Stages · minutes in the last run", LABEL, C.dim, FontWeight.SemiBold)
                val total = h.stages.sumOf { it.getOrNull(1)?.content?.toDoubleOrNull() ?: 0.0 }.coerceAtLeast(1.0)
                h.stages.forEach { sg0 ->
                    val name = sg0.getOrNull(0)?.content ?: ""; val sec = sg0.getOrNull(1)?.content?.toDoubleOrNull() ?: 0.0
                    Column(Modifier.padding(vertical = 4.dp)) {
                        Row { T(name.replaceFirstChar { it.uppercase() }, 13.sp, modifier = Modifier.weight(1f)); T("${fmt(sec / 60, 1)} min", 13.sp, C.dim) }
                        ProgBar((sec / total).toFloat(), C.grey, Modifier.padding(top = 3.dp).fillMaxWidth(), height = 4.dp)
                    }
                }
                T("Stores after the last run", LABEL, C.dim, FontWeight.SemiBold, Modifier.padding(top = 12.dp))
                h.sources.forEach { (k, m) ->
                    Column(Modifier.padding(vertical = 4.dp)) {
                        T(k.replaceFirstChar { it.uppercase() }, 13.sp, weight = FontWeight.SemiBold)
                        T(m.entries.joinToString(" · ") { (a, b) -> "${a.replace('_', ' ')} ${b.content}" }, 12.sp, C.dim)
                    }
                }
                T("Check coverage · stocks with data", LABEL, C.dim, FontWeight.SemiBold, Modifier.padding(top = 12.dp))
                LEVELS.forEachIndexed { i, lk ->
                    val rows = h.checks.filter { it.level == lk }
                    if (rows.isNotEmpty()) {
                        T(LEVEL_SHORT[i], 13.sp, weight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
                        rows.forEach { c ->
                            val tot = (c.data + c.noData + c.pending).coerceAtLeast(1); val p = c.data * 100 / tot
                            Row(Modifier.padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                                T(c.id, 11.sp, C.dim, modifier = Modifier.width(30.dp))
                                T(c.name, 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
                                T("$p%", 12.sp, if (c.pending > 0 && c.data == 0) TierC.lightRed else if (p >= 80) TierC.lightGreen else C.amber, FontWeight.SemiBold)
                            }
                        }
                    }
                }
                T("Where each number comes from", LABEL, C.dim, FontWeight.SemiBold, Modifier.padding(top = 12.dp))
                SOURCES.forEach { x ->
                    var open by remember { mutableStateOf(false) }
                    Column(Modifier.fillMaxWidth().clickable { open = !open }.padding(vertical = 6.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T(x.name, 13.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                            T(x.freq, 11.sp, C.dim, maxLines = 1, modifier = Modifier.widthIn(max = 150.dp)); T(if (open) " ▴" else " ›", 13.sp, C.dim)
                        }
                        if (open) {
                            T(x.what, 12.sp, C.muted, lineHeight = 16.sp, modifier = Modifier.padding(top = 4.dp))
                            listOf("Source" to x.from, "Coverage" to x.cover).forEach { (k, v) ->
                                Row(Modifier.padding(top = 2.dp)) { T(k, 11.sp, C.dim, modifier = Modifier.width(70.dp)); T(v, 11.sp, C.grey, modifier = Modifier.weight(1f)) }
                            }
                        }
                    }
                }
                }
              }
              }
            }
        }
    }
}

/** Source coverage rows from health.json: a share of the universe where there is a total to measure against, else just the count. */
private fun sourceRows(h: Health, u: HealthU): List<SrcRow> {
    fun n(src: String, key: String): Int? = h.sources[src]?.get(key)?.content?.toIntOrNull()
    val out = ArrayList<SrcRow>()
    val uni = u.universe?.takeIf { it > 0 }
    n("prices", "stocks")?.let { out += SrcRow("Prices", fmt(it.toDouble(), 0), uni?.let { t -> it.toDouble() / t }) }
    n("filings", "stocks")?.let { out += SrcRow("Results (NSE)", fmt(it.toDouble(), 0), null) }
    n("bse_results", "with_results")?.let { w -> n("bse_results", "companies")?.takeIf { it > 0 }?.let { t -> out += SrcRow("Results (BSE)", "$w of $t", w.toDouble() / t) } }
    val prob = h.problems.joinToString(" ")
    val done = Regex("'complete': (\\d+)").find(prob)?.groupValues?.get(1)?.toIntOrNull() ?: n("shareholding", "stocks")
    val tot = Regex("of (\\d+) NSE stocks").find(prob)?.groupValues?.get(1)?.toIntOrNull() ?: n("filings", "stocks")
    if (done != null && tot != null && tot > 0) out += SrcRow("Shareholding", "${fmt(done.toDouble(), 0)} of ${fmt(tot.toDouble(), 0)}", done.toDouble() / tot)
    n("announcements", "companies")?.let { out += SrcRow("Announcements", fmt(it.toDouble(), 0), null) }
    n("corporate filings", "insider")?.let { out += SrcRow("Corp. filings", "${fmt(it.toDouble(), 0)} insider", null) }
    n("NSE daily files", "delivery_days")?.let { out += SrcRow("NSE daily", "$it days", null) }
    n("research", "researched")?.let { out += SrcRow("Research", "$it reviewed", null) }
    return out
}

// ---------------------------------------------------------------- a07 Research queue
/** Queue task -> colour (task names and meanings are in QUEUE_TASKS). */
private val TASK_COLOR get() = mapOf("review" to TierC.lightGreen, "review_flag" to C.amber, "recheck" to C.grey, "enrich" to C.muted)
fun queueTaskColor(task: String?): Color = TASK_COLOR[task] ?: C.dim
fun queueTaskName(task: String?): String = (QUEUE_TASKS[task] ?: QUEUE_TASKS.getValue("scan")).first

@Composable
fun ResearchQueueScreen(st: AppState) {
    val q = st.queue
    var tab by remember { mutableStateOf("waiting") }
    var info by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("All") }
    var qFilter by remember { mutableStateOf("All") }
    var search by remember { mutableStateOf("") }  // feedback #188: one search over the queue and completed work
    val focus = LocalFocusManager.current
    val done by produceState<DoneFile?>(null) { value = st.repo.get<DoneFile>("data/research_done.json") }
    val nDone = done?.runs.orEmpty().sumOf { r -> r.items.size }
    if (info) QueueInfoSheet { info = false }
    // feedback #116: swipe left / right switches Waiting and Completed
    val swipe = Modifier.pointerInput(Unit) {
        var dx = 0f
        detectHorizontalDragGestures(onDragStart = { dx = 0f }, onDragEnd = {
            if (dx < -120f) tab = "completed" else if (dx > 120f) tab = "waiting"
        }) { _, d -> dx += d }
    }
    AccScreen(st, "Research queue", q?.let { "${it.items.size} waiting · queue of ${shortDate(it.date)}" }, "Queue",
        actions = { InfoButton { info = true } }, modifier = swipe) {
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("waiting" to "Waiting ${q?.items?.size ?: 0}", "completed" to "Completed $nDone").forEach { (k, lab) ->
                    Box(Modifier.weight(1f).clip(rr(10.dp)).background(if (tab == k) C.teal else C.card).clickable { tab = k }.padding(vertical = 9.dp),
                        contentAlignment = Alignment.Center) { T(lab, 13.sp, if (tab == k) C.onAccent else C.dim, if (tab == k) FontWeight.SemiBold else FontWeight.Normal) }
                }
            }
        }
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth().clip(rr(14.dp)).background(C.hi.copy(alpha = 0.07f))
                .padding(horizontal = 12.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Search, null, tint = C.dim, modifier = Modifier.size(20.dp)); Spacer(Modifier.width(8.dp))
                BasicTextField(search, { search = it }, singleLine = true, textStyle = TextStyle(color = C.white, fontSize = 15.sp), cursorBrush = SolidColor(C.blue),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { focus.clearFocus() }),
                    modifier = Modifier.weight(1f),
                    decorationBox = { inner -> if (search.isEmpty()) T("Search queue and done…", 15.sp, C.dim); inner() })
                if (search.isNotEmpty()) Icon(Icons.Rounded.Close, "Clear", tint = C.dim, modifier = Modifier.clip(CircleShape).clickable { search = "" }.size(20.dp))
            }
        }
        if (search.isNotBlank()) { queueSearch(st, q, done, search); return@AccScreen }
        if (tab == "completed") { completedList(st, done, filter) { filter = it }; return@AccScreen }
        if (q == null || q.items.isEmpty()) { item { Empty("The queue appears after the next daily run.") }; return@AccScreen }
        // owner, 27 Nov 2026: no "All N done by" heading or task chart; one filter button; rows by expected time, first to last
        val etas = queueEtas(q.items.map { it.task })
        val rows = q.items.indices.map { q.items[it] to etas.getOrNull(it)?.first }
            .filter { (it, _) -> qFilter == "All" || (it.task ?: "scan") == qFilter }
            .sortedBy { (_, e) -> e }
        item {
            val mix = q.items.groupingBy { it.task ?: "scan" }.eachCount()
            FilterMenu(listOf(Triple("All", "All", q.items.size)) + mix.entries.sortedByDescending { it.value }.map { Triple(it.key, queueTaskName(it.key), it.value) },
                qFilter, { k -> queueTaskColor(k) }) { qFilter = it }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                rows.forEachIndexed { n, (it, e) ->
                    QueueRow(st, it, e)
                    if (n < rows.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
                }
            }
        }
    }
}

/** One filter button with a menu: label, count and colour dot per option; the button names the chosen option (owner, 27 Nov 2026). */
@Composable
fun FilterMenu(options: List<Triple<String, String, Int>>, selected: String, color: (String) -> Color?, onSelect: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val cur = options.firstOrNull { it.first == selected } ?: options.first()
    Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Box {
            CtlButton(Icons.Rounded.Tune, if (cur.first == "All") "Filter" else "${cur.second} · ${cur.third}", cur.first != "All") { open = true }
            DropdownMenu(open, { open = false }, containerColor = C.chip) {
                options.forEach { (k, lab, n) ->
                    DropdownMenuItem(text = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            val dot = if (k == "All") null else color(k)
                            Box(Modifier.padding(end = 8.dp).size(8.dp).clip(CircleShape).background(dot ?: Color.Transparent))
                            Text("$lab  $n", color = if (k == cur.first) C.blue else C.white, fontSize = 14.sp)
                        }
                    }, onClick = { onSelect(k); open = false })
                }
            }
        }
    }
}

/** One queued item: task colour, symbol, task name ("Review N of M" for a full review), expected run. */
@Composable
private fun QueueRow(st: AppState, it: QItem, eta: java.time.LocalDateTime?) {
    val col = queueTaskColor(it.task)
    // one count everywhere: a full review says "Review N of M" (its place among pending reviews, as on the stock page);
    // other tasks keep their own name, with no competing number
    val label = (if (it.task == "review") queueLabel(st, it.symbol) else null) ?: queueTaskName(it.task)
    Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(it.symbol)) }.defaultMinSize(minHeight = 52.dp).padding(horizontal = 14.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.padding(end = 12.dp).size(3.dp, 30.dp).clip(rr(2.dp)).background(col))
        Column(Modifier.weight(1f)) {
            T(it.symbol.substringBeforeLast("."), 15.sp, weight = FontWeight.SemiBold, maxLines = 1)
            T(label, 12.sp, col, FontWeight.SemiBold, maxLines = 1)  // #117: no "rules say Buy" line; meanings behind (i)
        }
        eta?.let { e -> T(etaWords(e), 12.sp, C.blue.takeIf { Look.paper } ?: C.muted, maxLines = 1, modifier = Modifier.padding(start = 8.dp)) }
    }
}

/** Search text matches a stock: symbol with or without .NS / .BO, or its company name (case-insensitive). */
fun queueMatch(st: AppState, sym: String?, name: String?, q: String): Boolean {
    val k = q.trim().lowercase()
    if (k.isEmpty() || sym == null) return false
    val nm = (st.pick(sym)?.n?.ifBlank { null } ?: name ?: "").lowercase()
    return sym.lowercase().contains(k) || sym.substringBeforeLast(".").lowercase().contains(k) || nm.contains(k)
}

/** Feedback #188: matches in the queue and in completed work, in two sections with counts. */
fun LazyListScope.queueSearch(st: AppState, q: QueueFile?, d: DoneFile?, text: String) {
    val items = q?.items.orEmpty()
    val etas = queueEtas(items.map { it.task })
    val inQ = items.indices.filter { queueMatch(st, items[it].symbol, items[it].name, text) }
    val inDone = d?.runs.orEmpty().flatMap { r -> r.items.map { r to it } }.filter { (_, x) -> queueMatch(st, x.s, null, text) }
    item { T("In queue (${inQ.size})", 13.sp, C.dim, FontWeight.SemiBold, modifier = Modifier.padding(start = 20.dp, top = 10.dp, bottom = 4.dp)) }
    if (inQ.isNotEmpty()) item {
        Card(Modifier.padding(horizontal = 16.dp, vertical = 2.dp).fillMaxWidth(), pad = 0.dp) {
            inQ.forEachIndexed { n, i ->
                QueueRow(st, items[i], etas.getOrNull(i)?.first)
                if (n < inQ.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
            }
        }
    }
    item { T("Done (${inDone.size})" + (d?.let { " · last ${it.days} days" } ?: ""), 13.sp, C.dim, FontWeight.SemiBold,
        modifier = Modifier.padding(start = 20.dp, top = 14.dp, bottom = 4.dp)) }
    if (inDone.isNotEmpty()) item {
        Card(Modifier.padding(horizontal = 16.dp, vertical = 2.dp).fillMaxWidth(), pad = 0.dp) {
            inDone.forEachIndexed { n, (r, x) ->
                DoneRow(st, x, doneRunTime(r))
                if (n < inDone.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
            }
        }
    }
    if (inQ.isEmpty() && inDone.isEmpty()) item { Empty("No stock in the queue or in completed work matches \"${text.trim()}\".") }
}

// Research runs (RESEARCH.md / KNOWLEDGE.md): full reviews and flags in the 5 review slots, at most 8 a run; rechecks and
// catalysts in the 3 catalyst slots (07:05 12:05 16:05 IST), at most 15 a run. The estimate assumes every run does its maximum.
val REVIEW_TASKS = setOf("review", "review_flag", "audit")
const val REVIEW_PER_RUN = 8
const val CATALYST_PER_RUN = 15
val CATALYST_SLOTS = listOf(7 * 60 + 5, 12 * 60 + 5, 16 * 60 + 5)

/** The run each queued item is expected in, in queue order: (date-time of the run, slot minutes). */
fun queueEtas(tasks: List<String?>): List<Pair<java.time.LocalDateTime, Int>> {
    val now = java.time.LocalDateTime.now(java.time.ZoneId.of("Asia/Kolkata"))
    fun runAt(k: Int, slots: List<Int>): java.time.LocalDateTime {
        val m = now.hour * 60 + now.minute
        val first = slots.indexOfFirst { it > m }.let { if (it < 0) slots.size else it }
        val idx = first + k; val slot = slots[idx % slots.size]
        return now.toLocalDate().plusDays((idx / slots.size).toLong()).atTime(slot / 60, slot % 60)
    }
    var r = 0; var c = 0
    return tasks.map { t ->
        if (t in REVIEW_TASKS) runAt(r++ / REVIEW_PER_RUN, RESEARCH_SLOTS).let { it to 0 } else runAt(c++ / CATALYST_PER_RUN, CATALYST_SLOTS).let { it to 1 }
    }
}

/** "today 14:05", "tomorrow 04:05", "Fri 27 Nov 04:05". */
fun etaWords(t: java.time.LocalDateTime): String {
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata"))
    val hm = "%02d:%02d".format(t.hour, t.minute)
    return when (t.toLocalDate()) {
        today -> "today $hm"; today.plusDays(1) -> "tomorrow $hm"
        else -> t.dayOfWeek.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH) + " " + skDay(t.toLocalDate().toString()) + " " + hm
    }
}

/** (i) on the Research queue (feedback #117): what each task and each result means. */
@Composable
fun QueueInfoSheet(onDismiss: () -> Unit) {
    BottomSheet(onDismiss, "What the queue means") {
        PaperLabel("Waiting", size = 11.sp, modifier = Modifier.padding(bottom = 4.dp))
        QUEUE_TASKS.filterKeys { it in setOf("review", "recheck", "enrich", "review_flag") }.forEach { (k, v) ->
            Column(Modifier.padding(vertical = 4.dp)) { T(v.first, 13.sp, queueTaskColor(k), FontWeight.SemiBold); T(v.second, 12.sp, C.muted, lineHeight = 16.sp) }
        }
        PaperLabel("Completed · results", size = 11.sp, modifier = Modifier.padding(top = 10.dp, bottom = 4.dp))
        listOf(Triple("Pass", TierC.darkGreen, "Numbers confirmed, no issue that changes the case."),
            Triple("Caution", C.amber, "The case holds, but an issue needs watching."),
            Triple("Fail", C.red, "A number is materially wrong or an issue breaks the case."),
            Triple("Flags checked", C.white, "Red flags from filings looked at: dismissed or confirmed.")).forEach { (n, c, d) ->
            Row(Modifier.padding(vertical = 3.dp)) { T(n, 12.sp, c, FontWeight.SemiBold, modifier = Modifier.width(96.dp)); T(d, 12.sp, C.muted, lineHeight = 16.sp) }
        }
        T("Times are estimates: full reviews at most $REVIEW_PER_RUN a run (04:05 09:05 14:05 18:05 23:05), rechecks and catalysts at most $CATALYST_PER_RUN a run (07:05 12:05 16:05).",
            11.sp, C.dim, lineHeight = 15.sp, modifier = Modifier.padding(top = 10.dp))
    }
}

// ---------------------------------------------------------------- a09 Version and release notes
/** Release-note tag: one word, sentence case, the same grey chip everywhere (tags are not tappable, so never blue). */
fun changeTag(type: String): String = when (type) {
    "new" -> "New"; "change", "changed" -> "Changed"; "imp", "improved" -> "Improved"; "fix", "fixed" -> "Fix"; else -> type.replaceFirstChar { it.uppercase() }
}

/** One change in release notes (Release notes screen, older releases, update dialog). */
@Composable
fun ChangeLine(c: Change) {
    Row(Modifier.padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.width(70.dp).clip(rr(S.inner)).background(C.chip).padding(vertical = 3.dp), contentAlignment = Alignment.Center) {
            T(changeTag(c.type), 11.sp, C.muted, FontWeight.SemiBold, maxLines = 1)
        }
        T(c.text, 14.sp, lineHeight = 19.sp, modifier = Modifier.weight(1f))
    }
}

/** Changes per release as small bars, oldest left. */
@Composable
private fun ChangeBars(rs: List<Release>, modifier: Modifier = Modifier.size(70.dp, 22.dp)) {
    if (rs.isEmpty()) return
    Canvas(modifier) {
        val mx = rs.maxOf { it.changes.size }.coerceAtLeast(1); val bw = size.width / rs.size
        rs.reversed().forEachIndexed { i, r ->
            val h = (r.changes.size.toFloat() / mx * size.height).coerceAtLeast(2.dp.toPx())
            drawRoundRect(C.grey.copy(alpha = 0.7f), Offset(i * bw + 1.dp.toPx(), size.height - h), Size(bw - 3.dp.toPx(), h), CornerRadius(2.dp.toPx()))
        }
    }
}

@Composable
fun ReleaseNotesScreen(st: AppState) {
    val v = st.version
    val scope = rememberCoroutineScope()
    var allNew by remember { mutableStateOf(false) }
    var older by remember { mutableStateOf(false) }
    // version.json normally comes with the app's load; if it is not here yet, fetch it once so loading and offline differ
    val tried by produceState(st.version != null) {
        if (st.version == null) st.repo.get<VersionInfo>("app/version.json")?.let { st.version = it }
        value = true
    }
    AccScreen(st, "Release notes", null, "Release notes") {
        val newer = (v?.versionCode ?: 0) > BuildConfig.VERSION_CODE
        val rel = v?.changelog?.firstOrNull { it.version == BuildConfig.VERSION_NAME } ?: v?.changelog?.firstOrNull()
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        T("v${BuildConfig.VERSION_NAME}", 26.sp, weight = FontWeight.ExtraBold)
                        T("installed" + (v?.changelog?.firstOrNull { it.version == BuildConfig.VERSION_NAME }?.let { " · released ${skDay(it.date)}" } ?: ""), 12.sp, C.dim)
                    }
                    val col = if (newer) C.amber else TierC.lightGreen
                    Row(Modifier.clip(rr(12.dp)).background(col.copy(alpha = 0.13f)).padding(horizontal = 10.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        StatusDot(col); T(if (newer) "Update available" else "Up to date", 12.sp, col, FontWeight.SemiBold, maxLines = 1)
                    }
                }
                PrimaryButton(if (newer) "Install v${v?.versionName}" else "Check for updates", Modifier.padding(top = 14.dp).fillMaxWidth()) {
                    if (newer) st.showUpdate = true
                    else scope.launch { st.repo.get<VersionInfo>("app/version.json")?.let { st.version = it; if (it.versionCode > BuildConfig.VERSION_CODE) st.showUpdate = true else st.toast = "Up to date" } }
                }
            }
        }
        if (v == null && !tried) { item { LoadingCard(5) }; return@AccScreen }
        if (v == null || rel == null) { item { Empty("Release notes load with an internet connection.") }; return@AccScreen }
        item {
            val cnt = rel.changes.groupingBy { it.type }.eachCount().entries.sortedByDescending { it.value }
            SecHead("What's new in v${rel.version}", cnt.joinToString(" · ") { (k, n) ->
                n.toString() + " " + when (k) { "new" -> "new"; "fix" -> if (n > 1) "fixes" else "fix"; "change", "changed" -> "changed"; "imp", "improved" -> "improved"; else -> k } })
        }
        item {
            val shown = if (allNew) rel.changes else rel.changes.take(5)
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 14.dp) {
                shown.forEach { ChangeLine(it) }
                if (rel.changes.size > 5) MoreLink(if (allNew) "Show fewer" else "${rel.changes.size - 5} more changes") { allNew = !allNew }
            }
        }
        val olderRel = v.changelog.filter { it.version != rel.version }
        if (olderRel.isNotEmpty()) item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth(), pad = 0.dp) {
                Row(Modifier.fillMaxWidth().clickable { older = !older }.height(52.dp).padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    T("Older releases", 14.sp, modifier = Modifier.weight(1f))
                    T("${olderRel.size} releases", 12.sp, C.dim); Spacer(Modifier.width(10.dp))
                    ChangeBars(olderRel.take(7))
                    androidx.compose.material3.Icon(if (older) Icons.Rounded.ExpandLess else Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.padding(start = 6.dp).size(18.dp))
                }
                if (older) Column(Modifier.padding(horizontal = 14.dp, vertical = 4.dp)) { olderRel.take(10).forEach { r -> HLineDivider(); ReleaseNotes(r) } }
            }
        }
    }
}

// ---------------------------------------------------------------- a10 Feedback list
@Composable
fun FeedbackScreen(st: AppState) {
    val data by produceState<Fetched<Pair<List<FbItem>, Pair<Int, Int>>>?>(null) {
        value = Fetched(st.repo.apiGet("feedback/stats")?.let { o ->
            val items = runCatching { json.decodeFromJsonElement(kotlinx.serialization.builtins.ListSerializer(FbItem.serializer()), o["items"]!!) }.getOrDefault(emptyList())
            items to ((o["open"]?.toString()?.toIntOrNull() ?: 0) to (o["closed"]?.toString()?.toIntOrNull() ?: 0))
        })
    }
    var state by remember { mutableStateOf("open") }
    var type by remember { mutableStateOf<String?>(null) }
    AccScreen(st, "Feedback", null, "Feedback") {
        if (data == null) { item { LoadingCard(1) }; item { LoadingCard(2) }; return@AccScreen }
        val d = data?.v
        if (d == null) { item { Empty("Feedback loads with an internet connection.") }; return@AccScreen }
        item {
            val (open, closed) = d.second
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 14.dp) {
                Row {
                    listOf("open" to open, "closed" to closed).forEach { (k, n) ->
                        val on = state == k
                        Row(Modifier.weight(1f).clip(rr(8.dp)).clickable { state = k }.padding(vertical = 2.dp), verticalAlignment = Alignment.Bottom,
                            horizontalArrangement = if (k == "open") Arrangement.Start else Arrangement.End) {
                            T(k.replaceFirstChar { it.uppercase() }, 13.sp, if (on) C.white else C.dim)
                            T("  $n", 20.sp, if (on) C.white else C.dim, FontWeight.Bold)
                        }
                    }
                }
                SegmentedBar(listOf(Segment(open.toDouble(), C.muted), Segment(closed.toDouble(), C.hi.copy(alpha = 0.2f))),
                    Modifier.padding(top = 10.dp).fillMaxWidth(), height = 10.dp, gap = 3.dp, legend = SegLegend.None)
            }
        }
        val types = d.first.map { it.type }.distinct().sorted()
        item {
            Row(Modifier.fillMaxWidth().horizontalScroll(androidx.compose.foundation.rememberScrollState()).padding(horizontal = 16.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (listOf<String?>(null) + types).forEach { t -> ToggleChip(t ?: "All", type == t, { type = t }) }
            }
        }
        val list = d.first.filter { it.state == state && (type == null || it.type == type) }
        if (list.isEmpty()) item { Empty("Nothing here.") }
        list.forEach { f ->
            item {
                Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 14.dp) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TypeTag(f.type, if (f.type == "Bug") TierC.lightRed else C.grey)
                        T("#${f.n} · ${skDay(f.date)}", 11.sp, C.dim, modifier = Modifier.weight(1f), align = TextAlign.End)
                    }
                    T(f.text.replaceFirstChar { it.uppercase() }, 14.sp, lineHeight = 19.sp, maxLines = 4, modifier = Modifier.padding(top = 8.dp))
                    if (f.screen.isNotBlank()) T(f.screen, 11.sp, C.dim, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
    }
}


/** Research queue > Completed: what each research run finished (docs/data/research_done.json, last 7 days, newest first). */
/** The filter group of a completed item (feedback #115). */
fun doneGroup(r: String?): String {
    val x = r ?: ""
    return when {
        x == "pass" -> "Pass"; x == "caution" -> "Caution"; x == "fail" -> "Fail"
        x.startsWith("review_flag") || "flag" in x -> "Flags checked"
        x.startsWith("enrich") || x.startsWith("fund_use") -> "Catalyst"
        x.startsWith("recheck") || x.startsWith("skipped") || "no change" in x -> "Recheck"
        else -> "Other"
    }
}
fun doneGroupColor(g: String): Color = when (g) {
    "Pass" -> TierC.darkGreen; "Caution" -> C.amber; "Fail" -> C.red; "Recheck" -> C.grey; "Catalyst" -> TierC.lime; "Flags checked" -> C.white; else -> C.dim
}

/** A research run's start in IST, "27 Nov 04:05" (the raw start when it does not parse). */
fun doneRunTime(r: DoneRun): String {
    val t = runCatching { java.time.OffsetDateTime.parse(r.start.replace("+00:00", "Z").let { if (it.length == 17) it.dropLast(1) + ":00Z" else it })
        .atZoneSameInstant(java.time.ZoneId.of("Asia/Kolkata")) }.getOrNull()
    return t?.let { "${skDay(it.toLocalDate().toString())} ${it.toLocalTime().toString().take(5)}" } ?: r.start.take(16)
}

/** One completed item: result colour, symbol (or industry reasons), task, result word; [time] on the right in search results. */
@Composable
private fun DoneRow(st: AppState, it: DoneItem, time: String? = null) {
    val o = doneOutcome(it)
    val sym = it.s
    Row(Modifier.fillMaxWidth().then(if (sym != null) Modifier.clickable { st.go(Screen.Stock(sym)) } else Modifier)
        .defaultMinSize(minHeight = 48.dp).padding(horizontal = 14.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.padding(end = 12.dp).size(3.dp, 28.dp).clip(rr(2.dp)).background(o.color))
        Column(Modifier.weight(1f)) {
            T(sym?.substringBeforeLast(".") ?: "Industry notes", 15.sp, weight = FontWeight.SemiBold, maxLines = 1)
            Text(buildAnnotatedString {
                withStyle(SpanStyle(color = if (o.open) C.amber else TierC.lightGreen, fontWeight = FontWeight.Bold)) { append(if (o.open) "⚠ " else "✓ ") }
                append(o.what)
                if (o.result.isNotEmpty()) {
                    append(" · ")
                    withStyle(SpanStyle(color = o.color, fontWeight = FontWeight.SemiBold)) { append(o.result) }
                }
            }, fontSize = 12.sp, color = C.dim, lineHeight = 16.sp, maxLines = 2)
        }
        time?.let { t -> T(t, 11.sp, C.dim, maxLines = 1, modifier = Modifier.padding(start = 8.dp)) }
    }
}

/** Names of the red-flag checks (funnel.py A / G items), for the Completed rows. */
private val FLAG_NAMES = mapOf("A1" to "negative equity", "A2" to "loan default", "A3" to "audit qualification", "A4" to "insolvency",
    "A5" to "rating downgrade", "A6" to "suspension", "G1" to "regulator order", "G2" to "fraud probe", "G3" to "auditor resignation",
    "G4" to "CEO and CFO exits", "G5" to "promoter stake cut", "G6" to "loans to the promoter group", "G7" to "fund use deviation")

private data class DoneOutcome(val what: String, val result: String, val color: Color, val open: Boolean = false)

/** A run-log result ("fail (A5 confirmed)", "review_flag (G1 dismissed, G2 confirmed)", "recheck+driver", "enrich none found")
 *  in plain words: what was done and what came out of it (owner, 27 Nov 2026: "recheck" read like a task still waiting). */
private fun doneOutcome(it: DoneItem): DoneOutcome {
    it.industries?.let { return DoneOutcome("Industry notes updated", it, C.blue) }
    val raw = (it.r ?: "").trim()
    val word = raw.lowercase().split(' ', '(', '+', ':').firstOrNull().orEmpty()
    val inner = raw.substringAfter("(", "").substringBeforeLast(")", "")
    val rest = raw.drop(word.length).trim()
    fun names(codes: String) = Regex("[AG]\\d").findAll(codes).map { m -> FLAG_NAMES[m.value] ?: m.value }.toList()
    return when (word) {
        "pass" -> DoneOutcome("Full review done", "Pass", TierC.darkGreen)
        "caution" -> DoneOutcome("Full review done", "Caution", C.amber)
        "fail" -> {
            val conf = names(inner)
            DoneOutcome("Full review done", "Fail" + if (conf.isNotEmpty()) ": ${conf.joinToString(", ")} confirmed" else "", C.red)
        }
        "review_flag", "dismissed", "confirmed" -> {
            val parts = inner.split(";").map { p -> p.trim() }.filter { p -> p.isNotEmpty() }
            val confirmed = mutableListOf<String>(); val dismissed = mutableListOf<String>(); val open = mutableListOf<String>()
            parts.forEach { p ->
                // "A2, G2 confirmed" / "G1 dismissed, G2 confirmed" / "G3 not reviewed: filing is a zip"
                p.split(Regex(",\\s*(?=[AG]\\d)")).forEach { seg ->
                    when {
                        seg.contains("not reviewed") -> open += names(seg)
                        seg.contains("dismissed") -> dismissed += names(seg)
                        seg.contains("confirmed") -> confirmed += names(seg)
                    }
                }
            }
            if (confirmed.isEmpty() && dismissed.isEmpty() && open.isNotEmpty())
                return DoneOutcome("Red flag still open", "filing could not be read", C.amber, open = true)
            val out = listOfNotNull(confirmed.takeIf { c -> c.isNotEmpty() }?.let { c -> "${c.joinToString(", ")} confirmed" },
                dismissed.takeIf { d -> d.isNotEmpty() }?.let { d -> "${d.joinToString(", ")}: false alarm" },
                open.takeIf { o -> o.isNotEmpty() }?.let { o -> "${o.joinToString(", ")} still open" })
            DoneOutcome(if (confirmed.size + dismissed.size + open.size > 1) "Red flags checked" else "Red flag checked",
                out.joinToString("; ").ifEmpty { "checked" }, if (confirmed.isNotEmpty()) C.red else TierC.darkGreen)
        }
        "recheck" -> DoneOutcome("Research refreshed", when {
            raw.contains("+driver") && it.dated != 0 -> "new dated driver found"
            rest.isNotEmpty() -> rest.trimStart('+', ' ')
            else -> ""
        }, C.blue)
        // feedback #219: say "found" only when the stock has a verified dated driver on record (it.dated, from the pipeline)
        "enrich" -> when {
            raw.contains("no_concall") -> DoneOutcome("Looked for a dated driver", "no earnings call to read", C.dim)
            raw.contains("none found") || it.dated == 0 -> DoneOutcome("Looked for a dated driver", "none with a confirmed date", C.dim)
            raw.contains("already had") -> DoneOutcome("Dated driver", "already on record", C.blue)
            else -> DoneOutcome("Dated driver found", it.dated?.let { n -> "$n on record" } ?: "", TierC.darkGreen)
        }
        else -> DoneOutcome(QUEUE_TASKS[word]?.first ?: "Research done", rest, C.blue)
    }
}

fun LazyListScope.completedList(st: AppState, d: DoneFile?, filter: String = "All", onFilter: (String) -> Unit = {}) {
    if (d == null) { item { LoadingCard(3) }; return }
    if (d.runs.isEmpty()) { item { Empty("Nothing completed in the last ${d.days} days.") }; return }
    val all = d.runs.flatMap { it.items }
    val cnt = all.groupingBy { doneGroup(it.r) }.eachCount()
    item {
        // owner, 27 Nov 2026: one filter button (was a row of result chips)
        FilterMenu(listOf(Triple("All", "All", all.size)) + listOf("Pass", "Caution", "Fail", "Flags checked", "Recheck", "Catalyst", "Other")
            .mapNotNull { g -> cnt[g]?.let { n -> Triple(g, g, n) } }, filter, { g -> doneGroupColor(g) }, onFilter)
    }
    d.runs.map { r -> r.copy(items = r.items.filter { filter == "All" || doneGroup(it.r) == filter }) }.filter { it.items.isNotEmpty() }.forEach { r ->
        val head = doneRunTime(r) + " · ${r.items.size} done" + (r.task?.let { " · " + if (it == "catalyst") "catalysts" else "reviews" } ?: "")
        item { T(head, 12.sp, C.dim, modifier = Modifier.padding(start = 20.dp, top = 10.dp, bottom = 2.dp)) }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 2.dp).fillMaxWidth(), pad = 0.dp) {
                r.items.forEachIndexed { n, it ->
                    DoneRow(st, it)
                    if (n < r.items.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
                }
            }
        }
    }
}
