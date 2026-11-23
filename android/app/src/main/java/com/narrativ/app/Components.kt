package com.narrativ.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.NumberFormat
import java.util.Locale

private val inr = NumberFormat.getNumberInstance(Locale("en", "IN"))
fun fmt(v: Double?, d: Int = 2): String = if (v == null) "–" else inr.apply { maximumFractionDigits = d; minimumFractionDigits = 0 }.format(v)
fun pctStr(v: Double?): String = if (v == null) "–" else (if (v >= 0) "+" else "") + fmt(v, 1) + "%"
fun pctColor(v: Double?): Color = if ((v ?: 0.0) >= 0) C.teal else C.red

@Composable
fun T(text: String, size: TextUnit = 14.sp, color: Color = C.white, weight: FontWeight = FontWeight.Normal,
      modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE, lineHeight: TextUnit = TextUnit.Unspecified,
      align: androidx.compose.ui.text.style.TextAlign? = null) =
    Text(text, modifier = modifier, fontSize = size, color = color, fontWeight = weight, maxLines = maxLines,
        overflow = TextOverflow.Ellipsis, lineHeight = lineHeight, textAlign = align)

@Composable
fun CircleBtn(icon: ImageVector, tint: Color = C.white, accent: Boolean = false, onClick: () -> Unit) {
    Box(
        Modifier.size(44.dp).clip(CircleShape)
            .background(if (accent) C.teal.copy(alpha = 0.08f) else Color.White.copy(alpha = 0.07f))
            .then(if (accent) Modifier.border(1.dp, C.teal.copy(alpha = 0.35f), CircleShape) else Modifier)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, null, tint = if (accent) C.teal else tint, modifier = Modifier.size(22.dp)) }
}

@Composable
fun Pill(text: String, fg: Color = C.grey, bg: Color = C.chip, size: TextUnit = 11.sp, modifier: Modifier = Modifier) {
    Box(modifier.clip(RoundedCornerShape(12.dp)).background(bg).padding(horizontal = 8.dp, vertical = 3.dp)) {
        T(text, size, fg, FontWeight.SemiBold, maxLines = 1)
    }
}

fun statusColors(s: String): Pair<Color, Color> = when (s) {
    "BUY ZONE", "delivered", "beat", "raised", "met" -> C.teal to C.teal.copy(alpha = 0.15f)
    "WATCH", "PULLBACK", "partly", "on track", "open" -> C.blue to C.blue.copy(alpha = 0.15f)
    "EXIT", "missed", "delayed", "off_track", "DROPPED", "due" -> C.red to C.red.copy(alpha = 0.15f)
    else -> C.grey to C.chip
}

@Composable
fun StatusPill(s: String, label: String? = null) {
    val (fg, bg) = statusColors(s)
    Pill(label ?: s.lowercase().replaceFirstChar { it.uppercase() }, fg, bg)
}

@Composable
fun Card(modifier: Modifier = Modifier, color: Color = C.card, radius: Dp = 20.dp, pad: Dp = 14.dp,
         onClick: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier.clip(RoundedCornerShape(radius)).background(color)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(pad),
        content = content,
    )
}

@Composable
fun SectionTitle(title: String, right: String? = null, onClick: (() -> Unit)? = null) {
    Row(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 22.dp, bottom = 10.dp)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        T(title, 18.sp, weight = FontWeight.SemiBold)
        if (right != null) T(right, 13.sp, C.grey)
    }
}

// Sparkline moved to Charts.kt (same signature, mockup colours).

/** Two growth-of-100 lines: `a` coloured green where it is at or above `b`, red where below; `b` grey; dashed line at 100. */
@Composable
fun VsChart(a: List<Double>, b: List<Double>, modifier: Modifier = Modifier) {
    if (a.size < 2 || b.size != a.size) return
    val lo = (a + b + 100.0).min(); val hi = (a + b + 100.0).max()
    val span = (hi - lo).takeIf { it > 0 } ?: 1.0
    Canvas(modifier) {
        fun x(i: Int) = i / (a.size - 1f) * size.width
        fun y(v: Double) = size.height - ((v - lo) / span * size.height).toFloat()
        drawLine(C.line, Offset(0f, y(100.0)), Offset(size.width, y(100.0)), 1.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 6f)))
        val pb = Path(); b.forEachIndexed { i, v -> if (i == 0) pb.moveTo(x(i), y(v)) else pb.lineTo(x(i), y(v)) }
        drawPath(pb, C.dim, style = Stroke(width = 1.6.dp.toPx()))
        for (i in 1 until a.size) {
            drawLine(if (a[i] >= b[i]) TierC.darkGreen else TierC.red, Offset(x(i - 1), y(a[i - 1])), Offset(x(i), y(a[i])), 2.4.dp.toPx())
        }
    }
}

