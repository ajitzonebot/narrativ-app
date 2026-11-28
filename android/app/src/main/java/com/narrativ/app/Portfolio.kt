package com.narrativ.app

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Upload
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.net.URLEncoder
import java.time.DayOfWeek
import java.time.Duration
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit

/** Owner's holdings (Settings › Portfolio). Kept only in this phone's app storage: never sent to GitHub or Cloudflare. */
@Serializable data class Holding(val s: String, val qty: Double, val avg: Double, val fileLtp: Double? = null)
/** [idx] is the time-weighted index (starts at 100; money added or taken out by a re-import is not counted as return). */
@Serializable data class PortSnap(val d: String, val value: Double, val invested: Double, val nifty: Double? = null, val idx: Double? = null)
@Serializable data class PortStore(val imported: String? = null, val holdings: List<Holding> = emptyList(), val snaps: List<PortSnap> = emptyList(),
                            /** Market value added (+) or taken out (-) by re-imports since the last snapshot. */
                            val flow: Double = 0.0)
@Serializable data class ExtraPrices(val date: String? = null, val prices: Map<String, List<Double?>> = emptyMap())
data class Quote(val p: Double, val prev: Double?, val t: Long?) { val d1: Double? get() = prev?.takeIf { it > 0 }?.let { (p / it - 1) * 100 } }

private val IST: ZoneId = ZoneId.of("Asia/Kolkata")

object Portfolio {
    private val lock = Mutex()  // load-change-save steps (daily snapshot, import) never interleave

