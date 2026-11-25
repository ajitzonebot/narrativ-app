package com.narrativ.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.List
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Routes. Dock (tab roots): Home, Screener ("Stocks"), Portfolio, Settings. Market is pushed from Home's strip;
 * Settings > Track record and Settings > Advanced > Data (Pipeline) / Research queue (Queue) / Checkpoint calendar
 * (Calendar) / Release notes (Notes). Money is the old name of Market (kept so old links work).
 */
sealed class Screen {
    data object Home : Screen()
    data object Market : Screen()
    data object Advanced : Screen()
    data object TrackRecord : Screen()
    data object Money : Screen()
    data class Screener(val preset: String? = null) : Screen()
    data object Settings : Screen()
    data object Calendar : Screen()
    data class Stock(val symbol: String) : Screen()
    data object Queue : Screen()
    data class Quadrant(val q: String, val sectors: Boolean) : Screen()
    data object Notes : Screen()
    data object Feedback : Screen()
    data object Sources : Screen()
    data object Pipeline : Screen()
    data object Refresh : Screen()
    data object Alerts : Screen()
    data object Tracking : Screen()
    data object Portfolio : Screen()
    data class Ipo(val name: String) : Screen()
    data object Search : Screen()
}

@kotlinx.serialization.Serializable
data class Sent(val kind: String = "", val text: String = "", val date: String = "", val ref: Int = 0)

/** Stocks whose pages are preloaded after each data update (about 25 KB each; two files per stock). */
const val PRELOAD_STOCKS = 25

