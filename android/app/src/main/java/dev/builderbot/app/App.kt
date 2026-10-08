// The application: the notification channels, made once, and the watch's
// alarm set when the account is known.
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
        // The watch's own persistent note is gone (23 Sep: it put a dot on
        // the icon that read as something needing attention); its channel
        // goes with it on a phone that had the older app.
        nm.deleteNotificationChannel(CH_WATCH)
        nm.createNotificationChannel(NotificationChannel(CH_ASK, "Needs your answer",
            NotificationManager.IMPORTANCE_HIGH).apply {
            description = "A session asking for your phone, or for a root command on a node" })
        nm.createNotificationChannel(NotificationChannel(CH_NOTE, "Attention",
            NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Changes waiting for approval, a session finishing its turn, and nodes that need an update" })
        // While it lasts (the operator, 4 Oct): your phone lent, a session
        // allowed. Quiet and no dot on the icon, which is what the watch's
        // old persistent note was taken out for.
        nm.createNotificationChannel(NotificationChannel(CH_HELD, "While it lasts",
            NotificationManager.IMPORTANCE_LOW).apply {
            description = "Your phone lent to a project, or a session allowed to drive it; tap to end it"
            setShowBadge(false) })
        // The live connection's own note, which Android requires while it
        // runs: as quiet as a note can be.
        nm.createNotificationChannel(NotificationChannel(CH_LIVE, "Hearing asks at once",
            NotificationManager.IMPORTANCE_MIN).apply {
            description = "Shown while the app keeps a connection open so a question reaches you in seconds"
            setShowBadge(false) })
        Watch.startIfWanted(this)
        Live.startIfWanted(this)
    }

    companion object {
        const val CH_WATCH = "watch"
        const val CH_ASK = "ask"
        const val CH_NOTE = "note"
        const val CH_HELD = "held"
        const val CH_LIVE = "live"
    }
}

// The watch comes back after a reboot, the way the dashboard's bell is
// there after a page load.
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED){ Watch.startIfWanted(context); Live.startIfWanted(context) }
    }
}
