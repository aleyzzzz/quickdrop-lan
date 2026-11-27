package com.quickdrop.lan.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.AttachFile
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.SwapVert
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.quickdrop.lan.data.ConnectionState
import com.quickdrop.lan.data.TransferItem
import com.quickdrop.lan.data.TransferProgress
import com.quickdrop.lan.data.formatBytes
import com.quickdrop.lan.ui.theme.AccentCyan
import com.quickdrop.lan.ui.theme.AccentCyanLight
import com.quickdrop.lan.ui.theme.AccentEmerald
import com.quickdrop.lan.ui.theme.BgBase
import com.quickdrop.lan.ui.theme.BorderSubtle
import com.quickdrop.lan.ui.theme.MonoTextStyle
import com.quickdrop.lan.ui.theme.StatusAmber
import com.quickdrop.lan.ui.theme.StatusError
import com.quickdrop.lan.ui.theme.SurfaceCard
import com.quickdrop.lan.ui.theme.SurfaceElevated
import com.quickdrop.lan.ui.theme.SurfaceNav
import com.quickdrop.lan.ui.theme.TextPrimary
import com.quickdrop.lan.ui.theme.TextSecondary
import com.quickdrop.lan.ui.theme.TextTertiary

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QuickDropApp(viewModel: QuickDropViewModel) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbarHostState = remember { SnackbarHostState() }

    var showConnectionSheet by remember { mutableStateOf(false) }
    var searchQuery by remember { mutableStateOf("") }
    var selectedFilter by remember { mutableStateOf(HistoryFilter.ALL) }
    var previewImageTarget by remember { mutableStateOf<Pair<TransferItem, String>?>(null) }

    val baseUrl = (state.connectionState as? ConnectionState.Connected)?.endpoint?.baseUrl

    // Native Photo Picker (Photos, Videos, GIFs)
    val visualMediaPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickMultipleVisualMedia(),
    ) { uris ->
        if (uris.isNotEmpty()) viewModel.sendFiles(uris)
    }

    // Any file picker (Audio, PDF, ZIP, APK, Documents)
    val anyFilesPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        if (uris.isNotEmpty()) viewModel.sendFiles(uris)
    }

    LaunchedEffect(state.snackbarMessage) {
        val msg = state.snackbarMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(msg)
        viewModel.consumeSnackbar()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(BgBase),
    ) {
        Scaffold(
            containerColor = BgBase,
            snackbarHost = {
                SnackbarHost(hostState = snackbarHostState) { data ->
                    Snackbar(
                        snackbarData = data,
                        containerColor = SurfaceElevated,
                        contentColor = TextPrimary,
                        shape = RoundedCornerShape(12.dp),
                    )
                }
            },
            topBar = {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = BgBase,
                        titleContentColor = TextPrimary,
                    ),
                    title = {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .size(28.dp)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(AccentCyan.copy(alpha = 0.14f)),
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.SwapVert,
                                    contentDescription = null,
                                    tint = AccentCyanLight,
                                    modifier = Modifier.size(17.dp),
                                )
                            }
                            Text(
                                text = "QuickDrop",
                                style = MaterialTheme.typography.titleMedium,
                                color = TextPrimary,
                            )
                        }
                    },
                    actions = {
                        ConnectionStatusPill(
                            connectionState = state.connectionState,
                            onClick = { showConnectionSheet = true },
                            modifier = Modifier.padding(end = 12.dp),
                        )
                    },
                )
            },
            bottomBar = {
                Column {
                    HorizontalDivider(thickness = 1.dp, color = BorderSubtle)
                    NavigationBar(
                        containerColor = SurfaceNav,
                        tonalElevation = 0.dp,
                    ) {
                        val navColors = NavigationBarItemDefaults.colors(
                            selectedIconColor = AccentCyanLight,
                            selectedTextColor = TextPrimary,
                            indicatorColor = AccentCyan.copy(alpha = 0.14f),
                            unselectedIconColor = TextTertiary,
                            unselectedTextColor = TextTertiary,
                        )
                        NavigationBarItem(
                            selected = state.selectedTab == 0,
                            onClick = { viewModel.selectTab(0) },
                            icon = { Icon(Icons.Rounded.ArrowUpward, contentDescription = "Enviar") },
                            label = { Text("Enviar", style = MaterialTheme.typography.labelMedium) },
                            colors = navColors,
                        )
                        NavigationBarItem(
                            selected = state.selectedTab == 1,
                            onClick = { viewModel.selectTab(1) },
                            icon = {
                                BadgedBox(
                                    badge = {
                                        if (state.unreadReceivedCount > 0) {
                                            Badge(
                                                containerColor = AccentEmerald,
                                                contentColor = Color(0xFF041A12),
                                            ) {
                                                Text(state.unreadReceivedCount.toString())
                                            }
                                        }
                                    },
                                ) {
                                    Icon(Icons.Rounded.History, contentDescription = "Historial")
                                }
                            },
                            label = { Text("Historial", style = MaterialTheme.typography.labelMedium) },
                            colors = navColors,
                        )
                    }
                }
            },
        ) { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .padding(horizontal = 16.dp),
            ) {
                if (state.selectedTab == 0) {
                    SendScreen(
                        state = state,
                        baseUrl = baseUrl,
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
                        onPickGallery = {
                            visualMediaPicker.launch(
                                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo),
                            )
                        },
                        onPickAnyFiles = { anyFilesPicker.launch(arrayOf("*/*")) },
                        onCancelTransfer = viewModel::cancelActiveTransfer,
                        onOpenHistory = { viewModel.selectTab(1) },
                        onCopyText = {
                            copyToClipboard(context, it)
                            viewModel.showSnackbar("Copiado")
                        },
                        onOpenLink = { openExternalUrl(context, it) },
                        onDownloadFile = { item ->
                            viewModel.downloadItem(item) { uri, mime ->
                                openDownloadedFile(context, uri, mime)
                            }
                        },
                        onPreviewImage = { item, url -> previewImageTarget = item to url },
                    )
                } else {
                    HistoryScreen(
                        allItems = remember(state.receivedItems, state.sentItems) {
                            (state.receivedItems + state.sentItems)
                                .distinctBy { it.id }
                                .sortedByDescending { parseItemEpochMillis(it.createdAt) }
                        },
                        baseUrl = baseUrl,
                        searchQuery = searchQuery,
                        selectedFilter = selectedFilter,
                        downloadingItemId = state.downloadingItemId,
                        downloadedItemIds = state.downloadedItemIds,
                        activeTransfer = state.activeTransfer,
                        onSearchChange = { searchQuery = it },
                        onFilterChange = { selectedFilter = it },
                        onRefresh = viewModel::refreshItems,
                        onCancelTransfer = viewModel::cancelActiveTransfer,
                        onCopyText = {
                            copyToClipboard(context, it)
                            viewModel.showSnackbar("Copiado")
                        },
                        onOpenLink = { openExternalUrl(context, it) },
                        onDownloadFile = { item ->
                            viewModel.downloadItem(item) { uri, mime ->
                                openDownloadedFile(context, uri, mime)
                            }
                        },
                        onPreviewImage = { item, url -> previewImageTarget = item to url },
                    )
                }
            }
        }

        // Centered elegant dark overlay for incoming Android Share Sheet intents
        ShareSheetOverlay(
            shareState = state.shareSheetState,
            activeTransfer = state.activeTransfer,
            onConfigureIp = { showConnectionSheet = true },
            onDismiss = viewModel::dismissShareSheet,
        )
    }

    if (showConnectionSheet) {
        ConnectionBottomSheet(
            connectionState = state.connectionState,
            discovered = state.discoveredServers,
            initialHost = state.manualHost,
            initialPort = state.manualPort,
            useManual = state.useManualEndpoint,
            onDismiss = { showConnectionSheet = false },
            onRescanMdns = viewModel::restartDiscovery,
            onSelectDiscovered = { endpoint ->
                viewModel.selectDiscoveredServer(endpoint)
                showConnectionSheet = false
            },
            onConnectManual = { host, port ->
                viewModel.applyManualConnection(host, port)
                showConnectionSheet = false
            },
            onEnableAuto = {
                viewModel.switchToAutoDiscovery()
                showConnectionSheet = false
            },
        )
    }

    previewImageTarget?.let { (item, url) ->
        ImageViewerDialog(
            item = item,
            imageUrl = url,
            isDownloading = state.downloadingItemId == item.id,
            isDownloaded = item.id in state.downloadedItemIds,
            onDismiss = { previewImageTarget = null },
            onDownload = {
                viewModel.downloadItem(item) { uri, mime ->
                    openDownloadedFile(context, uri, mime)
                }
            },
        )
    }
}

