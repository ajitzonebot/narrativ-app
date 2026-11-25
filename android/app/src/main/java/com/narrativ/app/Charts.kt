package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/*
 * Charts for the redesign ("show, don't say"): small, stateless Canvas composables drawn to match the approved
 * mockups (scratchpad/mock/screens_*.py). Data and colours come in as parameters; scaling lives in ChartMath.
 * Every chart takes a Modifier that sets its size (each has a sensible default height).
 */

// ---------------------------------------------------------------- shared drawing helpers
enum class Anchor { Start, Middle, End }

/** Draw one line of text with its baseline at [y]; tabular digits. Optional pill background (chart tags). */
fun DrawScope.chartText(tm: TextMeasurer, s: String, x: Float, y: Float, color: Color, size: TextUnit = 10.sp,
                        weight: FontWeight = FontWeight.Normal, anchor: Anchor = Anchor.Start, bg: Color? = null) {
    if (s.isEmpty()) return
    val r = tm.measure(AnnotatedString(s), TextStyle(color = color, fontSize = size, fontWeight = weight, fontFeatureSettings = "tnum"),
        overflow = TextOverflow.Clip, softWrap = false, maxLines = 1)
    val w = r.size.width.toFloat()
    val left = when (anchor) { Anchor.Start -> x; Anchor.Middle -> x - w / 2; Anchor.End -> x - w }
    val top = y - r.firstBaseline
    if (bg != null) drawRoundRect(bg, Offset(left - 5.dp.toPx(), top - 1.dp.toPx()), Size(w + 10.dp.toPx(), r.size.height + 2.dp.toPx()),
        CornerRadius(8.dp.toPx()))
    drawText(r, topLeft = Offset(left, top))
}

/** Smooth path through the points (ChartMath.smooth). */
fun smoothPath(pts: List<Offset>, k: Float = 1f / 8f, into: Path = Path(), moveFirst: Boolean = true): Path {
    if (pts.isEmpty()) return into
    if (moveFirst) into.moveTo(pts[0].x, pts[0].y) else into.lineTo(pts[0].x, pts[0].y)
    ChartMath.smooth(pts.map { it.x }, pts.map { it.y }, k).forEach { s -> into.cubicTo(s[0], s[1], s[2], s[3], s[4], s[5]) }
    return into
}

private val dash = PathEffect.dashPathEffect(floatArrayOf(10f, 10f))
private val dashFine = PathEffect.dashPathEffect(floatArrayOf(8f, 10f))
/** Track behind bars, meters and gauges (#ffffff1a in the mockups). */
val TRACK = C.line
private val KNOB_RING = C.card2

// ---------------------------------------------------------------- AreaLine
/** Horizontal level on a line chart (exit, buy-rest, pass line), dashed by default, label as a dark tag at the left. */
data class HLine(val value: Double, val color: Color, val label: String? = null, val dashed: Boolean = true, val labelBelow: Boolean = false)
/** Shaded horizontal band between two values (buy zone, analyst range), optional tag label at its top. */
/** A labelled dot on the line at [index] (the 52-week "H" / "L" closes); the label sits above or below the dot. */
data class PointMark(val index: Int, val label: String, val above: Boolean)
data class HBand(val lo: Double, val hi: Double, val color: Color, val label: String? = null, val alpha: Float = 0.22f)
/** Extra line on a line chart (e.g. 50-day / 200-day average); nulls leave gaps. */
data class Series(val values: List<Double?>, val color: Color, val endLabel: String? = null, val width: Dp = 1.8.dp)
enum class EndLabel { Above, Right }

/**
 * Smooth line with a soft area fill. Used for price (1Y with buy zone / exit levels), P/E band (cheap / expensive zones,
 * dashed median, "today" dot), promoter and institutional holding, market mood, 6-month price with 50/200-day lines.
 * - [lo]/[hi] fix the y scale (else min/max of everything drawn, 6% padding).
 * - [endLabel] at the last point: above-left ([EndLabel.Above]) or in a right gutter ([EndLabel.Right], where overlay labels go too).
 * - [today]: a dashed hop from the last point to a dot in the right gutter labelled [todayLabel] / [todayCaption].
 * - [xLabels] spread under the plot (first left-aligned, last right-aligned).
 */
