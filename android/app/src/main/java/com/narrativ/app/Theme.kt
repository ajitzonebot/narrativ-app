package com.narrativ.app

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.ImageShader
import androidx.compose.ui.graphics.ShaderBrush
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * Two looks (owner, 25 Nov 2026): Paper (cream newsprint, ink colours, serif type) and Classic (the dark look as it was).
 * Only colours, type and the paper texture change between them; every screen, section and tap is the same in both.
 * Settings › Look switches at once (no restart). Every colour is read through C / TierC, so the switch reaches all screens.
 */
object Look {
    private const val PREF = "paperLook"
    var paper by mutableStateOf(true)
    fun load(ctx: Context) { paper = ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE).getBoolean(PREF, true) }
    fun set(ctx: Context, on: Boolean) {
        paper = on
        ctx.getSharedPreferences("narrativ", Context.MODE_PRIVATE).edit().putBoolean(PREF, on).apply()
    }
}

/** Classic: the dark palette exactly as it was before the Paper look. */
private object Dark {
    val bg = Color(0xFF000000)
    val card = Color(0xFF121315)
    val card2 = Color(0xFF0E0F11)
    val chip = Color(0xFF1E2023)
    val line = Color(0xFF23262A)
    val teal = Color(0xFF3D8BFD)
    val blue = Color(0xFF7DAEFF)
    val grey = Color(0xFFB3B5B6)
    val dim = Color(0xFFA3A7AC)
    val red = Color(0xFFF0453A)
    val amber = Color(0xFFF0A33A)
    val white = Color(0xFFFFFFFF)
    val muted = Color(0xFFC9CBCD)
    val sheet = Color(0xFF1A1C1F)
    val dock = Color(0xEE121315)
    val hero = Brush.radialGradient(listOf(Color(0xFF2C5DB8), Color(0xFF16408F), Color(0xFF0A1D40), Color(0xFF000000)), radius = 1400f)
    val screen = Brush.verticalGradient(listOf(Color(0xFF16408F), Color(0xFF0A1D40), Color(0xFF050E20), Color(0xFF000000)), startY = 0f, endY = 2400f)
    val heroTop = Brush.verticalGradient(listOf(Color(0xFF16408F), Color(0xFF0A1D40), Color(0xFF000000)))
    val tile = Brush.linearGradient(listOf(Color(0xFF7DAEFF), Color(0xFF3D8BFD)))
}

/** Paper: cream newsprint with muted print inks. Text colours keep ≥ 4.5:1 on the paper; slate blue stays "you can tap this". */
private object Ink {
    val bg = Color(0xFFEDE4D3)       // paper
    val card = Color(0xFFF4EDE0)     // a lighter sheet laid on the paper
    val card2 = Color(0xFFE8DECB)
    val chip = Color(0xFFE1D5BE)
    val line = Color(0xFFCBBDA3)     // rules
    val teal = Color(0xFF2C4A72)     // slate-blue ink: tappable
    val blue = Color(0xFF2C4A72)
    val grey = Color(0xFF5E544B)
    val dim = Color(0xFF6A5F55)
    val red = Color(0xFF862A22)      // oxblood
    val amber = Color(0xFF8A5A0C)    // ochre
    val white = Color(0xFF2E2622)    // ink: the main text colour on paper
    val muted = Color(0xFF4A4038)
    val sheet = Color(0xFFEFE7D8)
    val dock = Color(0xF2F3ECDF)
    val hero = Brush.radialGradient(listOf(Color(0xFFF4EDDF), Color(0xFFEDE4D3), Color(0xFFE4D8C2)), radius = 1400f)
    val screen = Brush.verticalGradient(listOf(Color(0xFFF2EADB), Color(0xFFEDE4D3), Color(0xFFE9DFCB), Color(0xFFE4D9C4)), startY = 0f, endY = 2400f)
    val heroTop = Brush.verticalGradient(listOf(Color(0xFFF2EADB), Color(0xFFEDE4D3), Color(0xFFEDE4D3)))
    val tile = Brush.linearGradient(listOf(Color(0xFF3E5F8A), Color(0xFF2C4A72)))
}

