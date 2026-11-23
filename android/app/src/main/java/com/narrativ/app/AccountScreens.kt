package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ChevronRight
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
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
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
              actions: @Composable RowScope.() -> Unit = {}, content: LazyListScope.() -> Unit) {
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, title, context, subtitle, back, big, actions) }
        content()
    }
}

/** Darker cell inside a card: small grey label, bold figure. */
@Composable
fun Cell(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = C.white, note: String? = null) {
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(C.sheet).padding(horizontal = 12.dp, vertical = 10.dp)) {
        T(label, 11.sp, C.dim, maxLines = 1)
        T(value, 17.sp, valueColor, FontWeight.Bold, maxLines = 1)
        note?.let { T(it, 10.sp, C.dim, maxLines = 2) }
    }
}

/** Rounded progress bar on a track. */
@Composable
fun ProgBar(fraction: Float, color: Color, modifier: Modifier = Modifier, height: Dp = 8.dp, track: Color = Color.White.copy(alpha = 0.10f)) {
    Box(modifier.height(height).clip(RoundedCornerShape(height / 2)).background(track)) {
        Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).fillMaxHeight().clip(RoundedCornerShape(height / 2)).background(color))
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

private suspend inline fun <reified A : Any, reified B : Any> Repo.get2(path: String): Pair<A, B>? =
    text(path)?.let { t -> runCatching { json.decodeFromString<A>(t) to json.decodeFromString<B>(t) }.getOrNull() }

// ---------------------------------------------------------------- a03 Track record
private val MIX_GOAL = listOf(Triple("Multibagger", 2, TierC.lightGreen), Triple("Beat Nifty", 3, TierC.darkGreen),
    Triple("Near Nifty", 3, C.dim), Triple("Behind Nifty", 2, TierC.lightRed))