@Composable
fun AreaLine(
    values: List<Double>, modifier: Modifier = Modifier.fillMaxWidth().height(150.dp),
    color: Color = C.teal, fillAlpha: Float = 0.28f, strokeWidth: Dp = 2.2.dp,
    xs: List<Float>? = null, lo: Double? = null, hi: Double? = null,
    median: Double? = null, medianLabel: String? = null,
    cheapBelow: Double? = null, cheapLabel: String? = null, expensiveAbove: Double? = null, expensiveLabel: String? = null,
    bands: List<HBand> = emptyList(), lines: List<HLine> = emptyList(), overlays: List<Series> = emptyList(),
    endLabel: String? = null, endLabelPos: EndLabel = EndLabel.Above, endLabelColor: Color = C.white,
    endDot: Boolean = true, hollowEnd: Boolean = false, pointDots: Boolean = false,
    today: Double? = null, todayLabel: String? = null, todayCaption: String? = "today", todayColor: Color = TierC.lightGreen,
    xLabels: List<String> = emptyList(), rightGutter: Dp? = null, marks: List<PointMark> = emptyList(),
) {
    if (values.size < 2) return
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val gutter = (rightGutter ?: when { endLabelPos == EndLabel.Right -> 74.dp; today != null -> 58.dp; else -> 0.dp }).toPx()
        val left = 4.dp.toPx(); val right = size.width - gutter - (if (gutter > 0) 0f else 4.dp.toPx())
        val top = 8.dp.toPx(); val bottom = size.height - (if (xLabels.isNotEmpty()) 16.dp else 2.dp).toPx()
        val all = values + overlays.flatMap { it.values }.filterNotNull() + lines.map { it.value } + bands.flatMap { listOf(it.lo, it.hi) } +
            listOfNotNull(median, cheapBelow, expensiveAbove, today)
        val (rlo, rhi) = ChartMath.range(all, 0.06)
        val ylo = lo ?: rlo; val yhi = hi ?: rhi
        fun y(v: Double) = ChartMath.lerp(v, ylo, yhi, bottom, top)
        fun x(i: Int, n: Int) = left + (xs?.getOrNull(i) ?: (i / (n - 1f))) * (right - left)
        val pts = values.indices.map { Offset(x(it, values.size), y(values[it])) }

        // zones and levels
        if (cheapBelow != null) {
            drawRoundRect(TierC.darkGreen.copy(alpha = 0.13f), Offset(0f, y(cheapBelow)), Size(size.width, bottom - y(cheapBelow)), CornerRadius(8.dp.toPx()))
            cheapLabel?.let { chartText(tm, it, 6.dp.toPx(), bottom - 6.dp.toPx(), TierC.lightGreen, 10.sp) }
        }
        if (expensiveAbove != null) {
            drawRoundRect(TierC.red.copy(alpha = 0.10f), Offset(0f, 0f), Size(size.width, y(expensiveAbove)), CornerRadius(8.dp.toPx()))
            expensiveLabel?.let { chartText(tm, it, 6.dp.toPx(), 13.dp.toPx(), TierC.lightRed, 10.sp) }
        }
        bands.forEach { b -> drawRoundRect(b.color.copy(alpha = b.alpha), Offset(0f, y(b.hi)), Size(size.width, y(b.lo) - y(b.hi)), CornerRadius(4.dp.toPx())) }
        if (median != null) {
            drawLine(TierC.grey, Offset(0f, y(median)), Offset(size.width, y(median)), 1.dp.toPx(), pathEffect = dashFine)
            medianLabel?.let { chartText(tm, it, size.width, y(median) - 5.dp.toPx(), C.dim, 9.5.sp, anchor = Anchor.End) }
        }
        lines.forEach { l ->
            drawLine(l.color.copy(alpha = 0.8f), Offset(0f, y(l.value)), Offset(size.width, y(l.value)), 1.dp.toPx(), pathEffect = if (l.dashed) dash else null)
        }

        // overlays, then the main area and line
        overlays.forEach { s ->
            var run = mutableListOf<Offset>()
            fun flush() { if (run.size >= 2) drawPath(smoothPath(run), s.color, style = Stroke(s.width.toPx(), cap = StrokeCap.Round)); run = mutableListOf() }
            s.values.forEachIndexed { i, v -> if (v == null) flush() else run += Offset(x(i, s.values.size), y(v)) }
            flush()
        }
        val line = smoothPath(pts)
        val area = smoothPath(pts).apply { lineTo(pts.last().x, bottom); lineTo(pts.first().x, bottom); close() }
        drawPath(area, Brush.verticalGradient(listOf(color.copy(alpha = fillAlpha), color.copy(alpha = 0f)), startY = pts.minOf { it.y }, endY = bottom))
        drawPath(line, color, style = Stroke(strokeWidth.toPx(), cap = StrokeCap.Round))
        if (pointDots) pts.forEach { drawCircle(color, 3.5.dp.toPx(), it) }

        // level tags drawn over the line so they stay readable
        bands.forEach { b -> b.label?.let { chartText(tm, it, 7.dp.toPx(), y(b.hi) - 5.dp.toPx(), b.color, 10.sp, FontWeight.SemiBold, bg = Color.Black.copy(alpha = 0.8f)) } }
        lines.forEach { l -> l.label?.let { chartText(tm, it, 7.dp.toPx(), y(l.value) + (if (l.labelBelow) 14 else -4).dp.toPx(), l.color, 10.sp, FontWeight.SemiBold, bg = Color.Black.copy(alpha = 0.8f)) } }

        marks.forEach { m ->
            val o = pts.getOrNull(m.index) ?: return@forEach
            drawCircle(C.card, 6.dp.toPx(), o); drawCircle(C.white, 4.dp.toPx(), o)
            val ly = if (m.above) max(10.dp.toPx(), o.y - 9.dp.toPx()) else min(size.height - 1.dp.toPx(), o.y + 17.dp.toPx())
            chartText(tm, m.label, o.x.coerceIn(5.dp.toPx(), size.width - 5.dp.toPx()), ly, C.white, 10.5.sp, FontWeight.Bold, Anchor.Middle)
        }

        val last = pts.last()
        if (today != null) {
            val tx = size.width - 22.dp.toPx(); val ty = y(today)
            val hop = Path().apply { moveTo(last.x, last.y); cubicTo(last.x + 18.dp.toPx(), last.y, size.width - 40.dp.toPx(), ty, tx, ty) }
            drawPath(hop, color, style = Stroke(2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4f, 6f))))
            drawCircle(C.card, 9.dp.toPx(), Offset(tx, ty)); drawCircle(todayColor, 6.5.dp.toPx(), Offset(tx, ty))
            todayLabel?.let { chartText(tm, it, size.width, ty - 11.dp.toPx(), C.white, 12.sp, FontWeight.Bold, Anchor.End) }
            todayCaption?.let { chartText(tm, it, size.width, ty + 20.dp.toPx(), todayColor, 10.sp, anchor = Anchor.End) }
        }
        if (endDot) {
            if (hollowEnd) { drawCircle(Color.Black, 4.5.dp.toPx(), last); drawCircle(C.white, 4.5.dp.toPx(), last, style = Stroke(2.dp.toPx())) }
            else { drawCircle(C.card, 6.dp.toPx(), last); drawCircle(color, 4.dp.toPx(), last) }
        }
        if (endLabelPos == EndLabel.Right) {
            val labs = listOfNotNull(endLabel?.let { Triple(last.y, it, endLabelColor) }) + overlays.mapNotNull { s ->
                val i = s.values.indexOfLast { it != null }
                if (s.endLabel == null || i < 0) null else Triple(y(s.values[i]!!), s.endLabel, s.color)
            }
            val ys = ChartMath.spread(labs.map { it.first }, 13.dp.toPx())
            labs.forEachIndexed { i, (_, t, c) -> chartText(tm, t, right + 8.dp.toPx(), ys[i] + 4.dp.toPx(), c, 10.5.sp, FontWeight.SemiBold) }
        } else endLabel?.let { chartText(tm, it, last.x - 6.dp.toPx(), max(12.dp.toPx(), last.y - 8.dp.toPx()), endLabelColor, 11.sp, FontWeight.Bold, Anchor.End) }

        xLabels.forEachIndexed { i, t ->
            val n = xLabels.size
            val f = if (n == 1) 0f else i / (n - 1f)
            chartText(tm, t, left + f * (right - left), size.height - 2.dp.toPx(), C.dim, 10.sp,
                anchor = when (i) { 0 -> Anchor.Start; n - 1 -> Anchor.End; else -> Anchor.Middle })
        }
    }
}

