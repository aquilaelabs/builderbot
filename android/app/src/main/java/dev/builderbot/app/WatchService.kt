// The watch: what the dashboard's bell shows, as notifications. A foreground
// service polls /api/status and /api/phone on a clock and posts what is
// new: a session asking for the phone or for root, with Approve and Deny on
// the notification itself; a notebook holding a session's changes; a node
// whose agent is behind or out of window. No push service: the dashboard is
// on somebody's own network, reached directly or over a tailnet, and a
// persistent connection from the phone is what does not need anybody's
// account or a key in the repository.
package dev.builderbot.app

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.json.JSONObject

class WatchService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val note = NotificationCompat.Builder(this, App.CH_WATCH)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle("Watching BuilderBot")
            .setContentText("Questions for you arrive here")
            .setOngoing(true)
            .setContentIntent(openApp(this))
            .build()
        if (Build.VERSION.SDK_INT >= 29)
            startForeground(ID_WATCH, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(ID_WATCH, note)
        if (loop == null) loop = scope.launch { run() }
        return START_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun run() {
        val store = Store(this)
        var failures = 0
        while (true) {
            val api = store.api()
            if (api == null || !store.watch) { stopSelf(); return }
            try {
                tick(api, store)
                failures = 0
            } catch (e: Exception) {
                failures++
            }
            // Back off while the dashboard is unreachable; a phone that left
            // the network should not spend its battery on connection refusals.
            val wait = store.pollSeconds.toLong() * (if (failures > 3) 4 else 1)
            delay(wait * 1000)
        }
    }

    private suspend fun tick(api: Api, store: Store) {
        val nm = getSystemService(NotificationManager::class.java)
        val ph = api.phone()
        val asks = ph.arr("asks")
        val seen = store.notifiedAsks.toMutableSet()
        val live = asks.map { it.int("id").toString() }.toSet()
        for (a in asks) {
            val id = a.int("id")
            if (id.toString() in seen) continue
            nm.notify(ID_ASK_BASE + id, askNotification(a))
            seen.add(id.toString())
        }
        // An ask that was answered elsewhere, or expired, leaves the shade.
        for (gone in seen - live) {
            gone.toIntOrNull()?.let { nm.cancel(ID_ASK_BASE + it) }
        }
        store.notifiedAsks = seen.intersect(live)

        val st = api.status()
        // Changes a session has waiting, per project: one note naming them all.
        val waiting = st.arr("projects").filter { it.int("pending") > 0 }
        val pendKey = waiting.joinToString(",") { "${it.str("name")}:${it.int("pending")}" }
        if (pendKey != store.lastPending) {
            if (waiting.isEmpty()) nm.cancel(ID_PENDING)
            else nm.notify(ID_PENDING, NotificationCompat.Builder(this, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle("Waiting for your approval")
                .setContentText(waiting.joinToString("; ") { "${it.int("pending")} in ${it.str("name")}" })
                .setContentIntent(openApp(this, "approvals"))
                .setAutoCancel(true)
                .build())
            store.lastPending = pendKey
        }
        // Nodes that need attention, and a CLAUDE.md block out of window.
        val att = st.arr("attention")
        val attKey = att.joinToString(",") { "${it.str("kind")}:${it.str("id")}${it.str("project")}:${it.str("to")}" }
        if (attKey != store.lastAttention) {
            if (att.isEmpty()) nm.cancel(ID_ATTENTION)
            else {
                val red = att.any { it.bool("window") }
                nm.notify(ID_ATTENTION, NotificationCompat.Builder(this, App.CH_NOTE)
                    .setSmallIcon(R.drawable.ic_stat_bb)
                    .setContentTitle(if (red) "Work is stopped on a node" else "A node needs attention")
                    .setContentText(att.joinToString("; ") { attentionLine(it) })
                    .setStyle(NotificationCompat.BigTextStyle().bigText(att.joinToString("\n") { attentionLine(it) }))
                    .setContentIntent(openApp(this, "nodes"))
                    .setAutoCancel(true)
                    .build())
            }
            store.lastAttention = attKey
        }
    }

    private fun askNotification(a: JSONObject): Notification {
        val id = a.int("id")
        val root = a.str("kind") == "root"
        val cmd = (if (root) "# " else "adb ") + a.strs("cmd").joinToString(" ")
        val who = a.str("asker").ifBlank { a.str("project").ifBlank { "a session" } }
        val title = if (root) "Root on ${a.str("node_name")}: needs your answer" else "The phone: needs your answer"
        val text = "${a.str("why")}\n$cmd\n$who's session in ${a.str("project")}"
        return NotificationCompat.Builder(this, App.CH_ASK)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle(title)
            .setContentText(a.str("why"))
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setColor(if (root) 0xFFE5534B.toInt() else 0xFFD29922.toInt())
            .setContentIntent(openApp(this, "approvals"))
            .addAction(0, "Deny", DecideReceiver.intent(this, id, false))
            .addAction(0, "Approve", DecideReceiver.intent(this, id, true))
            .setAutoCancel(true)
            .build()
    }

    companion object {
        const val ID_WATCH = 1
        const val ID_PENDING = 2
        const val ID_ATTENTION = 3
        const val ID_ASK_BASE = 1000

        fun startIfWanted(context: Context) {
            val store = Store(context)
            if (!store.signedIn || !store.watch) return
            val i = Intent(context, WatchService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(i) else context.startService(i)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, WatchService::class.java))
        }

        fun openApp(context: Context, screen: String = ""): PendingIntent {
            val i = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                if (screen.isNotEmpty()) putExtra("screen", screen)
            }
            return PendingIntent.getActivity(context, screen.hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }

        fun attentionLine(a: JSONObject): String = when (a.str("kind")) {
            "md" -> "${a.str("project")}'s CLAUDE.md block is from ${a.str("from")}; this BuilderBot is ${a.str("to")}"
            else -> "${a.str("node")} runs agent ${a.str("from")}; the controller ships ${a.str("to")}" +
                (if (a.bool("window")) " (out of window, work there is stopped)" else "")
        }
    }
}

// Approve or Deny from the notification: one POST, the note cleared, and a
// short note of the answer, and the person never had to open the app.
class DecideReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra("id", 0)
        val allow = intent.getBooleanExtra("allow", false)
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.cancel(WatchService.ID_ASK_BASE + id)
        val api = Store(context).api() ?: return
        val pending = goAsync()
        Thread {
            val said = try {
                runBlocking { api.decide(id, allow) }
                if (allow) "Allowed: the node is running it" else "Denied"
            } catch (e: Exception) {
                "Could not answer: ${e.message}"
            }
            nm.notify(WatchService.ID_ASK_BASE + id, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(said)
                .setContentIntent(WatchService.openApp(context, "approvals"))
                .setAutoCancel(true)
                .setTimeoutAfter(20_000)
                .build())
            pending.finish()
        }.start()
    }

    companion object {
        fun intent(context: Context, id: Int, allow: Boolean): PendingIntent {
            val i = Intent(context, DecideReceiver::class.java).apply {
                putExtra("id", id); putExtra("allow", allow)
            }
            return PendingIntent.getBroadcast(context, id * 2 + (if (allow) 1 else 0), i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
    }
}
