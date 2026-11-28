@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.narrativ.app

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.GenericShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * Today's Knockout Funnel (owner, 28 Nov 2026, mock-up "Funnel and Filters", idea 2 "Knockout funnel"): one upside-down
 * trapezium banded by stage from sand to green, the count left after each stage, and between stages one sentence on what
 * that stage removed. Every number comes from picks.json (funnel.listed / companies / levels / researched / decisions, and
 * the verified Buys counted from the picks). The first opening per app session counts the numbers in; later openings show
 * them at once. A stage's (i), or a tap on its band, opens its gates; tapping the tip opens the verified Buys on Stocks.
 */

/** One stage of the funnel: what is left after it, the sentence on what it removed (number + [gapPost]), how its gates
 *  combine ([rule]) and the gates themselves in plain words, read from the pipeline's checks (narrativ/funnel.py, universe.py,
 *  RULES.md Buy gates and complete research). [info]: the band shows the (i) that opens them. */
data class KoStage(val name: String, val value: Int, val level: Int, val rule: String, val gates: List<String> = emptyList(),
                   val gapPost: String? = null, val gapN: Int = 0, val gapWait: Boolean = false, val info: Boolean = true)

private data class KoDef(val name: String, val value: Int?, val level: Int, val rule: String, val gates: List<String>, val post: String?,
                         val wait: Boolean = false)