// ---------------------------------------------------------------- Sparkline
/** Tiny trend line (lists, tiles). Default colour: light green when up over the period, light red when down. */
@Composable
fun Sparkline(values: List<Double>, modifier: Modifier = Modifier.size(64.dp, 26.dp), color: Color? = null,
              area: Boolean = false, endDot: Boolean = false, strokeWidth: Dp = 1.6.dp) {
    if (values.size < 2) return
    val col = color ?: if (values.last() >= values.first()) TierC.lightGreen else TierC.lightRed
    Canvas(modifier) {
        val (lo, hi) = ChartMath.range(values)
        val pad = 2.dp.toPx()
        val pts = values.indices.map { Offset(it / (values.size - 1f) * (size.width - if (endDot) 3.dp.toPx() else 0f), ChartMath.lerp(values[it], lo, hi, size.height - pad, pad)) }
        if (area) drawPath(smoothPath(pts).apply { lineTo(pts.last().x, size.height); lineTo(0f, size.height); close() },
            Brush.verticalGradient(listOf(col.copy(alpha = 0.25f), col.copy(alpha = 0f)), startY = pts.minOf { it.y }, endY = size.height))
        val p = Path().apply { pts.forEachIndexed { i, o -> if (i == 0) moveTo(o.x, o.y) else lineTo(o.x, o.y) } }
        drawPath(if (area) smoothPath(pts) else p, col, style = Stroke(strokeWidth.toPx(), cap = StrokeCap.Round))
        if (endDot) drawCircle(col, 2.8.dp.toPx(), pts.last())
    }
}

// ---------------------------------------------------------------- Bars
/**
 * Rounded vertical bars (ROCE by year, growth by year, run minutes). Last bar full colour, earlier ones dimmed when
 * [highlightLast]. [valueFmt] prints values above bars (last bold white); [labels] go underneath. [base] sets the value at
 * the bottom of the plot (e.g. min × 0.8 to show change); default 0, or the lowest value when negatives exist.
 */
@Composable
fun Bars(values: List<Double>, modifier: Modifier = Modifier.fillMaxWidth().height(96.dp), labels: List<String> = emptyList(),
         valueFmt: ((Double) -> String)? = null, color: Color = C.teal, colors: List<Color>? = null, highlightLast: Boolean = true,
         dimAlpha: Float = 0.45f, base: Double? = null, barFrac: Float? = null) {
    if (values.isEmpty()) return
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val n = values.size; val bw = size.width / n; val fr = barFrac ?: if (n > 4) 0.6f else 0.36f
        val topPad = if (valueFmt != null) 18.dp.toPx() else 0f; val botPad = if (labels.isNotEmpty()) 16.dp.toPx() else 0f
        val lo = base ?: min(0.0, values.min()); val hi = max(values.max(), lo + 1e-9)
        val y0 = size.height - botPad; val y1 = topPad
        fun y(v: Double) = ChartMath.lerp(v, lo, hi, y0, y1, clamp = true)
        val zero = y(max(lo, 0.0).coerceAtMost(hi))
        values.forEachIndexed { i, v ->
            var top = min(y(v), zero); var bot = max(y(v), zero)
            if (bot - top < 3.dp.toPx()) { if (v >= 0) top = bot - 3.dp.toPx() else bot = top + 3.dp.toPx() }
            val w = bw * fr; val x = i * bw + (bw - w) / 2
            val c = colors?.getOrNull(i) ?: color
            drawRoundRect(c.copy(alpha = if (!highlightLast || i == n - 1) c.alpha else c.alpha * dimAlpha), Offset(x, top), Size(w, bot - top),
                CornerRadius(min(5.dp.toPx(), w / 2)))
            val cx = i * bw + bw / 2
            valueFmt?.let { f -> chartText(tm, f(v), cx, (if (v >= 0) top else bot + 12.dp.toPx()) - 4.dp.toPx(), if (i == n - 1) C.white else C.dim, 11.sp,
                if (i == n - 1) FontWeight.Bold else FontWeight.Normal, Anchor.Middle) }
            labels.getOrNull(i)?.let { chartText(tm, it, cx, size.height - 2.dp.toPx(), C.dim, 10.sp, anchor = Anchor.Middle) }
        }
    }
}

// ---------------------------------------------------------------- BarsWithLine
/**
 * Revenue bars with a margin line on its own scale (Quality: 8 quarters). The line's first value is labelled under its
 * first point, the last at the right ([lineEndLabel], e.g. "margin 35.4%"); [lastBarLabel] (e.g. "₹630 cr") sits above the
 * last bar. [legend] (name, colour) pairs are drawn above the chart when given.
 */
@Composable
fun BarsWithLine(bars: List<Double>, line: List<Double>, labels: List<String>, modifier: Modifier = Modifier.fillMaxWidth().height(150.dp),
                 barColor: Color = C.teal, lineColor: Color = TierC.yellow, lineFmt: (Double) -> String = { "${skFx(it, 1)}%" },
                 lineEndLabel: String? = line.lastOrNull()?.let(lineFmt), lastBarLabel: String? = null,
                 legend: List<Pair<String, Color>>? = null) {
    if (bars.isEmpty()) return
    val tm = rememberTextMeasurer()
    Column {
        legend?.let { Legend(it, Modifier.padding(bottom = 6.dp)) }
        Canvas(modifier) {
            val n = bars.size; val bw = size.width / n; val bmax = bars.max().takeIf { it > 0 } ?: 1.0
            val H = size.height; val barTop = 70.dp.toPx()
            bars.forEachIndexed { i, v ->
                val h = (v / bmax * (H - barTop)).toFloat().coerceAtLeast(2.dp.toPx())
                drawRoundRect(barColor.copy(alpha = if (i == n - 1) 1f else 0.45f), Offset(i * bw + bw * 0.18f, H - 16.dp.toPx() - h), Size(bw * 0.64f, h),
                    CornerRadius(5.dp.toPx()))
                labels.getOrNull(i)?.let { chartText(tm, it, i * bw + bw / 2, H - 2.dp.toPx(), C.dim, 9.sp, anchor = Anchor.Middle) }
            }
            if (line.size == n && n >= 1) {
                val (lo, hi) = ChartMath.range(line)
                val pts = line.indices.map { Offset(it * bw + bw / 2, ChartMath.lerp(line[it], lo, hi, 46.dp.toPx(), 16.dp.toPx())) }
                if (n >= 2) drawPath(smoothPath(pts), lineColor, style = Stroke(2.2.dp.toPx(), cap = StrokeCap.Round))
                drawCircle(lineColor, 3.5.dp.toPx(), pts.last())
                if (n >= 2) chartText(tm, lineFmt(line.first()), pts.first().x, pts.first().y + 15.dp.toPx(), lineColor, 10.sp, anchor = Anchor.Middle)
                lineEndLabel?.let { chartText(tm, it, size.width - 2.dp.toPx(), pts.last().y - 8.dp.toPx(), lineColor, 11.sp, FontWeight.Bold, Anchor.End) }
            }
            lastBarLabel?.let {
                val h = (bars.last() / bmax * (H - barTop)).toFloat()
                chartText(tm, it, size.width - 2.dp.toPx(), H - 20.dp.toPx() - h, C.white, 11.sp, FontWeight.Bold, Anchor.End)
            }
        }
    }
}

