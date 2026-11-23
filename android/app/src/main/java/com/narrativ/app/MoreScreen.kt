package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonPrimitive

/** One row of a settings card: icon, title and a grey line, an optional figure, then a chevron or [trailing]. */
@Composable
private fun SetRow(icon: ImageVector, title: String, sub: String, onClick: () -> Unit, figure: String? = null, figureColor: Color = C.white,
                   trailing: (@Composable () -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).defaultMinSize(minHeight = 64.dp).padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Icon(icon, null, tint = C.muted, modifier = Modifier.size(22.dp))
        Column(Modifier.weight(1f)) {
            T(title, 16.sp, weight = FontWeight.SemiBold, maxLines = 1)
            T(sub, 12.5.sp, C.dim, maxLines = 1)
        }
        figure?.let { T(it, 16.sp, figureColor, FontWeight.Bold, maxLines = 1) }
        if (trailing != null) trailing() else Icon(Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.size(18.dp))
    }
}

@Composable
fun SettingsScreen(st: AppState) {
    val v = st.version
    val calls by produceState<CallsFile?>(null) { value = st.repo.get<CallsFile>("data/calls.json") }
    val newer = v != null && v.versionCode > BuildConfig.VERSION_CODE
    val buys = calls?.calls.orEmpty().count { it.kind == "verified" }
    val vsNifty = calls?.summary?.now?.avgVsNifty
    AccScreen(st, "Settings", back = false, big = true, context = "Settings") {
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 14.dp, onClick = { st.go(Screen.Notes) }) {  // version card opens release notes
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    AppLogo(46.dp)
                    Column(Modifier.weight(1f)) {
                        T("Narrativ ${BuildConfig.VERSION_NAME}", 17.sp, weight = FontWeight.Bold, maxLines = 1)
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            StatusDot(if (newer) C.blue else TierC.lightGreen)
                            T((if (newer) "Update available" else "Up to date") + " · data of ${shortDate(st.picks?.date)}", 12.5.sp, C.dim, maxLines = 1)
                        }
                    }
                    Icon(Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.size(18.dp))
                }
            }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                SetRow(Icons.Rounded.QueryStats, "Track record", if (buys > 0) "$buys Buys · vs Nifty" else "Every Buy vs Nifty", { st.go(Screen.TrackRecord) },
                    vsNifty?.let { sg(it) }, plColor(vsNifty))
                HLineDivider(Modifier.padding(horizontal = 14.dp))
                // a switch, not a click-through (the old "Alerts" page described push alerts that were never set up: removed)
                SetRow(Icons.Rounded.NotificationsNone, "IPO alerts", "09:15 and 15:00 on the last day", { st.toggleIpoAlerts() }, trailing = {
                    androidx.compose.material3.Switch(checked = st.ipoAlerts, onCheckedChange = { st.toggleIpoAlerts() },
                        colors = androidx.compose.material3.SwitchDefaults.colors(checkedTrackColor = C.teal, checkedThumbColor = Color.White))
                })
                HLineDivider(Modifier.padding(horizontal = 14.dp))
                SetRow(Icons.Rounded.ChatBubbleOutline, "Feedback", "Send a note or see yours", { st.go(Screen.Feedback) })
            }
        }
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                SetRow(Icons.Rounded.Tune, "Advanced", "Data, queue, checkpoints, releases", { st.go(Screen.Advanced) })
            }
        }
        item {
            T("Screening tool, not investment advice. Every number is computed by formula from a named source or quoted verbatim; a dash means it could not be computed.",
                12.sp, C.dim, lineHeight = 17.sp, modifier = Modifier.padding(horizontal = 20.dp, vertical = 14.dp))
        }
    }
}