    /** Own preferences file, so backup rules can leave the holdings out while the rest of the app's settings stay eligible. */
    private fun prefs(ctx: Context): android.content.SharedPreferences {
        val p = ctx.getSharedPreferences("narrativ_portfolio", Context.MODE_PRIVATE)
        val old = ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE)
        old.getString("portfolio", null)?.let { v ->  // holdings saved by an earlier version: move them over
            if (!p.contains("portfolio")) p.edit().putString("portfolio", v).commit()
            old.edit().remove("portfolio").apply()
        }
        return p
    }
    /** Last decoded holdings and their saved text: the Portfolio tab does not decode the same text again on the main thread. */
    @Volatile private var loaded: Pair<String, PortStore>? = null
    fun load(ctx: Context): PortStore {
        val raw = prefs(ctx).getString("portfolio", null) ?: "{}"
        loaded?.let { if (it.first == raw) return it.second }
        return runCatching { json.decodeFromString<PortStore>(raw) }.getOrDefault(PortStore()).also { loaded = raw to it }
    }
    fun save(ctx: Context, p: PortStore) = prefs(ctx).edit().putString("portfolio", json.encodeToString(p)).apply()

    /** One CSV line into fields (quotes and commas inside quotes handled). */
    private fun fields(line: String): List<String> {
        val out = mutableListOf<String>(); val cur = StringBuilder(); var q = false
        for (ch in line) {
            when {
                ch == '"' -> q = !q
                ch == ',' && !q -> { out.add(cur.toString().trim()); cur.clear() }
                else -> cur.append(ch)
            }
        }
        out.add(cur.toString().trim())
        return out
    }

    /** Zerodha holdings CSV: Instrument, Qty., Avg. cost, LTP, ... */
    fun parse(text: String): List<Holding> =
        parseRows(text.removePrefix("\uFEFF").lines().filter { it.isNotBlank() }.map { fields(it) })

    /** A holdings file's bytes: Zerodha's Excel export (.xlsx) or the CSV. */
    fun parseFile(bytes: ByteArray): List<Holding> =
        if (Xlsx.isZip(bytes)) parseRows(Xlsx.rows(bytes)) else parse(bytes.toString(Charsets.UTF_8))

    private fun clean(h: String) = h.trim().trimStart('\uFEFF').lowercase()
    private fun isSym(h: String) = h.startsWith("instrument") || h == "symbol" || h == "trading symbol" || h == "tradingsymbol"
    private fun isQty(h: String) = h.startsWith("qty") || h.startsWith("quantity")
    private fun isAvg(h: String) = h.startsWith("avg") || h.startsWith("average")
    private fun isLtp(h: String) = h == "ltp" || h == "previous closing price" || h == "close price"

    /**
     * Holdings from table rows: the header is the first row naming the symbol (Instrument / Symbol), the quantity (Qty. / Quantity Available)
     * and the average cost (Avg. cost / Average Price), case-insensitive; rows above it (the .xlsx title block) are skipped.
     */
    fun parseRows(rows: List<List<String>>): List<Holding> {
        val hi = rows.indexOfFirst { r -> val h = r.map(::clean); h.any(::isSym) && h.any(::isQty) && h.any(::isAvg) }
        if (hi < 0) return emptyList()
        val head = rows[hi].map(::clean)
        val iS = head.indexOfFirst(::isSym); val iQ = head.indexOfFirst(::isQty); val iA = head.indexOfFirst(::isAvg)
        val iL = head.indexOfFirst { it == "ltp" }.takeIf { it >= 0 } ?: head.indexOfFirst(::isLtp)
        fun num(f: List<String>, i: Int) = f.getOrNull(i)?.replace(",", "")?.trim()?.toDoubleOrNull()
        return rows.drop(hi + 1).mapNotNull { f ->
            val s = f.getOrNull(iS)?.trim()?.uppercase()?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val q = num(f, iQ) ?: return@mapNotNull null
            Holding(s, q, num(f, iA) ?: 0.0, if (iL >= 0) num(f, iL) else null)
        }.filter { it.qty > 0 }
    }

    /** Mon-Fri 09:14-15:35 IST, except NSE trading holidays (docs/data/holidays.json, "YYYY-MM-DD"). No file: weekdays only, as before. */
    fun marketOpen(now: ZonedDateTime = ZonedDateTime.now(IST), holidays: Set<String> = emptySet()): Boolean =
        now.dayOfWeek !in setOf(DayOfWeek.SATURDAY, DayOfWeek.SUNDAY) && now.toLocalDate().toString() !in holidays &&
            now.toLocalTime() in LocalTime.of(9, 14)..LocalTime.of(15, 35)

    private var holidayCache: Pair<Long, Set<String>>? = null

    /** NSE trading holidays, read through Repo (network, then the copy cached on the phone); empty when the file is missing. Kept 6 hours. */
    suspend fun holidays(repo: Repo): Set<String> {
        holidayCache?.let { if (System.currentTimeMillis() - it.first < 6 * 3600_000L) return it.second }
        val set = repo.get<Holidays>("data/holidays.json")?.tradingHolidays?.toSet() ?: emptySet()
        holidayCache = System.currentTimeMillis() to set
        return set
    }

    /** Delayed quotes from the Narrativ API (/quotes: Yahoo chart endpoint, unofficial; only symbols are sent). */
    suspend fun quotes(repo: Repo, syms: List<String>): Map<String, Quote> {
        val out = mutableMapOf<String, Quote>()
        syms.distinct().chunked(40).forEach { ch ->
            val o = repo.apiGet("quotes?s=" + URLEncoder.encode(ch.joinToString(","), "UTF-8")) ?: return@forEach
            (o["quotes"] as? JsonObject)?.forEach { (k, v) ->
                val m = v.jsonObject
                val p = m["p"]?.jsonPrimitive?.doubleOrNull ?: return@forEach
                out[k] = Quote(p, m["prev"]?.jsonPrimitive?.doubleOrNull, m["t"]?.jsonPrimitive?.longOrNull)
            }
        }
        return out
    }

    /** Price and day change (%) of a holding: scored stock from picks, else ETF / other from extra_prices. */
    fun price(s: String, picks: Map<String, P>, extra: ExtraPrices?): Pair<Double?, Double?> {
        pickFor(s, picks)?.let { return it.p to it.d1 }
        extra?.prices?.get(s)?.let { return it.getOrNull(0) to it.getOrNull(1) }
        return null to null
    }

    /** A holding's scored stock: Zerodha lists the bare symbol, picks hold it as SYMBOL.NS or (BSE only) SYMBOL.BO. */
    fun pickFor(s: String, picks: Map<String, P>): P? = picks["$s.NS"] ?: picks["$s.BO"]

    /** Time-weighted index per snapshot (100 at the first): the value moves with prices, not with money added or taken out. */
    fun series(snaps: List<PortSnap>): List<Double> {
        val out = ArrayList<Double>(snaps.size)
        snaps.forEachIndexed { i, s ->
            out.add(s.idx ?: if (i == 0) 100.0 else if (snaps[i - 1].value > 0) out[i - 1] * s.value / snaps[i - 1].value else out[i - 1])
        }
        return out
    }

    /** Market value of what a re-import adds (+) or removes (-), at the prices the daily snapshot uses. */
    private fun flowOf(old: List<Holding>, new: List<Holding>, picks: Map<String, P>, ex: ExtraPrices?): Double {
        val oq = old.associateBy { it.s }; val nq = new.associateBy { it.s }
        return (oq.keys + nq.keys).sumOf { s ->
            val o = oq[s]; val n = nq[s]
            val px = price(s, picks, ex).first ?: n?.fileLtp ?: o?.fileLtp ?: n?.avg ?: o?.avg ?: 0.0
            ((n?.qty ?: 0.0) - (o?.qty ?: 0.0)) * px
        }
    }

    /** Adds the point for the data date of [pf] (value, invested, Nifty, index) unless it is already there. Caller holds [lock]. */
    private fun withSnap(st: PortStore, pf: PicksFile, ex: ExtraPrices?): PortStore {
        if (st.holdings.isEmpty()) return st
        val d = pf.date ?: return st
        if (st.snaps.lastOrNull()?.d == d) return st
        val m = pf.picks.associateBy { it.s }
        var value = 0.0; var inv = 0.0
        st.holdings.forEach { h -> value += h.qty * (price(h.s, m, ex).first ?: h.fileLtp ?: 0.0); inv += h.qty * h.avg }
        val prev = st.snaps.lastOrNull()
        val base = if (prev == null) 0.0 else prev.value + st.flow  // value of today's units at the previous close
        val idx = if (prev == null) 100.0 else series(st.snaps).last().let { if (base > 0) it * value / base else it }
        return st.copy(snaps = (st.snaps + PortSnap(d, value, inv, ex?.prices?.get("NIFTY 50")?.getOrNull(0), idx)).takeLast(1000), flow = 0.0)
    }

    /** Record one point a day (the data date of picks.json): value, invested, Nifty. Called by the daily job and on open.
     *  [picks]: the app's picks already loaded (the screen passes them, so picks.json is not downloaded again). */
    suspend fun snapshot(ctx: Context, repo: Repo, picks: PicksFile? = null) {
        if (load(ctx).holdings.isEmpty()) return
        val pf = picks ?: repo.get<PicksFile>("data/picks.json") ?: return
        val ex = repo.get<ExtraPrices>("data/extra_prices.json")
        lock.withLock {
            val st = load(ctx)
            val n = withSnap(st, pf, ex)
            if (n !== st) save(ctx, n)
        }
    }

    /** Replace the holdings with a fresh import. The series is closed first at the latest data date with the old holdings, and the
     *  money the new holdings add or remove is recorded as a cash flow, so buying more is not shown as a gain against the Nifty. */
    suspend fun importHoldings(ctx: Context, repo: Repo, h: List<Holding>, picks: PicksFile? = null): PortStore {
        val pf = picks ?: repo.get<PicksFile>("data/picks.json")
        val ex = repo.get<ExtraPrices>("data/extra_prices.json")
        return lock.withLock {
            var st = load(ctx)
            if (st.holdings.isNotEmpty() && pf != null) st = withSnap(st, pf, ex)
            val flow = if (st.holdings.isEmpty()) 0.0 else flowOf(st.holdings, h, pf?.picks?.associateBy { it.s }.orEmpty(), ex)
            st = st.copy(imported = java.time.LocalDate.now(IST).toString(), holdings = h, flow = st.flow + flow)
            save(ctx, st)
            st
        }
    }

    fun schedule(ctx: Context) {
        val now = ZonedDateTime.now(IST)
        var at = now.withHour(18).withMinute(30).withSecond(0)
        if (at.isBefore(now)) at = at.plusDays(1)
        val req = PeriodicWorkRequestBuilder<PortfolioWorker>(1, TimeUnit.DAYS)
            .setInitialDelay(Duration.between(now, at).toMinutes(), TimeUnit.MINUTES).addTag("portfolio").build()
        WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("portfolio-daily", ExistingPeriodicWorkPolicy.KEEP, req)
    }
}

