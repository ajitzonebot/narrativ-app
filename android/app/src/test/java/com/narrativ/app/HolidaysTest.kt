package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.ZonedDateTime

/** NSE trading holidays (docs/data/holidays.json) close the live-quote poll; a missing file changes nothing. */
class HolidaysTest {
    private fun at(date: String, h: Int, m: Int) = ZonedDateTime.parse("${date}T%02d:%02d:00+05:30[Asia/Kolkata]".format(h, m))

    @Test fun decodesHolidayFile() {
        val h = json.decodeFromString<Holidays>("""{"source":"NSE","updated":"2026-11-20","trading_holidays":["2026-11-24","2026-12-25"]}""")
        assertEquals(listOf("2026-11-24", "2026-12-25"), h.tradingHolidays)
        assertEquals("NSE", h.source)
    }

    @Test fun missingFieldsDecodeToEmpty() {
        assertTrue(json.decodeFromString<Holidays>("{}").tradingHolidays.isEmpty())
    }

    @Test fun holidayIsClosedAndOtherWeekdayIsOpen() {
        val hol = setOf("2026-11-24")  // a Tuesday
        assertFalse(Portfolio.marketOpen(at("2026-11-24", 10, 0), hol))
        assertTrue(Portfolio.marketOpen(at("2026-11-25", 10, 0), hol))
    }

    @Test fun noFileBehavesAsBefore() {
        assertTrue(Portfolio.marketOpen(at("2026-11-24", 10, 0)))
        assertTrue(Portfolio.marketOpen(at("2026-11-24", 10, 0), emptySet()))
        assertFalse(Portfolio.marketOpen(at("2026-11-21", 10, 0)))   // Saturday
        assertFalse(Portfolio.marketOpen(at("2026-11-24", 9, 0)))    // before 09:14
        assertFalse(Portfolio.marketOpen(at("2026-11-24", 15, 40)))  // after 15:35
    }

    @Test fun publishedFileDecodesWhenPresent() {
        val docs = generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "docs/data") }.firstOrNull { it.exists() } ?: return
        val f = File(docs, "holidays.json")
        if (!f.exists()) return
        val h = json.decodeFromString<Holidays>(f.readText())
        assertTrue("dates are YYYY-MM-DD", h.tradingHolidays.all { Regex("""\d{4}-\d{2}-\d{2}""").matches(it) })
    }
}