@Composable
private fun ConnectionStatusPill(
    connectionState: ConnectionState,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "statusPulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 0.35f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1000),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "dotAlpha",
    )

    val (dotColor, shouldPulse, label) = when (connectionState) {
        is ConnectionState.Connected -> Triple(
            AccentEmerald,
            true,
            connectionState.info.hostname.ifBlank { connectionState.endpoint.name },
        )
        is ConnectionState.Searching -> Triple(StatusAmber, true, "Buscando…")
        is ConnectionState.Disconnected -> Triple(StatusError, false, "Sin conexión")
    }

    Surface(
        color = SurfaceCard,
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, BorderSubtle),
        modifier = modifier
            .clip(RoundedCornerShape(999.dp))
            .clickable(onClick = onClick),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(start = 10.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .alpha(if (shouldPulse) pulseAlpha else 1f)
                    .clip(CircleShape)
                    .background(dotColor),
            )
            Spacer(modifier = Modifier.width(7.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(modifier = Modifier.width(2.dp))
            Icon(
                imageVector = Icons.Rounded.KeyboardArrowDown,
                contentDescription = "Configurar conexión",
                tint = TextTertiary,
                modifier = Modifier.size(16.dp),
            )
        }
    }
}

@Composable
private fun ActiveTransferCard(
    progress: TransferProgress,
    onCancel: () -> Unit,
) {
    val rawFraction = progress.fraction
    val animatedProgress by animateFloatAsState(
        targetValue = if (rawFraction >= 0f) rawFraction else 0f,
        label = "transferProgress",
    )
    val percent = if (rawFraction >= 0f) "${(rawFraction * 100f).toInt().coerceIn(0, 100)}%" else "…"
    val speedStr = if (progress.speedBytesPerSec > 0L) "${formatBytes(progress.speedBytesPerSec)}/s" else ""

    Surface(
        color = SurfaceElevated,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, AccentCyan.copy(alpha = 0.35f)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = if (progress.isDownload) "DESCARGANDO" else "ENVIANDO",
                        style = MaterialTheme.typography.labelSmall,
                        color = AccentCyanLight,
                    )
                    Text(
                        text = progress.label,
                        style = MaterialTheme.typography.titleSmall,
                        color = TextPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Text(
                    text = percent,
                    style = MonoTextStyle.copy(fontSize = 14.sp, fontWeight = FontWeight.Bold),
                    color = AccentCyanLight,
                )
                IconButton(
                    onClick = onCancel,
                    modifier = Modifier.size(30.dp),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Close,
                        contentDescription = "Cancelar",
                        tint = TextTertiary,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }

            if (rawFraction >= 0f) {
                LinearProgressIndicator(
                    progress = { animatedProgress },
                    color = AccentCyan,
                    trackColor = BgBase,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(999.dp)),
                )
            } else {
                LinearProgressIndicator(
                    color = AccentCyan,
                    trackColor = BgBase,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(999.dp)),
                )
            }

            Row(
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth(),
            ) {
                val bytesLabel = if (progress.totalBytes > 0L) {
                    "${formatBytes(progress.bytesDone)} / ${formatBytes(progress.totalBytes)}"
                } else {
                    formatBytes(progress.bytesDone)
                }
                Text(
                    text = bytesLabel,
                    style = MonoTextStyle.copy(fontSize = 11.sp),
                    color = TextSecondary,
                )
                if (speedStr.isNotBlank()) {
                    Text(
                        text = speedStr,
                        style = MonoTextStyle.copy(fontSize = 11.sp),
                        color = AccentEmerald,
                    )
                }
            }
        }
    }
}

