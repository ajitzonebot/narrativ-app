@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.HourglassTop
import androidx.compose.material3.Icon
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import kotlin.math.abs

/*
 * Stock page redesign, part 2 (mockups scratchpad/mock/out_stock, generator screens_stock.py): shared helpers for the
 * stock tabs, the Filings tab (s09) and the sheets behind the Summary rows (Claude's research, all ratios).
 */

// ---------------------------------------------------------------- small helpers (figures parsed from the rule texts)
private val SK_NUM = Regex("-?\\d+(?:\\.\\d+)?")

/** Numbers in a rule text ("P/E 23.0 vs own 21.2–29.9" -> 23.0, 21.2, 29.9). Grouping commas and the − sign handled. */
fun skNums(s: String?): List<Double> = if (s == null) emptyList()
    else SK_NUM.findAll(s.replace(",", "").replace("−", "-")).mapNotNull { it.value.toDoubleOrNull() }.toList()

/** First capture group of [re] in [s] as a number. */
fun skFind(s: String?, re: String): Double? = s?.replace(",", "")?.replace("−", "-")?.let { Regex(re).find(it)?.groupValues?.getOrNull(1)?.toDoubleOrNull() }

fun Level.item(id: String): Item? = items.firstOrNull { it.id == id }
fun Level.status(id: String): String = statusOf(item(id)?.m)

fun skOrd(n: Int): String = "$n" + if (n % 100 in 10..20) "th" else when (n % 10) { 1 -> "st"; 2 -> "nd"; 3 -> "rd"; else -> "th" }

private fun fixed(v: Double, d: Int): String = java.text.NumberFormat.getNumberInstance(java.util.Locale("en", "IN"))
    .apply { minimumFractionDigits = d; maximumFractionDigits = d }.format(v)

/** Fixed decimals, Indian grouping, a real minus sign ("−0.69", "2,084.60"). */
fun skFx(v: Double?, d: Int = 1): String = if (v == null) "–" else (if (v < 0 && abs(v) >= 0.5 * Math.pow(10.0, -d.toDouble())) "−" else "") + fixed(abs(v), d)

/** Signed with a unit: +11.0%, −2.3 pts. */
fun skSgn(v: Double?, d: Int = 1, unit: String = "%"): String = if (v == null) "–" else (if (v >= 0) "+" else "−") + fixed(abs(v), d) + unit

fun skRs(v: Double?, d: Int = 0): String = v?.let { "₹" + fmt(it, d) } ?: "–"
fun skDate(s: String?): LocalDate? = runCatching { LocalDate.parse(s!!.take(10)) }.getOrNull()
fun skToday(): LocalDate = LocalDate.now(ZoneId.of("Asia/Kolkata"))

/** "16 Nov", with the year when it is not this year (or [year]). */
fun skDay(iso: String?, year: Boolean? = null): String {
    val d = skDate(iso) ?: return iso ?: "–"
    val y = year ?: (d.year != skToday().year)
    return "${d.dayOfMonth} " + d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH) + if (y) " ${d.year}" else ""
}

/** A due date: the exact day ("24 Nov") when it has one, else the month ("Nov 2026") for month-precision items; "–" when missing. */
fun skDue(s: String?): String {
    if (s.isNullOrBlank()) return "–"
    if (skDate(s) != null) return skDay(s)
    val ym = runCatching { java.time.YearMonth.parse(s.take(7)) }.getOrNull() ?: return s
    val m = ym.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)
    return if (ym.year != skToday().year) "$m ${ym.year}" else m
}


// ---------------------------------------------------------------- small UI pieces
/** Chip with coloured text and no dot ("1M +11.0%", "vs 200-day −5.2%"). */
@Composable
fun ValChip(text: String, color: Color = C.muted, modifier: Modifier = Modifier) {
    Box(modifier.clip(rr(S.inner)).background(C.chip).padding(horizontal = 8.dp, vertical = 3.dp)) {
        T(text, 11.sp, color, maxLines = 1)
    }
}

/** Empty state inside the page padding. */
@Composable
fun EmptyNote(text: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().clip(rr(S.card)).background(C.card).padding(S.cardPad)) { T(text, 13.sp, C.dim, lineHeight = 18.sp) }
}

