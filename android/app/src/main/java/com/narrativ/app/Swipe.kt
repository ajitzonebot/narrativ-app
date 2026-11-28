package com.narrativ.app

import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animate
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.lazy.LazyItemScope
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/*
 * Card swipe (owner, 28 Nov 2026: "wherever swipe works I need animation of card swipe, like inside the stock screen").
 * The swiped content follows the finger; past the threshold it slides out, the change runs (next / previous page),
 * and the new content slides in from the other side. A short drag springs back. At the first / last page the drag
 * is damped and always springs back.
 */

/** Start offsets handed from a page that slid out to the new composition that slides in (key -> px). */
private val swipeHandoff = HashMap<String, Float>()

@Stable
class CardSwipe internal constructor(private val scope: CoroutineScope) {
    /** Horizontal offset of the swiped content, px. */
    var offset by mutableFloatStateOf(0f)
        internal set
    internal var width = 0f
    private var job: Job? = null

    internal fun drag(d: Float, canPrev: Boolean, canNext: Boolean) {
        job?.cancel()
        val o = offset + d
        offset = if ((o > 0f && !canPrev) || (o < 0f && !canNext)) offset + d * 0.3f else o
    }

    /**
     * dir -1: next (content leaves to the left), +1: previous, 0: spring back. With [handoff], the new page is a new
     * composition (rememberCardSwipe with the same handoff key) and slides itself in.
     */
    fun go(dir: Int, onPrev: () -> Unit, onNext: () -> Unit, handoff: String? = null) {
        job?.cancel()
        val from = offset
        job = scope.launch {
            if (dir == 0) {
                animate(from, 0f, animationSpec = spring<Float>(dampingRatio = 0.85f, stiffness = Spring.StiffnessMediumLow)) { v, _ -> offset = v }
                return@launch
            }
            val w = if (width > 0f) width else 1080f
            animate(from, dir * w, animationSpec = tween<Float>(170, easing = FastOutLinearInEasing)) { v, _ -> offset = v }
            if (handoff != null) swipeHandoff[handoff] = -dir * w
            if (dir < 0) onNext() else onPrev()
            if (handoff != null) return@launch
            offset = -dir * w
            animate(-dir * w, 0f, animationSpec = tween<Float>(260, easing = LinearOutSlowInEasing)) { v, _ -> offset = v }
        }
    }

    internal fun enter() {
        val from = offset
        if (from == 0f) return
        job?.cancel()
        job = scope.launch { animate(from, 0f, animationSpec = tween<Float>(260, easing = LinearOutSlowInEasing)) { v, _ -> offset = v } }
    }
}

/** Swipe state; a new [key] starts a new state (and, with [handoff], slides in when the previous page handed over). */
@Composable
fun rememberCardSwipe(key: Any? = Unit, handoff: String? = null): CardSwipe {
    val scope = rememberCoroutineScope()
    val cs = remember(key) {
        CardSwipe(scope).also { c ->
            val start = handoff?.let { swipeHandoff.remove(it) }
            if (start != null) c.offset = start
        }
    }
    LaunchedEffect(cs) { cs.enter() }
    return cs
}

/** The layer that moves with the swipe. Put it after (inside) the gesture modifier, never before it. */
fun Modifier.swipeLayer(cs: CardSwipe): Modifier =
    this.onSizeChanged { cs.width = it.width.toFloat() }.graphicsLayer { translationX = cs.offset }

/** Horizontal drag that drives [cs]: past [threshold] px it moves to the next / previous page (if there is one). */
@Composable
fun Modifier.swipeGesture(cs: CardSwipe, canPrev: Boolean, canNext: Boolean, onPrev: () -> Unit, onNext: () -> Unit,
                          threshold: Float = 120f, handoff: String? = null, enabled: Boolean = true): Modifier {
    val prevOk by rememberUpdatedState(canPrev)
    val nextOk by rememberUpdatedState(canNext)
    val prev by rememberUpdatedState(onPrev)
    val next by rememberUpdatedState(onNext)
    val limit by rememberUpdatedState(threshold)
    val hand by rememberUpdatedState(handoff)
    return this.pointerInput(cs, enabled) {
        if (!enabled) return@pointerInput
        detectHorizontalDragGestures(
            onDragEnd = {
                val o = cs.offset
                val dir = if (o < -limit && nextOk) -1 else if (o > limit && prevOk) 1 else 0
                cs.go(dir, prev, next, hand)
            },
            onDragCancel = { cs.go(0, prev, next) },
        ) { _, d -> cs.drag(d, prevOk, nextOk) }
    }
}

/** List items added through this scope sit in the swipe layer (items added straight to the list, such as a header, stay put). */
@OptIn(ExperimentalFoundationApi::class)
class SwipeItems(private val base: LazyListScope, private val cs: CardSwipe) : LazyListScope by base {
    override fun item(key: Any?, contentType: Any?, content: @Composable LazyItemScope.() -> Unit) {
        val c = cs
        base.item(key, contentType) {
            val scope = this
            Box(Modifier.swipeLayer(c)) { scope.content() }
        }
    }

    override fun items(count: Int, key: ((index: Int) -> Any)?, contentType: (index: Int) -> Any?,
                       itemContent: @Composable LazyItemScope.(index: Int) -> Unit) {
        val c = cs
        base.items(count, key, contentType) { i ->
            val scope = this
            Box(Modifier.swipeLayer(c)) { scope.itemContent(i) }
        }
    }
}
