package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.*
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Queue task -> (short name, what Claude does). */
val QUEUE_TASKS = linkedMapOf(
    "review" to ("Full review" to "Rules say Buy: Claude checks the numbers against the filing and passes or holds it."),
    "enrich" to ("Find catalyst" to "Looks only for a dated reason the price could move (order, capacity, guidance)."),
    "review_flag" to ("Check a flag" to "Opens a filing that raised a warning and says whether it matters."),
    "recheck" to ("Recheck" to "New results since Claude's notes: updates them."),
    "audit" to ("Audit" to "Re-checks a stock already rated Buy against its latest filing."),
    "triage" to ("Quick look" to "Decides whether a stock is worth a full read."),
    "scan" to ("First read" to "Claude reads the latest filings for the first time."),
)

/** Research queue: the stocks Claude deep-scans next, in order (feedback #15). */
@Composable
fun QueueScreen(st: AppState) {
    val q = st.queue
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { Header(st, "Research queue", q?.date, "Queue", back = true) }
        // feedback #70: say what each task means once, in plain words, instead of a rule under every stock
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth()) {
                QUEUE_TASKS.values.forEach { (name, what) ->
                    Row(Modifier.padding(vertical = 3.dp)) { T(name, 12.sp, C.teal, FontWeight.SemiBold, modifier = Modifier.width(110.dp)); T(what, 12.sp, C.grey, lineHeight = 16.sp) }
                }
            }
        }
        if (q == null || q.items.isEmpty()) item { Empty("The queue appears after the next daily run.") }
        else itemsIndexed(q.items, key = { _, it -> it.symbol }) { n, it ->
            val p = st.pick(it.symbol)
            Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(C.card)
                .clickable { st.go(Screen.Stock(it.symbol)) }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                T("${n + 1}", 16.sp, C.teal, FontWeight.Bold, modifier = Modifier.width(30.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        T(p?.c ?: it.symbol.substringBeforeLast("."), 15.sp, weight = FontWeight.SemiBold)
                        Spacer(Modifier.width(8.dp))
                        T((QUEUE_TASKS[it.task] ?: QUEUE_TASKS.getValue("scan")).first, 11.sp, if (it.task == "review") C.teal else C.grey)
                    }
                    T(it.name ?: p?.n ?: "", 12.sp, C.grey, maxLines = 1)
                }
            }
        }
    }
}

/** One rotation quadrant: its industries (tap one for its stocks) or sectors (feedback #12, #6). */
@Composable
fun QuadrantScreen(st: AppState, q: String, sectors: Boolean) {
    val rot = st.rotation
    val src = (if (sectors) rot?.sectors else rot?.industries).orEmpty()
    val list = src.entries.filter { it.value.q == q }.sortedByDescending { it.value.mom }
    val what = mapOf("Leading" to "money flowing in", "Improving" to "money starting to flow in",
        "Weakening" to "book profits · tighten stops", "Lagging" to "money flowing out")[q] ?: ""
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { Header(st, q, "${list.size} ${if (sectors) "sectors" else "industries"} · $what", "Quadrant $q", back = true) }
        if (list.isEmpty()) item { Empty("Nothing in this quadrant today.") }
        else itemsIndexed(list, key = { _, e -> e.key }) { _, (name, r) ->
            val top = if (sectors) emptyList() else (st.picks?.picks ?: emptyList()).filter { it.out == null && it.i == name }.sortedByDescending { it.pr }
            Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(C.card)
                .clickable { st.go(Screen.Screener(if (sectors) "sec:$name" else "ind:$name")) }.padding(12.dp)) {
                IndRow(name, r)
                if (top.isNotEmpty()) {
                    T("Top in funnel: " + top.take(3).joinToString(" · ") { "${it.c} (${fmt(it.pr, 0)})" } + "  ›", 12.sp, C.teal, maxLines = 1,
                        modifier = Modifier.padding(top = 2.dp))
                }
            }
        }
        if (sectors) item { T("Sector indices are NSE's; tap one for the stocks in its industries.", 12.sp, C.dim, modifier = Modifier.padding(16.dp)) }
    }
}

