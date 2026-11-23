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
 * stock tabs, the Filings tab (s09) and the sheets behind the Summary rows (Claude's research, all ratios). These replace
 * StockParts.kt's ResearchSection and AnnouncementsPage for the stock page (the old ones stay until the lead removes them).
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


// ---------------------------------------------------------------- small UI pieces
/** Chip with coloured text and no dot ("1M +11.0%", "vs 200-day −5.2%"). */
@Composable
fun ValChip(text: String, color: Color = C.muted, modifier: Modifier = Modifier) {
    Box(modifier.clip(RoundedCornerShape(9.dp)).background(Color.White.copy(alpha = 0.063f)).padding(horizontal = 8.dp, vertical = 3.dp)) {
        T(text, 11.sp, color, maxLines = 1)
    }
}

/** Empty state inside the page padding. */
@Composable
fun EmptyNote(text: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().clip(RoundedCornerShape(S.card)).background(C.card).padding(16.dp)) { T(text, 13.sp, C.dim, lineHeight = 18.sp) }
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
        BoxWithConstraints(Modifier.fillMaxWidth().height(12.dp).clip(RoundedCornerShape(6.dp)).background(Color.White.copy(alpha = 0.07f))) {
            Box(Modifier.width((maxWidth * (v / mx).toFloat()).coerceAtLeast(6.dp)).fillMaxHeight().clip(RoundedCornerShape(6.dp)).background(c))
        }
    }
}

/** Thin progress bar 0..1. */
@Composable
fun ProgressLine(frac: Float, color: Color = C.teal, modifier: Modifier = Modifier, height: Dp = 6.dp) {
    BoxWithConstraints(modifier.fillMaxWidth().height(height).clip(RoundedCornerShape(height / 2)).background(TRACK)) {
        Box(Modifier.width(maxWidth * frac.coerceIn(0f, 1f)).fillMaxHeight().clip(RoundedCornerShape(height / 2)).background(color))
    }
}

// ---------------------------------------------------------------- key checks (level tabs)
/** A bullet bar under a key check: value on lo..hi, pass line, optional partly line. */
data class Bullet(val v: Double, val lo: Double, val hi: Double, val pass: Double, val higher: Boolean = true, val partly: Double? = null)
/** One row of "Key checks": status word, short name, figure, pass line and optional bullet. */
data class KeyCheck(val status: String, val name: String, val figure: String, val pass: String? = null, val bullet: Bullet? = null)

