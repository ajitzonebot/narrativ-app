package com.narrativ.app

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/*
 * Paper look, drawn parts (owner, 25 Nov 2026: "exactly match the Narrativ on paper mock-ups"): the pictures the mock-ups
 * use to show instead of say. Dot inks are a little lighter than text inks (they carry no text); text uses TierC.
 */

/** Dot / bar inks by tier: 1 best .. 5 worst, 0 no data. */
fun dotInk(t: Int): Color = when (t) {
    1 -> Color(0xFF2F5A36); 2 -> Color(0xFF5E7A2E); 3 -> Color(0xFFB08A2A); 4 -> Color(0xFFB0603E); 5 -> Color(0xFF862A22); else -> Color(0xFFA39888)
}
private val SCALE_OFF = Color(0xFFD8CCB4)

/** Mood zones as ink: upper bound, dot ink, text ink. */
val ZONE_INK = listOf(Triple(25.0, Color(0xFF862A22), Color(0xFF862A22)), Triple(45.0, Color(0xFFB0603E), Color(0xFF9A4A2E)),
    Triple(55.0, Color(0xFFB08A2A), Color(0xFF765A0C)), Triple(75.0, Color(0xFF5E7A2E), Color(0xFF47632A)), Triple(100.0, Color(0xFF2F5A36), Color(0xFF2F5A36)))
fun zoneDotInk(s: Double): Color = ZONE_INK.first { s < it.first || it.first == 100.0 }.second
fun zoneTextInk(s: Double): Color = ZONE_INK.first { s < it.first || it.first == 100.0 }.third

/** "▲ 0.29%" / "▼ 1.86%": direction is shown by the arrow as well as the colour. */
fun arrowPct(v: Double?): String = if (v == null) "–" else (if (v >= 0) "▲ " else "▼ ") + fmt(kotlin.math.abs(v), 2) + "%"

/** Seven level dots in ink. */
@Composable
fun InkDots(t: List<Int>, dot: Dp = 7.dp, gap: Dp = 3.dp) {
    Row(horizontalArrangement = Arrangement.spacedBy(gap), verticalAlignment = Alignment.CenterVertically) {
        (0 until 7).forEach { i -> Box(Modifier.size(dot).clip(CircleShape).background(dotInk(t.getOrElse(i) { 0 }))) }
    }
}

/** A thin price line (no fill), in the day's gain or loss ink. */
@Composable
fun InkSpark(values: List<Double>, color: Color, modifier: Modifier = Modifier.size(60.dp, 24.dp)) {
    if (values.size < 2) { Box(modifier); return }
    Canvas(modifier) {
        val lo = values.min(); val hi = values.max(); val span = (hi - lo).takeIf { it > 0 } ?: 1.0
        val p = Path()
        values.forEachIndexed { i, v ->
            val x = i * size.width / (values.size - 1); val y = (size.height - 2f) - ((v - lo) / span).toFloat() * (size.height - 4f)
            if (i == 0) p.moveTo(x, y) else p.lineTo(x, y)
        }
        drawPath(p, color, style = Stroke(1.3.dp.toPx()))
    }
}

/** Half-dial mood gauge: five zone arcs in ink and a needle; [ticks] prints the zone edges. */
@Composable
fun PaperGauge(score: Float, modifier: Modifier, stroke: Dp = 12.dp, ticks: Boolean = false) {
    val tm = rememberTextMeasurer()
    val ink = C.white; val dim = C.dim
    Canvas(modifier) {
        val sw = stroke.toPx()
        val r = minOf(size.width / 2f, size.height) - sw / 2f - 2f
        val c = Offset(size.width / 2f, size.height - 4f)
        fun ang(v: Double) = PI * (1 - v / 100.0)
        var from = 0.0
        ZONE_INK.forEach { (to, col, _) ->
            val a0 = ang(from + 0.6); val a1 = ang(to - 0.6)
            drawArc(col, startAngle = (-a0 * 180 / PI).toFloat(), sweepAngle = ((a0 - a1) * 180 / PI).toFloat(), useCenter = false,
                topLeft = Offset(c.x - r, c.y - r), size = Size(2 * r, 2 * r), style = Stroke(sw))
            from = to
        }
        if (ticks) listOf(0, 25, 45, 55, 75, 100).forEach { v ->
            val a = ang(v.toDouble()); val rr = r - sw - 8.dp.toPx()
            val l = tm.measure("$v", TextStyle(fontSize = 9.sp, color = dim, fontFamily = PaperFonts.label))
            drawText(l, topLeft = Offset((c.x + rr * cos(a)).toFloat() - l.size.width / 2f, (c.y - rr * sin(a)).toFloat() - l.size.height / 2f))
        }
        val a = ang(score.toDouble().coerceIn(0.0, 100.0)); val nl = r - sw - (if (ticks) 18.dp.toPx() else 4.dp.toPx())
        drawLine(ink, c, Offset((c.x + nl * cos(a)).toFloat(), (c.y - nl * sin(a)).toFloat()), 2.5.dp.toPx(), cap = StrokeCap.Round)
        drawCircle(ink, 4.dp.toPx(), c)
    }
}

