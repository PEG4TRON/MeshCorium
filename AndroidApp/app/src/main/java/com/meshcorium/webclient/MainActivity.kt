package com.peg4tron.meshcorium

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import com.peg4tron.meshcorium.databinding.ActivityMainBinding
import org.json.JSONObject

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

    private var pendingNativeAction: String? = null
    private var suppressDockSelectionCallback = false
    private var suppressNextSettingsClick = false
    private var webPageReady = false

    companion object {
        private const val STATE_WEBVIEW = "webview_state"
    }

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (!granted) {
                Toast.makeText(this, R.string.notification_permission_denied, Toast.LENGTH_SHORT).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val baseUrl = AppPrefs.getBaseUrl(this)
        if (baseUrl.isBlank()) {
            openServerEntry()
            return
        }
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        configureEdgeToEdge()
        applyWindowInsets()
        configureWebView(binding.webView)
        val restored = savedInstanceState
            ?.getBundle(STATE_WEBVIEW)
            ?.let { binding.webView.restoreState(it) }
            ?: null
        if (restored == null) {
            loadBaseUrl(forceReload = false)
        }
        requestNotificationPermissionIfNeeded()
        PushRegistrar.registerCurrentDevice(this)
        onBackPressedDispatcher.addCallback(this) {
            if (binding.webView.canGoBack()) {
                binding.webView.goBack()
            } else {
                finish()
            }
        }
        configureNativeDock()
    }

    override fun onResume() {
        super.onResume()
        if (::binding.isInitialized) {
            PushRegistrar.registerCurrentDevice(this)
            if (binding.webView.url.isNullOrBlank()) {
                loadBaseUrl(forceReload = false)
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::binding.isInitialized) {
            binding.webView.url?.let { AppPrefs.setLastWebUrl(this, it) }
            outState.putBundle(STATE_WEBVIEW, Bundle().also { bundle ->
                binding.webView.saveState(bundle)
            })
        }
    }

    override fun onPause() {
        if (::binding.isInitialized) {
            binding.webView.url?.let { AppPrefs.setLastWebUrl(this, it) }
        }
        super.onPause()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView(webView: WebView) {
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.databaseEnabled = true
        webView.settings.loadsImagesAutomatically = true
        webView.settings.mediaPlaybackRequiresUserGesture = false
        webView.settings.userAgentString = webView.settings.userAgentString + " MeshcoriumAndroidWebClient/${BuildConfig.VERSION_NAME}"
        webView.addJavascriptInterface(MeshcoriumAndroidBridge(applicationContext, onDockStateChanged = ::applyNativeDockState), "MeshcoriumAndroid")
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val target = request?.url ?: return false
                val configuredBase = android.net.Uri.parse(AppPrefs.getBaseUrl(this@MainActivity))

                val sameOrigin =
                    target.scheme.equals(configuredBase.scheme, ignoreCase = true)
                        && target.host.equals(configuredBase.host, ignoreCase = true)
                        && effectivePort(target) == effectivePort(configuredBase)

                if (sameOrigin) {
                    return false
                }

                startActivity(Intent(Intent.ACTION_VIEW, target))
                return true
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                super.onPageStarted(view, url, favicon)
                webPageReady = false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                webPageReady = true
                pendingNativeAction?.let { action ->
                    pendingNativeAction = null
                    dispatchNativeAction(action)
                }
                super.onPageFinished(view, url)
                url?.let { AppPrefs.setLastWebUrl(this@MainActivity, it) }
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                binding.progressIndicator.progress = newProgress
                binding.progressIndicator.isIndeterminate = false
                binding.progressIndicator.alpha = if (newProgress >= 100) 0f else 1f
            }
        }
    }

    private fun loadBaseUrl(forceReload: Boolean) {
        val baseUrl = AppPrefs.getBaseUrl(this)
        if (baseUrl.isBlank()) {
            openServerEntry()
            return
        }
        val lastWebUrl = AppPrefs.getLastWebUrl(this).trim()
        val targetUrl = if (lastWebUrl.startsWith(baseUrl)) lastWebUrl else baseUrl
        if (forceReload || binding.webView.url.isNullOrBlank()) {
            binding.webView.loadUrl(targetUrl)
        } else if (binding.webView.url != targetUrl) {
            binding.webView.loadUrl(targetUrl)
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            return
        }
        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun configureEdgeToEdge() {
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = false
        }
    }

    private fun applyWindowInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.mainRoot) { view, windowInsets ->
            val systemBars = windowInsets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout(),
            )
            view.updatePadding(
                left = systemBars.left,
                top = systemBars.top,
                right = systemBars.right,
                bottom = systemBars.bottom,
            )
            windowInsets
        }
        ViewCompat.requestApplyInsets(binding.mainRoot)
    }

    private fun openServerEntry(forceEdit: Boolean = false) {
        startActivity(
            Intent(this, UrlEntryActivity::class.java).apply {
                putExtra(UrlEntryActivity.EXTRA_FORCE_EDIT, forceEdit)
            },
        )
        finish()
    }

    private fun applyNativeDockState(payloadJson: String) {
        val payload = runCatching { org.json.JSONObject(payloadJson) }.getOrNull()
            ?: return

        val selectedId = when (payload.optString("active")) {
            "notifications" -> R.id.nav_notifications
            "messages" -> R.id.nav_messages
            "contacts" -> R.id.nav_contacts
            "maps" -> R.id.nav_maps
            "settings" -> R.id.nav_settings
            else -> android.view.View.NO_ID
        }

        if (selectedId != android.view.View.NO_ID) {
            suppressDockSelectionCallback = true
            binding.nativeBottomNavigation.selectedItemId = selectedId
            suppressDockSelectionCallback = false
        }

        val rawBadge = payload.optString("notificationBadge").trim()
        val badge = binding.nativeBottomNavigation
            .getOrCreateBadge(R.id.nav_notifications)

        if (rawBadge.isBlank()) {
            badge.isVisible = false
        } else {
            badge.isVisible = true
            val numeric = rawBadge.toIntOrNull()
            if (numeric != null) {
                badge.number = numeric.coerceAtMost(99)
                badge.maxCharacterCount = 3
            } else {
                badge.clearNumber()
            }
        }
    }

    private fun handleServerConnectionChanged(newBaseUrl: String) {
        val normalized = AppPrefs.normalizeBaseUrl(newBaseUrl)
        if (normalized.isBlank()) {
            // openServerEntry(forceEdit = true) — будет в Этапе 8
            return
        }

        webPageReady = false
        pendingNativeAction = null

        AppPrefs.clearLastWebUrl(this)

        android.webkit.CookieManager.getInstance().removeAllCookies {
            android.webkit.CookieManager.getInstance().flush()
        }

        binding.webView.clearHistory()
        binding.webView.clearCache(false)
        binding.webView.loadUrl(normalized)

        PushRegistrar.registerCurrentDevice(
            context = this,
            baseUrlOverride = normalized,
        )
    }

    private fun configureNativeDock() {
        binding.nativeBottomNavigation.setOnItemSelectedListener { item ->
            if (suppressDockSelectionCallback) {
                return@setOnItemSelectedListener true
            }
            when (item.itemId) {
                R.id.nav_notifications -> {
                    dispatchNativeAction("notifications")
                    true
                }
                R.id.nav_messages -> {
                    dispatchNativeAction("messages")
                    true
                }
                R.id.nav_contacts -> {
                    dispatchNativeAction("contacts")
                    true
                }
                R.id.nav_maps -> {
                    dispatchNativeAction("maps")
                    true
                }
                R.id.nav_settings -> {
                    if (suppressNextSettingsClick) {
                        suppressNextSettingsClick = false
                        return@setOnItemSelectedListener true
                    }
                    dispatchNativeAction("settings")
                    true
                }
                else -> false
            }
        }

        binding.nativeBottomNavigation.post {
            binding.nativeBottomNavigation
                .findViewById<android.view.View>(R.id.nav_settings)
                ?.setOnLongClickListener {
                    openClientSettings()
                    true
                }
        }
    }

    private fun openClientSettings() {
        suppressNextSettingsClick = true
        binding.nativeBottomNavigation.postDelayed({
            suppressNextSettingsClick = false
        }, 500L)
        // TODO: open ClientSettingsActivity (Этап 7)
    }

    private fun dispatchNativeAction(action: String) {
        if (!webPageReady) {
            pendingNativeAction = action
            return
        }
        val quotedAction = org.json.JSONObject.quote(action)
        binding.webView.evaluateJavascript(
            """
            (function () {
                if (typeof window.__meshcoriumNativeAction !== 'function') {
                    return false;
                }
                window.__meshcoriumNativeAction($quotedAction);
                return true;
            })();
            """.trimIndent(),
            null,
        )
    }

    private fun effectivePort(uri: android.net.Uri): Int {
        val port = uri.port
        return if (port != -1) port else if (uri.scheme == "https") 443 else 80
    }
}
