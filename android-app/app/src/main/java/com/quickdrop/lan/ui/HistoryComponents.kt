package com.quickdrop.lan.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.quickdrop.lan.data.TransferItem
import com.quickdrop.lan.data.formatBytes
import com.quickdrop.lan.ui.theme.AccentCyan
import com.quickdrop.lan.ui.theme.AccentCyanLight
import com.quickdrop.lan.ui.theme.AccentEmerald
import com.quickdrop.lan.ui.theme.BadgeRose
import com.quickdrop.lan.ui.theme.BadgeViolet
import com.quickdrop.lan.ui.theme.BgBase
import com.quickdrop.lan.ui.theme.BorderStrong
import com.quickdrop.lan.ui.theme.BorderSubtle
import com.quickdrop.lan.ui.theme.MonoTextStyle
import com.quickdrop.lan.ui.theme.StatusAmber
import com.quickdrop.lan.ui.theme.SurfaceCard
import com.quickdrop.lan.ui.theme.SurfaceElevated
import com.quickdrop.lan.ui.theme.TextPrimary
import com.quickdrop.lan.ui.theme.TextSecondary
import com.quickdrop.lan.ui.theme.TextTertiary
import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

enum class HistoryFilter(val label: String) {
    ALL("Todos"),
    FROM_PC("Desde PC"),
    SENT("Enviados"),
    LINKS("Enlaces"),
    FILES("Archivos"),
}

private val TIME_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm", Locale.getDefault())

fun isImageOrGifItem(item: TransferItem): Boolean {
    if (item.kind != "file") return false
    val mime = item.mimeType.lowercase(Locale.US)
    if (mime.startsWith("image/")) return true
    val ext = extractExtension(item.filename)
    return ext in setOf("PNG", "JPG", "JPEG", "GIF", "WEBP", "BMP", "AVIF")
}

fun extractExtension(filename: String?): String {
    if (filename.isNullOrBlank()) return "FILE"
    val dot = filename.lastIndexOf('.')
    if (dot < 0 || dot == filename.lastIndex) return "FILE"
    return filename.substring(dot + 1).uppercase(Locale.US).take(5)
}

fun resolveItemImageUrl(baseUrl: String?, item: TransferItem): String? {
    if (baseUrl.isNullOrBlank() || !item.fileExists) return null
    val rel = item.downloadUrl ?: "/api/files/${item.id}"
    return "$baseUrl$rel?inline=1"
}

fun parseItemEpochMillis(iso: String): Long =
    runCatching { OffsetDateTime.parse(iso).toInstant().toEpochMilli() }.getOrDefault(0L)

fun chronologicalSectionLabel(iso: String): String {
    val parsedDate = runCatching {
        OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()).toLocalDate()
    }.getOrNull() ?: return "Anteriores"

    val today = LocalDate.now()
    return when {
        !parsedDate.isBefore(today) -> "Hoy"
        !parsedDate.isBefore(today.minusDays(1)) -> "Ayer"
        else -> "Anteriores"
    }
}

fun formatShortTime(iso: String): String =
    runCatching {
        OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()).format(TIME_FORMATTER)
    }.getOrDefault("")

private fun extractDomain(url: String): String =
    runCatching { URI(url.trim()).host?.removePrefix("www.") }.getOrNull().orEmpty().ifBlank { "Enlace" }

private fun badgeColorForExtension(ext: String): Color = when (ext) {
    "MP3", "WAV", "OGG", "FLAC", "M4A", "AAC", "OPUS" -> AccentEmerald
    "MP4", "MKV", "MOV", "WEBM", "AVI" -> BadgeViolet
    "PDF" -> BadgeRose
    "ZIP", "RAR", "7Z", "TAR", "GZ" -> StatusAmber
    "APK" -> AccentCyan
    "PNG", "JPG", "JPEG", "GIF", "WEBP" -> AccentCyanLight
    else -> TextSecondary
}