object C {
    private val p get() = Look.paper
    val bg: Color get() = if (p) Ink.bg else Dark.bg
    val card: Color get() = if (p) Ink.card else Dark.card
    val card2: Color get() = if (p) Ink.card2 else Dark.card2
    val chip: Color get() = if (p) Ink.chip else Dark.chip
    val line: Color get() = if (p) Ink.line else Dark.line
    val teal: Color get() = if (p) Ink.teal else Dark.teal  // accent: Ocean blue (feedback #42); name kept for minimal churn
    val blue: Color get() = if (p) Ink.blue else Dark.blue
    val grey: Color get() = if (p) Ink.grey else Dark.grey
    val dim: Color get() = if (p) Ink.dim else Dark.dim  // ≥ 4:1 on the blue header gradient (was 0xFF7D8186, ≈2.4:1)
    val red: Color get() = if (p) Ink.red else Dark.red
    val amber: Color get() = if (p) Ink.amber else Dark.amber
    val white: Color get() = if (p) Ink.white else Dark.white   // main text colour (ink on Paper)
    val muted: Color get() = if (p) Ink.muted else Dark.muted   // secondary text on cards (labels in charts, chip text)
    val sheet: Color get() = if (p) Ink.sheet else Dark.sheet   // section inside a bottom sheet
    val dock: Color get() = if (p) Ink.dock else Dark.dock      // bottom dock (translucent card)
    val hero: Brush get() = if (p) Ink.hero else Dark.hero
    val screen: Brush get() = if (p) Ink.screen else Dark.screen
    val heroTop: Brush get() = if (p) Ink.heroTop else Dark.heroTop
    val tile: Brush get() = if (p) Ink.tile else Dark.tile
    /** Foreground for overlays, rules and selected chips: white on Classic, ink on Paper (was Color.White). */
    val hi: Color get() = if (p) Ink.white else Color.White
    /** The opposite of [hi]: text on a [hi]-filled chip (was Color.Black). */
    val lo: Color get() = if (p) Ink.bg else Color.Black
    /** Text and icons on the blue accent: white in both looks. */
    val onAccent: Color get() = Color.White
}

/** Design system: one place for spacing, corner radii and text sizes (every screen uses these). */
object S {
    val xs = 4.dp; val s = 8.dp; val m = 12.dp; val l = 16.dp; val xl = 24.dp      // spacing
    val card get() = if (Look.paper) 6.dp else 20.dp                                 // radii: Paper is nearly square, like a printed box
    val cardPad = 14.dp
    val inner get() = if (Look.paper) 3.dp else 8.dp
    val tile get() = if (Look.paper) 4.dp else 12.dp     // radii: card, nested = card − padding (≈6–8), standalone tile
}

/** Paper type: Source Serif for reading, Playfair Display for headlines, Anton for the masthead, Archivo for labels. */
object PaperFonts {
    val serif = FontFamily(
        Font(R.font.paper_serif_regular, FontWeight.Normal), Font(R.font.paper_serif_italic, FontWeight.Normal, FontStyle.Italic),
        Font(R.font.paper_serif_semibold, FontWeight.SemiBold), Font(R.font.paper_serif_semibold, FontWeight.Medium),
        Font(R.font.paper_serif_bold, FontWeight.Bold),
    )
    val headline = FontFamily(Font(R.font.paper_playfair_bold, FontWeight.Bold), Font(R.font.paper_playfair_bold, FontWeight.SemiBold),
        Font(R.font.paper_playfair_black, FontWeight.Black), Font(R.font.paper_playfair_black, FontWeight.ExtraBold))
    val masthead = FontFamily(Font(R.font.paper_anton, FontWeight.Normal))
    val label = FontFamily(Font(R.font.paper_archivo_medium, FontWeight.Normal), Font(R.font.paper_archivo_medium, FontWeight.Medium),
        Font(R.font.paper_archivo_bold, FontWeight.SemiBold), Font(R.font.paper_archivo_bold, FontWeight.Bold))
}

