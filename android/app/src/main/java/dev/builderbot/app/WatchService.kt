// The watch: what the dashboard's bell shows, as notifications. The app
// asks /api/status and /api/phone and posts what is new: a session asking
// for the phone or for root, with Approve and Deny on the notification
// itself; a notebook holding a session's changes; a session of the
// account's own coming free to take a message, timed by its project's
// During-a-test-run setting; a node whose agent is
// behind or out of window, or whose Claude Code is behind. No push service:
// the dashboard is on somebody's own network, reached directly or over a
// tailnet, and asking it from here is what needs nobody's account and no
// key in the repository.
//
// Not a foreground service any more (23 Sep). Android hangs a persistent
// notification on one, and that note put a dot on the app's icon that read
// as something needing attention when nothing did. Instead the app asks on
// its own clock while it is open, and an inexact alarm asks about once a
// minute while it is not, delivered to WatchReceiver with no service and
// nothing in the shade between questions. Doze can hold an alarm back for
// some minutes on a phone left alone; a question that cannot wait is one
// the dashboard's bell also carries.
package dev.builderbot.app

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.runBlocking
import org.json.JSONObject

object Watch {
    const val ID_PENDING = 2
    const val ID_ATTENTION = 3
    const val ID_TURN_BASE = 5000
    const val ID_ASK_BASE = 1000
    // In the background, no oftener than this: an inexact alarm is batched
    // by the system anyway, and a phone in a pocket is not a dashboard tab.
    const val BACKGROUND_MIN_S = 60L

    /** One round: ask, and post what is new. Called from the open app on
     *  its own clock and from the alarm's receiver in the background. */
    suspend fun tick(context: Context, api: Api, store: Store) {
        val nm = context.getSystemService(NotificationManager::class.java)
        val ph = api.phone()
        val asks = ph.arr("asks")
        val seen = store.notifiedAsks.toMutableSet()
        val live = asks.map { it.int("id").toString() }.toSet()
        for (a in asks) {
            val id = a.int("id")
            if (id.toString() in seen) continue
            nm.notify(ID_ASK_BASE + id, askNotification(context, a))
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
            else nm.notify(ID_PENDING, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle("Waiting for your approval")
                .setContentText(waiting.joinToString("; ") { "${it.int("pending")} in ${it.str("name")}" })
                .setContentIntent(openApp(context, "approvals"))
                .setAutoCancel(true)
                .build())
            store.lastPending = pendKey
        }
        // A turn finished: a session of the account's own that was busy at
        // the last look and can take a message now. Told once, on the
        // change; a session already waiting when the watch first looks is
        // not news. What "busy" is follows the project's During-a-test-run
        // setting (the operator, 30 Sep): where a new ask cuts into a run
        // (restart), a session that put its tests in the background and
        // handed the turn back can be interrupted, so it is waiting; where a
        // new ask waits for the run (wait), the note waits for the run too,
        // and comes when the tests finish. The run itself is what `bb test`
        // reports to the dashboard (the project's `testing`).
        val prefix = st.str("tmux_prefix")
        val own = st.arr("projects").mapNotNull { p ->
            val want = prefix + ("claude-" + p.str("name")).replace(Regex("[.:]"), "_")
            st.arr("sessions").firstOrNull { it.str("name") == want }?.let { Triple(p, it.obj("claude"), p.optJSONObject("testing")) }
        }
        val busy = own.filter { (p, claude, testing) ->
            claude.str("state") == "working" || (testing != null && p.obj("prefs").str("test_change") != "restart")
        }.map { it.first.str("name") }.toSet()
        for ((p, claude, testing) in own) {
            val project = p.str("name")
            val note = ID_TURN_BASE + (project.hashCode() and 0xfff)
            if (project in busy) { nm.cancel(note); continue }
            if (project !in store.lastWorking || !store.turns) continue
            val task = claude.str("task").ifBlank { "it finished what it was on" }
            val text = if (testing != null) "tests are running, and a new ask cuts into them: $task"
                       else if (p.obj("prefs").str("test_change") != "restart" && wasTesting(store, project)) "its tests finished: $task"
                       else task
            nm.notify(note, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle("$project: Claude is waiting on you")
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setContentIntent(openApp(context, "project/$project"))
                .setAutoCancel(true)
                .build())
        }
        store.lastWorking = busy
        store.lastTesting = own.filter { it.third != null }.map { it.first.str("name") }.toSet()
        // Nodes that need attention: an agent behind or out of window, or
        // Claude Code behind what is out.
        val att = st.arr("attention")
        // The server names the projects on the node as a list (B275).
        val attKey = att.joinToString(",") { "${it.str("kind")}:${it.str("id")}${it.strs("projects").joinToString("+")}:${it.str("to")}" }
        if (attKey != store.lastAttention) {
            if (att.isEmpty()) nm.cancel(ID_ATTENTION)
            else {
                val red = att.any { it.bool("window") }
                nm.notify(ID_ATTENTION, NotificationCompat.Builder(context, App.CH_NOTE)
                    .setSmallIcon(R.drawable.ic_stat_bb)
                    .setContentTitle(if (red) "Work is stopped on a node" else "A node needs attention")
                    .setContentText(att.joinToString("; ") { attentionLine(it) })
                    .setStyle(NotificationCompat.BigTextStyle().bigText(att.joinToString("\n") { attentionLine(it) }))
                    .setContentIntent(openApp(context, "nodes"))
                    .setAutoCancel(true)
                    .build())
            }
            store.lastAttention = attKey
        }
    }

    /** Whether a project's tests were running at the last look: what the
     *  note says when a session under "wait" comes free. */
    private fun wasTesting(store: Store, project: String) = project in store.lastTesting