@Composable
fun HistoryItemCard(
    item: TransferItem,
    baseUrl: String?,
    isDownloading: Boolean,
    isDownloaded: Boolean,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
    onDownloadFile: (TransferItem) -> Unit,
    onPreviewImage: (TransferItem, String) -> Unit,
) {
    val isFromPc = item.direction == "to_phone"
    val timeText = formatShortTime(item.createdAt)

    Surface(
        color = SurfaceCard,
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, BorderSubtle),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // Subtle header metadata row
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Surface(
                    color = if (isFromPc) AccentEmerald.copy(alpha = 0.12f) else AccentCyan.copy(alpha = 0.12f),
                    shape = RoundedCornerShape(999.dp),
                ) {
                    Text(
                        text = if (isFromPc) "↓ Desde PC" else "↑ Enviado",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (isFromPc) AccentEmerald else AccentCyanLight,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = item.sender,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextTertiary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (timeText.isNotBlank()) {
                        Text(
                            text = "·",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextTertiary,
                        )
                        Text(
                            text = timeText,
                            style = MonoTextStyle.copy(fontSize = 11.sp),
                            color = TextTertiary,
                        )
                    }
                }
            }

            // Content body by type
            when {
                isImageOrGifItem(item) -> {
                    ImageFileContent(
                        item = item,
                        imageUrl = resolveItemImageUrl(baseUrl, item),
                        isDownloading = isDownloading,
                        isDownloaded = isDownloaded,
                        onDownloadFile = { onDownloadFile(item) },
                        onPreviewImage = { url -> onPreviewImage(item, url) },
                    )
                }

                item.kind == "link" || item.kind == "text" -> {
                    LinkOrTextContent(
                        item = item,
                        onCopyText = onCopyText,
                        onOpenLink = onOpenLink,
                    )
                }

                else -> {
                    GenericFileContent(
                        item = item,
                        isDownloading = isDownloading,
                        isDownloaded = isDownloaded,
                        onDownloadFile = { onDownloadFile(item) },
                    )
                }
            }
        }
    }
}

@Composable
private fun ImageFileContent(
    item: TransferItem,
    imageUrl: String?,
    isDownloading: Boolean,
    isDownloaded: Boolean,
    onDownloadFile: () -> Unit,
    onPreviewImage: (String) -> Unit,
) {
    val context = LocalContext.current

    if (imageUrl != null) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(180.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(BgBase)
                .clickable { onPreviewImage(imageUrl) },
        ) {
            AsyncImage(
                model = ImageRequest.Builder(context)
                    .data(imageUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = item.filename ?: "Imagen",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
            Surface(
                color = BgBase.copy(alpha = 0.72f),
                shape = RoundedCornerShape(8.dp),
                border = BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(8.dp),
            ) {
                Text(
                    text = "Ver",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextPrimary,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
        }
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        if (imageUrl == null) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(AccentCyan.copy(alpha = 0.12f)),
            ) {
                Icon(Icons.Rounded.Image, contentDescription = null, tint = AccentCyanLight, modifier = Modifier.size(20.dp))
            }
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = item.filename ?: "Imagen",
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatBytes(item.sizeBytes),
                style = MonoTextStyle.copy(fontSize = 12.sp),
                color = TextTertiary,
            )
        }
        if (item.fileExists) {
            DownloadActionButton(
                isDownloading = isDownloading,
                isDownloaded = isDownloaded,
                onClick = onDownloadFile,
            )
        }
    }
}