// ---------------------------------------------------------------- DivergingBars
/** One row of [DivergingBars]. value null = no data (dashed placeholder, "–"). [group] starts a new labelled group (e.g. "1 month"). */
data class DivRow(val label: String, val value: Double?, val color: Color, val group: String? = null, val hollow: Boolean = false,
                  val valueText: String? = null)

/**
 * Bars left/right of a zero line with a label column and a right-aligned value column (returns vs index, industry wind,
 * growth the price needs). A [DivRow.hollow] row draws an outline bar. [span] fixes the scale (else largest |value| + 5%).
 */
@Composable
fun DivergingBars(rows: List<DivRow>, modifier: Modifier = Modifier.fillMaxWidth(), span: Double? = null,
                  valueFmt: (Double) -> String = { skSgn(it) },
                  labelWidth: Dp = 104.dp, valueWidth: Dp = 56.dp, mutedColor: Color = TierC.grey) {
    val sp = span ?: ChartMath.divergingSpan(rows.map { it.value })
    Column(modifier) {
        rows.forEachIndexed { i, r ->
            if (r.group != null) T(r.group, 12.sp, C.dim, FontWeight.Medium, Modifier.padding(top = if (i > 0) 6.dp else 0.dp, bottom = 2.dp))
            Row(Modifier.fillMaxWidth().height(20.dp), verticalAlignment = Alignment.CenterVertically) {
                T(r.label, 11.5.sp, C.muted, modifier = Modifier.width(labelWidth), maxLines = 1)
                Canvas(Modifier.weight(1f).fillMaxHeight()) {
                    val cx = size.width / 2; val k = (size.width / 2 - 4.dp.toPx()) / sp.toFloat(); val bh = 12.dp.toPx(); val top = (size.height - bh) / 2
                    drawLine(TierC.grey, Offset(cx, 0f), Offset(cx, size.height), 1.dp.toPx())
                    val v = r.value
                    if (v == null) drawRoundRect(C.dim, Offset(cx - 24.dp.toPx(), top), Size(48.dp.toPx(), bh), CornerRadius(bh / 2),
                        style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 6f))))
                    else {
                        val w = max(abs(v.toFloat()) * k, 3.dp.toPx()); val x = if (v >= 0) cx else cx - w
                        if (r.hollow) drawRoundRect(r.color, Offset(x, top), Size(w, bh), CornerRadius(bh / 2), style = Stroke(1.5.dp.toPx()))
                        else drawRoundRect(r.color, Offset(x, top), Size(w, bh), CornerRadius(bh / 2))
                    }
                }
                T(r.valueText ?: r.value?.let(valueFmt) ?: "–", 11.5.sp,
                    if (r.value == null || r.color == mutedColor) C.dim else C.white, if (r.value == null) FontWeight.Normal else FontWeight.SemiBold,
                    Modifier.width(valueWidth), maxLines = 1, align = androidx.compose.ui.text.style.TextAlign.End)
            }
        }
    }
}

// ---------------------------------------------------------------- FillBar (feedback #83, option B)
/** Fill colour of a check by its status word: pass light green, partly yellow, miss light red, n/a grey. */
fun fillColor(status: String): Color = when (status) { "Pass" -> TierC.lightGreen; "Partly" -> TierC.yellow; "Miss" -> TierC.lightRed; else -> C.grey }

/** A scale number with its unit: "70%", "1.5×", "67th", "−2 pts". */
fun scaleNum(v: Double, unit: String): String {
    val d = if (abs(v - Math.round(v).toDouble()) < 1e-9) 0 else 1
    return when (unit) {
        "th" -> skOrd(Math.round(v).toInt())
        else -> skFx(v, d) + unit
    }
}

/**
 * Filled bar for a check: 8dp rounded track, filled from the scale start up to [value] in [color] (the check's status
 * colour), a 2dp white tick at the [pass] mark and under it a 12sp dim row: scale min, "pass x" at the tick, scale max.
 * Lower-is-better checks fill the same way (the colour carries the verdict).
 */
@Composable
fun FillBar(value: Double, lo: Double, hi: Double, pass: Double, color: Color, modifier: Modifier = Modifier.fillMaxWidth(),
            unit: String = "", labels: Boolean = true) {
    val span = if (hi > lo) hi - lo else 1.0
    val tick = ((pass - lo) / span).coerceIn(0.0, 1.0).toFloat()
    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(12.dp)) {
            val bh = 8.dp.toPx(); val top = (size.height - bh) / 2; val r = CornerRadius(bh / 2)
            drawRoundRect(C.line, Offset(0f, top), Size(size.width, bh), r)
            val f = ((value - lo) / span).coerceIn(0.0, 1.0).toFloat()
            if (f > 0f) drawRoundRect(color, Offset(0f, top), Size(max(size.width * f, bh), bh), r)
            val tx = (size.width * tick).coerceIn(1.dp.toPx(), size.width - 1.dp.toPx())
            drawRect(Color.White, Offset(tx - 1.dp.toPx(), 0f), Size(2.dp.toPx(), size.height))
        }
        // min left, "pass x" centred on the tick, max right; an end label that would touch the pass label is left out
        if (labels) Layout(content = {
            T(scaleNum(lo, unit), 12.sp, C.dim, maxLines = 1)
            T("pass ${scaleNum(pass, unit)}", 12.sp, C.dim, maxLines = 1)
            T(scaleNum(hi, unit), 12.sp, C.dim, maxLines = 1)
        }, modifier = Modifier.fillMaxWidth().padding(top = 3.dp)) { ms, c ->
            val w = c.maxWidth
            val ps = ms.map { it.measure(c.copy(minWidth = 0)) }
            val a = ps[0]; val p = ps[1]; val b = ps[2]
            val gap = 6.dp.roundToPx()
            val px = (w * tick - p.width / 2f).toInt().coerceIn(0, max(0, w - p.width))
            val showA = a.width + gap <= px
            val showB = px + p.width + gap <= w - b.width
            layout(w, ps.maxOf { it.height }) {
                if (showA) a.place(0, 0)
                p.place(px, 0)
                if (showB) b.place(w - b.width, 0)
            }
        }
    }
}

