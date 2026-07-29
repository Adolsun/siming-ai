package com.siming.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val SimingCinnabar = Color(0xFF963A36)
val SimingInk = Color(0xFF20201F)
val SimingPaper = Color(0xFFF4F4F1)
val SimingPaperWarm = Color(0xFFFFFDF8)
val SimingBlue = Color(0xFF315F75)
val SimingGreen = Color(0xFF39735D)

private val SimingLightColors = lightColorScheme(
    primary = SimingCinnabar,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFF5E9E6),
    onPrimaryContainer = Color(0xFF5A211F),
    secondary = SimingBlue,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFEDF5F8),
    onSecondaryContainer = Color(0xFF244E62),
    tertiary = SimingGreen,
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFEDF6F2),
    onTertiaryContainer = Color(0xFF2D5F4C),
    background = SimingPaper,
    onBackground = SimingInk,
    surface = Color.White,
    onSurface = SimingInk,
    surfaceVariant = Color(0xFFF6F2EA),
    onSurfaceVariant = Color(0xFF62615E),
    outline = Color(0xFFD8D6D0),
    outlineVariant = Color(0xFFE7E6E1),
    error = Color(0xFFB33A36),
)

@Composable
fun SimingTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = SimingLightColors,
        typography = Typography(),
        content = content,
    )
}
