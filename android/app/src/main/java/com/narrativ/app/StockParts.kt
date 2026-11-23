@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

// ---------------------------------------------------------------- sector / industry rotation
/** Industry (as in the app) -> NSE sector index tracked in rotation.json. Industries without a matching index show the industry only. */
val SECTOR_OF = mapOf(
    "IT - Software" to "IT", "IT - Services" to "IT", "IT - Hardware" to "IT",
    "Auto Components" to "Auto", "Automobiles" to "Auto", "Agricultural, Commercial & Construction Vehicles" to "Auto",
    "Pharmaceuticals & Biotechnology" to "Pharma",
    "Food Products" to "FMCG", "Beverages" to "FMCG", "Personal Products" to "FMCG", "Household Products" to "FMCG",
    "Diversified FMCG" to "FMCG", "Agricultural Food & other Products" to "FMCG",
    "Ferrous Metals" to "Metal", "Non - Ferrous Metals" to "Metal", "Minerals & Mining" to "Metal", "Metals & Minerals Trading" to "Metal",
    "Realty" to "Realty",
    "Oil" to "Energy", "Gas" to "Energy", "Petroleum Products" to "Energy", "Power" to "Energy",
    "Banks" to "Bank",
    "Construction" to "Infra", "Cement & Cement Products" to "Infra", "Transport Infrastructure" to "Infra", "Telecom - Services" to "Infra",
    "Finance" to "Fin Services", "Capital Markets" to "Fin Services", "Insurance" to "Fin Services", "Financial Technology (Fintech)" to "Fin Services",
    "Consumer Durables" to "Consumption", "Retailing" to "Consumption", "Leisure Services" to "Consumption", "Entertainment" to "Consumption",
)

fun quadColor(q: String?): Color = when (q) { "Leading" -> TierC.darkGreen; "Improving" -> C.blue; "Weakening" -> C.amber; "Lagging" -> TierC.red; else -> C.grey }
fun quadIcon(q: String?): String = when (q) { "Leading" -> "▲"; "Improving" -> "↗"; "Weakening" -> "↘"; "Lagging" -> "▼"; else -> "–" }

@Composable
private fun RotCell(title: String, q: String?, line: String?, modifier: Modifier) {
    Column(modifier) {
        T(title, 10.sp, C.dim, maxLines = 2, lineHeight = 12.sp)
        T("${quadIcon(q)} ${q ?: "Not enough data"}", 15.sp, quadColor(q), FontWeight.SemiBold, modifier = Modifier.padding(top = 2.dp))
        line?.let { T(it, 11.sp, C.grey, maxLines = 1) }
    }
}

