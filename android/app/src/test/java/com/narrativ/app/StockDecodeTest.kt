package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Fields the redesigned stock page reads (flag reviews, driver due dates, chart start, checkpoint resolution, valuation key, sector ticker). */
class StockDecodeTest {
    private val docs = generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "docs/data") }.first { it.exists() || it.path == "/docs/data" }

    @Test fun research() {
        val f = File(docs, "research.json")
        if (!f.exists()) return
        val r = json.decodeFromString<Map<String, Research>>(f.readText())
        val raw = f.readText()
        if (raw.contains("\"flag_reviews\"")) assertTrue("flag reviews decoded", r.values.any { it.flagReviews.values.any { v -> v.verdict != null } })
        if (raw.contains("\"due\"")) assertTrue("driver due dates decoded", r.values.any { it.drivers.any { d -> d.due != null } })
    }

    @Test fun chartStart() {
        val dir = File(docs, "charts")
        val f = dir.listFiles()?.firstOrNull { it.extension == "json" } ?: return
        val c = json.decodeFromString<Chart>(f.readText())
        if (f.readText().contains("\"d0\"")) assertTrue("d0", c.d0 != null && c.d0!!.length == 10)
    }

    @Test fun historyAndLevels() {
        val hs = File(docs, "stocks").listFiles()?.filter { it.extension == "json" }?.take(200).orEmpty().map { json.decodeFromString<StockHistory>(it.readText()) }
        if (hs.any { h -> h.checkpoints.any { it.status == "met" } }) assertTrue("resolved dates", hs.any { h -> h.checkpoints.any { it.resolved != null } })
        File(docs, "fin").listFiles()?.filter { it.extension == "json" }?.take(50)?.forEach { f ->
            val txt = f.readText()
            if (!txt.contains("\"levels\"")) return@forEach
            val d = json.decodeFromString<Detail>(txt)
            val v = d.levels["val"] ?: return@forEach
            if (txt.contains("\"mkey\"") && v.metric != null) assertTrue("${f.name} mkey", v.mkey != null)
        }
    }

    @Test fun rotationTicker() {
        val f = File(docs, "rotation.json")
        if (!f.exists()) return
        val r = json.decodeFromString<RotationFile>(f.readText())
        if (f.readText().contains("\"ticker\"")) assertTrue("ticker", r.sectors.values.any { it.ticker != null })
    }

    @Test fun parseHelpers() {
        assertEquals(listOf(23.0, 21.2, 29.9), skNums("P/E 23.0 vs own 21.2–29.9"))
        assertEquals(35.8, skFind("median 35.8 (35 companies)", "median (-?[\\d.]+)")!!, 1e-9)
        assertEquals(-0.3, skFind("7.9% (MF 1.6%, foreign 5.7%) · 1Q -0.3 pts · 4Q -0.7 pts", "1Q (-?[\\d.]+) pts")!!, 1e-9)
        assertEquals("29th", skOrd(29)); assertEquals("11th", skOrd(11)); assertEquals("21st", skOrd(21))
        assertEquals("−0.69", skFx(-0.69, 2)); assertEquals("0.00", skFx(-0.001, 2)); assertEquals("+11.0%", skSgn(11.0))
    }
}
