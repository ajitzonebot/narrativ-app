@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.narrativ.app

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Feedback
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * Shared building blocks of the redesign (approved mockups, scratchpad/mock/kit.py + screens_*.py).
 * Status words, not symbols: Pass / Partly / Miss / n/a. Colour only for meaning; blue (C.blue) for taps.
 */

// ---------------------------------------------------------------- status, severity
val STATUS_COLORS get() = mapOf("Pass" to TierC.lightGreen, "Partly" to TierC.yellow, "Miss" to TierC.lightRed, "n/a" to C.dim,
    "Pending" to C.grey, "Met" to TierC.lightGreen, "Verified" to TierC.lightGreen)
/** Check mark (Item.m: 2 full, 1 partial, 0 miss, null not scored) as a status word. */
fun statusOf(m: Int?): String = when (m) { 2 -> "Pass"; 1 -> "Partly"; 0 -> "Miss"; else -> "n/a" }
fun statusColor(s: String): Color = STATUS_COLORS[s] ?: C.dim
/** Filing severity (Ev.sev): red can break the case, watch (amber) needs a look, green can be a trigger, info routine. */
fun sevColor(sev: String?): Color = when (sev) { "red" -> TierC.red; "watch" -> C.amber; "green" -> TierC.darkGreen; else -> C.dim }

/** Status word in a tinted pill (Pass / Partly / Miss / n/a, or any word with a colour). */
@Composable
fun StatusChip(status: String, modifier: Modifier = Modifier, color: Color = statusColor(status), minWidth: Dp = 52.dp) {
    Box(modifier.defaultMinSize(minWidth = minWidth).clip(rr(S.inner)).background(color.copy(alpha = 0.13f))
        .padding(horizontal = 8.dp, vertical = 3.dp), contentAlignment = Alignment.Center) {
        T(status, 11.sp, color, FontWeight.Bold, maxLines = 1)
    }
}

/** Claude's review mark next to a stock code: filled green = verified, outline = researched but not verified. */
@Composable
fun VerifiedTick(verified: Boolean, modifier: Modifier = Modifier, size: Dp = 15.dp) {
    Box(modifier.size(size).clip(CircleShape)
        .then(if (verified) Modifier.background(TierC.lightGreen) else Modifier.border(1.dp, TierC.grey, CircleShape)),
        contentAlignment = Alignment.Center) {
        Icon(Icons.Rounded.Check, if (verified) "Verified by Narrativ.ai" else "Researched by Narrativ.ai, not verified",
            tint = if (verified) C.lo else C.dim, modifier = Modifier.size(size * 0.73f))
    }
}

/** Small chip with a colour dot (legends, rotation, quadrant tags). */
@Composable
fun DotChip(text: String, color: Color, modifier: Modifier = Modifier, textColor: Color = C.muted) {
    Row(modifier.clip(rr(S.inner)).background(C.hi.copy(alpha = 0.063f)).padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(color))
        T(text, 11.sp, textColor, maxLines = 1)
    }
}

/** Legend row: small square + name per series. */
@Composable
fun Legend(items: List<Pair<String, Color>>, modifier: Modifier = Modifier) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
        items.forEach { (n, c) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(rr(2.dp)).background(c)); Spacer(Modifier.width(5.dp)); T(n, 11.sp, C.dim, maxLines = 1)
            }
        }
    }
}

// ---------------------------------------------------------------- level head, checks
/** Top card of a level tab: level name, tier name in tier colour, score/100, five-tier scale, one line. */
@Composable
fun LevelHead(level: String, tierName: String, tier: Int, score: Int?, line: String?, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null) {
    Card(modifier.fillMaxWidth(), onClick = onClick) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
            Column(Modifier.weight(1f)) {
                T(level, 12.sp, C.dim, maxLines = 1)
                // long names ("Turnaround watch", "Not enough data") shrink and may wrap instead of truncating on 360 dp phones
                val long = tierName.length > 12
                T(tierName, if (long) 22.sp else 26.sp, tierColor(tier), FontWeight.Bold, maxLines = 2, lineHeight = if (long) 26.sp else 30.sp)
            }
            Row {
                if (score != null) {
                    T("$score", 26.sp, weight = FontWeight.Bold, modifier = Modifier.alignByBaseline())
                    T("/100", 13.sp, C.dim, modifier = Modifier.alignByBaseline())
                } else T("No score", 12.sp, C.dim, modifier = Modifier.padding(bottom = 6.dp))
            }
        }
        TierScale(tier, Modifier.fillMaxWidth().padding(vertical = 10.dp))
        line?.let { T(it, 13.sp, lineHeight = 18.sp) }
    }
}