// ---------------------------------------------------------------- summary card (decision + Claude + score) and its sheet
@Composable
fun SummaryChip(st: AppState, sym: String, p: P?, det: Detail?, onOpen: () -> Unit) {
    val dd = det?.decision ?: p?.dc?.let { Decision(it) }
    val rv = reviewState(st, sym)
    // the decision is the main thing on the page (#7, #10); captions replaced by the values themselves (#2)
    val dcol = decisionColor(dd?.d ?: "")
    Column(Modifier.fillMaxWidth().padding(top = 12.dp).clip(RoundedCornerShape(S.card)).background(dcol.copy(alpha = 0.12f))
        .clickable(onClick = onOpen).padding(16.dp)) {
        T((dd?.d ?: "–").uppercase(), 28.sp, dcol, FontWeight.ExtraBold, maxLines = 1)
        val (claude, ccol) = when {
            rv.verdict == "pass" -> "✓ Claude passed the full review" + (rv.date?.let { " · ${shortDate(it)}" } ?: "") to reviewColor("pass")
            rv.verdict != null -> "Claude's review: ${rv.verdict}" + (rv.date?.let { " · ${shortDate(it)}" } ?: "") to reviewColor(rv.verdict)
            rv.pos > 0 -> "Queued #${rv.pos} for Claude's full review" to C.grey
            rv.pos != 0 -> "In Claude's research queue" to C.grey
            rv.studied != null -> "Claude's notes only, no full review yet" to C.grey
            else -> "Rules only: not studied by Claude" to C.grey
        }
        T(claude, 14.sp, ccol, maxLines = 2, modifier = Modifier.padding(top = 2.dp))
        // one line from the decision's own reasons: forward evidence first, then valuation and momentum
        val why = dd?.why.orEmpty()
        val fwd = why.filter { it.startsWith("Order:") || it.startsWith("Guidance") || it.startsWith("Driver") }.take(2).map { it.substringAfter(": ").trimEnd('.') }
        val line = if (fwd.isNotEmpty()) fwd.joinToString("; ") + "." else why.filter { it.startsWith("Momentum:") || it.startsWith("Quality:") }.take(2).joinToString(" · ")
        if (line.isNotBlank()) T(line, 14.sp, C.white, maxLines = 4, lineHeight = 20.sp, modifier = Modifier.padding(top = 10.dp))
        val rank = st.picks?.top10?.indexOf(sym)?.takeIf { it >= 0 }
        Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
            T("Score ${p?.let { fmt(it.pr, 0) } ?: "–"}", 13.sp, C.grey)
            rank?.let { T("Rank #${it + 1} in Top 10", 13.sp, C.grey) }
            Spacer(Modifier.weight(1f)); T("Details ›", 13.sp, C.teal)
        }
        if (p?.mb == true) Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Rounded.RocketLaunch, null, tint = TierC.yellow, modifier = Modifier.size(14.dp)); Spacer(Modifier.width(6.dp))
            T("Multibagger potential: under ₹10,000 cr, undiscovered, growing 20%+, ROCE 15%+, dated trigger, undervalued", 11.sp, TierC.yellow, maxLines = 2)
        }
        // sector and industry: leading or not
        val ind = p?.i ?: det?.stock?.industry
        val secKey = ind?.let { SECTOR_OF[it] }
        val sec = secKey?.let { st.rotation?.sectors?.get(it) }
        val ir = ind?.let { st.rotation?.industries?.get(it) }
        val wind = det?.levels?.get("out")?.wind
        if (sec != null || ir != null || wind != null) {
            Spacer(Modifier.height(14.dp))  // grouped by spacing, not lines (#8)
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                if (sec != null) {
                    RotCell("SECTOR · NIFTY ${(secKey ?: "").uppercase()}", sec.q, "1M ${pctStr(sec.r1m)} · 3M ${pctStr(sec.r3m)}", Modifier.weight(1f))
                }
                RotCell("INDUSTRY · ${(ind ?: "–").uppercase()}", ir?.q ?: det?.stock?.rotation,
                    listOfNotNull(wind, ir?.r1m?.let { "1M ${pctStr(it)}" }).joinToString(" · ").ifBlank { null }, Modifier.weight(1f))
            }
        }
    }
}

@Composable
fun DecisionSheet(onClose: () -> Unit, content: @Composable () -> Unit) {
    ModalBottomSheet(onDismissRequest = onClose, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = C.bg) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 28.dp).verticalScroll(rememberScrollState())) { content() }
    }
}

// ---------------------------------------------------------------- 52-week range (on top of the chart)
@Composable
fun RangeBar(price: Double?, lo: Double?, hi: Double?) {
    if (price == null || lo == null || hi == null || hi <= lo) return
    val f = ((price - lo) / (hi - lo)).coerceIn(0.0, 1.0).toFloat()
    Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column { T("52W LOW", 10.sp, C.dim); T("₹${fmt(lo, 1)}", 14.sp, weight = FontWeight.SemiBold) }
        BoxWithConstraints(Modifier.weight(1f).padding(horizontal = 12.dp).height(36.dp)) {
            val w = maxWidth
            Box(Modifier.align(Alignment.TopStart).padding(top = 6.dp).fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp))
                .background(Brush.horizontalGradient(listOf(TierC.red, TierC.yellow, TierC.darkGreen))))
            Box(Modifier.offset(x = (w * f - 2.dp).coerceIn(0.dp, w - 4.dp)).width(4.dp).height(18.dp).clip(RoundedCornerShape(2.dp)).background(Color.White))
            val below = (1 - price / hi) * 100
            T(if (below < 0.5) "at the 52-week high" else "${fmt(below, 0)}% below high", 11.sp, C.white,
                modifier = Modifier.align(Alignment.BottomCenter))
        }
        Column(horizontalAlignment = Alignment.End) { T("52W HIGH", 10.sp, C.dim); T("₹${fmt(hi, 1)}", 14.sp, weight = FontWeight.SemiBold) }
    }
}

