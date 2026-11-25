package com.narrativ.app

import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.animation.core.animateFloat
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.max

/**
 * Home (mockup h01): header (logo, search, feedback), one-line Market strip, Today's Top 10 (rank, code, MB, conviction,
 * setup · industry, sparkline, price, day move), track record as two bars (opens How we know, h02), open IPOs (only when
 * the 08:30 check found any), Explore chips into Stocks presets, the data line. Pull down to refresh.
 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun HomeScreen(st: AppState) {
    val pf = st.picks ?: return
    val scope = rememberCoroutineScope()
    var refreshing by remember { mutableStateOf(false) }
    var showEvidence by remember { mutableStateOf(false) }
    // Explore chip counts: one pass over all picks per picks.json, not on every recomposition
    // feedback #81: same Outlook tier the stock's Outlook tab shows (p.t[6]: 1 Very strong, 2 Strong)
    val chips = remember(pf) {
        val live = pf.picks.filter { it.out == null }
        val good = live.filter { p -> p.dc != "Sell" && p.dc != "Strong Sell" && p.tier(6) in 1..2 }
            .sortedWith(compareBy<P> { it.tier(6) }.thenByDescending { it.pr })
        val bq = live.count { it.bq != null }
        val vc = live.groupingBy { it.vd }.eachCount()
        listOf(Triple("Strong outlook", good.size, "syms:Strong outlook|" + good.joinToString(",") { it.s }), Triple("Beaten-up quality", bq, "bq")) +
            listOf("Prime candidate", "Early story", "Undervalued quality", "Momentum play", "Value watch", "Quality, priced in").map { Triple(it, vc[it] ?: 0, "v:$it") }
    }
    // one Top 10 for Home and the stock page rank (Look.kt topTen): open IPOs first, then verified Buys in the pipeline's order
    val tt = topTen(st)
    val ipoTop = tt?.ipos.orEmpty()
    val stockTop = tt?.stocks.orEmpty()
    val pending = tt?.pendingReview ?: 0
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    val ipoOpen = st.ipo?.takeIf { it.date == today }?.actionable.orEmpty()
    // memory / phone copy at once (no wait on the network each time Home opens), then the network copy if it changed
    val rp by produceState(st.repo.peek<ReplayFile>("data/replay.json")) { st.repo.cacheFirst<ReplayFile>("data/replay.json") { if (it != null) value = it } }
    val cf by produceState(st.repo.peek<CallsFile>("data/calls.json")) { st.repo.cacheFirst<CallsFile>("data/calls.json") { if (it != null) value = it } }

    androidx.compose.material3.pulltorefresh.PullToRefreshBox(refreshing, { scope.launch { refreshing = true; st.load(); refreshing = false } },
        Modifier.fillMaxSize().background(C.screen)) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 110.dp)) {
            item {
                Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    AppLogo(40.dp)
                    T("Narrativ", 26.sp, weight = FontWeight.Bold, modifier = Modifier.weight(1f), maxLines = 1)
                    IconBtn(Icons.Rounded.Search, "Search") { st.go(Screen.Search) }
                    FeedbackButton(st, "Home")
                }
            }
            item {
                val md = pf.mood
                val n200 = md?.inputs?.firstOrNull { it.k == "nifty_200" }?.value
                MarketStrip(md?.score, md?.zone, n200?.let { "Nifty ${sg1(it)} vs 200-day" }, { st.go(Screen.Market) },
                    Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 18.dp))
            }
            item {
                Row(Modifier.fillMaxWidth().padding(start = 18.dp, end = 16.dp, bottom = 10.dp), verticalAlignment = Alignment.Bottom) {
                    Column(Modifier.weight(1f)) {
                        T("Today's Top 10", 21.sp, weight = FontWeight.Bold)
                        // counts what the card shows: the verified Buys listed plus any IPO rated into the Top 10
                        val ns = stockTop.size; val ni = ipoTop.size
                        T("$ns verified Buy${if (ns == 1) "" else "s"}" + (if (ni > 0) " + $ni IPO${if (ni == 1) "" else "s"}" else "") + " · max 2 per industry" +
                            (if (pending > 0) " · $pending awaiting review" else ""), 13.sp, C.dim, maxLines = 2)
                    }
                    // Stocks lists stocks only, so "All N" opens exactly the stocks on the card (IPOs open from their own rows)
                    if (stockTop.isNotEmpty()) Row(Modifier.clip(RoundedCornerShape(8.dp)).clickable {
                        st.go(Screen.Screener("syms:Today's Top 10|" + stockTop.joinToString(",") { it.s }))
                    }.padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                        T("All ${stockTop.size}", 13.sp, C.blue); Icon(Icons.Rounded.ChevronRight, null, tint = C.blue, modifier = Modifier.size(16.dp))
                    }
                }
            }
            item {
                if (stockTop.isEmpty() && ipoTop.isEmpty()) Empty(if (pending > 0) "$pending Buy-rated stocks are queued for Narrativ.ai's review; verified ones appear here." else "No verified Buy today.")
                else Top10Card(st, stockTop, ipoTop)
            }
            rp?.let { r ->
                val cur = r.variants["current rules"]; val any = r.baselines["every stock scored"]
                if (cur != null && cur.m6.n > 0 && cur.m6.winPct != null) item { TrackBars(cur, any) { showEvidence = true } }
            }
            if (ipoOpen.isNotEmpty()) item { IpoRow(st, ipoOpen) }
            item {
                // Explore: counts open Stocks with the matching preset (chips, computed once per picks.json above)
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                    T("Explore", 21.sp, weight = FontWeight.Bold, modifier = Modifier.padding(start = 2.dp, top = 18.dp, bottom = 10.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        chips.filter { it.second > 0 }.forEach { (name, n, preset) -> ToggleChip(name, false, { st.go(Screen.Screener(preset)) }, count = n) }
                    }
                }
            }
            item { DataLine(st) }
        }
    }
    if (showEvidence) rp?.let { HowWeKnowSheet(st, it, cf) { showEvidence = false } }
}

/** Time of day in IST (HH:mm) of an ISO timestamp; null when it cannot be read. */
fun istHm(iso: String?): String? = runCatching {
    java.time.OffsetDateTime.parse(iso!!).atZoneSameInstant(java.time.ZoneId.of("Asia/Kolkata")).toLocalTime().toString().take(5)
}.getOrNull()