/** Settings > Advanced: the operational screens, each row with a status dot and a small picture of its state. */
@Composable
fun AdvancedScreen(st: AppState) {
    val runs by produceState<List<RunRec>?>(null) { value = st.repo.get<List<RunRec>>("data/runs.json") }
    val q = st.queue
    val today = remember { java.time.LocalDate.now(java.time.ZoneId.of("Asia/Kolkata")) }
    val cps = st.memory?.stocks.orEmpty().flatMap { it.checkpoints }
    val ndue = cps.count { it.status == "due" }
    val n45 = cps.count { it.status == "open" && it.due in today.toString()..today.plusDays(45).toString() }
    val newer = (st.version?.versionCode ?: 0) > BuildConfig.VERSION_CODE
    val last = runs?.firstOrNull()
    AccScreen(st, "Advanced", context = "Advanced") {
        item {
            Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth(), pad = 0.dp) {
                AdvRow(Icons.Rounded.MonitorHeart, "Data and pipeline", { st.go(Screen.Pipeline) },
                    dot = if ((last?.problems ?: 0) > 0) C.amber else TierC.lightGreen,
                    sub = if (last == null) "Last run" else "${shortDate(last.date)} · ${fmt(last.minutes, 1)} min",
                    visual = { runs?.takeIf { it.size >= 2 }?.let { MiniRuns(it.reversed().takeLast(11)) } },
                    badge = last?.problems?.takeIf { it > 0 })
                HLineDivider(Modifier.padding(horizontal = 14.dp))
                AdvRow(Icons.Rounded.Science, "Research queue", { st.go(Screen.Queue) }, null, "${q?.items?.size ?: 0} in queue", visual = {
                    q?.items?.takeIf { it.isNotEmpty() }?.let { items ->
                        SegmentedBar(items.groupingBy { it.task ?: "scan" }.eachCount().entries.sortedByDescending { it.value }.map { Segment(it.value.toDouble(), queueTaskColor(it.key)) },
                            Modifier.width(56.dp), height = 8.dp, legend = SegLegend.None)
                    }
                })
                HLineDivider(Modifier.padding(horizontal = 14.dp))
                AdvRow(Icons.Rounded.CalendarMonth, "Checkpoint calendar", { st.go(Screen.Calendar) }, if (ndue > 0) C.amber else null, "$ndue due · $n45 in 45 days", visual = {
                    if (ndue + n45 > 0) SegmentedBar(listOf(Segment(ndue.toDouble(), TierC.yellow), Segment(n45.toDouble(), C.teal)), Modifier.width(56.dp), height = 8.dp, legend = SegLegend.None)
                })
                HLineDivider(Modifier.padding(horizontal = 14.dp))
                AdvRow(Icons.Rounded.Info, "Release notes", { st.go(Screen.Notes) }, if (newer) C.blue else TierC.lightGreen,
                    "v${BuildConfig.VERSION_NAME} · " + if (newer) "update available" else "up to date")
            }
        }
    }
}

@Composable
private fun AdvRow(icon: ImageVector, title: String, onClick: () -> Unit, dot: Color?, sub: String, visual: (@Composable () -> Unit)? = null, badge: Int? = null) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).defaultMinSize(minHeight = 76.dp).padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(Color.White.copy(alpha = 0.06f)), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = C.blue, modifier = Modifier.size(22.dp))
        }
        Column(Modifier.weight(1f)) {
            T(title, 16.sp, weight = FontWeight.SemiBold, maxLines = 1)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                dot?.let { StatusDot(it) }
                T(sub, 13.sp, C.dim, maxLines = 1)
            }
        }
        Box(Modifier.width(56.dp), contentAlignment = Alignment.CenterEnd) { visual?.invoke() }
        badge?.let { Box(Modifier.defaultMinSize(22.dp, 22.dp).clip(CircleShape).background(C.amber.copy(alpha = 0.18f)), contentAlignment = Alignment.Center) { T("$it", 12.sp, C.amber, FontWeight.Bold) } }
        Icon(Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.size(18.dp))
    }
}

/** Minutes per run as 56 dp bars, oldest left; amber = 2 or more problems; the latest run is full strength. */
@Composable
private fun MiniRuns(rs: List<RunRec>) {
    androidx.compose.foundation.Canvas(Modifier.size(56.dp, 22.dp)) {
        val mx = rs.maxOf { it.minutes ?: 0.0 }.coerceAtLeast(0.1); val bw = size.width / rs.size
        rs.forEachIndexed { i, r ->
            val h = (((r.minutes ?: 0.0) / mx).toFloat() * size.height).coerceAtLeast(2.dp.toPx())
            val c = if (r.problems >= 2) C.amber else C.teal
            drawRoundRect(c.copy(alpha = if (i == rs.lastIndex) 1f else 0.55f), androidx.compose.ui.geometry.Offset(i * bw + 0.5.dp.toPx(), size.height - h),
                androidx.compose.ui.geometry.Size(bw - 1.5.dp.toPx(), h), androidx.compose.ui.geometry.CornerRadius(1.5.dp.toPx()))
        }
    }
}

