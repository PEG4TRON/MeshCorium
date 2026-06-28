package com.peg4tron.meshcorium

import android.content.Intent
import android.os.Bundle
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.appbar.MaterialToolbar

class ClientSettingsActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        android.util.Log.d("ClientSettingsActivity", "onCreate")
        setContentView(R.layout.activity_client_settings)

        findViewById<MaterialToolbar>(R.id.toolbar).setNavigationOnClickListener { finish() }

        updateConnectionSummary()

        findViewById<android.view.View>(R.id.connectionSettingsRow).setOnClickListener {
            openConnectionEditor()
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
