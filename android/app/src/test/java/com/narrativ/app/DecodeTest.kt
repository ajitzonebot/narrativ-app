package com.narrativ.app

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Decodes the pipeline's real output with the app's models (catches field/type mismatches before release). */
class DecodeTest {
    private val docs = generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "docs/data") }.first { it.exists() || it.path == "/docs/data" }

    @Test fun picks() {
        val f = File(docs, "picks.json")
        if (!f.exists()) return
        val txt = f.readText()
        if (!txt.startsWith("{\"v\":")) { println("picks.json is pre-v2 data; skipped"); return }
        val p = json.decodeFromString<PicksFile>(txt)
        assertTrue("v2 file", p.v >= 2)
        assertTrue("has picks", p.picks.isNotEmpty())
        assertTrue("tiers", p.picks.all { it.t.size == 7 })
        if (txt.contains("\"research_updated\"")) assertTrue("research_updated", p.researchUpdated?.startsWith("20") == true)
        println("picks ${p.picks.size}, mood ${p.mood?.score} ${p.mood?.zone}, funnel ${p.funnel.levels}")
    }

    @Test fun details() {
        val dir = File(docs, "fin")
        val files = dir.listFiles()?.filter { it.extension == "json" }.orEmpty()
        var n = 0
        files.forEach { f ->
            val txt = f.readText()
            if (!txt.contains("\"levels\"")) return@forEach  // pre-v2 file
            val d = json.decodeFromString<Detail>(txt)
            assertTrue("${f.name} levels", d.levels.size == 7)
            assertTrue("${f.name} statement", d.statement.isNotBlank())
            d.m("pe"); d.quarterly; d.roceFy
            n++
        }
        println("details decoded $n")
    }

    @Test fun rotation() {
        val f = File(docs, "rotation.json")
        if (f.exists()) json.decodeFromString<RotationFile>(f.readText())
    }
}