// ---------------------------------------------------------------- RangeBar
/** A marker on [RangeBar]: value, label, colour, label above (true) or below the track. */
data class RangeMark(val value: Double, val label: String, val color: Color, val above: Boolean = false)

/** Low–high track with markers (52-week range: price, 50/200-day; analyst target range; valuation vs peers). */
@Composable
fun RangeBar(lo: Double, hi: Double, marks: List<RangeMark>, modifier: Modifier = Modifier.fillMaxWidth().height(46.dp), band: HBand? = null) {
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val pad = 10.dp.toPx(); val ty = size.height / 2
        fun X(v: Double) = ChartMath.lerp(v, lo, hi, pad, size.width - pad, clamp = true)
        drawRoundRect(TRACK, Offset(pad, ty - 3.dp.toPx()), Size(size.width - 2 * pad, 6.dp.toPx()), CornerRadius(3.dp.toPx()))
        band?.let { drawRoundRect(it.color.copy(alpha = 0.45f), Offset(X(it.lo), ty - 5.dp.toPx()), Size(X(it.hi) - X(it.lo), 10.dp.toPx()), CornerRadius(5.dp.toPx())) }
        marks.forEach { m ->
            val x = X(m.value)
            drawCircle(C.card, 8.5.dp.toPx(), Offset(x, ty)); drawCircle(m.color, 6.dp.toPx(), Offset(x, ty))
            val anchor = when { x < 50.dp.toPx() -> Anchor.Start; x > size.width - 50.dp.toPx() -> Anchor.End; else -> Anchor.Middle }
            val lx = when (anchor) { Anchor.Start -> max(0f, x - 6.dp.toPx()); Anchor.End -> min(size.width, x + 6.dp.toPx()); else -> x }
            chartText(tm, m.label, lx, if (m.above) ty - 12.dp.toPx() else ty + 20.dp.toPx(), m.color, 10.5.sp, FontWeight.SemiBold, anchor)
        }
    }
}

// ---------------------------------------------------------------- Gauge
/** Zone of a [Gauge] up to (exclusive) [upTo] on 0..100. */
data class GaugeZone(val upTo: Double, val color: Color, val name: String = "")
/** Market mood zones (Market screen and Home strip). */
val MOOD_ZONES = listOf(GaugeZone(25.0, TierC.red, "Extreme fear"), GaugeZone(45.0, TierC.lightRed, "Fear"), GaugeZone(55.0, TierC.yellow, "Neutral"),
    GaugeZone(75.0, TierC.lightGreen, "Greed"), GaugeZone(100.0, TierC.darkGreen, "Extreme greed"))
fun zoneColor(score: Double, zones: List<GaugeZone> = MOOD_ZONES): Color = zones[ChartMath.zoneOf(score, zones.map { it.upTo })].color

/**
 * Semicircle with coloured zones (the active one full colour, others faded), a white knob at [score] and, unless [mini],
 * the score and [label] (zone name, in its colour) in the centre. Mini = 36×22 dp strip icon.
 */
@Composable
fun Gauge(score: Int, modifier: Modifier = Modifier.size(220.dp, 124.dp), zones: List<GaugeZone> = MOOD_ZONES, label: String? = null,
          labelColor: Color? = null, mini: Boolean = false, stroke: Dp = if (mini) 5.dp else 16.dp) {
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val sw = stroke.toPx(); val cx = size.width / 2; val cy = size.height - (if (mini) 4 else 12).dp.toPx()
        val r = min(cy - sw / 2 - 2.dp.toPx(), cx - sw / 2)
        val active = ChartMath.zoneOf(score.toDouble(), zones.map { it.upTo })
        var from = 0.0
        zones.forEachIndexed { i, z ->
            val gap = if (mini) 1.5f else 2.2f
            val a = ChartMath.gaugeStart(from) + (if (from > 0) gap / 2 else 0f); val b = ChartMath.gaugeStart(z.upTo) - (if (z.upTo < 100) gap / 2 else 0f)
            drawArc(z.color.copy(alpha = if (i == active) 1f else 0.32f), a, b - a, false, Offset(cx - r, cy - r), Size(2 * r, 2 * r), style = Stroke(sw))
            from = z.upTo
        }
        val an = PI * (1 - score.coerceIn(0, 100) / 100.0)
        val k = Offset(cx + (r * cos(an)).toFloat(), cy - (r * sin(an)).toFloat())
        val kr = if (mini) sw / 2 + 0.5.dp.toPx() else sw / 2 + 3.dp.toPx()
        drawCircle(KNOB_RING, kr + 2.dp.toPx(), k); drawCircle(Color.White, kr, k)
        if (!mini) {
            chartText(tm, "$score", cx, cy - 22.dp.toPx(), C.white, 40.sp, FontWeight.ExtraBold, Anchor.Middle)
            (label ?: zones.getOrNull(active)?.name)?.let { chartText(tm, it, cx, cy, labelColor ?: zones[active].color, 16.sp, FontWeight.Bold, Anchor.Middle) }
        }
    }
}

