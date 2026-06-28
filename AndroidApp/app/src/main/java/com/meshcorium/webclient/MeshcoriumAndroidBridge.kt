package com.peg4tron.meshcorium

import android.content.Context
import android.webkit.JavascriptInterface

class MeshcoriumAndroidBridge(
    private val context: Context,
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
}
