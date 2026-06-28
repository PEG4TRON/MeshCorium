package com.peg4tron.meshcorium

import android.content.Context
import android.os.Build
import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

object PushRegistrar {
    private const val TAG = "PushRegistrar"
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()

    fun registerCurrentDevice(
        context: Context,
        baseUrlOverride: String? = null,
        refreshedToken: String? = null,
    ) {
        val baseUrl = AppPrefs.normalizeBaseUrl(baseUrlOverride ?: AppPrefs.getBaseUrl(context))
        if (baseUrl.isBlank()) {
            return
        }
        if (!refreshedToken.isNullOrBlank()) {
            postRegister(context, baseUrl, refreshedToken)
            return
        }
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (!task.isSuccessful) {
                Log.w(TAG, "failed to obtain FCM token", task.exception)
                return@addOnCompleteListener
            }
            val token = task.result.orEmpty()
            if (token.isBlank()) {
                return@addOnCompleteListener
            }
            postRegister(context, baseUrl, token)
        }
    }

    fun unregisterCurrentDevice(
        context: Context,
        baseUrlOverride: String? = null,
    ) {
        val baseUrl = AppPrefs.normalizeBaseUrl(baseUrlOverride ?: AppPrefs.getBaseUrl(context))
        if (baseUrl.isBlank()) {
            return
        }
        executor.execute {
            runCatching {
                postJson(
                    "$baseUrl/api/mobile-push/unregister",
                    JSONObject()
                        .put("installation_id", AppPrefs.getInstallationId(context))
                        .toString(),
                )
            }.onFailure { error ->
                Log.w(TAG, "failed to unregister device", error)
            }
        }
    }

    private fun postRegister(
        context: Context,
        baseUrl: String,
        token: String,
    ) {
        executor.execute {
            runCatching {
                val payload = JSONObject()
                    .put("installation_id", AppPrefs.getInstallationId(context))
                    .put("fcm_token", token)
                    .put("base_url", baseUrl)
                    .put("device_label", buildDeviceLabel())
                    .put("app_version", BuildConfig.VERSION_NAME)
                    .put("notifications_enabled", true)
                    .put("muted_regular_keys", JSONArray(AppPrefs.getMutedRegularKeys(context)))
                    .put("muted_all_keys", JSONArray(AppPrefs.getMutedAllKeys(context)))
                postJson("$baseUrl/api/mobile-push/register", payload.toString())
            }.onFailure { error ->
                Log.w(TAG, "failed to register device for push", error)
            }
        }
    }

    private fun postJson(url: String, payload: String) {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15000
            readTimeout = 15000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        try {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(payload)
            }
            val code = connection.responseCode
            if (code !in 200..299) {
                throw IllegalStateException("HTTP $code while calling $url")
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun buildDeviceLabel(): String {
        val manufacturer = Build.MANUFACTURER.orEmpty().trim()
        val model = Build.MODEL.orEmpty().trim()
        return listOf(manufacturer, model)
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .ifBlank { "Android" }
    }
}