@Composable
fun ScoreRing(score: Int, size: Dp = 42.dp) {
    Box(Modifier.size(size).border(2.dp, C.blue, CircleShape), contentAlignment = Alignment.Center) {
        T("$score", 15.sp, weight = FontWeight.Bold)
    }
}

@Composable
fun GaugeRing(pct: Int, size: Dp = 92.dp) {
    Box(Modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize().padding(6.dp)) {
            drawArc(C.chip, 0f, 360f, false, style = Stroke(10.dp.toPx()))
            drawArc(C.teal, -90f, 360f * pct / 100f, false, style = Stroke(10.dp.toPx(), cap = androidx.compose.ui.graphics.StrokeCap.Round))
        }
        T("$pct%", 20.sp, weight = FontWeight.Bold)
    }
}

@Composable
fun Meter(label: String, v: Int?, modifier: Modifier = Modifier) {
    Column(modifier) {
        T("$label ${v ?: "–"}", 11.sp, C.grey, maxLines = 1)
        Spacer(Modifier.height(3.dp))
        Box(Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(C.chip)) {
            Box(Modifier.fillMaxWidth(((v ?: 0) / 100f).coerceIn(0f, 1f)).fillMaxHeight().background(C.teal))
        }
    }
}

/** Icon tile used in timelines and section headers. */
@Composable
fun Tile(icon: ImageVector, brush: Brush = C.tile, size: Dp = 46.dp, iconSize: Dp = 26.dp) {
    Box(Modifier.size(size).clip(RoundedCornerShape(14.dp)).background(brush), contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = Color.White, modifier = Modifier.size(iconSize))
    }
}

fun kindIcon(kind: String): ImageVector = when (kind) {
    "factory" -> Icons.Rounded.Factory
    "product" -> Icons.Rounded.Inventory2
    "order" -> Icons.Rounded.Description
    "debt" -> Icons.Rounded.AccountBalance
    "results" -> Icons.Rounded.BarChart
    "approval" -> Icons.Rounded.Verified
    "holding" -> Icons.Rounded.PieChart
    else -> Icons.Rounded.Lightbulb
}

// ---------------------------------------------------------------- funnel levels, tiers, verdicts
val LEVELS = listOf("surv", "qual", "val", "mgmt", "mom", "disc", "out")
val LEVEL_TITLES = listOf("Company stability", "Business quality", "Business valuation", "Management evaluation",
    "Momentum analysis", "Discovery stage", "Future outlook")
val LEVEL_SHORT = listOf("Stability", "Quality", "Valuation", "Management", "Momentum", "Discovery", "Outlook")
val LEVEL_ICONS = listOf(Icons.Rounded.Shield, Icons.Rounded.Diamond, Icons.Rounded.LocalOffer, Icons.Rounded.Groups,
    Icons.Rounded.Speed, Icons.Rounded.Visibility, Icons.Rounded.RocketLaunch)
val DEFAULT_TIERS = mapOf(
    "surv" to listOf("Rock solid", "Strong", "Steady", "Fragile", "Distressed"),
    "qual" to listOf("Excellent", "Good", "Average", "Below average", "Poor"),
    "val" to listOf("Deep value", "Undervalued", "Fairly valued", "Rich", "Overvalued"),
    "mgmt" to listOf("Exemplary", "Trustworthy", "Adequate", "Questionable", "Red flag"),
    "mom" to listOf("Surging", "Strong", "Building", "Neutral", "Weak"),
    "disc" to listOf("Undiscovered", "Early discovery", "Being discovered", "Well discovered", "Crowded"),
    "out" to listOf("Very strong", "Strong", "Moderate", "Limited", "No trigger"),
)

