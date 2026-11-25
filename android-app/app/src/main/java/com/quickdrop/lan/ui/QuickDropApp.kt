package com.quickdrop.lan.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.AttachFile
import androidx.compose.material.icons.rounded.AudioFile
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Computer
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Inbox
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.quickdrop.lan.data.ConnectionState
import com.quickdrop.lan.data.ServerEndpoint
import com.quickdrop.lan.data.TransferItem
import com.quickdrop.lan.data.TransferProgress
import com.quickdrop.lan.data.formatBytes
import com.quickdrop.lan.ui.theme.AccentMint
import com.quickdrop.lan.ui.theme.AccentSky
import com.quickdrop.lan.ui.theme.StatusAmber
import com.quickdrop.lan.ui.theme.StatusError
import com.quickdrop.lan.ui.theme.SurfaceCard
import com.quickdrop.lan.ui.theme.SurfaceElevated
import com.quickdrop.lan.ui.theme.TextMuted

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QuickDropApp(viewModel: QuickDropViewModel) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbarHostState = remember { SnackbarHostState() }
    var showConnectionDialog by remember { mutableStateOf(false) }

    val anyFilesPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        if (uris.isNotEmpty()) viewModel.sendFiles(uris)
    }

    val mediaPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        if (uris.isNotEmpty()) viewModel.sendFiles(uris)
    }

    LaunchedEffect(state.snackbarMessage) {
        val msg = state.snackbarMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(msg)
        viewModel.consumeSnackbar()
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                    titleContentColor = MaterialTheme.colorScheme.onBackground,
                ),
                title = {
                    Column {
                        Text(
                            text = "QuickDrop LAN",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        ConnectionStatusSubtitle(
                            connectionState = state.connectionState,
                            onClick = { showConnectionDialog = true },
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.restartDiscovery() }) {
                        Icon(
                            imageVector = Icons.Rounded.Refresh,
                            contentDescription = "Buscar PC en la red",
                        )
                    }
                    IconButton(onClick = { showConnectionDialog = true }) {
                        Icon(
                            imageVector = Icons.Rounded.Settings,
                            contentDescription = "Configurar IP manual",
                        )
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar(containerColor = SurfaceCard) {
                NavigationBarItem(
                    selected = state.selectedTab == 0,
                    onClick = { viewModel.selectTab(0) },
                    icon = { Icon(Icons.Rounded.Upload, contentDescription = "Enviar") },
                    label = { Text("Enviar") },
                )
                NavigationBarItem(
                    selected = state.selectedTab == 1,
                    onClick = { viewModel.selectTab(1) },
                    icon = {
                        BadgedBox(
                            badge = {
                                if (state.unreadReceivedCount > 0) {
                                    Badge { Text(state.unreadReceivedCount.toString()) }
                                }
                            },
                        ) {
                            Icon(Icons.Rounded.Inbox, contentDescription = "Recibidos")
                        }
                    },
                    label = { Text("Recibidos") },
                )
            }
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp),
        ) {
            state.activeTransfer?.let { progress ->
                TransferProgressCard(
                    progress = progress,
                    onCancel = { viewModel.cancelActiveTransfer() },
                )
                Spacer(modifier = Modifier.height(12.dp))
            }

            state.pendingShare?.let { pending ->
                PendingShareBanner(
                    countDesc = buildString {
                        if (!pending.text.isNullOrBlank()) append("Texto/link")
                        if (pending.uris.isNotEmpty()) {
                            if (isNotEmpty()) append(" + ")
                            append("${pending.uris.size} archivo(s)")
                        }
                    },
                    onConfigureIp = { showConnectionDialog = true },
                    onDismiss = { viewModel.clearPendingShare() },
                )
                Spacer(modifier = Modifier.height(12.dp))
            }

            if (state.selectedTab == 0) {
                SendTabContent(
                    state = state,
                    onTextChange = viewModel::updateTextInput,
                    onPasteClick = {
                        val pasted = readClipboardText(context)
                        if (!pasted.isNullOrBlank()) {
                            viewModel.updateTextInput(pasted)
                        } else {
                            viewModel.showSnackbar("El portapapeles está vacío")
                        }
                    },
                    onSendText = viewModel::sendCurrentText,
                    onPickAnyFiles = { anyFilesPicker.launch(arrayOf("*/*")) },
                    onPickMedia = {
                        mediaPicker.launch(arrayOf("image/*", "video/*", "audio/*"))
                    },
                    onCopyText = { copyToClipboard(context, it); viewModel.showSnackbar("Copiado") },
                    onOpenLink = { openExternalUrl(context, it) },
                )
            } else {
                ReceivedTabContent(
                    items = state.receivedItems,
                    onRefresh = viewModel::refreshItems,
                    onCopyText = { copyToClipboard(context, it); viewModel.showSnackbar("Copiado") },
                    onOpenLink = { openExternalUrl(context, it) },
                    onDownloadFile = { item ->
                        viewModel.downloadItem(item) { uri, mime ->
                            openDownloadedFile(context, uri, mime)
                        }
                    },
                )
            }
        }
    }

    if (showConnectionDialog) {
        ConnectionDialog(
            discovered = state.discoveredServers,
            initialHost = state.manualHost,
            initialPort = state.manualPort,
            useManual = state.useManualEndpoint,
            onDismiss = { showConnectionDialog = false },
            onSelectDiscovered = { endpoint ->
                viewModel.selectDiscoveredServer(endpoint)
                showConnectionDialog = false
            },
            onConnectManual = { host, port ->
                viewModel.applyManualConnection(host, port)
                showConnectionDialog = false
            },
            onEnableAuto = {
                viewModel.switchToAutoDiscovery()
                showConnectionDialog = false
            },
        )
    }
}