/** The stages of [pf] that have data, top to bottom; a sentence only where the stage above exists and the gap is above 0. */
fun koStages(pf: PicksFile): List<KoStage> {
    val fn = pf.funnel
    val buys = fn.decisions.takeIf { it.isNotEmpty() }?.let { (it["Buy"] ?: 0) + (it["Strong Buy"] ?: 0) }
    val verified = pf.picks.takeIf { it.isNotEmpty() }?.let { verifiedBuys(pf) }
    val defs = listOf(
        KoDef("NSE and BSE universe", fn.listed, 0, "Every company listed on the NSE and BSE today.", emptyList(), null),
        KoDef("₹200 cr and above", fn.companies, 0, "Small companies are left out before any check. A company stays when all of these hold:", listOf(
            "Market value of ₹200 crore or more",
            "Not listed on an SME board",
            "Counted once, even when listed on both exchanges",
        ), " stocks under ₹200 cr removed"),
        KoDef("Stability", fn.levels.getOrNull(0), 1,
            "Removes a company that may not survive a bad year. Negative equity removes it on its own; otherwise it takes two or more of the debt and cash warnings below.",
            listOf(
                "Shareholders' equity below zero",
                "Interest cover below 1.5x",
                "Net debt above 5x EBITDA, or negative EBITDA while carrying debt",
                "Cash from operations negative in 2 of the last 3 years, with a loss in the latest year",
                "Current ratio below 0.8 with short-term debt above cash",
                "Banks and finance companies instead: gross NPA above 10%, core capital (CET1) below 5.5%, or a net loss in 2 of the last 4 quarters; any one removes",
            ), " removed for weak interest cover and heavy debt"),
        KoDef("Quality", fn.levels.getOrNull(1), 2,
            "Removes a business with two or more of these weak spots, once it has at least 8 quarters of results filed. A turnaround is kept: " +
                "revenue up 20% or more on a year ago in each of the last two quarters, with a better margin than a year ago.",
            listOf(
                "Return on capital below 10%, over 3 years and in the last 4 quarters",
                "EBITDA margin below 8%, unless return on capital is 15% or more",
                "Revenue growing less than 5% a year over 3 years and less than 10% in the last 4 quarters",
                "Profit growing less than 5% a year over 3 years and less than 10% in the last 4 quarters",
                "Margin down more than 5 points over 3 years and still falling",
                "Industry shrinking (median revenue growth below 5% a year, more than 35% of its companies shrinking) and the company growing slower than that median",
                "Cash from operations below 50% of EBITDA, or other income above 40% of pre-tax profit",
                "Banks and finance companies: return on equity below 10% with return on assets below 1%",
            ), " removed for low returns and weak cash"),
        KoDef("Valuation", fn.levels.getOrNull(2), 3,
            "Removes a company only when it is expensive on all three measures at once. The multiple is price to earnings, price to book or EV to EBITDA, whichever suits the business.",
            listOf(
                "Against its own history: at or above the 75th percentile of its own range (6 or more quarters of history)",
                "Against peers: more than 1.25x the peer median (5 or more comparable companies)",
                "Against its growth: the price needs more than 5 points a year more growth than the company delivered (delivered growth counted up to 25%)",
                "Banks and finance companies, third measure: price to book above 1.25x what their return on equity justifies at a 13% cost of equity",
            ), " removed as overvalued on every measure"),
        KoDef("Management", fn.levels.getOrNull(3), 4, "Removes a company on either of these:", listOf(
            "Promoters cut their stake by more than 5 points in 12 months (a sale down to the 75% public shareholding limit does not count)",
            "Overall management score below 45 out of 100, with data for at least 60% of the checks",
        ), " removed for promoter stake cuts or low conviction"),
        KoDef("Narrativ.ai primary research", fn.researched, 0,
            "Companies Narrativ.ai has studied from their own filings and results. The rest wait in the research queue; there is no pass mark at this step.",
            emptyList(), " yet to be studied", wait = true),
        KoDef("Qualified Buy", buys, 0, "A researched company earns a Buy only when all of these hold:", listOf(
            "Stability and quality in the top three of their five grades",
            "Something to move the price: a driver Narrativ.ai verified, a live trigger, or price strength in the top third of the market",
            "A margin of safety against the base-case value: price at most 0.90x it when management credibility is 75% or more, 0.75x at 50% or more, " +
                "0.60x at 35% or more, 0.80x when credibility is not known; no Buy below 35% credibility",
            "Price trend known and not a downtrend",
            "No open integrity question, unreviewed serious flag, or unread bad filing from the last 30 days",
            "Narrativ.ai's full review passed, including total debt with leases and related-party deals",
            "Cash from operations above zero against operating profit over the last 3 full years (not applied to lenders)",
            "Other income at most 25% of pre-tax profit, unless it is shown to be recurring (not applied to lenders)",
            "A live trigger on the outlook, a verified driver due within 18 months, or relative strength in the top third of the market",
            "Not fairly valued while already well owned by institutions",
        ), " removed as they do not qualify as a Buy"),
        KoDef("Verified Buy", verified, 0, "A Buy gets the verified mark only once Narrativ.ai's research is complete:", listOf(
            "An outlook scan with at least one must-go-right item, one kill switch, and bull, base and bear cases",
            "At least one driver with a verified due date",
            "A story check that finds the story intact",
            "A written synthesis",
            "At least 3 of Narrativ.ai's own checks against the filings, all matching",
        ), " Buys with full in-depth research still pending", wait = true),
    )
    return defs.mapIndexedNotNull { i, d ->
        val v = d.value ?: return@mapIndexedNotNull null
        val above = defs.getOrNull(i - 1)?.value
        val gap = if (above != null && d.post != null) above - v else 0
        KoStage(d.name, v, d.level, d.rule, d.gates, d.post.takeIf { gap > 0 }, gap.coerceAtLeast(0), d.wait, info = i > 0)
    }
}

private val CV_ORDER = listOf("High", "Medium", "Low")

/** The verified Buys, highest conviction first (High, Medium, Low, then none), each group by the pipeline's rank. */
fun koVerified(pf: PicksFile): List<P> = pf.picks.filter { isBuy(it) && it.verified() }
    .sortedWith(compareBy<P> { CV_ORDER.indexOf(it.cv).let { k -> if (k < 0) CV_ORDER.size else k } }.thenBy { it.rk ?: Int.MAX_VALUE })

