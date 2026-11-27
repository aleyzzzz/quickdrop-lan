package com.quickdrop.lan.ui

import android.app.Application
import android.net.Uri
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.quickdrop.lan.data.ConnectionState
import com.quickdrop.lan.data.PendingShare
import com.quickdrop.lan.data.PreferencesStore
import com.quickdrop.lan.data.ServerEndpoint
import com.quickdrop.lan.data.TransferItem
import com.quickdrop.lan.data.TransferProgress
import com.quickdrop.lan.network.NsdDiscoveryManager
import com.quickdrop.lan.network.QuickDropClient
import com.quickdrop.lan.notifications.LocalNotificationHelper
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.sse.EventSource

data class ShareSheetState(
    val summary: String,
    val detail: String? = null,
    val targetName: String? = null,
    val isWaitingForConnection: Boolean = false,
    val isSending: Boolean = false,
    val isCompleted: Boolean = false,
    val errorMessage: String? = null,
)

data class QuickDropUiState(
    val connectionState: ConnectionState = ConnectionState.Searching,
    val discoveredServers: List<ServerEndpoint> = emptyList(),
    val manualHost: String = "",
    val manualPort: String = "8765",
    val useManualEndpoint: Boolean = false,
    val selectedTab: Int = 0, // 0 = Enviar, 1 = Historial
    val textInput: String = "",
    val isSendingText: Boolean = false,
    val sentItems: List<TransferItem> = emptyList(),
    val receivedItems: List<TransferItem> = emptyList(),
    val activeTransfer: TransferProgress? = null,
    val downloadingItemId: String? = null,
    val downloadedItemIds: Set<String> = emptySet(),
    val pendingShare: PendingShare? = null,
    val shareSheetState: ShareSheetState? = null,
    val snackbarMessage: String? = null,
    val unreadReceivedCount: Int = 0,
    val isRefreshing: Boolean = false,
)

class QuickDropViewModel(application: Application) : AndroidViewModel(application) {

    private val prefs = PreferencesStore(application)
    private val client = QuickDropClient()
    private val nsd = NsdDiscoveryManager(application)
    private val notifier = LocalNotificationHelper(application)

    private val _uiState = MutableStateFlow(
        QuickDropUiState(
            manualHost = prefs.manualHost,
            manualPort = prefs.manualPort.toString(),
            useManualEndpoint = prefs.useManualEndpoint,
        ),
    )
    val uiState: StateFlow<QuickDropUiState> = _uiState.asStateFlow()

    private val knownItemIds = HashSet<String>()
    private var sseSource: EventSource? = null
    private var sseReconnectJob: Job? = null
    private var connectJob: Job? = null
    private var shareAutoCloseJob: Job? = null

    init {
        observeDiscoveredServers()
        nsd.start()
        tryInitialConnection()
    }

    private fun observeDiscoveredServers() {
        viewModelScope.launch {
            nsd.servers.collect { servers ->
                _uiState.update { it.copy(discoveredServers = servers) }
                val state = _uiState.value
                if (!state.useManualEndpoint &&
                    state.connectionState !is ConnectionState.Connected &&
                    servers.isNotEmpty()
                ) {
                    connectToEndpoint(servers.first())
                }
            }
        }
    }

    private fun tryInitialConnection() {
        val state = _uiState.value
        if (state.useManualEndpoint && state.manualHost.isNotBlank()) {
            val port = state.manualPort.toIntOrNull() ?: 8765
            connectToEndpoint(
                ServerEndpoint(name = "PC (IP manual)", host = state.manualHost, port = port, isManual = true),
            )
            return
        }
        val last = prefs.getLastEndpoint()
        if (last != null) {
            connectToEndpoint(last, silentFallbackToSearching = true)
        }
    }

    fun selectTab(tabIndex: Int) {
        _uiState.update { state ->
            state.copy(
                selectedTab = tabIndex,
                unreadReceivedCount = if (tabIndex == 1) 0 else state.unreadReceivedCount,
            )
        }
    }

    fun updateTextInput(value: String) {
        _uiState.update { it.copy(textInput = value) }
    }

    fun consumeSnackbar() {
        _uiState.update { it.copy(snackbarMessage = null) }
    }