@Composable
private fun ConnectionStatusSubtitle(
    connectionState: ConnectionState,
    onClick: () -> Unit,
) {
    val (dotColor, label) = when (connectionState) {
        is ConnectionState.Connected -> AccentMint to "${connectionState.info.hostname} · ${connectionState.endpoint.host}:${connectionState.endpoint.port}"
        is ConnectionState.Searching -> StatusAmber to "Buscando PC por mDNS… (toca para IP manual)"
        is ConnectionState.Disconnected -> StatusError to "${connectionState.message} (toca para configurar)"
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(dotColor),
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = TextMuted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun TransferProgressCard(
    progress: TransferProgress,
    onCancel: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = SurfaceElevated),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = if (progress.isDownload) "Descargando: ${progress.label}" else "Enviando: ${progress.label}",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = onCancel, modifier = Modifier.size(28.dp)) {
                    Icon(Icons.Rounded.Close, contentDescription = "Cancelar", tint = TextMuted)
                }
            }
            Spacer(modifier = Modifier.height(6.dp))
            if (progress.fraction >= 0f) {
                LinearProgressIndicator(
                    progress = { progress.fraction },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(999.dp)),
                    color = AccentSky,
                )
            } else {
                LinearProgressIndicator(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(999.dp)),
                    color = AccentSky,
                )
            }
            Spacer(modifier = Modifier.height(6.dp))
            val speedText = if (progress.speedBytesPerSec > 0L) {
                " · ${formatBytes(progress.speedBytesPerSec)}/s"
            } else {
                ""
            }
            val totalText = if (progress.totalBytes > 0L) {
                "${formatBytes(progress.bytesDone)} / ${formatBytes(progress.totalBytes)}"
            } else {
                formatBytes(progress.bytesDone)
            }
            Text(
                text = "$totalText$speedText",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
            )
        }
    }
}

@Composable
private fun PendingShareBanner(
    countDesc: String,
    onConfigureIp: () -> Unit,
    onDismiss: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1E293B)),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier
            .fillMaxWidth()
            .border(1.dp, AccentSky.copy(alpha = 0.4f), RoundedCornerShape(12.dp)),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(12.dp),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("En cola para enviar: $countDesc", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
                Text("Se enviará en cuanto conecte con la PC.", style = MaterialTheme.typography.bodySmall, color = TextMuted)
            }
            TextButton(onClick = onConfigureIp) { Text("IP manual") }
            IconButton(onClick = onDismiss) { Icon(Icons.Rounded.Close, contentDescription = "Descartar") }
        }
    }
}