/** "Data of 20 Nov · run finished 01:11 IST · research 09:08", or offline / updating. */
@Composable
fun DataLine(st: AppState) {
    val pf = st.picks ?: return
    val txt = when {
        st.loading -> "Updating…"
        else -> listOfNotNull("Data of ${shortDate(pf.date)}", istHm(pf.updated)?.let { "run finished $it IST" }, istHm(pf.researchUpdated)?.let { "research $it" })
            .joinToString(" · ") + if (st.offline) " · offline, phone copy" else ""
    }
    T(txt, 12.sp, if (st.offline) C.amber else C.dim, modifier = Modifier.fillMaxWidth().padding(top = 18.dp, start = 16.dp, end = 16.dp),
        align = TextAlign.Center)
}

/** Top 10 rows: IPOs rated into the Top 10 first, then stocks; live delayed quotes in market hours. */
@Composable
fun Top10Card(st: AppState, list: List<P>, ipos: List<IpoOpen> = emptyList()) {
    val live = rememberLiveQuotes(st, list.map { it.s.substringBeforeLast(".") })
    Card(Modifier.padding(horizontal = 16.dp).fillMaxWidth(), pad = 0.dp) {
        if (live.isNotEmpty()) T("Delayed quotes, ${quoteTime(live) ?: ""} (unofficial source)", 11.sp, C.dim, modifier = Modifier.padding(start = S.cardPad, top = 10.dp))
        val n = ipos.size + list.size
        ipos.forEachIndexed { k, i ->
            Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Ipo(i.name)) }.padding(horizontal = S.cardPad, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                T("${k + 1}", 14.sp, C.dim, modifier = Modifier.width(26.dp))
                Column(Modifier.weight(1f)) {
                    T(i.symbol ?: i.name, 16.sp, weight = FontWeight.Bold, maxLines = 1)
                    T("IPO · ${i.board} · closes ${ipoCloses(i.lastDate).first}", 13.sp, C.dim, maxLines = 1)
                }
                StatusChip(sentence(i.action), color = ipoActColor(i.action))
            }
            if (k < n - 1) HLineDivider(Modifier.padding(horizontal = S.cardPad))
        }
        list.forEachIndexed { k, p ->
            val q = live[p.s.substringBeforeLast(".")]
            Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Stock(p.s)) }.padding(horizontal = S.cardPad, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                T("${ipos.size + k + 1}", 14.sp, C.dim, modifier = Modifier.width(26.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        T(p.c, 16.sp, weight = FontWeight.Bold, maxLines = 1, modifier = Modifier.weight(1f, false))
                        if (p.mb) MbTag()
                        ConvictionMeter(p.cv)
                    }
                    Text(androidx.compose.ui.text.buildAnnotatedString {
                        pushStyle(androidx.compose.ui.text.SpanStyle(color = C.white)); append(setupName(p.su, p.tb == 1)); pop(); append(" · " + (p.i ?: "–"))
                    }, fontSize = 13.sp, color = C.dim, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                }
                Sparkline(p.sp, Modifier.padding(horizontal = 8.dp).size(52.dp, 26.dp))
                Column(Modifier.widthIn(min = 76.dp), horizontalAlignment = Alignment.End) {
                    T(priceStr(q?.p ?: p.p), 15.sp, weight = FontWeight.Bold, maxLines = 1)
                    (q?.d1 ?: p.d1)?.let { T(pct2(it), 12.sp, gainColor(it), maxLines = 1) }
                }
            }
            if (ipos.size + k < n - 1) HLineDivider(Modifier.padding(horizontal = S.cardPad))
        }
    }
}

