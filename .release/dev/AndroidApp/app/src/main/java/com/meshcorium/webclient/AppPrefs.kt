package com.peg4tron.meshcorium

import android.content.Context
import org.json.JSONObject
import java.util.UUID

object AppPrefs {
    private const val PREFS_NAME = "meshcorium_android_web_client"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_LAST_WEB_URL = "last_web_url"
    private const val KEY_INSTALLATION_ID = "installation_id"
    private const val KEY_MUTED_CONVERSATIONS_JSON = "muted_conversations_json"

    fun getBaseUrl(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_BASE_URL, "").orEmpty()
    }

    fun setBaseUrl(context: Context, url: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val normalized = normalizeBaseUrl(url)
        val currentLastWebUrl = prefs.getString(KEY_LAST_WEB_URL, "").orEmpty()
        prefs.edit()
            .putString(KEY_BASE_URL, normalized)
            .apply()
        if (!currentLastWebUrl.startsWith(normalized)) {
            clearLastWebUrl(context)
        }
    }

    fun getLastWebUrl(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_LAST_WEB_URL, "").orEmpty()
    }

    fun setLastWebUrl(context: Context, url: String) {
        val normalizedBaseUrl = normalizeBaseUrl(getBaseUrl(context))
        val normalizedUrl = url.trim()
        if (normalizedBaseUrl.isBlank() || normalizedUrl.isBlank() || !normalizedUrl.startsWith(normalizedBaseUrl)) {
            return
        }
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_LAST_WEB_URL, normalizedUrl).apply()
    }

    fun clearLastWebUrl(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().remove(KEY_LAST_WEB_URL).apply()
    }

    fun getInstallationId(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_INSTALLATION_ID, "").orEmpty().trim()
        if (existing.isNotEmpty()) {
            return existing
        }
        val created = UUID.randomUUID().toString()
        prefs.edit().putString(KEY_INSTALLATION_ID, created).apply()
        return created
    }

    fun setMutedConversationsJson(context: Context, rawJson: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_MUTED_CONVERSATIONS_JSON, normalizeMutedConversationsJson(rawJson)).apply()
    }

    fun getMutedConversationsJson(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return normalizeMutedConversationsJson(prefs.getString(KEY_MUTED_CONVERSATIONS_JSON, "").orEmpty())
    }

    fun getMutedRegularKeys(context: Context): List<String> {
        val parsed = getMutedConversationsObject(context) ?: return emptyList()
        val result = mutableListOf<String>()
        val iterator = parsed.keys()
        while (iterator.hasNext()) {
            val rawKey = iterator.next()
            val key = rawKey.orEmpty().trim().lowercase()
            val mode = parsed.optString(rawKey).trim().lowercase()
            if (key.isNotBlank() && (mode == "regular" || mode == "all")) {
                result += key
            }
        }
        return result.distinct()
    }

    fun getMutedAllKeys(context: Context): List<String> {
        val parsed = getMutedConversationsObject(context) ?: return emptyList()
        val result = mutableListOf<String>()
        val iterator = parsed.keys()
        while (iterator.hasNext()) {
            val rawKey = iterator.next()
            val key = rawKey.orEmpty().trim().lowercase()
            val mode = parsed.optString(rawKey).trim().lowercase()
            if (key.isNotBlank() && mode == "all") {
                result += key
            }
        }
        return result.distinct()
    }

    fun normalizeBaseUrl(raw: String): String {
        val trimmed = raw.trim().removeSuffix("/")
        return trimmed
    }

    private fun getMutedConversationsObject(context: Context): JSONObject? {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val raw = prefs.getString(KEY_MUTED_CONVERSATIONS_JSON, "").orEmpty()
        return runCatching { JSONObject(raw) }.getOrNull()
    }

    private fun normalizeMutedConversationsJson(rawJson: String): String {
        val parsed = runCatching { JSONObject(rawJson) }.getOrNull() ?: return "{}"
        val normalized = JSONObject()
        val iterator = parsed.keys()
        while (iterator.hasNext()) {
            val rawKey = iterator.next()
            val key = rawKey.orEmpty().trim().lowercase()
            val mode = parsed.optString(rawKey).trim().lowercase()
            if (key.isBlank()) {
                continue
            }
            if (mode == "regular" || mode == "all") {
                normalized.put(key, mode)
            }
        }
        return normalized.toString()
    }
}