class PortfolioWorker(ctx: Context, p: WorkerParameters) : CoroutineWorker(ctx, p) {
    override suspend fun doWork(): Result {
        runCatching { Portfolio.snapshot(applicationContext, Repo(applicationContext)) }
        return Result.success()
    }
}

/** Polls delayed quotes every minute while shown and the market is open. Empty outside market hours. */
@Composable
fun rememberLiveQuotes(st: AppState, syms: List<String>): Map<String, Quote> {
    var q by remember { mutableStateOf<Map<String, Quote>>(emptyMap()) }
    val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    LaunchedEffect(syms, owner) {
        // polls only while the app is on screen (STARTED), on NSE trading days in market hours
        owner.lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
            while (true) {
                if (syms.isNotEmpty() && Portfolio.marketOpen(holidays = Portfolio.holidays(st.repo))) q = q + Portfolio.quotes(st.repo, syms)
                delay(60_000)
            }
        }
    }
    return q
}

fun quoteTime(q: Map<String, Quote>): String? = q.values.mapNotNull { it.t }.maxOrNull()?.let {
    java.time.Instant.ofEpochSecond(it).atZone(IST).toLocalTime().toString().take(5)
}

private fun rupees(v: Double): String = (if (v < 0) "−" else "") + if (kotlin.math.abs(v) >= 1e5) "₹${fmt(kotlin.math.abs(v) / 1e5, 2)} L" else "₹${fmt(kotlin.math.abs(v), 0)}"

