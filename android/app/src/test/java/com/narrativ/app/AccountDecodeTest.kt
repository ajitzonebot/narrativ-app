package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Account screens: the extra fields they read from calls.json, health.json and data_issues.json, and the signed-number helper. */
class AccountDecodeTest {
    private val docs = generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "docs/data") }.first { it.exists() || it.path == "/docs/data" }

    @Test fun callsMaturity() {
        val f = File(docs, "calls.json")
        if (!f.exists()) return
        val c = json.decodeFromString<CallsMat>(f.readText())
        // keys 1m, 3m, 6m, 12m exist; n = 0 until a verified Buy is that old
        listOf("1m", "3m", "6m", "12m").forEach { k -> assertNotNull("verified.$k", c.summary.verified[k]) }
    }

    @Test fun healthUniverseAndIssues() {
        val h = File(docs, "health.json")
        if (h.exists()) {
            val txt = h.readText()
            json.decodeFromString<Health>(txt)
            assertTrue("universe", (json.decodeFromString<HealthU>(txt).universe ?: 0) > 0)
        }
        val i = File(docs, "data_issues.json")
        if (i.exists()) { json.decodeFromString<IssuesFile>(i.readText()); json.decodeFromString<IssuesU>(i.readText()) }
    }

    @Test fun signedFigures() {
        assertEquals("+1.69%", sg(1.69))
        assertEquals("−3.12%", sg(-3.12))
        assertEquals("–", sg(null))
        assertEquals("+3.73", sg(3.73, 2, ""))
    }
}