@Composable
private fun LinkOrTextContent(
    item: TransferItem,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
) {
    val isLink = item.kind == "link"
    val rawText = item.content.orEmpty()

    Row(
        verticalAlignment = Alignment.Top,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .size(36.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(if (isLink) AccentCyan.copy(alpha = 0.12f) else SurfaceElevated),
        ) {
            Icon(
                imageVector = if (isLink) Icons.Rounded.Link else Icons.Rounded.Description,
                contentDescription = null,
                tint = if (isLink) AccentCyanLight else TextSecondary,
                modifier = Modifier.size(18.dp),
            )
        }

        Column(
            verticalArrangement = Arrangement.spacedBy(2.dp),
            modifier = Modifier.weight(1f),
        ) {
            if (isLink) {
                Text(
                    text = extractDomain(rawText),
                    style = MaterialTheme.typography.labelMedium,
                    color = TextSecondary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = rawText,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isLink) AccentCyanLight else TextPrimary,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }

    if (rawText.isNotBlank()) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            OutlinedButton(
                onClick = { onCopyText(rawText) },
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, BorderSubtle),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                modifier = Modifier.height(34.dp),
            ) {
                Icon(Icons.Rounded.ContentCopy, contentDescription = null, modifier = Modifier.size(15.dp), tint = TextSecondary)
                Spacer(modifier = Modifier.width(6.dp))
                Text("Copiar", style = MaterialTheme.typography.labelMedium, color = TextPrimary)
            }

            if (isLink) {
                FilledTonalButton(
                    onClick = { onOpenLink(rawText) },
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.filledTonalButtonColors(
                        containerColor = AccentCyan.copy(alpha = 0.14f),
                        contentColor = AccentCyanLight,
                    ),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    modifier = Modifier.height(34.dp),
                ) {
                    Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("Abrir", style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

@Composable
private fun GenericFileContent(
    item: TransferItem,
    isDownloading: Boolean,
    isDownloaded: Boolean,
    onDownloadFile: () -> Unit,
) {
    val ext = extractExtension(item.filename)
    val badgeColor = badgeColorForExtension(ext)

    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Surface(
            color = badgeColor.copy(alpha = 0.14f),
            shape = RoundedCornerShape(12.dp),
            border = BorderStroke(1.dp, badgeColor.copy(alpha = 0.28f)),
            modifier = Modifier.size(width = 48.dp, height = 42.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Text(
                    text = ext,
                    style = MonoTextStyle.copy(fontSize = 11.sp, fontWeight = FontWeight.Bold),
                    color = badgeColor,
                    maxLines = 1,
                )
            }
        }

        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = item.filename ?: "Archivo",
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = formatBytes(item.sizeBytes),
                style = MonoTextStyle.copy(fontSize = 12.sp),
                color = TextTertiary,
            )
        }

        if (item.fileExists) {
            DownloadActionButton(
                isDownloading = isDownloading,
                isDownloaded = isDownloaded,
                onClick = onDownloadFile,
            )
        }
    }
}

@Composable
private fun DownloadActionButton(
    isDownloading: Boolean,
    isDownloaded: Boolean,
    onClick: () -> Unit,
) {
    when {
        isDownloading -> {
            Surface(
                color = SurfaceElevated,
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.height(34.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 12.dp),
                ) {
                    CircularProgressIndicator(
                        strokeWidth = 2.dp,
                        color = AccentCyan,
                        modifier = Modifier.size(14.dp),
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("Bajando", style = MaterialTheme.typography.labelMedium, color = TextSecondary)
                }
            }
        }

        isDownloaded -> {
            OutlinedButton(
                onClick = onClick,
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, AccentEmerald.copy(alpha = 0.35f)),
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                modifier = Modifier.height(34.dp),
            ) {
                Icon(Icons.Rounded.CheckCircle, contentDescription = null, tint = AccentEmerald, modifier = Modifier.size(15.dp))
                Spacer(modifier = Modifier.width(5.dp))
                Text("Guardado", style = MaterialTheme.typography.labelMedium, color = AccentEmerald)
            }
        }

        else -> {
            FilledTonalButton(
                onClick = onClick,
                shape = RoundedCornerShape(10.dp),
                colors = ButtonDefaults.filledTonalButtonColors(
                    containerColor = AccentEmerald.copy(alpha = 0.14f),
                    contentColor = AccentEmerald,
                ),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                modifier = Modifier.height(34.dp),
            ) {
                Icon(Icons.Rounded.Download, contentDescription = null, modifier = Modifier.size(15.dp))
                Spacer(modifier = Modifier.width(5.dp))
                Text("Descargar", style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
fun ImageViewerDialog(
    item: TransferItem,
    imageUrl: String,
    isDownloading: Boolean,
    isDownloaded: Boolean,
    onDismiss: () -> Unit,
    onDownload: () -> Unit,
) {
    val context = LocalContext.current

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(BgBase.copy(alpha = 0.94f))
                .clickable(onClick = onDismiss),
        ) {
            Surface(
                color = SurfaceCard,
                shape = RoundedCornerShape(20.dp),
                border = BorderStroke(1.dp, BorderStrong),
                modifier = Modifier
                    .align(Alignment.Center)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 32.dp)
                    .clickable(enabled = false, onClick = {}),
            ) {
                Column(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = 16.dp, end = 8.dp, top = 10.dp, bottom = 10.dp),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = item.filename ?: "Imagen",
                                style = MaterialTheme.typography.titleSmall,
                                color = TextPrimary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = "${formatBytes(item.sizeBytes)} · ${item.sender}",
                                style = MonoTextStyle.copy(fontSize = 11.sp),
                                color = TextTertiary,
                            )
                        }
                        IconButton(onClick = onDismiss) {
                            Icon(Icons.Rounded.Close, contentDescription = "Cerrar", tint = TextSecondary)
                        }
                    }

                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(380.dp)
                            .background(BgBase),
                    ) {
                        AsyncImage(
                            model = ImageRequest.Builder(context)
                                .data(imageUrl)
                                .crossfade(true)
                                .build(),
                            contentDescription = item.filename,
                            contentScale = ContentScale.Fit,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }

                    Row(
                        horizontalArrangement = Arrangement.End,
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp),
                    ) {
                        Button(
                            onClick = onDownload,
                            enabled = !isDownloading,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = if (isDownloaded) AccentEmerald else AccentCyan,
                                contentColor = Color(0xFF041318),
                            ),
                        ) {
                            Icon(
                                imageVector = if (isDownloaded) Icons.Rounded.CheckCircle else Icons.Rounded.Download,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = when {
                                    isDownloading -> "Descargando…"
                                    isDownloaded -> "Abrir / Guardar de nuevo"
                                    else -> "Descargar en teléfono"
                                },
                                style = MaterialTheme.typography.labelLarge,
                            )
                        }
                    }
                }
            }
        }
    }
}