@Composable
private fun SendScreen(
    state: QuickDropUiState,
    baseUrl: String?,
    onTextChange: (String) -> Unit,
    onPasteClick: () -> Unit,
    onSendText: () -> Unit,
    onPickGallery: () -> Unit,
    onPickAnyFiles: () -> Unit,
    onCancelTransfer: () -> Unit,
    onOpenHistory: () -> Unit,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
    onDownloadFile: (TransferItem) -> Unit,
    onPreviewImage: (TransferItem, String) -> Unit,
) {
    val isConnected = state.connectionState is ConnectionState.Connected
    val looksLikeUrl = remember(state.textInput) {
        val trimmed = state.textInput.trim()
        trimmed.startsWith("http://", ignoreCase = true) || trimmed.startsWith("https://", ignoreCase = true)
    }
    val recentSent = remember(state.sentItems) { state.sentItems.take(3) }

    LazyColumn(
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item {
            AnimatedVisibility(
                visible = state.activeTransfer != null && state.shareSheetState == null,
                enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically(),
            ) {
                state.activeTransfer?.let { progress ->
                    ActiveTransferCard(progress = progress, onCancel = onCancelTransfer)
                }
            }
        }

        // Quick Text / Link Card
        item {
            Surface(
                color = SurfaceCard,
                shape = RoundedCornerShape(18.dp),
                border = BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            text = "Texto o enlace",
                            style = MaterialTheme.typography.titleSmall,
                            color = TextPrimary,
                        )
                        AnimatedVisibility(visible = looksLikeUrl) {
                            Surface(
                                color = AccentCyan.copy(alpha = 0.14f),
                                shape = RoundedCornerShape(999.dp),
                            ) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                ) {
                                    Icon(
                                        imageVector = Icons.Rounded.Link,
                                        contentDescription = null,
                                        tint = AccentCyanLight,
                                        modifier = Modifier.size(13.dp),
                                    )
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text(
                                        text = "Enlace",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = AccentCyanLight,
                                    )
                                }
                            }
                        }
                    }

                    OutlinedTextField(
                        value = state.textInput,
                        onValueChange = onTextChange,
                        placeholder = {
                            Text(
                                text = "Pega un enlace o escribe algo para tu PC…",
                                color = TextTertiary,
                            )
                        },
                        minLines = 3,
                        maxLines = 5,
                        shape = RoundedCornerShape(12.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = AccentCyan,
                            unfocusedBorderColor = BorderSubtle,
                            focusedContainerColor = SurfaceElevated,
                            unfocusedContainerColor = SurfaceElevated,
                            cursorColor = AccentCyan,
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    )

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        OutlinedButton(
                            onClick = onPasteClick,
                            shape = RoundedCornerShape(12.dp),
                            border = BorderStroke(1.dp, BorderSubtle),
                            modifier = Modifier
                                .weight(0.95f)
                                .height(44.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.ContentPaste,
                                contentDescription = null,
                                tint = TextSecondary,
                                modifier = Modifier.size(17.dp),
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Pegar", style = MaterialTheme.typography.labelLarge, color = TextPrimary)
                        }

                        Button(
                            onClick = onSendText,
                            enabled = isConnected && state.textInput.isNotBlank() && !state.isSendingText,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = AccentCyan,
                                contentColor = Color(0xFF041318),
                                disabledContainerColor = SurfaceElevated,
                                disabledContentColor = TextTertiary,
                            ),
                            modifier = Modifier
                                .weight(1.35f)
                                .height(44.dp),
                        ) {
                            if (state.isSendingText) {
                                CircularProgressIndicator(
                                    strokeWidth = 2.dp,
                                    color = Color(0xFF041318),
                                    modifier = Modifier.size(16.dp),
                                )
                            } else {
                                Icon(
                                    imageVector = Icons.AutoMirrored.Rounded.Send,
                                    contentDescription = null,
                                    modifier = Modifier.size(17.dp),
                                )
                            }
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = if (state.isSendingText) "Enviando…" else "Enviar",
                                style = MaterialTheme.typography.labelLarge,
                            )
                        }
                    }
                }
            }
        }

        // 2-Column Large Media & File Picker Cards
        item {
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                QuickActionTile(
                    icon = Icons.Rounded.PhotoLibrary,
                    accentColor = AccentCyanLight,
                    title = "Galería",
                    subtitle = "Fotos · Videos · GIFs",
                    onClick = onPickGallery,
                    modifier = Modifier.weight(1f),
                )
                QuickActionTile(
                    icon = Icons.Rounded.AttachFile,
                    accentColor = AccentEmerald,
                    title = "Archivos",
                    subtitle = "Audio · PDF · ZIP · APK",
                    onClick = onPickAnyFiles,
                    modifier = Modifier.weight(1f),
                )
            }
        }

        // Recent sends compact preview
        if (recentSent.isNotEmpty()) {
            item {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 4.dp),
                ) {
                    Text(
                        text = "RECIENTES",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                    )
                    TextButton(
                        onClick = onOpenHistory,
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                    ) {
                        Text(
                            text = "Ver historial",
                            style = MaterialTheme.typography.labelMedium,
                            color = AccentCyanLight,
                        )
                    }
                }
            }
            items(recentSent, key = { it.id }) { item ->
                HistoryItemCard(
                    item = item,
                    baseUrl = baseUrl,
                    isDownloading = state.downloadingItemId == item.id,
                    isDownloaded = item.id in state.downloadedItemIds,
                    onCopyText = onCopyText,
                    onOpenLink = onOpenLink,
                    onDownloadFile = onDownloadFile,
                    onPreviewImage = onPreviewImage,
                )
            }
        }
    }
}