/** Tappable row with a label, grey right text and a chevron (Summary: Claude's research, all ratios). */
@Composable
fun LinkRow(label: String, right: String = "", divider: Boolean = false, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        if (divider) HLineDivider()
        Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            T(label, 14.sp, modifier = Modifier.weight(1f), maxLines = 1)
            if (right.isNotEmpty()) T(right, 12.sp, C.dim, maxLines = 1)
            Icon(Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.padding(start = 2.dp).size(16.dp))
        }
    }
}

/** Track with one dot (P/E today inside its own range, on a Summary tile). */
@Composable
fun MiniRange(lo: Double, hi: Double, v: Double, color: Color, modifier: Modifier = Modifier.fillMaxWidth().height(14.dp)) {
    Canvas(modifier) {
        val pad = 4.dp.toPx(); val cy = size.height / 2
        drawRoundRect(TRACK, Offset(pad, cy - 2.dp.toPx()), Size(size.width - 2 * pad, 4.dp.toPx()), CornerRadius(2.dp.toPx()))
        val x = ChartMath.lerp(v, lo, if (hi > lo) hi else lo + 1, pad, size.width - pad, clamp = true)
        drawCircle(C.card, 6.5.dp.toPx(), Offset(x, cy)); drawCircle(color, 4.5.dp.toPx(), Offset(x, cy))
    }
}

/** Two labelled horizontal bars on one scale (Stability: cash vs debt). */
@Composable
fun PairBars(rows: List<Triple<String, Double, Color>>, valueFmt: (Double) -> String) {
    val mx = rows.maxOfOrNull { it.second }?.takeIf { it > 0 } ?: 1.0
    rows.forEachIndexed { i, (label, v, c) ->
        Row(Modifier.fillMaxWidth().padding(top = if (i > 0) 10.dp else 0.dp, bottom = 4.dp)) {
            T(label, 12.sp, C.muted, modifier = Modifier.weight(1f), maxLines = 1); T(valueFmt(v), 12.sp, weight = FontWeight.Bold, maxLines = 1)
        }
        BoxWithConstraints(Modifier.fillMaxWidth().height(12.dp).clip(rr(6.dp)).background(TRACK)) {
            Box(Modifier.width((maxWidth * (v / mx).toFloat()).coerceAtLeast(6.dp)).fillMaxHeight().clip(rr(6.dp)).background(c))
        }
    }
}

/** Thin progress bar 0..1. */
@Composable
fun ProgressLine(frac: Float, color: Color = C.muted, modifier: Modifier = Modifier, height: Dp = 6.dp) {
    BoxWithConstraints(modifier.fillMaxWidth().height(height).clip(rr(height / 2)).background(TRACK)) {
        Box(Modifier.width(maxWidth * frac.coerceIn(0f, 1f)).fillMaxHeight().clip(rr(height / 2)).background(color))
    }
}

// ---------------------------------------------------------------- key checks (level tabs)
/** A filled bar under a key check: value on lo..hi, pass mark, scale [unit] ("%", "×", "th", " pts"). [higher] and [partly]
 *  are kept for the rule texts; the bar fills from the left and its colour carries the verdict. */
data class Bullet(val v: Double, val lo: Double, val hi: Double, val pass: Double, val higher: Boolean = true, val partly: Double? = null,
                  val unit: String = "")
/** One row of "Key checks": status word, short name, figure, pass line and optional bullet. */
data class KeyCheck(val status: String, val name: String, val figure: String, val pass: String? = null, val bullet: Bullet? = null)

/** " ✓" / " ✗" / " ~" after a figure, by status word. */
fun statusMark(status: String): String = when (status) { "Pass" -> " ✓"; "Miss" -> " ✗"; "Partly" -> " ~"; else -> "" }