/** Past Top 10s vs any stock: share that beat the Nifty over 6 months, as two bars with the 50% mark. */
@Composable
private fun TrackBars(cur: ReplayVar, any: ReplayVar?, onClick: () -> Unit) {
    Card(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp).fillMaxWidth(), onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                T("Beat the Nifty over 6 months · past Top 10s", 12.sp, C.dim, maxLines = 1, modifier = Modifier.padding(bottom = 6.dp))
                TrackBar("Top 10", cur.m6.winPct, C.teal, C.white)
                any?.m6?.winPct?.let { TrackBar("Any stock", it, TierC.grey, C.dim) }
            }
            Icon(Icons.Rounded.ChevronRight, "How we know", tint = C.dim, modifier = Modifier.padding(start = 6.dp).size(18.dp))
        }
    }
}

@Composable
private fun TrackBar(label: String, v: Int?, c: Color, vc: Color) = Row(Modifier.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
    T(label, 13.sp, C.muted, modifier = Modifier.width(76.dp), maxLines = 1)
    HBar((v ?: 0) / 100.0, c, Modifier.weight(1f), 8.dp, 0.5)
    T(v?.let { "$it%" } ?: "–", 14.sp, vc, FontWeight.Bold, Modifier.width(46.dp), maxLines = 1, align = TextAlign.End)
}