    fun dismissShareSheet() {
        shareAutoCloseJob?.cancel()
        _uiState.update { it.copy(shareSheetState = null, pendingShare = null) }
    }

    fun restartDiscovery() {
        disconnectSse()
        _uiState.update { it.copy(connectionState = ConnectionState.Searching, isRefreshing = true) }
        nsd.restart()
        viewModelScope.launch {
            delay(400)
            val state = _uiState.value
            if (state.useManualEndpoint && state.manualHost.isNotBlank()) {
                val port = state.manualPort.toIntOrNull() ?: 8765
                connectToEndpoint(ServerEndpoint("PC (IP manual)", state.manualHost, port, isManual = true))
            } else {
                val candidate = state.discoveredServers.firstOrNull() ?: prefs.getLastEndpoint()
                if (candidate != null) {
                    connectToEndpoint(candidate, silentFallbackToSearching = true)
                } else {
                    _uiState.update { it.copy(isRefreshing = false) }
                }
            }
        }
    }

    fun applyManualConnection(host: String, portStr: String) {
        val cleanHost = host.trim()
            .removePrefix("http://")
            .removePrefix("https://")
            .substringBefore("/")
            .substringBefore(":")
        val port = portStr.trim().toIntOrNull()?.coerceIn(1, 65535) ?: 8765
        if (cleanHost.isBlank()) {
            showSnackbar("Ingresa una dirección IP válida (ej. 192.168.1.50)")
            return
        }
        prefs.manualHost = cleanHost
        prefs.manualPort = port
        prefs.useManualEndpoint = true
        _uiState.update {
            it.copy(
                manualHost = cleanHost,
                manualPort = port.toString(),
                useManualEndpoint = true,
            )
        }
        connectToEndpoint(ServerEndpoint(name = "PC ($cleanHost)", host = cleanHost, port = port, isManual = true))
    }

    fun selectDiscoveredServer(endpoint: ServerEndpoint) {
        prefs.useManualEndpoint = false
        _uiState.update { it.copy(useManualEndpoint = false) }
        connectToEndpoint(endpoint)
    }

    fun switchToAutoDiscovery() {
        prefs.useManualEndpoint = false
        _uiState.update { it.copy(useManualEndpoint = false) }
        restartDiscovery()
    }

    fun connectToEndpoint(
        endpoint: ServerEndpoint,
        silentFallbackToSearching: Boolean = false,
    ) {
        connectJob?.cancel()
        connectJob = viewModelScope.launch {
            _uiState.update { it.copy(isRefreshing = true) }
            runCatching {
                val info = client.fetchInfo(endpoint)
                val items = client.fetchItems(endpoint, limit = 150)
                info to items
            }.onSuccess { (info, items) ->
                val resolvedEndpoint = endpoint.copy(name = info.hostname.ifBlank { endpoint.name })
                prefs.saveLastEndpoint(resolvedEndpoint)
                knownItemIds.clear()
                items.forEach { knownItemIds.add(it.id) }

                _uiState.update { state ->
                    state.copy(
                        connectionState = ConnectionState.Connected(resolvedEndpoint, info),
                        sentItems = items.filter { it.direction == "to_pc" },
                        receivedItems = items.filter { it.direction == "to_phone" },
                        isRefreshing = false,
                    )
                }
                startSse(resolvedEndpoint)
                flushPendingShareIfAny()
            }.onFailure { err ->
                disconnectSse()
                _uiState.update { state ->
                    state.copy(
                        connectionState = if (silentFallbackToSearching) {
                            ConnectionState.Searching
                        } else {
                            ConnectionState.Disconnected(err.message ?: "No se pudo conectar a ${endpoint.baseUrl}")
                        },
                        isRefreshing = false,
                    )
                }
            }
        }
    }

