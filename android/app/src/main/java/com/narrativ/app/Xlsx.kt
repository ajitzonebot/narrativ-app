package com.narrativ.app

import org.w3c.dom.Element
import org.w3c.dom.Node
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.zip.ZipInputStream
import javax.xml.parsers.DocumentBuilderFactory

/**
 * Minimal .xlsx reader for the Zerodha holdings export (feedback #91), with no extra library: an .xlsx is a zip of XML parts.
 * Reads the first worksheet (xl/workbook.xml + its rels, else xl/worksheets/sheet1.xml) into rows of cell text, resolving
 * shared strings, inline strings, formula strings, booleans and numbers. Columns keep their position (a blank column A stays "").
 */
object Xlsx {
    private const val MAX_PART = 16L * 1024 * 1024  // one XML part; a holdings file is a few KB
    private const val MAX_TOTAL = 48L * 1024 * 1024

    /** True when [b] starts like a zip file (an .xlsx), rather than CSV text. */
    fun isZip(b: ByteArray): Boolean = b.size >= 4 && b[0] == 'P'.code.toByte() && b[1] == 'K'.code.toByte() && b[2] == 3.toByte() && b[3] == 4.toByte()

    /** Rows of the first worksheet; empty when the file is not a readable .xlsx. */
    fun rows(bytes: ByteArray): List<List<String>> = runCatching { readRows(unzip(bytes)) }.getOrDefault(emptyList())

    private fun unzip(bytes: ByteArray): Map<String, ByteArray> {
        val out = HashMap<String, ByteArray>(); var total = 0L
        ZipInputStream(ByteArrayInputStream(bytes)).use { z ->
            val buf = ByteArray(8192)
            while (true) {
                val e = z.nextEntry ?: break
                val name = e.name.trimStart('/')
                if (e.isDirectory || !name.startsWith("xl/") || !name.endsWith(".xml") && !name.endsWith(".rels")) continue
                val bo = ByteArrayOutputStream(); var n: Int; var size = 0L
                while (z.read(buf).also { n = it } > 0) {
                    size += n; total += n
                    if (size > MAX_PART || total > MAX_TOTAL) error("xlsx part too large")
                    bo.write(buf, 0, n)
                }
                out[name] = bo.toByteArray()
            }
        }
        return out
    }

    private fun parse(b: ByteArray): Element {
        val f = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true; isExpandEntityReferences = false }
        runCatching { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
        runCatching { f.setFeature("http://xml.org/sax/features/external-general-entities", false) }
        runCatching { f.setFeature("http://xml.org/sax/features/external-parameter-entities", false) }
        return f.newDocumentBuilder().parse(ByteArrayInputStream(b)).documentElement
    }

    private fun Node.local(): String = localName ?: nodeName.substringAfter(':')
    private fun Element.kids(name: String): List<Element> {
        val out = mutableListOf<Element>(); val cs = childNodes
        for (i in 0 until cs.length) (cs.item(i) as? Element)?.takeIf { it.local() == name }?.let { out += it }
        return out
    }
    private fun Element.all(name: String): List<Element> {
        val nl = getElementsByTagNameNS("*", name)
        return (0 until nl.length).map { nl.item(it) as Element }
    }
    /** An attribute by local name, whatever its namespace prefix (r:id). */
    private fun Element.attr(name: String): String? {
        val a = attributes
        for (i in 0 until a.length) { val n = a.item(i); if (n.local() == name) return n.nodeValue }
        return null
    }
    /** Text of a string item (<si> or <is>): plain <t>, or the runs' <t> (phonetic <rPh> left out). */
    private fun Element.stringItem(): String = buildString {
        kids("t").forEach { append(it.textContent) }
        kids("r").forEach { r -> r.kids("t").forEach { append(it.textContent) } }
    }

    private fun firstSheet(parts: Map<String, ByteArray>): ByteArray? {
        val viaWorkbook = runCatching {
            val wb = parse(parts.getValue("xl/workbook.xml"))
            val rid = wb.all("sheet").firstOrNull()?.attr("id") ?: return@runCatching null
            val rels = parse(parts.getValue("xl/_rels/workbook.xml.rels"))
            val target = rels.all("Relationship").firstOrNull { it.getAttribute("Id") == rid }?.getAttribute("Target") ?: return@runCatching null
            val path = if (target.startsWith("/")) target.trimStart('/') else "xl/" + target.removePrefix("./")
            parts[path]
        }.getOrNull()
        return viaWorkbook ?: parts["xl/worksheets/sheet1.xml"]
            ?: parts.keys.filter { it.startsWith("xl/worksheets/") && it.endsWith(".xml") }.minOrNull()?.let { parts[it] }
    }

    /** "BC12" -> 54 (0-based column), or null when the reference has no letters. */
    internal fun col(ref: String?): Int? {
        val letters = ref?.takeWhile { it.isLetter() }?.uppercase().orEmpty()
        if (letters.isEmpty()) return null
        return letters.fold(0) { acc, ch -> acc * 26 + (ch - 'A' + 1) } - 1
    }

    private fun readRows(parts: Map<String, ByteArray>): List<List<String>> {
        val shared = parts["xl/sharedStrings.xml"]?.let { b -> parse(b).kids("si").map { it.stringItem() } }.orEmpty()
        val sheet = parse(firstSheet(parts) ?: return emptyList())
        val data = sheet.kids("sheetData").firstOrNull() ?: return emptyList()
        return data.kids("row").map { row ->
            val cells = sortedMapOf<Int, String>(); var next = 0
            row.kids("c").forEach { c ->
                val i = col(c.attr("r")) ?: next
                next = i + 1
                val v = c.kids("v").firstOrNull()?.textContent
                val text = when (c.attr("t")) {
                    "s" -> v?.trim()?.toIntOrNull()?.let { shared.getOrNull(it) }
                    "inlineStr" -> c.kids("is").firstOrNull()?.stringItem()
                    "b" -> if (v?.trim() == "1") "TRUE" else "FALSE"
                    else -> v
                } ?: ""
                cells[i] = text
            }
            val width = (cells.keys.maxOrNull() ?: -1) + 1
            List(width) { cells[it] ?: "" }
        }
    }
}