/** "3 IPOs open" with the one to apply for; tap opens it (one IPO) or the list of open and coming IPOs. */
@Composable
private fun IpoRow(st: AppState, open: List<IpoOpen>) {
    val x = st.ipo ?: return
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    val soon = x.laterToday.map { IpoOpen(name = it.name, board = it.board, lastDate = it.lastDate ?: "", upcoming = true, why = "Opens today ${it.opens ?: ""}".trim()) } +
        x.upcoming.filter { (it.lastDate ?: "") >= today }.map { IpoOpen(name = it.name, board = it.board, openDate = it.openDate ?: "", lastDate = it.lastDate ?: "",
            upcoming = true, why = "Opens ${shortDate(it.openDate)}") }
    var expanded by remember { mutableStateOf(false) }
    val pick = open.firstOrNull { "APPLY" in it.action }
    Card(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp).fillMaxWidth(), onClick = {
        if (open.size == 1 && soon.isEmpty()) st.go(Screen.Ipo(open[0].name)) else expanded = !expanded
    }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                T("${open.size} IPO${if (open.size == 1) "" else "s"} open", 17.sp, weight = FontWeight.Bold)
                T(pick?.let { "${it.name}: ${sentence(it.action)} · ${ipoCloses(it.lastDate).first}" } ?: "None to apply", 13.sp, C.dim, maxLines = 1)
            }
            Icon(if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.size(18.dp))
        }
        if (expanded) {
            Spacer(Modifier.height(6.dp))
            (open + soon).forEach { i ->
                HLineDivider()
                Row(Modifier.fillMaxWidth().clickable { st.go(Screen.Ipo(i.name)) }.padding(vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        T(i.name, 14.sp, if (i.upcoming) C.dim else C.white, FontWeight.Medium, maxLines = 1)
                        T(if (i.upcoming) (i.why ?: "Opens later") else "${i.board} · ${ipoCloses(i.lastDate).first}",
                            12.sp, if (i.finalDay) TierC.lightRed else C.dim, maxLines = 1)
                    }
                    if (!i.upcoming && i.action.isNotEmpty()) StatusChip(sentence(i.action), color = when (i.action) {
                        "APPLY" -> TierC.lightGreen; "WAIT" -> C.grey; "AVOID" -> TierC.lightRed; else -> C.dim })
                }
            }
            T("GMP is unofficial grey-market data, not a guaranteed return.", 11.sp, C.dim, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

private fun monYear(iso: String?): String = runCatching {
    val d = java.time.LocalDate.parse(iso!!.take(10)); d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH) + " ${d.year}"
}.getOrDefault("–")

/** How we know (mockup h02): replay of the rules (Top 10 vs any stock), live Buys, what helps, limits. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun HowWeKnowSheet(st: AppState, rp: ReplayFile, cf: CallsFile?, onDismiss: () -> Unit) {
    val cur = rp.variants["current rules"] ?: return
    val any = rp.baselines["every stock scored"]
    val grey = TierC.grey
    val hs = listOf(cur.m3, cur.m6, cur.m12); val ha = listOf(any?.m3, any?.m6, any?.m12)
    val names = listOf("3 months", "6 months", "12 months")
    BottomSheet(onDismiss, "How we know") {
        T("Monthly replay of the rules, ${monYear(rp.dates.firstOrNull())} – ${monYear(rp.dates.lastOrNull())}, on what was known each day.", 13.sp, C.dim,
            lineHeight = 18.sp, modifier = Modifier.padding(bottom = 10.dp))
        Legend(listOf("Top 10" to C.teal, "Any stock" to grey))
        T("Beat the Nifty", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.padding(top = 10.dp, bottom = 4.dp))
        GroupedBars(names.mapIndexed { k, n -> n to "${hs[k].n} picks" }, listOf(C.teal to hs.map { it.winPct?.toDouble() }, grey to ha.map { it?.winPct?.toDouble() }),
            Modifier.fillMaxWidth().height(160.dp), { "${it.toInt()}%" }, ref = 50.0, refLabel = "50%")
        Row(Modifier.padding(top = 14.dp, bottom = 4.dp), verticalAlignment = Alignment.Bottom) {
            T("Average vs Nifty", 15.sp, weight = FontWeight.SemiBold); T("  pts", 12.sp, C.dim)
        }
        GroupedBars(names.map { it to null }, listOf(C.teal to hs.map { it.avgVsNifty }, grey to ha.map { it?.avgVsNifty }),
            Modifier.fillMaxWidth().height(130.dp), { sg1(it, "") })
        cf?.summary?.now?.takeIf { it.n > 0 }?.let { now ->
            val since = cf.calls.minOfOrNull { it.date }
            Row(Modifier.padding(top = 16.dp, bottom = 6.dp), verticalAlignment = Alignment.Bottom) {
                T("Live Buys", 15.sp, weight = FontWeight.SemiBold)
                Text(androidx.compose.ui.text.buildAnnotatedString {
                    append("  " + listOfNotNull(since?.let { "since ${shortDate(it)}" }, "${now.n} Buys").joinToString(" · "))
                    now.avgVsNifty?.let { v -> append(" · avg "); pushStyle(androidx.compose.ui.text.SpanStyle(color = gainColor(v))); append(vsNifty(v)); pop(); append(" vs Nifty") }
                }, fontSize = 12.sp, color = C.dim, maxLines = 2)
            }
            val m = now.mix
            // same four outcomes as Track record (on track counts with Multibagger), every segment named in the legend
            val mix = listOf(Triple("Multibagger", m.multibagger + m.onTrack, TierC.darkGreen), Triple("Beat Nifty", m.beat, TierC.lightGreen),
                Triple("Near Nifty", m.near, C.grey), Triple("Behind Nifty", m.loser, TierC.lightRed))
            SegmentedBar(mix.map { (_, v, c) -> Segment(v.toDouble(), c) }, legend = SegLegend.None)
            FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                mix.forEach { (k, v, c) ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp)).background(c)); T(" $k ", 12.sp, C.dim); T("$v", 12.sp, weight = FontWeight.Bold)
                    }
                }
            }
        }
        val v = rp.variants
        val helps = listOfNotNull(
            v["without R4 dated trigger"]?.let { Triple("Trigger or strength (R4)", cur.m6.winPct?.toDouble() to it.m6.winPct?.toDouble(), true) },
            v["rank: no entry-setup tier"]?.let { Triple("Entry setup first", cur.m6.winPct?.toDouble() to it.m6.winPct?.toDouble(), true) },
            v["without margin of safety"]?.let { Triple("Margin of safety", cur.m6.avgVsNifty to it.m6.avgVsNifty, false) })
        if (helps.isNotEmpty()) {
            Row(Modifier.padding(top = 16.dp, bottom = 4.dp), verticalAlignment = Alignment.Bottom) { T("What helps", 15.sp, weight = FontWeight.SemiBold); T("  6 months", 12.sp, C.dim) }
            Legend(listOf("With it" to C.teal, "Without it" to grey), Modifier.padding(bottom = 4.dp))
            val ptsMax = helps.filter { !it.third }.flatMap { listOfNotNull(it.second.first, it.second.second) }.maxOfOrNull { abs(it) }?.takeIf { it > 0 } ?: 10.0
            helps.forEach { (label, ab, isPct) ->
                Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                    T(label, 14.sp, modifier = Modifier.width(140.dp), maxLines = 2)
                    Column(Modifier.weight(1f)) {
                        listOf(ab.first to C.teal, ab.second to grey).forEachIndexed { k, (x, c) ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                HBar(if (x == null) 0.0 else if (isPct) x / 100 else max(x, 0.0) / (ptsMax * 1.25), c, Modifier.weight(1f), 5.dp)
                                T(x?.let { if (isPct) "${it.toInt()}%" else sg1(it, "") } ?: "–", 12.sp, if (k == 0) C.white else C.dim, FontWeight.SemiBold,
                                    Modifier.width(48.dp), maxLines = 1, align = TextAlign.End)
                            }
                        }
                    }
                }
            }
        }
        T("Limits", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.padding(top = 16.dp, bottom = 4.dp))
        listOf("Code rules only: Narrativ.ai's reviews cannot be replayed.",
            "One period, ${monYear(rp.dates.firstOrNull())} – ${monYear(rp.dates.lastOrNull())}; stocks delisted since are missing.",
            if ((cur.m3.winPct ?: 0) <= (any?.m3?.winPct ?: 0)) "No 3-month edge: ${cur.m3.winPct ?: "–"}% vs ${any?.m3?.winPct ?: "–"}% for any stock."
            else "3 months: ${cur.m3.winPct ?: "–"}% vs ${any?.m3?.winPct ?: "–"}% for any stock.").forEach {
            T(it, 13.sp, C.muted, lineHeight = 18.sp, modifier = Modifier.padding(vertical = 3.dp))
        }
        MoreLink("Every call in Track record") { onDismiss(); st.go(Screen.TrackRecord) }
    }
}

fun shortDate(iso: String?): String = runCatching {
    val d = java.time.LocalDate.parse(iso!!.take(10))
    "${d.dayOfMonth} " + d.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)
}.getOrDefault(iso ?: "")

/** Seven short bars, one per level, in tier colours. */
@Composable
fun LevelBars(p: P) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        LEVELS.indices.forEach { i -> Box(Modifier.weight(1f).height(5.dp).clip(RoundedCornerShape(3.dp)).background(p.levelColor(i))) }
    }
}

