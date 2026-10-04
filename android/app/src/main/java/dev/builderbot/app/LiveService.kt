// Hearing an ask at once (R125, the operator 4 Oct). The watch asks on
// Android's alarm, which an idle phone stretches to nine minutes or more
// against a fifteen-minute window to answer. This keeps one request open
// to the dashboard instead (GET /api/phone/wait), which answers the moment
// this account's phone asks, lease or grants change, and then runs the
// watch's own round, so what is posted and how is the watch's. No push
// service: the phone reaches its BuilderBot directly, as the watch does.
// Android requires a note while it runs; it sits in its own channel at the
// lowest importance, with no dot on the icon.
package dev.builderbot.app

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

object Live {
    const val ID = 7

    fun startIfWanted(context: Context) {
        val store = Store(context)
        if (!store.signedIn || !store.watch || !store.live) { stop(context); return }
        try {
            ContextCompat.startForegroundService(context, Intent(context, LiveService::class.java))
        } catch (e: Exception) {
            // Started from somewhere Android does not allow a foreground
            // service to start: the alarm still runs, and the next time
            // the app is opened this starts.
        }
    }

    fun stop(context: Context) {
        context.stopService(Intent(context, LiveService::class.java))
    }
}

class LiveService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val note = NotificationCompat.Builder(this, App.CH_LIVE)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle("Hearing asks at once")
            .setContentText("A question from a session reaches you in seconds")
            .setOngoing(true)
            .setContentIntent(Watch.openApp(this))
            .build()
        if (Build.VERSION.SDK_INT >= 34)
            startForeground(Live.ID, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING)
        else startForeground(Live.ID, note)
        if (job?.isActive != true) job = scope.launch { listen() }
        return START_STICKY
    }

    private suspend fun listen() {
        var since = ""
        var backoff = 2_000L
        while (scope.isActive) {
            val store = Store(this)
            val api = store.api()
            if (api == null || !store.watch || !store.live) { stopSelf(); return }
            try {
                val tok = api.phoneWait(since).str("token")
                if (tok != since) {
                    // Not on the first answer alone: a round then is what
                    // opening the app does anyway.
                    since = tok
                    Watch.tick(this, api, store)
                }
                backoff = 2_000L
            } catch (e: ApiError) {
                if (e.status == 401 || e.status == 403) { Watch.signedOut(this); stopSelf(); return }
                delay(backoff); backoff = minOf(backoff * 2, 60_000L)
            } catch (e: Exception) {
                // The dashboard out of reach (a restart, no network): wait,
                // longer each time, and try again.
                delay(backoff); backoff = minOf(backoff * 2, 60_000L)
            }
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