/**
 * One key check: status chip, name, figure (bold, right) and under it an optional [bullet] with the
 * small pass-line text ("full ≥ 15%").
 */
@Composable
fun CheckRow(status: String, name: String, figure: String, passLine: String? = null, modifier: Modifier = Modifier,
             bullet: (@Composable () -> Unit)? = null, divider: Boolean = true, onClick: (() -> Unit)? = null) {
    Column(modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)) {
        Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatusChip(status)
            T(name, 14.sp, modifier = Modifier.weight(1f), maxLines = 2, lineHeight = 18.sp)
            Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(3.dp)) {
                T(cap(figure), 15.sp, weight = FontWeight.Bold, maxLines = 1)
                if (bullet != null || passLine != null) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    bullet?.invoke()
                    passLine?.let { T(cap(it), 11.sp, C.dim, maxLines = 1) }
                }
            }
        }
        if (divider) HLineDivider()
    }
}

/** True inside a BottomSheet: pop-ups have no divider lines (owner, 27 Nov 2026, feedback #195 #201 #203). */
val LocalInSheet = androidx.compose.runtime.staticCompositionLocalOf { false }

@Composable
fun HLineDivider(modifier: Modifier = Modifier) = if (LocalInSheet.current) {
    Box(modifier.fillMaxWidth().height(1.dp))
} else if (Look.paper) {
    val c = C.dim
    Box(modifier.fillMaxWidth().height(1.dp).drawBehind {
        drawLine(c, androidx.compose.ui.geometry.Offset(0f, 0.5f), androidx.compose.ui.geometry.Offset(size.width, 0.5f), 1.dp.toPx(),
            pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(2.dp.toPx(), 3.dp.toPx())))
    })
} else Box(modifier.fillMaxWidth().height(1.dp).background(C.line))

// ---------------------------------------------------------------- cards and rows
/** Card with an optional header (title left, small grey text right) and an optional blue "more" link at the bottom. */
@Composable
fun SectionCard(title: String? = null, right: String? = null, modifier: Modifier = Modifier, more: String? = null, onMore: (() -> Unit)? = null,
                pad: Dp = 14.dp, onClick: (() -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Card(modifier.fillMaxWidth(), pad = pad, onClick = onClick) {
        if (title != null || right != null) {
            Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.Bottom) {
                T(title ?: "", 15.sp, weight = FontWeight.SemiBold, modifier = Modifier.weight(1f), maxLines = 1)
                right?.let { T(it, 12.sp, C.dim, maxLines = 1, modifier = Modifier.padding(start = 8.dp)) }
            }
        }
        content()
        if (more != null) MoreLink(more, onClick = onMore ?: {})
    }
}

/** Blue link with a chevron ("All 7 checks with formulas ›"). */
@Composable
fun MoreLink(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Row(modifier.clip(rr(8.dp)).clickable(onClick = onClick).padding(top = 8.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        T(text, 13.sp, C.blue, maxLines = 1)
        Icon(Icons.Rounded.ChevronRight, null, tint = C.blue, modifier = Modifier.size(16.dp))
    }
}

/** Key–value row: grey key left, bold value right, hairline under it. [trailing] replaces the value text (e.g. a Meter). */
@Composable
fun KvRow(key: String, value: String = "", modifier: Modifier = Modifier, valueColor: Color = C.white, divider: Boolean = true,
          onClick: (() -> Unit)? = null, trailing: (@Composable () -> Unit)? = null) {
    Column(modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
            T(key, 13.sp, C.dim, modifier = Modifier.weight(1f), maxLines = 2)
            Spacer(Modifier.width(10.dp))
            if (trailing != null) trailing() else T(value, 13.sp, valueColor, FontWeight.Bold, maxLines = 1)
        }
        if (divider) HLineDivider()
    }
}