/** Feedback #137: the needle eases from 0 to [score] in 1 s, once per opening (kept across scrolling); the number shown beside
 *  the dial reads the same value, so it counts up and stops on the score as the needle stops. */
@Composable
fun rememberSwing(score: Int): Float {
    val played = androidx.compose.runtime.saveable.rememberSaveable { androidx.compose.runtime.mutableStateOf(false) }
    val a = androidx.compose.runtime.remember { androidx.compose.animation.core.Animatable(if (played.value) score.toFloat() else 0f) }
    androidx.compose.runtime.LaunchedEffect(score) {
        if (played.value) a.snapTo(score.toFloat())
        else { a.animateTo(score.toFloat(), androidx.compose.animation.core.tween(1000, easing = androidx.compose.animation.core.FastOutSlowInEasing)); played.value = true }
    }
    return a.value
}

/** Five-step scale with the tier's step inked (1 = left, best). */
@Composable
fun FiveStep(tier: Int, modifier: Modifier = Modifier.width(110.dp)) {
    Row(modifier.height(7.dp), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        (1..5).forEach { k -> Box(Modifier.weight(1f).height(7.dp).background(if (k == tier) dotInk(k) else SCALE_OFF)) }
    }
}

/** One mark on [PlanLine]. */
data class PlanMark(val label: String, val value: Double, val color: Color, val extra: String? = null)

/** The trading plan as a number line: marks (stop, now, buy above, +5%, analyst) and a shaded buy zone. */
@Composable
fun PlanLine(marks: List<PlanMark>, zone: Pair<Double, Double>?, modifier: Modifier = Modifier.fillMaxWidth().height(50.dp), zoneLabel: String? = null) {
    if (marks.isEmpty()) return
    val tm = rememberTextMeasurer()
    val ink = C.white; val zoneC = TierC.darkGreen.copy(alpha = 0.22f)
    Canvas(modifier) {
        val vals = marks.map { it.value } + listOfNotNull(zone?.first, zone?.second)
        val lo = vals.min(); val hi = vals.max(); val pad = (hi - lo) * 0.06 + 0.01
        val x0 = 8.dp.toPx(); val x1 = size.width - 8.dp.toPx(); val y = if (zoneLabel != null && zone != null) size.height * 0.62f else size.height / 2f
        fun x(v: Double) = (x0 + ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (x1 - x0)).toFloat()
        drawLine(ink, Offset(0f, y), Offset(size.width, y), 1.dp.toPx())
        zone?.let { (a, b) ->
            drawRect(zoneC, Offset(x(a), y - 6.dp.toPx()), Size(x(b) - x(a), 12.dp.toPx()))
            // feedback #129: the setup is written over the buy zone ("BREAKING OUT ↑")
            zoneLabel?.let { zl ->
                val t = tm.measure(zl, TextStyle(fontSize = 9.5.sp, color = Color(0xFF2F5A36), fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold))
                val cx = (x(a) + x(b)) / 2f
                drawText(t, topLeft = Offset((cx - t.size.width / 2f).coerceIn(0f, size.width - t.size.width), 0f))
            }
        }
        marks.forEachIndexed { i, m ->
            val mx = x(m.value)
            drawLine(m.color, Offset(mx, y - 8.dp.toPx()), Offset(mx, y + 8.dp.toPx()), 2.dp.toPx())
            val top = tm.measure(m.label.uppercase(), TextStyle(fontSize = 8.5.sp, color = m.color, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold))
            val bot = tm.measure(fmt(m.value, if (m.value >= 100) 0 else 2) + (m.extra?.let { " · $it" } ?: ""), TextStyle(fontSize = 9.sp, color = m.color, fontFamily = PaperFonts.label))
            fun lx(w: Int) = when (i) { 0 -> (mx - 1f).coerceAtLeast(0f); marks.lastIndex -> (mx - w + 1f).coerceAtMost(size.width - w); else -> mx - w / 2f }
            drawText(top, topLeft = Offset(lx(top.size.width), y - 10.dp.toPx() - top.size.height))
            drawText(bot, topLeft = Offset(lx(bot.size.width), y + 10.dp.toPx()))
        }
    }
}

