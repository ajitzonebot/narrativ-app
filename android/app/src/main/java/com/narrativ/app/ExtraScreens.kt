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

// ---------------------------------------------------------------- Settings sub-screens (feedback #40, #41)
@Composable
fun SubScreen(st: AppState, title: String, subtitle: String?, content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit) {
    LazyColumn(Modifier.fillMaxSize().background(C.screen), contentPadding = PaddingValues(bottom = 110.dp)) {
        item { Header(st, title, subtitle, title, back = true) }
        content()
    }
}

@Serializable data class FbItem(val n: Int = 0, val state: String = "", val type: String = "", val text: String = "", val screen: String = "", val date: String = "")

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


@Serializable data class RunRec(val date: String = "", val finished: String = "", val minutes: Double? = null, val problems: Int = 0)

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