class AppState(private val ctx: Context, startStack: List<Screen> = listOf(Screen.Home)) {
    val repo = Repo(ctx)
    private val prefs = ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE)
    var picks by mutableStateOf<PicksFile?>(null)
    var research by mutableStateOf<Map<String, Research>>(emptyMap())
    var memory by mutableStateOf<MemoryFile?>(null)
    var version by mutableStateOf<VersionInfo?>(null)
    var rotation by mutableStateOf<RotationFile?>(null)
    var queue by mutableStateOf<QueueFile?>(null)
    var ipo by mutableStateOf<IpoToday?>(null)
    var ipoAlerts by mutableStateOf(prefs.getBoolean("ipoAlerts", true))
    fun toggleIpoAlerts() {
        ipoAlerts = !ipoAlerts; prefs.edit().putBoolean("ipoAlerts", ipoAlerts).apply()
        if (ipoAlerts) { IpoAlerts.schedule(ctx); askNotif = true } else IpoAlerts.cancel(ctx)
    }
    var askNotif by mutableStateOf(false)  // set when IPO alerts are switched on: App asks for the notification permission
    var toast by mutableStateOf<String?>(null)
    var loading by mutableStateOf(false)
    var updatedAt by mutableStateOf<String?>(null)  // time of the last load that really came from the network (Home shows a short "Updated" line)
    var offline by mutableStateOf(false)  // the last refresh could not reach the server: what is shown is the phone copy
    var error by mutableStateOf<String?>(null)
    var watch by mutableStateOf(prefs.getStringSet("watch", emptySet())!!.toSet())
    var showFeedback by mutableStateOf(false)
    var feedbackContext by mutableStateOf("Home")
    var showUpdate by mutableStateOf(false)
    var requested by mutableStateOf(prefs.getStringSet("requested", emptySet())!!.toSet())
    // decoded on first use (Settings), not while the app starts
    private val sentState by lazy { mutableStateOf(runCatching { json.decodeFromString<List<Sent>>(prefs.getString("sent", "[]")!!) }.getOrDefault(emptyList())) }
    var sent: List<Sent>
        get() = sentState.value
        set(v) { sentState.value = v }
    val stack = mutableStateListOf<Screen>().apply { addAll(startStack.ifEmpty { listOf(Screen.Home) }) }
    private val details = mutableStateMapOf<String, Detail?>()

    val current: Screen get() = stack.last()
    fun go(s: Screen) { stack.add(s) }
    fun tab(s: Screen) { stack.clear(); stack.add(s) }
    fun back(): Boolean = if (stack.size > 1) { stack.removeAt(stack.lastIndex); true } else false

    fun toggleWatch(sym: String) {
        watch = if (sym in watch) watch - sym else watch + sym
        prefs.edit().putStringSet("watch", watch).apply()
    }
    /** Symbol -> pick of the current picks.json (first row wins, as the old linear search did), rebuilt only when picks change. */
    @Volatile private var pickIdx: Pair<PicksFile, Map<String, P>>? = null
    fun pick(sym: String): P? {
        val pf = picks ?: return null
        pickIdx?.let { if (it.first === pf) return it.second[sym] }
        val m = HashMap<String, P>(pf.picks.size * 2)
        pf.picks.forEach { m.putIfAbsent(it.s, it) }
        pickIdx = pf to m
        return m[sym]
    }
    /** Look.kt topTen: last result and what it was computed from. */
    @Volatile var topTenMemo: TopTenMemo? = null
    fun levelName(k: String) = picks?.levelNames?.get(k) ?: LEVEL_TITLES[LEVELS.indexOf(k)]

    /** Phone copy (instant, may be a day old); the screen then swaps in [detail]. */
    suspend fun cachedDetail(sym: String): Detail? = details[sym] ?: repo.get<Detail>("data/fin/${Repo.seg(sym)}.json", fresh = false)

    suspend fun detail(sym: String): Detail? {
        if (details.containsKey(sym) && details[sym] != null) return details[sym]
        val path = "data/fin/${Repo.seg(sym)}.json"
        // network first, phone cache only when offline; a copy the network confirmed within a minute (a preload) is used as is
        val d = repo.get<Detail>(path, fresh = !Repo.checkedRecently(path))
        details[sym] = d
        return d
    }

    var lastLoad = 0L
    /** Called when the app comes back to the screen: re-check published data if the last check is over 15 minutes old. */
    suspend fun autoRefresh() {
        if (System.currentTimeMillis() - lastLoad < 15 * 60_000L) return
        val before = picks?.updated; val rb = research.size to research.values.mapNotNull { it.updated }.maxOrNull()
        load()
        if (before != null && picks?.updated != before) toast = "Updated to data of ${shortDate(picks?.date)} · ${istTime(picks?.updated)}"
        else if (before != null && (research.size to research.values.mapNotNull { it.updated }.maxOrNull()) != rb) toast = "New Narrativ.ai research loaded"
    }

    /** [picksText]: a picks.json request already started (App starts it during the phone-copy pass). */
    suspend fun load(fresh: Boolean = true, picksText: Deferred<Pair<String, Boolean>?>? = null) {
        if (fresh) lastLoad = System.currentTimeMillis()
        loading = true; error = null
        val src = if (picksText != null) picksText.await() else repo.textSrc("data/picks.json", fresh)
        val got = src?.let { (body, net) -> repo.decodeOff<PicksFile>("data/picks.json", body)?.let { Repo.Loaded(it, net) } }
        if (got != null && got.value.v >= 2) {
            picks = got.value; details.clear(); clearChartCache()
            if (fresh) {
                if (got.net) {
                    offline = false
                    updatedAt = java.time.LocalTime.now(java.time.ZoneId.of("Asia/Kolkata")).format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
                } else {
                    offline = true  // the phone copy, not an update: no "Updated" time
                    lastLoad = System.currentTimeMillis() - 10 * 60_000L  // look again in about 5 minutes
                }
            }
        } else if (picks == null) error = "Could not load data. Check internet."
        else if (fresh) { offline = true; lastLoad = System.currentTimeMillis() - 10 * 60_000L }
        loading = false
        // the rest together, not one after another; an unchanged file is not decoded again (Repo keeps the decoded copy).
        // The phone-copy pass (fresh = false) never touches the network, version.json included.
        coroutineScope {
            launch { repo.get<Map<String, Research>>("data/research.json", fresh)?.let { research = it } }
            launch { repo.get<RotationFile>("data/rotation.json", fresh)?.let { rotation = it } }
            launch { repo.get<MemoryFile>("data/memory.json", fresh)?.let { memory = it } }
            launch { repo.get<QueueFile>("data/queue.json", fresh)?.let { queue = it } }
            launch { repo.get<IpoToday>("data/ipo_today.json", fresh)?.let { ipo = it } }
            launch {
                repo.get<VersionInfo>("app/version.json", fresh)?.let { v ->
                    version = v
                    if (v.versionCode > BuildConfig.VERSION_CODE && prefs.getInt("dismissed", 0) < v.versionCode) showUpdate = true
                }
            }
        }
        // once per data update: the stock pages most likely opened next, in the background (feedback #107: slow first open)
        val pf = picks
        if (fresh && got?.net == true && pf != null && "${pf.updated}|${pf.date}" != preloadedFor) {
            preloadedFor = "${pf.updated}|${pf.date}"
            repo.preload(preloadPaths())
        }
    }

    private var preloadedFor: String? = null

    /** Files a stock page reads first (fin = Summary and level tabs, charts) for today's Top 10, then the other verified Buys. */
    fun preloadPaths(): List<String> {
        val pf = picks ?: return emptyList()
        val top = topTen(this)?.stocks.orEmpty().map { it.s }
        val buys = pf.picks.filter { it.out == null && isBuy(it) && it.verified() }.map { it.s }
        return (top + buys).distinct().take(PRELOAD_STOCKS).flatMap { s ->
            listOf("data/fin/${Repo.seg(s)}.json", "data/charts/${Repo.seg(s)}.json")
        }
    }
    fun dismissUpdate() { version?.let { prefs.edit().putInt("dismissed", it.versionCode).apply() }; showUpdate = false }
    fun openFeedback(context: String) { feedbackContext = context; showFeedback = true }

    private fun remember(kind: String, text: String, ref: Int) {
        sent = (listOf(Sent(kind, text, java.time.LocalDate.now().toString(), ref)) + sent).take(50)
        prefs.edit().putString("sent", json.encodeToString(kotlinx.serialization.builtins.ListSerializer(Sent.serializer()), sent)).apply()
    }

    /** In-app feedback and scan requests go to the Narrativ API, which files them as issues in the private repo. */
    suspend fun sendFeedback(type: String, text: String, stock: String?): Result<Int> = repo.post("feedback", buildJsonObject {
        put("text", "[$type] $text"); put("screen", feedbackContext); put("version", "v${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
        put("dataDate", picks?.date ?: "-"); stock?.let { put("stock", it) }
    }).onSuccess { remember("Feedback · $type", text, it) }
    suspend fun requestScan(symbol: String, note: String = ""): Result<Int> = repo.post("scan", buildJsonObject {
        put("symbol", symbol); put("note", note); put("screen", feedbackContext); put("version", "v${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
        put("dataDate", picks?.date ?: "-")
    }).onSuccess {
        requested = requested + symbol
        prefs.edit().putStringSet("requested", requested).apply()
        remember("Scan request", symbol, it)
    }
}

/** The navigation stack as text (one screen per line, fields split by a tab) so it can be saved across rotation. */
fun encodeStack(stack: List<Screen>): String = stack.joinToString("\n") { s ->
    when (s) {
        is Screen.Screener -> "Screener\t${s.preset ?: ""}"
        is Screen.Stock -> "Stock\t${s.symbol}"
        is Screen.Quadrant -> "Quadrant\t${s.q}\t${s.sectors}"
        is Screen.Ipo -> "Ipo\t${s.name}"
        else -> s::class.simpleName ?: "Home"
    }
}

fun decodeStack(text: String): List<Screen> = text.lines().filter { it.isNotBlank() }.mapNotNull { l ->
    val f = l.split('\t')
    when (f[0]) {
        "Home" -> Screen.Home; "Money" -> Screen.Money; "Settings" -> Screen.Settings; "Calendar" -> Screen.Calendar
        "Queue" -> Screen.Queue; "Notes" -> Screen.Notes; "Feedback" -> Screen.Feedback; "Sources" -> Screen.Sources
        "Pipeline" -> Screen.Pipeline; "Refresh" -> Screen.Refresh; "Alerts" -> Screen.Alerts; "Tracking" -> Screen.Tracking
        "Portfolio" -> Screen.Portfolio; "Search" -> Screen.Search; "Market" -> Screen.Market; "Advanced" -> Screen.Advanced; "TrackRecord" -> Screen.TrackRecord
        "Screener" -> Screen.Screener(f.getOrNull(1)?.ifBlank { null })
        "Stock" -> f.getOrNull(1)?.takeIf { it.isNotBlank() }?.let { Screen.Stock(it) }
        "Quadrant" -> Screen.Quadrant(f.getOrNull(1) ?: "Leading", f.getOrNull(2) == "true")
        "Ipo" -> f.getOrNull(1)?.let { Screen.Ipo(it) }
        else -> null
    }
}

fun openUrl(ctx: Context, url: String) {
    runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        KeyGate.init(this)
        val start = intent?.getStringExtra("route")
        val ci = intent?.getBooleanExtra("ci", false) ?: false
        setContent { NarrativTheme { App(start, ci) } }
    }
}