/** Universal search on Home: name, code or industry across the whole universe (feedback #14). */
@Composable
fun HomeSearch(st: AppState) {
    var q by remember { mutableStateOf("") }
    val all = st.picks?.picks ?: emptyList()
    val hits = remember(q, all) {
        if (q.length < 2) emptyList() else all.filter { "${it.c} ${it.n} ${it.i ?: ""}".contains(q, true) }
            .sortedWith(compareByDescending<P> { it.c.startsWith(q, true) }.thenByDescending { it.out == null }.thenByDescending { it.pr })
    }
    Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color.Black.copy(alpha = 0.35f)).padding(horizontal = 14.dp, vertical = 12.dp)) {
            BasicTextField(q, { q = it }, singleLine = true, textStyle = TextStyle(color = C.white, fontSize = 15.sp), cursorBrush = SolidColor(C.teal),
                decorationBox = { inner -> if (q.isEmpty()) T("Search ${all.size} stocks: name, code or industry", 15.sp, C.dim); inner() })
        }
        if (hits.isNotEmpty()) {
            Column(Modifier.padding(top = 6.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(C.card)) {
                hits.take(8).forEach { p ->
                    Row(Modifier.fillMaxWidth().clickable { q = ""; st.go(Screen.Stock(p.s)) }.padding(horizontal = 12.dp, vertical = 9.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            T(p.c, 14.sp, weight = FontWeight.SemiBold); T(p.n, 12.sp, C.grey, maxLines = 1)
                        }
                        if (p.out == null) VerdictChip(p.vd, 10.sp) else TierChip("Removed L${p.out.l}", TierC.red, 10.sp)
                        Spacer(Modifier.width(8.dp)); T("${fmt(p.pr, 0)}", 13.sp, C.teal, FontWeight.SemiBold)
                    }
                }
                if (hits.size > 8) T("All ${hits.size} results in the screener ›", 13.sp, C.blue,
                    modifier = Modifier.fillMaxWidth().clickable { val t = q; q = ""; st.go(Screen.Screener("q:$t")) }.padding(12.dp))
            }
        }
    }
}

/** Promoter holding over time as a line chart (feedback #16). */
@Composable
fun PromoterChart(points: List<PromoterPoint>, modifier: Modifier) {
    val tm = rememberTextMeasurer()
    val pts = points.sortedBy { it.date }
    if (pts.size < 2) return
    Canvas(modifier) {
        val lo0 = pts.minOf { it.pct }; val hi0 = pts.maxOf { it.pct }
        val span = maxOf(2.0, hi0 - lo0)
        val lo = lo0 - span * 0.2; val hi = hi0 + span * 0.2
        val left = 44f; val bottom = size.height - 22f; val top = 8f
        fun x(i: Int) = left + i * (size.width - left - 8f) / (pts.size - 1)
        fun y(v: Double) = (bottom - (v - lo) / (hi - lo) * (bottom - top)).toFloat()
        val st = TextStyle(color = C.dim, fontSize = 10.sp)
        listOf(lo0, hi0).distinct().forEach { v ->
            drawLine(C.line, Offset(left, y(v)), Offset(size.width, y(v)), 1f)
            drawText(tm.measure("${fmt(v, 1)}%", st), topLeft = Offset(0f, y(v) - 7f))
        }
        val path = Path()
        pts.forEachIndexed { i, p -> if (i == 0) path.moveTo(x(i), y(p.pct)) else path.lineTo(x(i), y(p.pct)) }
        val col = if (pts.last().pct >= pts.first().pct) C.teal else C.red
        drawPath(path, col, style = Stroke(4f))
        pts.forEachIndexed { i, p -> drawCircle(col, 5f, Offset(x(i), y(p.pct))) }
        drawText(tm.measure(shortMonth(pts.first().date), st), topLeft = Offset(left - 10f, bottom + 6f))
        val l = tm.measure(shortMonth(pts.last().date), st)
        drawText(l, topLeft = Offset(size.width - l.size.width, bottom + 6f))
    }
}

