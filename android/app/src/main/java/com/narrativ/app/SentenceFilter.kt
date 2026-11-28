@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * Filters as a sentence (owner, 28 Nov 2026, mock-up "Filters: say it as a sentence", screen "Default sentence, + to add
 * more"): "Show me [verified Buys] with [high] conviction, priced [near the entry price] [+]". Each blank is one or more
 * Filt fields; tapping a blank opens its choices with today's count for each; "+" writes more filters into the sentence.
 */

/** The decision blank (Filt.call). "Pending Buys" are Buys without the verified seal. */
val CALLS = listOf("Verified Buys", "All Buys", "Pending Buys", "Holds", "Sells", "Any")
val CONVICTIONS = listOf("Any", "High", "High or medium", "Medium", "Low")
/** Price against the entry zone (Filt.zone). Near: in the zone or up to [NEAR_PCT] % above its top. */
val ZONES = listOf("Any", "In zone", "Near", "Below")
const val NEAR_PCT = 3.0

/** What the Stocks tab opens on. */
val DEFAULT_SENTENCE = Filt(call = "Verified Buys", cv = "High or medium")

fun callMatch(p: P, c: String): Boolean = when (c) {
    "Verified Buys" -> isBuy(p) && p.verified()
    "All Buys" -> isBuy(p)
    "Pending Buys" -> isBuy(p) && !p.verified()
    "Holds" -> p.dc == "Hold"
    "Sells" -> p.dc == "Sell" || p.dc == "Strong Sell"
    else -> true
}

/** Conviction is set on Buys only, so any conviction other than Any keeps Buys only. */
fun cvMatch(p: P, c: String): Boolean = when (c) {
    "Any" -> true
    "High or medium" -> isBuy(p) && (p.cv == "High" || p.cv == "Medium")
    else -> isBuy(p) && p.cv == c
}

fun zoneMatch(p: P, z: String): Boolean {
    if (z == "Any") return true
    val ez = p.ez
    val px = p.p
    if (ez == null || ez.size < 2 || px == null) return false
    val lo = ez[0]
    val hi = ez[1]
    return when (z) {
        "In zone" -> px >= lo && px <= hi
        "Near" -> px >= lo && px <= hi * (1 + NEAR_PCT / 100)
        "Below" -> px < lo
        else -> true
    }
}

/** Where today's price sits against the entry zone: "In the entry zone", "4.4% above the entry zone". */
fun zoneWhere(p: P): String {
    val ez = p.ez
    val px = p.p
    if (ez == null || ez.size < 2 || px == null) return "No entry zone today"
    return when {
        px > ez[1] -> "${fmt((px / ez[1] - 1) * 100, 1)}% above the entry zone"
        px < ez[0] -> "${fmt((1 - px / ez[0]) * 100, 1)}% below the entry zone"
        else -> "In the entry zone"
    }
}

/** How far today's price is from the entry zone, in % (0 inside it); no zone sorts last. */
private fun zoneGap(p: P): Double {
    val ez = p.ez
    val px = p.p
    if (ez == null || ez.size < 2 || px == null) return Double.MAX_VALUE
    return when { px > ez[1] -> (px / ez[1] - 1) * 100; px < ez[0] -> (1 - px / ez[0]) * 100; else -> 0.0 }
}

/** One choice of a blank: its label and the filter it gives. */
class SOpt(val label: String, val on: Boolean, val give: (Filt) -> Filt)

/** One blank of the sentence: what it reads now, whether it narrows the list, its choices and how it is removed. */
class SBlank(val id: String, val title: String, val text: String, val isSet: Boolean, val options: List<SOpt>, val clear: (Filt) -> Filt)

private const val PLUS = "+"
private val WITH_IDS = setOf("L0", "L1", "L2", "L3", "L4", "L5", "L6", "setup", "cross")
private val LEVEL_NOUN = listOf("stability", "quality", "valuation", "management", "momentum", "discovery stage", "outlook")
private val DC_PLURAL = mapOf("Strong Buy" to "Strong Buys", "Buy" to "Buys", "Hold" to "Holds", "Sell" to "Sells", "Strong Sell" to "Strong Sells",
    "Not rated" to "stocks not rated")
private val CALL_LABEL = mapOf("Verified Buys" to "Verified Buys", "All Buys" to "All Buys", "Pending Buys" to "Buys with research pending",
    "Holds" to "Holds", "Sells" to "Sells and Strong Sells", "Any" to "Any")
private val MCAP_TEXT = mapOf("< 1k cr" to "under ₹1,000 cr", "1k–5k cr" to "₹1,000–5,000 cr", "5k–20k cr" to "₹5,000–20,000 cr", "> 20k cr" to "over ₹20,000 cr")
/** Setup words as the stock rows and More filters say them (setupName): Breaking out, Dip in uptrend, Near entry, Wait. */
private val SETUP_TEXT = mapOf("Breakout" to "a breakout", "Pullback" to "a dip in an uptrend", "Base" to "a base near entry", "No setup" to "no setup yet")
private val CROSS_TEXT = mapOf("Golden cross, last month" to "a golden cross in the last month", "Golden cross, last 3 months" to "a golden cross in the last 3 months",
    "50-day above 200-day" to "the 50-day average above the 200-day", "Death cross, last 3 months" to "a death cross in the last 3 months")

/** The decision blank as it reads: set from the sentence (call) or from a list that opened Stocks (dc, research). */
fun decText(f: Filt): String {
    val v = when (f.research) { "Verified" -> "verified "; "Researched" -> "researched "; else -> "" }
    f.dc?.let { return v + (DC_PLURAL[it] ?: it) }
    return when (f.call) {
        "Verified Buys" -> "verified Buys"
        "All Buys" -> if (v.isEmpty()) "all Buys" else "${v}Buys"
        "Pending Buys" -> "Buys with research pending"
        "Holds" -> "${v}Holds"
        "Sells" -> "${v}Sells and Strong Sells"
        else -> if (f.cv != "Any") "${v}Buys" else if (v.isEmpty()) "all stocks" else "${v}stocks"
    }
}

/** Tier a level blank asks for: 0 any, 1 top, 2 good or better, 3..5 that tier or better; -1 a discovery set from More filters. */
private fun levelAsk(f: Filt, i: Int): Int = if (i == 5) {
    when (f.disc.sorted()) { emptyList<Int>() -> 0; listOf(1) -> 1; listOf(1, 2) -> 2; listOf(1, 2, 3) -> 3; listOf(1, 2, 3, 4) -> 4; listOf(1, 2, 3, 4, 5) -> 5; else -> -1 }
} else f.minTier.getOrElse(i) { 0 }

private fun levelText(f: Filt, i: Int, names: List<String>): String {
    val noun = LEVEL_NOUN[i]
    val t = levelAsk(f, i)
    if (t == 0) return "any $noun"
    if (t < 0) return "a discovery stage of " + f.disc.sorted().joinToString(" or ") { names.getOrElse(it - 1) { "–" }.lowercase() }
    val word = when (t) { 1 -> "top"; 2 -> "good"; 3 -> "average or better"; else -> names.getOrElse(t - 1) { "–" }.lowercase() + " or better" }
    if (i < 5) return "$word $noun"
    return (if (word.first() in "aeiou") "an " else "a ") + "$word $noun"
}

private fun setLevel(f: Filt, i: Int, t: Int): Filt =
    if (i == 5) f.copy(disc = if (t == 0) emptyList() else (1..t).toList()) else f.copy(minTier = f.minTier.toMutableList().also { if (i < it.size) it[i] = t })

/** Every blank in sentence order: decision, turnaround, conviction, price, market cap, industry, then the "with" list. */
fun sentenceBlanks(f: Filt, names: (Int) -> List<String>): List<SBlank> {
    val out = mutableListOf<SBlank>()
    val dcClear: (Filt) -> Filt = { g -> g.copy(call = "Any", dc = null, research = "Any", showRemoved = if (g.dc?.endsWith("Sell") == true) false else g.showRemoved) }
    out.add(SBlank("dec", "Decision", decText(f), f.call != "Any" || f.dc != null || f.research != "Any",
        CALLS.map { c -> SOpt(CALL_LABEL[c] ?: c, f.dc == null && f.research == "Any" && f.call == c, { g -> dcClear(g).copy(call = c) }) }, dcClear))
    out.add(SBlank("turn", "Turnaround", "turnarounds", f.turnaround, listOf(SOpt("Turnarounds", f.turnaround, { g -> g.copy(turnaround = true) })),
        { g -> g.copy(turnaround = false) }))
    out.add(SBlank("cv", "Conviction", f.cv.lowercase(), f.cv != "Any", CONVICTIONS.map { c -> SOpt(c, f.cv == c, { g -> g.copy(cv = c) }) },
        { g -> g.copy(cv = "Any") }))
    val zoneText = mapOf("Any" to "anywhere", "In zone" to "in the entry zone", "Near" to "near the entry price", "Below" to "below the entry zone")
    out.add(SBlank("zone", "Price vs the entry zone", zoneText[f.zone] ?: "anywhere", f.zone != "Any",
        ZONES.map { z -> SOpt(sentence(zoneText[z] ?: z), f.zone == z, { g -> g.copy(zone = z) }) }, { g -> g.copy(zone = "Any") }))
    out.add(SBlank("mcap", "Market cap", MCAP_TEXT[f.mcap] ?: "any amount", f.mcap != "Any",
        MCAP.map { m -> SOpt(if (m == "Any") "Any" else (MCAP_TEXT[m] ?: m).replaceFirstChar { it.uppercase() }, f.mcap == m, { g -> g.copy(mcap = m) }) },
        { g -> g.copy(mcap = "Any") }))
    val indText = when { f.industry.isBlank() -> "any industry"; f.industryExact -> f.industry; else -> "industries containing “${f.industry.trim()}”" }
    out.add(SBlank("ind", "Industry", indText, f.industry.isNotBlank(), emptyList(), { g -> g.copy(industry = "", industryExact = false) }))
    LEVEL_SHORT.indices.forEach { i ->
        val t = levelAsk(f, i)
        out.add(SBlank("L$i", LEVEL_SHORT[i], levelText(f, i, names(i)), t != 0,
            listOf(0 to "Any", 1 to "Top", 2 to "Good or better", 3 to "Average or better").map { (k, label) -> SOpt(label, t == k, { g -> setLevel(g, i, k) }) },
            { g -> setLevel(g, i, 0) }))
    }
    out.add(SBlank("setup", "Setup", SETUP_TEXT[f.setup] ?: "any setup", f.setup != "Any",
        SETUPS.map { s -> SOpt(if (s == "Any") "Any" else setupLabel(s), f.setup == s, { g -> g.copy(setup = s) }) }, { g -> g.copy(setup = "Any") }))
    out.add(SBlank("cross", "50-day vs 200-day average", CROSS_TEXT[f.cross] ?: "any 50-day vs 200-day average", f.cross != "Any",
        CROSSES.map { c -> SOpt(c, f.cross == c, { g -> g.copy(cross = c) }) }, { g -> g.copy(cross = "Any") }))
    return out
}

/** Blanks the sentence shows: the decision always, every blank that narrows the list, and blanks added with "+" this visit. */
fun visibleBlanks(all: List<SBlank>, extra: Set<String>): List<SBlank> = all.filter { it.id == "dec" || it.isSet || it.id in extra }

/** The sentence in a short line for a saved card: "Verified Buys, high conviction, near the entry price". */
fun sentenceSummary(f: Filt, names: (Int) -> List<String>): String {
    val parts = mutableListOf<String>()
    sentenceBlanks(f, names).filter { it.isSet || it.id == "dec" }.forEach { b ->
        parts.add(when (b.id) {
            "dec" -> b.text.replaceFirstChar { it.uppercase() }
            "cv" -> "${b.text} conviction"
            "mcap" -> "worth ${b.text}"
            "ind" -> "in ${b.text}"
            "turn" -> "turnarounds"
            else -> b.text
        })
    }
    if (f.syms.isNotEmpty()) parts.add(f.name.ifBlank { "selected stocks" }.lowercase())
    f.verdict?.let { parts.add(it.lowercase()) }
    if (f.bq) parts.add("beaten-up quality")
    if (f.q.isNotBlank()) parts.add("matching “${f.q.trim()}”")
    return parts.joinToString(", ")
}

/** What a near miss lacks for one blank: "Medium conviction", "4.4% above the entry zone", "Quality: Average". */
fun missText(st: AppState, id: String, p: P): String = when (id) {
    "dec" -> when {
        isBuy(p) && p.ic != null -> "${p.dc}, research pending"
        isBuy(p) && !p.verified() -> "${p.dc}, not verified"
        else -> p.dc ?: "Not rated"
    }
    "cv" -> p.cv?.let { "$it conviction" } ?: "No conviction set"
    "zone" -> zoneWhere(p)
    "turn" -> "Not a turnaround"
    "mcap" -> p.mc?.let { "Market cap ₹${fmt(it, 0)} cr" } ?: "Market cap not known"
    "ind" -> p.i ?: "Industry not known"
    "setup" -> "Setup: " + setupName(p.su, p.tb == 1).lowercase()
    "cross" -> when (p.ma) { 1 -> "50-day above the 200-day"; 0 -> "50-day below the 200-day"; else -> "No average data" }
    else -> id.removePrefix("L").toIntOrNull()?.let { i -> "${LEVEL_SHORT.getOrElse(i) { "" }}: ${p.levelTierName(st, i)}" } ?: ""
}

/** Stocks that miss exactly one blank of the sentence, with what they miss: taken in turn from each blank (best score
 *  first within a blank), so one wide blank does not crowd out the others. */
fun nearMisses(st: AppState, f: Filt, picks: List<P>, researched: (P) -> Boolean, names: (Int) -> List<String>, max: Int = 5): List<Pair<P, String>> {
    val groups = sentenceBlanks(f, names).filter { it.isSet }.map { b ->
        val g = b.clear(f)
        val hits = picks.filter { g.match(it, researched) && !f.match(it, researched) }.sortedByDescending { it.pr }
        // closest first where "close" has a meaning: Medium before Low conviction, the smallest gap to the entry zone
        when (b.id) {
            "cv" -> hits.sortedBy { listOf("High", "Medium", "Low").indexOf(it.cv).let { k -> if (k < 0) 9 else k } }
            "zone" -> hits.sortedBy { zoneGap(it) }
            else -> hits
        }.map { p -> p to missText(st, b.id, p) }
    }
    val out = mutableListOf<Pair<P, String>>()
    var k = 0
    while (out.size < max && groups.any { k < it.size }) {
        groups.forEach { grp -> if (k < grp.size && out.size < max && out.none { it.first.s == grp[k].first.s }) out.add(grp[k]) }
        k++
    }
    return out
}

private sealed interface Tok
private class Word(var text: String) : Tok
private class Gap(val blank: SBlank, var after: String = "") : Tok
private object PlusTok : Tok

private fun sentenceWords(s: String): List<Tok> = s.split(" ").map { Word(it) }

/** Words and blanks in reading order, commas attached to the word or blank before them so a line never starts with one. */
private fun sentenceTokens(visible: List<SBlank>): List<Tok> {
    val by = visible.associateBy { it.id }
    val segs = mutableListOf<List<Tok>>()
    by["dec"]?.let { segs.add(sentenceWords("Show me") + Gap(it)) }
    listOf("turn" to "that are", "cv" to "with", "zone" to "priced", "mcap" to "worth", "ind" to "in").forEach { (id, lead) ->
        by[id]?.let { b -> segs.add(sentenceWords(lead) + Gap(b) + (if (id == "cv") sentenceWords("conviction") else emptyList())) }
    }
    val with = visible.filter { it.id in WITH_IDS }
    if (with.isNotEmpty()) {
        val s = mutableListOf<Tok>(Word("with"))
        with.forEachIndexed { k, b ->
            if (k > 0 && k == with.lastIndex) s.add(Word("and"))
            s.add(Gap(b, if (k < with.lastIndex - 1) "," else ""))
        }
        segs.add(s)
    }
    val out = mutableListOf<Tok>()
    segs.forEachIndexed { k, s ->
        if (k >= 2) {
            val last = out.last()
            if (last is Word) last.text += "," else if (last is Gap) last.after += ","
        }
        out.addAll(s)
    }
    out.add(PlusTok)
    return out
}

@Composable
private fun SLabel(text: String, modifier: Modifier = Modifier) {
    if (Look.paper) PaperLabel(text, C.dim, 10.sp, modifier = modifier) else T(text, 12.sp, C.dim, modifier = modifier, maxLines = 1)
}

@Composable
private fun BlankText(text: String, on: Boolean, style: TextStyle, onClick: () -> Unit) {
    val ink = C.teal
    Text(text, style = style.copy(color = if (on) C.onAccent else ink), modifier = Modifier
        .background(if (on) ink else Color.Transparent)
        .clickable(onClick = onClick)
        .drawBehind {
            val w = 2.dp.toPx()
            val y = size.height - w / 2
            drawLine(ink, Offset(0f, y), Offset(size.width, y), strokeWidth = w)
        }
        .padding(horizontal = 2.dp))
}

/** The sentence itself: Playfair on Paper, blanks in slate ink with a slate underline; the open blank filled in slate. */
@Composable
private fun SentenceText(toks: List<Tok>, open: String?, onTap: (String) -> Unit) {
    val style = TextStyle(fontSize = 21.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold, color = C.white,
        fontFamily = if (Look.paper) PaperFonts.headline else null)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        toks.forEach { t ->
            when (t) {
                is Word -> Text(t.text, style = style)
                is Gap -> Row {
                    BlankText(t.blank.text, t.blank.id == open, style) { onTap(t.blank.id) }
                    if (t.after.isNotEmpty()) Text(t.after, style = style)
                }
                else -> BlankText(" + ", open == PLUS, style) { onTap(PLUS) }
            }
        }
    }
}