@Composable
fun App(startRoute: String? = null, ci: Boolean = false) {
    val ctx = LocalContext.current
    // the navigation stack survives rotation (saved as text); everything else reloads from the phone cache
    var savedStack by rememberSaveable { mutableStateOf("") }
    var routeDone by rememberSaveable { mutableStateOf(false) }
    val st = remember { AppState(ctx, decodeStack(savedStack)) }
    LaunchedEffect(st) { snapshotFlow { encodeStack(st.stack) }.collect { savedStack = it } }
    val scope = rememberCoroutineScope()
    val notifPerm = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { }
    fun askNotifPerm() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && androidx.core.content.ContextCompat.checkSelfPermission(ctx, android.Manifest.permission.POST_NOTIFICATIONS)
            != android.content.pm.PackageManager.PERMISSION_GRANTED) notifPerm.launch(android.Manifest.permission.POST_NOTIFICATIONS)
    }
    LaunchedEffect(st.askNotif) { if (st.askNotif) { st.askNotif = false; askNotifPerm() } }
    // auto-update (no Refresh tap needed): re-check published data whenever the app returns to the screen
    val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = androidx.lifecycle.LifecycleEventObserver { _, e ->
            if (e == androidx.lifecycle.Lifecycle.Event.ON_RESUME && st.lastLoad > 0) scope.launch { st.autoRefresh() }
        }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    LaunchedEffect(Unit) {
        val picksNet = async { st.repo.textSrc("data/picks.json") }  // the network check runs while the phone copy is shown
        if (st.ipoAlerts && !ci) {
            IpoAlerts.schedule(ctx)
            askNotifPerm()
        }
        withContext(Dispatchers.IO) { Portfolio.load(ctx) }  // moves holdings saved by an older version into their own (not backed up) preferences file
        if (!ci) Portfolio.schedule(ctx)  // one point a day for Settings › Portfolio (no-op without holdings)
        st.load(fresh = false)
        st.load(fresh = true, picksText = picksNet)
        if (ci && startRoute != "update") st.showUpdate = false
        if (routeDone) return@LaunchedEffect  // after a rotation the saved stack already holds the opened screen
        routeDone = true
        when (startRoute) {  // CI screenshot routes (android/ci/shots.sh) and deep links
            "money", "market" -> { st.tab(Screen.Home); st.go(Screen.Market) }
            "screener", "stocks" -> st.tab(Screen.Screener())
            "portfolio" -> st.tab(Screen.Portfolio)
            "settings" -> st.tab(Screen.Settings)
            "track" -> { st.tab(Screen.Settings); st.go(Screen.TrackRecord) }
            "advanced" -> { st.tab(Screen.Settings); st.go(Screen.Advanced) }
            "data" -> { st.tab(Screen.Settings); st.go(Screen.Advanced); st.go(Screen.Pipeline) }
            "release" -> { st.tab(Screen.Settings); st.go(Screen.Advanced); st.go(Screen.Notes) }
            "calendar" -> { st.tab(Screen.Settings); st.go(Screen.Advanced); st.go(Screen.Calendar) }
            "queue" -> { st.tab(Screen.Settings); st.go(Screen.Advanced); st.go(Screen.Queue) }
            "quadrant" -> { st.tab(Screen.Home); st.go(Screen.Market); st.go(Screen.Quadrant("Leading", false)) }
        }
        when {
            startRoute == "search" -> { st.tab(Screen.Home); st.go(Screen.Search) }
            startRoute == "update" -> st.showUpdate = st.version != null
            startRoute == "feedback" -> st.openFeedback("Home")
            startRoute?.startsWith("stock:") == true -> st.go(Screen.Stock(startRoute.removePrefix("stock:")))
            startRoute?.startsWith("tab:") == true -> st.go(Screen.Stock(startRoute.removePrefix("tab:").substringBefore("@")))
        }
    }
    BackHandler(enabled = st.stack.size > 1) { st.back() }

    if (KeyGate.showing && !ci) {
        KeyScreen(onDone = { scope.launch { st.load() } })
        return
    }
    Box(Modifier.fillMaxSize().background(C.bg)) {
        if (st.picks == null) {
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                if (st.error != null) {
                    T(st.error!!, 15.sp, C.grey)
                    Spacer(Modifier.height(14.dp))
                    PrimaryButton("Retry") { scope.launch { st.load() } }
                }
            }
            if (st.error == null) HomeSkeleton()  // placeholders in the shape of Home instead of a spinner (#19)
        } else {
            when (val s = st.current) {
                Screen.Home -> HomeScreen(st)
                Screen.Money, Screen.Market -> MoneyScreen(st)
                Screen.Advanced -> AdvancedScreen(st)
                Screen.TrackRecord -> TrackRecordScreen(st)
                is Screen.Screener -> ScreenerScreen(st, s.preset)
                Screen.Settings -> SettingsScreen(st)
                Screen.Calendar -> UpcomingScreen(st)
                is Screen.Stock -> StockScreen(st, s.symbol, startTab(startRoute, s.symbol))
                Screen.Queue -> ResearchQueueScreen(st)
                is Screen.Quadrant -> QuadrantListScreen(st, s.q, s.sectors)
                Screen.Notes -> ReleaseNotesScreen(st)
                Screen.Feedback -> FeedbackScreen(st)
                Screen.Sources -> DataPipelineScreen(st)
                Screen.Pipeline -> DataPipelineScreen(st)
                Screen.Refresh -> DataPipelineScreen(st)
                Screen.Alerts -> DataPipelineScreen(st)
                Screen.Tracking -> TrackRecordScreen(st)
                Screen.Portfolio -> PortfolioScreen(st)
                is Screen.Ipo -> IpoDetailScreen(st, s.name)
                Screen.Search -> SearchScreen(st)
            }
        }
        if (st.picks != null) BottomBar(st, Modifier.align(Alignment.BottomCenter))
        if (st.showUpdate) UpdateDialog(st)
        if (st.showFeedback) FeedbackSheet(st)
        st.toast?.let { msg ->
            LaunchedEffect(msg) { delay(3500); st.toast = null }
            Box(Modifier.align(Alignment.BottomCenter).padding(bottom = 96.dp, start = 24.dp, end = 24.dp).navigationBarsPadding()
                .clip(RoundedCornerShape(16.dp)).background(C.chip).border(1.dp, C.line, RoundedCornerShape(16.dp))
                .padding(horizontal = 16.dp, vertical = 12.dp)) { T(msg, 14.sp) }
        }
    }
}