    private fun startSse(endpoint: ServerEndpoint) {
        disconnectSse()
        sseSource = client.connectEvents(
            endpoint = endpoint,
            onItemCreated = { item ->
                val isBrandNew = knownItemIds.add(item.id)
                _uiState.update { state ->
                    if (item.direction == "to_phone") {
                        val updated = listOf(item) + state.receivedItems.filterNot { it.id == item.id }
                        val incrementUnread = if (isBrandNew && state.selectedTab != 1) 1 else 0
                        state.copy(
                            receivedItems = updated,
                            unreadReceivedCount = state.unreadReceivedCount + incrementUnread,
                        )
                    } else {
                        val updated = listOf(item) + state.sentItems.filterNot { it.id == item.id }
                        state.copy(sentItems = updated)
                    }
                }
                if (isBrandNew && item.direction == "to_phone") {
                    notifier.notifyIncomingFromPc(item)
                }
            },
            onItemRemoved = { id ->
                _uiState.update { state ->
                    state.copy(
                        sentItems = state.sentItems.filterNot { it.id == id },
                        receivedItems = state.receivedItems.filterNot { it.id == id },
                    )
                }
            },
            onConnected = {
                sseReconnectJob?.cancel()
            },
            onDisconnected = {
                scheduleSseReconnect(endpoint)
            },
        )
    }

    private fun scheduleSseReconnect(endpoint: ServerEndpoint) {
        sseReconnectJob?.cancel()
        sseReconnectJob = viewModelScope.launch {
            delay(3500)
            val current = _uiState.value.connectionState
            if (current is ConnectionState.Connected && current.endpoint.baseUrl == endpoint.baseUrl) {
                runCatching { client.fetchItems(endpoint, limit = 150) }
                    .onSuccess { items ->
                        items.forEach { item ->
                            if (knownItemIds.add(item.id) && item.direction == "to_phone") {
                                notifier.notifyIncomingFromPc(item)
                            }
                        }
                        _uiState.update { state ->
                            state.copy(
                                sentItems = items.filter { it.direction == "to_pc" },
                                receivedItems = items.filter { it.direction == "to_phone" },
                            )
                        }
                        startSse(endpoint)
                    }
                    .onFailure {
                        _uiState.update {
                            it.copy(connectionState = ConnectionState.Disconnected("Se perdió la conexión con la PC"))
                        }
                    }
            }
        }
    }

    private fun disconnectSse() {
        sseReconnectJob?.cancel()
        sseReconnectJob = null
        sseSource?.cancel()
        sseSource = null
    }

