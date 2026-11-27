package com.quickdrop.lan.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quickdrop.lan.data.TransferProgress
import com.quickdrop.lan.data.formatBytes
import com.quickdrop.lan.ui.theme.AccentCyan
import com.quickdrop.lan.ui.theme.AccentEmerald
import com.quickdrop.lan.ui.theme.BgBase
import com.quickdrop.lan.ui.theme.BorderStrong
import com.quickdrop.lan.ui.theme.BorderSubtle
import com.quickdrop.lan.ui.theme.MonoTextStyle
import com.quickdrop.lan.ui.theme.StatusAmber
import com.quickdrop.lan.ui.theme.StatusError
import com.quickdrop.lan.ui.theme.SurfaceCard
import com.quickdrop.lan.ui.theme.SurfaceElevated
import com.quickdrop.lan.ui.theme.TextPrimary
import com.quickdrop.lan.ui.theme.TextSecondary
import com.quickdrop.lan.ui.theme.TextTertiary

@Composable
fun ShareSheetOverlay(
    shareState: ShareSheetState?,
    activeTransfer: TransferProgress?,
    onConfigureIp: () -> Unit,
    onDismiss: () -> Unit,
) {
    AnimatedVisibility(
        visible = shareState != null,
        enter = fadeIn(),
        exit = fadeOut(),
    ) {
        val current = shareState ?: return@AnimatedVisibility
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .fillMaxSize()
                .background(BgBase.copy(alpha = 0.78f))
                .padding(horizontal = 24.dp),
        ) {
            Surface(
                color = SurfaceCard,
                shape = RoundedCornerShape(22.dp),
                border = BorderStroke(1.dp, BorderStrong),
                shadowElevation = 16.dp,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    val (accentColor, icon, heading) = when {
                        current.isCompleted -> Triple(
                            AccentEmerald,
                            Icons.Rounded.CheckCircle,
                            "Enviado a ${current.targetName ?: "tu PC"}",
                        )
                        current.errorMessage != null -> Triple(
                            StatusError,
                            Icons.Rounded.ErrorOutline,
                            "No se pudo enviar",
                        )
                        current.isWaitingForConnection -> Triple(
                            StatusAmber,
                            Icons.Rounded.Bolt,
                            "Buscando tu PC…",
                        )
                        else -> Triple(
                            AccentCyan,
                            Icons.Rounded.Bolt,
                            "Enviando a ${current.targetName ?: "tu PC"}",
                        )
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .size(40.dp)
                                .clip(RoundedCornerShape(12.dp))
                                .background(accentColor.copy(alpha = 0.14f)),
                        ) {
                            Icon(
                                imageVector = icon,
                                contentDescription = null,
                                tint = accentColor,
                                modifier = Modifier.size(22.dp),
                            )
                        }
                        Spacer(modifier = Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = heading,
                                style = MaterialTheme.typography.titleMedium,
                                color = TextPrimary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = current.summary,
                                style = MaterialTheme.typography.bodySmall,
                                color = TextSecondary,
                            )
                        }
                    }

                    if (!current.detail.isNullOrBlank()) {
                        Surface(
                            color = SurfaceElevated,
                            shape = RoundedCornerShape(12.dp),
                            border = BorderStroke(1.dp, BorderSubtle),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                text = current.detail,
                                style = MaterialTheme.typography.bodySmall,
                                color = TextSecondary,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.padding(12.dp),
                            )
                        }
                    }

                    if (current.isSending || current.isWaitingForConnection) {
                        val rawFraction = activeTransfer?.fraction ?: -1f
                        val animatedProgress by animateFloatAsState(
                            targetValue = if (rawFraction >= 0f) rawFraction else 0f,
                            label = "shareSheetProgress",
                        )
                        if (rawFraction >= 0f) {
                            LinearProgressIndicator(
                                progress = { animatedProgress },
                                color = AccentCyan,
                                trackColor = SurfaceElevated,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(6.dp)
                                    .clip(RoundedCornerShape(999.dp)),
                            )
                            val pct = (rawFraction * 100f).toInt().coerceIn(0, 100)
                            val speed = activeTransfer?.speedBytesPerSec?.takeIf { it > 0L }
                                ?.let { " · ${formatBytes(it)}/s" }
                                .orEmpty()
                            Row(
                                horizontalArrangement = Arrangement.SpaceBetween,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(
                                    text = activeTransfer?.label.orEmpty(),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = TextTertiary,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "$pct%$speed",
                                    style = MonoTextStyle.copy(fontSize = 12.sp),
                                    color = AccentCyan,
                                )
                            }
                        } else {
                            LinearProgressIndicator(
                                color = accentColor,
                                trackColor = SurfaceElevated,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(5.dp)
                                    .clip(RoundedCornerShape(999.dp)),
                            )
                        }
                    }

                    if (current.errorMessage != null) {
                        Text(
                            text = current.errorMessage,
                            style = MaterialTheme.typography.bodySmall,
                            color = StatusError,
                        )
                    }

                    if (!current.isCompleted) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            OutlinedButton(
                                onClick = onDismiss,
                                shape = RoundedCornerShape(12.dp),
                                border = BorderStroke(1.dp, BorderSubtle),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Cancelar", color = TextSecondary)
                            }
                            if (current.isWaitingForConnection || current.errorMessage != null) {
                                Button(
                                    onClick = onConfigureIp,
                                    shape = RoundedCornerShape(12.dp),
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = AccentCyan,
                                        contentColor = Color(0xFF041318),
                                    ),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text("Configurar IP")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