/** Plain words for one removal reason (P.out.w), numbers left out so the same reason groups together. */
fun plainReason(w: String): String {
    val parts = w.split("; ", ", ").map { it.trim() }.filter { it.isNotEmpty() }.map { part ->
        val anchors = Regex("^overvalued on all \\d+ anchors \\((.+)\\)$").find(part)
        when {
            anchors != null -> "overvalued on every measure (" + when (val m = anchors.groupValues[1]) {
                "P/E" -> "price to earnings"; "P/B" -> "price to book"; else -> m.replace(" / ", " to ")
            } + ")"
            Regex("^interest cover -?[\\d.]+x$").matches(part) -> "weak interest cover"
            Regex("^net debt -?[\\d.]+x EBITDA$").matches(part) -> "heavy net debt against EBITDA"
            Regex("^\\d+ loss quarters of last \\d+$").matches(part) -> "losses in recent quarters"
            Regex("^current ratio -?[\\d.]+ with short-term debt above cash$").matches(part) -> "short-term debt above cash"
            part.startsWith("promoter stake down") -> "promoter stake cut"
            Regex("^conviction \\d+/\\d+.*").matches(part) -> "low management score"
            else -> part.replace(Regex("[-+]?\\d+(\\.\\d+)?\\s*(x|%|pts)?"), "").replace(Regex("\\s+"), " ").trim()
        }
    }.filter { it.isNotEmpty() }.distinct()
    return parts.joinToString(", ").replaceFirstChar { it.uppercase() }
}

/** The most common removal reasons at funnel level [level] (1 Stability .. 4 Management) today, with how many stocks each. */
fun koReasons(pf: PicksFile, level: Int, top: Int = 3): List<Pair<String, Int>> =
    pf.picks.mapNotNull { p -> p.out?.takeIf { it.l == level }?.w?.let { plainReason(it) }?.takeIf { it.isNotEmpty() } }
        .groupingBy { it }.eachCount().entries.sortedByDescending { it.value }.take(top).map { it.key to it.value }

/** Set once the funnel has counted in: later openings while the app stays open show the final numbers at once. */
private var funnelCounted = false

private val KO_INK = Color(0xFF2E2622)
private val KO_SHEET = Color(0xFFF4EDE0)
private val KO_RED = Color(0xFF6E1F18)
private val KO_WAIT = Color(0xFF6B4708)
private val KO_GREEN = Color(0xFF1F4227)
private val KO_SLATE = Color(0xFF2C4A72)
private val KO_BANDS = listOf(0xFFE4D6BC, 0xFFE9D3AE, 0xFFECCDA4, 0xFFE8C9A6, 0xFFDDCDAA, 0xFFD3CFAE, 0xFFC8D0B6, 0xFFBACDB8, 0xFFA8C6AC, 0xFF97BC9E)
    .map { Color(it) }

/** Top full width, bottom 52 % wide, centred. */
private val KoShape = GenericShape { size, _ ->
    moveTo(0f, 0f); lineTo(size.width, 0f); lineTo(size.width * 0.76f, size.height); lineTo(size.width * 0.24f, size.height); close()
}

private const val KO_START = 250
private const val KO_STEP = 380
private const val KO_FADE = 350
private const val KO_COUNT = 800

private fun clamp01(x: Float) = x.coerceIn(0f, 1f)
private fun easeOut(k: Float) = 1f - (1f - k) * (1f - k) * (1f - k)

/** One band of the trapezium: a stage, the sentence above a stage, or the tip with the verified Buys. */
private sealed class KoBand(val group: Int) {
    class Stage(val i: Int) : KoBand(i)
    class Gap(val i: Int) : KoBand(i)
    class Tip(g: Int) : KoBand(g)
}

