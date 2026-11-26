package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.drawText
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.style.TextAlign
import kotlin.math.abs
import kotlin.math.max

fun moodColor(score: Int?): Color = when {
    score == null -> C.grey
    score < 25 -> TierC.red
    score < 45 -> TierC.lightRed
    score < 55 -> TierC.yellow
    score < 75 -> TierC.lightGreen
    else -> TierC.darkGreen
}

/**
 * Market (was Money; mockup h04): mood gauge with the one-line hint, mood over the last month, the inputs as meters
 * (fear ← score → greed, line at 50; "How it is built" opens sources and percentiles), Industries | Sectors rotation map
 * (tap a box for its list, h05), money flowing in (top 5 rising industries by momentum), Buys in leading industries.
 */
@Composable
fun MoneyScreen(st: AppState) {
    val pf = st.picks ?: return
    val rot = st.rotation
    val md = pf.mood
    var sectors by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    var how by remember { mutableStateOf(false) }
    val why = rememberIndustryWhy(st)
    var whyOf by remember { mutableStateOf<String?>(null) }
    whyOf?.let { n -> IndustryWhySheet(st, n, rot?.industries?.get(n), why) { whyOf = null } }
    // Buys in leading industries: one scan of all picks per picks.json / rotation.json, not on every recomposition
    val tops = remember(pf, rot) {
        val lead = rot?.industries.orEmpty().filter { it.value.q == "Leading" }.keys
        pf.picks.filter { p -> p.out == null && (p.i ?: "") in lead && isBuy(p) }.sortedByDescending { it.pr }
    }
    var moodInfo by remember { mutableStateOf(false) }
    if (moodInfo) MoodInfoSheet { moodInfo = false }
    LazyColumn(Modifier.fillMaxSize().pageBackground(), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { TopBar(st, "Market", back = st.stack.size > 1, big = st.stack.size == 1) { InfoButton { moodInfo = true } } }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth()) {
                if (md?.score == null) {
                    T("Market mood appears after the next daily run. Old rule: ${pf.regime.label ?: "–"} (breadth ${fmt(pf.regime.breadthPct, 0)}%)", 13.sp, C.dim)
                } else {
                    val series = md.series.mapNotNull { r -> val d = r.getOrNull(0)?.content; val v = r.getOrNull(1)?.content?.toDoubleOrNull(); if (d != null && v != null) d to v else null }
                    if (Look.paper) PaperMoodTop(md, series)
                    else Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { Gauge(md.score, Modifier.size(220.dp, 124.dp), label = md.zone) }
                    if (!Look.paper) md.hint?.let { T(it, 13.sp, lineHeight = 18.sp, align = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 10.dp)) }
                    if (series.size >= 2 && !Look.paper) {
                        T("Mood, last month", 14.sp, weight = FontWeight.SemiBold)
                        AreaLine(series.map { it.second }, Modifier.fillMaxWidth().height(70.dp), color = C.teal, endDot = false,
                            xLabels = listOf(shortDate(series.first().first), shortDate(series.last().first)))
                    }
                    Row(Modifier.padding(top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.Bottom) {
                        if (Look.paper) PaperLabel("What moves the needle", size = 11.sp)
                        else { T("Inputs", 14.sp, weight = FontWeight.SemiBold); T("  fear ← score → greed · line at 50", 11.sp, C.dim, maxLines = 1) }
                    }
                    md.inputs.forEach { i ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            T(INPUT_SHORT[i.k] ?: i.name, 12.sp, C.muted, modifier = Modifier.width(118.dp), maxLines = 1)
                            if (i.score == null) T(i.note ?: "no data today", 11.sp, C.dim, modifier = Modifier.weight(1f), maxLines = 1)
                            else HBar(i.score / 100.0, moodColor(i.score), Modifier.weight(1f), 6.dp, 0.5)
                            T(if (i.score == null || i.value == null) "n/a" else inputValue(i), 12.sp, if (i.score == null) C.dim else C.white, FontWeight.SemiBold,
                                Modifier.width(56.dp), maxLines = 1, align = TextAlign.End)
                        }
                    }
                    ToggleRow("How it is built", "${md.nInputs ?: md.inputs.size} inputs", how, { how = !how }, modifier = Modifier.padding(top = 6.dp))
                    if (how) {
                        md.inputs.forEach { i ->
                            Column(Modifier.padding(vertical = 5.dp)) {
                                T(i.name + (i.value?.let { " · " + fmt(it, 2) + (i.unit?.takeIf { u -> u.isNotBlank() }?.let { u -> " $u" } ?: "") } ?: ""), 13.sp, weight = FontWeight.Medium)
                                i.score?.let { s -> T("Score $s · ${i.pct ?: "–"}th percentile of 3 years · fear when ${i.fearWhen ?: "–"}" + (i.asof?.let { " · $it" } ?: ""), 11.sp, C.dim) }
                                i.note?.let { T(it, 11.sp, C.amber) }
                                i.src?.let { T(it, 11.sp, C.dim) }
                            }
                        }
                        md.method?.let { T(it, 11.sp, C.dim, lineHeight = 15.sp, modifier = Modifier.padding(top = 6.dp)) }
                    }
                }
            }
        }
        if (rot == null) { item { Spacer(Modifier.height(8.dp)); Empty("Rotation data appears after the next daily run.") }; return@LazyColumn }
        item {
            SegmentedControl(listOf("Industries ${rot.industries.size}", "Sectors ${rot.sectors.size}"), if (sectors) 1 else 0, { sectors = it == 1 },
                Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        }
        item {
            val src = if (sectors) rot.sectors else rot.industries
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 12.dp) {
                if (src.isEmpty()) T("No ${if (sectors) "sector" else "industry"} data today.", 13.sp, C.dim)
                else RotationMap(src.values.map { RotPoint(it.ratio, it.mom, it.q) }, Modifier.fillMaxWidth().height(236.dp), colors = QUAD_COLORS,
                    onQuadrant = { q -> st.go(Screen.Quadrant(q, sectors)) })
                Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                    T("← weaker trend · stronger →", 10.sp, C.dim, modifier = Modifier.weight(1f)); T("tap a box", 10.sp, C.dim)
                }
                T("vs " + (if (sectors) rot.bench ?: "Nifty 500" else "our universe (equal weight)") + (if (sectors) " · NSE sector indices, weekly closes" else " · industries with 5+ stocks"),
                    10.sp, C.dim, modifier = Modifier.padding(top = 2.dp))
            }
        }
        val rising = rot.industries.entries.filter { it.value.q in setOf("Leading", "Improving") }.sortedByDescending { it.value.mom }.take(5)
        item {
            SectionCard("Money flowing in", "1 month, top 5 by momentum", Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                more = if (rising.isNotEmpty()) "All rising industries" else null, onMore = { st.go(Screen.Quadrant("Rising", false)) }) {
                if (rising.isEmpty()) T("No industry is leading or improving today.", 13.sp, C.dim)
                val rmax = rising.maxOfOrNull { abs(it.value.r1m ?: 0.0) }?.takeIf { it > 0 } ?: 1.0
                rising.forEach { (ind, r) ->
                    Row(Modifier.fillMaxWidth().clickable { whyOf = ind }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        T(ind, 13.sp, modifier = Modifier.width(128.dp), maxLines = 1)
                        HBar(max(r.r1m ?: 0.0, 0.0) / rmax, quadC(r.q), Modifier.weight(1f), 10.dp)
                        T(sg1(r.r1m), 13.sp, if (r.r1m == null) C.dim else gainColor(r.r1m), FontWeight.SemiBold, Modifier.width(56.dp), maxLines = 1, align = TextAlign.End)
                    }
                }
            }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 0.dp) {
                Row(Modifier.padding(start = S.cardPad, end = S.cardPad, top = 14.dp, bottom = 10.dp), verticalAlignment = Alignment.Bottom) {
                    T("Buys in leading industries", 15.sp, weight = FontWeight.SemiBold); T("  ${tops.size}", 15.sp, C.dim)
                }
                if (tops.isEmpty()) T("No Buy-rated stock in a leading industry today.", 13.sp, C.dim, modifier = Modifier.padding(start = S.cardPad, bottom = 14.dp))
                else LazyRow(contentPadding = PaddingValues(start = S.cardPad, end = S.cardPad, bottom = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(tops, key = { it.s }) { MiniStockCard(st, it) }
                }
            }
        }
    }
}

