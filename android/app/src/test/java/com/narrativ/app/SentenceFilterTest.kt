package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The filter sentence (owner, 28 Nov 2026): default "verified Buys with high conviction, priced near the entry price". */
class SentenceFilterTest {
    private val names: (Int) -> List<String> = { i -> DEFAULT_TIERS[LEVELS[i]] ?: emptyList() }
    private val mps = P("MPSLTD.NS", dc = "Buy", vf = "pass", cv = "High", p = 2097.5, ez = listOf(2050.1, 2152.61))
    private val talbro = P("TALBROAUTO.NS", dc = "Buy", vf = "pass", cv = "High", p = 379.15, ez = listOf(345.8, 363.09))
    private val suraksha = P("SURAKSHA.NS", dc = "Buy", vf = "pass", cv = "Low", p = 311.3, ez = listOf(295.0, 309.75))
    private val pending = P("THEJO.NS", dc = "Buy", vf = "pass", ic = 1, cv = "High", p = 1993.7, ez = listOf(1865.0, 1958.25))
    private val noZone = P("MACPOWER.NS", dc = "Buy", vf = "pass", cv = "High", p = 2082.2)

    @Test fun defaultSentenceKeepsVerifiedBuysOfHighOrMediumConviction() {
        assertTrue(DEFAULT_SENTENCE.match(mps))
        assertTrue(DEFAULT_SENTENCE.match(talbro))
        assertTrue(DEFAULT_SENTENCE.match(noZone))
        assertFalse(DEFAULT_SENTENCE.match(suraksha))
        assertFalse(DEFAULT_SENTENCE.match(pending))
        assertTrue(DEFAULT_SENTENCE.match(P("ASAHISONG.NS", dc = "Buy", vf = "pass", cv = "Medium", p = 358.85)))
    }

    @Test fun sellsBlankKeepsSellsAndStrongSells() {
        assertTrue(callMatch(P("A.NS", dc = "Sell"), "Sells"))
        assertTrue(callMatch(P("B.NS", dc = "Strong Sell"), "Sells"))
        assertFalse(callMatch(P("C.NS", dc = "Hold"), "Sells"))
    }

    @Test fun nearIsInTheZoneOrUpToThreePercentAbove() {
        assertTrue(zoneMatch(suraksha, "Near"))
        assertFalse(zoneMatch(suraksha, "In zone"))
        assertFalse(zoneMatch(talbro, "Near"))
        assertTrue(zoneMatch(mps, "In zone"))
        assertFalse(zoneMatch(mps, "Below"))
        assertFalse(zoneMatch(noZone, "Near"))
        assertTrue(zoneMatch(noZone, "Any"))
        assertEquals("4.4% above the entry zone", zoneWhere(talbro))
        assertEquals("In the entry zone", zoneWhere(mps))
    }

    @Test fun decisionAndConvictionBlanks() {
        assertTrue(callMatch(pending, "Pending Buys"))
        assertFalse(callMatch(pending, "Verified Buys"))
        assertTrue(callMatch(pending, "All Buys"))
        assertTrue(cvMatch(suraksha, "Any"))
        assertTrue(cvMatch(mps, "High or medium"))
        assertFalse(cvMatch(suraksha, "High or medium"))
        assertFalse(cvMatch(P("X.NS", dc = "Hold", cv = "High"), "High"))
    }

    @Test fun sentenceReadsInPlainWords() {
        val ready = Filt(call = "Verified Buys", cv = "High", zone = "Near")
        assertEquals("Verified Buys, high conviction, near the entry price", sentenceSummary(ready, names))
        assertEquals("Verified Buys, high or medium conviction", sentenceSummary(DEFAULT_SENTENCE, names))
        val more = ready.copy(minTier = listOf(0, 2, 2, 0, 0, 0, 0), disc = listOf(1, 2))
        assertEquals("Verified Buys, high conviction, near the entry price, good quality, good valuation, a good discovery stage",
            sentenceSummary(more, names))
        assertEquals("Buys, high conviction", sentenceSummary(Filt(cv = "High"), names))
        assertEquals("Sells", decText(Filt(dc = "Sell")))
        assertEquals("verified stocks", decText(Filt(research = "Verified")))
    }

    @Test fun everyBlankCanBeRemoved() {
        val f = DEFAULT_SENTENCE.copy(setup = "Breakout", industry = "Chemicals", industryExact = true, turnaround = true)
        val cleared = sentenceBlanks(f, names).fold(f) { g, b -> b.clear(g) }
        assertEquals(Filt(), cleared)
    }
}