/** Collapsed row that opens more ("What was checked  9 items ⌄"). */
@Composable
fun ToggleRow(label: String, right: String = "", expanded: Boolean, onToggle: () -> Unit, modifier: Modifier = Modifier, divider: Boolean = true) {
    Column(modifier.fillMaxWidth()) {
        if (divider) HLineDivider()
        Row(Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            T(label, 13.sp, modifier = Modifier.weight(1f), maxLines = 1)
            if (right.isNotEmpty()) T(right, 12.sp, C.dim, maxLines = 1)
            Icon(if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore, null, tint = C.dim, modifier = Modifier.padding(start = 4.dp).size(16.dp))
        }
    }
}

/** Grid tile: small grey label, bold figure, optional mini chart under it. */
@Composable
fun StatTile(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = C.white, onClick: (() -> Unit)? = null,
             content: (@Composable ColumnScope.() -> Unit)? = null) {
    Card(modifier, radius = S.tile, pad = 11.dp, onClick = onClick) {
        T(label, 11.sp, C.dim, maxLines = 1)
        T(value, 16.sp, valueColor, FontWeight.Bold, maxLines = 1)
        if (content != null) { Spacer(Modifier.height(6.dp)); content() }
    }
}

/** Section inside a bottom sheet (darker tile) with a sentence-case header (13 sp semibold) and optional right text. */
@Composable
fun SheetSection(title: String? = null, right: String? = null, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().padding(bottom = 10.dp).clip(rr(16.dp)).background(C.sheet).padding(12.dp)) {
        if (title != null) Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            T(title, 13.sp, C.muted, FontWeight.SemiBold, Modifier.weight(1f), maxLines = 1)
            right?.let { T(it, LABEL, C.dim, maxLines = 1) }
        }
        content()
    }
}

// ---------------------------------------------------------------- tabs, toggles, chips
/** A tab in [TabStrip]: label and optional tier dot. */
data class TabSpec(val label: String, val dot: Color? = null)

/** Scrollable pill tabs (stock page: 9 tabs with tier dots). The active tab is white and scrolled to the centre. */
@Composable
fun TabStrip(tabs: List<TabSpec>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier, sidePad: Dp = 16.dp) {
    val scroll = rememberScrollState()
    val pos = remember { mutableStateMapOf<Int, Pair<Int, Int>>() }
    var viewport by remember { mutableIntStateOf(0) }
    LaunchedEffect(selected, pos[selected], viewport) {
        val (x, w) = pos[selected] ?: return@LaunchedEffect
        if (viewport > 0) scroll.animateScrollTo((x + w / 2 - viewport / 2).coerceIn(0, scroll.maxValue))
    }
    Row(modifier.fillMaxWidth().onSizeChanged { viewport = it.width }.horizontalScroll(scroll).padding(horizontal = sidePad),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        tabs.forEachIndexed { i, t ->
            val on = i == selected
            val ink = C.white
            Row(Modifier.onGloballyPositioned { pos[i] = it.positionInParent().x.toInt() to it.size.width }
                .clip(rr(16.dp)).then(if (Look.paper) Modifier.drawBehind {
                    if (on) drawRect(ink, androidx.compose.ui.geometry.Offset(0f, size.height - 2.dp.toPx()), androidx.compose.ui.geometry.Size(size.width, 2.dp.toPx()))
                } else Modifier.background(if (on) C.hi else C.hi.copy(alpha = 0.063f)))
                .clickable { onSelect(i) }.padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                t.dot?.let { Box(Modifier.size(8.dp).clip(CircleShape).background(it)) }
                if (Look.paper) PaperLabel(t.label, if (on) C.white else C.dim, 12.sp, bold = on)
                else T(t.label, 13.sp, if (on) C.lo else C.dim, if (on) FontWeight.SemiBold else FontWeight.Normal, maxLines = 1)
            }
        }
    }
}

