package com.peg4tron.meshcorium

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.util.Patterns
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import com.peg4tron.meshcorium.databinding.ActivityUrlEntryBinding

class UrlEntryActivity : AppCompatActivity() {
    private lateinit var binding: ActivityUrlEntryBinding
    private var returnResult = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val forceEdit = intent.getBooleanExtra(EXTRA_FORCE_EDIT, false)
        returnResult = intent.getBooleanExtra(EXTRA_RETURN_RESULT, false)
        val savedUrl = AppPrefs.getBaseUrl(this)
        if (!forceEdit && savedUrl.isNotBlank()) {
            openMain()
            return
        }
        binding = ActivityUrlEntryBinding.inflate(layoutInflater)
        setContentView(binding.root)
        configureEdgeToEdge()
        applyWindowInsets()
        binding.urlEditText.setText(savedUrl)
        binding.saveButton.setOnClickListener {
            saveAndContinue()
        }
    }

    private fun saveAndContinue() {
        val rawUrl = binding.urlEditText.text?.toString().orEmpty()
        val normalized = AppPrefs.normalizeBaseUrl(rawUrl)
        if (!isValidBaseUrl(normalized)) {
            binding.urlInputLayout.error = getString(R.string.invalid_url)
            return
        }
        binding.urlInputLayout.error = null
        val previousUrl = AppPrefs.getBaseUrl(this)
        AppPrefs.setBaseUrl(this, normalized)
        if (previousUrl.isNotBlank() && previousUrl != normalized) {
            PushRegistrar.unregisterCurrentDevice(this, previousUrl)
        }
        PushRegistrar.registerCurrentDevice(this, baseUrlOverride = normalized)
        if (returnResult) {
            setResult(RESULT_OK, Intent().apply {
                putExtra(EXTRA_PREVIOUS_URL, previousUrl)
                putExtra(EXTRA_UPDATED_URL, normalized)
            })
            finish()
        } else {
            openMain()
        }
    }

    private fun openMain() {
        startActivity(
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            },
        )
        finish()
    }

    private fun isValidBaseUrl(value: String): Boolean {
        if (!Patterns.WEB_URL.matcher(value).matches()) {
            return false
        }
        return value.startsWith("http://") || value.startsWith("https://")
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
        ViewCompat.setOnApplyWindowInsetsListener(binding.urlEntryRoot) { view, windowInsets ->
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
        ViewCompat.requestApplyInsets(binding.urlEntryRoot)
    }

    companion object {
        const val EXTRA_FORCE_EDIT = "force_edit"
        const val EXTRA_RETURN_RESULT = "return_result"
        const val EXTRA_PREVIOUS_URL = "previous_url"
        const val EXTRA_UPDATED_URL = "updated_url"
    }
}
