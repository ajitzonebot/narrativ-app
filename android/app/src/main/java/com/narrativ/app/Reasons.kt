package com.narrativ.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// ================================================================ industry "Why" (feedback #90)
// data/industry_reasons.json: real-world reasons Claude wrote for each rising industry, every one with a source.
// Since 28 Nov 2026 each reason has a type, a mechanism and code labels, and each industry the four-test verdict
// (narrativ/industrywhy.py: cause, broad, numbers, before).
@Serializable data class IndReason(val date: String? = null, val text: String = "", val url: String? = null, val source: String? = null,
                                   val type: String? = null, val mechanism: String? = null, val timing: String? = null,
                                   val checked: Boolean? = null, val lasting: String? = null)
@Serializable data class IndTests(val cause: Boolean = false, val broad: Boolean = false, val numbers: Boolean = false, val before: Boolean = false)
@Serializable data class IndNumbers(@SerialName("breadth_pct") val breadth: Int? = null, @SerialName("revenue_growth_pct") val rev: Int? = null,
                                    @SerialName("profit_growth_pct") val pat: Int? = null,
                                    @SerialName("market_revenue_growth_pct") val mRev: Int? = null,
                                    @SerialName("market_profit_growth_pct") val mPat: Int? = null,
                                    @SerialName("move_start") val moveStart: String? = null, @SerialName("from_low_pct") val fromLow: Double? = null)
@Serializable data class IndReasons(val date: String? = null, val quadrant: String? = null, val reasons: List<IndReason> = emptyList(),
                                    @SerialName("none_found") val noneFound: Boolean = false, val dropped: Int? = null,
                                    val tests: IndTests? = null, val score: Int? = null, val verdict: String? = null, val lasting: String? = null,
                                    val notes: List<String> = emptyList(), val numbers: IndNumbers? = null)
@Serializable data class IndReasonsFile(val date: String? = null, val industries: Map<String, IndReasons> = emptyMap(), val source: String? = null)

// data/industry_packs.json: the numbers the reasons were written from (only the parts the app shows are decoded).
@Serializable data class IndCommodity(val series: String = "", val role: String? = null, val chg3m: Double? = null, val effect: String? = null)
@Serializable data class IndFacts(val members: Int? = null, @SerialName("rev_growth_over_10pct") val revGrowthOver10: Int? = null,
                                  @SerialName("rev_reported") val revReported: Int? = null, @SerialName("above_200_day") val above200: Int? = null,
                                  @SerialName("order_wins_30d") val orderWins: List<String>? = null,
                                  @SerialName("rating_upgrades_30d") val ratingUpgrades: List<String>? = null,
                                  val commodities: List<IndCommodity> = emptyList(), val urls: List<String> = emptyList())
@Serializable data class IndPack(val quadrant: String? = null, val r1m: Double? = null, val r3m: Double? = null, val ratio: Double? = null,
                                 val mom: Double? = null, val facts: IndFacts? = null)
@Serializable data class IndPacksFile(val date: String? = null, val industries: Map<String, IndPack> = emptyMap())

/** Both files for the Why sheet, loaded once per screen; either may be null (not written yet / offline). */
class IndustryWhyData(val reasons: IndReasonsFile?, val packs: IndPacksFile?)

@Composable
fun rememberIndustryWhy(st: AppState): IndustryWhyData {
    // cache-first, both files at once; each shows as soon as it is read
    val d by produceState(IndustryWhyData(st.repo.peek<IndReasonsFile>("data/industry_reasons.json"), st.repo.peek<IndPacksFile>("data/industry_packs.json"))) {
        launch { st.repo.cacheFirst<IndReasonsFile>("data/industry_reasons.json") { if (it != null) value = IndustryWhyData(it, value.packs) } }
        launch { st.repo.cacheFirst<IndPacksFile>("data/industry_packs.json") { if (it != null) value = IndustryWhyData(value.reasons, it) } }
    }
    return d
}

/** First sourced reason's text, for the one-line preview on list rows. */
fun IndustryWhyData.preview(name: String): String? =
    reasons?.industries?.get(name)?.reasons?.firstOrNull { it.text.isNotBlank() && !it.url.isNullOrBlank() }?.text