/** A dated event on [DateStrip]. */
data class StripMark(val date: LocalDate, val color: Color, val weight: Int = 1)

/** Today → last date as one line, month ticks, one ink dot per date (bigger when more falls on it). */
@Composable
fun DateStrip(marks: List<StripMark>, today: LocalDate, modifier: Modifier = Modifier.fillMaxWidth().height(46.dp)) {
    if (marks.isEmpty()) return
    val tm = rememberTextMeasurer()
    val ink = C.white; val dim = C.dim; val tap = C.teal
    val end = marks.maxOf { it.date }.plusDays(4)
    Canvas(modifier) {
        val span = (end.toEpochDay() - today.toEpochDay()).coerceAtLeast(1).toFloat()
        val x0 = 6.dp.toPx(); val x1 = size.width - 6.dp.toPx(); val y = 20.dp.toPx()
        fun x(d: LocalDate) = x0 + (d.toEpochDay() - today.toEpochDay()) / span * (x1 - x0)
        drawLine(ink, Offset(0f, y), Offset(size.width, y), 1.dp.toPx())
        var m = today.withDayOfMonth(1).plusMonths(1)
        while (!m.isAfter(end)) {
            val mx = x(m)
            drawLine(dim, Offset(mx, y - 4.dp.toPx()), Offset(mx, y + 4.dp.toPx()), 1.dp.toPx())
            val l = tm.measure(m.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH).uppercase(),
                TextStyle(fontSize = 9.sp, color = dim, fontFamily = PaperFonts.label))
            drawText(l, topLeft = Offset(mx - l.size.width / 2f, y + 8.dp.toPx()))
            m = m.plusMonths(1)
        }
        marks.forEach { drawCircle(it.color, (3.5f + it.weight.coerceAtMost(4)).dp.toPx(), Offset(x(it.date), y)) }
        val tl = tm.measure("TODAY", TextStyle(fontSize = 9.sp, color = tap, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold))
        drawPath(Path().apply { moveTo(x0 - 3.dp.toPx(), 4.dp.toPx()); lineTo(x0 + 3.dp.toPx(), 4.dp.toPx()); lineTo(x0, 10.dp.toPx()); close() }, tap)
        drawText(tl, topLeft = Offset(x0 + 6.dp.toPx(), 0f))
    }
}

/** Funnel step: an ink bar holding its label (2,359 companies → 162 read → 15 Buy). */
@Composable
fun FunnelBar(label: String, fraction: Float, color: Color) {
    Box(Modifier.fillMaxWidth(fraction).height(20.dp).background(color).padding(horizontal = 6.dp), contentAlignment = Alignment.CenterStart) {
        // feedback #119: left-aligned, centred top to bottom (no font padding, line box trimmed)
        androidx.compose.material3.Text(label, fontSize = 11.sp, color = C.bg, fontFamily = PaperFonts.serif, maxLines = 1,
            style = TextStyle(platformStyle = androidx.compose.ui.text.PlatformTextStyle(includeFontPadding = false),
                lineHeight = 11.sp, lineHeightStyle = androidx.compose.ui.text.style.LineHeightStyle(
                    androidx.compose.ui.text.style.LineHeightStyle.Alignment.Center, androidx.compose.ui.text.style.LineHeightStyle.Trim.Both)))
    }
}

/** A meter bar (value of 0..100) with its fill in [color] on a pale track. */
@Composable
fun InkMeter(pct: Double, color: Color, modifier: Modifier = Modifier.fillMaxWidth().height(8.dp)) {
    Box(modifier.background(SCALE_OFF)) { Box(Modifier.fillMaxWidth((pct / 100.0).toFloat().coerceIn(0f, 1f)).height(8.dp).background(color)) }
}