@Composable
fun SectionHeader(title: String, sub: String, right: String? = null, onClick: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
        .padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { T(title, 18.sp, weight = FontWeight.SemiBold); T(sub, 12.sp, C.grey, maxLines = 2) }
        if (right != null) T("$right ›", 13.sp, C.grey)
    }
}

@Composable
fun Empty(text: String) {
    Box(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(S.card)).background(C.card2).padding(16.dp)) { T(text, 13.sp, C.grey) }
}

@Composable
fun Col(k: String, v: String, color: Color = C.white) = Column { T(k, 12.sp, C.grey); T(v, 14.sp, color, FontWeight.SemiBold) }

@Composable
fun QuadPill(q: String) {
    val c = quadC(q)
    Pill(q, c, c.copy(alpha = 0.15f))
}

/** Dots and labels only; quadrants labelled. Labels avoid each other by trying four positions. */
@Composable
fun RotationMap(pts: Map<String, Rot>, modifier: Modifier, labels: Boolean = true, onQuadrant: ((String) -> Unit)? = null) {
    val tm = rememberTextMeasurer()
    val xr = if (pts.isEmpty()) 2.0 else maxOf(2.0, pts.values.maxOf { kotlin.math.abs(it.ratio - 100) } * 1.15)
    val yr = if (pts.isEmpty()) 2.0 else maxOf(2.0, pts.values.maxOf { kotlin.math.abs(it.mom - 100) } * 1.15)
    val tap = if (onQuadrant == null) Modifier else Modifier.pointerInput(pts) {
        detectTapGestures { o ->
            val pad = 8f
            val cx = pad + (xr / (2 * xr) * (size.width - 2 * pad)).toFloat()
            val cy = size.height - pad - (yr / (2 * yr) * (size.height - 2 * pad)).toFloat()
            onQuadrant(if (o.y < cy) (if (o.x >= cx) "Leading" else "Improving") else (if (o.x >= cx) "Weakening" else "Lagging"))
        }
    }
    Canvas(modifier.then(tap)) {
        if (pts.isEmpty()) return@Canvas
        val pad = 8f
        fun X(v: Double) = (pad + (v - (100 - xr)) / (2 * xr) * (size.width - 2 * pad)).toFloat()
        fun Y(v: Double) = (size.height - pad - (v - (100 - yr)) / (2 * yr) * (size.height - 2 * pad)).toFloat()
        val cx = X(100.0); val cy = Y(100.0)
        drawRect(quadC("Leading").copy(alpha = 0.06f), Offset(cx, 0f), Size(size.width - cx, cy))
        drawRect(quadC("Improving").copy(alpha = 0.05f), Offset(0f, 0f), Size(cx, cy))
        drawRect(quadC("Weakening").copy(alpha = 0.04f), Offset(cx, cy), Size(size.width - cx, size.height - cy))
        drawRect(quadC("Lagging").copy(alpha = 0.04f), Offset(0f, cy), Size(cx, size.height - cy))
        drawLine(C.line, Offset(cx, 0f), Offset(cx, size.height), 1.5f)
        drawLine(C.line, Offset(0f, cy), Offset(size.width, cy), 1.5f)
        val qStyle = { c: Color -> TextStyle(color = c, fontSize = 10.sp, fontWeight = FontWeight.Bold) }
        val sub = { c: Color -> TextStyle(color = c.copy(alpha = 0.7f), fontSize = 9.sp) }
        listOf(Triple("Improving", "money starting to flow in", quadC("Improving")) to (false to false), Triple("Leading", "money flowing in", quadC("Leading")) to (true to false),
            Triple("Lagging", "money flowing out", quadC("Lagging")) to (false to true), Triple("Weakening", "book profits · tighten stops", quadC("Weakening")) to (true to true)).forEach { (t, pos) ->
            val a = tm.measure(t.first, qStyle(t.third)); val b = tm.measure(if (labels) t.second else " ", sub(t.third))
            val right = pos.first; val bottom = pos.second
            val x1 = if (right) size.width - a.size.width - 6f else 6f
            val x2 = if (right) size.width - b.size.width - 6f else 6f
            val y1 = if (bottom) size.height - a.size.height - b.size.height - 6f else 4f
            drawText(a, topLeft = Offset(x1, y1)); drawText(b, topLeft = Offset(x2, y1 + a.size.height))
        }
        val placed = mutableListOf<Rect>()
        pts.entries.sortedBy { it.value.mom }.forEach { (name, r) ->
            val px = X(r.ratio); val py = Y(r.mom); val c = quadC(r.q)
            drawCircle(c, 9f, Offset(px, py))
            if (!labels) return@forEach
            val label = tm.measure("$name ${r.r1m?.let { pctStr(it).replace(".0%", "%") } ?: ""}", TextStyle(color = Color.White, fontSize = 10.sp))
            val w = label.size.width.toFloat(); val h = label.size.height.toFloat()
            val cands = listOf(Offset(px + 12, py - h / 2), Offset(px - 12 - w, py - h / 2), Offset(px - w / 2, py - h - 10), Offset(px - w / 2, py + 10))
            val pos = cands.firstOrNull { o -> val rr = Rect(o, Size(w, h)); rr.left >= 0 && rr.right <= size.width && rr.top >= 0 && rr.bottom <= size.height && placed.none { it.overlaps(rr) } }
            if (pos != null) { placed += Rect(pos, Size(w, h)); drawText(label, topLeft = pos) }
        }
    }
}