object TierC {
    val darkGreen = Color(0xFF1E9E5A)
    val lightGreen = Color(0xFF8BDB8F)
    val yellow = Color(0xFFF2C94C)
    val lightRed = Color(0xFFF2908A)
    val red = Color(0xFFE5483B)
    val grey = Color(0xFF6B7075)
}

fun tierColor(t: Int): Color = when (t) {
    1 -> TierC.darkGreen; 2 -> TierC.lightGreen; 3 -> TierC.yellow; 4 -> TierC.lightRed; 5 -> TierC.red; else -> TierC.grey
}

fun tierName(st: AppState, level: Int, t: Int, grey: String? = null): String {
    val k = LEVELS[level]
    if (t == 0) return grey ?: "Not enough data"
    return (st.picks?.tiers?.get(k) ?: DEFAULT_TIERS[k])?.getOrNull(t - 1) ?: "–"
}

fun P.levelTierName(st: AppState, level: Int): String =
    if (level == 1 && turn && tier(1) != 0) "Turnaround watch" else tierName(st, level, tier(level), gn[LEVELS[level]])

// feedback #66 #72 #73: quality always takes its spectrum colour; a turnaround is named, not coloured blue
fun P.levelColor(level: Int): Color = tierColor(tier(level))

@Composable
fun TierChip(text: String, color: Color, size: TextUnit = 11.sp) {
    Box(Modifier.clip(RoundedCornerShape(10.dp)).background(color.copy(alpha = 0.16f)).border(1.dp, color.copy(alpha = 0.55f), RoundedCornerShape(10.dp))
        .padding(horizontal = 8.dp, vertical = 2.dp), contentAlignment = Alignment.Center) {  // feedback #61: text centred in the pill
        T(text, size, color, FontWeight.SemiBold, maxLines = 1) }
}

/** Seven dots, one per funnel level, in tier colours. */
@Composable
fun LevelDots(p: P, dot: Dp = 8.dp) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
        LEVELS.indices.forEach { i -> Box(Modifier.size(dot).clip(CircleShape).background(p.levelColor(i))) }
    }
}

data class VerdictMeta(val name: String, val color: Color, val icon: ImageVector, val rule: String)

val VERDICTS = listOf(
    VerdictMeta("Prime candidate", C.teal, Icons.Rounded.Star, "Quality good+, management trustworthy+, fair or cheaper, outlook strong+"),
    VerdictMeta("Early story", C.blue, Icons.Rounded.RocketLaunch, "Outlook strong+, quality average or turnaround"),
    VerdictMeta("Undervalued quality", TierC.lightGreen, Icons.Rounded.Diamond, "Quality good+, undervalued or deep value"),
    VerdictMeta("Momentum play", Color(0xFF5FD9E8), Icons.Rounded.Bolt, "Momentum strong+, quality average+, early or being discovered"),
    VerdictMeta("Quality, priced in", C.amber, Icons.Rounded.Balance, "Quality good+, management trustworthy+, valuation rich"),
    VerdictMeta("Value watch", TierC.yellow, Icons.Rounded.LocalOffer, "Undervalued, quality average or below"),
    VerdictMeta("Watchlist", C.grey, Icons.Rounded.Visibility, "Passed the funnel; no stronger verdict yet"),
    VerdictMeta("Not enough data", TierC.grey, Icons.Rounded.HourglassEmpty, "3+ levels without enough data"),
)

fun verdictColor(v: String): Color = VERDICTS.firstOrNull { it.name == v }?.color ?: if (v == "Removed") TierC.red else C.grey

@Composable
fun VerdictChip(v: String, size: TextUnit = 11.sp) = TierChip(v, verdictColor(v), size)

val DECISION_ORDER = listOf("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell", "Not rated")
fun decisionColor(d: String?): Color = when (d) {
    "Strong Buy" -> TierC.darkGreen; "Buy" -> TierC.lightGreen; "Hold" -> TierC.yellow
    "Sell" -> TierC.lightRed; "Strong Sell" -> TierC.red; else -> TierC.grey
}
@Composable
fun DecisionChip(d: String?, size: TextUnit = 11.sp) {  // redesign: tinted pill, no border (mockup .dch)
    if (d == null) return
    val c = decisionColor(d)
    Box(Modifier.clip(RoundedCornerShape(9.dp)).background(c.copy(alpha = 0.13f)).padding(horizontal = 8.dp, vertical = 2.dp), contentAlignment = Alignment.Center) {
        T(d, size, c, FontWeight.SemiBold, maxLines = 1)
    }
}