/**
 * Two or more options as one control. Default: full-width track, active option white (Industries | Sectors).
 * [compact]: small pills, active one lightly filled (1M 3M 6M 1Y on a chart).
 */
@Composable
fun SegmentedControl(options: List<String>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier, compact: Boolean = false) {
    if (compact) {
        Row(modifier, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            options.forEachIndexed { i, o ->
                Box(Modifier.clip(rr(10.dp)).background(if (i == selected) C.hi.copy(alpha = 0.08f) else Color.Transparent)
                    .clickable { onSelect(i) }.padding(horizontal = 10.dp, vertical = 4.dp)) { T(o, 12.sp, if (i == selected) C.white else C.dim, maxLines = 1) }
            }
        }
    } else {
        Row(modifier.fillMaxWidth().clip(rr(14.dp)).background(C.hi.copy(alpha = 0.063f)).padding(3.dp)) {
            options.forEachIndexed { i, o ->
                Box(Modifier.weight(1f).clip(rr(11.dp)).background(if (i == selected) C.hi else Color.Transparent)
                    .clickable { onSelect(i) }.padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
                    T(o, 13.sp, if (i == selected) C.lo else C.dim, if (i == selected) FontWeight.SemiBold else FontWeight.Normal, maxLines = 1)
                }
            }
        }
    }
}

/**
 * Filter chip with an optional count ("All 41", "Red flags 0"), colour dot or icon. Selected: blue fill, or with [accent]
 * a tinted fill and border in that colour ("Verified only").
 */
@Composable
fun ToggleChip(label: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier, count: Int? = null,
               dot: Color? = null, accent: Color? = null, icon: ImageVector? = null, solidOn: Boolean = false) {
    val bg = when { !selected -> C.chip; accent != null -> accent.copy(alpha = 0.15f); else -> C.teal }
    val p = Look.paper
    // solidOn (Paper): when on, filled in the accent with white letters (the High conviction Buy chip, #205)
    val solid = p && solidOn && selected && accent != null
    Row(modifier.clip(rr(16.dp)).then(if (solid) Modifier.background(accent!!) else if (p) Modifier.border(1.dp, if (selected) (accent ?: C.teal) else C.line) else Modifier.background(bg))
        .then(if (selected && accent != null && !p) Modifier.border(1.dp, accent, rr(16.dp)) else Modifier)
        .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        val onFill = selected && accent == null && !Look.paper  // solid blue fill (Classic): white text
        icon?.let { Icon(it, null, tint = accent ?: if (onFill) C.onAccent else C.white, modifier = Modifier.size(14.dp)) }
        dot?.let { Box(Modifier.size(8.dp).clip(CircleShape).background(it)) }
        if (Look.paper) PaperLabel(label, if (solid) Color.White else if (selected) (accent ?: C.teal) else C.white, 11.sp, bold = selected)
        else T(label, 13.sp, if (onFill) C.onAccent else if (selected) C.white else C.muted, maxLines = 1)
        count?.let { T("$it", 12.sp, if (solid) Color.White else if (onFill) C.onAccent.copy(alpha = 0.8f) else if (selected) C.hi.copy(alpha = 0.8f) else C.dim, maxLines = 1) }
    }
}

// ---------------------------------------------------------------- sheet, header bits
/**
 * Modal bottom sheet in the app style: grab handle, optional title row with a grey [aside] and a close button,
 * scrollable content. Use for "All reasons and checks", "Promises", "How we know", filters.
 */