@Composable
private fun ChoiceBox(label: String, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.padding(top = 10.dp).fillMaxWidth()) {
        SLabel(label)
        Column(Modifier.padding(top = 6.dp).fillMaxWidth().clip(rr(6.dp)).background(C.card).border(1.dp, C.line, rr(6.dp)).padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp), content = content)
    }
}

/**
 * The filter sentence with the open blank's choices under it and "Save this sentence". [extra] holds blanks added with "+"
 * (or set to Any) this visit, so they stay in the sentence until removed.
 */
@Composable
fun SentenceBlock(st: AppState, f: Filt, open: String?, extra: Set<String>, researched: (P) -> Boolean, savedAlready: Boolean,
                  onFilt: (Filt) -> Unit, onOpen: (String?) -> Unit, onExtra: (Set<String>) -> Unit, onSave: (String) -> Unit) {
    val pf = st.picks ?: return
    val names: (Int) -> List<String> = { i -> (1..5).map { tierName(st, i, it) } }
    val all = sentenceBlanks(f, names)
    val visible = visibleBlanks(all, extra)
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth()) {
        SentenceText(sentenceTokens(visible), open) { id -> onOpen(if (open == id) null else id) }
        if (open == PLUS) {
            val addable = all.filter { b -> b.id != "dec" && visible.none { it.id == b.id } }
            ChoiceBox("Add to the sentence") {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    addable.forEach { b ->
                        ToggleChip(b.title, false, {
                            if (b.id == "turn") onFilt(f.copy(turnaround = true)) else onExtra(extra + b.id)
                            onOpen(b.id)
                        })
                    }
                }
            }
        } else all.firstOrNull { it.id == open && visible.any { v -> v.id == it.id } }?.let { b ->
            val pick: (Filt) -> Unit = { g -> onFilt(g); if (b.id != "turn") onExtra(extra + b.id) }
            val remove: () -> Unit = { onFilt(b.clear(f)); onExtra(extra - b.id); onOpen(null) }
            ChoiceBox("${b.title} (the blank you tapped)") {
                if (b.id == "ind") IndustryChoices(f, pf.picks, researched, pick)
                else {
                    val counts = remember(f, b.id, pf, st.research) { b.options.map { o -> o.give(f).let { g -> pf.picks.count { g.match(it, researched) } } } }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        b.options.forEachIndexed { k, o -> ToggleChip(o.label, o.on, { pick(o.give(f)) }, count = counts.getOrNull(k)) }
                    }
                }
                if (b.id == "zone") T("Near the entry price: in the entry zone or up to ${fmt(NEAR_PCT, 0)}% above it. Only stocks with a live setup " +
                    "(breakout, pullback or base) have an entry zone.", 11.sp, C.dim)
                if (b.id != "dec") MoreLink("Remove from the sentence", onClick = remove)
            }
        }
        SaveSentence(f, savedAlready, names, onSave)
    }
}