/** "In the data" sentence(s) from the rotation numbers and the pack facts; parts with missing numbers are left out. */
fun industryDataText(r: Rot?, p: IndPack?): String {
    val r1m = r?.r1m ?: p?.r1m
    val r3m = r?.r3m ?: p?.r3m
    val ratio = r?.ratio ?: p?.ratio
    val mom = r?.mom ?: p?.mom
    val parts = mutableListOf<String>()
    val ups = listOfNotNull(r1m?.let { "${skSgn(it)} in a month" }, r3m?.let { "${skSgn(it)} in 3 months" })
    if (ups.isNotEmpty()) parts += "Price " + ups.joinToString(" and ")
    if (ratio != null) parts += "strength vs the market ${skFx(ratio)} (100 = in line)" +
        (mom?.let { ", " + (if (it >= 100) "rising" else "easing") + " (${skFx(it)})" } ?: "")
    val out = StringBuilder()
    if (parts.isNotEmpty()) out.append(parts.joinToString("; ")).append(".")
    val f = p?.facts
    if (f != null) {
        val fp = mutableListOf<String>()
        if (f.revGrowthOver10 != null && f.revReported != null) fp += "${f.revGrowthOver10} of ${f.revReported} grew revenue more than 10% last quarter"
        if (f.above200 != null && f.members != null) fp += "${f.above200} of ${f.members} above their 200-day average"
        if (f.orderWins != null || f.ratingUpgrades != null)
            fp += "${f.orderWins?.size ?: 0} order wins and ${f.ratingUpgrades?.size ?: 0} rating upgrades filed in 30 days"
        if (fp.isNotEmpty()) { if (out.isNotEmpty()) out.append(" "); out.append(fp.joinToString("; ").replaceFirstChar { it.uppercase() }).append(".") }
        f.commodities.filter { it.effect == "tailwind" || it.effect == "headwind" }.forEach { c ->
            if (c.chg3m == null || c.series.isBlank()) return@forEach
            if (out.isNotEmpty()) out.append("\n")
            out.append("${c.series}: ${skSgn(c.chg3m)} in 3 months (${c.effect})")
        }
    }
    return out.toString()
}

/** The industry's Why sheet: sourced reasons, the numbers behind the move, and a link to its stocks. */
@Composable
fun IndustryWhySheet(st: AppState, name: String, rot: Rot?, data: IndustryWhyData, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val entry = data.reasons?.industries?.get(name)
    val pack = data.packs?.industries?.get(name)
    val q = rot?.q?.takeIf { it.isNotBlank() } ?: entry?.quadrant ?: pack?.quadrant
    BottomSheet(onDismiss, title = name, titleExtra = if (q != null) { { QuadPill(q) } } else null) {
        entry?.takeIf { it.tests != null && it.verdict != null }?.let { IndustryVerdict(it) }
        T("What's driving it", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.padding(bottom = 8.dp))
        val shown = entry?.reasons.orEmpty().filter { it.text.isNotBlank() && !it.url.isNullOrBlank() }
        when {
            shown.isNotEmpty() -> shown.forEach { rs ->
                Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.Top) {
                    T(skDay(rs.date), 12.sp, C.dim, modifier = Modifier.width(52.dp).padding(top = 1.dp), maxLines = 1)
                    Column(Modifier.weight(1f)) {
                        reasonTag(rs)?.let { T(it, 11.sp, C.dim, FontWeight.SemiBold, maxLines = 1, modifier = Modifier.padding(bottom = 2.dp)) }
                        T(rs.text, 13.sp, C.muted, lineHeight = 19.sp)
                        rs.mechanism?.takeIf { it.isNotBlank() }?.let { T("How it helps: $it", 12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 2.dp)) }
                        if (rs.checked == false) T("Source could not be read to check the quote, so it is not counted as the cause.", 12.sp, C.dim, lineHeight = 17.sp)
                        T("Source ›", 13.sp, C.blue, maxLines = 1,
                            modifier = Modifier.padding(top = 2.dp).clickable { rs.url?.let { openUrl(ctx, it) } })
                    }
                }
            }
            entry?.noneFound == true -> T("No single event found for this move; it shows in prices only.", 13.sp, C.muted, lineHeight = 19.sp)
            else -> T("Narrativ.ai hasn't written the reasons yet (written weekly for rising industries).", 13.sp, C.muted, lineHeight = 19.sp)
        }
        val dataText = industryDataText(rot, pack)
        if (dataText.isNotBlank()) {
            T("In the data", 12.sp, C.dim, FontWeight.SemiBold, modifier = Modifier.padding(top = 16.dp, bottom = 4.dp))
            T(dataText, 12.sp, C.dim, lineHeight = 17.sp)
        }
        T("Written by Narrativ.ai from the linked sources" + (entry?.date?.let { ", ${skDay(it)}" } ?: "") + ". A reason without a source is not shown.",
            12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 16.dp))
        // the count of the list the link opens (audit 26 Nov 2026: rotation n counted stocks with a price series)
        val n = st.picks?.picks?.count { Filt(industry = name, industryExact = true).match(it) }?.takeIf { it > 0 } ?: rot?.n ?: pack?.facts?.members
        MoreLink(if (n != null) "See the $n stocks" else "See the stocks") { onDismiss(); st.go(Screen.Screener("ind:$name")) }
    }
}