@Composable
fun BottomSheet(onDismiss: () -> Unit, title: String? = null, aside: String? = null, titleExtra: (@Composable () -> Unit)? = null,
                feedback: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    // feedback #212 (owner, 27 Nov 2026): sheets on the same paper as the pages (paper colour and grain), not a flat card colour
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = if (Look.paper) C.bg else C.card,
        dragHandle = { Box(Modifier.padding(top = 10.dp, bottom = 12.dp).size(36.dp, 4.dp).clip(rr(2.dp)).background(C.hi.copy(alpha = 0.25f))) }) {
        Column(Modifier.fillMaxWidth().then(if (Look.paper) Modifier.pageBackground() else Modifier).verticalScroll(rememberScrollState())
            .padding(start = 16.dp, end = 16.dp, bottom = 24.dp).navigationBarsPadding()) {
            if (title != null) Row(Modifier.fillMaxWidth().padding(bottom = 12.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                T(title, 19.sp, weight = FontWeight.Bold, modifier = Modifier.weight(1f), maxLines = 2)
                titleExtra?.invoke()
                aside?.let { T(it, 13.sp, C.dim, maxLines = 1) }
                // feedback #151: feedback from inside a sheet, tagged with the screen and the sheet's title
                if (feedback) AppRef.st?.let { st -> FeedbackButton(st, "${st.screenContext} · $title") }
                Icon(Icons.Rounded.Close, "Close", tint = C.dim, modifier = Modifier.clip(CircleShape).clickable(onClick = onDismiss).padding(2.dp).size(22.dp))
            }
            androidx.compose.runtime.CompositionLocalProvider(LocalInSheet provides true) { content() }
        }
    }
}

/** Round 40 dp icon button on the screen gradient (back, watch, search). */
@Composable
fun IconBtn(icon: ImageVector, description: String?, modifier: Modifier = Modifier, tint: Color = C.white, onClick: () -> Unit) {
    Box(modifier.size(40.dp).clip(CircleShape).then(if (Look.paper) Modifier else Modifier.background(C.hi.copy(alpha = 0.08f)))
        .clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(icon, description, tint = tint, modifier = Modifier.size(20.dp))
    }
}

/** The in-app feedback button; every screen's top bar shows it (it opens the feedback sheet tagged with [context]). */
@Composable
fun FeedbackButton(st: AppState, context: String, modifier: Modifier = Modifier) =
    IconBtn(Icons.Rounded.Feedback, "Send feedback", modifier, C.blue) { st.openFeedback(context) }

/** Small open-in-new icon after a link's text (the ↗ glyph is missing from the Paper fonts). */
@Composable
fun LinkIcon(size: androidx.compose.ui.unit.Dp = 14.dp) =
    Icon(Icons.AutoMirrored.Rounded.OpenInNew, null, tint = C.blue, modifier = Modifier.padding(start = 4.dp).size(size))

/**
 * Top bar of the redesign: optional back button, title (20 sp; 17 sp with a [subtitle], as the stock header),
 * [actions] (e.g. watch heart) and always the feedback button. [context] tags feedback with the screen name.
 */
@Composable
fun TopBar(st: AppState, title: String, context: String = title, subtitle: String? = null, back: Boolean = true,
           big: Boolean = false, link: String? = null, actions: @Composable RowScope.() -> Unit = {}) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    // feedback #168: the subtitle (the company name) with an open-in-new icon opens [link], the company's website
    val sub = subtitle
    val subMod = if (link != null) Modifier.clickable { openUrl(ctx, link) } else Modifier
    SideEffect { st.screenContext = context }
    Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 16.dp, vertical = 4.dp).heightIn(min = 48.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        if (back) IconBtn(Icons.AutoMirrored.Rounded.ArrowBack, "Back") { st.back() }
        Column(Modifier.weight(1f)) {
            if (Look.paper) {
                // feedback #127: the name once, at the top and larger (stock page: code as the headline, company name in italic)
                androidx.compose.material3.Text(title, fontSize = if (big) 28.sp else if (subtitle != null) 24.sp else 20.sp, lineHeight = 28.sp, color = C.white,
                    fontFamily = PaperFonts.headline, fontWeight = FontWeight.Black, maxLines = 1)
                sub?.let { Row(subMod, verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.Text(it, fontSize = 13.sp, color = if (link != null) C.blue else C.muted, fontFamily = PaperFonts.headline,
                        fontStyle = androidx.compose.ui.text.font.FontStyle.Italic, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, false))
                    if (link != null) LinkIcon()
                } }
            } else {
                T(title, if (big) 26.sp else if (subtitle != null) 17.sp else 20.sp, weight = FontWeight.Bold, maxLines = 1)
                sub?.let { Row(subMod, verticalAlignment = Alignment.CenterVertically) {
                    T(it, 12.sp, if (link != null) C.blue else C.dim, maxLines = 1, modifier = Modifier.weight(1f, false)); if (link != null) LinkIcon()
                } }
            }
        }
        actions()
        FeedbackButton(st, context)
    }
    if (Look.paper) DoubleRule(Modifier.padding(horizontal = 16.dp).padding(bottom = 8.dp))
}