// ---------------------------------------------------------------- Settings sub-screens (feedback #40, #41)
@Composable
fun SubScreen(st: AppState, title: String, subtitle: String?, content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit) {
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { Header(st, title, subtitle, title, back = true) }
        content()
    }
}

@Composable
fun NotesScreen(st: AppState) {
    val v = st.version
    val scope = rememberCoroutineScope()
    SubScreen(st, "Version", null) {
        item {
            Column(Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(C.card).padding(14.dp)) {
                val newer = (v?.versionCode ?: 0) > BuildConfig.VERSION_CODE
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { T("v${BuildConfig.VERSION_NAME}", 20.sp, weight = FontWeight.Bold); T("build ${BuildConfig.VERSION_CODE} · installed", 12.sp, C.grey) }
                    TierChip(if (newer) "UPDATE AVAILABLE" else "UP TO DATE", if (newer) C.blue else TierC.darkGreen, 10.sp)
                }
                Box(Modifier.padding(top = 12.dp).fillMaxWidth().height(44.dp).clip(RoundedCornerShape(22.dp)).background(C.teal).clickable {
                    if (newer) st.showUpdate = true
                    else scope.launch { st.repo.get<VersionInfo>("app/version.json")?.let { st.version = it; if (it.versionCode > BuildConfig.VERSION_CODE) st.showUpdate = true else st.toast = "Up to date" } }
                }, contentAlignment = Alignment.Center) { T(if (newer) "Install v${v?.versionName}" else "Check for updates", 15.sp, Color.Black, FontWeight.SemiBold) }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("What's new", "Release notes, newest first") } }
        if (v == null) item { Empty("Release notes load with an internet connection.") }
        else item { Column(Modifier.padding(horizontal = 16.dp)) { v.changelog.take(8).forEach { rel -> ReleaseNotes(rel) } } }
    }
}

@Serializable data class FbItem(val n: Int = 0, val state: String = "", val type: String = "", val text: String = "", val screen: String = "", val date: String = "")

@Composable
fun FeedbackListScreen(st: AppState) {
    val data by produceState<Pair<List<FbItem>, Pair<Int, Int>>?>(null) {
        value = st.repo.apiGet("feedback/stats")?.let { o ->
            val items = runCatching { json.decodeFromJsonElement(kotlinx.serialization.builtins.ListSerializer(FbItem.serializer()), o["items"]!!) }.getOrDefault(emptyList())
            items to ((o["open"]?.toString()?.toIntOrNull() ?: 0) to (o["closed"]?.toString()?.toIntOrNull() ?: 0))
        }
    }
    var state by remember { mutableStateOf("open") }
    var type by remember { mutableStateOf<String?>(null) }
    SubScreen(st, "Feedback", null) {
        val d = data
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                listOf("open" to d?.second?.first, "closed" to d?.second?.second).forEach { (k, n) ->
                    val on = state == k
                    Column(Modifier.weight(1f).height(76.dp).clip(RoundedCornerShape(16.dp)).background(if (on) C.teal.copy(alpha = 0.18f) else C.card)
                        .clickable { state = k }.padding(12.dp), verticalArrangement = Arrangement.SpaceBetween) {
                        T(k.replaceFirstChar { it.uppercase() }, 13.sp, if (on) C.white else C.grey); T(n?.toString() ?: "–", 24.sp, weight = FontWeight.Bold)
                    }
                }
            }
        }
        if (d == null) { item { Empty("Feedback loads with an internet connection.") }; return@SubScreen }
        val types = d.first.map { it.type }.distinct().sorted()
        item {
            Row(Modifier.horizontalScroll(androidx.compose.foundation.rememberScrollState()).padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (listOf<String?>(null) + types).forEach { t -> FChip(t ?: "All", type == t, C.teal) { type = t } }
            }
        }
        val list = d.first.filter { it.state == state && (type == null || it.type == type) }
        if (list.isEmpty()) item { Empty("Nothing here.") }
        list.forEach { f ->
            item {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(C.card).padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Pill(f.type, if (f.type == "Bug") C.red else C.blue, (if (f.type == "Bug") C.red else C.blue).copy(alpha = 0.15f))
                        Spacer(Modifier.width(8.dp)); T("#${f.n} · ${f.date}", 11.sp, C.dim, modifier = Modifier.weight(1f))
                    }
                    T(f.text.replaceFirstChar { it.uppercase() }, 14.sp, modifier = Modifier.padding(top = 6.dp))
                    if (f.screen.isNotBlank()) T(f.screen, 11.sp, C.grey)
                }
            }
        }
    }
}