@Composable
fun TargetBar(price: Double, a: Analyst, modifier: Modifier) {
    Canvas(modifier) {
        val lo = -40.0; val hi = 80.0
        fun x(v: Double?) = (((((v ?: price) / price - 1) * 100) - lo) / (hi - lo)).coerceIn(0.0, 1.0).toFloat() * size.width
        val cy = size.height / 2
        drawRoundRect(C.chip, Offset(0f, cy - 3), Size(size.width, 6f), androidx.compose.ui.geometry.CornerRadius(3f))
        if (a.low != null && a.high != null) drawRect(C.blue.copy(alpha = 0.45f), Offset(x(a.low), cy - 3), Size(x(a.high) - x(a.low), 6f))
        drawLine(Color.White, Offset(x(price), cy - 8), Offset(x(price), cy + 8), 3f)
        val m = x(a.mean)
        val path = Path().apply { moveTo(m, cy - 7); lineTo(m + 7, cy); lineTo(m, cy + 7); lineTo(m - 7, cy); close() }
        drawPath(path, C.teal)
    }
}

/** Charts seen recently (LRU), each with the data generation it was loaded in; kept across refreshes so a chart shows at once. */
private val chartCache = object : LinkedHashMap<String, Pair<Int, Chart>>(16, 0.75f, true) {
    override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Pair<Int, Chart>>?) = size > 48
}
@Volatile private var chartGen = 0