/** A holding's Narrativ decision as chip text, colour and the group it counts in (null: ETF or an equity Narrativ does not score). */
internal data class Dg(val group: String, val text: String, val color: Color)
internal fun decisionOf(p: P?): Dg? = when {
    p == null -> null
    p.dc in setOf("Sell", "Strong Sell") -> Dg("Sell", p.dc ?: "Sell", decisionColor(p.dc))
    p.vf in setOf("caution", "fail") -> Dg("Hold", "${p.dc ?: "Hold"} · Caution", reviewColor("caution"))  // Claude's caution, its one colour
    p.dc in setOf("Buy", "Strong Buy") -> Dg("Buy", p.dc ?: "Buy", decisionColor(p.dc))
    p.dc == "Hold" -> Dg("Hold", "Hold", decisionColor("Hold"))
    else -> Dg("Not rated", p.dc ?: "Not rated", decisionColor(null))
}
private val DEC_BAR get() = listOf("Buy", "Hold", "Sell", "Not rated").associateWith { decisionColor(it) }

/** Pill in a header ("Import"). */
@Composable
fun HeaderPill(icon: androidx.compose.ui.graphics.vector.ImageVector, text: String, onClick: () -> Unit) {
    Row(Modifier.height(36.dp).clip(rr(18.dp)).background(C.hi.copy(alpha = 0.08f)).clickable(onClick = onClick).padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        androidx.compose.material3.Icon(icon, null, tint = C.white, modifier = Modifier.size(16.dp))
        T(text, 13.sp, weight = FontWeight.Medium, maxLines = 1)
    }
}

/** Section heading with a small grey count / note beside it. */
@Composable
fun SecHead(title: String, sub: String = "", modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 8.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        T(title, SECTION_TITLE, weight = FontWeight.SemiBold, maxLines = 1)
        if (sub.isNotEmpty()) T(sub, 12.sp, C.dim, maxLines = 1, modifier = Modifier.padding(bottom = 1.dp))
    }
}

/** Today's move of a holding as a tiny bar left (down) or right (up) of a centre line; full width at ±[scale] %. */
@Composable
fun MiniDiv(v: Double?, modifier: Modifier = Modifier.size(44.dp, 8.dp), scale: Double = 4.0) {
    androidx.compose.foundation.Canvas(modifier) {
        val half = size.width / 2; val cy = size.height / 2
        drawRoundRect(TRACK, androidx.compose.ui.geometry.Offset(0f, cy - 1.dp.toPx()), androidx.compose.ui.geometry.Size(size.width, 2.dp.toPx()),
            androidx.compose.ui.geometry.CornerRadius(1.dp.toPx()))
        if (v == null) return@Canvas
        val len = (kotlin.math.abs(v) / scale).coerceIn(0.0, 1.0).toFloat() * half
        val w = maxOf(len, 2.dp.toPx())
        drawRoundRect(if (v >= 0) TierC.lightGreen else TierC.lightRed, androidx.compose.ui.geometry.Offset(if (v >= 0) half else half - w, cy - 3.dp.toPx()),
            androidx.compose.ui.geometry.Size(w, 6.dp.toPx()), androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()))
    }
}