/** Dock: Home / Stocks / Portfolio / Settings, icon and label; the tab whose stack is showing is blue. */
@Composable
fun BottomBar(st: AppState, modifier: Modifier) {
    val root = st.stack.first()
    val items = listOf(
        Triple(Icons.Rounded.Home, "Home", Screen.Home as Screen),
        Triple(Icons.AutoMirrored.Rounded.List, "Stocks", Screen.Screener()),
        Triple(Icons.Rounded.AccountBalanceWallet, "Portfolio", Screen.Portfolio),
        Triple(Icons.Rounded.Settings, "Settings", Screen.Settings),
    )
    fun active(s: Screen) = when (s) { is Screen.Screener -> root is Screen.Screener; else -> root == s }
    Row(
        modifier.navigationBarsPadding().padding(start = 12.dp, end = 12.dp, bottom = 14.dp).fillMaxWidth().height(64.dp)
            .clip(RoundedCornerShape(22.dp)).background(C.dock).border(1.dp, C.line, RoundedCornerShape(22.dp)),
        horizontalArrangement = Arrangement.SpaceAround, verticalAlignment = Alignment.CenterVertically,
    ) {
        items.forEach { (icon, label, screen) ->
            val on = active(screen)
            Column(
                Modifier.width(72.dp).clip(RoundedCornerShape(16.dp)).clickable { st.tab(screen) }.padding(vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Icon(icon, label, tint = if (on) C.blue else C.dim, modifier = Modifier.size(22.dp))
                T(label, 11.sp, if (on) C.blue else C.dim, maxLines = 1)
            }
        }
    }
}

/** Screen header with the feedback button top-right. */
@Composable
fun Header(st: AppState, title: String, subtitle: String? = null, context: String, back: Boolean = false,
           subtitleLines: Int = 1, actions: @Composable RowScope.() -> Unit = {}) {
    Row(
        Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (back) { CircleBtn(Icons.Rounded.ArrowBack) { st.back() }; Spacer(Modifier.width(10.dp)) }
        Column(Modifier.weight(1f)) {
            T(title, if (back) 18.sp else 26.sp, weight = FontWeight.Bold, maxLines = 1)
            if (subtitle != null) T(subtitle, 13.sp, C.grey, maxLines = subtitleLines, lineHeight = 17.sp)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            actions()
            CircleBtn(Icons.Rounded.Feedback, accent = true) { st.openFeedback(context) }
        }
    }
}

/** CI screenshots: route "tab:SYMBOL@3" opens the stock screen on tab 3. */
fun startTab(route: String?, sym: String): Int =
    if (route?.startsWith("tab:$sym@") == true) route.substringAfter("@").toIntOrNull() ?: 0 else 0