@Composable
fun FunnelScreen(st: AppState) {
    val pf = st.picks
    val ctx = LocalContext.current
    val stages = remember(pf) { pf?.let { koStages(it) }.orEmpty() }
    val chips = remember(pf) { pf?.let { koVerified(it) }.orEmpty() }
    val bands = remember(stages, chips) {
        buildList {
            stages.forEachIndexed { i, s -> if (s.gapPost != null) add(KoBand.Gap(i)); add(KoBand.Stage(i)) }
            if (chips.isNotEmpty()) add(KoBand.Tip(stages.size))
        }
    }
    val total = (KO_START + stages.size * KO_STEP + KO_COUNT).toFloat()
    val reduce = remember {
        runCatching { android.provider.Settings.Global.getFloat(ctx.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }
            .getOrDefault(false)
    }
    val clock = remember { Animatable(if (funnelCounted || reduce) Float.MAX_VALUE else 0f) }
    LaunchedEffect(stages.isNotEmpty()) {
        if (stages.isNotEmpty() && clock.value < total) {
            funnelCounted = true
            clock.animateTo(total, tween(total.toInt(), easing = LinearEasing))
        }
    }
    val t: () -> Float = { clock.value }
    var sheet by remember { mutableStateOf<Int?>(null) }

    LazyColumn(Modifier.fillMaxSize().pageBackground(), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { KoTopBar(st) }
        if (stages.isEmpty()) item { Empty("The funnel appears after the next data run.") }
        else item {
            KoTrapezium(bands, t, Modifier.padding(horizontal = 16.dp, vertical = 6.dp), onTap = { b ->
                when (b) {
                    is KoBand.Stage -> if (stages[b.i].info) sheet = b.i
                    is KoBand.Gap -> sheet = b.i
                    is KoBand.Tip -> st.go(Screen.Screener("vb"))
                }
            }) { b ->
                when (b) {
                    is KoBand.Stage -> KoStageBand(stages, b.i, t) { sheet = it }
                    is KoBand.Gap -> KoGapBand(stages[b.i], b.i, t)
                    is KoBand.Tip -> KoTipBand(chips)
                }
            }
        }
    }
    val s = sheet?.let { stages.getOrNull(it) }
    if (s != null && pf != null) KoStageSheet(pf, s) { sheet = null }
}

/** Back arrow on the left, the title centred, feedback on the right; a double rule under it on Paper. */
@Composable
private fun KoTopBar(st: AppState) {
    SideEffect { st.screenContext = "Funnel" }
    Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 4.dp).heightIn(min = 48.dp),
        verticalAlignment = Alignment.CenterVertically) {
        IconBtn(Icons.AutoMirrored.Rounded.ArrowBack, "Back") { st.back() }
        Text("Today's Knockout Funnel", Modifier.weight(1f).padding(horizontal = 6.dp), fontSize = 21.sp, lineHeight = 25.sp, color = C.white,
            fontFamily = if (Look.paper) PaperFonts.headline else null, fontWeight = if (Look.paper) FontWeight.Black else FontWeight.Bold,
            textAlign = TextAlign.Center, maxLines = 2)
        FeedbackButton(st, "Funnel")
    }
    if (Look.paper) DoubleRule(Modifier.padding(horizontal = 16.dp).padding(bottom = 8.dp))
}

/**
 * The trapezium: bands stacked top to bottom, each band's text kept inside the slanted edges (its side inset grows with how
 * far down it sits, worked out from the bands' heights in two passes). Each band paints its colour across the full width;
 * the shape clips it. A tap anywhere on a band's row goes to [onTap].
 */