/** A key check with a filled bar (feedback #83 option B): name, figure in the status colour with its mark, bar and scale row. */
@Composable
fun BarCheckRow(r: KeyCheck, b: Bullet, divider: Boolean = true) {
    val col = fillColor(r.status)
    Column(Modifier.fillMaxWidth()) {
        Column(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                T(r.name, 14.sp, modifier = Modifier.weight(1f), maxLines = 2, lineHeight = 18.sp)
                T(r.figure + statusMark(r.status), 15.sp, if (r.status == "n/a") C.white else col, FontWeight.Bold, maxLines = 1,
                    modifier = Modifier.padding(start = 8.dp))
            }
            FillBar(b.v, b.lo, b.hi, b.pass, col, Modifier.fillMaxWidth().padding(top = 8.dp), unit = b.unit)
            // extra context from the pass line ("pass ≥ 15% · avg 12.3%"): the part after the rule
            r.pass?.split(" · ")?.filter { !it.startsWith("pass") }?.joinToString(" · ")?.takeIf { it.isNotBlank() }?.let { T(cap(it), 12.sp, C.dim, maxLines = 1, modifier = Modifier.padding(top = 2.dp)) }
        }
        if (divider) HLineDivider()
    }
}

@Composable
fun KeyChecksCard(rows: List<KeyCheck>, total: Int, onAll: () -> Unit) {
    SectionCard("Key checks", more = "All $total checks with formulas", onMore = onAll) {
        if (Look.paper) { ZoneGrid(rows); return@SectionCard }
        rows.forEach { r ->
            val b = r.bullet
            if (b != null) BarCheckRow(r, b) else CheckRow(r.status, r.name, r.figure, r.pass)
        }
    }
}

/** When a tab's named checks are missing (other business kinds), the first scored items as they are. */
fun genericChecks(lv: Level, n: Int = 4): List<KeyCheck> = lv.items.filter { it.m != null }.take(n).map { i ->
    KeyCheck(statusOf(i.m), i.n, "", i.v?.let { if (it.length > 30) it.take(29) + "…" else it })
}

/** One check with its status word, figure and note (All checks sheet). Tap: formula or the filing. */
@Composable
fun CheckItemRow(item: Item, onClick: () -> Unit) {
    val uri = androidx.compose.ui.platform.LocalUriHandler.current
    Column(Modifier.fillMaxWidth().clickable(enabled = item.k != null || item.u != null) {
        if (item.k != null) onClick() else item.u?.let { runCatching { uri.openUri(it) } }
    }) {
        Row(Modifier.fillMaxWidth().padding(vertical = 9.dp), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatusChip(statusOf(item.m))
            Column(Modifier.weight(1f)) {
                T(item.n, 13.5.sp, if (item.m == null) C.muted else C.white, FontWeight.Medium, lineHeight = 18.sp)
                item.v?.let { T(it, 12.sp, if (item.k != null) C.blue else C.dim, lineHeight = 16.sp) }
                item.note?.let { T(it, 11.sp, C.dim, lineHeight = 15.sp) }
            }
            if (item.pts.size == 2) T("${fmt(item.pts[0], 0)}/${fmt(item.pts[1], 0)}", 11.sp, C.dim, maxLines = 1)
        }
        HLineDivider()
    }
}

// ---------------------------------------------------------------- Filings tab (s09)
private val FILING_BOILER = Regex("^.*?(has informed the Exchange|has submitted to the Exchange|has intimated the Exchange|informed the Exchange)\\s*(about|regarding|that|of|,)?\\s*", RegexOption.IGNORE_CASE)
private val RESULTS_RE = Regex("result|board meeting|presentation|con\\. ?call|analyst|investor meet|earnings", RegexOption.IGNORE_CASE)
private val INFO_DOT get() = TierC.grey  // routine filings: one grey for the strip, the legend and the list

/** Subject of a filing without the exchange boilerplate. */
fun filingSubject(e: Ev): String {
    var t = e.text.replace(FILING_BOILER, "").trim().trim('\'', '"', '.', ' ')
    t = t.replace(Regex("^(a copy of|the)\\s+", RegexOption.IGNORE_CASE), "").replace("'", "").replace("\"", "")
    return t.replaceFirstChar { it.uppercase() }.ifBlank { e.text }
}

/** Filings tab (feedback #86): "Filings | News" segmented control on top, then the filings list or the news headlines. */
@Composable
fun FilingsTab(det: Detail?) {
    var view by rememberSaveable { mutableIntStateOf(0) }
    FilingsNewsSwitch(view) { view = it }
    if (view == 1) NewsList(det) else FilingsList(det)
}

