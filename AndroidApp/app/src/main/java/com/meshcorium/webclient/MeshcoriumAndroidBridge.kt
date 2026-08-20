package com.peg4tron.meshcorium

import android.content.Context
import android.webkit.JavascriptInterface

class MeshcoriumAndroidBridge(
    private val context: Context,
    private val onDockStateChanged: (String) -> Unit,
) {
    @JavascriptInterface
    fun getMutedConversations(): String {
        return AppPrefs.getMutedConversationsJson(context)
    }

    @JavascriptInterface
    fun syncMutedConversations(rawJson: String?) {
        AppPrefs.setMutedConversationsJson(context, rawJson.orEmpty())
        PushRegistrar.registerCurrentDevice(context)
    }

    @JavascriptInterface
    fun updateDockState(payloadJson: String?) {
        val payload = payloadJson.orEmpty()
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            onDockStateChanged(payload)
        }
    }
}