@Composable
private fun SendTabContent(
    state: QuickDropUiState,
    onTextChange: (String) -> Unit,
    onPasteClick: () -> Unit,
    onSendText: () -> Unit,
    onPickAnyFiles: () -> Unit,
    onPickMedia: () -> Unit,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
) {
    val isConnected = state.connectionState is ConnectionState.Connected

    LazyColumn(
        contentPadding = PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = SurfaceCard),
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        text = "Link o texto rápido",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = state.textInput,
                        onValueChange = onTextChange,
                        placeholder = { Text("Pega un enlace (https://...) o escribe texto") },
                        minLines = 2,
                        maxLines = 5,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(modifier = Modifier.height(10.dp))
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        OutlinedButton(
                            onClick = onPasteClick,
                            modifier = Modifier.weight(1f),
                        ) {
                            Icon(Icons.Rounded.ContentPaste, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Pegar")
                        }
                        Button(
                            onClick = onSendText,
                            enabled = isConnected && state.textInput.isNotBlank(),
                            colors = ButtonDefaults.buttonColors(containerColor = AccentSky),
                            modifier = Modifier.weight(1.3f),
                        ) {
                            Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Enviar a PC")
                        }
                    }
                }
            }
        }

        item {
            Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                FilledTonalButton(
                    onClick = onPickAnyFiles,
                    shape = RoundedCornerShape(14.dp),
                    contentPadding = PaddingValues(vertical = 16.dp, horizontal = 12.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.AttachFile, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Archivos (2 GB)", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                FilledTonalButton(
                    onClick = onPickMedia,
                    shape = RoundedCornerShape(14.dp),
                    contentPadding = PaddingValues(vertical = 16.dp, horizontal = 12.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.PhotoLibrary, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Fotos / Audio", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }

        if (state.sentItems.isNotEmpty()) {
            item {
                Text(
                    text = "Enviados recientemente",
                    style = MaterialTheme.typography.labelLarge,
                    color = TextMuted,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            items(state.sentItems, key = { it.id }) { item ->
                TransferItemCard(
                    item = item,
                    showDownload = false,
                    onCopyText = onCopyText,
                    onOpenLink = onOpenLink,
                    onDownloadFile = {},
                )
            }
        }
    }
}

@Composable
private fun ReceivedTabContent(
    items: List<TransferItem>,
    onRefresh: () -> Unit,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
    onDownloadFile: (TransferItem) -> Unit,
) {
    if (items.isEmpty()) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.fillMaxSize(),
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    imageVector = Icons.Rounded.Inbox,
                    contentDescription = null,
                    tint = TextMuted,
                    modifier = Modifier.size(44.dp),
                )
                Spacer(modifier = Modifier.height(10.dp))
                Text("Aún no recibiste nada desde tu PC", color = TextMuted)
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    "Arrastra archivos o pega links en http://localhost:8765 en tu PC.",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextMuted,
                )
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedButton(onClick = onRefresh) {
                    Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("Actualizar")
                }
            }
        }
        return
    }

    LazyColumn(
        contentPadding = PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        items(items, key = { it.id }) { item ->
            TransferItemCard(
                item = item,
                showDownload = true,
                onCopyText = onCopyText,
                onOpenLink = onOpenLink,
                onDownloadFile = { onDownloadFile(item) },
            )
        }
    }
}

