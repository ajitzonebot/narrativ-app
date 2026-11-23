package com.narrativ.app

import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.unit.dp
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

object C {
    val bg = Color(0xFF000000)
    val card = Color(0xFF121315)
    val card2 = Color(0xFF0E0F11)
    val chip = Color(0xFF1E2023)
    val line = Color(0xFF23262A)
    val teal = Color(0xFF3D8BFD)  // accent: Ocean blue (feedback #42); name kept for minimal churn
    val blue = Color(0xFF7DAEFF)
    val grey = Color(0xFFB3B5B6)
    val dim = Color(0xFFA3A7AC)  // ≥ 4:1 on the blue header gradient (was 0xFF7D8186, ≈2.4:1)
    val red = Color(0xFFF0453A)
    val amber = Color(0xFFF0A33A)
    val white = Color(0xFFFFFFFF)
    val muted = Color(0xFFC9CBCD)   // secondary text on cards (labels in charts, chip text)
    val sheet = Color(0xFF1A1C1F)   // section inside a bottom sheet
    val dock = Color(0xEE121315)    // bottom dock (translucent card)
    val hero = Brush.radialGradient(listOf(Color(0xFF2C5DB8), Color(0xFF16408F), Color(0xFF0A1D40), Color(0xFF000000)), radius = 1400f)
    val screen = Brush.verticalGradient(listOf(Color(0xFF16408F), Color(0xFF0A1D40), Color(0xFF050E20), Color(0xFF000000)), startY = 0f, endY = 2400f)
    val heroTop = Brush.verticalGradient(listOf(Color(0xFF16408F), Color(0xFF0A1D40), Color(0xFF000000)))
    val tile = Brush.linearGradient(listOf(Color(0xFF7DAEFF), Color(0xFF3D8BFD)))
}

/** Design system: one place for spacing, corner radii and text sizes (every screen uses these). */
object S {
    val xs = 4.dp; val s = 8.dp; val m = 12.dp; val l = 16.dp; val xl = 24.dp      // spacing
    val card = 20.dp; val cardPad = 14.dp; val inner = 8.dp; val tile = 12.dp     // radii: card, nested = card − padding (≈6–8), standalone tile
}

@Composable
fun NarrativTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = C.teal, onPrimary = Color.Black, secondary = C.blue, background = C.bg, surface = C.card,
            onSurface = C.white, onBackground = C.white, surfaceVariant = C.chip, outline = C.line, error = C.red,
        ),
    ) {
        // tabular digits everywhere: prices, %, counts and ranks line up in columns
        CompositionLocalProvider(LocalTextStyle provides LocalTextStyle.current.copy(fontFeatureSettings = "tnum"), content = content)
    }
}