data class Src(val name: String, val what: String, val from: String, val freq: String, val cover: String)

val SOURCES = listOf(
    Src("Universe", "Which companies are covered: non-SME, market cap ≥ ₹200 crore, one row per company (NSE listing preferred); industry from BSE's 4-level classification", "NSE market-cap file and equity lists; BSE equity list and classification", "Daily", "All NSE and BSE main-board companies"),
    Src("Financial results", "Revenue, profit, margins, balance sheet, cash flow used in every ratio; auditor's opinion from annual results", "Company XBRL filings on NSE; BSE results summary for companies filing only on BSE (Yahoo only for what BSE lacks)", "Every run: market-wide list of new filings", "All companies; BSE-only balance sheets partly"),
    Src("Prices and volume", "Price trend, momentum, relative strength, charts", "NSE and BSE end-of-day files (history before 17 Nov 2026 from Yahoo); splits and bonuses applied from the exchange previous close", "Daily", "All companies, 5 years"),
    Src("Delivery and surveillance", "Delivery %, GSM / ASM stages, suspension, Nifty index membership", "NSE daily files and surveillance lists; BSE delivery file", "Daily (index lists weekly)", "Delivery: all; surveillance: NSE companies"),
    Src("Shareholding", "Promoter holding and pledge, mutual funds, institutions, retail holders", "NSE shareholding pattern (XBRL), market-wide list of new and revised filings", "Every run", "NSE companies"),
    Src("Announcements", "Red flags (defaults, insolvency, rating actions, regulator orders, auditor exits, leadership changes) and order wins with rupee values", "NSE and BSE corporate announcements", "Daily (only the days since the last run)", "All companies, 25 months"),
    Src("Corporate filings", "Dividends, preferential issues, loans and guarantees to the promoter side, promoter trades, use of raised funds", "NSE corporate actions, further issues, governance filings, insider trading, statements of deviation; BSE dividends", "Daily; insider trades the day a disclosure is announced", "NSE companies; BSE dividends"),
    Src("Analyst estimates", "Consensus target and EPS revisions (shown labelled); named broker targets", "Yahoo consensus; broker reports quoted in Claude's research", "Daily for rated stocks and after results, weekly for the rest", "Where covered"),
    Src("Market mood", "India VIX, Nifty vs 200-day, sector indices, breadth, 52-week highs and lows, put-call ratio, FII/DII flows", "NSE index closing file, F&O end-of-day file, own prices", "Daily", "Market-wide"),
    Src("Research", "Full reviews of rule-Buy stocks (numbers checked against the filing), promises, guidance, drivers, red flags, story", "Claude reading filings and transcripts; quotes verified word-for-word", "5 runs a day; published within minutes", "Your requests and rule-Buy stocks first (full reviews), then the research queue"),
    Src("Not connected yet", "Lenders' capital adequacy and NPA trend, order book to revenue, shareholding / surveillance / governance for BSE-only companies", "–", "–", "Shown as 'source not connected yet'"),
)

