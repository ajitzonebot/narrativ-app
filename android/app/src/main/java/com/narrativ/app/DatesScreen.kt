package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate

/*
 * Dates to watch (owner, 25 Nov 2026, Paper mock-up): every open checkpoint of today's Top 10 on one calendar, so the
 * dates that can change a call are visible at a glance. Results / shareholding dates shared by several stocks are one line.
 */

private data class DateItem(val who: String, val text: String, val type: String, val syms: List<String>)

private fun typeInk(t: String): Color = when (t) {
    "kill_switch" -> TierC.red; "promise" -> TierC.darkGreen; "must_go_right" -> TierC.yellow; "results" -> C.white; else -> C.dim
}
private fun typeDot(t: String): Color = when (t) {
    "kill_switch" -> dotInk(5); "promise" -> dotInk(1); "must_go_right" -> dotInk(3); "results" -> C.white; else -> dotInk(0)
}
private val TYPE_RANK = listOf("kill_switch", "promise", "must_go_right", "results", "shareholding")

@Composable
fun DatesScreen(st: AppState) {
    val top = topTen(st)?.stocks.orEmpty()
    val today = LocalDate.now(java.time.ZoneId.of("Asia/Kolkata"))
    // (date, type, what) -> stocks; routine filings shared by several stocks become one line
    val rows = top.flatMap { p -> p.cp.filter { it.status != "closed" }.mapNotNull { c ->
        val d = runCatching { LocalDate.parse(c.due) }.getOrNull() ?: return@mapNotNull null
        if (d.isBefore(today)) null else Triple(d, c, p)
    } }
    val byDate = rows.groupBy { it.first }.toSortedMap()
    AccScreen(st, "Dates to watch", "What can change a call on the Top 10", context = "Dates") {
        item {
            Text("The calendar: what can change a call on the Top 10", fontSize = 22.sp, lineHeight = 26.sp, color = C.white,
                fontFamily = if (Look.paper) PaperFonts.headline else null, fontWeight = FontWeight.Black, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
        }
        if (byDate.isEmpty()) { item { Empty("No dated events for the Top 10 yet.") }; return@AccScreen }
        item {
            val marks = byDate.map { (d, list) ->
                val worst = TYPE_RANK.firstOrNull { t -> list.any { it.second.type == t } } ?: "shareholding"
                StripMark(d, typeDot(worst), list.size)
            }
            DateStrip(marks, today, Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth().height(46.dp))
            Box(Modifier.padding(horizontal = 16.dp).fillMaxWidth().height(1.dp).background(C.white))
        }
        byDate.forEach { (d, list) ->
            item {
                val items = list.groupBy { (_, c, sp) -> if (c.type in setOf("results", "shareholding")) "${c.type}|${c.what}" else "${c.type}|${c.what}|${sp.s}" }  // other items stay per stock (review 26 Nov 2026)
                    .values.map { g ->
                        val c = g.first().second; val syms = g.map { it.third }
                        val who = when { syms.size == top.size && top.size > 2 -> "All ${syms.size}"; syms.size > 3 -> "${syms.size} stocks"; else -> syms.joinToString(", ") { it.c } }
                        val text = when (c.type) {
                            "kill_switch" -> "exit check: " + (c.what ?: "")
                            "must_go_right" -> "must go right: " + (c.what ?: "")
                            "promise" -> "promise due: " + (c.what ?: "")
                            else -> c.what ?: cpWord(c.type)
                        } + if (syms.size > 3 && syms.size != top.size) " (" + syms.joinToString(", ") { it.c } + ")" else ""
                        DateItem(who, text, c.type ?: "", syms.map { it.s })
                    }.sortedBy { TYPE_RANK.indexOf(it.type).let { i -> if (i < 0) 9 else i } }
                Row(Modifier.padding(horizontal = 16.dp).fillMaxWidth().padding(vertical = 8.dp)) {
                    Column(Modifier.width(52.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("${d.dayOfMonth}", fontSize = 22.sp, lineHeight = 24.sp, color = C.white, fontFamily = if (Look.paper) PaperFonts.headline else null, fontWeight = FontWeight.Black)
                        PaperLabel(d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH), size = 10.sp)
                    }
                    Box(Modifier.padding(horizontal = 8.dp).width(1.dp).height(40.dp).background(C.line))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        items.forEach { it2 ->
                            Row(Modifier.clickable(enabled = it2.syms.size == 1) { st.go(Screen.Stock(it2.syms.first())) }, verticalAlignment = Alignment.Top) {
                                Box(Modifier.padding(top = 5.dp, end = 6.dp).size(8.dp).clip(CircleShape).background(typeDot(it2.type)))
                                Text(androidx.compose.ui.text.buildAnnotatedString {
                                    pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.Bold, color = C.white)); append(it2.who); pop()
                                    append(" "); pushStyle(androidx.compose.ui.text.SpanStyle(color = typeInk(it2.type))); append(it2.text); pop()
                                }, fontSize = 12.sp, lineHeight = 16.sp)
                            }
                        }
                    }
                }
                HLineDivider(Modifier.padding(horizontal = 16.dp))
            }
        }
    }
}
