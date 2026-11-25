package com.quickdrop.lan.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val BgObsidian = Color(0xFF0B0F17)
val SurfaceCard = Color(0xFF131A26)
val SurfaceElevated = Color(0xFF1B2435)
val AccentSky = Color(0xFF38BDF8)
val AccentMint = Color(0xFF2DD4BF)
val TextPrimary = Color(0xFFE2E8F0)
val TextMuted = Color(0xFF94A3B8)
val StatusAmber = Color(0xFFF59E0B)
val StatusError = Color(0xFFF87171)

private val QuickDropDarkColorScheme = darkColorScheme(
    primary = AccentSky,
    onPrimary = Color(0xFF06131C),
    primaryContainer = Color(0xFF0E2A3B),
    onPrimaryContainer = AccentSky,
    secondary = AccentMint,
    onSecondary = Color(0xFF041C19),
    secondaryContainer = Color(0xFF0C2E2B),
    onSecondaryContainer = AccentMint,
    background = BgObsidian,
    onBackground = TextPrimary,
    surface = SurfaceCard,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceElevated,
    onSurfaceVariant = TextMuted,
    outline = Color(0xFF2B374C),
    error = StatusError,
    onError = Color(0xFF2B0808),
)

@Composable
fun QuickDropTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = QuickDropDarkColorScheme,
        typography = Typography(),
        content = content,
    )
}