/** Revenue bars with the quarter's profit drawn inside each bar (below the base when it is a loss) and the margin as a line of
 *  dots with the % inside each dot (owner, 26 Nov 2026, feedback #132). Labels: profit on top of its green part (feedback #142),
 *  revenue on top of the bar, one line higher when the two would touch. */
@Composable
fun RevenueProfitChart(rev: List<Double>, profit: List<Double?>, margin: List<Double?>, labels: List<String>,
                       modifier: Modifier = Modifier.fillMaxWidth().height(250.dp)) {
    if (rev.isEmpty()) return
    val tm = rememberTextMeasurer()
    val barC = if (Look.paper) Color(0xFFCBBDA3) else C.muted.copy(alpha = 0.45f)
    val gain = TierC.darkGreen; val loss = TierC.red; val ink = C.white; val dim = C.dim; val mC = C.amber; val onDot = C.bg
    Canvas(modifier) {
        val n = rev.size
        val hasM = margin.size == n && margin.all { it != null }
        val bottomLab = 16.dp.toPx(); val topPad = 28.dp.toPx()  // room for revenue + profit values on two lines
        val mBand = if (hasM) size.height * 0.36f else 0f            // the margin line sits above the bars
        val minP = profit.filterNotNull().minOrNull()?.coerceAtMost(0.0) ?: 0.0
        val maxV = rev.max().coerceAtLeast(1.0)
        val barTop = mBand + topPad; val barBottom = size.height - bottomLab
        val span = maxV - minP
        fun y(v: Double) = (barBottom - ((v - minP) / span) * (barBottom - barTop)).toFloat()
        val base = y(0.0)
        val slot = size.width / n; val bw = slot * 0.62f
        val lab = { s: String, c: Color, w: FontWeight -> tm.measure(s, TextStyle(fontSize = 9.sp, color = c, fontWeight = w, fontFamily = if (Look.paper) PaperFonts.label else null)) }
        drawLine(ink, Offset(0f, base), Offset(size.width, base), 1.dp.toPx())
        for (i in 0 until n) {
            val cx = slot * i + slot / 2f; val x0 = cx - bw / 2f
            drawRect(barC, Offset(x0, y(rev[i])), Size(bw, base - y(rev[i])))
            val rl = lab(fmt(rev[i], 0), ink, FontWeight.Bold)
            var ry = y(rev[i]) - rl.size.height - 1f
            profit.getOrNull(i)?.let { p ->
                val top = minOf(y(p), base); val h = kotlin.math.abs(base - y(p))
                drawRect(if (p >= 0) gain else loss, Offset(x0, top), Size(bw, h))
                // feedback #142: the profit value sits on top of the green part, in green (a loss: under the base line, in red);
                // when it would touch the revenue value, the revenue value moves one line up
                val pl = lab(fmt(p, 0), if (p >= 0) gain else loss, FontWeight.Bold)
                val py = if (p >= 0) top - pl.size.height - 1f else top + h + 1f
                if (p >= 0 && py < ry + rl.size.height) ry = py - rl.size.height - 1f
                drawText(pl, topLeft = Offset(cx - pl.size.width / 2f, py))
            }
            drawText(rl, topLeft = Offset(cx - rl.size.width / 2f, ry))
            val xl = lab(labels.getOrElse(i) { "" }, dim, FontWeight.Normal)
            drawText(xl, topLeft = Offset(cx - xl.size.width / 2f, size.height - xl.size.height))
        }
        if (hasM) {
            val ms = margin.map { it!! }
            val lo = minOf(ms.min(), 0.0); val hi = maxOf(ms.max(), 1.0)
            val r = 11.dp.toPx()
            fun my(m: Double) = (r + 2f + (1 - (m - lo) / (hi - lo)) * (mBand - 2 * r - 4f)).toFloat()
            val path = Path()
            ms.forEachIndexed { i, m -> val cx = slot * i + slot / 2f; if (i == 0) path.moveTo(cx, my(m)) else path.lineTo(cx, my(m)) }
            drawPath(path, mC, style = Stroke(1.5.dp.toPx()))
            ms.forEachIndexed { i, m ->
                val cx = slot * i + slot / 2f
                drawCircle(mC, r, Offset(cx, my(m)))
                val t = tm.measure("${fmt(m, 0)}%", TextStyle(fontSize = 8.sp, color = onDot, fontWeight = FontWeight.Bold, fontFamily = if (Look.paper) PaperFonts.label else null))
                drawText(t, topLeft = Offset(cx - t.size.width / 2f, my(m) - t.size.height / 2f))
            }
        }
    }
    Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).background(barC)); T("Revenue", 11.sp, C.dim)
        Box(Modifier.size(9.dp).background(gain)); T("Profit", 11.sp, C.dim)
        if (margin.isNotEmpty()) { Box(Modifier.size(9.dp).clip(CircleShape).background(mC)); T("EBITDA margin", 11.sp, C.dim) }
    }
}