@Composable
fun PipelineScreen(st: AppState) {
    val h by produceState<Health?>(null) { value = st.repo.get<Health>("data/health.json") }
    val issues by produceState<IssuesFile?>(null) { value = st.repo.get<IssuesFile>("data/data_issues.json") }
    val sched by produceState<Schedule?>(null) { value = st.repo.get<Schedule>("data/schedule.json") }
    val runs by produceState<List<RunRec>?>(null) { value = st.repo.get<List<RunRec>>("data/runs.json") }
    val scope = rememberCoroutineScope()
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    // feedback #67: Data pipeline + Data sources + Refresh data in one screen
    SubScreen(st, "Data", h?.let { "Last run ${it.date ?: "–"} · ${fmt(it.minutes, 1)} min" }) {
        item {
            Column(Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(C.card).padding(14.dp)) {
                T("On this phone", 13.sp, C.grey)
                T("Data of ${shortDate(st.picks?.date)} · finished ${istTime(st.picks?.updated)} IST", 15.sp, weight = FontWeight.SemiBold)
                Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(TierC.darkGreen)); Spacer(Modifier.width(6.dp))
                    T("Updates automatically when you open the app", 12.sp, TierC.darkGreen)
                }
                T("Next daily run: ${nextDailyRun()} · Claude's reviews are published within minutes of each research run",
                    12.sp, C.grey, lineHeight = 16.sp, modifier = Modifier.padding(top = 2.dp))
                Box(Modifier.padding(top = 12.dp).fillMaxWidth().height(44.dp).clip(RoundedCornerShape(22.dp)).background(C.teal)
                    .clickable { scope.launch {
                        val before = st.picks?.updated
                        st.load()
                        st.toast = if (st.picks?.updated == before) "Already latest: data of ${shortDate(st.picks?.date)}. Next update ${nextDailyRun()}"
                                   else "Updated to data of ${shortDate(st.picks?.date)}"
                    } }, contentAlignment = Alignment.Center) { T("Check for new data", 15.sp, Color.Black, FontWeight.SemiBold) }
            }
        }
        sched?.let { sc ->
            item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Today (IST)", sc.note ?: "") } }
            item {
                Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                    val reviewsToday = st.research.values.count { it.updated == today }
                    sc.jobs.forEach { j ->
                        val status = when {
                            j.name.startsWith("Daily run") && st.picks?.date == today -> "✓ done" to TierC.darkGreen
                            j.by == "Claude" && j.name.startsWith("Research") && reviewsToday > 0 -> "✓ $reviewsToday stocks" to TierC.darkGreen
                            else -> null
                        }
                        Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                            Column(Modifier.width(118.dp)) { T(j.time, 12.sp, weight = FontWeight.SemiBold); T(j.days, 11.sp, C.grey) }
                            T(j.name, 12.sp, modifier = Modifier.weight(1f).padding(horizontal = 6.dp), lineHeight = 15.sp)
                            if (status != null) T(status.first, 11.sp, status.second, FontWeight.SemiBold) else T(j.by, 11.sp, C.grey)
                        }
                    }
                }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Sources", "Where each number comes from · tap for coverage") } }
        item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                SOURCES.forEach { x ->
                    var open by remember { mutableStateOf(false) }
                    Column(Modifier.fillMaxWidth().clickable { open = !open }.padding(vertical = 7.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T(x.name, 13.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                            T(x.freq, 11.sp, C.grey, maxLines = 1, modifier = Modifier.widthIn(max = 150.dp)); T(if (open) " ▴" else " ›", 13.sp, C.grey)
                        }
                        if (open) {
                            T(x.what, 12.sp, Color(0xFFDFE3E6), lineHeight = 16.sp, modifier = Modifier.padding(top = 4.dp))
                            listOf("Source" to x.from, "Coverage" to x.cover).forEach { (k, v) ->
                                Row(Modifier.padding(top = 2.dp)) { T(k, 11.sp, C.dim, modifier = Modifier.width(70.dp)); T(v, 11.sp, C.grey, modifier = Modifier.weight(1f)) }
                            }
                        }
                    }
                }
            }
        }
        val x = h
        if (x == null) { item { Empty("Pipeline health appears after the next daily run.") }; return@SubScreen }
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                listOf("Coverage" to (x.coveragePct?.let { "${fmt(it, 1)}%" } ?: "–"), "Problems" to "${x.problems.size}", "Stocks" to "${x.stocks}").forEach { (k, v) ->
                    Column(Modifier.weight(1f).height(76.dp).clip(RoundedCornerShape(16.dp)).background(C.card).padding(12.dp), verticalArrangement = Arrangement.SpaceBetween) {
                        T(k, 13.sp, C.grey); T(v, 22.sp, if (k == "Problems" && x.problems.isNotEmpty()) C.amber else C.white, FontWeight.Bold)
                    }
                }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Data issues", "Wrong numbers found by Claude's audits · fixed for every stock when systemic") } }
        item {
            val iss = issues
            if (iss == null || iss.issues.isEmpty()) Empty("No data issue logged yet. Audits add them as they find wrong numbers.")
            else Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                T("${iss.open} open (${iss.openSystemic} systemic) · ${iss.fixed} fixed", 14.sp, weight = FontWeight.SemiBold)
                iss.issues.values.sortedWith(compareBy<DataIssue> { it.status != "open" }.thenByDescending { it.firstSeen }).take(30).forEach { d ->
                    Column(Modifier.padding(top = 8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            T(d.symbol.substringBeforeLast("."), 13.sp, weight = FontWeight.SemiBold); Spacer(Modifier.width(6.dp))
                            Pill(d.scope, if (d.scope == "systemic") C.amber else C.grey, (if (d.scope == "systemic") C.amber else C.grey).copy(alpha = 0.15f))
                            Spacer(Modifier.width(6.dp))
                            T(if (d.status == "fixed") "fixed ${d.fixedOn ?: ""}" else d.status, 11.sp, if (d.status == "fixed") TierC.darkGreen else C.red)
                        }
                        T("${d.field}: app ${d.app ?: "–"} → filed ${d.found ?: "–"}", 12.sp, C.grey)
                        d.cause?.let { T(it.replaceFirstChar { c -> c.uppercase() }, 12.sp) }
                    }
                }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Stages", "Minutes per stage of the last run") } }
        item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                val total = x.stages.sumOf { it.getOrNull(1)?.content?.toDoubleOrNull() ?: 0.0 }.coerceAtLeast(1.0)
                x.stages.forEach { s ->
                    val name = s.getOrNull(0)?.content ?: ""; val sec = s.getOrNull(1)?.content?.toDoubleOrNull() ?: 0.0
                    Column(Modifier.padding(vertical = 5.dp)) {
                        Row { T(name.replaceFirstChar { it.uppercase() }, 13.sp, modifier = Modifier.weight(1f)); T("${fmt(sec / 60, 1)} min", 13.sp, C.grey) }
                        Box(Modifier.padding(top = 4.dp).fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(C.chip)) {
                            Box(Modifier.fillMaxWidth((sec / total).toFloat()).fillMaxHeight().background(C.teal))
                        }
                    }
                }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Problems", if (x.problems.isEmpty()) "None in the last run" else "Lines flagged in the last run's log") } }
        if (x.problems.isNotEmpty()) item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) { x.problems.take(40).forEach { T(it, 12.sp, C.amber, lineHeight = 16.sp, modifier = Modifier.padding(vertical = 3.dp)) } }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Sources", "Size of each store after the last run") } }
        item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                x.sources.forEach { (k, m) ->
                    Column(Modifier.padding(vertical = 5.dp)) {
                        T(k.replaceFirstChar { it.uppercase() }, 14.sp, weight = FontWeight.SemiBold)
                        T(m.entries.joinToString(" · ") { (a, b) -> "${a.replace('_', ' ')} ${b.content}" }, 12.sp, C.grey)
                    }
                }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Check coverage", "Stocks with data · no data · source not connected") } }
        LEVELS.forEachIndexed { i, lk ->
            val rows = x.checks.filter { it.level == lk }
            if (rows.isNotEmpty()) item {
                Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth()) {
                    T(LEVEL_SHORT[i], 14.sp, weight = FontWeight.SemiBold)
                    rows.forEach { c ->
                        val tot = (c.data + c.noData + c.pending).coerceAtLeast(1)
                        Row(Modifier.padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                            T(c.id, 11.sp, C.dim, modifier = Modifier.width(30.dp))
                            T(c.name, 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
                            T("${c.data * 100 / tot}%", 12.sp, if (c.pending > 0 && c.data == 0) C.red else if (c.data * 100 / tot >= 80) C.teal else C.amber, FontWeight.SemiBold)
                        }
                    }
                }
            }
        }
        item { Box(Modifier.padding(horizontal = 16.dp)) { SectionHeader2("Last 30 runs", "Data date, finish time (IST), minutes, problems") } }
        runs?.forEach { x ->
            item {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 3.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(C.card).padding(12.dp)) {
                    T("${shortDate(x.date)} · finished ${istTime(x.finished)}", 13.sp, modifier = Modifier.weight(1f))
                    T("${fmt(x.minutes, 1)} min", 13.sp, C.grey); Spacer(Modifier.width(12.dp))
                    T(if (x.problems == 0) "OK" else "${x.problems} problem${if (x.problems > 1) "s" else ""}", 13.sp, if (x.problems == 0) C.teal else C.amber)
                }
            }
        }
    }
}