@Composable
fun MoreRow(icon: ImageVector, title: String, onClick: () -> Unit) {
    Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().height(56.dp).clip(RoundedCornerShape(16.dp)).background(C.card2)
        .clickable(onClick = onClick).padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = C.grey, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(12.dp))
        T(title, 15.sp, modifier = Modifier.weight(1f))
        Icon(Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.size(18.dp))
    }
}

@Composable
fun ReleaseNotes(rel: Release) {
    Column(Modifier.padding(vertical = 6.dp)) {
        T("v${rel.version} · ${rel.date}", 13.sp, C.grey, FontWeight.SemiBold)
        rel.changes.forEach { ChangeRow(it) }
    }
}

@Composable
fun ChangeRow(c: Change) {
    val (label, col) = when (c.type) { "new" -> "NEW" to C.teal; "imp", "improved" -> "IMPROVED" to C.blue; "fix" -> "FIX" to C.grey; else -> c.type.uppercase() to C.grey }
    Row(Modifier.padding(vertical = 5.dp), verticalAlignment = Alignment.Top) {
        Box(Modifier.width(70.dp).border(1.dp, col.copy(alpha = 0.35f), RoundedCornerShape(6.dp)).padding(vertical = 2.dp), contentAlignment = Alignment.Center) {
            T(label, 9.sp, col, FontWeight.Bold)
        }
        Spacer(Modifier.width(10.dp))
        T(c.text, 14.sp, lineHeight = 19.sp)
    }
}

@Composable
fun UpdateDialog(st: AppState) {
    val ctx = LocalContext.current
    val v = st.version ?: return
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var prog by remember { mutableStateOf(0f) }
    var err by remember { mutableStateOf<String?>(null) }
    var done by remember { mutableStateOf<java.io.File?>(null) }
    Dialog(onDismissRequest = { if (!busy) st.dismissUpdate() }) {
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(C.card).border(1.dp, C.line, RoundedCornerShape(28.dp)).padding(20.dp)
            .heightIn(max = 560.dp).verticalScroll(rememberScrollState())) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Box(Modifier.size(40.dp).clip(CircleShape).background(C.teal.copy(alpha = 0.13f)), contentAlignment = Alignment.Center) {
                    Icon(Icons.Rounded.Download, null, tint = C.teal, modifier = Modifier.size(20.dp))
                }
                Box(Modifier.size(34.dp).clip(CircleShape).background(C.chip).clickable { st.dismissUpdate() }, contentAlignment = Alignment.Center) {
                    Icon(Icons.Rounded.Close, null, tint = C.grey, modifier = Modifier.size(18.dp))
                }
            }
            Spacer(Modifier.height(14.dp))
            T("Update available", 22.sp, weight = FontWeight.Bold)
            T("v${v.versionName} (build ${v.versionCode}) · you have build ${BuildConfig.VERSION_CODE} · ${v.date}", 13.sp, C.grey)
            Spacer(Modifier.height(14.dp))
            T("What's new", 15.sp, weight = FontWeight.SemiBold)
            val mine = BuildConfig.VERSION_NAME
            v.changelog.takeWhile { it.version != mine }.ifEmpty { v.changelog.take(1) }.take(4).forEach { rel ->
                if (v.changelog.size > 1) T("v${rel.version}", 12.sp, C.dim, modifier = Modifier.padding(top = 6.dp))
                rel.changes.forEach { ChangeRow(it) }
            }
            Spacer(Modifier.height(16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(Modifier.weight(1f).height(48.dp).clip(RoundedCornerShape(24.dp)).background(Color.White.copy(alpha = 0.06f))
                    .border(1.dp, Color.White.copy(alpha = 0.12f), RoundedCornerShape(24.dp)).clickable { st.dismissUpdate() }, contentAlignment = Alignment.Center) {
                    T("Later", 15.sp, weight = FontWeight.SemiBold)
                }
                Box(Modifier.weight(1f).height(48.dp).clip(RoundedCornerShape(24.dp)).background(if (busy) C.teal.copy(alpha = 0.5f) else C.teal)
                    .clickable(enabled = !busy) {
                        val apk = done
                        if (apk != null) { if (Updater.canInstall(ctx)) Updater.install(ctx, apk) else err = "Allow Narrativ to install updates, then tap Install again." }
                        else scope.launch {
                            busy = true; err = null; prog = 0f
                            try { done = Updater.download(ctx, v.apkUrl, v.sha256) { p -> prog = p }; if (Updater.canInstall(ctx)) Updater.install(ctx, done!!) else err = "Allow Narrativ to install updates, then tap Install." }
                            catch (e: Exception) { err = e.message ?: "Download failed. Try again." }
                            busy = false
                        }
                    },
                    contentAlignment = Alignment.Center) {
                    T(when { busy && prog >= 0f -> "Downloading ${(prog * 100).toInt()}%"; busy -> "Downloading…"; done != null -> "Install"; else -> "Update now" },
                        15.sp, Color.Black, FontWeight.SemiBold)
                }
            }
            if (busy && prog >= 0f) Box(Modifier.padding(top = 10.dp).fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(C.chip)) {
                Box(Modifier.fillMaxWidth(prog.coerceIn(0f, 1f)).fillMaxHeight().background(C.teal))
            }
            err?.let { T(it, 12.sp, C.red, modifier = Modifier.padding(top = 10.dp)) }
            T("Downloads inside the app from GitHub Releases" + (v.sizeMb?.let { " · ${fmt(it, 1)} MB" } ?: ""), 11.sp, C.dim,
                modifier = Modifier.padding(top = 10.dp).fillMaxWidth().wrapContentWidth(Alignment.CenterHorizontally))
        }
    }
}