/** Icon + text line (replaces emoji/text symbols such as ⚠ ★ ●). */
@Composable
fun IconLine(icon: androidx.compose.ui.graphics.vector.ImageVector, color: Color, text: String, size: TextUnit = 13.sp, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.Top) {
        androidx.compose.material3.Icon(icon, null, tint = color, modifier = Modifier.padding(top = 1.dp).size(16.dp))
        Spacer(Modifier.width(6.dp))
        T(text, size, color)
    }
}


/** The launcher icon (dark tile + foreground vector) for in-app headers (feedback #43). */
@Composable
fun AppLogo(size: androidx.compose.ui.unit.Dp) {
    Box(Modifier.size(size).clip(androidx.compose.foundation.shape.CircleShape).background(Color(0xFF0F1115)), contentAlignment = Alignment.Center) {
        androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(R.drawable.ic_launcher_fg), null, modifier = Modifier.requiredSize(size * 1.5f))
    }
}


/** Claude's independent audit state for a Buy / Strong Buy. */
@Composable
fun VerifiedChip(state: String?) {
    val (txt, col) = when (state) { "pass" -> "Verified" to TierC.darkGreen; "caution" -> "Audit: caution" to C.amber
        "fail" -> "Audit: failed" to C.red; else -> "Verification pending" to C.grey }
    Row(Modifier.clip(RoundedCornerShape(10.dp)).background(col.copy(alpha = 0.16f)).padding(horizontal = 8.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.material3.Icon(if (state == "pass") Icons.Rounded.Verified else Icons.Rounded.HourglassTop, null, tint = col, modifier = Modifier.size(13.dp))
        Spacer(Modifier.width(4.dp)); T(txt, 11.sp, col, FontWeight.SemiBold)
    }
}


// ---------------------------------------------------------------- Claude review status (feedback #65)
/** reviewed (verdict) / queued (position, of) / none. */
data class ReviewState(val verdict: String? = null, val date: String? = null, val pos: Int = 0, val of: Int = 0, val studied: String? = null)

fun reviewState(st: AppState, sym: String): ReviewState {
    st.research[sym]?.audit?.takeIf { it.verdict != null }?.let { return ReviewState(it.verdict, it.date) }
    // research file not loaded yet (or trimmed): the rating's own verified flag still says what Claude decided
    st.pick(sym)?.vf?.takeIf { it in setOf("pass", "caution", "fail") }?.let { return ReviewState(it) }
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    val pending = st.queue?.items.orEmpty().filter { it.task == "review" && st.research[it.symbol]?.updated != today }
    val i = pending.indexOfFirst { it.symbol == sym }
    if (i >= 0) return ReviewState(pos = i + 1, of = pending.size)
    val j = st.queue?.items.orEmpty().indexOfFirst { it.symbol == sym }
    // feedback #69: Claude has research notes (scan, thesis) but no full review yet: say so instead of "not studied"
    val studied = st.research[sym]?.updated
    return if (j >= 0) ReviewState(pos = -1, studied = studied) else ReviewState(studied = studied)
}

private val RESEARCH_SLOTS = listOf(4 * 60 + 5, 9 * 60 + 5, 14 * 60 + 5, 18 * 60 + 5, 23 * 60 + 5)

/** Research run that should reach queue position [pos] at about 6 full reviews a run (an estimate). */
fun expectedRun(pos: Int): String {
    val now = java.time.LocalTime.now(java.time.ZoneId.of("Asia/Kolkata")); val m = now.hour * 60 + now.minute
    val k = (pos - 1) / 6
    val next = RESEARCH_SLOTS.indexOfFirst { it > m }.let { if (it < 0) RESEARCH_SLOTS.size else it } + k
    val slot = RESEARCH_SLOTS[next % RESEARCH_SLOTS.size]; val day = next / RESEARCH_SLOTS.size
    return "%s%02d:%02d run".format(if (day == 0) "today " else if (day == 1) "tomorrow " else "in $day days, ", slot / 60, slot % 60)
}

fun reviewColor(v: String?): Color = when (v) { "pass" -> TierC.darkGreen; "caution" -> C.amber; "fail" -> C.red; else -> C.grey }

/** Small marker beside the decision chip: reviewed (coloured by verdict), queued, or rules only. */
@Composable
fun ReviewMark(st: AppState, sym: String) {
    val r = reviewState(st, sym)
    val (icon, col) = when {
        r.verdict != null -> Icons.Rounded.CheckCircle to reviewColor(r.verdict)
        r.pos != 0 -> Icons.Rounded.HourglassTop to C.teal
        else -> Icons.Rounded.RadioButtonUnchecked to C.dim
    }
    Icon(icon, null, tint = col, modifier = Modifier.padding(start = 4.dp).size(14.dp))
}

@Composable
fun ReviewCard(st: AppState, sym: String, p: P?, det: Detail?) {
    val r = reviewState(st, sym)
    val a = st.research[sym]?.audit
    Column(Modifier.fillMaxWidth().padding(top = 12.dp).clip(RoundedCornerShape(16.dp)).background(C.card).padding(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            T("CLAUDE'S REVIEW", 11.sp, C.grey, FontWeight.SemiBold, modifier = Modifier.weight(1f))
            a?.date?.let { T(shortDate(it), 11.sp, C.grey) }
        }
        Column(Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp)).border(1.dp, C.line, RoundedCornerShape(14.dp)).background(C.card2).padding(12.dp)) {
            when {
                a != null && r.verdict != null -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.CheckCircle, null, tint = reviewColor(r.verdict), modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                        T("Reviewed by Claude", 14.sp, modifier = Modifier.weight(1f))
                        val vc = reviewColor(r.verdict)
                        Box(Modifier.clip(RoundedCornerShape(10.dp)).background(vc.copy(alpha = 0.16f)).padding(horizontal = 10.dp, vertical = 3.dp)) {
                            T(r.verdict.uppercase(), 12.sp, vc, FontWeight.Bold)
                        }
                    }
                    a.summary?.let { T(it, 14.sp, modifier = Modifier.padding(top = 10.dp), lineHeight = 20.sp) }
                    Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ReviewTag("${a.checks.size} checks verified")
                        ReviewTag("${a.failed} failed")
                        st.research[sym]?.dataIssues?.size?.takeIf { it > 0 }?.let { ReviewTag("$it data issue${if (it > 1) "s" else ""}") }
                    }
                    T("Next review: after the next results filing", 12.sp, C.dim, modifier = Modifier.padding(top = 8.dp))
                }
                r.pos != 0 -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.HourglassTop, null, tint = C.teal, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                        T(if (r.pos > 0) "Waiting for Claude's full review" else "In Claude's research queue", 14.sp)
                    }
                    val cand = p?.cand ?: det?.decision?.candidate
                    T(if (cand != null) "Rules say ${cand.uppercase()}. Shown as Hold until Claude checks the numbers against the filing."
                      else "Claude will read the latest filings for this stock.", 13.sp, C.grey, lineHeight = 18.sp, modifier = Modifier.padding(top = 8.dp))
                    if (r.pos > 0) Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ReviewTag("Queue #${r.pos} of ${r.of}"); ReviewTag("Estimated: ${expectedRun(r.pos)}")
                    }
                }
                else -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.RadioButtonUnchecked, null, tint = C.dim, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(8.dp))
                        T(if (r.studied != null) "Researched by Claude ${r.studied}, no full review" else "Not studied by Claude", 14.sp)
                    }
                    T(if (r.studied != null) "Claude's notes (thesis, promises, flags) are in Research. A full review, which can confirm a Buy, runs when the rules rate it Buy."
                      else "Rules only: this rating comes from filed numbers and prices. Claude reviews a stock when the rules rate it Buy.",
                        13.sp, C.grey, lineHeight = 18.sp, modifier = Modifier.padding(top = 8.dp))
                }
            }
        }
    }
}

@Composable
private fun ReviewTag(t: String) = Box(Modifier.clip(RoundedCornerShape(10.dp)).background(C.chip).padding(horizontal = 8.dp, vertical = 3.dp)) { T(t, 11.sp, C.white) }
