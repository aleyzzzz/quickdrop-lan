package com.quickdrop.lan

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import com.quickdrop.lan.notifications.LocalNotificationHelper
import com.quickdrop.lan.ui.QuickDropApp
import com.quickdrop.lan.ui.QuickDropViewModel
import com.quickdrop.lan.ui.theme.QuickDropTheme

class MainActivity : ComponentActivity() {

    private val viewModel: QuickDropViewModel by viewModels()

    private val requestNotificationsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* Best-effort: app remains fully functional even if denied */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        requestNotificationPermissionIfNeeded()
        if (savedInstanceState == null) {
            handleIntent(intent)
        }

        setContent {
            QuickDropTheme {
                QuickDropApp(viewModel = viewModel)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                requestNotificationsLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun handleIntent(intent: Intent?) {
        if (intent == null) return

        if (intent.getBooleanExtra(LocalNotificationHelper.EXTRA_OPEN_RECEIVED_TAB, false)) {
            viewModel.selectTab(1)
            return
        }

        when (intent.action) {
            Intent.ACTION_SEND -> {
                val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT)
                val sharedUri = getParcelableUri(intent, Intent.EXTRA_STREAM)
                val uris = buildList {
                    if (sharedUri != null) {
                        add(sharedUri)
                    } else {
                        extractClipDataUris(intent, this)
                    }
                }
                viewModel.handleIncomingShare(text = sharedText, uris = uris)
            }

            Intent.ACTION_SEND_MULTIPLE -> {
                val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT)
                val extraUris = getParcelableUriList(intent, Intent.EXTRA_STREAM)
                val uris = if (extraUris.isNotEmpty()) {
                    extraUris
                } else {
                    buildList { extractClipDataUris(intent, this) }
                }
                viewModel.handleIncomingShare(text = sharedText, uris = uris)
            }
        }
    }

    private fun extractClipDataUris(intent: Intent, out: MutableList<Uri>) {
        val clip = intent.clipData ?: return
        for (i in 0 until clip.itemCount) {
            clip.getItemAt(i).uri?.let { out.add(it) }
        }
    }

    @Suppress("DEPRECATION")
    private fun getParcelableUri(intent: Intent, key: String): Uri? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(key, Uri::class.java)
        } else {
            intent.getParcelableExtra(key)
        }

    @Suppress("DEPRECATION")
    private fun getParcelableUriList(intent: Intent, key: String): List<Uri> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableArrayListExtra(key, Uri::class.java).orEmpty()
        } else {
            intent.getParcelableArrayListExtra<Uri>(key).orEmpty()
        }
}