/** Simple progress semicircle with the value and a small label in the middle (RS percentile on Momentum). */
@Composable
fun ArcGauge(value: Int, label: String, modifier: Modifier = Modifier.size(110.dp, 62.dp), color: Color = C.teal, max: Int = 100) {
    val tm = rememberTextMeasurer()
    Canvas(modifier) {
        val sw = 9.dp.toPx(); val cx = size.width / 2; val cy = 48.dp.toPx().coerceAtMost(size.height - 14.dp.toPx())
        val r = min(40.dp.toPx(), cx - sw / 2)
        val tl = Offset(cx - r, cy - r); val sz = Size(2 * r, 2 * r)
        drawArc(TRACK, 180f, 180f, false, tl, sz, style = Stroke(sw, cap = StrokeCap.Round))
        drawArc(color, 180f, 180f * value.coerceIn(0, max) / max, false, tl, sz, style = Stroke(sw, cap = StrokeCap.Round))
        chartText(tm, "$value", cx, cy - 4.dp.toPx(), C.white, 20.sp, FontWeight.Bold, Anchor.Middle)
        chartText(tm, label, cx, cy + 12.dp.toPx(), C.dim, 10.sp, anchor = Anchor.Middle)
    }
}

// ---------------------------------------------------------------- SegmentedBar
/** One part of a [SegmentedBar]. */
data class Segment(val value: Double, val color: Color, val label: String = "")
enum class SegLegend { None, Chips, Below }

/**
 * Stacked parts as rounded segments (who owns it, decisions by count, research coverage, promises by status).
 * Legend: [SegLegend.Chips] = dot chips underneath; [SegLegend.Below] = each label in its colour under its segment.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SegmentedBar(parts: List<Segment>, modifier: Modifier = Modifier.fillMaxWidth(), height: Dp = 12.dp, gap: Dp = 2.dp,
                 legend: SegLegend = SegLegend.Chips) {
    val shown = parts.filter { it.value > 0 }
    if (shown.isEmpty()) return
    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(height)) {
            ChartMath.shares(shown.map { it.value }, size.width, gap.toPx()).forEachIndexed { i, (x, w) ->
                drawRoundRect(shown[i].color, Offset(x, 0f), Size(max(w, 2.dp.toPx()), size.height), CornerRadius(size.height / 2))
            }
        }
        when (legend) {
            SegLegend.Chips -> FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                shown.filter { it.label.isNotEmpty() }.forEach { DotChip(it.label, it.color) }
            }
            SegLegend.Below -> Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                shown.forEach { s -> Box(Modifier.weight(s.value.toFloat())) {
                    androidx.compose.material3.Text(s.label, color = s.color, fontSize = 11.sp, softWrap = false, maxLines = 1, overflow = TextOverflow.Visible)
                } }
            }
            SegLegend.None -> {}
        }
    }
}

// ---------------------------------------------------------------- Meter
enum class MeterStyle { Bar, Dot }

/**
 * [n] segments, the first [on] lit (conviction: Meter(3, 2); conviction checks: Meter(7, 5, style = Dot)).
 * [colors] colours each segment individually (e.g. seven level tiers) and overrides [color]/[on].
 */
@Composable
fun Meter(n: Int, on: Int, modifier: Modifier = Modifier, color: Color = TierC.yellow, off: Color = C.line,
          style: MeterStyle = MeterStyle.Bar, colors: List<Color>? = null, segment: Dp = if (style == MeterStyle.Dot) 10.dp else 9.dp) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(if (style == MeterStyle.Dot) 4.dp else 2.dp), verticalAlignment = Alignment.CenterVertically) {
        repeat(n) { i ->
            val c = colors?.getOrNull(i) ?: if (i < on) color else off
            if (style == MeterStyle.Dot) Box(Modifier.size(segment).clip(CircleShape).background(c))
            else Box(Modifier.size(segment, 5.dp).clip(RoundedCornerShape(2.dp)).background(c))
        }
    }
}

// ---------------------------------------------------------------- DotTimeline
/** One dated row of [DotTimeline]; [hollow] for expected / routine items; [today] marks the "Today" row (white ring). */
data class TimelineItem(val date: String, val title: String, val sub: String? = null, val color: Color = C.dim, val hollow: Boolean = false,
                        val today: Boolean = false)

/** Vertical timeline: coloured dots on a thin line, title and small line on the left, date on the right. */
@Composable
fun DotTimeline(items: List<TimelineItem>, modifier: Modifier = Modifier.fillMaxWidth(), ring: Color = C.card,
                onClick: ((Int) -> Unit)? = null) {
    Column(modifier) {
        items.forEachIndexed { i, it ->
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)
                .then(if (onClick != null) Modifier.pointerInput(i) { detectTapGestures { onClick(i) } } else Modifier)) {
                Canvas(Modifier.width(22.dp).fillMaxHeight()) {
                    val x = 6.dp.toPx(); val cy = 16.dp.toPx(); val line = C.line
                    if (i > 0) drawLine(line, Offset(x, 0f), Offset(x, cy), 2.dp.toPx())
                    if (i < items.lastIndex) drawLine(line, Offset(x, cy), Offset(x, size.height), 2.dp.toPx())
                    val c = if (it.today) C.white else it.color
                    drawCircle(ring, 9.dp.toPx(), Offset(x, cy))
                    if (it.hollow || it.today) { drawCircle(ring, 6.dp.toPx(), Offset(x, cy)); drawCircle(c, 5.dp.toPx(), Offset(x, cy), style = Stroke(2.dp.toPx())) }
                    else drawCircle(c, 6.dp.toPx(), Offset(x, cy))
                }
                Column(Modifier.weight(1f).padding(vertical = 7.dp)) {
                    T(it.title, 13.sp, weight = FontWeight.Medium, lineHeight = 17.sp)
                    it.sub?.let { s -> T(s, 11.sp, C.dim, modifier = Modifier.padding(top = 1.dp)) }
                }
                T(it.date, 12.sp, C.dim, modifier = Modifier.padding(start = 8.dp, top = 7.dp), maxLines = 1)
            }
        }
    }
}

// ---------------------------------------------------------------- DotStrip
/** One dot on a [DotStrip]. */
data class StripDot(val date: LocalDate, val color: Color)

/**
 * Dots over a date axis. [stack] true (Filings): dots sharing a date stack upward above a baseline, month names below,
 * optional shaded last-[window]-days box. [stack] false (rating history): dots on one line, same-day dots side by side.
 * [labels] replace the month names (date, text).
 */