@Composable
fun PortfolioScreen(st: AppState) {
    val ctx = LocalContext.current
    var store by remember { mutableStateOf(Portfolio.load(ctx)) }
    val scope = rememberCoroutineScope()
    val extra by produceState(st.repo.peek<ExtraPrices>("data/extra_prices.json")) { st.repo.cacheFirst<ExtraPrices>("data/extra_prices.json") { if (it != null) value = it } }
    LaunchedEffect(store.holdings) { if (store.holdings.isNotEmpty()) { Portfolio.snapshot(ctx, st.repo, st.picks); store = withContext(Dispatchers.IO) { Portfolio.load(ctx) } } }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            val h = withContext(Dispatchers.IO) {
                val bytes = runCatching { ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } }.getOrNull()
                bytes?.let { runCatching { Portfolio.parseFile(it) }.getOrNull() }.orEmpty()
            }
            if (h.isEmpty()) st.toast = "No holdings found: pick the Zerodha holdings file (.xlsx or .csv)"
            else {
                store = withContext(Dispatchers.IO) { Portfolio.importHoldings(ctx, st.repo, h, st.picks) }
                st.toast = "Imported ${h.size} holdings"
            }
        }
    }
    // feedback #91: Zerodha's holdings export is an Excel .xlsx; the CSV still works ("*/*" for pickers that label either file oddly)
    fun launchImport() = pick.launch(arrayOf("text/csv", "text/comma-separated-values", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel", "text/*", "application/octet-stream", "*/*"))
    val pf = st.picks
    val picks = remember(pf) { pf?.picks?.associateBy { it.s }.orEmpty() }  // once per picks.json, not every recomposition
    val live = rememberLiveQuotes(st, store.holdings.map { it.s })
    fun now(h: Holding): Pair<Double?, Double?> = live[h.s]?.let { it.p to it.d1 } ?: Portfolio.price(h.s, picks, extra).let { (p, d) -> (p ?: h.fileLtp) to d }
    var sent by remember { mutableStateOf(false) }
    var etfOpen by remember { mutableStateOf(false) }
    if (sent) BottomSheet({ sent = false }, "What leaves this phone") {
        T("Your holdings (symbols, quantities, cost) are kept only in this phone's app storage: not sent to GitHub, Cloudflare or anyone, and left out of Android backups. Uninstalling the app deletes them.",
            14.sp, lineHeight = 20.sp)
        T("Live prices: only the stock symbols are sent to the Narrativ server to fetch delayed quotes (unofficial source). Quantities and cost never are.",
            14.sp, C.muted, lineHeight = 20.sp, modifier = Modifier.padding(top = 10.dp))
    }
    val has = store.holdings.isNotEmpty()
    LazyColumn(Modifier.fillMaxSize().pageBackground(), contentPadding = PaddingValues(bottom = 110.dp)) {
        item {
            TopBar(st, "Portfolio", subtitle = if (has) "${store.holdings.size} holdings · imported ${shortDate(store.imported)} · stays on this phone" else null,
                back = false, big = true) { if (has) HeaderPill(Icons.Rounded.Upload, "Import") { launchImport() } }
        }
        if (!has) {
            item {
                Column(Modifier.fillMaxWidth().padding(horizontal = 28.dp).padding(top = 72.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(Modifier.size(84.dp).clip(rr(26.dp)).background(C.teal.copy(alpha = 0.18f)), contentAlignment = Alignment.Center) {
                        androidx.compose.material3.Icon(Icons.Rounded.Upload, null, tint = C.blue, modifier = Modifier.size(38.dp))
                    }
                    T("Track your holdings", 24.sp, weight = FontWeight.Bold, modifier = Modifier.padding(top = 24.dp))
                    T("Import your Zerodha holdings file (Excel .xlsx or CSV).", 14.sp, C.dim, lineHeight = 20.sp,
                        align = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.padding(top = 8.dp, bottom = 28.dp))
                    PrimaryButton("Import Zerodha holdings", Modifier.fillMaxWidth()) { launchImport() }
                    Row(Modifier.padding(top = 22.dp), verticalAlignment = Alignment.CenterVertically) {
                        androidx.compose.material3.Icon(Icons.Rounded.Lock, null, tint = C.dim, modifier = Modifier.size(16.dp))
                        T("  Kept only on this phone. Never uploaded.", 13.sp, C.dim)
                    }
                    MoreLink("What is sent for prices", Modifier.padding(top = 6.dp)) { sent = true }
                }
            }
            return@LazyColumn
        }
        val rows = store.holdings.map { h -> Triple(h, now(h).first, now(h).second) }
        val value = rows.sumOf { (h, p, _) -> h.qty * (p ?: 0.0) }
        val inv = rows.sumOf { (h, _, _) -> h.qty * h.avg }
        val today = rows.sumOf { (h, p, d) -> if (p != null && d != null) h.qty * p * d / (100 + d) else 0.0 }
        val pl = value - inv
        val plPct = if (inv > 0) pl / inv * 100 else null
        val todayPct = if (value - today > 0) today / (value - today) * 100 else null
        if (Look.paper) item { PaperLedgerFront(rows, picks, value, inv, today, todayPct, pl, plPct) }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 16.dp) {
                if (!Look.paper) Row(verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) { T("Current value", LABEL, C.dim); T(rupees(value), 28.sp, weight = FontWeight.Bold, maxLines = 1) }
                    Column(horizontalAlignment = Alignment.End) { T("Invested", LABEL, C.dim); T(rupees(inv), 16.sp, C.muted, FontWeight.SemiBold, modifier = Modifier.padding(top = 6.dp)) }
                }
                if (!Look.paper) Row(Modifier.padding(top = 14.dp)) {
                    Column(Modifier.weight(1f)) {
                        T("Total P&L", LABEL, C.dim)
                        T("${rupees(pl)} · ${sg(plPct, 1)}", 15.sp, plColor(pl), FontWeight.Bold, maxLines = 1)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        T("Today", LABEL, C.dim)
                        T("${rupees(today)} · ${sg(todayPct, 1)}", 15.sp, plColor(today), FontWeight.Bold, maxLines = 1)
                    }
                }
                if (Look.paper) PaperLabel("Since import vs Nifty", size = 11.sp) else T("Since import vs Nifty", 13.sp, weight = FontWeight.SemiBold, modifier = Modifier.padding(top = 16.dp))
                val sn = store.snaps
                if (sn.size >= 2 && sn.first().nifty != null && sn.last().nifty != null) {
                    val ix = Portfolio.series(sn)
                    val you = ix.map { it / ix.first() * 100 }
                    val nf = sn.map { (it.nifty ?: sn.first().nifty!!) / sn.first().nifty!! * 100 }
                    AreaLine(you, Modifier.padding(top = 8.dp).fillMaxWidth().height(120.dp), color = C.blue,
                        overlays = listOf(Series(nf, C.grey, "Nifty", 1.6.dp)), endLabel = "You", endLabelPos = EndLabel.Right, endLabelColor = C.blue,
                        xLabels = listOf(shortDate(sn.first().d), shortDate(sn.last().d)))
                } else T("Not enough history yet: one point a day after each evening's data (18:30), the chart starts after the second", 12.sp, C.dim,
                    lineHeight = 16.sp, modifier = Modifier.padding(top = 6.dp))
                Row(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                    T(if (live.isNotEmpty()) "Prices: delayed quotes, ${quoteTime(live) ?: ""}" else "Prices: latest exchange close", 11.sp, C.dim, modifier = Modifier.weight(1f), maxLines = 1)
                    T("Data of ${shortDate(st.picks?.date)}", 11.sp, C.dim, maxLines = 1)
                }
            }
        }
        val scored = rows.filter { (h, _, _) -> decisionOf(Portfolio.pickFor(h.s, picks)) != null }
        if (scored.isNotEmpty()) item {
            val cnt = scored.groupingBy { (h, _, _) -> decisionOf(Portfolio.pickFor(h.s, picks))!!.group }.eachCount()
            SectionCard("By Narrativ decision", "By count", Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
                SegmentedBar(DEC_BAR.keys.mapNotNull { k -> cnt[k]?.let { Segment(it.toDouble(), DEC_BAR.getValue(k), "$it $k") } }, height = 12.dp, gap = 3.dp, legend = SegLegend.Below)
            }
        }
        val attention = rows.filter { (h, _, _) -> Portfolio.pickFor(h.s, picks)?.let { needsAttention(it) } == true }
        val etfs = rows.filter { (h, _, _) -> Portfolio.pickFor(h.s, picks) == null }
        val rest = rows.filter { it !in attention && it !in etfs }.sortedBy { (h, p, _) -> if (h.avg > 0 && p != null) p / h.avg else 9.0 }
        if (attention.isNotEmpty()) {
            item { SecHead("Needs attention", "${attention.size}") }
            item { HoldingList(st, attention, picks, value) }
        }
        if (rest.isNotEmpty()) {
            item { SecHead("All stocks", "${rest.size} · biggest loss first") }
            item { HoldingList(st, rest, picks, value) }
        }
        if (etfs.isNotEmpty()) item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 12.dp).fillMaxWidth(), pad = 0.dp) {
                Column(Modifier.padding(horizontal = 14.dp)) { ToggleRow("ETFs and others", "${etfs.size}", etfOpen, { etfOpen = !etfOpen }, divider = false) }
                if (etfOpen) { HLineDivider(); HoldingRows(st, etfs, picks, value) }
            }
        }
        item { MoreLink("What is sent for prices", Modifier.padding(horizontal = 16.dp)) { sent = true } }
    }
}

