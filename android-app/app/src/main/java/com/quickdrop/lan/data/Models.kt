package com.quickdrop.lan.data

import android.net.Uri
import java.util.Locale

data class ServerEndpoint(
    val name: String,
    val host: String,
    val port: Int = 8765,
    val isManual: Boolean = false,
) {
    val baseUrl: String
        get() = "http://$host:$port"
}

data class ServerInfo(
    val name: String,
    val hostname: String,
    val ip: String,
    val port: Int,
    val downloadDir: String,
    val maxFileSizeBytes: Long,
)

data class TransferItem(
    val id: String,
    val direction: String, // "to_pc" | "to_phone"
    val kind: String, // "link" | "text" | "file"
    val content: String?,
    val filename: String?,
    val mimeType: String,
    val sizeBytes: Long,
    val sender: String,
    val createdAt: String,
    val downloadUrl: String?,
    val fileExists: Boolean,
)

data class TransferProgress(
    val label: String,
    val bytesDone: Long,
    val totalBytes: Long,
    val isDownload: Boolean,
    val speedBytesPerSec: Long = 0L,
) {
    val fraction: Float
        get() = if (totalBytes > 0L) (bytesDone.toFloat() / totalBytes.toFloat()).coerceIn(0f, 1f) else -1f
}

sealed interface ConnectionState {
    data object Searching : ConnectionState
    data class Connected(
        val endpoint: ServerEndpoint,
        val info: ServerInfo,
    ) : ConnectionState

    data class Disconnected(val message: String) : ConnectionState
}

data class PendingShare(
    val text: String? = null,
    val uris: List<Uri> = emptyList(),
) {
    val isEmpty: Boolean
        get() = text.isNullOrBlank() && uris.isEmpty()
}

fun formatBytes(bytes: Long): String {
    if (bytes <= 0L) return "0 B"
    val units = arrayOf("B", "KB", "MB", "GB")
    var value = bytes.toDouble()
    var index = 0
    while (value >= 1024.0 && index < units.lastIndex) {
        value /= 1024.0
        index++
    }
    return if (index == 0) {
        "${value.toLong()} B"
    } else {
        String.format(Locale.US, "%.1f %s", value, units[index])
    }
}