    /** The password changed, or the account went: asking on would be a
     *  refused request every minute for good, and the person would never
     *  learn why the questions stopped arriving. */
    fun signedOut(context: Context) {
        context.getSystemService(NotificationManager::class.java).notify(ID_ATTENTION,
            NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle("BuilderBot no longer accepts this sign-in")
                .setContentText("Open the app and sign in again; the watch has stopped until you do")
                .setContentIntent(openApp(context, "more"))
                .setAutoCancel(true)
                .build())
        stop(context)
    }

    private fun askNotification(context: Context, a: JSONObject): Notification {
        val id = a.int("id")
        val kind = a.str("kind")
        val who = a.str("asker").ifBlank { a.str("project").ifBlank { "a session" } }
        val text = "${a.str("why")}\n${askCommand(a)}\n$who's session in ${a.str("project")}"
        return NotificationCompat.Builder(context, App.CH_ASK)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle(askTitle(a) + ": needs your answer")
            .setContentText(a.str("why"))
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setColor(if (kind == "root") 0xFFE5534B.toInt() else 0xFFD29922.toInt())
            .setContentIntent(openApp(context, "approvals"))
            // Root on a node is not granted from a locked phone (B272): the
            // actions need the device unlocked, and the lock screen shows
            // that an answer is wanted, not the command.
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(NotificationCompat.Builder(context, App.CH_ASK)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle("A session needs your answer")
                .setContentText("Unlock to see what it asks")
                .build())
            .addAction(NotificationCompat.Action.Builder(0, "Deny", DecideReceiver.intent(context, id, false))
                .setAuthenticationRequired(true).build())
            .addAction(NotificationCompat.Action.Builder(0, "Approve", DecideReceiver.intent(context, id, true))
                .setAuthenticationRequired(true).build())
            .setAutoCancel(true)
            .build()
    }

    /** The background half: the next alarm, from now. Idempotent, so the
     *  app's start, a reboot and every receiver round all call it. */
    fun startIfWanted(context: Context) {
        val store = Store(context)
        if (!store.signedIn || !store.watch) { stop(context); return }
        val every = maxOf(store.pollSeconds.toLong(), BACKGROUND_MIN_S) * 1000
        val am = context.getSystemService(AlarmManager::class.java)
        // Inexact, and allowed while idle: no permission to ask for, and
        // the system batches it with the phone's other work.
        am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
            SystemClock.elapsedRealtime() + every, alarm(context))
    }

    fun stop(context: Context) {
        context.getSystemService(AlarmManager::class.java).cancel(alarm(context))
    }

    private fun alarm(context: Context): PendingIntent =
        PendingIntent.getBroadcast(context, 7, Intent(context, WatchReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    fun openApp(context: Context, screen: String = ""): PendingIntent {
        val i = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            if (screen.isNotEmpty()) putExtra("screen", screen)
        }
        return PendingIntent.getActivity(context, screen.hashCode(), i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    // The two kinds the server sends: a node whose agent is behind (red
    // when out of window, where work is stopped), and one whose Claude Code
    // is behind what is out (claudecode.py, 23 Sep). The bell says the same.
    fun attentionLine(a: JSONObject): String = when (a.str("kind")) {
        "claude" -> "${a.str("node")} runs Claude Code ${a.str("from")}; ${a.str("to")} is out"
        else -> "${a.str("node")} runs agent ${a.str("from")}; the controller ships ${a.str("to")}" +
            (if (a.bool("window")) " (out of window, work there is stopped)" else "")
    }

    // What an ask is, in the words the dashboard's bell uses for the same
    // four kinds: the phone, root on a node, a rebuild of a dev instance,
    // and a container to be made. Shared with the Approvals screen so the
    // notification and the row agree.
    fun askTitle(a: JSONObject): String = when (a.str("kind")) {
        "root" -> "Root on ${a.str("node_name")}"
        "rebuild" -> "Rebuild in ${a.str("project").ifBlank { "a project" }}"
        "container" -> "Container ${a.str("name")} on ${a.str("node_name").ifBlank { "the default node" }}"
        else -> "The phone on ${a.str("node_name")}"
    }
    fun askCommand(a: JSONObject): String = when (a.str("kind")) {
        "root" -> "# "
        "rebuild", "container" -> "bb "
        else -> "adb "
    } + a.strs("cmd").joinToString(" ")
}

// The alarm's other end: one round, then the next alarm. goAsync keeps the
// process alive for the two requests; a dashboard that does not answer is
// one missed round, not a stopped watch.
class WatchReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val store = Store(context)
        val api = store.api()
        if (api == null || !store.watch) { Watch.stop(context); return }
        val pending = goAsync()
        Thread {
            try {
                runBlocking { Watch.tick(context, api, store) }
                Watch.startIfWanted(context)
            } catch (e: ApiError) {
                if (e.status == 401 || e.status == 403) Watch.signedOut(context)
                else Watch.startIfWanted(context)
            } catch (e: Exception) {
                Watch.startIfWanted(context)
            } finally {
                pending.finish()
            }
        }.start()
    }
}

// Approve or Deny from the notification: one POST, the note cleared, and a
// short note of the answer, and the person never had to open the app.
class DecideReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra("id", 0)
        val allow = intent.getBooleanExtra("allow", false)
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.cancel(Watch.ID_ASK_BASE + id)
        val api = Store(context).api() ?: return
        val pending = goAsync()
        Thread {
            val said = try {
                runBlocking { api.decide(id, allow) }
                if (allow) "Allowed: the node is running it" else "Denied"
            } catch (e: Exception) {
                "Could not answer: ${e.message}"
            }
            nm.notify(Watch.ID_ASK_BASE + id, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(said)
                .setContentIntent(Watch.openApp(context, "approvals"))
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
