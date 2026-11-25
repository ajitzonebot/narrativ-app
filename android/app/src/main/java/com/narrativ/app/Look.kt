package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * One look everywhere (owner, 24 Nov 2026, UI consistency mock-ups): every screen takes these words, formats and colours
 * from here, so the same thing reads the same on Home, Stocks, Market and the stock page.
 *  - colour: blue (C.teal / C.blue) only for things you tap; green/red for good/bad; one palette per concept.
 *  - numbers: skFx / skSgn (one decimal, true minus), "×" on multiples, "₹a–b" ranges, "–" when missing.
 *  - dates: skDay ("24 Nov", year only when not this year); never a raw ISO date.
 */

/** Sector / industry rotation, every screen. */
fun quadC(q: String?): Color = when (q) {
    "Leading" -> TierC.lightGreen; "Improving" -> TierC.yellow; "Weakening" -> C.amber; "Lagging" -> TierC.lightRed; else -> C.grey
}
val QUAD_COLORS = mapOf("Leading" to quadC("Leading"), "Improving" to quadC("Improving"), "Weakening" to quadC("Weakening"), "Lagging" to quadC("Lagging"))

/** A multiple: "1.2×". */
fun mult(v: Double?, d: Int = 1): String = if (v == null) "–" else skFx(v, d) + "×"

/** A price range: "₹100–120". */
fun rangeStr(lo: Double?, hi: Double?): String = if (lo == null || hi == null) "–" else "₹${priceNum(lo)}–${priceNum(hi)}"
private fun priceNum(v: Double): String = fmt(v, if (v >= 100) 0 else 2)

/** "vs Nifty" is always in points. */
fun vsNifty(v: Double?): String = skSgn(v, 1, " pts")

/** Setup name in lists and on the Plan card. */
fun setupName(su: String?, trendBroken: Boolean = false): String = when (su) {
    "Breakout" -> "Breaking out"; "Pullback" -> "Dip in uptrend"; "Base" -> "Near entry"
    null, "" -> "No data"
    else -> if (trendBroken) "Avoid · trend broken" else "Wait"
}
fun setupColor(su: String?, trendBroken: Boolean = false): Color = when {
    su in setOf("Breakout", "Pullback", "Base") -> TierC.lightGreen
    trendBroken -> TierC.lightRed
    else -> C.grey
}

/** Claude's review verdict: one colour and sentence case everywhere. */
fun reviewWord(v: String?): String = when (v) { "pass" -> "Pass"; "caution" -> "Caution"; "fail" -> "Fail"; null -> "Not reviewed"; else -> sentence(v) }

/** Today's Top 10 exactly as Home shows it: open IPOs first, then verified Buys in the pipeline's order. */
data class TopTen(val ipos: List<IpoOpen>, val stocks: List<P>, val pendingReview: Int, val buys: Int)

/** What [topTen] was last computed from (compared by identity) and its result: a scan of all picks only when one of them changes. */
class TopTenMemo(val pf: PicksFile, val rot: RotationFile?, val ipo: IpoToday?, val today: String, val value: TopTen)

fun topTen(st: AppState): TopTen? {
    val pf = st.picks ?: return null
    val rot = st.rotation
    val ipo = st.ipo
    val today = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")).toString()
    st.topTenMemo?.let { m -> if (m.pf === pf && m.rot === rot && m.ipo === ipo && m.today == today) return m.value }
    return computeTopTen(pf, rot, ipo, today).also { st.topTenMemo = TopTenMemo(pf, rot, ipo, today, it) }
}

private fun computeTopTen(pf: PicksFile, rot: RotationFile?, ipo: IpoToday?, today: String): TopTen {
    val live = pf.picks.filter { it.out == null }
    val marketUp = pf.regime.niftyAbove == true
    fun setup(p: P): Int = listOf(
        marketUp,
        rot?.industries?.get(p.i ?: "")?.q in setOf("Leading", "Improving"),
        p.t.getOrNull(0) in setOf(1, 2) && p.t.getOrNull(1) in setOf(1, 2),
        p.t.getOrNull(5) in setOf(2, 3),
        p.t.getOrNull(6) in setOf(1, 2),
        p.su in setOf("Breakout", "Pullback", "Base"),
    ).count { it }
    val buys = live.filter { isBuy(it) }
    val bySym = buys.associateBy { it.s }
    val ranked = pf.top10.mapNotNull { bySym[it] }.filter { it.verified() }.ifEmpty {
        buys.filter { it.verified() }.sortedWith(compareBy<P> { it.rk ?: Int.MAX_VALUE }.thenByDescending { setup(it) }.thenByDescending { it.pr }).take(10) }
    val ipoTop = ipo?.takeIf { it.date == today }?.actionable.orEmpty().filter { it.top10 }
    return TopTen(ipoTop, ranked.take((10 - ipoTop.size).coerceAtLeast(0)), buys.count { !it.verified() }, buys.size)
}

/** The stock's rank in today's Top 10 as Home numbers it, or null. */
fun topTenRank(st: AppState, sym: String): Int? = topTen(st)?.let { t -> t.stocks.indexOfFirst { it.s == sym }.takeIf { it >= 0 }?.let { t.ipos.size + it + 1 } }

/** "Review 2 of 5": position among Claude's pending review tasks (reviewState), the one count every screen uses. */
fun queueLabel(st: AppState, sym: String): String? = reviewState(st, sym).takeIf { it.pos > 0 }?.let { "Review ${it.pos} of ${it.of}" }

/** The one primary button: blue, white text. */
@Composable
fun PrimaryButton(text: String, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    Box(modifier.height(48.dp).clip(RoundedCornerShape(24.dp)).background(if (enabled) C.teal else C.chip)
        .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 22.dp), contentAlignment = Alignment.Center) {
        T(text, 15.sp, if (enabled) Color.White else C.dim, FontWeight.SemiBold, maxLines = 1)
    }
}

/** Section title inside a card / screen section (15, semibold, sentence case); screen titles stay 21. */
val SECTION_TITLE = 15.sp
val LABEL = 12.sp
