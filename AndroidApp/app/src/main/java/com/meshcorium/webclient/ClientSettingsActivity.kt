package com.peg4tron.meshcorium

import android.content.Intent
import android.os.Bundle
import com.peg4tron.meshcorium.BuildConfig
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.appbar.MaterialToolbar

class ClientSettingsActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        android.util.Log.d("ClientSettingsActivity", "onCreate")
        setContentView(R.layout.activity_client_settings)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.clientSettingsRoot)) { view, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(
                systemBars.left,
                systemBars.top,
                systemBars.right,
                0
            )
            insets
        }

        findViewById<MaterialToolbar>(R.id.toolbar).setNavigationOnClickListener { finish() }

        updateConnectionSummary()

        findViewById<android.view.View>(R.id.connectionSettingsRow).setOnClickListener {
            openConnectionEditor()
        }

        // Set client version
        val versionText = "Версия ${BuildConfig.VERSION_NAME} (build ${BuildConfig.VERSION_CODE})"
        findViewById<android.widget.TextView>(R.id.clientVersion).text = versionText

        // GitHub link
        findViewById<android.widget.TextView>(R.id.githubLink).setOnClickListener {
            val intent = android.content.Intent(android.content.Intent.ACTION_VIEW).apply {
                data = android.net.Uri.parse("https://github.com/PEG4TRON/MeshCorium")
            }
            startActivity(intent)
        }
    }

    override fun onResume() {
        super.onResume()
        updateConnectionSummary()
    }

    private fun updateConnectionSummary() {
        val url = AppPrefs.getBaseUrl(this)
        findViewById<TextView>(R.id.connectionSettingsValue).text = url.ifBlank { "Не настроено" }
    }

    private val connectionSettingsLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == RESULT_OK) {
                val updatedUrl = result.data
                    ?.getStringExtra(UrlEntryActivity.EXTRA_UPDATED_URL)
                    .orEmpty()
                setResult(RESULT_OK, Intent().putExtra(UrlEntryActivity.EXTRA_UPDATED_URL, updatedUrl))
                finish()
            }
        }

    private fun openConnectionEditor() {
        connectionSettingsLauncher.launch(
            Intent(this, UrlEntryActivity::class.java).apply {
                putExtra(UrlEntryActivity.EXTRA_FORCE_EDIT, true)
                putExtra(UrlEntryActivity.EXTRA_RETURN_RESULT, true)
            },
        )
    }
}
