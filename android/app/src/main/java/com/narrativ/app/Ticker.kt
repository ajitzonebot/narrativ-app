package com.narrativ.app

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** One value in the Home strip (feedback #145): Nifty 50, Sensex, Gift Nifty, gold 22K per 10 g. */
data class Tick(val k: String, val name: String, val p: Double, val prev: Double?) {
    val pct: Double? get() = prev?.takeIf { it > 0 }?.let { (p / it - 1) * 100 }
}

object Ticker {
    /** Last values seen, kept while the app runs so Home shows them at once when it opens again. */
    var last by mutableStateOf<Map<String, Tick>>(emptyMap())

    /** GET /ticker from the Narrativ API. A source that failed is missing; the last value seen for it is kept. */
    suspend fun load(repo: Repo) {
        val o = repo.apiGet("ticker") ?: return
        val got = runCatching {
            o["items"]!!.jsonArray.mapNotNull { e ->
                val m = e.jsonObject
                val k = m["k"]?.jsonPrimitive?.content ?: return@mapNotNull null
                val p = m["p"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
                Tick(k, m["name"]?.jsonPrimitive?.content ?: k.uppercase(), p, m["prev"]?.jsonPrimitive?.doubleOrNull)
            }
        }.getOrDefault(emptyList())
        if (got.isNotEmpty()) last = last + got.associateBy { it.k }
    }
}

/** Polls /ticker while Home is on screen: every 30 s in NSE hours, every 5 min otherwise (Gift Nifty trades nearly round the clock). */
@Composable
fun rememberTicker(st: AppState): Map<String, Tick> {
    val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    LaunchedEffect(owner) {
        owner.lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
            while (true) {
                Ticker.load(st.repo)
                delay(if (Portfolio.marketOpen()) 30_000L else 300_000L)
            }
        }
    }
    return Ticker.last
}

/** Two columns beside the logo; each holds a value 4 s, then the name lifts up and the next slides in
 *  (Nifty 50 ↔ Gift Nifty, Sensex ↔ Gold). The right column turns 0.4 s after the left. */
@Composable
fun PaperTicker(ticks: Map<String, Tick>, modifier: Modifier = Modifier) {
    val left = listOfNotNull(ticks["nifty"], ticks["gift"])
    val right = listOfNotNull(ticks["sensex"], ticks["gold22"])
    if (left.isEmpty() && right.isEmpty()) { Spacer(modifier); return }
    Row(modifier.height(IntrinsicSize.Min), verticalAlignment = Alignment.CenterVertically) {
        TickColumn(left, 0L, Modifier.weight(1f))
        if (left.isNotEmpty() && right.isNotEmpty()) Box(Modifier.width(1.dp).fillMaxHeight().padding(vertical = 2.dp).background(C.line))
        TickColumn(right, 400L, Modifier.weight(1f))
    }
}

@Composable
private fun TickColumn(items: List<Tick>, offset: Long, modifier: Modifier) {
    var i by remember { mutableIntStateOf(0) }
    LaunchedEffect(items.size) {
        if (items.size < 2) return@LaunchedEffect
        delay(offset)
        while (true) { delay(4_000); i = (i + 1) % items.size }
    }
    val t = items.getOrNull(i % items.size.coerceAtLeast(1)) ?: return Spacer(modifier)
    AnimatedContent(t, modifier.padding(horizontal = 8.dp), transitionSpec = {
        (slideInVertically(tween(450)) { it } togetherWith slideOutVertically(tween(450)) { -it })
    }, label = "tick", contentKey = { it.k }) { v -> TickCell(v) }
}

@Composable
private fun TickCell(t: Tick) {
    Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            PaperLabel(t.name, C.dim, 9.sp)
            val pc = t.pct
            if (pc != null) T(arrowPct(pc), 10.sp, if (pc >= 0) TierC.darkGreen else TierC.lightRed, maxLines = 1)
            else if (t.k == "gold22") T("Today", 10.sp, C.dim, maxLines = 1)
        }
        androidx.compose.material3.Text((if (t.k == "gold22") "₹" else "") + fmt(t.p, 0), fontSize = 16.sp, lineHeight = 19.sp,
            color = C.white, fontFamily = PaperFonts.headline, fontWeight = FontWeight.Bold, maxLines = 1)
    }
}
