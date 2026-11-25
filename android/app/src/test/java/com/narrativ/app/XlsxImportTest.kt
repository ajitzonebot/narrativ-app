package com.narrativ.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** feedback #91: Zerodha's holdings export is an .xlsx with title rows above the header; the CSV keeps working. */
class XlsxImportTest {
    private fun zip(vararg parts: Pair<String, String>): ByteArray {
        val bo = ByteArrayOutputStream()
        ZipOutputStream(bo).use { z -> parts.forEach { (n, t) -> z.putNextEntry(ZipEntry(n)); z.write(t.toByteArray()); z.closeEntry() } }
        return bo.toByteArray()
    }

    private val ns = """xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships""""

    /** A Zerodha-shaped workbook: title rows, a blank column A, header "Symbol / Quantity Available / Average Price", a second sheet. */
    private fun zerodhaXlsx(): ByteArray {
        val strings = listOf("Equity Holdings Statement as on 2026-11-25", "Client ID", "AB1234", "Symbol", "ISIN", "Quantity Available",
            "Quantity Discrepant", "Average Price", "Previous Closing Price", "CAPLIPOINT", "INE475E01026", "SATIN")
        val sst = "<sst $ns count=\"${strings.size}\" uniqueCount=\"${strings.size}\">" +
            strings.joinToString("") { if (it == "SATIN") "<si><r><t>SAT</t></r><r><t>IN</t></r></si>" else "<si><t>$it</t></si>" } + "</sst>"
        fun s(ref: String, i: Int) = "<c r=\"$ref\" t=\"s\"><v>$i</v></c>"
        fun n(ref: String, v: String) = "<c r=\"$ref\"><v>$v</v></c>"
        val sheet = "<worksheet $ns><sheetData>" +
            "<row r=\"2\">${s("B2", 0)}</row>" +
            "<row r=\"4\">${s("B4", 1)}${s("C4", 2)}</row>" +
            "<row r=\"7\">${s("B7", 3)}${s("C7", 4)}${s("D7", 5)}${s("E7", 6)}${s("F7", 7)}${s("G7", 8)}</row>" +
            "<row r=\"8\">${s("B8", 9)}${s("C8", 10)}${n("D8", "12")}${n("E8", "0")}${n("F8", "2346.8")}${n("G8", "2033.3")}</row>" +
            "<row r=\"9\">${s("B9", 11)}<c r=\"C9\" t=\"inlineStr\"><is><t>INE713Q01011</t></is></c>${n("D9", "40")}${n("E9", "0")}${n("F9", "258.88")}${n("G9", "252.17")}</row>" +
            "<row r=\"10\"><c r=\"B10\" t=\"inlineStr\"><is><t>IGIL</t></is></c>${n("D10", "0")}${n("F10", "400")}</row>" +
            "</sheetData></worksheet>"
        val other = "<worksheet $ns><sheetData><row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>Mutual Funds</t></is></c></row></sheetData></worksheet>"
        val wb = "<workbook $ns><sheets><sheet name=\"Equity\" sheetId=\"1\" r:id=\"rId3\"/><sheet name=\"Mutual Funds\" sheetId=\"2\" r:id=\"rId4\"/></sheets></workbook>"
        val rels = "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
            "<Relationship Id=\"rId4\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>" +
            "<Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet2.xml\"/>" +
            "</Relationships>"
        return zip("[Content_Types].xml" to "<Types/>", "xl/workbook.xml" to wb, "xl/_rels/workbook.xml.rels" to rels,
            "xl/sharedStrings.xml" to sst, "xl/worksheets/sheet1.xml" to other, "xl/worksheets/sheet2.xml" to sheet)
    }

    @Test fun readsZerodhaXlsx() {
        val b = zerodhaXlsx()
        assertTrue(Xlsx.isZip(b))
        val h = Portfolio.parseFile(b)
        assertEquals(listOf("CAPLIPOINT", "SATIN"), h.map { it.s })  // the zero-quantity row is left out
        assertEquals(12.0, h[0].qty, 0.0); assertEquals(2346.8, h[0].avg, 1e-9); assertEquals(2033.3, h[0].fileLtp!!, 1e-9)
        assertEquals(40.0, h[1].qty, 0.0); assertEquals(258.88, h[1].avg, 1e-9)
    }

    @Test fun keepsColumnPositions() {
        val rows = Xlsx.rows(zerodhaXlsx())
        val head = rows.first { "Symbol" in it }
        assertEquals("", head[0]); assertEquals("Symbol", head[1]); assertEquals("Average Price", head[5])
    }

    @Test fun fallsBackToSheet1WithoutWorkbook() {
        val sheet = "<worksheet $ns><sheetData>" +
            "<row><c t=\"inlineStr\"><is><t>Instrument</t></is></c><c t=\"inlineStr\"><is><t>Qty.</t></is></c><c t=\"inlineStr\"><is><t>Avg. cost</t></is></c><c t=\"inlineStr\"><is><t>LTP</t></is></c></row>" +
            "<row><c t=\"inlineStr\"><is><t>thejo</t></is></c><c><v>5</v></c><c><v>1,200.5</v></c><c><v>1300</v></c></row>" +
            "</sheetData></worksheet>"
        val h = Portfolio.parseFile(zip("xl/worksheets/sheet1.xml" to sheet))
        assertEquals(1, h.size); assertEquals("THEJO", h[0].s); assertEquals(1200.5, h[0].avg, 1e-9); assertEquals(1300.0, h[0].fileLtp!!, 1e-9)
    }

    @Test fun csvStillWorksAndSkipsTitleRows() {
        val csv = "﻿Instrument,Qty.,Avg. cost,LTP,Cur. val\n\"HEROMOTOCO\",3,\"5,400.00\",5535,16605\n"
        assertEquals(listOf(Holding("HEROMOTOCO", 3.0, 5400.0, 5535.0)), Portfolio.parseFile(csv.toByteArray()))
        val titled = "Holdings as on 25 Nov\n\nSymbol,Quantity Available,Average Price\nEPL,10,210\n"
        assertEquals(listOf(Holding("EPL", 10.0, 210.0, null)), Portfolio.parse(titled))
    }

    @Test fun notHoldingsGivesNothing() {
        assertTrue(Portfolio.parseFile("a,b,c\n1,2,3".toByteArray()).isEmpty())
        assertTrue(Portfolio.parseFile(byteArrayOf('P'.code.toByte(), 'K'.code.toByte(), 3, 4, 0, 0)).isEmpty())
        assertFalse(Xlsx.isZip("Instrument".toByteArray()))
        assertNull(Xlsx.col("12")); assertEquals(27, Xlsx.col("AB3"))
    }
}