@Composable
fun TrackRecordScreen(st: AppState) {
    val cf by produceState<CallsFile?>(null) { value = st.repo.get<CallsFile>("data/calls.json") }
    val mat by produceState<CallsMat?>(null) { value = st.repo.get<CallsMat>("data/calls.json") }
    val c = cf
    val v = c?.calls.orEmpty().filter { it.kind == "verified" }
    AccScreen(st, "Track record", if (v.isEmpty()) "Verified Buys vs Nifty" else "Verified Buys since ${shortDate(v.minOf { it.date })}", "Track record") {
        if (c == null) { item { Empty("Loading…") }; return@AccScreen }
        val sm = c.summary.now
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                T("AVERAGE VS NIFTY, PER BUY", 11.sp, C.dim)
                T(sg(sm?.avgVsNifty), 36.sp, plColor(sm?.avgVsNifty), FontWeight.ExtraBold, modifier = Modifier.padding(top = 2.dp, bottom = 12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Cell("Verified Buys", "${v.size}", Modifier.weight(1f))
                    Cell("Avg return", sg(sm?.avgPct), Modifier.weight(1f), plColor(sm?.avgPct))
                    Cell("Beat Nifty", sm?.beatPct?.let { "$it%" } ?: "–", Modifier.weight(1f))
                }
                sm?.beatPct?.let { b ->
                    SegmentedBar(listOf(Segment(b.toDouble(), TierC.lightGreen), Segment((100 - b).toDouble(), Color.White.copy(alpha = 0.18f))),
                        Modifier.padding(top = 12.dp).fillMaxWidth(), height = 6.dp, legend = SegLegend.None)
                }
                val ms = mat?.summary?.verified.orEmpty()
                Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    T("Matured:", 12.sp, C.dim)
                    listOf("1m", "3m", "6m", "12m").forEach { k ->
                        val s = ms[k]
                        Row(Modifier.clip(RoundedCornerShape(8.dp)).background(C.sheet).padding(horizontal = 8.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                            T(k.uppercase(), 12.sp, C.dim)
                            T(if (s != null && s.n > 0) sg(s.avgVsNifty, 1) else "—", 12.sp, if (s != null && s.n > 0) plColor(s.avgVsNifty) else C.white, FontWeight.Medium)
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

/** "As one portfolio": the verified Buys as one equal-weight portfolio vs Nifty (calls.json summary.portfolio), or an empty state. */
@Composable
private fun OnePortfolioCard(p: CallPortfolio?) {
    val a = p?.curve.orEmpty().mapNotNull { it.getOrNull(1)?.content?.toDoubleOrNull() }
    val b = p?.curve.orEmpty().mapNotNull { it.getOrNull(2)?.content?.toDoubleOrNull() }
    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            T("As one portfolio", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            T(if (p != null) "equal weight · ${p.days} day${if (p.days == 1) "" else "s"}" else "equal weight", 12.sp, C.dim)
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

private fun vsNifty(c: CallRec): Double? = if (c.ended != null) c.toEndVsNifty else c.nowVsNifty

@Composable
private fun EveryBuyCard(st: AppState, v: List<CallRec>) {
    val sorted = v.sortedWith(compareBy<CallRec> { vsNifty(it) == null }.thenByDescending { vsNifty(it) ?: 0.0 })
    val mx = sorted.mapNotNull { vsNifty(it)?.let { x -> abs(x) } }.maxOrNull()?.takeIf { it > 0 } ?: 1.0
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
            BuyRow(c, mx) { st.go(Screen.Stock(c.symbol)) }
        }
        if (sorted.size > 15) MoreLink(if (all) "Show fewer" else "${sorted.size - 15} more Buys") { all = !all }
    }
}

/** One Buy: code and date, a bar left (behind Nifty) or right (ahead) of the centre line, points vs Nifty. Hollow bar = closed, "day 0" = no return yet. */
@Composable
private fun BuyRow(c: CallRec, mx: Double, onClick: () -> Unit) {
    val closed = c.ended != null
    val v = vsNifty(c)
    val col = plColor(v)
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).defaultMinSize(minHeight = 46.dp).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.width(100.dp)) {
            T(c.symbol.substringBeforeLast("."), 13.sp, weight = FontWeight.SemiBold, maxLines = 1)
            T(shortDate(c.date) + if (closed) " · closed" else "", 10.5.sp, C.dim, maxLines = 1)
        }
        Box(Modifier.weight(1f).height(20.dp)) {
            Canvas(Modifier.fillMaxSize()) {
                val cx = size.width / 2
                drawLine(Color.White.copy(alpha = 0.2f), Offset(cx, 0f), Offset(cx, size.height), 1.dp.toPx())
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
        T(if (v == null) "—" else sg(v, 2, ""), 13.sp, col, FontWeight.SemiBold, modifier = Modifier.width(56.dp), maxLines = 1, align = TextAlign.End)
    }
}

// ---------------------------------------------------------------- a06 Data and pipeline
private fun coverageColor(p: Double) = if (p >= 0.95) TierC.lightGreen else C.amber

private data class SrcRow(val name: String, val figure: String, val pct: Double?)

@Composable
fun DataPipelineScreen(st: AppState) {
    val hh by produceState<Pair<Health, HealthU>?>(null) { value = st.repo.get2<Health, HealthU>("data/health.json") }
    val ii by produceState<Pair<IssuesFile, IssuesU>?>(null) { value = st.repo.get2<IssuesFile, IssuesU>("data/data_issues.json") }
    val sched by produceState<Schedule?>(null) { value = st.repo.get<Schedule>("data/schedule.json") }
    val runs by produceState<List<RunRec>?>(null) { value = st.repo.get<List<RunRec>>("data/runs.json") }
    val scope = rememberCoroutineScope()
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    AccScreen(st, "Data and pipeline", null, "Data") {
        val h = hh?.first
        val next = nextDailyRun()
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        T("LAST RUN", 11.sp, C.dim)
                        T(if (h != null) "${istTime(h.finished)} IST" else "Data of ${shortDate(st.picks?.date)}", 20.sp, weight = FontWeight.Bold, maxLines = 1)
                    }
                    HeaderPill(Icons.Rounded.Refresh, "Check for data") {
                        scope.launch {
                            val before = st.picks?.updated
                            st.load()
                            st.toast = if (st.picks?.updated == before) "Already latest: data of ${shortDate(st.picks?.date)}. Next update $next"
                                       else "Updated to data of ${shortDate(st.picks?.date)}"
                        }
                    }
                }
                Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Cell("Duration", h?.minutes?.let { "${fmt(it, 1)} min" } ?: "–", Modifier.weight(1f))
                    Column(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(C.sheet).padding(horizontal = 12.dp, vertical = 10.dp)) {
                        T("Problems", 11.sp, C.dim)
                        val n = h?.problems?.size ?: 0
                        Box(Modifier.padding(top = 2.dp).defaultMinSize(minWidth = 24.dp, minHeight = 24.dp).clip(CircleShape).background((if (n > 0) C.amber else TierC.darkGreen).copy(alpha = 0.22f)),
                            contentAlignment = Alignment.Center) { T(if (h == null) "–" else "$n", 14.sp, if (n > 0) C.amber else TierC.lightGreen, FontWeight.Bold) }
                    }
                    Cell(if (next.startsWith("today")) "Next daily run" else "Next · ${next.substringBefore(" 17:10")}", "17:10", Modifier.weight(1f))
                }
                val rs = runs.orEmpty().reversed()
                if (rs.size >= 2) {
                    Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        T("Minutes per run, last ${rs.size}", 12.sp, C.dim, modifier = Modifier.weight(1f))
                        StatusDot(C.amber, size = 8.dp); T("  2+ problems", 12.sp, C.dim)
                    }
                    val mins = rs.map { it.minutes ?: 0.0 }
                    Bars(mins, Modifier.padding(top = 6.dp).fillMaxWidth().height(92.dp),
                        labels = rs.mapIndexed { i, r -> if (i == 0) shortDate(r.date) else if (i == rs.lastIndex) "latest" else "" },
                        valueFmt = { x -> if (x == mins.last()) fmt(x, 1) else "" },
                        colors = rs.map { if (it.problems >= 2) C.amber else C.teal }, highlightLast = true, base = 0.0)
                }
            }
        }
        val s = sched
        item {
            CollapseCard("Today's schedule", if (s == null) "" else "${s.jobs.size} jobs · next 17:10") {
                if (s == null) T("The schedule appears after the next daily run.", 13.sp, C.dim) else {
                    s.note?.let { T(it, 11.sp, C.dim, lineHeight = 15.sp, modifier = Modifier.padding(bottom = 6.dp)) }
                    val reviewsToday = st.research.values.count { it.updated == today }
                    s.jobs.forEach { j ->
                        val status = when {
                            j.name.startsWith("Daily run") && st.picks?.date == today -> "done" to TierC.lightGreen
                            j.by == "Claude" && j.name.startsWith("Research") && reviewsToday > 0 -> "$reviewsToday stocks" to TierC.lightGreen
                            else -> null
                        }
                        Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                            Column(Modifier.width(118.dp)) { T(j.time, 12.sp, weight = FontWeight.SemiBold); T(j.days, 11.sp, C.dim) }
                            T(j.name, 12.sp, modifier = Modifier.weight(1f).padding(horizontal = 6.dp), lineHeight = 15.sp)
                            if (status != null) T(status.first, 11.sp, status.second, FontWeight.SemiBold) else T(j.by, 11.sp, C.dim)
                        }
                    }
                }
            }
        }
        item { SecHead("Sources", "coverage of the universe") }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 0.dp) {
                val rows = if (hh == null) emptyList() else sourceRows(hh!!.first, hh!!.second)
                if (rows.isEmpty()) Box(Modifier.padding(14.dp)) { T("Source coverage appears after the next daily run.", 13.sp, C.dim) }
                rows.forEachIndexed { i, r ->
                    Row(Modifier.fillMaxWidth().defaultMinSize(minHeight = 44.dp).padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        T(r.name, 14.sp, maxLines = 1, modifier = Modifier.width(112.dp))
                        if (r.pct != null) ProgBar(r.pct.toFloat(), coverageColor(r.pct), Modifier.weight(1f))
                        else ProgBar(1f, TierC.darkGreen.copy(alpha = 0.5f), Modifier.weight(1f), track = TierC.darkGreen.copy(alpha = 0.2f))
                        T(r.figure, 11.sp, C.dim, maxLines = 1, align = TextAlign.End, modifier = Modifier.width(88.dp).padding(start = 8.dp))
                        Box(Modifier.width(46.dp), contentAlignment = Alignment.CenterEnd) {
                            if (r.pct != null) T("${fmt(r.pct * 100, 1)}%", 12.sp, coverageColor(r.pct), FontWeight.Bold, maxLines = 1) else StatusDot(TierC.lightGreen)
                        }
                    }
                    if (i < rows.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
                }
            }
        }
        item {
            val iss = ii
            CollapseCard("Data issues", if (iss == null) "" else "${iss.first.open} open · ${iss.second.corrected} corrected") {
                if (iss == null || iss.first.issues.isEmpty()) T("No data issue logged yet. Audits add them as they find wrong numbers.", 13.sp, C.dim)
                else {
                    T("${iss.first.open} open (${iss.first.openSystemic} systemic) · ${iss.first.fixed} fixed", 13.sp, weight = FontWeight.SemiBold)
                    iss.first.issues.values.sortedWith(compareBy<DataIssue> { it.status != "open" }.thenByDescending { it.firstSeen }).take(30).forEach { d ->
                        Column(Modifier.padding(top = 8.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                T(d.symbol.substringBeforeLast("."), 13.sp, weight = FontWeight.SemiBold)
                                TypeTag(d.scope, if (d.scope == "systemic") C.amber else C.grey)
                                T(if (d.status == "fixed") "fixed ${d.fixedOn ?: ""}" else d.status, 11.sp, if (d.status == "fixed") TierC.lightGreen else TierC.lightRed)
                            }
                            T("${d.field}: app ${d.app ?: "–"} → filed ${d.found ?: "–"}", 12.sp, C.dim)
                            d.cause?.let { T(it.replaceFirstChar { c -> c.uppercase() }, 12.sp) }
                        }
                    }
                }
            }
        }
        item {
            CollapseCard("Last runs", "${runs?.size ?: 0} runs") {
                val rs = runs
                if (rs.isNullOrEmpty()) T("Run history appears after the next daily run.", 13.sp, C.dim)
                else rs.forEach { x ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                        T("${shortDate(x.date)} · finished ${istTime(x.finished)}", 13.sp, modifier = Modifier.weight(1f), maxLines = 1)
                        T("${fmt(x.minutes, 1)} min", 13.sp, C.dim); Spacer(Modifier.width(12.dp))
                        T(if (x.problems == 0) "OK" else "${x.problems} problem${if (x.problems > 1) "s" else ""}", 13.sp, if (x.problems == 0) TierC.lightGreen else C.amber)
                    }
                }
            }
        }
        item {
            CollapseCard("Details", "Stages · log · coverage") {
                if (h == null) { T("Pipeline health appears after the next daily run.", 13.sp, C.dim); return@CollapseCard }
                T("STAGES · MINUTES IN THE LAST RUN", 11.sp, C.dim, FontWeight.Bold)
                val total = h.stages.sumOf { it.getOrNull(1)?.content?.toDoubleOrNull() ?: 0.0 }.coerceAtLeast(1.0)
                h.stages.forEach { sg0 ->
                    val name = sg0.getOrNull(0)?.content ?: ""; val sec = sg0.getOrNull(1)?.content?.toDoubleOrNull() ?: 0.0
                    Column(Modifier.padding(vertical = 4.dp)) {
                        Row { T(name.replaceFirstChar { it.uppercase() }, 13.sp, modifier = Modifier.weight(1f)); T("${fmt(sec / 60, 1)} min", 13.sp, C.dim) }
                        ProgBar((sec / total).toFloat(), C.teal, Modifier.padding(top = 3.dp).fillMaxWidth(), height = 4.dp)
                    }
                }
                T("LOG · ${if (h.problems.isEmpty()) "no problems in the last run" else "lines flagged in the last run"}", 11.sp, C.dim, FontWeight.Bold, Modifier.padding(top = 12.dp))
                h.problems.take(40).forEach { T(it, 12.sp, C.amber, lineHeight = 16.sp, modifier = Modifier.padding(vertical = 3.dp)) }
                T("STORES AFTER THE LAST RUN", 11.sp, C.dim, FontWeight.Bold, Modifier.padding(top = 12.dp))
                h.sources.forEach { (k, m) ->
                    Column(Modifier.padding(vertical = 4.dp)) {
                        T(k.replaceFirstChar { it.uppercase() }, 13.sp, weight = FontWeight.SemiBold)
                        T(m.entries.joinToString(" · ") { (a, b) -> "${a.replace('_', ' ')} ${b.content}" }, 12.sp, C.dim)
                    }
                }
                T("CHECK COVERAGE · STOCKS WITH DATA", 11.sp, C.dim, FontWeight.Bold, Modifier.padding(top = 12.dp))
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
                T("WHERE EACH NUMBER COMES FROM", 11.sp, C.dim, FontWeight.Bold, Modifier.padding(top = 12.dp))
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
private val TASK_COLOR = mapOf("review" to TierC.lightGreen, "review_flag" to C.amber, "recheck" to C.blue, "enrich" to C.muted)
fun queueTaskColor(task: String?): Color = TASK_COLOR[task] ?: C.dim
fun queueTaskName(task: String?): String = (QUEUE_TASKS[task] ?: QUEUE_TASKS.getValue("scan")).first

@Composable
fun ResearchQueueScreen(st: AppState) {
    val q = st.queue
    var all by remember { mutableStateOf(false) }
    var legend by remember { mutableStateOf(false) }
    AccScreen(st, "Research queue", q?.let { "${it.items.size} stocks · ${shortDate(it.date)}" }, "Queue") {
        if (q == null || q.items.isEmpty()) { item { Empty("The queue appears after the next daily run.") }; return@AccScreen }
        item {
            val mix = q.items.groupingBy { it.task ?: "scan" }.eachCount().entries.sortedByDescending { it.value }
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 14.dp) {
                SegmentedBar(mix.map { Segment(it.value.toDouble(), queueTaskColor(it.key), "${queueTaskName(it.key)} ${it.value}") },
                    height = 12.dp, gap = 3.dp, legend = SegLegend.Below)
            }
        }
        item {
            val shown = if (all) q.items else q.items.take(12)
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                shown.forEachIndexed { n, it ->
                    val p = st.pick(it.symbol); val col = queueTaskColor(it.task)
                    Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(it.symbol)) }.defaultMinSize(minHeight = 52.dp).padding(horizontal = 14.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        T("${n + 1}", 13.sp, C.dim, modifier = Modifier.width(26.dp), align = TextAlign.End)
                        Box(Modifier.padding(horizontal = 10.dp).size(3.dp, 30.dp).clip(RoundedCornerShape(2.dp)).background(col))
                        Column(Modifier.weight(1f)) {
                            T(it.symbol.substringBeforeLast("."), 15.sp, weight = FontWeight.SemiBold, maxLines = 1)
                            T((it.reason ?: p?.n ?: "").substringBefore(":"), 12.sp, C.dim, maxLines = 1)
                        }
                        T(queueTaskName(it.task), 12.sp, col, FontWeight.SemiBold, maxLines = 1)
                    }
                    if (n < shown.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
                }
            }
        }
        if (q.items.size > 12) item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp, onClick = { all = !all }) {
                Row(Modifier.fillMaxWidth().height(52.dp).padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    T(if (all) "Show first 12" else "${q.items.size - 12} more", 14.sp, modifier = Modifier.weight(1f))
                    T("ranks 13 to ${q.items.size}", 12.sp, C.dim)
                }
            }
        }
        item {
            CollapseCard("What the tasks mean", "") {
                QUEUE_TASKS.forEach { (k, v) ->
                    Row(Modifier.padding(vertical = 4.dp)) {
                        T(v.first, 12.sp, queueTaskColor(k), FontWeight.SemiBold, modifier = Modifier.width(100.dp)); T(v.second, 12.sp, C.dim, lineHeight = 16.sp)
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- a09 Version and release notes
private fun changeTag(type: String): Pair<String, Color> = when (type) {
    "new" -> "NEW" to C.blue; "change", "imp", "improved" -> "CHANGED" to C.muted; "fix" -> "FIX" to C.dim; else -> type.uppercase() to C.dim
}

@Composable
private fun ChangeLine(c: Change) {
    val (t, col) = changeTag(c.type)
    Row(Modifier.padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.width(70.dp).clip(RoundedCornerShape(6.dp)).background(col.copy(alpha = 0.12f)).padding(vertical = 3.dp), contentAlignment = Alignment.Center) {
            T(t, 10.sp, col, FontWeight.Bold, maxLines = 1)
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
            drawRoundRect(C.teal.copy(alpha = 0.7f), Offset(i * bw + 1.dp.toPx(), size.height - h), Size(bw - 3.dp.toPx(), h), CornerRadius(2.dp.toPx()))
        }
    }
}

@Composable
fun ReleaseNotesScreen(st: AppState) {
    val v = st.version
    val scope = rememberCoroutineScope()
    var allNew by remember { mutableStateOf(false) }
    var older by remember { mutableStateOf(false) }
    AccScreen(st, "Version", null, "Version") {
        val newer = (v?.versionCode ?: 0) > BuildConfig.VERSION_CODE
        val rel = v?.changelog?.firstOrNull { it.version == BuildConfig.VERSION_NAME } ?: v?.changelog?.firstOrNull()
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        T("v${BuildConfig.VERSION_NAME}", 26.sp, weight = FontWeight.ExtraBold)
                        T("installed" + (v?.changelog?.firstOrNull { it.version == BuildConfig.VERSION_NAME }?.let { " · released ${shortDate(it.date)}" } ?: ""), 12.sp, C.dim)
                    }
                    val col = if (newer) C.blue else TierC.lightGreen
                    Row(Modifier.clip(RoundedCornerShape(12.dp)).background(col.copy(alpha = 0.13f)).padding(horizontal = 10.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        StatusDot(col); T(if (newer) "Update available" else "Up to date", 12.sp, col, FontWeight.SemiBold, maxLines = 1)
                    }
                }
                Box(Modifier.padding(top = 14.dp).fillMaxWidth().height(44.dp).clip(RoundedCornerShape(22.dp)).background(C.teal).clickable {
                    if (newer) st.showUpdate = true
                    else scope.launch { st.repo.get<VersionInfo>("app/version.json")?.let { st.version = it; if (it.versionCode > BuildConfig.VERSION_CODE) st.showUpdate = true else st.toast = "Up to date" } }
                }, contentAlignment = Alignment.Center) { T(if (newer) "Install v${v?.versionName}" else "Check for updates", 15.sp, C.white, FontWeight.SemiBold) }
            }
        }
        if (v == null || rel == null) { item { Empty("Release notes load with an internet connection.") }; return@AccScreen }
        item {
            val cnt = rel.changes.groupingBy { it.type }.eachCount().entries.sortedByDescending { it.value }
            SecHead("What's new in v${rel.version}", cnt.joinToString(" · ") { (k, n) ->
                n.toString() + " " + when (k) { "new" -> "new"; "fix" -> if (n > 1) "fixes" else "fix"; "change" -> "changed"; else -> k } })
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
    val data by produceState<Pair<List<FbItem>, Pair<Int, Int>>?>(null) {
        value = st.repo.apiGet("feedback/stats")?.let { o ->
            val items = runCatching { json.decodeFromJsonElement(kotlinx.serialization.builtins.ListSerializer(FbItem.serializer()), o["items"]!!) }.getOrDefault(emptyList())
            items to ((o["open"]?.toString()?.toIntOrNull() ?: 0) to (o["closed"]?.toString()?.toIntOrNull() ?: 0))
        }
    }
    var state by remember { mutableStateOf("open") }
    var type by remember { mutableStateOf<String?>(null) }
    AccScreen(st, "Feedback", null, "Feedback", actions = { HeaderPill(Icons.Rounded.Add, "New") { st.openFeedback("Feedback") } }) {
        val d = data
        if (d == null) { item { Empty("Feedback loads with an internet connection.") }; return@AccScreen }
        item {
            val (open, closed) = d.second
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 14.dp) {
                Row {
                    listOf("open" to open, "closed" to closed).forEach { (k, n) ->
                        val on = state == k
                        Row(Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).clickable { state = k }.padding(vertical = 2.dp), verticalAlignment = Alignment.Bottom,
                            horizontalArrangement = if (k == "open") Arrangement.Start else Arrangement.End) {
                            T(k.replaceFirstChar { it.uppercase() }, 13.sp, if (on) C.white else C.dim)
                            T("  $n", 20.sp, if (on) C.white else C.dim, FontWeight.Bold)
                        }
                    }
                }
                SegmentedBar(listOf(Segment(open.toDouble(), C.teal), Segment(closed.toDouble(), Color.White.copy(alpha = 0.2f))),
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
                        TypeTag(f.type, if (f.type == "Bug") TierC.lightRed else C.blue)
                        T("#${f.n} · ${f.date}", 11.sp, C.dim, modifier = Modifier.weight(1f), align = TextAlign.End)
                    }
                    T(f.text.replaceFirstChar { it.uppercase() }, 14.sp, lineHeight = 19.sp, maxLines = 4, modifier = Modifier.padding(top = 8.dp))
                    if (f.screen.isNotBlank()) T(f.screen, 11.sp, C.dim, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
    }
}