@Composable
fun DotStrip(dots: List<StripDot>, start: LocalDate, end: LocalDate, modifier: Modifier = Modifier.fillMaxWidth().height(78.dp),
             stack: Boolean = true, window: Int? = null, windowLabel: String? = window?.let { "$it days" }, windowColor: Color = TierC.red,
             labels: List<Pair<LocalDate, String>>? = null, ring: Color = C.card) {
    val tm = rememberTextMeasurer()
    val mon = java.time.format.DateTimeFormatter.ofPattern("MMM", java.util.Locale.ENGLISH)
    Canvas(modifier) {
        val pad = 6.dp.toPx(); val H = size.height
        fun X(d: LocalDate) = pad + ChartMath.dayFrac(d, start, end) * (size.width - 2 * pad)
        val base = if (stack) H - 18.dp.toPx() else 16.dp.toPx()
        if (window != null) {
            val lx = X(end.minusDays(window.toLong()))
            drawRoundRect(windowColor.copy(alpha = 0.08f), Offset(lx, 0f), Size(X(end) - lx + pad, base), CornerRadius(4.dp.toPx()))
            windowLabel?.let { chartText(tm, it, lx + 3.dp.toPx(), 10.dp.toPx(), windowColor.copy(alpha = 0.9f), 9.sp) }
        }
        drawLine(C.line, Offset(if (stack) 0f else pad, base), Offset(size.width - if (stack) 0f else pad, base),
            (if (stack) 1 else 2).dp.toPx())
        val idx = ChartMath.stackIndex(dots.map { it.date })
        dots.forEachIndexed { i, d ->
            if (stack) drawCircle(d.color, 3.8.dp.toPx(), Offset(X(d.date), base - 8.dp.toPx() - idx[i] * 9.dp.toPx()))
            else { val c = Offset(X(d.date) + idx[i] * 9.dp.toPx(), base); drawCircle(ring, 7.dp.toPx(), c); drawCircle(d.color, 5.dp.toPx(), c) }
        }
        val labs = labels ?: ChartMath.months(start, end).map { it to it.format(mon) }
        labs.forEach { (d, t) ->
            val x = X(d)
            val a = if (labels == null) Anchor.Start else when { x < 30.dp.toPx() -> Anchor.Start; x > size.width - 30.dp.toPx() -> Anchor.End; else -> Anchor.Middle }
            chartText(tm, t, if (a == Anchor.Start && labels != null) 0f else if (a == Anchor.End) size.width else x, if (stack) H - 4.dp.toPx() else base + 20.dp.toPx(), C.dim, 9.5.sp, anchor = a)
        }
    }
}

// ---------------------------------------------------------------- RotationMap
/** One sector / industry on a [RotationMap]: RS ratio and momentum (100 = in line with the benchmark), quadrant name. */
data class RotPoint(val ratio: Double, val mom: Double, val q: String, val label: String? = null)
/** Quadrant colours: one palette for the full map (Market) and the mini map (Look.kt QUAD_COLORS); names kept for callers. */
val QUAD_FULL: Map<String, Color> get() = QUAD_COLORS
val QUAD_MINI: Map<String, Color> get() = QUAD_COLORS
private val QUADS = listOf("Improving", "Leading", "Lagging", "Weakening")  // top-left, top-right, bottom-left, bottom-right

/**
 * 2×2 relative-rotation map. Full (Market, ~330×236 dp): outlined quadrant boxes with name and count, small dots.
 * [mini] (stock Summary, ~128×104 dp): tinted quadrants with small caps names and big labelled dots (S, I).
 * [onQuadrant] makes the boxes tappable.
 */
@Composable
fun RotationMap(points: List<RotPoint>, modifier: Modifier = Modifier.fillMaxWidth().height(236.dp), mini: Boolean = false,
                colors: Map<String, Color> = if (mini) QUAD_MINI else QUAD_FULL, onQuadrant: ((String) -> Unit)? = null) {
    val tm = rememberTextMeasurer()
    val counts = points.groupingBy { it.q }.eachCount()
    Canvas(modifier.then(if (onQuadrant != null) Modifier.pointerInput(Unit) {
        detectTapGestures { o -> onQuadrant(QUADS[(if (o.y > size.height / 2) 2 else 0) + (if (o.x > size.width / 2) 1 else 0)]) }
    } else Modifier)) {
        val W = size.width; val H = size.height
        if (mini) {
            val cx = W / 2; val cy = H / 2
            QUADS.forEachIndexed { i, q ->
                val c = colors[q] ?: C.grey; val x = if (i % 2 == 1) cx else 0f; val y = if (i >= 2) cy else 0f
                drawRoundRect(c.copy(alpha = 0.13f), Offset(x + 1, y + 1), Size(cx - 2, cy - 2), CornerRadius(8.dp.toPx()))
                chartText(tm, q, if (i % 2 == 1) x + cx - 6.dp.toPx() else x + 6.dp.toPx(), if (i < 2) y + 12.dp.toPx() else y + cy - 6.dp.toPx(),
                    c, 8.5.sp, FontWeight.Bold, if (i % 2 == 1) Anchor.End else Anchor.Start)
            }
            val span = max(3.0, (points.maxOfOrNull { max(abs(it.ratio - 100), abs(it.mom - 100)) } ?: 0.0) * 1.3)
            val m = 11.dp.toPx()
            val pos = points.map { ChartMath.rotMini(it.ratio, it.mom, span, W, H, m) }.map { Offset(it.first, it.second) }.toMutableList()
            for (a in pos.indices) for (b in a + 1 until pos.size) {  // two dots on top of each other: move them apart vertically
                if ((pos[a] - pos[b]).getDistance() < 20.dp.toPx()) {
                    val mid = (pos[a].y + pos[b].y) / 2; val up = pos[a].y <= pos[b].y
                    pos[a] = pos[a].copy(y = mid + if (up) -10.dp.toPx() else 10.dp.toPx()); pos[b] = pos[b].copy(y = mid + if (up) 10.dp.toPx() else -10.dp.toPx())
                }
            }
            points.forEachIndexed { i, p ->
                drawCircle(C.card, 11.dp.toPx(), pos[i]); drawCircle(colors[p.q] ?: C.grey, 9.dp.toPx(), pos[i])
                p.label?.let { chartText(tm, it, pos[i].x, pos[i].y + 3.5.dp.toPx(), C.white, 10.sp, FontWeight.Bold, Anchor.Middle) }
            }
        } else {
            val gap = 6.dp.toPx(); val qw = (W - gap) / 2; val qh = (H - gap) / 2
            val dxm = points.maxOfOrNull { abs(it.ratio - 100) } ?: 1.0; val dym = points.maxOfOrNull { abs(it.mom - 100) } ?: 1.0
            QUADS.forEachIndexed { i, q ->
                val c = colors[q] ?: C.grey; val x = if (i % 2 == 1) qw + gap else 0f; val y = if (i >= 2) qh + gap else 0f
                drawRoundRect(c.copy(alpha = 0.10f), Offset(x, y), Size(qw, qh), CornerRadius(14.dp.toPx()))
                drawRoundRect(c.copy(alpha = 0.35f), Offset(x, y), Size(qw, qh), CornerRadius(14.dp.toPx()), style = Stroke(1.dp.toPx()))
            }
            points.forEach { p ->
                val (px, py) = ChartMath.rotFull(p.ratio, p.mom, dxm, dym, W / density, H / density, 6f)
                val o = Offset(px * density, py * density)
                if (p.label != null) { drawCircle(colors[p.q] ?: C.grey, 9.dp.toPx(), o); chartText(tm, p.label, o.x, o.y + 3.5.dp.toPx(), C.white, 10.sp, FontWeight.Bold, Anchor.Middle) }
                else drawCircle((colors[p.q] ?: C.grey).copy(alpha = 0.85f), 4.dp.toPx(), o)
            }
            QUADS.forEachIndexed { i, q ->
                val c = colors[q] ?: C.grey; val x = if (i % 2 == 1) qw + gap else 0f; val y = if (i >= 2) qh + gap else 0f
                val tx = if (i % 2 == 1) x + qw - 12.dp.toPx() else x + 12.dp.toPx(); val a = if (i % 2 == 1) Anchor.End else Anchor.Start
                val top = i < 2
                chartText(tm, q, tx, if (top) y + 20.dp.toPx() else y + qh - 34.dp.toPx(), c, 12.sp, FontWeight.SemiBold, a)
                chartText(tm, "${counts[q] ?: 0}", tx, if (top) y + 46.dp.toPx() else y + qh - 10.dp.toPx(), C.white, 24.sp, FontWeight.ExtraBold, a)
            }
        }
    }
}

