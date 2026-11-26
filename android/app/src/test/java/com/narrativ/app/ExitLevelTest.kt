package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** feedback #92 (exit level hit, still Buy) and #105 (52-week H / L closes on the chart). */
class ExitLevelTest {
    private val call = CallRec(symbol = "CAPLIPOINT.NS", kind = "verified", decision = "Buy", date = "2026-11-16", ended = "2026-11-20",
        endDecision = "Exit level ₹2,044.22 broken", stop = 2044.22, reentryAfter = "2026-12-07")

    @Test fun closedOnExitLevelStillBuy() {
        val (hit, still) = exitLevelLines(call, P("CAPLIPOINT.NS", dc = "Buy"))!!
        assertEquals("Closed · exit level ₹2,044.22 hit on 20 Nov", hit)
        assertEquals("Still rated Buy" to " · re-entry above ₹2,044.22 or after 7 Dec", still)
    }

    @Test fun noReentryDateAndNoLongerBuy() {
        val c = call.copy(reentryAfter = null)
        assertEquals(" · re-entry above ₹2,044.22", exitLevelLines(c, P("CAPLIPOINT.NS", dc = "Buy"))!!.second!!.second)
        assertNull(exitLevelLines(c, P("CAPLIPOINT.NS", dc = "Hold"))!!.second)
        assertNull(exitLevelLines(c, null)!!.second)
    }

    @Test fun candidateRowUsesCandidateFlag() {
        val c = call.copy(kind = "candidate")
        assertEquals("Still a Buy candidate", exitLevelLines(c, P("CAPLIPOINT.NS", dc = "Hold", cand = "Buy"))!!.second!!.first)
    }

    @Test fun otherEndingsHaveNoLines() {
        assertNull(exitLevelLines(call.copy(endDecision = "Hold"), P("CAPLIPOINT.NS", dc = "Buy")))
        assertNull(exitLevelLines(call.copy(ended = null), P("CAPLIPOINT.NS", dc = "Buy")))
    }

    @Test fun planAmberLine() {
        assertEquals("Exit level ₹2,044.22 hit on 20 Nov: no new call until a close back above ₹2,044.22 or after 7 Dec",
            exitHitLine(ExitHit(2044.22, "2026-11-20", "2026-12-07", "verified")))
        assertEquals("Exit level ₹2,044.22 hit on 20 Nov: no new call until a close back above ₹2,044.22 or 10 trading days",
            exitHitLine(ExitHit(2044.22, "2026-11-20", null, "verified")))
        assertNull(exitHitLine(null))
        val d = json.decodeFromString<Detail>("""{"exit_hit":{"stop":257.38,"date":"2026-11-18","reentry_after":"2026-12-03","kind":"verified"}}""")
        assertEquals(257.38, d.exitHit!!.stop!!, 0.0)
        assertNull(json.decodeFromString<Detail>("{}").exitHit)
        val cf = json.decodeFromString<CallsFile>("""{"calls":[{"symbol":"SATIN.NS","kind":"verified","reentry_after":"2026-12-03"},{"symbol":"X"}]}""")
        assertEquals("2026-12-03", cf.calls[0].reentryAfter); assertNull(cf.calls[1].reentryAfter)
    }

    @Test fun hiLoMarksOnlyInsideTheWindow() {
        // 300 closes: low at 20 (outside the last 250), low inside the window at 100, high at 280
        val all = List(300) { i -> when (i) { 20 -> 1.0; 100 -> 5.0; 280 -> 50.0; else -> 10.0 } }
        val year = hiLoMarks(all, 260)
        assertEquals(listOf(PointMark(100 - 40, "L", false), PointMark(280 - 40, "H", true)), year)
        val month = hiLoMarks(all, 22)  // only the high (20 sessions ago) is inside the last 22 closes
        assertEquals(listOf(PointMark(280 - 278, "H", true)), month)
        assertTrue(hiLoMarks(List(30) { 3.0 }, 22).isEmpty())
    }
}