@Composable
fun KeyChecksCard(rows: List<KeyCheck>, total: Int, onAll: () -> Unit) {
    SectionCard("Key checks", more = "All $total checks with formulas", onMore = onAll) {
        rows.forEach { r ->
            CheckRow(r.status, r.name, r.figure, r.pass, bullet = r.bullet?.let { b ->
                { BulletBar(b.v, b.lo, b.hi, b.pass, statusColor(r.status), higherIsBetter = b.higher, partly = b.partly) }
            })
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
private val INFO_DOT = Color(0xFF7A7F86)

/** Subject of a filing without the exchange boilerplate. */
fun filingSubject(e: Ev): String {
    var t = e.text.replace(FILING_BOILER, "").trim().trim('\'', '"', '.', ' ')
    t = t.replace(Regex("^(a copy of|the)\\s+", RegexOption.IGNORE_CASE), "").replace("'", "").replace("\"", "")
    return t.replaceFirstChar { it.uppercase() }.ifBlank { e.text }
}

private fun sevRank(s: String) = when (s) { "red" -> 3; "watch" -> 2; "green" -> 1; else -> 0 }

@Composable
fun FilingsTab(det: Detail?) {
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
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        ToggleChip("All", filter == "All", { filter = "All" }, count = evs.size)
        ToggleChip("Red flags", filter == "Red flags", { filter = "Red flags" }, count = nRed)
        if (nWatch > 0) ToggleChip("Watch", filter == "Watch", { filter = "Watch" }, count = nWatch, dot = C.amber)
        ToggleChip("Orders & growth", filter == "Orders & growth", { filter = "Orders & growth" }, count = nGreen)
        ToggleChip("Results", filter == "Results", { filter = "Results" }, count = nRes)
    }
    val dates = evs.mapNotNull { e -> skDate(e.date)?.let { it to e } }
    if (dates.isNotEmpty()) Card(Modifier.fillMaxWidth(), pad = 12.dp) {
        val start = dates.minOf { it.first }.withDayOfMonth(1)
        DotStrip(dates.sortedBy { sevRank(it.second.sev) }.map { (d, e) -> StripDot(d, if (e.sev == "info") INFO_DOT else sevColor(e.sev)) },
            start, maxOf(today, start.plusDays(1)), window = 45, windowLabel = "45 days")
        FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            DotChip("Red $nRed", TierC.red)
            if (nWatch > 0) DotChip("Watch $nWatch", C.amber)
            DotChip("Growth $nGreen", TierC.darkGreen)
            DotChip("Routine ${evs.size - nRed - nWatch - nGreen}", INFO_DOT)
        }
    }
    val shown = ordered.filter { e -> when (filter) { "Red flags" -> e.sev == "red"; "Watch" -> e.sev == "watch"; "Orders & growth" -> e.sev == "green"
        "Results" -> RESULTS_RE.containsMatchIn(e.category ?: e.type); else -> true } }
    if (shown.isEmpty()) EmptyNote("None in this filter.")
    else Card(Modifier.fillMaxWidth(), pad = 14.dp) {
        val n = if (showAll) shown.size else minOf(11, shown.size)
        shown.take(n).forEachIndexed { i, e ->
            Row(Modifier.fillMaxWidth().clickable(enabled = e.url != null) { e.url?.let { openUrl(ctx, it) } }.padding(vertical = 8.dp),
                verticalAlignment = Alignment.Top) {
                Box(Modifier.padding(top = 6.dp).size(8.dp).clip(CircleShape).background(if (e.sev == "info") Color(0xFF5C6066) else sevColor(e.sev)))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    T(filingSubject(e), 13.5.sp, weight = FontWeight.Medium, maxLines = 1)
                    T("${skDay(e.date)} · ${e.category ?: e.type}", 11.sp, if (e.sev == "red" || e.sev == "watch") sevColor(e.sev) else C.dim, maxLines = 1)
                }
            }
            if (i < n - 1) HLineDivider()
        }
        if (shown.size > 11) Row(Modifier.clip(RoundedCornerShape(8.dp)).clickable { showAll = !showAll }.padding(top = 8.dp, bottom = 2.dp),
            verticalAlignment = Alignment.CenterVertically) {
            T(if (showAll) "Show fewer" else "Show ${shown.size - 11} older", 13.sp, C.blue)
            Icon(Icons.Rounded.ExpandMore, null, tint = C.blue, modifier = Modifier.size(16.dp))
        }
    }
    // transcripts and presentations (exchange filings store), collapsed
    val fl = det?.stock?.exchange?.filings.orEmpty()
    if (fl.isNotEmpty()) {
        var open by remember { mutableStateOf(false) }
        Card(Modifier.fillMaxWidth(), pad = 14.dp) {
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
    BottomSheet(onDismiss, "Claude's research", aside = if (log.isEmpty()) null else "${log.size} entries") {
        if (log.isEmpty() && first == null) T("Claude has not studied this stock yet.", 13.sp, C.dim, modifier = Modifier.padding(bottom = 10.dp))
        else SheetSection {
            log.forEachIndexed { i, e ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            T(e.kind, 14.sp, weight = FontWeight.SemiBold, maxLines = 1)
                            e.verdict?.let { v -> StatusChip(v.uppercase(), color = reviewColor(v), minWidth = 0.dp) }
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
        val inQueue = st.queue?.items.orEmpty().let { q ->
            val today = skToday().toString()
            val left = q.filter { st.research[it.symbol]?.updated != today }
            val i = left.indexOfFirst { it.symbol == sym }
            if (i >= 0) (i + 1) to left.size else null
        }
        val requested = sym in st.requested
        if (inQueue != null || requested) SheetSection {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.HourglassTop, null, tint = if (inQueue != null) C.teal else C.dim, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                T(if (inQueue != null) "In Claude's queue" else "Full review requested", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                StatusChip(if (inQueue != null) "#${inQueue.first} of ${inQueue.second}" else "not in queue yet", color = if (inQueue != null) C.blue else C.dim)
            }
            T(if (inQueue != null) "Estimated: ${expectedRun(inQueue.first)}, in the app about an hour after it starts (about 6 stocks a run)."
              else "Requests join the queue at the 17:10 daily run (weekdays) as full reviews; estimated the first research run after that.",
                12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 6.dp))
        }
        val rv = reviewState(st, sym)
        val days = skDate(rv.date)?.let { ChronoUnit.DAYS.between(it, skToday()) }
        val recent = days != null && days <= 7
        val enabled = !requested && inQueue == null && !recent
        val label = when { requested || inQueue != null -> "Review queued"; recent -> "Reviewed ${skDay(rv.date)} · a new request opens after 7 days"
                           rv.verdict != null || rv.studied != null -> "Request a new full review"; else -> "Request a full review" }
        Box(Modifier.padding(top = 4.dp).fillMaxWidth().height(48.dp).clip(RoundedCornerShape(24.dp)).background(if (enabled) C.teal else C.chip)
            .clickable(enabled = enabled) { scope.launch { st.toast = st.requestScan(sym).fold({ "Requested (#$it)" }, { "Not sent: ${it.message}" }) } },
            contentAlignment = Alignment.Center) { T(label, 14.sp, if (enabled) Color.Black else C.dim, FontWeight.SemiBold, maxLines = 1) }
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
        SheetSection("Key ratios") {
            key.forEachIndexed { i, (r, v) -> KvRow(r.label, v, divider = i < key.lastIndex, onClick = { open(r.key) }) }
        }
        val shown = key.map { it.first.key }.toSet()
        val rest = METRIC_NAMES.keys.filter { it !in shown && det.m(it)?.v != null }
        if (rest.isNotEmpty()) SheetSection("Every computed figure", "${rest.size}") {
            rest.forEachIndexed { i, k ->
                val m = det.m(k)!!
                KvRow(METRIC_NAMES[k] ?: k, if (m.nm) "n/m" else fmt(m.v, 2) + (if (k.endsWith("_pct")) "%" else "") + (m.u?.let { " $it" } ?: ""),
                    divider = i < rest.lastIndex, onClick = { open(k) })
            }
        }
    }
}