// ---------------------------------------------------------------- TierScale
/** Five tier segments (1 dark green .. 5 red); the current [tier] full colour, others faded. 0 = none lit. */
@Composable
fun TierScale(tier: Int, modifier: Modifier = Modifier.fillMaxWidth(), height: Dp = 6.dp) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        (1..5).forEach { i -> Box(Modifier.weight(1f).height(height).clip(RoundedCornerShape(height / 2)).background(tierColor(i).copy(alpha = if (i == tier) 1f else 0.25f))) }
    }
}

// ---------------------------------------------------------------- previews (Android Studio only)
@Preview(widthDp = 360, backgroundColor = 0xFF121315, showBackground = true)
@Composable
private fun ChartsPreview() = NarrativTheme {
    Column(Modifier.background(C.card).padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        AreaLine(listOf(26.0, 25.1, 27.4, 29.9, 24.2, 22.0, 21.2, 23.5), cheapBelow = 22.8, cheapLabel = "cheap ≤ 22.8", expensiveAbove = 26.9,
            expensiveLabel = "expensive ≥ 26.9", median = 24.5, medianLabel = "median 24.5", today = 23.0, todayLabel = "23.0", xLabels = listOf("Dec '22", "Sep '26"))
        BarsWithLine(listOf(480.0, 490.0, 500.0, 510.0, 515.0, 560.0, 575.0, 630.0), listOf(32.9, 33.4, 34.8, 35.5, 35.1, 34.0, 35.0, 35.4),
            listOf("Dec", "Mar", "Jun", "Sep", "Dec", "Mar", "Jun", "Sep"), lastBarLabel = "₹630 cr", lineEndLabel = "margin 35.4%")
        Bars(listOf(21.5, 20.4, 19.2), labels = listOf("FY24", "FY25", "FY26"), valueFmt = { "${fmt(it, 1)}%" }, base = 15.0)
        DivergingBars(listOf(DivRow("CAPLIPOINT", -6.2, TierC.lightRed, "1 month"), DivRow("Nifty Pharma", 11.0, TierC.grey)))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            FillBar(68.0, 0.0, 100.0, 70.0, TierC.yellow, Modifier.width(120.dp), unit = "%"); Meter(3, 2); Meter(7, 5, color = TierC.lightGreen, style = MeterStyle.Dot)
            Gauge(37, Modifier.size(36.dp, 22.dp), mini = true); ArcGauge(53, "RS pct")
        }
        RangeBar(1495.0, 2990.0, listOf(RangeMark(1495.0, "₹1,495", C.grey), RangeMark(2198.0, "200-day", C.muted, true), RangeMark(2495.0, "50-day", TierC.yellow, true),
            RangeMark(2085.0, "now ₹2,085", C.white), RangeMark(2990.0, "₹2,990", C.grey)))
        Gauge(37, label = "Fear")
        SegmentedBar(listOf(Segment(69.6, TierC.darkGreen, "Promoter 69.6%"), Segment(3.1, C.muted, "Foreign 3.1%"), Segment(27.3, TierC.grey, "Public 27.3%")))
        TierScale(2)
        DotTimeline(listOf(TimelineItem("12 Nov", "Last results", "filed"), TimelineItem("20 Nov", "Today", today = true),
            TimelineItem("15 Feb 2028", "Thervoy oncology API unit not completed in CY27", "Kill switch", TierC.red)))
        val d0 = LocalDate.of(2026, 4, 1)
        DotStrip(listOf(StripDot(d0.plusDays(10), C.dim), StripDot(d0.plusDays(40), TierC.darkGreen), StripDot(d0.plusDays(40), C.dim)), d0, LocalDate.of(2026, 11, 20), window = 45)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            RotationMap(listOf(RotPoint(97.0, 98.5, "Lagging", "S"), RotPoint(98.0, 97.8, "Lagging", "I")), Modifier.size(128.dp, 104.dp), mini = true)
            Sparkline(listOf(1.0, 3.0, 2.0, 4.0, 3.5, 5.0))
        }
        RotationMap(listOf(RotPoint(102.0, 101.0, "Leading"), RotPoint(98.0, 101.5, "Improving"), RotPoint(97.0, 98.0, "Lagging"), RotPoint(101.0, 99.0, "Weakening")))
    }
}