    fun refreshItems() {
        val conn = _uiState.value.connectionState as? ConnectionState.Connected ?: run {
            restartDiscovery()
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isRefreshing = true) }
            runCatching { client.fetchItems(conn.endpoint, limit = 150) }
                .onSuccess { items ->
                    items.forEach { knownItemIds.add(it.id) }
                    _uiState.update { state ->
                        state.copy(
                            sentItems = items.filter { it.direction == "to_pc" },
                            receivedItems = items.filter { it.direction == "to_phone" },
                            isRefreshing = false,
                        )
                    }
                }
                .onFailure {
                    _uiState.update { it.copy(isRefreshing = false) }
                    showSnackbar("No se pudo actualizar el historial")
                }
        }
    }

    fun sendCurrentText() {
        val text = _uiState.value.textInput.trim()
        if (text.isEmpty() || _uiState.value.isSendingText) return
        val conn = _uiState.value.connectionState as? ConnectionState.Connected
        if (conn == null) {
            showSnackbar("Conéctate primero a tu PC en la misma red Wi-Fi")
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isSendingText = true) }
            runCatching {
                client.sendText(conn.endpoint, text, sender = deviceDisplayName())
            }.onSuccess { item ->
                knownItemIds.add(item.id)
                _uiState.update { state ->
                    state.copy(
                        textInput = "",
                        isSendingText = false,
                        sentItems = listOf(item) + state.sentItems.filterNot { it.id == item.id },
                        snackbarMessage = if (item.kind == "link") "Enlace enviado a ${conn.endpoint.name}" else "Texto enviado a ${conn.endpoint.name}",
                    )
                }
            }.onFailure { err ->
                _uiState.update { it.copy(isSendingText = false) }
                showSnackbar(err.message ?: "Error al enviar texto")
            }
        }
    }

    fun sendFiles(uris: List<Uri>) {
        if (uris.isEmpty()) return
        val conn = _uiState.value.connectionState as? ConnectionState.Connected
        if (conn == null) {
            _uiState.update { it.copy(pendingShare = PendingShare(uris = uris)) }
            showSnackbar("Esperando conexión con la PC para enviar ${uris.size} archivo(s)...")
            return
        }
        viewModelScope.launch {
            uploadUrisSequential(conn.endpoint, uris)
        }
    }

    fun handleIncomingShare(text: String?, uris: List<Uri>) {
        val payload = PendingShare(text = text?.trim()?.takeIf { it.isNotEmpty() }, uris = uris)
        if (payload.isEmpty) return

        shareAutoCloseJob?.cancel()
        val summary = buildShareSummary(payload)
        val detail = payload.text?.take(120)
        val conn = _uiState.value.connectionState as? ConnectionState.Connected
        if (conn == null) {
            _uiState.update {
                it.copy(
                    pendingShare = payload,
                    selectedTab = 0,
                    shareSheetState = ShareSheetState(
                        summary = summary,
                        detail = detail,
                        isWaitingForConnection = true,
                    ),
                )
            }
            return
        }
        dispatchSharePayload(conn.endpoint, payload, fromShareSheet = true)
    }

    fun clearPendingShare() {
        shareAutoCloseJob?.cancel()
        _uiState.update { it.copy(pendingShare = null, shareSheetState = null) }
    }

    private fun flushPendingShareIfAny() {
        val pending = _uiState.value.pendingShare ?: return
        val conn = _uiState.value.connectionState as? ConnectionState.Connected ?: return
        val hadShareSheet = _uiState.value.shareSheetState != null
        _uiState.update { it.copy(pendingShare = null) }
        dispatchSharePayload(conn.endpoint, pending, fromShareSheet = hadShareSheet)
    }

    private fun dispatchSharePayload(
        endpoint: ServerEndpoint,
        payload: PendingShare,
        fromShareSheet: Boolean,
    ) {
        val summary = buildShareSummary(payload)
        val detail = payload.text?.take(120)

        if (fromShareSheet) {
            _uiState.update {
                it.copy(
                    shareSheetState = ShareSheetState(
                        summary = summary,
                        detail = detail,
                        targetName = endpoint.name,
                        isSending = true,
                    ),
                )
            }
        }

        viewModelScope.launch {
            var sentCount = 0
            var lastError: String? = null

            if (!payload.text.isNullOrBlank()) {
                runCatching {
                    client.sendText(endpoint, payload.text, sender = deviceDisplayName())
                }.onSuccess { item ->
                    knownItemIds.add(item.id)
                    sentCount++
                    _uiState.update { state ->
                        state.copy(sentItems = listOf(item) + state.sentItems.filterNot { it.id == item.id })
                    }
                }.onFailure { err ->
                    val errMsg = err.message ?: "Error enviando enlace/texto compartido"
                    lastError = errMsg
                    if (!fromShareSheet) showSnackbar(errMsg)
                }
            }

            if (payload.uris.isNotEmpty()) {
                val (uploaded, errMsg) = uploadUrisSequential(endpoint, payload.uris, showToast = !fromShareSheet)
                sentCount += uploaded
                if (errMsg != null) lastError = errMsg
            } else if (sentCount > 0 && !fromShareSheet) {
                showSnackbar("Enviado a ${endpoint.name}")
            }

            if (fromShareSheet) {
                if (sentCount > 0 && lastError == null) {
                    _uiState.update {
                        it.copy(
                            shareSheetState = ShareSheetState(
                                summary = summary,
                                detail = detail,
                                targetName = endpoint.name,
                                isCompleted = true,
                            ),
                        )
                    }
                    shareAutoCloseJob?.cancel()
                    shareAutoCloseJob = viewModelScope.launch {
                        delay(1300)
                        _uiState.update { it.copy(shareSheetState = null) }
                    }
                } else {
                    _uiState.update {
                        it.copy(
                            shareSheetState = ShareSheetState(
                                summary = summary,
                                detail = detail,
                                targetName = endpoint.name,
                                errorMessage = lastError ?: "No se pudo completar el envío",
                            ),
                        )
                    }
                }
            }
        }
    }

    private suspend fun uploadUrisSequential(
        endpoint: ServerEndpoint,
        uris: List<Uri>,
        showToast: Boolean = true,
    ): Pair<Int, String?> {
        val resolver = getApplication<Application>().contentResolver
        var okCount = 0
        var lastError: String? = null

        for ((idx, uri) in uris.withIndex()) {
            val prefix = if (uris.size > 1) "[${idx + 1}/${uris.size}] " else ""
            runCatching {
                client.uploadUri(
                    endpoint = endpoint,
                    contentResolver = resolver,
                    uri = uri,
                    sender = deviceDisplayName(),
                ) { filename, done, total, speed ->
                    _uiState.update { state ->
                        state.copy(
                            activeTransfer = TransferProgress(
                                label = "$prefix$filename",
                                bytesDone = done,
                                totalBytes = total,
                                isDownload = false,
                                speedBytesPerSec = speed,
                            ),
                        )
                    }
                }
            }.onSuccess { item ->
                knownItemIds.add(item.id)
                okCount++
                _uiState.update { state ->
                    state.copy(sentItems = listOf(item) + state.sentItems.filterNot { it.id == item.id })
                }
            }.onFailure { err ->
                val errMsg = err.message ?: "Transferencia cancelada o fallida"
                lastError = errMsg
                if (showToast) showSnackbar(errMsg)
            }
        }
        _uiState.update { it.copy(activeTransfer = null) }
        if (okCount > 0 && showToast) {
            val msg = if (okCount == 1) "Archivo enviado a ${endpoint.name}" else "$okCount archivos enviados a ${endpoint.name}"
            showSnackbar(msg)
        }
        return okCount to lastError
    }

    fun downloadItem(item: TransferItem, onDownloaded: (Uri, String) -> Unit) {
        val conn = _uiState.value.connectionState as? ConnectionState.Connected ?: run {
            showSnackbar("Sin conexión con la PC")
            return
        }
        viewModelScope.launch {
            val filename = item.filename ?: "archivo"
            _uiState.update {
                it.copy(
                    downloadingItemId = item.id,
                    activeTransfer = TransferProgress(
                        label = filename,
                        bytesDone = 0L,
                        totalBytes = item.sizeBytes,
                        isDownload = true,
                    ),
                )
            }
            runCatching {
                client.downloadFileToDownloads(
                    context = getApplication(),
                    endpoint = conn.endpoint,
                    item = item,
                ) { done, total, speed ->
                    _uiState.update { state ->
                        state.copy(
                            activeTransfer = TransferProgress(
                                label = filename,
                                bytesDone = done,
                                totalBytes = total,
                                isDownload = true,
                                speedBytesPerSec = speed,
                            ),
                        )
                    }
                }
            }.onSuccess { uri ->
                _uiState.update {
                    it.copy(
                        activeTransfer = null,
                        downloadingItemId = null,
                        downloadedItemIds = it.downloadedItemIds + item.id,
                    )
                }
                showSnackbar("Guardado en Descargas/QuickDrop")
                onDownloaded(uri, item.mimeType)
            }.onFailure { err ->
                _uiState.update { it.copy(activeTransfer = null, downloadingItemId = null) }
                showSnackbar(err.message ?: "Error al descargar archivo")
            }
        }
    }

    fun cancelActiveTransfer() {
        client.cancelActiveTransfer()
        _uiState.update {
            it.copy(
                activeTransfer = null,
                downloadingItemId = null,
                snackbarMessage = "Transferencia cancelada",
            )
        }
    }

    fun showSnackbar(message: String) {
        _uiState.update { it.copy(snackbarMessage = message) }
    }

    private fun buildShareSummary(payload: PendingShare): String = buildString {
        val text = payload.text
        if (!text.isNullOrBlank()) {
            val isLink = text.startsWith("http://", ignoreCase = true) ||
                text.startsWith("https://", ignoreCase = true)
            append(if (isLink) "Enlace" else "Texto")
        }
        if (payload.uris.isNotEmpty()) {
            if (isNotEmpty()) append(" + ")
            append(
                if (payload.uris.size == 1) "1 archivo" else "${payload.uris.size} archivos",
            )
        }
    }.ifBlank { "Contenido compartido" }

    private fun deviceDisplayName(): String =
        listOfNotNull(Build.MANUFACTURER, Build.MODEL)
            .joinToString(" ")
            .trim()
            .ifBlank { "Android" }

    override fun onCleared() {
        super.onCleared()
        shareAutoCloseJob?.cancel()
        disconnectSse()
        client.cancelActiveTransfer()
        nsd.stop()
    }
}