/** Called when the published data is refreshed: charts already held still show at once, and are checked again on their next view. */
fun clearChartCache() { chartGen++ }

/** The chart held in memory, if any (no I/O): the stock page's first frame shows it instead of a placeholder. */
fun cachedChart(sym: String): Chart? = synchronized(chartCache) { chartCache[sym]?.second }

/** [onChart] gets the held / phone copy at once, then the network copy when it differs; nothing when there is no chart anywhere. */
suspend fun loadChart(st: AppState, sym: String, onChart: (Chart) -> Unit) {
    val gen = chartGen
    val hit = synchronized(chartCache) { chartCache[sym] }
    if (hit != null) { onChart(hit.second); if (hit.first == gen) return }
    var last = hit?.second
    st.repo.cacheFirst<Chart>("data/charts/${Repo.seg(sym)}.json") { ch ->
        if (ch != null) {
            synchronized(chartCache) { chartCache[sym] = gen to ch }
            if (ch != last) { last = ch; onChart(ch) }
        }
    }
}


/** One dot per rule: green passes, red fails, grey not known yet. */
@Composable
fun RuleDots(rules: List<IpoRule>, modifier: Modifier = Modifier, size: Dp = 8.dp) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        rules.forEach { r -> Box(Modifier.size(size).clip(CircleShape).background(when (r.ok) { true -> TierC.lightGreen; false -> C.red; null -> C.chip })) }
    }
}