private val INPUT_SHORT = mapOf("vix" to "India VIX", "nifty_200" to "Nifty vs 200-day", "breadth" to "Above 200-day", "highs_lows" to "52w highs − lows",
    "adv_dec" to "Advance / decline", "pcr" to "Put-call ratio", "fii" to "FII net buying")

/** Input value as on the mockup: breadth 46.1%, signed % for % inputs, two decimals otherwise. */
private fun inputValue(i: MoodInput): String {
    val v = i.value ?: return "n/a"
    val u = i.unit.orEmpty()
    return when {
        i.k == "breadth" -> String.format(java.util.Locale.US, "%.1f%%", v)
        u.startsWith("%") -> sg1(v)
        else -> String.format(java.util.Locale.US, "%.2f", v)
    }
}

@Composable
fun IndRow(ind: String, r: Rot) {
    Column(Modifier.padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            T(ind, 14.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f), maxLines = 1)
            T("1M ${pctStr(r.r1m)}", 12.sp, pctColor(r.r1m)); Spacer(Modifier.width(8.dp)); QuadPill(r.q)
        }
        val m = ((r.mom - 94) / 12).coerceIn(0.0, 1.0).toFloat()
        Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f).height(4.dp).clip(rr(2.dp)).background(C.chip)) { Box(Modifier.fillMaxWidth(m).fillMaxHeight().background(quadC(r.q))) }
            Spacer(Modifier.width(8.dp)); T("momentum ${fmt(r.mom, 1)}" + (r.n?.let { " · $it stocks" } ?: ""), 11.sp, C.dim)
        }
    }
}

