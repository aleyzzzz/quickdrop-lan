package com.quickdrop.lan.notifications

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.quickdrop.lan.MainActivity
import com.quickdrop.lan.R
import com.quickdrop.lan.data.TransferItem
import com.quickdrop.lan.data.formatBytes

class LocalNotificationHelper(private val context: Context) {

    init {
        ensureChannel()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Recibidos desde PC",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "Notificaciones instantáneas cuando tu PC envía links, texto o archivos."
            }
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    @SuppressLint("MissingPermission")
    fun notifyIncomingFromPc(item: TransferItem) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) return
        }

        val (title, body, tapIntent) = when (item.kind) {
            "link" -> {
                val url = item.content.orEmpty().trim()
                val safeIntent = if (url.startsWith("http://", true) || url.startsWith("https://", true)) {
                    Intent(Intent.ACTION_VIEW, Uri.parse(url))
                } else {
                    openReceivedTabIntent()
                }
                Triple("Enlace recibido de ${item.sender}", url, safeIntent)
            }

            "file" -> {
                val label = "${item.filename ?: "Archivo"} (${formatBytes(item.sizeBytes)})"
                Triple("Archivo recibido de ${item.sender}", label, openReceivedTabIntent())
            }

            else -> {
                val preview = item.content.orEmpty().take(160)
                Triple("Texto recibido de ${item.sender}", preview, openReceivedTabIntent())
            }
        }

        val pendingIntent = PendingIntent.getActivity(
            context,
            item.id.hashCode(),
            tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        runCatching {
            NotificationManagerCompat.from(context).notify(item.id.hashCode(), notification)
        }
    }

    private fun openReceivedTabIntent(): Intent =
        Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_OPEN_RECEIVED_TAB, true)
        }

    companion object {
        const val CHANNEL_ID = "quickdrop_pc_items"
        const val EXTRA_OPEN_RECEIVED_TAB = "open_received_tab"
    }
}
