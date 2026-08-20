package com.peg4tron.meshcorium

import android.Manifest
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class MeshcoriumFirebaseMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        PushRegistrar.registerCurrentDevice(applicationContext, refreshedToken = token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        if (MeshcoriumApp.isInForeground) {
            return
        }
        val title = message.data["title"].orEmpty().ifBlank {
            getString(R.string.default_notification_title)
        }
        val body = message.data["body"].orEmpty().ifBlank {
            getString(R.string.default_notification_body)
        }
        showNotification(title, body)
    }

    private fun showNotification(title: String, body: String) {
        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, MeshcoriumApp.MESSAGES_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()
        NotificationManagerCompat.from(this).notify((System.currentTimeMillis() % Int.MAX_VALUE).toInt(), notification)
    }
}
