package com.narrativ.app

import java.time.LocalDate
import java.time.temporal.ChronoUnit
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sign
import kotlin.math.sqrt

/** Pure scaling and layout maths for the charts in Charts.kt (no Compose types, unit-tested in ChartMathTest). */
object ChartMath {
    /** Map v in [lo, hi] linearly onto [a, b]; a flat range maps to the middle. */
    fun lerp(v: Double, lo: Double, hi: Double, a: Float, b: Float, clamp: Boolean = false): Float {
        if (hi == lo) return (a + b) / 2
        val f = ((if (clamp) v.coerceIn(min(lo, hi), max(lo, hi)) else v) - lo) / (hi - lo)
        return (a + (b - a) * f).toFloat()
    }

    /** Min and max of the non-null values, widened by [pad] (fraction of the span) on each side; a flat series gets ±1. */
    fun range(values: List<Double?>, pad: Double = 0.0): Pair<Double, Double> {
        val v = values.filterNotNull().filter { it.isFinite() }
        if (v.isEmpty()) return 0.0 to 1.0
        var lo = v.min(); var hi = v.max()
        if (hi == lo) { lo -= 1.0; hi += 1.0 }
        val p = (hi - lo) * pad
        return (lo - p) to (hi + p)
    }

    /**
     * Smooth curve through points (Catmull-Rom style, as the mockups' SVG): one FloatArray per segment,
     * [c1x, c1y, c2x, c2y, x, y] for a cubicTo from the previous point. [k] 1/8 is gentle, 1/6 rounder.
     */
    fun smooth(xs: List<Float>, ys: List<Float>, k: Float = 1f / 8f): List<FloatArray> {
        val n = min(xs.size, ys.size)
        if (n < 2) return emptyList()
        return (0 until n - 1).map { i ->
            val p0 = if (i > 0) i - 1 else i; val p3 = if (i + 2 < n) i + 2 else i + 1
            floatArrayOf(
                xs[i] + (xs[i + 1] - xs[p0]) * k, ys[i] + (ys[i + 1] - ys[p0]) * k,
                xs[i + 1] - (xs[p3] - xs[i]) * k, ys[i + 1] - (ys[p3] - ys[i]) * k,
                xs[i + 1], ys[i + 1],
            )
        }
    }

    /** Gauge: score 0..100 to a sweep from the left end (0) to the right end (100); degrees in Compose drawArc terms. */
    fun gaugeStart(score: Double): Float = (180.0 + 180.0 * score.coerceIn(0.0, 100.0) / 100.0).toFloat()

    /** Index of the zone [score] falls in, given ascending upper bounds (e.g. 25, 45, 55, 75, 100). */
    fun zoneOf(score: Double, uppers: List<Double>): Int = uppers.indexOfFirst { score < it }.let { if (it < 0) uppers.lastIndex else it }

    /** Own-history band as the Valuation mockup: 25th percentile, median, 75th percentile. */
    fun quartiles(values: List<Double>): Triple<Double, Double, Double>? {
        if (values.isEmpty()) return null
        val s = values.sorted(); val n = s.size
        return Triple(s[(n * 0.25).toInt()], (s[n / 2] + s[(n - 1) / 2]) / 2, s[min(n - 1, (n * 0.75).toInt())])
    }

    /** Push label positions apart (keeps their order by position) so none are closer than [gap]. */
    fun spread(ys: List<Float>, gap: Float): List<Float> {
        val order = ys.indices.sortedBy { ys[it] }
        val out = ys.toMutableList()
        for (j in 1 until order.size) {
            val prev = out[order[j - 1]]; val i = order[j]
            if (out[i] < prev + gap) out[i] = prev + gap
        }
        return out
    }

    /** Stacked share of each part across [width] with [gap] between parts: (x, w) per part; zero parts get w 0. */
    fun shares(values: List<Double>, width: Float, gap: Float): List<Pair<Float, Float>> {
        val tot = values.sumOf { max(it, 0.0) }
        if (tot <= 0) return values.map { 0f to 0f }
        val nz = values.count { it > 0 }
        val free = width - gap * (nz - 1).coerceAtLeast(0)
        var x = 0f
        return values.map { v ->
            if (v <= 0) x to 0f else {
                val w = (v / tot * free).toFloat(); val r = x to w; x += w + gap; r
            }
        }
    }

    /** Span for bars around zero: the largest absolute value, 5% wider. */
    fun divergingSpan(values: List<Double?>): Double = (values.filterNotNull().maxOfOrNull { abs(it) } ?: 1.0).let { if (it == 0.0) 1.0 else it * 1.05 }

    /** Day offset of [d] in [start, end] as 0..1. */
    fun dayFrac(d: LocalDate, start: LocalDate, end: LocalDate): Float {
        val span = ChronoUnit.DAYS.between(start, end).coerceAtLeast(1)
        return (ChronoUnit.DAYS.between(start, d).toFloat() / span).coerceIn(0f, 1f)
    }

    /** Position of each item among items with the same key, in input order (stacks dots that share a date). */
    fun <K> stackIndex(keys: List<K>): List<Int> {
        val seen = HashMap<K, Int>()
        return keys.map { k -> val n = seen[k] ?: 0; seen[k] = n + 1; n }
    }

    /** First day of each month from [start] to [end] (labels for a month strip). */
    fun months(start: LocalDate, end: LocalDate): List<LocalDate> {
        var m = start.withDayOfMonth(1); val out = mutableListOf<LocalDate>()
        if (m.isBefore(start)) m = m.plusMonths(1)
        while (!m.isAfter(end)) { out += m; m = m.plusMonths(1) }
        return out
    }

    /**
     * Full rotation map (Market): dot position in a w×h box with a [gap] between quadrants. ratio/mom are
     * centred at 100; square-root scaling spreads the crowd near the centre. Returns (x, y).
     */
    fun rotFull(ratio: Double, mom: Double, dxMax: Double, dyMax: Double, w: Float, h: Float, gap: Float = 6f): Pair<Float, Float> {
        val qw = (w - gap) / 2; val qh = (h - gap) / 2; val cx = qw + gap / 2; val cy = qh + gap / 2
        val dx = (ratio - 100) / (if (dxMax == 0.0) 1.0 else dxMax); val dy = (mom - 100) / (if (dyMax == 0.0) 1.0 else dyMax)
        val px = cx + (sign(dx) * sqrt(abs(dx)) * (qw - 16)).toFloat()
        val py = cy - (sign(dy) * (8 + sqrt(abs(dy)) * (qh - 66).coerceAtLeast(8f))).toFloat()
        return px.coerceIn(8f, w - 8f) to py.coerceIn(8f, h - 8f)
    }

    /** Mini rotation map (stock Summary): linear around the centre, each dot kept inside its own quadrant by [margin]. */
    fun rotMini(ratio: Double, mom: Double, span: Double, w: Float, h: Float, margin: Float): Pair<Float, Float> {
        val cx = w / 2; val cy = h / 2; val s = if (span == 0.0) 1.0 else span
        var x = cx + ((ratio - 100) / s * (cx - margin - 1)).toFloat()
        var y = cy - ((mom - 100) / s * (cy - margin - 1)).toFloat()
        x = if (ratio < 100) min(x, cx - margin) else max(x, cx + margin)
        y = if (mom < 100) max(y, cy + margin) else min(y, cy - margin)
        return x.coerceIn(margin, w - margin) to y.coerceIn(margin, h - margin)
    }
}