fun needsAttention(p: P): Boolean = p.dc in setOf("Sell", "Strong Sell") || p.vd == "Removed" || p.vf in setOf("caution", "fail")

/** [sym] only matters when [p] is null: ETFs are told by name, anything else not scored is an equity Narrativ does not cover. */
fun holdingLabel(p: P?, sym: String = ""): Pair<String, Color> = when {
    p == null -> (if (Regex("ETF|BEES").containsMatchIn(sym.uppercase())) "ETF" else "Not scored") to C.dim
    p.dc in setOf("Buy", "Strong Buy") && p.vf == "pass" -> (p.dc ?: "Buy") to decisionColor(p.dc)
    p.dc in setOf("Sell", "Strong Sell") -> (p.dc ?: "Sell") to decisionColor(p.dc)
    p.vf in setOf("caution", "fail") -> "${p.dc ?: "Hold"} · Narrativ.ai ${p.vf}" to C.amber
    else -> (p.dc ?: "Not rated") to (if (p.dc == "Hold") C.grey else C.dim)
}

@Composable
fun HoldingList(st: AppState, rows: List<Triple<Holding, Double?, Double?>>, picks: Map<String, P>, total: Double? = null) {
    Card(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth(), pad = 0.dp) { HoldingRows(st, rows, picks, total) }
}

