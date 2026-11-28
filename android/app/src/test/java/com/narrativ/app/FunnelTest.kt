package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Today's Knockout Funnel: stage numbers, the sentences between them, chip order and the removal reasons. */
class FunnelTest {
    private fun buy(s: String, cv: String?, rk: Int?, verified: Boolean = true) =
        P(s, c = s, dc = "Buy", vf = "pass", ic = if (verified) null else 1, cv = cv, rk = rk)

    private val picks = listOf(
        buy("SATIN", "Medium", 1), buy("TALBRO", "High", 37), buy("MPS", "High", 1146), buy("EPL", "Medium", 12),
        buy("WINDLAS", "Low", 1424), buy("PEND", "High", 2, verified = false),
        P("A", out = Out(1, "interest cover 1.0x; net debt 7.0x EBITDA")),
        P("B", out = Out(1, "interest cover -0.4x; net debt 3.2x EBITDA")),
        P("C", out = Out(1, "2 loss quarters of last 4")),
        P("D", out = Out(3, "overvalued on all 3 anchors (P/B)")),
    )
    private val pf = PicksFile(v = 2, picks = picks, funnel = FunnelV2(listed = 5110, companies = 2368,
        levels = listOf(2152, 1763, 1698, 1598, 1598), researched = 265, decisions = mapOf("Buy" to 24, "Hold" to 1078)))

    @Test fun stagesAndSentencesFollowThePublishedCounts() {
        val s = koStages(pf)
        assertEquals(listOf(5110, 2368, 2152, 1763, 1698, 1598, 265, 24, 5), s.map { it.value })
        assertNull(s[0].gapPost)
        assertEquals(2742, s[1].gapN)
        assertEquals(216, s[2].gapN)
        assertEquals(1333, s[6].gapN)
        assertTrue(s[6].gapWait)
        assertEquals(241, s[7].gapN)
        assertEquals(19, s[8].gapN)
        assertEquals(" Buys with full in-depth research still pending", s[8].gapPost)
    }

    @Test fun missingDataDropsTheStageAndTheSentencesBesideIt() {
        val s = koStages(pf.copy(funnel = pf.funnel.copy(companies = null, levels = listOf(2152))))
        assertEquals(listOf("NSE and BSE universe", "Stability", "Narrativ.ai primary research", "Qualified Buy", "Verified Buy"), s.map { it.name })
        assertNull(s[1].gapPost)
        assertNull(s[2].gapPost)
        val none = koStages(pf.copy(funnel = pf.funnel.copy(researched = 24)))
        assertNull(none.first { it.name == "Qualified Buy" }.gapPost)
    }

    @Test fun verifiedBuysHighestConvictionFirstThenByRank() {
        assertEquals(listOf("TALBRO", "MPS", "SATIN", "EPL", "WINDLAS"), koVerified(pf).map { it.s })
    }

    @Test fun reasonsGroupWithoutTheirNumbers() {
        assertEquals("Weak interest cover, heavy net debt against EBITDA", plainReason("interest cover -0.4x; net debt 3.2x EBITDA"))
        assertEquals("Low return on capital, weak cash backing", plainReason("low return on capital, weak cash backing"))
        assertEquals("Promoter stake cut", plainReason("promoter stake down 5.9 pts in 12 months"))
        assertEquals("Overvalued on every measure (EV to mid-cycle EBITDA)", plainReason("overvalued on all 3 anchors (EV / mid-cycle EBITDA)"))
        assertEquals(listOf("Weak interest cover, heavy net debt against EBITDA" to 2, "Losses in recent quarters" to 1), koReasons(pf, 1))
        assertEquals(listOf("Overvalued on every measure (price to book)" to 1), koReasons(pf, 3))
        assertTrue(koReasons(pf, 4).isEmpty())
    }

    @Test fun tipPresetOpensEveryVerifiedBuy() {
        val f = presetFilt("vb", pf)
        assertEquals(5, pf.picks.count { f.match(it) })
    }
}
