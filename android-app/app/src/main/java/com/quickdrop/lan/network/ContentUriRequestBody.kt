package com.quickdrop.lan.network

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.IOException

data class UriMeta(
    val filename: String,
    val sizeBytes: Long,
    val mimeType: String,
)

fun resolveUriMeta(contentResolver: ContentResolver, uri: Uri): UriMeta {
    var displayName: String? = null
    var size = -1L

    contentResolver.query(
        uri,
        arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
        null,
        null,
        null,
    )?.use { cursor ->
        if (cursor.moveToFirst()) {
            val nameIdx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            val sizeIdx = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (nameIdx >= 0) displayName = cursor.getString(nameIdx)
            if (sizeIdx >= 0 && !cursor.isNull(sizeIdx)) size = cursor.getLong(sizeIdx)
        }
    }

    val mime = contentResolver.getType(uri) ?: "application/octet-stream"
    val fallbackName = run {
        val ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(mime)
        val suffix = if (!ext.isNullOrBlank()) ".$ext" else ".bin"
        "archivo_${System.currentTimeMillis()}$suffix"
    }

    return UriMeta(
        filename = displayName?.takeIf { it.isNotBlank() } ?: uri.lastPathSegment ?: fallbackName,
        sizeBytes = size,
        mimeType = mime,
    )
}

/**
 * Streaming OkHttp RequestBody that pipes bytes directly from an Android ContentResolver URI
 * into the network socket in 64 KB chunks so files up to 2 GB use constant (~64 KB) RAM.
 */
class ContentUriRequestBody(
    private val contentResolver: ContentResolver,
    private val uri: Uri,
    private val meta: UriMeta,
    private val onProgress: (bytesWritten: Long, totalBytes: Long, speedBytesPerSec: Long) -> Unit,
) : RequestBody() {

    override fun contentType(): MediaType? = meta.mimeType.toMediaTypeOrNull()

    override fun contentLength(): Long = meta.sizeBytes

    override fun isOneShot(): Boolean = true

    @Throws(IOException::class)
    override fun writeTo(sink: BufferedSink) {
        val inputStream = contentResolver.openInputStream(uri)
            ?: throw IOException("No se pudo abrir el archivo seleccionado.")

        inputStream.use { stream ->
            val buffer = ByteArray(CHUNK_SIZE)
            var totalWritten = 0L
            val startedAtNs = System.nanoTime()
            var lastEmitNs = 0L

            while (true) {
                val read = stream.read(buffer)
                if (read == -1) break
                sink.write(buffer, 0, read)
                totalWritten += read

                val nowNs = System.nanoTime()
                if (nowNs - lastEmitNs >= PROGRESS_INTERVAL_NS) {
                    val elapsedSec = ((nowNs - startedAtNs) / 1_000_000_000.0).coerceAtLeast(0.05)
                    val speed = (totalWritten / elapsedSec).toLong()
                    onProgress(totalWritten, meta.sizeBytes, speed)
                    lastEmitNs = nowNs
                }
            }
            sink.flush()
            val totalElapsed = ((System.nanoTime() - startedAtNs) / 1_000_000_000.0).coerceAtLeast(0.05)
            onProgress(totalWritten, meta.sizeBytes, (totalWritten / totalElapsed).toLong())
        }
    }

    companion object {
        private const val CHUNK_SIZE = 64 * 1024 // 64 KiB streaming buffer
        private const val PROGRESS_INTERVAL_NS = 100_000_000L // 100 ms UI throttle
    }
}