/** Two-option segmented control: C.chip track, the selected option on C.card in SemiBold. */
@Composable
private fun FilingsNewsSwitch(selected: Int, onSelect: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth().clip(rr(S.tile)).background(C.chip).padding(3.dp)) {
        listOf("Filings", "News").forEachIndexed { i, o ->
            Box(Modifier.weight(1f).clip(rr(S.inner)).background(if (i == selected) C.card else Color.Transparent)
                .clickable { onSelect(i) }.padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
                T(o, 13.sp, if (i == selected) C.white else C.dim, if (i == selected) FontWeight.SemiBold else FontWeight.Normal, maxLines = 1)
            }
        }
    }
}

/** News headlines matched by company name, last 30 days, newest first; tap opens the article. */
@Composable
private fun NewsList(det: Detail?) {
    val ctx = LocalContext.current
    val news = det?.news.orEmpty()
    if (det == null) { EmptyNote("Loading news…"); return }
    if (news.isEmpty()) {
        EmptyNote("No news headlines in the last 30 days. Headlines come from Economic Times, Business Standard, BusinessLine, Moneycontrol and Mint, matched by company name.")
        return
    }
    Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
        news.forEachIndexed { i, n ->
            Column(Modifier.fillMaxWidth().clickable(enabled = n.url != null) { n.url?.let { openUrl(ctx, it) } }.padding(vertical = 9.dp)) {
                T(n.title, 13.sp, C.white, FontWeight.Medium, maxLines = 2, lineHeight = 18.sp)
                T(listOfNotNull(n.source?.takeIf { it.isNotBlank() }, n.time?.let { skDay(it) }).joinToString(" · "), LABEL, C.dim, maxLines = 1,
                    modifier = Modifier.padding(top = 2.dp))
            }
            if (i < news.lastIndex) HLineDivider()
        }
    }
    T("Headlines matched by company name, last 30 days. Tap to open.", LABEL, C.dim, modifier = Modifier.padding(horizontal = 4.dp))
}

@Composable
private fun FilingsList(det: Detail?) {
    val ctx = LocalContext.current
    var filter by rememberSaveable { mutableStateOf("All") }
    var showAll by remember { mutableStateOf(false) }
    val evs = det?.stock?.events.orEmpty().distinctBy { Triple(it.date, it.category, it.text) }
    if (evs.isEmpty()) { EmptyNote(if (det == null) "Loading filings…" else "No filings in the store for this stock."); return }
    val today = skToday()
    val recentRed = evs.filter { it.sev == "red" && (skDate(it.date)?.let { d -> ChronoUnit.DAYS.between(d, today) <= 45 } ?: false) }
    val ordered = recentRed + evs.filter { it !in recentRed }
    val nRed = evs.count { it.sev == "red" }; val nWatch = evs.count { it.sev == "watch" }; val nGreen = evs.count { it.sev == "green" }
    val nRes = evs.count { RESULTS_RE.containsMatchIn(it.category ?: it.type) }
    val nInfo = evs.size - nRed - nWatch - nGreen
    // the legend and the filters use the same names, colours and counts; every group shows, zero or not
    val groups = listOf(Triple("Red flags", nRed, TierC.red), Triple("Watch", nWatch, C.amber), Triple("Orders & growth", nGreen, TierC.darkGreen),
        Triple("Routine", nInfo, INFO_DOT))
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        ToggleChip("All", filter == "All", { filter = "All" }, count = evs.size)
        groups.forEach { (g, n, c) -> ToggleChip(g, filter == g, { filter = g }, count = n, dot = c) }
        ToggleChip("Results", filter == "Results", { filter = "Results" }, count = nRes)
    }
    val shown = ordered.filter { e -> when (filter) { "Red flags" -> e.sev == "red"; "Watch" -> e.sev == "watch"; "Orders & growth" -> e.sev == "green"
        "Routine" -> e.sev !in setOf("red", "watch", "green"); "Results" -> RESULTS_RE.containsMatchIn(e.category ?: e.type); else -> true } }
    if (shown.isEmpty()) EmptyNote("None in this filter.")
    else Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
        val n = if (showAll) shown.size else minOf(11, shown.size)
        shown.take(n).forEachIndexed { i, e ->
            Row(Modifier.fillMaxWidth().clickable(enabled = e.url != null) { e.url?.let { openUrl(ctx, it) } }.padding(vertical = 8.dp),
                verticalAlignment = Alignment.Top) {
                Box(Modifier.padding(top = 6.dp).size(8.dp).clip(CircleShape).background(if (e.sev in setOf("red", "watch", "green")) sevColor(e.sev) else INFO_DOT))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    T(filingSubject(e), 13.5.sp, weight = FontWeight.Medium, maxLines = 1)
                    T("${skDay(e.date)} · ${e.category ?: e.type}", 11.sp, if (e.sev == "red" || e.sev == "watch") sevColor(e.sev) else C.dim, maxLines = 1)
                }
            }
            if (i < n - 1) HLineDivider()
        }
        if (shown.size > 11) Row(Modifier.clip(rr(S.inner)).clickable { showAll = !showAll }.padding(top = 8.dp, bottom = 2.dp),
            verticalAlignment = Alignment.CenterVertically) {
            T(if (showAll) "Show fewer" else "Show ${shown.size - 11} older", 13.sp, C.blue)
            Icon(Icons.Rounded.ExpandMore, null, tint = C.blue, modifier = Modifier.size(16.dp))
        }
    }
    // transcripts and presentations (exchange filings store), collapsed
    val fl = det?.stock?.exchange?.filings.orEmpty()
    if (fl.isNotEmpty()) {
        var open by remember { mutableStateOf(false) }
        Card(Modifier.fillMaxWidth(), pad = S.cardPad) {
            ToggleRow("Transcripts and presentations", "${fl.size}", open, { open = !open }, divider = false)
            if (open) fl.forEach { f ->
                HLineDivider()
                Column(Modifier.fillMaxWidth().clickable(enabled = f.url != null) { f.url?.let { openUrl(ctx, it) } }.padding(vertical = 8.dp)) {
                    T(f.text ?: "", 13.sp, maxLines = 2); T("${skDay(f.date)} · ${f.category ?: ""}", 11.sp, C.dim, maxLines = 1)
                }
            }
        }
    }
}

