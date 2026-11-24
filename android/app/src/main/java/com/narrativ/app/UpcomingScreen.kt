package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material3.Icon
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate
import java.time.temporal.ChronoUnit

data class Cp(val symbol: String, val name: String, val c: Checkpoint)

private val CAL_TABS = listOf("Due", "Next 45 days", "Changes", "Removed")
// type tags are not tappable, so greys (blue is only for taps); amber / red keep their warning meaning
private val CP_TYPE = mapOf("results" to ("Results" to C.muted), "shareholding" to ("Shareholding" to TierC.grey), "must_go_right" to ("Must go right" to C.amber),
    "kill_switch" to ("Kill switch" to TierC.lightRed), "promise" to ("Promise" to C.dim))

/** "Claude reviews 5 times a day: 04:05, 09:05, 14:05, 18:05, 23:05 IST", from the research schedule. */
private fun researchScheduleText(): String =
    "Claude reviews ${RESEARCH_SLOTS.size} times a day: " + RESEARCH_SLOTS.joinToString(", ") { "%02d:%02d".format(it / 60, it % 60) } + " IST"

/** "Quarter ending 30 Sep 2026" instead of the raw "quarter ending 2026-09-30". */
private fun cpWhat(c: Checkpoint): String {
    val m = Regex("quarter ending (\\d{4})-(\\d\\d)-(\\d\\d)").find(c.what) ?: return c.what
    val d = LocalDate.of(m.groupValues[1].toInt(), m.groupValues[2].toInt(), m.groupValues[3].toInt())
    return "Quarter ending ${d.dayOfMonth} ${d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)} ${d.year}"
}

/** Checkpoint calendar: segmented Due / Next 45 days / Changes / Removed, a due-per-day timeline and the rows. */
@Composable
fun UpcomingScreen(st: AppState) {
    var tab by remember { mutableIntStateOf(0) }
    var showAll by remember { mutableStateOf(false) }
    val mem = st.memory
    val today = remember { LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")) }
    val cps = remember(mem) { mem?.stocks.orEmpty().flatMap { s -> s.checkpoints.map { Cp(s.symbol, s.name, it) } }.sortedBy { it.c.due } }
    val due = cps.filter { it.c.status == "due" }
    val end = today.plusDays(45).toString()
    val next = cps.filter { it.c.status == "open" && it.c.due in today.toString()..end }
    AccScreen(st, "Checkpoint calendar", "Results, promises and kill switches", "Calendar · ${CAL_TABS[tab]}") {
        item { SegmentedControl(CAL_TABS, tab, { tab = it; showAll = false }, Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
        when (tab) {
            0 -> {
                item {
                    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T("${due.size} due", 17.sp, weight = FontWeight.Bold, modifier = Modifier.weight(1f))
                            T("${next.size} more in the next 45 days", 12.sp, C.dim, maxLines = 1)
                        }
                        if (due.isEmpty()) T("Nothing due. ${researchScheduleText()}.", 13.sp, C.dim, modifier = Modifier.padding(top = 8.dp))
                        else DueTimeline(due.map { it.c.due }, today, Modifier.padding(top = 10.dp).fillMaxWidth().height(86.dp))
                    }
                }
                item { CpList(st, if (showAll) due else due.take(7), today, true) }
                if (due.size > 7) item { MoreCard(if (showAll) "Show first 7" else "${due.size - 7} more due") { showAll = !showAll } }
            }
            1 -> {
                item {
                    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T("${next.size} in the next 45 days", 17.sp, weight = FontWeight.Bold, modifier = Modifier.weight(1f))
                            T("to ${shortDate(end)}", 12.sp, C.dim)
                        }
                        val byType = next.groupingBy { it.c.type }.eachCount().entries.sortedByDescending { it.value }
                        if (byType.isNotEmpty()) SegmentedBar(byType.map { (k, n) -> Segment(n.toDouble(), CP_TYPE[k]?.second ?: C.dim, "${CP_TYPE[k]?.first ?: k} $n") },
                            Modifier.padding(top = 12.dp).fillMaxWidth(), height = 10.dp, gap = 3.dp)
                    }
                }
                if (next.isEmpty()) item { Empty("Nothing in the next 45 days.") }
                else item { CpList(st, if (showAll) next else next.take(15), today, false) }
                if (next.size > 15) item { MoreCard(if (showAll) "Show first 15" else "${next.size - 15} more") { showAll = !showAll } }
            }
            2 -> {
                val ch = mem?.stocks.orEmpty().flatMap { s -> s.verdicts.filter { it.from != null }.map { s to it } }.sortedByDescending { it.second.d }
                if (ch.isEmpty()) item { Empty("No verdict changes logged yet.") }
                else item {
                    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                        ch.take(60).forEachIndexed { i, (s, v) ->
                            Column(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(s.symbol)) }.padding(horizontal = 14.dp, vertical = 10.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    T(s.symbol.substringBeforeLast("."), 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f)); T(shortDate(v.d), 12.sp, C.dim)
                                }
                                Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) { T("${v.from} → ", 13.sp, C.dim); VerdictChip(v.v) }
                                v.cause?.let { T(it, 12.sp, C.dim, modifier = Modifier.padding(top = 3.dp)) }
                            }
                            if (i < minOf(ch.size, 60) - 1) HLineDivider(Modifier.padding(horizontal = 14.dp))
                        }
                    }
                }
            }
            else -> {
                val gone = mem?.stocks.orEmpty().filter { it.status == "removed" || it.status == "dropped" }
                item {
                    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 16.dp) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T("${gone.size} removed", 17.sp, weight = FontWeight.Bold, modifier = Modifier.weight(1f))
                            T("of ${mem?.stocks?.size ?: 0} remembered", 12.sp, C.dim)
                        }
                        T("Removed by a funnel level. History is kept.", 12.sp, C.dim, modifier = Modifier.padding(top = 6.dp))
                    }
                }
                item {
                    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                        gone.take(if (showAll) gone.size else 20).forEachIndexed { i, s ->
                            Column(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(s.symbol)) }.padding(horizontal = 14.dp, vertical = 10.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    T(s.symbol.substringBeforeLast("."), 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f)); T("since ${shortDate(s.firstSeen)}", 12.sp, C.dim)
                                }
                                T(s.name, 12.sp, C.dim, maxLines = 1)
                                s.dropReason?.let { T(it, 13.sp, C.white, modifier = Modifier.padding(top = 2.dp)) }
                            }
                            HLineDivider(Modifier.padding(horizontal = 14.dp))
                        }
                    }
                }
                if (gone.size > 20) item { MoreCard(if (showAll) "Show first 20" else "${gone.size - 20} more") { showAll = !showAll } }
            }
        }
    }
}