/** "Today 5 PM" (red), "Tomorrow 5 PM", else the weekday and date. */
fun ipoCloses(last: String): Pair<String, Color> {
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata"))
    val d = runCatching { java.time.LocalDate.parse(last.take(10)) }.getOrNull() ?: return "–" to C.dim
    return when (d) {
        today -> "Today 5 PM" to C.red
        today.plusDays(1) -> "Tomorrow 5 PM" to C.grey
        else -> "${d.dayOfWeek.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.ENGLISH)} ${d.dayOfMonth}, 5 PM" to C.grey
    }
}

/** IPO call colour: Apply green, Wait grey (not tappable, so never blue), Avoid red. */
fun ipoActColor(a: String) = when (a) { "APPLY" -> TierC.lightGreen; "WAIT" -> C.grey; "AVOID" -> TierC.lightRed; else -> C.dim }


fun setupWords(su: String?): String? = when (su) {
    "Breakout" -> "breaking out"; "Pullback" -> "dip in an uptrend"; "Base" -> "base, near entry"; null, "", "No setup" -> "wait for entry"; else -> su.lowercase()
}

/** Loading placeholders in the shape of the content (#19). */
@Composable
fun Skel(w: androidx.compose.ui.unit.Dp?, h: androidx.compose.ui.unit.Dp, modifier: Modifier = Modifier) {
    val t = androidx.compose.animation.core.rememberInfiniteTransition(label = "sk")
    val a by t.animateFloat(0.35f, 0.7f, androidx.compose.animation.core.infiniteRepeatable(androidx.compose.animation.core.tween(800),
        androidx.compose.animation.core.RepeatMode.Reverse), label = "ska")
    Box(modifier.then(if (w != null) Modifier.width(w) else Modifier.fillMaxWidth()).height(h).clip(RoundedCornerShape(6.dp)).background(C.chip.copy(alpha = a)))
}

@Composable
fun HomeSkeleton() {
    Column(Modifier.fillMaxSize().background(C.screen).statusBarsPadding().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) { Skel(46.dp, 46.dp); Spacer(Modifier.width(12.dp)); Column { Skel(110.dp, 16.dp); Spacer(Modifier.height(6.dp)); Skel(170.dp, 12.dp) } }
        Spacer(Modifier.height(16.dp)); Skel(null, 46.dp)
        Spacer(Modifier.height(24.dp)); Skel(160.dp, 20.dp); Spacer(Modifier.height(10.dp))
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(S.card)).background(C.card).padding(S.cardPad)) {
            repeat(6) {
                Row(Modifier.padding(vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                    Skel(14.dp, 14.dp); Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) { Skel(100.dp, 14.dp); Spacer(Modifier.height(6.dp)); Skel(150.dp, 10.dp) }
                    Skel(70.dp, 28.dp)
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        T("Loading today's data…", 12.sp, C.dim, modifier = Modifier.align(Alignment.CenterHorizontally))
    }
}