// ---------------------------------------------------------------- Claude's research sheet (Summary row)
@Composable
fun ResearchSheet(st: AppState, sym: String, det: Detail?, onDismiss: () -> Unit) {
    val scope = rememberCoroutineScope()
    val log = det?.researchLog.orEmpty()
    val first = det?.verdictLog?.firstOrNull()
    BottomSheet(onDismiss, "Narrativ.ai's research", aside = if (log.isEmpty()) null else "${log.size} entries") {
        if (log.isEmpty() && first == null) T("Narrativ.ai has not studied this stock yet.", 13.sp, C.dim, modifier = Modifier.padding(bottom = 10.dp))
        else SheetSection {
            log.forEachIndexed { i, e ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            T(e.kind, 14.sp, weight = FontWeight.SemiBold, maxLines = 1)
                            e.verdict?.let { v -> StatusChip(reviewWord(v), color = reviewColor(v), minWidth = 0.dp) }
                        }
                        if (e.text.isNotBlank()) T(e.text, 12.sp, C.dim)
                    }
                    T(skDay(e.date), 12.sp, C.dim, maxLines = 1)
                }
                if (i < log.lastIndex || first != null) HLineDivider()
            }
            first?.let { f ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { T("First rating", 14.sp, weight = FontWeight.SemiBold); T("${f.v} (rules)", 12.sp, C.dim) }
                    T(skDay(f.d), 12.sp, C.dim)
                }
            }
        }
        det?.scan?.next?.let { T("Next automatic refresh ${skDay(it)}, or after the next results filing", 11.sp, C.dim, modifier = Modifier.padding(bottom = 10.dp)) }
        // queue position: the one count every screen uses (Claude's pending review tasks, reviewState / queueLabel)
        val rv = reviewState(st, sym)
        val inQueue = rv.verdict == null && rv.pos != 0
        val requested = sym in st.requested
        if (inQueue || requested) SheetSection {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.HourglassTop, null, tint = C.grey, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                T(if (inQueue) "In Narrativ.ai's queue" else "Full review requested", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                StatusChip(if (inQueue) queueLabel(st, sym) ?: "Research queue" else "Not in queue yet", color = C.grey, minWidth = 0.dp)
            }
            T(if (rv.pos > 0) "Estimated: ${expectedRun(rv.pos)}, in the app about an hour after it starts (about 6 stocks a run)."
              else if (inQueue) "Queued for Narrativ.ai's research notes; a full review runs when the rules rate it Buy."
              else "Requests join the queue at the 17:10 daily run (weekdays) as full reviews; estimated the first research run after that.",
                12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 6.dp))
        }
        val days = skDate(rv.date)?.let { ChronoUnit.DAYS.between(it, skToday()) }
        val recent = days != null && days <= 7
        val enabled = !requested && !inQueue && !recent
        val label = when { requested || inQueue -> "Review queued"; recent -> "Reviewed ${skDay(rv.date)} · a new request opens after 7 days"
                           rv.verdict != null || rv.studied != null -> "Request a new full review"; else -> "Request a full review" }
        PrimaryButton(label, Modifier.padding(top = 4.dp).fillMaxWidth(), enabled = enabled) {
            scope.launch { st.toast = st.requestScan(sym).fold({ "Requested (#$it)" }, { "Not sent: ${it.message}" }) }
        }
    }
}

