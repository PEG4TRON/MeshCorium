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

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

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
        webView.addJavascriptInterface(MeshcoriumAndroidBridge(applicationContext), "MeshcoriumAndroid")
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val target = request?.url ?: return false
                if (target.scheme == "http" || target.scheme == "https") {
                    return false
                }
                startActivity(Intent(Intent.ACTION_VIEW, target))
                return true
            }

            override fun onPageFinished(view: WebView?, url: String?) {
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
}