/** Rows of a holdings card: code and decision chip, qty × avg · now, P&L since cost with today's move as a mini bar under it. */
@Composable
fun ColumnScope.HoldingRows(st: AppState, rows: List<Triple<Holding, Double?, Double?>>, picks: Map<String, P>, total: Double? = null) {
    rows.forEachIndexed { i, (h, p, d) ->
        val pk = Portfolio.pickFor(h.s, picks)
        val dg = decisionOf(pk)
        val pl = if (h.avg > 0 && p != null) (p / h.avg - 1) * 100 else null
        if (Look.paper) {
            PaperHoldingRow(st, h, p, d, pk, pl, total)
            if (i < rows.lastIndex) HLineDivider(Modifier.padding(horizontal = 4.dp))
            return@forEachIndexed
        }
        Row(Modifier.fillMaxWidth().defaultMinSize(minHeight = 56.dp).then(if (pk != null) Modifier.clickable { st.go(Screen.Stock(pk.s)) } else Modifier)
            .padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    T(h.s, 15.sp, weight = FontWeight.SemiBold, maxLines = 1, modifier = Modifier.weight(1f, fill = false))
                    if (dg != null) Box(Modifier.clip(rr(S.inner)).background(dg.color).padding(horizontal = 8.dp, vertical = 3.dp)) {
                        T(dg.text, 11.sp, Color.White, FontWeight.Bold, maxLines = 1)
                    }
                    else T(holdingLabel(null, h.s).first, 11.sp, C.dim, maxLines = 1)
                }
                T("${fmt(h.qty, 0)} × ${priceStr(h.avg)} · now ${priceStr(p)}", 11.sp, C.dim, maxLines = 1)
            }
            Column(horizontalAlignment = Alignment.End) {
                T(sg(pl, 1), 14.sp, plColor(pl), FontWeight.SemiBold, maxLines = 1)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    MiniDiv(d)
                    T(sg(d, 2), 11.sp, plColor(d), maxLines = 1)
                }
            }
        }
        if (i < rows.lastIndex) HLineDivider(Modifier.padding(horizontal = 14.dp))
    }
}