@Serializable data class RunRec(val date: String = "", val finished: String = "", val minutes: Double? = null, val problems: Int = 0)

/** One IPO, opened from its card (Open IPOs or Top 10). */
@Composable
fun IpoScreen(st: AppState, name: String) {
    val x = st.ipo
    val u = x?.upcoming?.firstOrNull { it.name == name }
    val i = x?.actionable?.firstOrNull { it.name == name }
        ?: x?.laterToday?.firstOrNull { it.name == name }?.let { IpoOpen(name = it.name, board = it.board, lastDate = it.lastDate ?: "", upcoming = true, why = "Opens today ${it.opens ?: ""}".trim()) }
        ?: u?.let { IpoOpen(name = it.name, board = it.board, priceLow = it.priceLow, priceHigh = it.priceHigh, openDate = it.openDate ?: "", lastDate = it.lastDate ?: "",
            upcoming = true, gmpNote = it.note, gmpObserved = it.gmpObserved, sources = listOfNotNull(it.source)) }
    val uri = androidx.compose.ui.platform.LocalUriHandler.current
    SubScreen(st, name, i?.let { "${it.board} · IPO · checked ${x?.checkedAt?.replace('T', ' ')?.take(16) ?: "–"} IST" }) {
        if (i == null) { item { Empty("This IPO is not in today's report.") }; return@SubScreen }
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (i.upcoming) Pill("NOT OPEN YET · not ranked", C.grey, C.chip)
                if (i.rating.isNotEmpty()) Pill(i.rating, ipoRateColor(i.rating), ipoRateColor(i.rating).copy(alpha = 0.15f), 13.sp)
                if (i.action.isNotEmpty()) Pill(i.action, Color.Black, ipoActColor(i.action), 13.sp)
                if (i.top10) Pill("In Top 10", C.teal, C.teal.copy(alpha = 0.15f), 13.sp)
            }
        }
        item {
            Card(Modifier.padding(16.dp).fillMaxWidth()) {
                IKV("Price band", if (i.priceHigh != null) "₹${fmt(i.priceLow, 0)}–${fmt(i.priceHigh, 0)}" else "–")
                IKV("Open → last date to apply", "${shortDate(i.openDate.ifEmpty { null })} → ${shortDate(i.lastDate)}" + (i.closeTime?.let { " · $it" } ?: ""))
                if (i.finalDay) IKV("Today", "FINAL DAY", C.red)
                i.day?.let { IKV("Day", "$it of ${i.days ?: "–"}") }
                IKV("Lot", i.lot?.let { l -> "$l shares" + (i.priceHigh?.let { " · ₹${fmt(it * l, 0)}" } ?: "") } ?: "–")
                IKV("Issue size", i.issueCr?.let { "₹${fmt(it, 0)} cr" } ?: "–")
            }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                T("GMP · unofficial, not a guaranteed return", 13.sp, C.grey)
                fun rng(a: Double?, b: Double?, pre: String = "₹", suf: String = "") = if (a == null) "–" else if (b == null || a == b) "$pre${fmt(a, 0)}$suf" else "$pre${fmt(a, 0)}–${fmt(b, 0)}$suf"
                IKV("GMP", rng(i.gmpLow, i.gmpHigh) + if (u != null && i.gmpHigh == null) (u.gmp ?: "") else "")
                IKV("Implied listing", rng(i.impliedLow, i.impliedHigh))
                IKV("GMP % of upper band", rng(i.gmpPctLow, i.gmpPctHigh, "", "%"))
                IKV("Observed", (i.gmpObserved?.replace('T', ' ')?.take(60) ?: "–") + if (i.gmpStale) " · not today (stale)" else "", if (i.gmpStale) C.amber else C.white)
                i.gmpTrend?.let { IKV("Trend", it) }
                i.gmpNote?.takeIf { it.isNotBlank() }?.let { T(it, 12.sp, C.amber, lineHeight = 16.sp, modifier = Modifier.padding(top = 6.dp)) }
            }
        }
        i.subscription?.let { sb ->
            item {
                Card(Modifier.padding(16.dp).fillMaxWidth()) {
                    T("Subscription · ${sb.asOf?.replace('T', ' ')?.take(16) ?: "–"}", 13.sp, C.grey)
                    listOf("QIB" to sb.qib, "NII" to sb.nii, "Retail" to sb.retail, "Overall" to sb.overall).forEach { (k, v) -> IKV(k, v?.let { "${fmt(it, 2)}×" } ?: "–") }
                    i.pmUpdate?.let { pm -> T("14:10 update: call ${pm.callBefore ?: "–"} → ${pm.callAfter ?: "–"}", 12.sp, if (pm.callBefore != pm.callAfter) C.amber else C.grey, modifier = Modifier.padding(top = 6.dp)) }
                }
            }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
                T("Assessment", 13.sp, C.grey)
                i.why?.takeIf { !i.upcoming }?.let { T("Why: $it", 13.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp)) }
                if (i.keyRisk.isNotEmpty()) T("Key risk: ${i.keyRisk}", 13.sp, Color(0xFFDFE3E6), lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp))
                if (i.missing.isNotEmpty()) T("Missing: " + i.missing.joinToString(" · "), 13.sp, C.amber, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp))
                if (i.upcoming) T("Rated at the 08:30 check on its opening day.", 13.sp, C.grey, modifier = Modifier.padding(top = 4.dp))
            }
        }
        val src = (i.sources + i.gmpSources + listOfNotNull(i.subscription?.source)).distinct()
        if (src.isNotEmpty()) item {
            Card(Modifier.padding(16.dp).fillMaxWidth()) {
                T("Sources", 13.sp, C.grey)
                src.forEach { s -> T(s.removePrefix("https://").removePrefix("www.").take(60) + " ›", 12.sp, C.blue, maxLines = 1,
                    modifier = Modifier.padding(top = 6.dp).clickable { runCatching { uri.openUri(s) } }) }
            }
        }
    }
}

@Composable
private fun IKV(k: String, v: String, col: Color = C.white) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) { T(k, 13.sp, C.grey, modifier = Modifier.weight(1f)); T(v, 13.sp, col, FontWeight.SemiBold) }
}

private val IST_ZONE = java.time.ZoneId.of("Asia/Kolkata")

/** ISO timestamp (any offset) -> "14 Nov 14:06" in IST. */
fun istTime(iso: String?): String = runCatching {
    val t = java.time.OffsetDateTime.parse(iso!!).atZoneSameInstant(IST_ZONE)
    "${t.dayOfMonth} ${t.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)} %02d:%02d".format(t.hour, t.minute)
}.getOrDefault("–")

/** Next 17:10 IST on a weekday. */
fun nextDailyRun(): String {
    var t = java.time.ZonedDateTime.now(IST_ZONE).withHour(17).withMinute(10).withSecond(0)
    val now = java.time.ZonedDateTime.now(IST_ZONE)
    while (!t.isAfter(now) || t.dayOfWeek.value >= 6) t = t.plusDays(1)
    return if (t.toLocalDate() == now.toLocalDate()) "today 17:10 IST" else "${t.dayOfWeek.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)} ${t.dayOfMonth} ${t.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)} 17:10 IST"
}
