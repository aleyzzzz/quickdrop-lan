package com.quickdrop.lan.network

import android.content.ContentResolver
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import com.quickdrop.lan.data.ServerEndpoint
import com.quickdrop.lan.data.ServerInfo
import com.quickdrop.lan.data.TransferItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class QuickDropClient {

    private val apiClient = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    // Zero read/write/call timeouts for huge 2 GB transfers over Wi-Fi
    private val transferClient = apiClient.newBuilder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .writeTimeout(0, TimeUnit.MILLISECONDS)
        .callTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private val sseClient = apiClient.newBuilder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val activeTransferCall = AtomicReference<Call?>(null)

    fun cancelActiveTransfer() {
        activeTransferCall.getAndSet(null)?.cancel()
    }

    suspend fun fetchInfo(endpoint: ServerEndpoint): ServerInfo = withContext(Dispatchers.IO) {
        val req = Request.Builder()
            .url("${endpoint.baseUrl}/api/info")
            .get()
            .build()
        apiClient.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IOException("El servidor respondió HTTP ${resp.code}")
            }
            val json = JSONObject(resp.body?.string() ?: "{}")
            ServerInfo(
                name = json.optString("name", endpoint.name),
                hostname = json.optString("hostname", endpoint.name),
                ip = json.optString("ip", endpoint.host),
                port = json.optInt("port", endpoint.port),
                downloadDir = json.optString("download_dir", ""),
                maxFileSizeBytes = json.optLong("max_file_size_bytes", 2L * 1024 * 1024 * 1024),
            )
        }
    }

    suspend fun sendText(
        endpoint: ServerEndpoint,
        content: String,
        sender: String = Build.MODEL ?: "Android",
    ): TransferItem = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("content", content)
            put("sender", sender)
        }
        val req = Request.Builder()
            .url("${endpoint.baseUrl}/api/text")
            .post(payload.toString().toRequestBody(JSON_MEDIA_TYPE))
            .build()

        apiClient.newCall(req).execute().use { resp ->
            val bodyStr = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IOException("Error enviando texto (HTTP ${resp.code})")
            }
            parseTransferItem(JSONObject(bodyStr))
        }
    }

    suspend fun uploadUri(
        endpoint: ServerEndpoint,
        contentResolver: ContentResolver,
        uri: Uri,
        sender: String = Build.MODEL ?: "Android",
        onProgress: (filename: String, bytesDone: Long, totalBytes: Long, speedBps: Long) -> Unit,
    ): TransferItem = withContext(Dispatchers.IO) {
        val meta = resolveUriMeta(contentResolver, uri)
        val encodedName = URLEncoder.encode(meta.filename, "UTF-8").replace("+", "%20")

        val body = ContentUriRequestBody(
            contentResolver = contentResolver,
            uri = uri,
            meta = meta,
            onProgress = { done, total, speed ->
                onProgress(meta.filename, done, total, speed)
            },
        )

        val req = Request.Builder()
            .url("${endpoint.baseUrl}/api/upload/raw")
            .header("X-Filename", encodedName)
            .header("X-Mime-Type", meta.mimeType)
            .header("X-Sender", sender)
            .header("X-Direction", "to_pc")
            .post(body)
            .build()

        val call = transferClient.newCall(req)
        activeTransferCall.set(call)
        try {
            call.execute().use { resp ->
                val respStr = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    throw IOException("Error subiendo ${meta.filename} (HTTP ${resp.code})")
                }
                parseTransferItem(JSONObject(respStr))
            }
        } finally {
            activeTransferCall.compareAndSet(call, null)
        }
    }

    suspend fun fetchItems(
        endpoint: ServerEndpoint,
        direction: String? = null,
        limit: Int = 100,
    ): List<TransferItem> = withContext(Dispatchers.IO) {
        val query = buildString {
            append("?limit=$limit")
            if (!direction.isNullOrBlank()) append("&direction=$direction")
        }
        val req = Request.Builder()
            .url("${endpoint.baseUrl}/api/items$query")
            .get()
            .build()

        apiClient.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IOException("No se pudo obtener historial (HTTP ${resp.code})")
            }
            val root = JSONObject(resp.body?.string() ?: "{}")
            val arr = root.optJSONArray("items") ?: return@withContext emptyList()
            buildList(arr.length()) {
                for (i in 0 until arr.length()) {
                    add(parseTransferItem(arr.getJSONObject(i)))
                }
            }
        }
    }

    suspend fun downloadFileToDownloads(
        context: Context,
        endpoint: ServerEndpoint,
        item: TransferItem,
        onProgress: (bytesDone: Long, totalBytes: Long, speedBps: Long) -> Unit,
    ): Uri = withContext(Dispatchers.IO) {
        val relUrl = item.downloadUrl ?: "/api/files/${item.id}"
        val req = Request.Builder()
            .url("${endpoint.baseUrl}$relUrl")
            .get()
            .build()

        val call = transferClient.newCall(req)
        activeTransferCall.set(call)
        try {
            call.execute().use { resp ->
                if (!resp.isSuccessful) {
                    throw IOException("No se pudo descargar (HTTP ${resp.code})")
                }
                val body = resp.body ?: throw IOException("Respuesta vacía")
                val totalBytes = body.contentLength().takeIf { it > 0L } ?: item.sizeBytes
                val filename = item.filename?.takeIf { it.isNotBlank() } ?: "quickdrop_${item.id}"
                val mimeType = item.mimeType.ifBlank { "application/octet-stream" }

                val savedUri = streamResponseToDownloads(
                    context = context,
                    filename = filename,
                    mimeType = mimeType,
                    body = body,
                    totalBytes = totalBytes,
                    onProgress = onProgress,
                )

                // Best-effort ACK to PC server
                runCatching {
                    val ackReq = Request.Builder()
                        .url("${endpoint.baseUrl}/api/items/${item.id}/ack")
                        .post("{}".toRequestBody(JSON_MEDIA_TYPE))
                        .build()
                    apiClient.newCall(ackReq).execute().close()
                }
                savedUri
            }
        } finally {
            activeTransferCall.compareAndSet(call, null)
        }
    }

    private fun streamResponseToDownloads(
        context: Context,
        filename: String,
        mimeType: String,
        body: okhttp3.ResponseBody,
        totalBytes: Long,
        onProgress: (bytesDone: Long, totalBytes: Long, speedBps: Long) -> Unit,
    ): Uri {
        val startedAtNs = System.nanoTime()
        var lastEmitNs = 0L

        fun copyStream(input: java.io.InputStream, output: java.io.OutputStream) {
            val buffer = ByteArray(64 * 1024)
            var downloaded = 0L
            while (true) {
                val read = input.read(buffer)
                if (read == -1) break
                output.write(buffer, 0, read)
                downloaded += read
                val now = System.nanoTime()
                if (now - lastEmitNs >= 100_000_000L) {
                    val sec = ((now - startedAtNs) / 1_000_000_000.0).coerceAtLeast(0.05)
                    onProgress(downloaded, totalBytes, (downloaded / sec).toLong())
                    lastEmitNs = now
                }
            }
            output.flush()
            val totalSec = ((System.nanoTime() - startedAtNs) / 1_000_000_000.0).coerceAtLeast(0.05)
            onProgress(downloaded, totalBytes, (downloaded / totalSec).toLong())
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val resolver = context.contentResolver
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, filename)
                put(MediaStore.Downloads.MIME_TYPE, mimeType)
                put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/QuickDrop")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("No se pudo crear el archivo en Descargas/QuickDrop.")

            try {
                resolver.openOutputStream(uri)?.use { out ->
                    body.byteStream().use { input -> copyStream(input, out) }
                } ?: throw IOException("No se pudo abrir flujo de escritura.")

                val doneValues = ContentValues().apply {
                    put(MediaStore.Downloads.IS_PENDING, 0)
                }
                resolver.update(uri, doneValues, null, null)
                return uri
            } catch (exc: Exception) {
                resolver.delete(uri, null, null)
                throw exc
            }
        } else {
            @Suppress("DEPRECATION")
            val dir = File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                "QuickDrop",
            )
            if (!dir.exists()) dir.mkdirs()
            val outFile = File(dir, filename)
            outFile.outputStream().use { out ->
                body.byteStream().use { input -> copyStream(input, out) }
            }
            return FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                outFile,
            )
        }
    }

    fun connectEvents(
        endpoint: ServerEndpoint,
        onItemCreated: (TransferItem) -> Unit,
        onItemRemoved: (String) -> Unit,
        onConnected: () -> Unit,
        onDisconnected: (Throwable?) -> Unit,
    ): EventSource {
        val req = Request.Builder()
            .url("${endpoint.baseUrl}/api/events")
            .header("Accept", "text/event-stream")
            .build()

        val listener = object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                onConnected()
            }

            override fun onEvent(
                eventSource: EventSource,
                id: String?,
                type: String?,
                data: String,
            ) {
                when (type) {
                    "item_created" -> runCatching {
                        onItemCreated(parseTransferItem(JSONObject(data)))
                    }

                    "item_removed" -> runCatching {
                        val removedId = JSONObject(data).optString("id")
                        if (removedId.isNotBlank()) onItemRemoved(removedId)
                    }
                }
            }

            override fun onClosed(eventSource: EventSource) {
                onDisconnected(null)
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                onDisconnected(t)
            }
        }

        return EventSources.createFactory(sseClient).newEventSource(req, listener)
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        fun parseTransferItem(obj: JSONObject): TransferItem = TransferItem(
            id = obj.optString("id"),
            direction = obj.optString("direction", "to_pc"),
            kind = obj.optString("kind", "text"),
            content = obj.optString("content").takeIf { !obj.isNull("content") && it.isNotBlank() },
            filename = obj.optString("filename").takeIf { !obj.isNull("filename") && it.isNotBlank() },
            mimeType = obj.optString("mime_type", "application/octet-stream"),
            sizeBytes = obj.optLong("size_bytes", 0L),
            sender = obj.optString("sender", "PC"),
            createdAt = obj.optString("created_at", ""),
            downloadUrl = obj.optString("download_url").takeIf { !obj.isNull("download_url") && it.isNotBlank() },
            fileExists = obj.optBoolean("file_exists", false),
        )
    }
}