// ---------------------------------------------------------------- trade setup: plain names, drawn as a price line
fun setupName(type: String?, note: String?): String = when (type) {
    "Breakout" -> "Breaking out"; "Pullback" -> "Dip in uptrend"; "Base" -> "Bottoming out"
    "No setup" -> if (note?.startsWith("No entry: trend broken") == true) "Avoid" else "Wait"
    else -> "No data"
}

private fun setupLine(type: String?, note: String?): String = when (type) {
    "Breakout" -> "price pushing above its 55-day high"
    "Pullback" -> "rising stock dipped to its short-term averages"
    "Base" -> "after a fall, price resting near its recent low"
    "No setup" -> if (note?.startsWith("No entry: trend broken") == true) "trend broken: below the 200-day average" else if (note?.startsWith("Extended") == true) "price ran too far above its averages" else "not at a buy point today"
    else -> "not enough price history"
}

private data class LadderMark(val v: Double, val col: Color, val label: String, val up: Boolean, val now: Boolean = false)

/** Horizontal price line: zones as bands, levels as ticks, labels alternating above and below. */
@Composable
private fun PriceLadder(marks: List<LadderMark>, zones: List<Triple<Double, Double, Color>>, zoneLabel: List<Pair<String, Color>>) {
    val all = marks.map { it.v } + zones.flatMap { listOf(it.first, it.second) }
    if (all.size < 2) return
    val lo = all.min(); val hi = all.max(); val pad = (hi - lo) * 0.06 + 0.01
    val a = lo - pad; val b = hi + pad
    BoxWithConstraints(Modifier.fillMaxWidth().padding(vertical = 8.dp).height(96.dp)) {
        val w = maxWidth
        fun x(v: Double): Dp = w * ((v - a) / (b - a)).toFloat()
        Box(Modifier.offset(y = 44.dp).fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(C.chip))
        zones.forEachIndexed { i, (z1, z2, c) ->
            Box(Modifier.offset(x = x(z1), y = 40.dp).width((x(z2) - x(z1)).coerceAtLeast(6.dp)).height(14.dp).clip(RoundedCornerShape(4.dp))
                .background(c.copy(alpha = 0.45f)).border(1.dp, c, RoundedCornerShape(4.dp)))
            zoneLabel.getOrNull(i)?.let { (t, col) -> LadderLabel(t, col, x((z1 + z2) / 2), w, up = false) }
        }
        marks.forEach { m ->
            Box(Modifier.offset(x = x(m.v) - 1.5.dp, y = if (m.now) 32.dp else 36.dp).width(if (m.now) 4.dp else 3.dp).height(if (m.now) 30.dp else 22.dp)
                .clip(RoundedCornerShape(2.dp)).background(m.col))
            LadderLabel(m.label, m.col, x(m.v), w, m.up)
        }
    }
}

@Composable
private fun LadderLabel(t: String, col: Color, cx: Dp, w: Dp, up: Boolean) {
    val lw = 92.dp
    Box(Modifier.offset(x = (cx - lw / 2).coerceIn(0.dp, w - lw), y = if (up) 0.dp else 64.dp).width(lw)) {
        T(t, 10.sp, col, lineHeight = 13.sp, modifier = Modifier.fillMaxWidth(), align = TextAlign.Center)
    }
}

@Composable
private fun Step(badge: String, col: Color, text: String) {
    Row(Modifier.padding(top = 9.dp), verticalAlignment = Alignment.Top) {
        Box(Modifier.size(20.dp).clip(CircleShape).background(col), contentAlignment = Alignment.Center) { T(badge, 11.sp, Color.Black, FontWeight.Bold) }
        Spacer(Modifier.width(10.dp)); T(text, 13.sp, Color(0xFFDFE3E6), lineHeight = 18.sp)
    }
}

