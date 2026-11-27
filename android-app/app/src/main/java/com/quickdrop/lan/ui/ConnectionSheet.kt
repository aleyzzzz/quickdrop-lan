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
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Computer
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Wifi
import androidx.compose.material3.BottomSheetDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quickdrop.lan.data.ConnectionState
import com.quickdrop.lan.data.ServerEndpoint
import com.quickdrop.lan.ui.theme.AccentCyan
import com.quickdrop.lan.ui.theme.AccentEmerald
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectionBottomSheet(
    connectionState: ConnectionState,
    discovered: List<ServerEndpoint>,
    initialHost: String,
    initialPort: String,
    useManual: Boolean,
    onDismiss: () -> Unit,
    onRescanMdns: () -> Unit,
    onSelectDiscovered: (ServerEndpoint) -> Unit,
    onConnectManual: (String, String) -> Unit,
    onEnableAuto: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var host by remember(initialHost) { mutableStateOf(initialHost) }
    var port by remember(initialPort) { mutableStateOf(initialPort) }

    val activeHost = (connectionState as? ConnectionState.Connected)?.endpoint?.host

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = SurfaceCard,
        contentColor = TextPrimary,
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
        dragHandle = {
            BottomSheetDefaults.DragHandle(color = BorderStrong)
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .navigationBarsPadding()
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column {
                    Text(
                        text = "Conexión LAN",
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary,
                    )
                    Text(
                        text = "Red Wi-Fi local sin servidores externos",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextTertiary,
                    )
                }
                FilledTonalButton(
                    onClick = onRescanMdns,
                    shape = RoundedCornerShape(10.dp),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    colors = ButtonDefaults.filledTonalButtonColors(
                        containerColor = SurfaceElevated,
                        contentColor = AccentCyan,
                    ),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Refresh,
                        contentDescription = null,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("Escanear", style = MaterialTheme.typography.labelMedium)
                }
            }

            // Active status summary card
            Surface(
                color = SurfaceElevated,
                shape = RoundedCornerShape(16.dp),
                border = BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(14.dp),
                ) {
                    val (dotColor, title, subtitle) = when (connectionState) {
                        is ConnectionState.Connected -> Triple(
                            AccentEmerald,
                            connectionState.info.hostname.ifBlank { connectionState.endpoint.name },
                            "${connectionState.endpoint.host}:${connectionState.endpoint.port}",
                        )
                        is ConnectionState.Searching -> Triple(
                            StatusAmber,
                            "Buscando PC en la red…",
                            "Servicio mDNS _quickdrop._tcp.",
                        )
                        is ConnectionState.Disconnected -> Triple(
                            StatusError,
                            "Sin conexión",
                            connectionState.message,
                        )
                    }

                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .size(36.dp)
                            .clip(RoundedCornerShape(10.dp))
                            .background(dotColor.copy(alpha = 0.14f)),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Wifi,
                            contentDescription = null,
                            tint = dotColor,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.titleSmall,
                            color = TextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = subtitle,
                            style = MonoTextStyle.copy(fontSize = 12.sp),
                            color = TextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Box(
                        modifier = Modifier
                            .size(9.dp)
                            .clip(CircleShape)
                            .background(dotColor),
                    )
                }
            }

            // Discovered PCs via mDNS
            if (discovered.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = "DETECTADOS POR mDNS",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                    )
                    discovered.forEach { server ->
                        val isCurrent = activeHost == server.host && !useManual
                        Surface(
                            color = if (isCurrent) AccentEmerald.copy(alpha = 0.08f) else SurfaceElevated,
                            shape = RoundedCornerShape(14.dp),
                            border = BorderStroke(
                                1.dp,
                                if (isCurrent) AccentEmerald.copy(alpha = 0.35f) else BorderSubtle,
                            ),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(14.dp))
                                .clickable { onSelectDiscovered(server) },
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.Computer,
                                    contentDescription = null,
                                    tint = if (isCurrent) AccentEmerald else AccentCyan,
                                    modifier = Modifier.size(20.dp),
                                )
                                Spacer(modifier = Modifier.width(12.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = server.name,
                                        style = MaterialTheme.typography.titleSmall,
                                        color = TextPrimary,
                                    )
                                    Text(
                                        text = "${server.host}:${server.port}",
                                        style = MonoTextStyle.copy(fontSize = 12.sp),
                                        color = TextSecondary,
                                    )
                                }
                                if (isCurrent) {
                                    Icon(
                                        imageVector = Icons.Rounded.Check,
                                        contentDescription = "Conectado",
                                        tint = AccentEmerald,
                                        modifier = Modifier.size(18.dp),
                                    )
                                }
                            }
                        }
                    }
                }
            }

            HorizontalDivider(thickness = 1.dp, color = BorderSubtle)

            // Manual IP fallback section
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        text = "CONEXIÓN MANUAL (IP)",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                    )
                    if (useManual) {
                        TextButton(
                            onClick = onEnableAuto,
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                        ) {
                            Text(
                                text = "Usar mDNS automático",
                                style = MaterialTheme.typography.labelMedium,
                                color = AccentCyan,
                            )
                        }
                    }
                }

                val fieldColors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = AccentCyan,
                    unfocusedBorderColor = BorderSubtle,
                    focusedContainerColor = SurfaceElevated,
                    unfocusedContainerColor = SurfaceElevated,
                    cursorColor = AccentCyan,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary,
                    focusedLabelColor = AccentCyan,
                    unfocusedLabelColor = TextTertiary,
                )

                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    OutlinedTextField(
                        value = host,
                        onValueChange = { host = it },
                        label = { Text("IP de la PC") },
                        placeholder = { Text("192.168.1.36", color = TextTertiary) },
                        singleLine = true,
                        textStyle = MonoTextStyle.copy(fontSize = 14.sp, color = TextPrimary),
                        shape = RoundedCornerShape(12.dp),
                        colors = fieldColors,
                        modifier = Modifier.weight(1.7f),
                    )
                    OutlinedTextField(
                        value = port,
                        onValueChange = { port = it.filter { ch -> ch.isDigit() } },
                        label = { Text("Puerto") },
                        singleLine = true,
                        textStyle = MonoTextStyle.copy(fontSize = 14.sp, color = TextPrimary),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        shape = RoundedCornerShape(12.dp),
                        colors = fieldColors,
                        modifier = Modifier.weight(0.9f),
                    )
                }

                Button(
                    onClick = { onConnectManual(host, port) },
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = AccentCyan,
                        contentColor = Color(0xFF041318),
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(46.dp),
                ) {
                    Text(
                        text = "Conectar a IP manual",
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))
        }
    }
}
