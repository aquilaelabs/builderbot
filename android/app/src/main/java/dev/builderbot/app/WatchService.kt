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
    const val ID_INVITES = 4
    const val ID_TURN_BASE = 5000
    const val ID_ASK_BASE = 1000
    const val ID_ONGOING_BASE = 20000
    // In the background, no oftener than this: an inexact alarm is batched
    // by the system anyway, and a phone in a pocket is not a dashboard tab.
    const val BACKGROUND_MIN_S = 60L

    /** One round: ask, and post what is new. Called from the open app on
     *  its own clock and from the alarm's receiver in the background. */
    suspend fun tick(context: Context, api: Api, store: Store, p: Pairing) {
        val nm = context.getSystemService(NotificationManager::class.java)
        val mem = store.memory(p.id)
        // Each pairing's notes in a slot of ids of its own (R132), and
        // named for it once there is more than one.
        val base = slotBase(p)
        val from = if (store.pairings.size > 1) "${p.label}: " else ""
        val ph = api.phone()
        val asks = ph.arr("asks")
        val seen = mem.notifiedAsks.toMutableSet()
        val live = asks.map { it.int("id").toString() }.toSet()
        for (a in asks) {
            val id = a.int("id")
            if (id.toString() in seen) continue
            nm.notify(base + ID_ASK_BASE + id, askNotification(context, a, p, from))
            seen.add(id.toString())
        }
        // An ask that was answered elsewhere, or expired, leaves the shade.
        for (gone in seen - live) {
            gone.toIntOrNull()?.let { nm.cancel(base + ID_ASK_BASE + it) }
        }
        mem.notifiedAsks = seen.intersect(live)

        // What stays on while it lasts (the operator, 4 Oct): your phone lent
        // to a project, and a session allowed to drive it without asking.
        // Tapping either ends it: the lend taken back and adb disconnected,
        // or the session asking every time again.
        val up = mutableSetOf<String>()
        for (n in ph.arr("nodes")) {
            if (!n.bool("mine")) continue
            val node = n.str("id")
            val lease = n.optJSONObject("lease")
            if (lease != null && lease.str("project").isNotBlank()) {
                val key = "${p.id}|lend|$node"
                up.add(key)
                nm.notify(base + ongoingId(key), ongoingNote(context, key,
                    from + "Your phone is lent to ${lease.str("project")}",
                    "Tap to take it back and disconnect adb on ${n.str("name")}",
                    EndReceiver.intent(context, p, key, "lend", node)))
            }
            for (g in n.arr("trust")) {
                val key = "${p.id}|trust|$node|${g.str("project")}|${g.str("asker_uid")}"
                up.add(key)
                nm.notify(base + ongoingId(key), ongoingNote(context, key,
                    from + "${g.str("asker").ifBlank { "A" }}'s sessions in ${g.str("project")} drive your phone",
                    "Allowed for the session, without asking. Tap to be asked every time again",
                    EndReceiver.intent(context, p, key, "trust", node, g.str("project"), g.str("asker_uid"))))
            }
        }
        for (gone in mem.ongoing - up) nm.cancel(base + ongoingId(gone))
        mem.ongoing = up

        val st = api.status()
        // Changes a session has waiting, per project: one note naming them all.
        val waiting = st.arr("projects").filter { it.int("pending") > 0 }
        val pendKey = waiting.joinToString(",") { "${it.str("name")}:${it.int("pending")}" }
        if (pendKey != mem.lastPending) {
            if (waiting.isEmpty()) nm.cancel(base + ID_PENDING)
            else nm.notify(base + ID_PENDING, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(from + "Waiting for your approval")
                .setContentText(waiting.joinToString("; ") { "${it.int("pending")} in ${it.str("label").ifBlank { it.str("name") }}" })
                .setContentIntent(openApp(context, "approvals"))
                .setAutoCancel(true)
                .build())
            mem.lastPending = pendKey
        }
        // An invitation to a project, or a project offered to this account:
        // Accept and Decline are on the Approvals screen, as in the bell.
        val invites = st.arr("invites")
        val invKey = invites.joinToString(",") { it.str("id") }
        if (invKey != mem.lastInvites) {
            if (invites.isEmpty()) nm.cancel(base + ID_INVITES)
            else nm.notify(base + ID_INVITES, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(from + (if (invites.size == 1) inviteLine(invites[0]) else "${invites.size} invitations to projects"))
                .setContentText("Accept or Decline on Approvals")
                .setContentIntent(openApp(context, "approvals"))
                .setAutoCancel(true)
                .build())
            mem.lastInvites = invKey
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
        // Any agent's session of the account's own (R128), the first running
        // per project as the page reads it; which agent is named on the note.
        val prefix = st.str("tmux_prefix")
        val names = st.arr("sessions").associateBy { it.str("name") }
        val agentOf = mutableMapOf<String, String>()
        val own = st.arr("projects").mapNotNull { p ->
            Agents.runningOn(prefix, p.str("name"), names.keys).firstOrNull()?.let { (a, name) ->
                agentOf[p.str("name")] = a.name
                Triple(p, names.getValue(name).obj("claude"), p.optJSONObject("testing"))
            }
        }
        val busy = own.filter { (p, claude, testing) ->
            claude.str("state") == "working" || (testing != null && p.obj("prefs").str("test_change") != "restart")
        }.map { it.first.str("name") }.toSet()
        for ((p, claude, testing) in own) {
            val project = p.str("name")
            val note = base + ID_TURN_BASE + (project.hashCode() and 0xfff)
            if (project in busy) { nm.cancel(note); continue }
            if (project !in mem.lastWorking || !store.turns) continue
            val task = claude.str("task").ifBlank { "it finished what it was on" }
            val text = if (testing != null) "tests are running, and a new ask cuts into them: $task"
                       else if (p.obj("prefs").str("test_change") != "restart" && wasTesting(mem, project)) "its tests finished: $task"
                       else task
            nm.notify(note, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(from + "${p.str("label").ifBlank { project }}: ${agentOf[project] ?: "Claude"} is waiting on you")
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setContentIntent(openApp(context, "project/$project"))
                .setAutoCancel(true)
                .build())
        }
        mem.lastWorking = busy
        mem.lastTesting = own.filter { it.third != null }.map { it.first.str("name") }.toSet()
        // Nodes that need attention: an agent behind or out of window, or
        // toolchains behind what is out, Claude Code among them.
        val att = st.arr("attention")
        // The server names the projects on the node as a list (B275).
        val attKey = att.joinToString(",") { "${it.str("kind")}:${it.str("id")}${it.strs("projects").joinToString("+")}:${it.str("to")}${
            it.arr("tools").joinToString("+") { t -> t.str("name") + "@" + t.str("to") }}" }
        if (attKey != mem.lastAttention) {
            if (att.isEmpty()) nm.cancel(base + ID_ATTENTION)
            else {
                val red = att.any { it.bool("window") }
                nm.notify(base + ID_ATTENTION, NotificationCompat.Builder(context, App.CH_NOTE)
                    .setSmallIcon(R.drawable.ic_stat_bb)
                    .setContentTitle(from + (if (red) "Work is stopped on a node" else "A node needs attention"))
                    .setContentText(att.joinToString("; ") { attentionLine(it) })
                    .setStyle(NotificationCompat.BigTextStyle().bigText(att.joinToString("\n") { attentionLine(it) }))
                    .setContentIntent(openApp(context, "nodes"))
                    .setAutoCancel(true)
                    .build())
            }
            mem.lastAttention = attKey
        }
    }

    /** Whether a project's tests were running at the last look: what the
     *  note says when a session under "wait" comes free. */
    private fun wasTesting(mem: Store.Memory, project: String) = project in mem.lastTesting

    /** The password changed, or the account went: asking on would be a
     *  refused request every minute for good, and the person would never
     *  learn why the questions stopped arriving. That pairing is forgotten
     *  and said; the others go on, and the watch stops only with the last. */
    fun signedOut(context: Context, p: Pairing) {
        val store = Store(context)
        store.forget(p.id)
        context.getSystemService(NotificationManager::class.java).notify(slotBase(p) + ID_ATTENTION,
            NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle("${p.label} no longer accepts this sign-in")
                .setContentText("Open the app and sign in to it again" +
                    (if (store.signedIn) "" else "; the watch has stopped until you do"))
                .setContentIntent(openApp(context, "more"))
                .setAutoCancel(true)
                .build())
        if (!store.signedIn) { stop(context); Live.stop(context) }
    }

    /** One round over every pairing (R132). A refused sign-in forgets that
     *  pairing; anything else is one missed round for it. */
    suspend fun tickAll(context: Context, store: Store) {
        for (p in store.pairings) {
            try { tick(context, store.api(p), store, p) }
            catch (e: ApiError) { if (e.status == 401 || e.status == 403) signedOut(context, p) }
            catch (e: Exception) { /* a missed round; the next one asks again */ }
        }
    }

    /** Where a pairing's notification ids start: a million apart, so two
     *  dashboards' asks with the same number are two notes. */
    fun slotBase(p: Pairing) = p.slot * 1_000_000

    fun ongoingId(key: String) = ID_ONGOING_BASE + (key.hashCode() and 0xffff)

    private fun ongoingNote(context: Context, key: String, title: String, text: String,
                            end: PendingIntent): Notification =
        NotificationCompat.Builder(context, App.CH_HELD)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setColor(0xFFD29922.toInt())
            .setContentIntent(end)
            .addAction(NotificationCompat.Action.Builder(0,
                if (key.contains("|lend|")) "Take back" else "Ask every time", end)
                .setAuthenticationRequired(true).build())
            .build()

    private fun askNotification(context: Context, a: JSONObject, p: Pairing, from: String): Notification {
        val id = a.int("id")
        val kind = a.str("kind")
        val who = a.str("asker").ifBlank { a.str("project").ifBlank { "a session" } }
        val text = "${a.str("why")}\n${askCommand(a)}\n$who's session in ${a.str("project")}"
        return NotificationCompat.Builder(context, App.CH_ASK)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle(from + askTitle(a) + ": needs your answer")
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
            .addAction(NotificationCompat.Action.Builder(0, "Deny", DecideReceiver.intent(context, p, id, false))
                .setAuthenticationRequired(true).build())
            .apply {
                // The rest of this session's phone commands without asking.
                if (kind == "phone" || kind == "phone-use")
                    addAction(NotificationCompat.Action.Builder(0, "This session",
                        DecideReceiver.intent(context, p, id, true, session = true))
                        .setAuthenticationRequired(true).build())
            }
            .addAction(NotificationCompat.Action.Builder(0, "Approve", DecideReceiver.intent(context, p, id, true))
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

    // Each kind the bell draws (page-bell.js attRow), in one line: a node
    // whose agent is behind (red when out of window, where work is
    // stopped), toolchains and coding agents behind what is out, a release
    // that cannot be signed, a node short of room, a container or nginx
    // update, a session the update held, a copy that did not happen and a
    // sign-in read by something else. A kind this build does not know is
    // said by its kind and node, never as an agent's version sentence.
    fun attentionLine(a: JSONObject): String = when (a.str("kind")) {
        // Toolchains behind what is out on a node (API 9), and the coding
        // agents' own (R95, the Agents page's): one line per node.
        "toolchain", "agents" -> "${a.str("node")}: " + a.arr("tools").joinToString(", ") {
            "${it.str("label")} ${it.str("from").ifBlank { "?" }} → ${it.str("to").let { v -> if (v == "newer") "a newer version" else v }}" } +
            (if (a.str("kind") == "agents" && a.arr("tools").any { it.str("name") == "claude-code" } && a.optInt("sessions") > 0)
                 " (updating Claude Code ends the ${a.optInt("sessions")} Claude session${if (a.optInt("sessions") == 1) "" else "s"} there)" else "")
        "release-sign" -> if (a.bool("bad")) "${a.str("tag")}'s APK in ${a.str("project")} is not signed: ${a.str("why")}"
                          else "${a.str("project")}'s next release cannot be signed: ${a.str("why")}"
        "room" -> "${a.str("node")} is running short of room: " + (a.arr("short").map {
                if (it.has("used_pct") && !it.isNull("used_pct")) "${it.str("what")} has been ${it.optInt("used_pct")}% used for ten minutes"
                else "${it.str("what")} has ${it.str("free_gb")} GB free of ${it.str("total_gb")} GB" } +
            (if (a.has("mem") && !a.isNull("mem")) listOf("its memory has been ${a.optInt("mem")}% used for ten minutes") else emptyList()))
            .joinToString("; ")
        "image" -> "${a.arr("containers").size} container update${if (a.arr("containers").size == 1) "" else "s"} on ${a.str("node")}"
        "nginx" -> "nginx update on ${a.str("node")}"
        "held" -> "A session in ${a.str("project")} stopped for the update"
        "relocate" -> "Copying or moving ${a.str("name")} did not happen: ${a.str("why")}"
        "token-read" -> "A sign-in on ${a.str("node")} was read: treat it as copied and end it at the provider"
        "agent", "" -> "${a.str("node")} runs agent ${a.str("from")}; the controller ships ${a.str("to")}" +
            (if (a.bool("window")) " (out of window, work there is stopped)" else "")
        else -> "The dashboard's bell has a ${a.str("kind").replace('-', ' ')} notice" +
            a.str("node").ifBlank { a.str("project") }.let { if (it.isBlank()) "" else " for $it" }
    }

    // What an ask is, in the words the dashboard's bell uses for the same
    // four kinds: the phone, root on a node, a rebuild of a dev instance,
    // and a container to be made. Shared with the Approvals screen so the
    // notification and the row agree.
    fun inviteLine(i: JSONObject): String =
        if (i.str("kind") == "owner") "${i.str("by").ifBlank { "Somebody" }} offers you ${i.str("project")}"
        else "${i.str("by").ifBlank { "Somebody" }} invited you to ${i.str("project")}"

    fun askTitle(a: JSONObject): String = when (a.str("kind")) {
        "root" -> "Root on ${a.str("node_name")}"
        "rebuild" -> "Rebuild in ${a.str("project").ifBlank { "a project" }}"
        "container" -> "Container ${a.str("name")} on ${a.str("node_name").ifBlank { "the default node" }}"
        // Signing (R106): asked of the project's owner.
        "sign" -> "Sign a build of ${a.str("project").ifBlank { "a project" }}"
        "sign-key" -> "A signing key change in ${a.str("project").ifBlank { "a project" }}"
        "release" -> "Release ${a.str("project").ifBlank { "a project" }} ${a.str("tag")}"
        "release-edit" -> "Edit the ${a.str("tag")} release of ${a.str("project").ifBlank { "a project" }}"
        "release-remove" -> "Remove files from the ${a.str("tag")} release of ${a.str("project").ifBlank { "a project" }}"
        "release-sign" -> "Sign the release APKs of ${a.str("project").ifBlank { "a project" }} again"
        // A VM a session asks to make, start or remove (R91), under its
        // project's Make VMs setting.
        "vm" -> "A VM in ${a.str("project").ifBlank { "a project" }}"
        else -> "The phone on ${a.str("node_name")}"
    }
    fun askCommand(a: JSONObject): String = when (a.str("kind")) {
        "root" -> "# "
        "rebuild", "container", "sign", "sign-key", "release", "release-edit", "release-remove", "release-sign", "vm" -> "bb "
        else -> "adb "
    } + a.strs("cmd").joinToString(" ")
}

// The alarm's other end: one round, then the next alarm. goAsync keeps the
// process alive for the two requests; a dashboard that does not answer is
// one missed round, not a stopped watch.
class WatchReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val store = Store(context)
        if (!store.signedIn || !store.watch) { Watch.stop(context); return }
        val pending = goAsync()
        Thread {
            try {
                runBlocking { Watch.tickAll(context, store) }
            } finally {
                Watch.startIfWanted(context)
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
        val session = intent.getBooleanExtra("session", false)
        val store = Store(context)
        val p = store.pairing(intent.getStringExtra("pairing") ?: "") ?: return
        val base = Watch.slotBase(p)
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.cancel(base + Watch.ID_ASK_BASE + id)
        val api = store.api(p)
        val pending = goAsync()
        Thread {
            val said = try {
                runBlocking { api.decide(id, allow, session) }
                if (session) "Allowed for this session" else if (allow) "Allowed: the node is running it" else "Denied"
            } catch (e: Exception) {
                "Could not answer: ${e.message}"
            }
            nm.notify(base + Watch.ID_ASK_BASE + id, NotificationCompat.Builder(context, App.CH_NOTE)
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
        fun intent(context: Context, p: Pairing, id: Int, allow: Boolean, session: Boolean = false): PendingIntent {
            val i = Intent(context, DecideReceiver::class.java).apply {
                putExtra("id", id); putExtra("allow", allow); putExtra("session", session); putExtra("pairing", p.id)
            }
            return PendingIntent.getBroadcast(context, (Watch.slotBase(p) + id) * 3 + (if (session) 2 else if (allow) 1 else 0), i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
    }
}

// Ending what an ongoing note stands for, from the note: a lent phone taken
// back and its adb disconnected, or a session allowed asking every time
// again. One POST or two, the note gone, and a short note of the answer.
class EndReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val key = intent.getStringExtra("key") ?: return
        val what = intent.getStringExtra("what") ?: return
        val node = intent.getStringExtra("node") ?: return
        val nm = context.getSystemService(NotificationManager::class.java)
        val store = Store(context)
        val p = store.pairing(intent.getStringExtra("pairing") ?: "") ?: return
        val api = store.api(p)
        val pending = goAsync()
        Thread {
            val said = try {
                runBlocking {
                    if (what == "lend") {
                        api.phoneTakeBack(node)
                        api.phoneDisconnect(node)
                    } else {
                        api.phoneUntrust(node, intent.getStringExtra("project") ?: "",
                                         intent.getStringExtra("asker") ?: "")
                    }
                }
                nm.cancel(Watch.slotBase(p) + Watch.ongoingId(key))
                store.memory(p.id).let { it.ongoing = it.ongoing - key }
                if (what == "lend") "Taken back, and adb disconnected" else "Asking every time again"
            } catch (e: Exception) {
                "Could not end it: ${e.message}"
            }
            nm.notify(Watch.slotBase(p) + Watch.ongoingId(key) + 1, NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(said)
                .setContentIntent(Watch.openApp(context))
                .setAutoCancel(true)
                .setTimeoutAfter(20_000)
                .build())
            pending.finish()
        }.start()
    }

    companion object {
        fun intent(context: Context, p: Pairing, key: String, what: String, node: String,
                   project: String = "", asker: String = ""): PendingIntent {
            val i = Intent(context, EndReceiver::class.java).apply {
                putExtra("key", key); putExtra("what", what); putExtra("node", node)
                putExtra("project", project); putExtra("asker", asker); putExtra("pairing", p.id)
            }
            return PendingIntent.getBroadcast(context, Watch.slotBase(p) + Watch.ongoingId(key), i,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
    }
}