/** Semicircle gauge, red (fear) to green (greed). */
@Composable
fun MoodGauge(score: Int, modifier: Modifier) {
    val tm = androidx.compose.ui.text.rememberTextMeasurer()
    Canvas(modifier) {
        val sw = 18.dp.toPx()
        val d = minOf(size.width, size.height * 2) - sw
        val tl = Offset((size.width - d) / 2, sw / 2)
        val zones = listOf(0 to 25, 25 to 45, 45 to 55, 55 to 75, 75 to 100)
        zones.forEach { (a, b) ->
            drawArc(moodColor(a).copy(alpha = 0.85f), 180f + a * 1.8f + 1f, (b - a) * 1.8f - 2f, false, tl, Size(d, d), style = Stroke(sw, cap = StrokeCap.Butt))
        }
        val ang = Math.toRadians(180.0 + score * 1.8)
        val c = Offset(size.width / 2, tl.y + d / 2)
        val r = d / 2
        val tip = Offset(c.x + (r * 0.82f * kotlin.math.cos(ang)).toFloat(), c.y + (r * 0.82f * kotlin.math.sin(ang)).toFloat())
        drawLine(C.hi, c, tip, 4.dp.toPx(), cap = StrokeCap.Round)
        drawCircle(C.hi, 7.dp.toPx(), c)
        drawCircle(C.lo, 3.dp.toPx(), c)
        // score label on the needle tip (feedback #50)
        val lab = tm.measure("$score", androidx.compose.ui.text.TextStyle(color = C.lo, fontSize = 13.sp, fontWeight = FontWeight.Bold))
        val w = lab.size.width + 14.dp.toPx(); val h = lab.size.height + 6.dp.toPx()
        drawRoundRect(C.hi, Offset(tip.x - w / 2, tip.y - h / 2), Size(w, h), androidx.compose.ui.geometry.CornerRadius(h / 2, h / 2))
        drawText(lab, topLeft = Offset(tip.x - lab.size.width / 2f, tip.y - lab.size.height / 2f))
    }
}


/** Paper look, Market (mock-up): headline from the zone and the month's move, the big dial with zone edges, score and zone,
 *  the hint, and the month's mood drawn over faint zone bands. */