@Composable
private fun KoTrapezium(bands: List<KoBand>, t: () -> Float, modifier: Modifier, onTap: (KoBand) -> Unit, band: @Composable (KoBand) -> Unit) {
    val rows = remember(bands) { IntArray(bands.size + 1) }
    Layout(content = {
        bands.forEach { b ->
            val start = (KO_START + b.group * KO_STEP).toFloat()
            Box(Modifier.semantics(mergeDescendants = true) {
                role = Role.Button
                onClick { onTap(b); true }
            }.graphicsLayer {
                val a = clamp01((t() - start) / KO_FADE)
                alpha = a
                compositingStrategy = CompositingStrategy.ModulateAlpha
                if (b !is KoBand.Gap) {
                    val e = FastOutSlowInEasing.transform(a)
                    translationY = -(1f - e) * 14.dp.toPx()
                    scaleX = 0.96f + 0.04f * e; scaleY = scaleX
                }
            }) { band(b) }
        }
    }, modifier = modifier.fillMaxWidth().border(1.5.dp, C.white, KoShape).background(KO_SHEET, KoShape)
        .pointerInput(bands) {
            detectTapGestures { o ->
                val y = o.y.toInt()
                val i = (0 until bands.size).firstOrNull { y >= rows[it] && y < rows[it + 1] }
                if (i != null) onTap(bands[i])
            }
        }.then(Modifier.graphicsLayer { shape = KoShape; clip = true })) { ms, c ->
        val w = c.maxWidth
        val n = ms.size
        var inset = FloatArray(n) { 0.15f }
        repeat(2) {
            val hs = IntArray(n) { ms[it].maxIntrinsicHeight((w * (1 - 2 * inset[it])).toInt().coerceAtLeast(1)) }
            val h = hs.sum().coerceAtLeast(1)
            var y = 0
            inset = FloatArray(n) { i -> val f = (y + hs[i] * 0.75f) / h; y += hs[i]; 0.03f + 0.24f * f }
        }
        val ps = ms.mapIndexed { i, m ->
            val bw = (w * (1 - 2 * inset[i])).toInt().coerceAtLeast(1)
            m.measure(Constraints(minWidth = bw, maxWidth = bw))
        }
        val h = ps.sumOf { it.height }
        layout(w, h) {
            var y = 0
            ps.forEachIndexed { i, p -> rows[i] = y; p.place((w - p.width) / 2, y); y += p.height }
            rows[n] = y
        }
    }
}

/** The small (i) beside a stage name: opens the stage's gates. A 16 dp ring in slate ink with an italic serif "i", tapped over 32 dp. */
@Composable
private fun KoInfo(name: String, onClick: () -> Unit) {
    Box(Modifier.size(32.dp).clip(CircleShape).clickable(onClickLabel = "How $name works", onClick = onClick), contentAlignment = Alignment.Center) {
        Box(Modifier.size(16.dp).border(1.dp, KO_SLATE, CircleShape), contentAlignment = Alignment.Center) {
            Text("i", color = KO_SLATE, fontSize = 11.sp, lineHeight = 11.sp, fontFamily = PaperFonts.serif, fontWeight = FontWeight.SemiBold,
                fontStyle = FontStyle.Italic)
        }
    }
}

/** Paints [color] across the whole row (the trapezium clips it), not only behind the inset text. */
private fun Modifier.koBand(color: Color) = this.drawBehind {
    drawRect(color, Offset(-size.width, 0f), Size(size.width * 3, size.height))
}