@Composable
private fun IndustryChoices(f: Filt, picks: List<P>, researched: (P) -> Boolean, pick: (Filt) -> Unit) {
    val base = remember(f, picks) { f.copy(industry = "", industryExact = false) }
    val inds = remember(base, picks) {
        picks.filter { base.match(it, researched) }.groupingBy { it.i ?: "" }.eachCount().filterKeys { it.isNotBlank() }.toList().sortedByDescending { it.second }
    }
    val total = remember(base, picks) { picks.count { base.match(it, researched) } }
    var showAll by remember { mutableStateOf(false) }
    val shown = if (showAll) inds else inds.take(12).let { top -> if (f.industryExact && top.none { it.first == f.industry }) top + inds.filter { it.first == f.industry } else top }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        ToggleChip("Any industry", f.industry.isBlank(), { pick(base) }, count = total)
        shown.forEach { (name, n) -> ToggleChip(name, f.industryExact && f.industry.equals(name, true), { pick(base.copy(industry = name, industryExact = true)) }, count = n) }
        if (!showAll && inds.size > shown.size) ToggleChip("All ${inds.size} industries", false, { showAll = true })
    }
}

@Composable
private fun SaveSentence(f: Filt, savedAlready: Boolean, names: (Int) -> List<String>, onSave: (String) -> Unit) {
    if (savedAlready) return
    var naming by remember(f) { mutableStateOf<String?>(null) }
    val current = naming
    if (current == null) {
        MoreLink("Save this sentence", Modifier.padding(top = 4.dp)) {
            naming = if (f.copy(sort = "Score", q = "") == DEFAULT_SENTENCE) "Ready to buy" else sentenceSummary(f, names).take(40)
        }
        return
    }
    Row(Modifier.padding(top = 10.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.weight(1f).clip(rr(12.dp)).background(C.chip).padding(horizontal = 12.dp, vertical = 11.dp)) {
            BasicTextField(current, { naming = it }, singleLine = true, textStyle = TextStyle(color = C.white, fontSize = 14.sp), cursorBrush = SolidColor(C.blue),
                modifier = Modifier.fillMaxWidth(), decorationBox = { inner -> if (current.isEmpty()) T("Name this sentence", 14.sp, C.dim); inner() })
        }
        T("Save", 14.sp, C.blue, FontWeight.SemiBold, modifier = Modifier.clip(rr(8.dp)).clickable { onSave(current.trim().ifBlank { "My sentence" }); naming = null }.padding(6.dp))
        Icon(Icons.Rounded.Close, "Cancel", tint = C.dim, modifier = Modifier.clip(rr(8.dp)).clickable { naming = null }.padding(4.dp).size(18.dp))
    }
}