/** The latest 50/200-day cross in the chart's year: golden (50-day rises above the 200-day) in green, death (falls below) in
 *  red, marked on a price chart with both averages (owner, 26 Nov 2026, feedback #133). Shown only: no rule uses it. The cross
 *  month is read from the chart's span (first day d0 to the data date), so it is given as a month, not a day. */
@Composable
fun CrossCard(ch: Chart, dataDate: String?) {
    val a = ch.sma50; val b = ch.sma200; val c = ch.c
    val n = minOf(a.size, b.size, c.size)
    if (n < 30 || a.lastOrNull() == null || b.lastOrNull() == null) return
    var k = -1
    for (i in 1 until n) { val x0 = a[i - 1]; val y0 = b[i - 1]; val x1 = a[i]; val y1 = b[i]
        if (x0 != null && y0 != null && x1 != null && y1 != null && (x1 - y1) * (x0 - y0) < 0) k = i }
    val above = a[n - 1]!! > b[n - 1]!!
    val golden = above
    val col = if (golden) TierC.darkGreen else TierC.red
    val d0 = runCatching { java.time.LocalDate.parse(ch.d0) }.getOrNull()
    val dEnd = runCatching { java.time.LocalDate.parse(dataDate) }.getOrNull()
    val month = if (k >= 0 && d0 != null && dEnd != null) d0.plusDays(((dEnd.toEpochDay() - d0.toEpochDay()) * k / (n - 1).toDouble()).toLong())
        .let { "${it.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)} ${it.year}" } else null
    val name = if (golden) "Golden cross" else "Death cross"
    SectionCard("50-day vs 200-day average", if (k >= 0) "$name${month?.let { " · $it" } ?: ""}" else if (above) "50-day above all year" else "50-day below all year") {
        val ink = C.white; val grey = C.dim
        Canvas(Modifier.fillMaxWidth().height(150.dp)) {
            val vals = (0 until n).flatMap { listOfNotNull(c[it], a[it], b[it]) }
            val lo = vals.min(); val hi = vals.max(); val sp = (hi - lo).takeIf { it > 0 } ?: 1.0
            fun x(i: Int) = i * size.width / (n - 1)
            fun y(v: Double) = (size.height - 6f - ((v - lo) / sp) * (size.height - 12f)).toFloat()
            fun line(s: List<Double?>, col: Color, w: Float, dash: Boolean) {
                val p = Path(); var started = false
                for (i in 0 until n) { val v = s[i] ?: continue; if (!started) { p.moveTo(x(i), y(v)); started = true } else p.lineTo(x(i), y(v)) }
                drawPath(p, col, style = Stroke(w, pathEffect = if (dash) androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(10f, 6f)) else null))
            }
            line(c, grey, 1.2.dp.toPx(), false)
            line(a, TierC.darkGreen, 2.dp.toPx(), false)
            line(b, ink, 2.dp.toPx(), true)
            if (k >= 0) { val v = (a[k]!! + b[k]!!) / 2; drawCircle(col, 6.dp.toPx(), Offset(x(k), y(v)), style = Stroke(2.dp.toPx())) }
        }
        Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            T("━ 50-day", 11.sp, TierC.darkGreen); T("╌ 200-day", 11.sp, C.white); T("— price", 11.sp, C.dim)
        }
        T("50-day ₹${fmt(a[n - 1], 1)} ${if (above) "above" else "below"} 200-day ₹${fmt(b[n - 1], 1)}" + (if (k >= 0 && month != null) " · crossed in $month" else ""),
            12.sp, col, FontWeight.SemiBold, modifier = Modifier.padding(top = 4.dp))
    }
}

/** A row's second line that does not fit scrolls slowly left after 2 s and loops, so the hidden end shows (owner, 26 Nov 2026).
 *  Text that fits stays still. */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
fun Modifier.rowMarquee(): Modifier = this.basicMarquee(iterations = Int.MAX_VALUE, initialDelayMillis = 2000, velocity = 28.dp)