/** The family a piece of text takes: Paper sets big bold text in Playfair, the rest in Source Serif; Classic keeps the system font. */
fun paperFamily(size: TextUnit, weight: FontWeight): FontFamily? = when {
    !Look.paper -> null
    size.isSp && size.value >= 17f && weight >= FontWeight.SemiBold -> PaperFonts.headline
    else -> PaperFonts.serif
}

private var grainTile: ImageBitmap? = null

/** A small tile of fibre-like speckle, made once and repeated over the page (no image file). */
private fun grain(): ImageBitmap = grainTile ?: run {
    val n = 160
    val rnd = java.util.Random(7)
    val px = IntArray(n * n) {
        val a = (rnd.nextGaussian() * 9 + 10).toInt().coerceIn(0, 34)
        (a shl 24) or (0x3A shl 16) or (0x2E shl 8) or 0x22
    }
    android.graphics.Bitmap.createBitmap(px, n, n, android.graphics.Bitmap.Config.ARGB_8888).asImageBitmap().also { grainTile = it }
}

/** The page background: the screen gradient, plus paper grain on the Paper look. */
fun Modifier.pageBackground(): Modifier = this.background(C.screen).then(
    if (!Look.paper) Modifier else Modifier.drawBehind {
        drawRect(ShaderBrush(ImageShader(grain(), TileMode.Repeated, TileMode.Repeated)))
    }
)

@Composable
fun NarrativTheme(content: @Composable () -> Unit) {
    val scheme = if (Look.paper) lightColorScheme(
        primary = C.teal, onPrimary = Color.White, secondary = C.blue, background = C.bg, surface = C.card,
        onSurface = C.white, onBackground = C.white, surfaceVariant = C.chip, outline = C.line, error = C.red,
    ) else darkColorScheme(
        primary = C.teal, onPrimary = Color.Black, secondary = C.blue, background = C.bg, surface = C.card,
        onSurface = C.white, onBackground = C.white, surfaceVariant = C.chip, outline = C.line, error = C.red,
    )
    MaterialTheme(colorScheme = scheme) {
        // tabular digits everywhere: prices, %, counts and ranks line up in columns
        val base = LocalTextStyle.current.copy(fontFeatureSettings = "tnum")
        CompositionLocalProvider(LocalTextStyle provides (if (Look.paper) base.copy(fontFamily = PaperFonts.serif) else base), content = content)
    }
}

// ---------------------------------------------------------------- Paper layout pieces (newspaper structure)

/** Corner radius: as given on Classic, square (≤ 2 dp) on Paper, like print. */
fun rr(r: androidx.compose.ui.unit.Dp): androidx.compose.foundation.shape.RoundedCornerShape =
    androidx.compose.foundation.shape.RoundedCornerShape(if (Look.paper) minOf(r, 2.dp) else r)

/** A thick-over-thin (or thin-over-thick) double rule across the width, in ink. */
@Composable
fun DoubleRule(modifier: Modifier = Modifier, thickFirst: Boolean = true) {
    val ink = C.white
    androidx.compose.foundation.layout.Column(modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Box(Modifier.fillMaxWidth().height(if (thickFirst) 3.dp else 1.dp).background(ink))
        androidx.compose.foundation.layout.Spacer(Modifier.height(2.dp))
        androidx.compose.foundation.layout.Box(Modifier.fillMaxWidth().height(if (thickFirst) 1.dp else 3.dp).background(ink))
    }
}


/** A small capitalised label in Archivo (section names, tags, tab labels on Paper). */
@Composable
fun PaperLabel(text: String, color: Color = C.white, size: TextUnit = 11.sp, bold: Boolean = true, modifier: Modifier = Modifier) =
    androidx.compose.material3.Text(text.uppercase(), modifier, fontSize = size, color = color, fontFamily = PaperFonts.label,
        fontWeight = if (bold) FontWeight.Bold else FontWeight.Medium, letterSpacing = 0.8.sp, maxLines = 1,
        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