@Composable
private fun KoStageBand(stages: List<KoStage>, i: Int, t: () -> Float, onInfo: (Int) -> Unit) {
    val s = stages[i]
    val start = (KO_START + i * KO_STEP).toFloat()
    val from = if (i == 0) 0 else stages[i - 1].value
    val win = s.name == "Verified Buy"
    Column(Modifier.fillMaxWidth().koBand(KO_BANDS[i.coerceAtMost(KO_BANDS.size - 2)]).padding(vertical = 9.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            Text(s.name, Modifier.weight(1f, false), color = KO_INK.copy(alpha = 0.85f), fontSize = 12.sp, lineHeight = 15.sp,
                fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
            if (s.info) KoInfo(s.name) { onInfo(i) }
        }
        val k = easeOut(clamp01((t() - start) / KO_COUNT))
        Text(fmt(from + (s.value - from) * k.toDouble(), 0), color = if (win) KO_GREEN else KO_INK, fontSize = 30.sp, lineHeight = 34.sp,
            fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1)
    }
}

@Composable
private fun KoGapBand(s: KoStage, i: Int, t: () -> Float) {
    val start = (KO_START + i * KO_STEP).toFloat()
    Box(Modifier.fillMaxWidth().koBand(KO_SHEET).padding(vertical = 6.dp), contentAlignment = Alignment.Center) {
        // the final sentence, invisible, holds the band's size so the line breaks do not move while the number ticks up
        Text(fmt(s.gapN.toDouble(), 0) + s.gapPost.orEmpty(), color = Color.Transparent, fontSize = 12.sp, lineHeight = 15.sp,
            fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
        val k = easeOut(clamp01((t() - start) / KO_COUNT))
        Text(fmt(s.gapN * k.toDouble(), 0) + s.gapPost.orEmpty(), color = if (s.gapWait) KO_WAIT else KO_RED, fontSize = 12.sp, lineHeight = 15.sp,
            fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
    }
}

@Composable
private fun KoTipBand(chips: List<P>) {
    Box(Modifier.fillMaxWidth().koBand(KO_BANDS.last()).padding(top = 9.dp, bottom = 12.dp), contentAlignment = Alignment.Center) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterHorizontally), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            chips.take(4).forEach { p ->
                Text(p.c.ifBlank { p.s.substringBefore('.') }, Modifier.background(KO_GREEN, RoundedCornerShape(2.dp)).padding(horizontal = 5.dp, vertical = 3.dp),
                    color = Color.White, fontSize = 10.sp, lineHeight = 12.sp, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, maxLines = 1)
            }
            if (chips.size > 4) Text("${chips.size - 4} more +", Modifier.background(KO_SHEET, RoundedCornerShape(2.dp))
                .border(1.dp, KO_GREEN, RoundedCornerShape(2.dp)).padding(horizontal = 5.dp, vertical = 3.dp),
                color = KO_GREEN, fontSize = 10.sp, lineHeight = 12.sp, fontFamily = PaperFonts.label, fontWeight = FontWeight.Bold, maxLines = 1)
        }
    }
}

/** A stage's rule in plain words, what it removed today and, for the four checked levels, the most common reasons. */
@Composable
private fun KoStageSheet(pf: PicksFile, s: KoStage, onDismiss: () -> Unit) {
    val reasons = remember(pf, s.level) { if (s.level in 1..4) koReasons(pf, s.level) else emptyList() }
    BottomSheet(onDismiss, title = s.name) {
        T(s.rule, 14.sp, lineHeight = 20.sp)
        s.gates.forEach { g ->
            Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.Top) {
                T("•", 14.sp, C.dim, modifier = Modifier.width(14.dp))
                T(g, 13.sp, modifier = Modifier.weight(1f), lineHeight = 18.sp)
            }
        }
        val n = fmt(s.value.toDouble(), 0)
        T("$n left after this stage today", 13.sp, C.dim, modifier = Modifier.padding(top = 12.dp))
        if (s.gapPost != null) {
            val line = fmt(s.gapN.toDouble(), 0) + s.gapPost + (if (s.gapWait) "" else " today")
            T(line.replaceFirstChar { it.uppercase() }, 13.sp, if (s.gapWait) C.amber else C.red, FontWeight.SemiBold, modifier = Modifier.padding(top = 2.dp))
        }
        if (reasons.isNotEmpty()) {
            T("Most common reasons today", 12.sp, C.dim, modifier = Modifier.padding(top = 12.dp, bottom = 4.dp))
            reasons.forEach { (why, n) ->
                Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
                    T(why, 13.sp, modifier = Modifier.weight(1f).padding(end = 10.dp), lineHeight = 18.sp)
                    T(fmt(n.toDouble(), 0), 13.sp, C.red, FontWeight.SemiBold)
                }
            }
        }
    }
}
