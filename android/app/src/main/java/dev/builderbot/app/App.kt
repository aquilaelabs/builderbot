// The application: the notification channels, made once, and the watch
// started when the account is known.
package dev.builderbot.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        // Two channels, so a person can silence the watch's own persistent
        // note without silencing the questions that wait on them.
        nm.createNotificationChannel(NotificationChannel(CH_WATCH, "Watching the dashboard",
            NotificationManager.IMPORTANCE_MIN).apply { description = "The connection to your BuilderBot" })
        nm.createNotificationChannel(NotificationChannel(CH_ASK, "Needs your answer",
            NotificationManager.IMPORTANCE_HIGH).apply {
            description = "A session asking for your phone, or for a root command on a node" })
        nm.createNotificationChannel(NotificationChannel(CH_NOTE, "Attention",
            NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Changes waiting for approval, and nodes that need an update" })
        WatchService.startIfWanted(this)
    }

    companion object {
        const val CH_WATCH = "watch"
        const val CH_ASK = "ask"
        const val CH_NOTE = "note"
    }
}

// The watch comes back after a reboot, the way the dashboard's bell is
// there after a page load.
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) WatchService.startIfWanted(context)
    }
}
