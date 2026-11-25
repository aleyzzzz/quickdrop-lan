package com.quickdrop.lan.network

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.util.Log
import androidx.annotation.RequiresApi
import com.quickdrop.lan.data.ServerEndpoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import java.net.Inet4Address
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import kotlin.coroutines.resume

/**
 * Discovers QuickDrop LAN PC servers automatically via Android's native NsdManager (mDNS).
 * Handles both Android 14+ ServiceInfoCallback and serialized legacy resolveService on API 26-33.
 */
class NsdDiscoveryManager(context: Context) {

    private val appContext = context.applicationContext
    private val nsdManager = appContext.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifiManager = appContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val callbackExecutor = Executors.newSingleThreadExecutor()

    private val _servers = MutableStateFlow<List<ServerEndpoint>>(emptyList())
    val servers: StateFlow<List<ServerEndpoint>> = _servers.asStateFlow()

    private val endpointsByKey = ConcurrentHashMap<String, ServerEndpoint>()
    private val api34Callbacks = ConcurrentHashMap<String, Any>()
    private val legacyResolveQueue = Channel<NsdServiceInfo>(capacity = Channel.UNLIMITED)

    private var multicastLock: WifiManager.MulticastLock? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    @Volatile
    private var isRunning = false

    init {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            scope.launch {
                for (service in legacyResolveQueue) {
                    resolveLegacySequentially(service)
                }
            }
        }
    }

    fun start() {
        if (isRunning) return
        isRunning = true
        acquireMulticastLock()

        val listener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "onStartDiscoveryFailed: $errorCode")
                stop()
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "onStopDiscoveryFailed: $errorCode")
            }

            override fun onDiscoveryStarted(serviceType: String) {
                Log.d(TAG, "mDNS discovery started for $serviceType")
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.d(TAG, "mDNS discovery stopped for $serviceType")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (!serviceInfo.serviceType.contains("_quickdrop")) return
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                    registerApi34Resolver(serviceInfo)
                } else {
                    legacyResolveQueue.trySend(serviceInfo)
                }
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                val key = serviceInfo.serviceName
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                    unregisterApi34Resolver(key)
                }
                if (endpointsByKey.remove(key) != null) {
                    emitServers()
                }
            }
        }

        discoveryListener = listener
        try {
            nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (exc: Exception) {
            Log.w(TAG, "Failed to start mDNS discovery", exc)
            isRunning = false
            releaseMulticastLock()
        }
    }

    fun restart() {
        stop()
        endpointsByKey.clear()
        emitServers()
        start()
    }

    fun stop() {
        isRunning = false
        discoveryListener?.let { listener ->
            try {
                nsdManager.stopServiceDiscovery(listener)
            } catch (_: Exception) {
            }
        }
        discoveryListener = null

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            for (key in api34Callbacks.keys.toList()) {
                unregisterApi34Resolver(key)
            }
        }
        releaseMulticastLock()
    }

    @RequiresApi(Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
    private fun registerApi34Resolver(serviceInfo: NsdServiceInfo) {
        val key = serviceInfo.serviceName
        unregisterApi34Resolver(key)

        val callback = object : NsdManager.ServiceInfoCallback {
            override fun onServiceInfoCallbackRegistrationFailed(errorCode: Int) {
                Log.w(TAG, "ServiceInfoCallback registration failed: $errorCode")
            }

            override fun onServiceUpdated(resolved: NsdServiceInfo) {
                val ipv4 = resolved.hostAddresses
                    .firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
                    ?.hostAddress
                    ?: return
                val port = resolved.port.takeIf { it > 0 } ?: 8765
                val displayName = resolved.attributes["host"]?.decodeToString()
                    ?.takeIf { it.isNotBlank() }
                    ?: resolved.serviceName.removePrefix("QuickDrop-")
                endpointsByKey[key] = ServerEndpoint(
                    name = displayName,
                    host = ipv4,
                    port = port,
                )
                emitServers()
            }

            override fun onServiceLost() {
                if (endpointsByKey.remove(key) != null) {
                    emitServers()
                }
            }

            override fun onServiceInfoCallbackUnregistered() = Unit
        }

        api34Callbacks[key] = callback
        try {
            nsdManager.registerServiceInfoCallback(serviceInfo, callbackExecutor, callback)
        } catch (exc: Exception) {
            Log.w(TAG, "registerServiceInfoCallback failed", exc)
            api34Callbacks.remove(key)
        }
    }

    @RequiresApi(Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
    private fun unregisterApi34Resolver(key: String) {
        val cb = api34Callbacks.remove(key) as? NsdManager.ServiceInfoCallback ?: return
        try {
            nsdManager.unregisterServiceInfoCallback(cb)
        } catch (_: Exception) {
        }
    }

    @Suppress("DEPRECATION")
    private suspend fun resolveLegacySequentially(serviceInfo: NsdServiceInfo) {
        val resolved = suspendCancellableCoroutine<NsdServiceInfo?> { cont ->
            try {
                nsdManager.resolveService(
                    serviceInfo,
                    object : NsdManager.ResolveListener {
                        override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                            if (cont.isActive) cont.resume(null)
                        }

                        override fun onServiceResolved(info: NsdServiceInfo) {
                            if (cont.isActive) cont.resume(info)
                        }
                    },
                )
            } catch (_: Exception) {
                if (cont.isActive) cont.resume(null)
            }
        } ?: return

        val hostAddr = resolved.host?.hostAddress?.takeIf { !it.startsWith("127.") } ?: return
        val port = resolved.port.takeIf { it > 0 } ?: 8765
        val displayName = resolved.attributes["host"]?.decodeToString()
            ?.takeIf { it.isNotBlank() }
            ?: resolved.serviceName.removePrefix("QuickDrop-")

        endpointsByKey[resolved.serviceName] = ServerEndpoint(
            name = displayName,
            host = hostAddr,
            port = port,
        )
        emitServers()
    }

    private fun emitServers() {
        _servers.value = endpointsByKey.values.sortedBy { it.name.lowercase() }
    }

    private fun acquireMulticastLock() {
        try {
            if (multicastLock == null) {
                multicastLock = wifiManager.createMulticastLock("QuickDropMdnsLock").apply {
                    setReferenceCounted(false)
                }
            }
            if (multicastLock?.isHeld == false) {
                multicastLock?.acquire()
            }
        } catch (exc: Exception) {
            Log.w(TAG, "Unable to acquire MulticastLock", exc)
        }
    }

    private fun releaseMulticastLock() {
        try {
            if (multicastLock?.isHeld == true) {
                multicastLock?.release()
            }
        } catch (_: Exception) {
        }
    }

    companion object {
        private const val TAG = "QuickDropNsd"
        private const val SERVICE_TYPE = "_quickdrop._tcp."
    }
}