/** Saved sentences at the top of Stocks: name, the sentence in short, today's count; the one on screen has a slate border. */
@Composable
fun SavedSentences(st: AppState, saved: List<Filt>, current: Filt, researched: (P) -> Boolean, onOpen: (Filt) -> Unit, onDelete: (Filt) -> Unit, onNew: () -> Unit) {
    val pf = st.picks ?: return
    val names: (Int) -> List<String> = { i -> (1..5).map { tierName(st, i, it) } }
    val counts = remember(saved, pf, st.research) { saved.map { s -> pf.picks.count { s.match(it, researched) } } }
    Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        SLabel("Your sentences")
        saved.forEachIndexed { k, s ->
            val on = s.sameSentence(current)
            Row(Modifier.fillMaxWidth().clip(rr(6.dp)).background(C.card).border(if (on) 2.dp else 1.dp, if (on) C.teal else C.line, rr(6.dp))
                .clickable { onOpen(s) }.padding(start = 10.dp, top = 8.dp, bottom = 8.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(s.name.ifBlank { "Saved ${k + 1}" }, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = C.white, maxLines = 1,
                        fontFamily = if (Look.paper) PaperFonts.label else null)
                    T(sentenceSummary(s, names), 11.5.sp, C.dim, maxLines = 2)
                }
                Text("${counts.getOrElse(k) { 0 }}", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = C.white, maxLines = 1,
                    fontFamily = if (Look.paper) PaperFonts.headline else null, modifier = Modifier.padding(horizontal = 8.dp))
                Icon(Icons.Rounded.Close, "Delete ${s.name}", tint = C.dim, modifier = Modifier.clip(rr(8.dp)).clickable { onDelete(s) }.padding(6.dp).size(16.dp))
            }
        }
        T("+ New sentence", 13.sp, C.blue, FontWeight.SemiBold, modifier = Modifier.clip(rr(8.dp)).clickable(onClick = onNew).padding(vertical = 4.dp))
    }
}