@Composable
fun SetupCard(s: Setup, a: Analyst?, price: Double?) {
    SectionHeader2("Trade setup", "From price rules · not advice")
    Card(Modifier.fillMaxWidth()) {
        val name = setupName(s.type, s.note)
        val col = when (name) { "Breaking out" -> C.teal; "Dip in uptrend" -> C.blue; "Bottoming out" -> TierC.yellow; "Avoid" -> TierC.red; else -> C.grey }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.clip(RoundedCornerShape(10.dp)).background(col.copy(alpha = 0.16f)).padding(horizontal = 10.dp, vertical = 3.dp)) { T(name, 13.sp, col, FontWeight.Bold) }
            Spacer(Modifier.width(8.dp)); T(setupLine(s.type, s.note), 12.sp, C.grey, modifier = Modifier.weight(1f), maxLines = 2)
        }
        val tgt = a?.mean?.takeIf { it > 0 }
        val px = price
        if (s.lo != null && s.hi != null) {
            val marks = buildList {
                s.stop?.let { add(LadderMark(it, TierC.red, "Exit\n₹${fmt(it, 0)}", up = true)) }
                s.add?.let { add(LadderMark(it, C.blue, "Buy rest\nabove ₹${fmt(it, 0)}", up = true)) }
                px?.let { add(LadderMark(it, Color.White, "Now\n₹${fmt(it, 0)}", up = false, now = true)) }
                tgt?.takeIf { it > s.hi }?.let { add(LadderMark(it, C.grey, "Analyst\n₹${fmt(it, 0)}", up = true)) }
            }
            val zl = if (s.type == "Base") "Buy part 1" else "Buy zone"
            PriceLadder(marks, listOf(Triple(s.lo, s.hi, TierC.darkGreen)), listOf("$zl\n₹${fmt(s.lo, 0)}–${fmt(s.hi, 0)}" to TierC.darkGreen))
            when (s.type) {
                "Base" -> {
                    Step("1", TierC.darkGreen, "Buy a first part between ₹${fmt(s.lo, 0)} and ₹${fmt(s.hi, 0)} (near the 20-day low).")
                    s.add?.let { ad -> Step("2", C.blue, "Buy the rest once it closes above ₹${fmt(ad, 0)} (50-day average): the uptrend is back." +
                        (px?.let { if (it > ad) " Now ₹${fmt(it, 0)}: already above." else "" } ?: "")) }
                }
                "Breakout" -> Step("1", TierC.darkGreen, "Buy on a close above ₹${fmt(s.lo, 0)} (55-day high), up to ₹${fmt(s.hi, 0)} (+5%).")
                else -> Step("1", TierC.darkGreen, "Buy between ₹${fmt(s.lo, 0)} and ₹${fmt(s.hi, 0)} (10–21 day averages).")
            }
            s.stop?.let { st -> Step("!", TierC.red, "Exit if it closes below ₹${fmt(st, 0)}" + (px?.let { " (${pctStr((st / it - 1) * 100)} from now)." } ?: ".")) }
            if (tgt != null) {
                val up = px?.let { (tgt / it - 1) * 100 }
                Step("↗", C.grey, "${a?.n ?: "?"} analyst target${if ((a?.n ?: 0) > 1) "s, average" else ""} ₹${fmt(tgt, 0)}" + (up?.let { " (${pctStr(it)})" } ?: "") +
                    (when { s.rrNote == "Above analyst target" -> ". The buy zone is above it: no upside to the target."
                            s.rr != null -> ". Upside is ${fmt(s.rr, 1)}× the risk to the exit."; else -> "." }))
            }
        } else if (s.watchLo != null && s.watchHi != null) {
            val marks = buildList {
                s.sma50?.let { add(LadderMark(it, C.amber, "50-day avg\n₹${fmt(it, 0)}", up = true)) }
                px?.let { add(LadderMark(it, Color.White, "Now\n₹${fmt(it, 0)}", up = false, now = true)) }
            }
            PriceLadder(marks, listOf(Triple(s.watchLo, s.watchHi, C.blue)), listOf("Buy on a dip\n₹${fmt(s.watchLo, 0)}–${fmt(s.watchHi, 0)}" to C.blue))
            px?.let { p0 ->
                val d1 = (p0 / s.watchHi - 1) * 100; val d2 = (p0 / s.watchLo - 1) * 100
                Step("1", C.blue, if (p0 > s.watchHi) "Price is ${fmt(d1, 0)}–${fmt(d2, 0)}% above its usual dip zone. Buy if it pulls back to ₹${fmt(s.watchLo, 0)}–${fmt(s.watchHi, 0)} (10–21 day averages)."
                    else "Price is at or below its dip zone ₹${fmt(s.watchLo, 0)}–${fmt(s.watchHi, 0)} (10–21 day averages); wait for a setup to form.")
            }
            s.sma50?.let { Step("!", C.amber, "A close below ₹${fmt(it, 0)} (50-day average) weakens the uptrend.") }
        } else T(s.note ?: "No buy zone.", 12.sp, C.grey, modifier = Modifier.padding(top = 8.dp))
    }
}