// ---------------------------------------------------------------- All ratios sheet (Summary row)
@Composable
fun RatiosSheet(det: Detail, onDismiss: () -> Unit, open: (String?) -> Unit) {
    BottomSheet(onDismiss, "Ratios and formulas", aside = det.str("source")) {
        if (det.standouts.good.isNotEmpty() || det.standouts.watch.isNotEmpty()) SheetSection("Strongest and weakest") {
            (det.standouts.good.map { it to TierC.lightGreen } + det.standouts.watch.map { it to C.amber }).forEach { (s, c) ->
                Row(Modifier.fillMaxWidth().clickable { open(s.k) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(c)); Spacer(Modifier.width(10.dp))
                    T(s.n, 13.sp, modifier = Modifier.weight(1f), maxLines = 1); T(s.v, 13.sp, weight = FontWeight.Bold, maxLines = 1)
                }
            }
        }
        val key = keyRatios(det)
        val rules = remember(det) { det.rulesByKey() }
        SheetSection("Key ratios") {
            key.forEachIndexed { i, (r, v) -> RatioRow(r.label, v, rules[r.key], divider = i < key.lastIndex) { open(r.key) } }
        }
        val shown = key.map { it.first.key }.toSet()
        val rest = METRIC_NAMES.keys.filter { it !in shown && det.m(it)?.v != null }
        if (rest.isNotEmpty()) SheetSection("Every computed figure", "${rest.size}") {
            rest.forEachIndexed { i, k ->
                val m = det.m(k)!!
                RatioRow(METRIC_NAMES[k] ?: k, if (m.nm) "n/m" else skFx(m.v, 2) + (if (k.endsWith("_pct")) "%" else "") + (m.u?.let { " $it" } ?: ""),
                    rules[k], divider = i < rest.lastIndex) { open(k) }
            }
        }
    }
}

/** A ratio with the rule that tests it (feedback #82): name and a 12sp dim rule line left, the value in the check's colour right. */
@Composable
fun RatioRow(label: String, value: String, rule: KeyRule?, divider: Boolean = true, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                T(label, 13.sp, C.muted, maxLines = 2)
                T(rule?.rule ?: "no rule", LABEL, C.dim, maxLines = 2)
            }
            Spacer(Modifier.width(10.dp))
            T(value, 13.sp, if (value == "n/m") C.white else ruleColor(rule), FontWeight.Bold, maxLines = 1)
        }
        if (divider) HLineDivider()
    }
}

// ---------------------------------------------------------------- key checks as zones (Paper, owner 26 Nov 2026)
/** The rule of a [Bullet] split into miss / partly / pass ranges, low to high. */
internal fun bulletZones(b: Bullet): List<Triple<Double, Double, String>> {
    val pt = b.partly
    return if (b.higher) {
        if (pt != null) listOf(Triple(b.lo, pt, "Miss"), Triple(pt, b.pass, "Partly"), Triple(b.pass, b.hi, "Pass"))
        else listOf(Triple(b.lo, b.pass, "Miss"), Triple(b.pass, b.hi, "Pass"))
    } else {
        if (pt != null) listOf(Triple(b.lo, b.pass, "Pass"), Triple(b.pass, pt, "Partly"), Triple(pt, b.hi, "Miss"))
        else listOf(Triple(b.lo, b.pass, "Pass"), Triple(b.pass, b.hi, "Miss"))
    }.filter { it.second > it.first }
}