@Composable
fun FeedbackSheet(st: AppState) {
    val scope = rememberCoroutineScope()
    var type by remember { mutableStateOf("Idea") }
    var text by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf<String?>(null) }
    val stock = st.feedbackContext.substringAfter("Stock · ", "").substringBefore(" ·").takeIf { it.isNotBlank() }
    BottomSheet(onDismiss = { st.showFeedback = false }, title = "Feedback") {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("Idea", "Bug", "Data looks wrong", "Stock request").forEach { t -> ToggleChip(t, type == t, { type = t }) }
        }
        Box(Modifier.fillMaxWidth().heightIn(min = 130.dp).clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B0C0D))
            .border(1.dp, C.teal.copy(alpha = 0.33f), RoundedCornerShape(16.dp)).padding(14.dp)) {
            BasicTextField(text, { text = it; err = null }, textStyle = TextStyle(color = C.white, fontSize = 15.sp), cursorBrush = SolidColor(C.blue),
                modifier = Modifier.fillMaxWidth().imePadding(),
                decorationBox = { inner -> if (text.isEmpty()) T(if (type == "Stock request") "Symbol and why, e.g. DEEPINDS: check order book" else "What should change?", 15.sp, C.dim); inner() })
        }
        T("Attached: ${st.feedbackContext} · v${BuildConfig.VERSION_NAME} · data of ${shortDate(st.picks?.date)}", 12.sp, C.dim, modifier = Modifier.padding(start = 2.dp, top = 12.dp, bottom = 16.dp))
        err?.let { T(it, 13.sp, C.red, modifier = Modifier.padding(bottom = 10.dp)) }
        val ready = text.isNotBlank() && !sending
        Box(Modifier.fillMaxWidth().height(50.dp).clip(RoundedCornerShape(25.dp)).background(if (ready) C.teal else C.chip)
            .clickable(enabled = ready) {
                sending = true
                scope.launch {
                    val res = if (type == "Stock request") {
                        val sym = text.trim().split(Regex("[\\s:,]+")).first().uppercase()
                        st.requestScan(sym, text)
                    } else st.sendFeedback(type, text, stock)
                    sending = false
                    res.onSuccess { st.showFeedback = false; st.toast = if (type == "Stock request") "Queued for deep scan" else "Thanks, feedback saved" }
                        .onFailure { err = "Not sent: ${it.message}" }
                }
            }, contentAlignment = Alignment.Center) {
            T(if (sending) "Sending…" else if (type == "Stock request") "Request deep scan" else "Send feedback", 16.sp, if (ready) Color.White else C.dim, FontWeight.SemiBold)
        }
    }
}