// ---------------------------------------------------------------- Claude's research history + scan request
@Composable
fun ResearchSection(st: AppState, sym: String, det: Detail?, p: P?) {
    val scope = rememberCoroutineScope()
    val log = det?.researchLog.orEmpty()
    val first = det?.verdictLog?.firstOrNull()
    SectionHeader2("Claude's research", "Every scan and review of this stock")
    if (log.isEmpty() && first == null) Empty("Claude has not studied this stock yet.")
    else Card(Modifier.fillMaxWidth(), pad = 6.dp) {
        log.forEachIndexed { i, e ->
            Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        T(e.kind, 14.sp, weight = FontWeight.SemiBold)
                        e.verdict?.let { v -> Spacer(Modifier.width(6.dp)); TierChip(v.uppercase(), reviewColor(v), 10.sp) }
                    }
                    if (e.text.isNotBlank()) T(e.text, 12.sp, C.grey)
                }
                T(shortDate(e.date), 12.sp, C.grey)
            }
            if (i < log.lastIndex || first != null) Box(Modifier.fillMaxWidth().height(1.dp).background(C.line))
        }
        first?.let { f ->
            Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { T("First rating", 14.sp, weight = FontWeight.SemiBold); T("${f.v} (rules)", 12.sp, C.grey) }
                T(shortDate(f.d), 12.sp, C.grey)
            }
        }
    }
    det?.scan?.next?.let { T("Next automatic refresh: ${shortDate(it)}, or after the next results filing", 11.sp, C.dim, modifier = Modifier.padding(top = 4.dp, start = 4.dp)) }
    // a request: position in Claude's queue and an estimate
    val inQueue = st.queue?.items.orEmpty().let { q ->
        val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
        val left = q.filter { st.research[it.symbol]?.updated != today }
        val i = left.indexOfFirst { it.symbol == sym }
        if (i >= 0) (i + 1) to left.size else null
    }
    val requested = sym in st.requested
    if (inQueue != null || requested) {
        Card(Modifier.fillMaxWidth().padding(top = 12.dp)) {
            if (inQueue != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.HourglassTop, null, tint = C.teal, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                    T("In Claude's queue", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    TierChip("#${inQueue.first} of ${inQueue.second}", C.teal, 11.sp)
                }
                T("Estimated: ${expectedRun(inQueue.first)}, in the app about an hour after it starts (about 6 stocks a run).", 12.sp, C.grey,
                    lineHeight = 17.sp, modifier = Modifier.padding(top = 6.dp))
            } else {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.HourglassTop, null, tint = C.grey, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                    T("Full review requested", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    TierChip("not in queue yet", C.grey, 11.sp)
                }
                T("Requests join the queue at the 17:10 daily run (weekdays) as full reviews, ahead of other work. Estimated: the first research run after that (18:05 on a weekday).",
                    12.sp, C.grey, lineHeight = 17.sp, modifier = Modifier.padding(top = 6.dp))
            }
        }
    }
    // a request is a full review (pipeline: run.py requested -> task "review"); one a week per stock
    val rv = reviewState(st, sym)
    val reviewedDays = rv.date?.let { runCatching { java.time.temporal.ChronoUnit.DAYS.between(java.time.LocalDate.parse(it.take(10)),
        java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata"))) }.getOrNull() }
    val recent = reviewedDays != null && reviewedDays <= 7
    val enabled = !requested && inQueue == null && !recent
    val label = when { requested || inQueue != null -> "Review queued"; recent -> "Reviewed ${shortDate(rv.date)} · a new request opens after 7 days"
                       rv.verdict != null || rv.studied != null -> "Request a new full review"; else -> "Request a full review" }
    Box(Modifier.padding(top = 12.dp, bottom = 16.dp).fillMaxWidth().height(48.dp).clip(RoundedCornerShape(24.dp)).background(if (enabled) C.teal else C.chip)
        .clickable(enabled = enabled) { scope.launch { st.toast = st.requestScan(sym).fold({ "Requested (#$it)" }, { "Not sent: ${it.message}" }) } },
        contentAlignment = Alignment.Center) { T(label, 14.sp, if (enabled) Color.Black else C.grey, FontWeight.SemiBold, maxLines = 1) }
}

// ---------------------------------------------------------------- Announcements tab (no score)
private val BOILER = Regex("^.*?(has informed the Exchange|has submitted to the Exchange|has intimated the Exchange|informed the Exchange)\\s*(about|regarding|that|of|,)?\\s*", RegexOption.IGNORE_CASE)
private val RESULTS_CAT = Regex("result|board meeting|presentation|con\\. ?call|analyst|investor meet|earnings", RegexOption.IGNORE_CASE)

@Composable
fun AnnouncementsPage(det: Detail?) {
    val ctx = LocalContext.current
    var filter by remember { mutableStateOf("All") }
    val evs = det?.stock?.events.orEmpty().distinctBy { Triple(it.date, it.category, it.text) }
    Column(Modifier.padding(horizontal = 16.dp)) {
        Card(Modifier.fillMaxWidth().padding(top = 12.dp), pad = 12.dp) {
            T(if (evs.isEmpty()) "No filings in the store for this stock." else "${evs.size} filings since ${shortDate(evs.mapNotNull { it.date }.minOrNull())} · tap to open the filing", 12.sp, C.grey)
            Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                (listOf("All", "Red flags") + (if (evs.any { it.sev == "watch" }) listOf("Watch") else emptyList()) + listOf("Orders & growth", "Results")).forEach { f ->
                    Box(Modifier.clip(RoundedCornerShape(14.dp)).background(if (filter == f) C.teal else C.chip).clickable { filter = f }.padding(horizontal = 10.dp, vertical = 5.dp)) {
                        T(f, 11.sp, if (filter == f) Color.Black else C.grey, FontWeight.SemiBold)
                    }
                }
            }
        }
        val shown = evs.filter { e -> when (filter) { "Red flags" -> e.sev == "red"; "Watch" -> e.sev == "watch"; "Orders & growth" -> e.sev == "green"; "Results" -> RESULTS_CAT.containsMatchIn(e.category ?: e.type); else -> true } }
        if (shown.isEmpty()) Box(Modifier.padding(top = 12.dp)) { Empty("None in this filter.") }
        else Card(Modifier.fillMaxWidth().padding(top = 12.dp), pad = 6.dp) {
            shown.forEachIndexed { i, e ->
                Row(Modifier.fillMaxWidth().clickable(enabled = e.url != null) { e.url?.let { openUrl(ctx, it) } }.padding(horizontal = 8.dp, vertical = 10.dp)) {
                    Box(Modifier.padding(top = 6.dp).size(8.dp).clip(CircleShape).background(sevColor(e.sev)))
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        val t = e.text.replace(BOILER, "").trim().replaceFirstChar { it.uppercase() }
                        T(t.ifBlank { e.text }, 14.sp, maxLines = 3, lineHeight = 18.sp)
                        T("${shortDate(e.date)} · ${e.category ?: e.type}", 11.sp, C.dim, maxLines = 1)
                    }
                    if (e.url != null) Icon(Icons.Rounded.NorthEast, null, tint = C.grey, modifier = Modifier.padding(start = 6.dp, top = 4.dp).size(18.dp))
                }
                if (i < shown.lastIndex) Box(Modifier.fillMaxWidth().height(1.dp).background(C.line))
            }
        }
        T("No score. Red = can break the investment case, amber = watch (needs a look), green = can be a trigger, grey = routine.", 11.sp, C.dim, lineHeight = 15.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

// ---------------------------------------------------------------- Buy tracking (Settings)
@Composable
fun TrackingScreen(st: AppState) {
    val cf by produceState<CallsFile?>(null) { value = st.repo.get<CallsFile>("data/calls.json") }
    SubScreen(st, "Buy tracking", "Every verified Buy from the day it was rated · closes when the rating leaves Buy or the exit level breaks") {
        val c = cf
        if (c == null) { item { Empty("Loading…") }; return@SubScreen }
        val v = c.calls.filter { it.kind == "verified" }.sortedByDescending { it.date }
        val sm = c.summary.now
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth()) {
                Row {
                    listOf("BUYS" to "${v.size}", "AVG RETURN" to (sm?.avgPct?.let { pctStr(it) } ?: "–"),
                        "VS NIFTY" to (sm?.avgVsNifty?.let { pctStr(it) } ?: "–"), "BEAT NIFTY" to (sm?.beatPct?.let { "$it%" } ?: "–")).forEach { (k, x) ->
                        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                            T(x, 18.sp, if (x.startsWith("-")) TierC.red else if (x.startsWith("+")) TierC.darkGreen else C.white, FontWeight.Bold)
                            T(k, 10.sp, C.dim)
                        }
                    }
                }
                T("Since ${shortDate(v.minOfOrNull { it.date })} · returns from our exchange closes; vs Nifty over the same days", 11.sp, C.dim, modifier = Modifier.padding(top = 8.dp))
            }
        }
        c.summary.portfolio?.let { p -> item { PortfolioCard(p) } }
        item {
            val m = sm?.mix ?: CallMix()
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth()) {
                T("Outcome mix vs the goal", 15.sp, weight = FontWeight.SemiBold)
                T("Goal per 10 Buys: 2 multibaggers, 3 beat Nifty, 3 near Nifty, 2 losers; overall ahead of the market", 11.sp, C.grey, lineHeight = 15.sp)
                listOf(Triple("Multibagger (2× or more)", "2", m.multibagger), Triple("On track (+50% within 12 months)", "–", m.onTrack),
                    Triple("Beat Nifty by more than 5 pts", "3", m.beat), Triple("Near Nifty (± 5 pts)", "3", m.near),
                    Triple("Behind Nifty by more than 5 pts", "2", m.loser)).forEach { (k, g, n) ->
                    Row(Modifier.padding(top = 6.dp)) {
                        T(k, 13.sp, modifier = Modifier.weight(1f)); T("goal $g", 12.sp, C.grey, modifier = Modifier.width(56.dp))
                        T(if (m.n == 0) "–" else "$n", 13.sp, weight = FontWeight.SemiBold)
                    }
                }
                if (m.n > 0) {
                    val parts = listOf(m.multibagger + m.onTrack to TierC.darkGreen, m.beat to TierC.lightGreen, m.near to C.grey, m.loser to TierC.red)
                    Row(Modifier.padding(top = 8.dp).fillMaxWidth().height(10.dp).clip(RoundedCornerShape(5.dp))) {
                        parts.filter { it.first > 0 }.forEach { (n, col) -> Box(Modifier.weight(n.toFloat()).fillMaxHeight().background(col)) }
                    }
                } else T("Fills in once calls are a day old (vs Nifty needs two closes)", 11.sp, C.dim, modifier = Modifier.padding(top = 6.dp))
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Every Buy", "${v.count { it.ended == null }} open · ${v.count { it.ended != null }} closed") } }
        v.forEach { x ->
            item {
                val r = if (x.ended != null) x.toEnd else x.now
                val rv = if (x.ended != null) x.toEndVsNifty else x.nowVsNifty
                Row(Modifier.padding(horizontal = 16.dp, vertical = 3.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(C.card)
                    .clickable { st.go(Screen.Stock(x.symbol)) }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        T(x.symbol.substringBeforeLast("."), 14.sp, weight = FontWeight.SemiBold)
                        T("${x.decision ?: "Buy"} ${shortDate(x.date)} at ₹${fmt(x.price, 1)}" +
                            (if (x.ended != null) " · closed ${shortDate(x.ended)} (${x.endDecision ?: "rating changed"})" else " · open"), 11.sp, C.dim, maxLines = 2)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        T(r?.let { pctStr(it) } ?: "–", 14.sp, if ((r ?: 0.0) < 0) TierC.red else TierC.darkGreen, FontWeight.Bold)
                        T(rv?.let { "${pctStr(it)} vs Nifty" } ?: "₹${fmt(x.priceNow, 1)}", 11.sp, C.dim)
                    }
                }
            }
        }
    }
}


/** Buy tracking: the verified Buys as one equal-weight portfolio vs the Nifty (calls.json summary.portfolio, quantstats). */
@Composable
fun PortfolioCard(p: CallPortfolio) {
    val a = p.curve.mapNotNull { it.getOrNull(1)?.content?.toDoubleOrNull() }
    val b = p.curve.mapNotNull { it.getOrNull(2)?.content?.toDoubleOrNull() }
    fun col(v: Double?) = if (v == null) C.white else if (v < 0) TierC.red else TierC.darkGreen
    Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            T("As one portfolio", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            T("equal weight · ${p.days} day${if (p.days == 1) "" else "s"}", 11.sp, C.dim)
        }
        Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.Bottom) {
            T(pctStr(p.returnPct), 20.sp, col(p.returnPct), FontWeight.Bold); T(" Buys   ", 13.sp, C.dim)
            T(pctStr(p.niftyPct), 20.sp, C.white, FontWeight.Bold); T(" Nifty", 13.sp, C.dim)
        }
        VsChart(a, b, Modifier.padding(top = 8.dp).fillMaxWidth().height(120.dp))
        Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp, 3.dp).background(if ((a.lastOrNull() ?: 0.0) >= (b.lastOrNull() ?: 0.0)) TierC.darkGreen else TierC.red))
            T("  Buys (growth of ₹100)    ", 11.sp, C.dim)
            Box(Modifier.size(10.dp, 3.dp).background(C.dim)); T("  Nifty", 11.sp, C.dim)
        }
        val cells = listOf(
            Triple(p.excessPct?.let { (if (it >= 0) "+" else "") + fmt(it, 1) + " pts" } ?: "–", "Ahead of Nifty", null),
            Triple(p.daysAheadPct?.let { "${it.toInt()}%" } ?: "–", "Days ahead of Nifty", null),
            Triple(p.maxDdPct?.let { fmt(it, 1) + "%" } ?: "–", "Worst fall from a peak", p.niftyMaxDdPct?.let { "Nifty ${fmt(it, 1)}%" }),
            Triple(p.sharpe?.let { fmt(it, 2) } ?: "–", "Return per unit of risk (Sharpe)",
                if (p.sharpe == null) "after ${p.minDays} trading days (${p.days} of ${p.minDays})" else p.niftySharpe?.let { "Nifty ${fmt(it, 2)}" }))
        cells.chunked(2).forEach { row ->
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { (v, k, n) ->
                    Column(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(C.bg).padding(horizontal = 10.dp, vertical = 9.dp)) {
                        T(v, 16.sp, if (v.startsWith("-")) TierC.red else if (v.startsWith("+")) TierC.darkGreen else C.white, FontWeight.Bold)
                        T(k, 11.sp, C.dim)
                        n?.let { T(it, 10.sp, C.dim) }
                    }
                }
            }
        }
        T("All verified Buys held in equal weight from their Buy close until they closed · our exchange closes", 11.sp, C.dim,
            modifier = Modifier.padding(top = 8.dp))
    }
}
