package com.narrativ.app

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animate
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/*
 * Card swipe (owner, 28 Nov 2026: "wherever swipe works I need animation of card swipe, like inside the stock screen").
 * The swiped content follows the finger with the next / previous page drawn edge to edge beside it (SwipePages), like the
 * stock screen's pager (owner, 28 Nov 2026: "feels like some white space in between ... can it look like swiping next screen
 * only"). Past the threshold both slide on until the neighbour fills the screen, then the page changes under it. A short
 * drag springs back. At the first / last page the drag is damped and always springs back.
 */

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

    /** dir -1: next (content leaves to the left), +1: previous, 0: spring back. */
    fun go(dir: Int, onPrev: () -> Unit, onNext: () -> Unit) {
        job?.cancel()
        val from = offset
        job = scope.launch {
            if (dir == 0) {
                animate(from, 0f, animationSpec = spring<Float>(dampingRatio = 0.85f, stiffness = Spring.StiffnessMediumLow)) { v, _ -> offset = v }
                return@launch
            }
            val w = if (width > 0f) width else 1080f
            animate(from, dir * w, animationSpec = tween<Float>(240, easing = FastOutSlowInEasing)) { v, _ -> offset = v }
            if (dir < 0) onNext() else onPrev()
            offset = 0f  // the neighbour now fills the screen: the new page takes its place with no gap
        }
    }
}

/** Swipe state; a new [key] starts a new state. */
@Composable
fun rememberCardSwipe(key: Any? = Unit): CardSwipe {
    val scope = rememberCoroutineScope()
    return remember(key) { CardSwipe(scope) }
}

/**
 * Pager-like page holder: [content] moves with the swipe and, while it is off centre, the page it is moving towards ([next]
 * when dragged left, [prev] when dragged right) is drawn edge to edge beside it. A null neighbour is not drawn (first / last
 * page). Use with [swipeGesture] on this or an outer modifier.
 */
@Composable
fun SwipePages(cs: CardSwipe, modifier: Modifier = Modifier, prev: (@Composable () -> Unit)? = null, next: (@Composable () -> Unit)? = null,
               content: @Composable () -> Unit) {
    val side by remember(cs) { derivedStateOf { if (cs.offset < 0f) -1 else if (cs.offset > 0f) 1 else 0 } }
    Box(modifier.clipToBounds().onSizeChanged { cs.width = it.width.toFloat() }) {
        if (side < 0 && next != null) Box(Modifier.fillMaxSize().graphicsLayer { translationX = cs.offset + cs.width }) { next() }
        if (side > 0 && prev != null) Box(Modifier.fillMaxSize().graphicsLayer { translationX = cs.offset - cs.width }) { prev() }
        Box(Modifier.fillMaxSize().graphicsLayer { translationX = cs.offset }) { content() }
    }
}

/** A neighbouring page drawn during a swipe: it must not take over the feedback context of the page that is showing. */
@Composable
fun Peek(st: AppState, content: @Composable () -> Unit) {
    val keep = st.screenContext
    content()
    SideEffect { st.screenContext = keep }
}

/** Horizontal drag that drives [cs]: past [threshold] px it moves to the next / previous page (if there is one). */
@Composable
fun Modifier.swipeGesture(cs: CardSwipe, canPrev: Boolean, canNext: Boolean, onPrev: () -> Unit, onNext: () -> Unit,
                          threshold: Float = 120f, enabled: Boolean = true): Modifier {
    val prevOk by rememberUpdatedState(canPrev)
    val nextOk by rememberUpdatedState(canNext)
    val prev by rememberUpdatedState(onPrev)
    val next by rememberUpdatedState(onNext)
    val limit by rememberUpdatedState(threshold)
    return this.pointerInput(cs, enabled) {
        if (!enabled) return@pointerInput
        detectHorizontalDragGestures(
            onDragEnd = {
                val o = cs.offset
                val dir = if (o < -limit && nextOk) -1 else if (o > limit && prevOk) 1 else 0
                cs.go(dir, prev, next)
            },
            onDragCancel = { cs.go(0, prev, next) },
        ) { _, d -> cs.drag(d, prevOk, nextOk) }
    }
}