/** One-line market strip on Home (mini mood gauge, score · zone, a figure on the right); opens Market. */
@Composable
fun MarketStrip(score: Int?, zone: String?, right: String?, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val ink = C.white
    Row(modifier.fillMaxWidth().clip(rr(14.dp)).then(if (Look.paper) Modifier.drawBehind {
            drawLine(ink, androidx.compose.ui.geometry.Offset(0f, 0f), androidx.compose.ui.geometry.Offset(size.width, 0f), 1.dp.toPx())
            drawLine(ink, androidx.compose.ui.geometry.Offset(0f, size.height), androidx.compose.ui.geometry.Offset(size.width, size.height), 1.dp.toPx())
        } else Modifier.background(C.hi.copy(alpha = 0.07f))).clickable(onClick = onClick)
        .padding(horizontal = 12.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (score != null) Gauge(score, Modifier.size(36.dp, 22.dp), mini = true)
        T("Market", 13.sp, C.dim, maxLines = 1)
        if (score != null) {
            T("$score ·", 13.sp, weight = FontWeight.SemiBold, maxLines = 1)
            T(zone ?: "", 13.sp, zoneColor(score.toDouble()), FontWeight.SemiBold, maxLines = 1)
        } else T("Mood after the next run", 13.sp, C.dim, maxLines = 1)
        T(right ?: "", 13.sp, C.muted, modifier = Modifier.weight(1f), maxLines = 1, align = androidx.compose.ui.text.style.TextAlign.End)
        Icon(Icons.Rounded.ChevronRight, null, tint = C.dim, modifier = Modifier.size(18.dp))
    }
}

// ---------------------------------------------------------------- previews (Android Studio only)
@Preview(widthDp = 360, backgroundColor = 0xFF000000, showBackground = true)
@Composable
private fun UiPreview() = NarrativTheme {
    Column(Modifier.background(C.bg).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        MarketStrip(37, "Fear", "Nifty +6.3% vs 200-day", {})
        TabStrip(listOf(TabSpec("Summary"), TabSpec("Stability", TierC.darkGreen), TabSpec("Quality", TierC.darkGreen)), 2, {})
        LevelHead("Business quality", "Good", 2, 76, "ROCE 20.4% (last 4Q 19.1%); 6 of 7 checks pass.")
        SectionCard("Key checks", more = "All 7 checks with formulas") {
            BarCheckRow(KeyCheck("Partly", "Cash conversion", "68%", "pass ≥ 70%"), Bullet(68.0, 0.0, 100.0, 70.0, unit = "%"))
            CheckRow("Pass", "ROCE", "20.4%", "full ≥ 15%", divider = false)
            KvRow("Upside vs risk", "3.6×", divider = false)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            ToggleChip("All", true, {}, count = 41); ToggleChip("Watch", false, {}, count = 2, dot = C.amber)
            StatusChip("Miss"); DecisionChip("Buy"); VerifiedTick(true); VerifiedTick(false)
        }
        SegmentedControl(listOf("Industries 53", "Sectors 13"), 0, {})
        SegmentedControl(listOf("1M", "3M", "6M", "1Y"), 3, {}, compact = true)
    }
}
