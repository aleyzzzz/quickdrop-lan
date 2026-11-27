package com.quickdrop.lan.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

val BgBase = Color(0xFF09090B)
val SurfaceCard = Color(0xFF121216)
val SurfaceElevated = Color(0xFF1A1A22)
val SurfaceNav = Color(0xFF0E0E12)
val BorderSubtle = Color.White.copy(alpha = 0.08f)
val BorderStrong = Color.White.copy(alpha = 0.14f)

val AccentCyan = Color(0xFF06B6D4)
val AccentCyanLight = Color(0xFF22D3EE)
val AccentEmerald = Color(0xFF10B981)
val StatusAmber = Color(0xFFF59E0B)
val StatusError = Color(0xFFEF4444)

val TextPrimary = Color(0xFFFAFAFA)
val TextSecondary = Color(0xFFA1A1AA)
val TextTertiary = Color(0xFF71717A)

val BadgeViolet = Color(0xFFA855F7)
val BadgeRose = Color(0xFFF43F5E)

val MonoTextStyle = TextStyle(
    fontFamily = FontFamily.Monospace,
    fontWeight = FontWeight.Medium,
    letterSpacing = 0.sp,
)

private val QuickDropDarkColorScheme = darkColorScheme(
    primary = AccentCyan,
    onPrimary = Color(0xFF041318),
    primaryContainer = Color(0xFF0C2A33),
    onPrimaryContainer = AccentCyanLight,
    secondary = AccentEmerald,
    onSecondary = Color(0xFF041A12),
    secondaryContainer = Color(0xFF0A2A20),
    onSecondaryContainer = AccentEmerald,
    background = BgBase,
    onBackground = TextPrimary,
    surface = SurfaceCard,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceElevated,
    onSurfaceVariant = TextSecondary,
    surfaceContainerLowest = BgBase,
    surfaceContainerLow = SurfaceNav,
    surfaceContainer = SurfaceCard,
    surfaceContainerHigh = SurfaceElevated,
    surfaceContainerHighest = Color(0xFF22222C),
    outline = Color(0xFF27272F),
    outlineVariant = Color(0xFF1E1E26),
    error = StatusError,
    onError = Color(0xFF2B0808),
)

private val QuickDropTypography = Typography(
    titleLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 20.sp,
        lineHeight = 26.sp,
        letterSpacing = (-0.3).sp,
    ),
    titleMedium = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 22.sp,
        letterSpacing = (-0.2).sp,
    ),
    titleSmall = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = (-0.1).sp,
    ),
    bodyLarge = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 15.sp,
        lineHeight = 22.sp,
    ),
    bodyMedium = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    bodySmall = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        lineHeight = 18.sp,
        letterSpacing = 0.1.sp,
    ),
    labelMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.2.sp,
    ),
    labelSmall = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 14.sp,
        letterSpacing = 0.4.sp,
    ),
)

private val QuickDropShapes = Shapes(
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(20.dp),
)

@Composable
fun QuickDropTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = QuickDropDarkColorScheme,
        typography = QuickDropTypography,
        shapes = QuickDropShapes,
        content = content,
    )
}