/** Top key checks two by two: name, figure in its verdict colour, and the rule's zones with the value marked. */
@Composable
fun ZoneGrid(rows: List<KeyCheck>) {
    rows.chunked(2).forEachIndexed { ri, pair ->
        if (ri > 0) HLineDivider()
        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
            ZoneCell(pair[0], Modifier.weight(1f).padding(end = 8.dp))
            Box(Modifier.width(1.dp).fillMaxHeight().padding(vertical = 6.dp).background(C.line))
            if (pair.size > 1) ZoneCell(pair[1], Modifier.weight(1f).padding(start = 8.dp)) else Spacer(Modifier.weight(1f))
        }
    }
}

@Composable
private fun ZoneCell(r: KeyCheck, modifier: Modifier) {
    val col = if (r.status == "n/a") C.white else fillColor(r.status)
    Column(modifier.padding(vertical = 9.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
        T(r.name, 12.sp, maxLines = 2, lineHeight = 15.sp, modifier = Modifier.heightIn(min = 30.dp))
        androidx.compose.material3.Text(r.figure + statusMark(r.status), fontSize = 20.sp, lineHeight = 23.sp, color = col,
            fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1)
        val b = r.bullet
        if (b != null) ZoneBar(b, Modifier.fillMaxWidth().height(40.dp))
        // the rest of the pass line ("pass ≥ 15% · avg 13.5%"): the part after the rule; without a bar, the whole line
        val note = if (b != null) r.pass?.split(" · ")?.filter { !it.startsWith("pass") }?.joinToString(" · ") else r.pass
        note?.takeIf { it.isNotBlank() }?.let { T(cap(it), 10.sp, C.dim, maxLines = 2, lineHeight = 13.sp) }
    }
}

/** Zones of the rule (miss / partly / pass); the one holding the value is solid, ▼ marks the value; thresholds under the bar. */
@Composable
private fun ZoneBar(b: Bullet, modifier: Modifier) {
    val tm = androidx.compose.ui.text.rememberTextMeasurer()
    val zones = bulletZones(b)
    val v = b.v.coerceIn(b.lo, b.hi)
    val inZone = zones.firstOrNull { v >= it.first && v <= it.second }?.third ?: zones.lastOrNull()?.third
    val ink = C.white; val dim = C.dim
    val zc = zones.map { fillColor(it.third) }
    Canvas(modifier) {
        val span = (b.hi - b.lo).takeIf { it > 0 } ?: 1.0
        fun x(t: Double) = ((t - b.lo) / span * size.width).toFloat()
        val barY = 13.dp.toPx(); val bh = 9.dp.toPx(); val gap = 1.dp.toPx()
        zones.forEachIndexed { i, z ->
            val x0 = x(z.first) + if (i > 0) gap / 2 else 0f; val x1 = x(z.second) - if (i < zones.size - 1) gap / 2 else 0f
            drawRect(zc[i].copy(alpha = if (z.third == inZone) 0.9f else 0.22f), Offset(x0, barY), Size((x1 - x0).coerceAtLeast(1f), bh))
        }
        val mx = x(v).coerceIn(5.dp.toPx(), size.width - 5.dp.toPx())
        val m = tm.measure("▼", androidx.compose.ui.text.TextStyle(fontSize = 10.sp, color = ink))
        drawText(m, topLeft = Offset(mx - m.size.width / 2f, barY - m.size.height + 1.dp.toPx()))
        // thresholds under the bar; when two sit too close, the pass line wins (it is the rule) and the other is left out
        val labs = zones.drop(1).map { z ->
            val t = tm.measure(scaleNum(z.first, b.unit), androidx.compose.ui.text.TextStyle(fontSize = 9.sp, color = dim, fontFamily = PaperFonts.label))
            Triple(t, (x(z.first) - t.size.width / 2f).coerceIn(0f, size.width - t.size.width), z.first == b.pass)
        }
        val tight = labs.size == 2 && labs[0].second + labs[0].first.size.width + 4.dp.toPx() > labs[1].second
        labs.filter { !tight || it.third }.forEach { (t, tx, _) -> drawText(t, topLeft = Offset(tx, barY + bh + 2.dp.toPx())) }
    }
}