@Composable
private fun QuickActionTile(
    icon: ImageVector,
    accentColor: Color,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        color = SurfaceCard,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, BorderSubtle),
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .clickable(onClick = onClick),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(42.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(accentColor.copy(alpha = 0.13f)),
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = accentColor,
                    modifier = Modifier.size(22.dp),
                )
            }
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    color = TextPrimary,
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun HistoryScreen(
    allItems: List<TransferItem>,
    baseUrl: String?,
    searchQuery: String,
    selectedFilter: HistoryFilter,
    downloadingItemId: String?,
    downloadedItemIds: Set<String>,
    activeTransfer: TransferProgress?,
    onSearchChange: (String) -> Unit,
    onFilterChange: (HistoryFilter) -> Unit,
    onRefresh: () -> Unit,
    onCancelTransfer: () -> Unit,
    onCopyText: (String) -> Unit,
    onOpenLink: (String) -> Unit,
    onDownloadFile: (TransferItem) -> Unit,
    onPreviewImage: (TransferItem, String) -> Unit,
) {
    val filteredItems = remember(allItems, searchQuery, selectedFilter) {
        val q = searchQuery.trim().lowercase()
        allItems.filter { item ->
            val matchesFilter = when (selectedFilter) {
                HistoryFilter.ALL -> true
                HistoryFilter.FROM_PC -> item.direction == "to_phone"
                HistoryFilter.SENT -> item.direction == "to_pc"
                HistoryFilter.LINKS -> item.kind == "link"
                HistoryFilter.FILES -> item.kind == "file"
            }
            if (!matchesFilter) return@filter false
            if (q.isEmpty()) return@filter true
            val hay = listOfNotNull(item.filename, item.content, item.sender, item.mimeType)
                .joinToString(" ")
                .lowercase()
            hay.contains(q)
        }
    }

    val groupedSections = remember(filteredItems) {
        val order = listOf("Hoy", "Ayer", "Anteriores")
        val map = filteredItems.groupBy { chronologicalSectionLabel(it.createdAt) }
        order.mapNotNull { label -> map[label]?.let { label to it } }
    }

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Compact search bar + refresh button
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 6.dp),
        ) {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = onSearchChange,
                placeholder = { Text("Buscar archivos, links…", color = TextTertiary, style = MaterialTheme.typography.bodyMedium) },
                singleLine = true,
                leadingIcon = {
                    Icon(
                        imageVector = Icons.Rounded.Search,
                        contentDescription = null,
                        tint = TextTertiary,
                        modifier = Modifier.size(18.dp),
                    )
                },
                trailingIcon = {
                    if (searchQuery.isNotEmpty()) {
                        IconButton(onClick = { onSearchChange("") }) {
                            Icon(
                                imageVector = Icons.Rounded.Close,
                                contentDescription = "Limpiar búsqueda",
                                tint = TextTertiary,
                                modifier = Modifier.size(17.dp),
                            )
                        }
                    }
                },
                shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentCyan,
                    unfocusedBorderColor = BorderSubtle,
                    focusedContainerColor = SurfaceCard,
                    unfocusedContainerColor = SurfaceCard,
                    cursorColor = AccentCyan,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                ),
                modifier = Modifier.weight(1f),
            )

            Surface(
                color = SurfaceCard,
                shape = RoundedCornerShape(12.dp),
                border = BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.size(52.dp),
            ) {
                IconButton(onClick = onRefresh) {
                    Icon(
                        imageVector = Icons.Rounded.Refresh,
                        contentDescription = "Actualizar historial",
                        tint = TextSecondary,
                    )
                }
            }
        }

        // Horizontal filter chips
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            items(HistoryFilter.entries) { filter ->
                val selected = filter == selectedFilter
                FilterChip(
                    selected = selected,
                    onClick = { onFilterChange(filter) },
                    label = {
                        Text(
                            text = filter.label,
                            style = MaterialTheme.typography.labelMedium,
                        )
                    },
                    shape = RoundedCornerShape(999.dp),
                    colors = FilterChipDefaults.filterChipColors(
                        containerColor = SurfaceCard,
                        labelColor = TextSecondary,
                        selectedContainerColor = AccentCyan.copy(alpha = 0.16f),
                        selectedLabelColor = AccentCyanLight,
                    ),
                    border = FilterChipDefaults.filterChipBorder(
                        enabled = true,
                        selected = selected,
                        borderColor = BorderSubtle,
                        selectedBorderColor = AccentCyan.copy(alpha = 0.45f),
                    ),
                )
            }
        }

        AnimatedVisibility(
            visible = activeTransfer != null,
            enter = fadeIn() + expandVertically(),
            exit = fadeOut() + shrinkVertically(),
        ) {
            activeTransfer?.let { progress ->
                ActiveTransferCard(progress = progress, onCancel = onCancelTransfer)
            }
        }

        if (groupedSections.isEmpty()) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.History,
                        contentDescription = null,
                        tint = TextTertiary,
                        modifier = Modifier.size(40.dp),
                    )
                    Text(
                        text = if (allItems.isEmpty()) {
                            "Aún no hay transferencias"
                        } else {
                            "Sin resultados para este filtro"
                        },
                        style = MaterialTheme.typography.titleSmall,
                        color = TextSecondary,
                    )
                    Text(
                        text = if (allItems.isEmpty()) {
                            "Lo que envíes o recibas desde tu PC aparecerá aquí."
                        } else {
                            "Prueba otra búsqueda o cambia el chip de filtro."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = TextTertiary,
                    )
                }
            }
        } else {
            LazyColumn(
                contentPadding = PaddingValues(top = 2.dp, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                groupedSections.forEach { (sectionLabel, itemsInSection) ->
                    item(key = "header_$sectionLabel") {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 6.dp, bottom = 2.dp),
                        ) {
                            Text(
                                text = sectionLabel.uppercase(),
                                style = MaterialTheme.typography.labelSmall,
                                color = TextTertiary,
                            )
                            Text(
                                text = "(${itemsInSection.size})",
                                style = MonoTextStyle.copy(fontSize = 11.sp),
                                color = TextTertiary,
                            )
                            HorizontalDivider(
                                thickness = 1.dp,
                                color = BorderSubtle,
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                    items(itemsInSection, key = { it.id }) { item ->
                        HistoryItemCard(
                            item = item,
                            baseUrl = baseUrl,
                            isDownloading = downloadingItemId == item.id,
                            isDownloaded = item.id in downloadedItemIds,
                            onCopyText = onCopyText,
                            onOpenLink = onOpenLink,
                            onDownloadFile = onDownloadFile,
                            onPreviewImage = onPreviewImage,
                        )
                    }
                }
            }
        }
    }
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