@Composable
private fun MoreCard(text: String, onClick: () -> Unit) {
    MoreLink(text, Modifier.padding(horizontal = 18.dp, vertical = 4.dp), onClick = onClick)
}

/** Rows of a checkpoint list: code and type tag, what is due, date and how long ago / how soon. */
@Composable
private fun CpList(st: AppState, rows: List<Cp>, today: LocalDate, overdueList: Boolean) {
    Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
        rows.forEachIndexed { i, x ->
            val (label, col) = CP_TYPE[x.c.type] ?: (x.c.type to C.dim)
            val days = runCatching { ChronoUnit.DAYS.between(LocalDate.parse(x.c.due), today).toInt() }.getOrNull()
            Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(x.symbol)) }.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        T(x.symbol.substringBeforeLast("."), 15.sp, weight = FontWeight.SemiBold, maxLines = 1, modifier = Modifier.weight(1f, fill = false))
                        TypeTag(label, col)
                    }
                    T(cpWhat(x.c), 12.5.sp, C.dim, lineHeight = 17.sp, maxLines = 3, modifier = Modifier.padding(top = 3.dp))
                }
                Column(Modifier.padding(start = 10.dp), horizontalAlignment = Alignment.End) {
                    T(shortDate(x.c.due), 13.sp, weight = FontWeight.SemiBold, maxLines = 1)
                    if (days != null) T(if (days > 0) "${days}d ago" else if (days == 0) "today" else "in ${-days}d", 12.sp,
                        if (overdueList || days == 0) C.amber else C.dim, maxLines = 1)
                }
            }
            if (i < rows.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
        }
    }
}

/** Checkpoints due per day from the oldest one to today: amber columns with the count above, grey stubs on empty days, dashed line at today. */
@Composable
private fun DueTimeline(dates: List<String>, today: LocalDate, modifier: Modifier) {
    val parsed = dates.mapNotNull { runCatching { LocalDate.parse(it) }.getOrNull() }
    if (parsed.isEmpty()) return
    val end = maxOf(today, parsed.max())
    val start = maxOf(parsed.min(), end.minusDays(59))  // older ones count in the first column
    val days = ChronoUnit.DAYS.between(start, end).toInt() + 1
    val counts = IntArray(days)
    parsed.forEach { counts[ChronoUnit.DAYS.between(start, it).toInt().coerceIn(0, days - 1)]++ }
    val mx = counts.max().coerceAtLeast(1)
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val labelH = 18.dp.toPx(); val base = size.height - labelH; val bw = size.width / days
        for (i in 0 until days) {
            val x = i * bw + 1.5.dp.toPx(); val w = (bw - 3.dp.toPx()).coerceAtLeast(2.dp.toPx())
            drawRoundRect(Color.White.copy(alpha = 0.12f), Offset(x, base - 4.dp.toPx()), Size(w, 4.dp.toPx()), CornerRadius(2.dp.toPx()))
            val n = counts[i]
            if (n > 0) {
                val bh = n.toFloat() / mx * (base - 22.dp.toPx())
                drawRoundRect(TierC.yellow, Offset(x, base - 4.dp.toPx() - bh), Size(w, bh + 4.dp.toPx()), CornerRadius(3.dp.toPx()))
                chartText(tm, "$n", i * bw + bw / 2, base - 8.dp.toPx() - bh, C.white, 10.sp, anchor = Anchor.Middle)
            }
        }
        val tx = (days - 1) * bw + bw / 2
        drawLine(C.amber, Offset(tx, 0f), Offset(tx, base), 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4f, 6f)))
        chartText(tm, shortDate(start.toString()), 0f, size.height - 2.dp.toPx(), C.dim, 10.sp)
        chartText(tm, "today", size.width, size.height - 2.dp.toPx(), C.amber, 10.sp, anchor = Anchor.End)
    }
}

@Composable
fun Text28(s: String) = T(s, 28.sp, C.white, FontWeight.Bold)

@Composable
fun CpRow(st: AppState, x: Cp, hot: Boolean) {
    Row(Modifier.padding(horizontal = 16.dp, vertical = 5.dp).fillMaxWidth().clip(RoundedCornerShape(S.card)).background(C.card2)
        .clickable { st.go(Screen.Stock(x.symbol)) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Tile(kindIcon(when (x.c.type) { "results" -> "results"; "shareholding" -> "holding"; "promise" -> "approval"; else -> "other" }),
            if (hot) C.tile else Brush.linearGradient(listOf(C.chip, C.card)), 40.dp, 22.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            T("${x.symbol.substringBeforeLast(".")} · ${x.c.what}", 14.sp, weight = FontWeight.Medium, maxLines = 2)
            T(listOfNotNull(shortDate(x.c.due), x.c.source).joinToString(" · "), 12.sp, C.grey, maxLines = 1)
        }
    }
}
