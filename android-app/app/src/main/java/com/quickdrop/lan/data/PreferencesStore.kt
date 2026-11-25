package com.quickdrop.lan.data

import android.content.Context
import android.content.SharedPreferences

class PreferencesStore(context: Context) {
    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences("quickdrop_prefs", Context.MODE_PRIVATE)

    var manualHost: String
        get() = prefs.getString(KEY_MANUAL_HOST, "") ?: ""
        set(value) = prefs.edit().putString(KEY_MANUAL_HOST, value.trim()).apply()

    var manualPort: Int
        get() = prefs.getInt(KEY_MANUAL_PORT, 8765)
        set(value) = prefs.edit().putInt(KEY_MANUAL_PORT, value).apply()

    var useManualEndpoint: Boolean
        get() = prefs.getBoolean(KEY_USE_MANUAL, false)
        set(value) = prefs.edit().putBoolean(KEY_USE_MANUAL, value).apply()

    fun getLastEndpoint(): ServerEndpoint? {
        val host = prefs.getString(KEY_LAST_HOST, null)?.takeIf { it.isNotBlank() } ?: return null
        val port = prefs.getInt(KEY_LAST_PORT, 8765)
        val name = prefs.getString(KEY_LAST_NAME, "PC") ?: "PC"
        return ServerEndpoint(name = name, host = host, port = port)
    }

    fun saveLastEndpoint(endpoint: ServerEndpoint) {
        prefs.edit()
            .putString(KEY_LAST_HOST, endpoint.host)
            .putInt(KEY_LAST_PORT, endpoint.port)
            .putString(KEY_LAST_NAME, endpoint.name)
            .apply()
    }

    companion object {
        private const val KEY_MANUAL_HOST = "manual_host"
        private const val KEY_MANUAL_PORT = "manual_port"
        private const val KEY_USE_MANUAL = "use_manual"
        private const val KEY_LAST_HOST = "last_host"
        private const val KEY_LAST_PORT = "last_port"
        private const val KEY_LAST_NAME = "last_name"
    }
}
