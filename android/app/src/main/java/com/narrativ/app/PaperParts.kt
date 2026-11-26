package com.narrativ.app

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
fun PaperGauge(score: Int, modifier: Modifier, stroke: Dp = 12.dp, ticks: Boolean = false) {
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
        val a = ang(score.toDouble()); val nl = r - sw - (if (ticks) 18.dp.toPx() else 4.dp.toPx())
        drawLine(ink, c, Offset((c.x + nl * cos(a)).toFloat(), (c.y - nl * sin(a)).toFloat()), 2.5.dp.toPx(), cap = StrokeCap.Round)
        drawCircle(ink, 4.dp.toPx(), c)
    }
}

/** Five-step scale with the tier's step inked (1 = left, best). */
@Composable
fun FiveStep(tier: Int, modifier: Modifier = Modifier.width(110.dp)) {
    Row(modifier.height(7.dp), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        (1..5).forEach { k -> Box(Modifier.weight(1f).height(7.dp).background(if (k == tier) dotInk(k) else SCALE_OFF)) }
    }
}

/** One mark on [PlanLine]. */
data class PlanMark(val label: String, val value: Double, val color: Color)

/** The trading plan as a number line: marks (stop, now, buy above, +5%, analyst) and a shaded buy zone. */
@Composable
fun PlanLine(marks: List<PlanMark>, zone: Pair<Double, Double>?, modifier: Modifier = Modifier.fillMaxWidth().height(50.dp)) {
    if (marks.isEmpty()) return
    val tm = rememberTextMeasurer()
    val ink = C.white; val zoneC = TierC.darkGreen.copy(alpha = 0.22f)
    Canvas(modifier) {
        val vals = marks.map { it.value } + listOfNotNull(zone?.first, zone?.second)
        val lo = vals.min(); val hi = vals.max(); val pad = (hi - lo) * 0.06 + 0.01
        val x0 = 8.dp.toPx(); val x1 = size.width - 8.dp.toPx(); val y = size.height / 2f
        fun x(v: Double) = (x0 + ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (x1 - x0)).toFloat()
        drawLine(ink, Offset(0f, y), Offset(size.width, y), 1.dp.toPx())
        zone?.let { (a, b) -> drawRect(zoneC, Offset(x(a), y - 6.dp.toPx()), Size(x(b) - x(a), 12.dp.toPx())) }
        marks.forEachIndexed { i, m ->
            val mx = x(m.value)
            drawLine(m.color, Offset(mx, y - 8.dp.toPx()), Offset(mx, y + 8.dp.toPx()), 2.dp.toPx())
            val top = tm.measure(m.label.uppercase(), TextStyle(fontSize = 8.5.sp, color = m.color, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold))
            val bot = tm.measure(fmt(m.value, if (m.value >= 100) 0 else 2), TextStyle(fontSize = 9.sp, color = m.color, fontFamily = PaperFonts.label))
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
        androidx.compose.material3.Text(label, fontSize = 11.sp, color = C.bg, fontFamily = PaperFonts.serif, maxLines = 1)
    }
}

/** A meter bar (value of 0..100) with its fill in [color] on a pale track. */
@Composable
fun InkMeter(pct: Double, color: Color, modifier: Modifier = Modifier.fillMaxWidth().height(8.dp)) {
    Box(modifier.background(SCALE_OFF)) { Box(Modifier.fillMaxWidth((pct / 100.0).toFloat().coerceIn(0f, 1f)).height(8.dp).background(color)) }
}