@androidx.compose.runtime.Composable
fun PaperMoodTop(md: Mood, series: List<Pair<String, Double>>) {
    val score = md.score ?: return
    val zi = zoneTextInk(score.toDouble())
    androidx.compose.material3.Text(androidx.compose.ui.text.buildAnnotatedString {
        append("The market weather: ")
        pushStyle(androidx.compose.ui.text.SpanStyle(color = zi)); append((md.zone ?: "").lowercase()); pop()
        md.chg1m?.let { append(if (it > 0) ", but lifting" else if (it < 0) ", and sinking" else ", unchanged") }
    }, fontSize = 23.sp, lineHeight = 27.sp, color = C.white, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black,
        textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp))
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { PaperGauge(score, Modifier.size(250.dp, 135.dp), stroke = 17.dp, ticks = true) }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.Bottom) {
        androidx.compose.material3.Text("$score", fontSize = 44.sp, lineHeight = 46.sp, color = zi, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black)
        androidx.compose.material3.Text("  " + (md.zone ?: ""), fontSize = 20.sp, color = zi, fontFamily = PaperFonts.serif,
            fontStyle = androidx.compose.ui.text.font.FontStyle.Italic, modifier = Modifier.padding(bottom = 6.dp))
        md.chg1m?.let { T("   " + (if (it >= 0) "▲ " else "▼ ") + abs(it) + " in a month", 12.sp, if (it >= 0) TierC.darkGreen else TierC.red, modifier = Modifier.padding(bottom = 9.dp)) }
    }
    md.hint?.let { T(it, 13.sp, lineHeight = 18.sp, align = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 8.dp)) }
    if (series.size >= 2) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(C.white))
        PaperLabel("The last month", size = 11.sp, modifier = Modifier.padding(top = 6.dp, bottom = 2.dp))
        val ink = C.white
        androidx.compose.foundation.Canvas(Modifier.fillMaxWidth().height(72.dp)) {
            fun y(v: Double) = (size.height - (v / 100.0) * size.height).toFloat()
            var lo = 0.0
            ZONE_INK.forEach { (hi, col, _) ->
                drawRect(col.copy(alpha = 0.13f), androidx.compose.ui.geometry.Offset(0f, y(hi)), androidx.compose.ui.geometry.Size(size.width, y(lo) - y(hi))); lo = hi
            }
            val p = androidx.compose.ui.graphics.Path()
            series.forEachIndexed { i, (_, v) -> val x = i * size.width / (series.size - 1); if (i == 0) p.moveTo(x, y(v)) else p.lineTo(x, y(v)) }
            drawPath(p, ink, style = androidx.compose.ui.graphics.drawscope.Stroke(1.6.dp.toPx()))
            drawCircle(zoneDotInk(series.last().second), 3.dp.toPx(), androidx.compose.ui.geometry.Offset(size.width, y(series.last().second)))
        }
        Row(Modifier.fillMaxWidth()) { T(shortDate(series.first().first), 10.sp, C.dim, modifier = Modifier.weight(1f)); T(shortDate(series.last().first), 10.sp, C.dim) }
        Box(Modifier.padding(top = 6.dp).fillMaxWidth().height(1.dp).background(C.white))
    }
}


/** (i) on Market (feedback #134): how our mood score is built and why it can differ from Tickertape's Market Mood Index. */
@androidx.compose.runtime.Composable
fun MoodInfoSheet(onDismiss: () -> Unit) {
    BottomSheet(onDismiss, "How the mood score works") {
        T("Each input (India VIX, Nifty vs its 200-day average, stocks above their 200-day average, 52-week highs minus lows, " +
            "advance/decline, put-call ratio, FII buying) is ranked against its own last 3 years, from 0 to 100. VIX and the put-call ratio " +
            "count inverted. The score is their average. Under 25 is extreme fear, 25 to 45 fear, 45 to 55 neutral, 55 to 75 greed, above 75 extreme greed.",
            13.sp, lineHeight = 19.sp)
        PaperLabel("Why Tickertape can say something else", size = 11.sp, modifier = Modifier.padding(top = 12.dp, bottom = 4.dp))
        T("Tickertape's Market Mood Index uses partly different inputs (FII activity, volatility and skew, market breadth, price strength) " +
            "and, by public descriptions, compares them with recent weeks rather than years. After a short rally it can read greed while ours, " +
            "measured against 3 years, still reads fear. Ours suits a 3 to 12-month horizon; the change over the last month (shown with the score) " +
            "is the short-term swing.", 13.sp, C.muted, lineHeight = 19.sp)
    }
}