private val REASON_TYPE = mapOf("policy" to "Policy", "rates" to "Interest rates", "demand" to "Demand", "prices" to "Prices and margins",
    "supply" to "Supply", "orders" to "Orders", "global" to "Global cycle", "flow" to "Fund flows")

/** "Policy · before the rally · lasting": the reason's type and the code's labels. */
fun reasonTag(r: IndReason): String? {
    val parts = listOfNotNull(r.type?.let { REASON_TYPE[it] ?: it },
        when (r.timing) { "before" -> "before the rally"; "after" -> "after the rally began"; else -> null },
        when (r.lasting) { "structural" -> "lasting"; "one_time" -> "one-time"; else -> null })
    return parts.takeIf { it.isNotEmpty() }?.joinToString(" · ")
}

/** The four tests behind "is this lead legitimate?" (narrativ/industrywhy.py), with the numbers they used. */
@Composable
fun IndustryVerdict(e: IndReasons) {
    val t = e.tests ?: return
    val n = e.numbers
    val col = when (e.score ?: 0) { 4 -> C.teal; 2, 3 -> C.amber; else -> C.red }
    val head = (e.verdict ?: "") + when (e.lasting) { "structural" -> " · lasting"; "one_time" -> " · one-time"; else -> "" }
    T(head, 15.sp, col, FontWeight.SemiBold, modifier = Modifier.padding(bottom = 6.dp))
    fun pct(x: Int?) = x?.let { "$it%" }
    val rows = listOf(
        Triple(t.cause, "A real event behind it", "not the price move or a broker tip; quote checked in the source"),
        Triple(t.broad, "Most of its stocks are rising", pct(n?.breadth)?.let { "$it above their 200-day average" } ?: ""),
        Triple(t.numbers, "It shows in results", listOfNotNull(
            n?.rev?.let { "$it% grew revenue over 10%" + (n?.mRev?.let { m -> " (market $m%)" } ?: "") },
            n?.pat?.let { "$it% grew profit over 10%" + (n?.mPat?.let { m -> " (market $m%)" } ?: "") }).joinToString("; ")),
        Triple(t.before, "The cause came before the rally", n?.moveStart?.let { "rally from ${skDay(it)}" + (n?.fromLow?.let { f -> ", ${skSgn(f)} since" } ?: "") } ?: ""),
    )
    rows.forEach { (ok, label, sub) ->
        Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
            T(if (ok) "✓" else "✗", 13.sp, if (ok) C.teal else C.red, FontWeight.SemiBold, modifier = Modifier.width(20.dp))
            Column(Modifier.weight(1f)) {
                T(label, 13.sp, C.muted)
                if (sub.isNotBlank()) T(sub, 12.sp, C.dim, lineHeight = 16.sp)
            }
        }
    }
    e.notes.forEach { T(it.replaceFirstChar { c -> c.uppercase() } + ".", 12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(top = 4.dp)) }
    Spacer(Modifier.height(14.dp))
}