@Composable
private fun TransferItemCard(
    item: TransferItem,
    showDownload: Boolean,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
    onDownloadFile: () -> Unit,
) {
    val icon = when {
        item.kind == "link" -> Icons.Rounded.Link
        item.kind == "file" && item.mimeType.startsWith("image/") -> Icons.Rounded.Image
        item.kind == "file" && item.mimeType.startsWith("audio/") -> Icons.Rounded.AudioFile
        item.kind == "file" -> Icons.Rounded.Description
        else -> Icons.Rounded.Description
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, contentDescription = null, tint = AccentSky, modifier = Modifier.size(20.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = when (item.kind) {
                        "file" -> item.filename ?: "Archivo"
                        "link" -> "Enlace"
                        else -> "Texto"
                    },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = if (item.kind == "file") formatBytes(item.sizeBytes) else item.sender,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }

            if (item.kind != "file" && !item.content.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = item.content,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (item.kind == "link") AccentSky else MaterialTheme.colorScheme.onSurface,
                    maxLines = 4,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (item.kind == "link" && !item.content.isNullOrBlank()) {
                    FilledTonalButton(onClick = { onOpenLink(item.content) }) {
                        Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Abrir")
                    }
                    OutlinedButton(onClick = { onCopyText(item.content) }) {
                        Icon(Icons.Rounded.ContentCopy, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Copiar")
                    }
                } else if (item.kind == "text" && !item.content.isNullOrBlank()) {
                    OutlinedButton(onClick = { onCopyText(item.content) }) {
                        Icon(Icons.Rounded.ContentCopy, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Copiar")
                    }
                } else if (item.kind == "file" && showDownload && item.fileExists) {
                    Button(
                        onClick = onDownloadFile,
                        colors = ButtonDefaults.buttonColors(containerColor = AccentMint),
                    ) {
                        Icon(Icons.Rounded.Download, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Descargar y abrir")
                    }
                }
            }
        }
    }
}

@Composable
private fun ConnectionDialog(
    discovered: List<ServerEndpoint>,
    initialHost: String,
    initialPort: String,
    useManual: Boolean,
    onDismiss: () -> Unit,
    onSelectDiscovered: (ServerEndpoint) -> Unit,
    onConnectManual: (String, String) -> Unit,
    onEnableAuto: () -> Unit,
) {
    var host by remember(initialHost) { mutableStateOf(initialHost) }
    var port by remember(initialPort) { mutableStateOf(initialPort) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Conexión con la PC") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (discovered.isNotEmpty()) {
                    Text("PCs detectadas automáticamente (mDNS):", style = MaterialTheme.typography.labelMedium, color = TextMuted)
                    discovered.forEach { server ->
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(SurfaceElevated)
                                .clickable { onSelectDiscovered(server) }
                                .padding(10.dp),
                        ) {
                            Icon(Icons.Rounded.Computer, contentDescription = null, tint = AccentMint)
                            Spacer(modifier = Modifier.width(10.dp))
                            Column {
                                Text(server.name, fontWeight = FontWeight.SemiBold)
                                Text("${server.host}:${server.port}", style = MaterialTheme.typography.bodySmall, color = TextMuted)
                            }
                        }
                    }
                    HorizontalDivider()
                } else {
                    Text(
                        "Si el router bloquea mDNS, ingresa la IP LAN que muestra el icono de la bandeja en Windows.",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextMuted,
                    )
                }

                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("IP de la PC (ej. 192.168.1.50)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = port,
                    onValueChange = { port = it.filter { ch -> ch.isDigit() } },
                    label = { Text("Puerto") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                if (useManual) {
                    TextButton(onClick = onEnableAuto) {
                        Text("Volver a detección automática (mDNS)")
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = { onConnectManual(host, port) }) {
                Text("Conectar IP")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cerrar")
            }
        },
    )
}

private fun readClipboardText(context: Context): String? {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return null
    val clip = cm.primaryClip ?: return null
    if (clip.itemCount == 0) return null
    return clip.getItemAt(0).coerceToText(context)?.toString()
}

private fun copyToClipboard(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
    cm.setPrimaryClip(ClipData.newPlainText("QuickDrop LAN", text))
}

private fun openExternalUrl(context: Context, url: String) {
    val clean = url.trim()
    if (!clean.startsWith("http://", true) && !clean.startsWith("https://", true)) return
    runCatching {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(clean)))
    }
}

private fun openDownloadedFile(context: Context, uri: Uri, mimeType: String) {
    runCatching {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mimeType.ifBlank { "*/*" })
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(intent, "Abrir archivo"))
    }
}
