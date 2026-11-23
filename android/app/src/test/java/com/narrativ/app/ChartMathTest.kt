package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/** Scaling and layout maths behind Charts.kt, plus the new routes and data fields of the redesign. */
class ChartMathTest {
    private val eps = 1e-4f

    @Test fun lerpMapsAndClamps() {
        assertEquals(0f, ChartMath.lerp(10.0, 10.0, 20.0, 0f, 100f), eps)
        assertEquals(50f, ChartMath.lerp(15.0, 10.0, 20.0, 0f, 100f), eps)
        assertEquals(0f, ChartMath.lerp(30.0, 10.0, 20.0, 100f, 0f, clamp = true), eps)  // clamped to hi -> b
        assertEquals(50f, ChartMath.lerp(5.0, 3.0, 3.0, 0f, 100f), eps)  // flat range: middle
        assertEquals(120f, ChartMath.lerp(22.0, 10.0, 20.0, 0f, 100f), eps)  // no clamp: extrapolates
    }

    @Test fun rangePadsAndHandlesFlat() {
        assertEquals(0.0 to 10.0, ChartMath.range(listOf(0.0, null, 10.0)))
        val (lo, hi) = ChartMath.range(listOf(10.0, 20.0), pad = 0.1)
        assertEquals(9.0, lo, 1e-9); assertEquals(21.0, hi, 1e-9)
        assertEquals(4.0 to 6.0, ChartMath.range(listOf(5.0, 5.0)))
        assertEquals(0.0 to 1.0, ChartMath.range(emptyList()))
    }

    @Test fun smoothEndsOnEachPoint() {
        val s = ChartMath.smooth(listOf(0f, 10f, 20f), listOf(0f, 10f, 0f))
        assertEquals(2, s.size)
        assertEquals(10f, s[0][4], eps); assertEquals(10f, s[0][5], eps)
        assertEquals(20f, s[1][4], eps); assertEquals(0f, s[1][5], eps)
        assertEquals(1.25f, s[0][0], eps)  // first control: p1 + (p2 - p0) / 8 with p0 = p1
        assertTrue(ChartMath.smooth(listOf(1f), listOf(1f)).isEmpty())
    }

    @Test fun gaugeAndZones() {
        assertEquals(180f, ChartMath.gaugeStart(0.0), eps)
        assertEquals(270f, ChartMath.gaugeStart(50.0), eps)
        assertEquals(360f, ChartMath.gaugeStart(140.0), eps)
        val up = listOf(25.0, 45.0, 55.0, 75.0, 100.0)
        assertEquals(1, ChartMath.zoneOf(37.0, up))  // Fear
        assertEquals(0, ChartMath.zoneOf(0.0, up)); assertEquals(2, ChartMath.zoneOf(45.0, up)); assertEquals(4, ChartMath.zoneOf(100.0, up))
    }

    @Test fun quartilesAsMockup() {
        val q = ChartMath.quartiles(listOf(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0))!!
        assertEquals(3.0, q.first, 1e-9); assertEquals(4.5, q.second, 1e-9); assertEquals(7.0, q.third, 1e-9)
    }

    @Test fun spreadKeepsGap() {
        val ys = ChartMath.spread(listOf(50f, 52f, 10f), 13f)
        assertEquals(10f, ys[2], eps); assertEquals(50f, ys[0], eps); assertEquals(63f, ys[1], eps)
    }

    @Test fun sharesFillWidthWithGaps() {
        val s = ChartMath.shares(listOf(6.0, 1.0, 0.0, 1.0), 104f, 2f)
        assertEquals(0f, s[2].second, eps)
        assertEquals(75f, s[0].second, eps); assertEquals(12.5f, s[1].second, eps)
        assertEquals(104f, s[3].first + s[3].second, eps)
    }

    @Test fun datesAndStacks() {
        val a = LocalDate.of(2026, 4, 1); val b = LocalDate.of(2026, 5, 1)
        assertEquals(0.5f, ChartMath.dayFrac(LocalDate.of(2026, 4, 16), a, b), eps)
        assertEquals(listOf(0, 1, 0, 2), ChartMath.stackIndex(listOf("x", "x", "y", "x")))
        assertEquals(listOf(LocalDate.of(2026, 5, 1), LocalDate.of(2026, 6, 1)), ChartMath.months(LocalDate.of(2026, 4, 15), LocalDate.of(2026, 6, 20)))
        assertEquals(1.05 * 8, ChartMath.divergingSpan(listOf(-8.0, null, 3.0)), 1e-9)
    }

    @Test fun rotationStaysInQuadrant() {
        val (x, y) = ChartMath.rotMini(99.9, 100.1, 3.0, 128f, 104f, 11f)  // barely improving: left half, top half
        assertTrue(x <= 64f - 11f); assertTrue(y <= 52f - 11f)
        val (fx, fy) = ChartMath.rotFull(104.0, 96.0, 4.0, 4.0, 330f, 236f)  // weakening extreme: right, bottom
        assertTrue(fx > 165f); assertTrue(fy > 118f)
    }

    @Test fun statusWords() {
        assertEquals(listOf("Pass", "Partly", "Miss", "n/a"), listOf(2, 1, 0, null).map { statusOf(it) })
    }

    @Test fun newRoutesSurviveRestore() {
        val st = listOf(Screen.Home, Screen.Market, Screen.Settings, Screen.Advanced, Screen.TrackRecord)
        assertEquals(st, decodeStack(encodeStack(st)))
    }

    @Test fun convictionAndCvDecode() {
        val d = json.decodeFromString<Detail>("""{"conviction":{"level":"Medium","met":5,"of":7,"why":"5 of 7 checks met","rule":"v1","date":"2026-11-20",
            "checks":[{"id":"C1","n":"Dated trigger","ok":true,"v":"2 independent"},{"id":"C3","n":"Entry setup","ok":false,"v":"No setup","extra":1}]},
            "decision":{"d":"Not rated","missing":["Not researched yet"]},"stock":{"events":[{"sev":"watch","type":"Court / tax order","text":"x"}]}}""")
        assertEquals("Medium", d.conviction?.level); assertEquals(2, d.conviction?.checks?.size); assertEquals(false, d.conviction?.checks?.get(1)?.ok)
        assertEquals("Not researched yet", d.decision?.missing?.first()); assertEquals("watch", d.stock.events.first().sev)
        val p = json.decodeFromString<P>("""{"s":"X.NS","cv":"High","sc":[100,90,null,80,40,55,20]}""")
        assertEquals("High", p.cv); assertEquals(55, p.sc[5])
    }
}