/** Paper look, Portfolio (mock-up): value · today · overall in ruled columns, the headline, and the calls weighted by value held. */
@Composable
fun PaperLedgerFront(rows: List<Triple<Holding, Double?, Double?>>, picks: Map<String, P>, value: Double, inv: Double, today: Double,
                     todayPct: Double?, pl: Double, plPct: Double?) {
    Column(Modifier.padding(horizontal = 16.dp).fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().height(androidx.compose.foundation.layout.IntrinsicSize.Min)) {
            @Composable fun cell(label: String, v: String, sub: String?, c: Color, m: Modifier) = Column(m.padding(vertical = 6.dp, horizontal = 6.dp)) {
                PaperLabel(label, size = 10.sp)
                androidx.compose.material3.Text(v, fontSize = 18.sp, color = c, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1)
                sub?.let { T(it, 10.sp, C.dim, maxLines = 1) }
            }
            cell("Value", rupees(value), "Invested ${rupees(inv)}", C.white, Modifier.weight(1f))
            Box(Modifier.width(1.dp).fillMaxHeight().background(C.line))
            cell("Today", (if (today >= 0) "▲ " else "▼ ") + rupees(kotlin.math.abs(today)), sg(todayPct, 1), plColor(today), Modifier.weight(1f))
            Box(Modifier.width(1.dp).fillMaxHeight().background(C.line))
            cell("Overall", (if (pl >= 0) "▲ " else "▼ ") + rupees(kotlin.math.abs(pl)), sg(plPct, 1), plColor(pl), Modifier.weight(1f))
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(C.white))
        androidx.compose.material3.Text("What today's calls say about what you own", fontSize = 22.sp, lineHeight = 26.sp, color = C.white,
            fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, modifier = Modifier.padding(vertical = 8.dp))
        val byCall = rows.groupBy { (h, _, _) -> decisionOf(Portfolio.pickFor(h.s, picks))?.group ?: "Not rated" }
            .mapValues { (_, r) -> r.sumOf { (h, p, _) -> h.qty * (p ?: 0.0) } }
        val tot = byCall.values.sum().takeIf { it > 0 }
        if (tot != null) {
            PaperLabel("Calls by value held", size = 10.sp)
            val order = listOf("Buy", "Hold", "Sell", "Not rated")
            Row(Modifier.padding(top = 4.dp).fillMaxWidth().height(16.dp), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                order.forEach { k -> byCall[k]?.takeIf { it > 0 }?.let { v -> Box(Modifier.weight(v.toFloat()).fillMaxHeight().background(DEC_BAR[k] ?: C.dim)) } }
            }
            Row(Modifier.padding(top = 4.dp, bottom = 6.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                order.forEach { k -> byCall[k]?.takeIf { it > 0 }?.let { v -> T("$k ${fmt(v / tot * 100, 0)}%", 11.sp, if (k == "Not rated") C.dim else DEC_BAR[k] ?: C.dim, FontWeight.SemiBold) } }
            }
        }
    }
}

/** Paper look, one holding: name over its seven dots and qty @ avg; P&L with an arrow over its share of the portfolio; the call tag. */
@Composable
fun PaperHoldingRow(st: AppState, h: Holding, p: Double?, d: Double?, pk: P?, pl: Double?, total: Double?) {
    val dg = decisionOf(pk)
    val share = if (total != null && total > 0 && p != null) h.qty * p / total * 100 else null
    Row(Modifier.fillMaxWidth().then(if (pk != null) Modifier.clickable { st.go(Screen.Stock(pk.s)) } else Modifier)
        .padding(horizontal = 4.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            androidx.compose.material3.Text(h.s, fontSize = 15.sp, color = C.white, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Bold, maxLines = 1)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (pk != null) InkDots(pk.t)
                androidx.compose.material3.Text("${fmt(h.qty, 0)} @ ${priceStr(h.avg)} · now ${priceStr(p)}", fontSize = 10.sp, color = C.dim,
                    fontStyle = androidx.compose.ui.text.font.FontStyle.Italic, maxLines = 1)
            }
        }
        Column(Modifier.padding(horizontal = 8.dp), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(2.dp)) {
            T(if (pl == null) "–" else (if (pl >= 0) "▲ " else "▼ ") + fmt(kotlin.math.abs(pl), 1) + "%", 12.sp, plColor(pl), FontWeight.SemiBold, maxLines = 1)
            T("Today " + arrowPct(d), 10.sp, plColor(d), maxLines = 1)
            share?.let { InkMeter(it.coerceAtMost(100.0), C.grey, Modifier.width(56.dp).height(5.dp)) }
        }
        if (dg != null) PaperSolidTag(dg.text, dg.color, 10.sp) else T(holdingLabel(null, h.s).first, 10.sp, C.dim, maxLines = 1)
    }
}
