// A project's coding agents, from the phone (R128): the dashboard's Manage
// agent chooser in the shape a phone takes. For the node the project runs
// on (a picker where it runs on several), one row per agent installed there:
// Claude, ChatGPT (Codex CLI) and Copilot. A running session of yours says
// what it is doing and offers Open, Restart (Claude's, as the page has it)
// and End; one not running offers Resume and New, which turn to the model
// and effort it starts on; a node you have not signed in to that agent on
// says so, since a sign-in is each node's own and is made on the dashboard's
// Agents page.
//
// Open and Start are the session's terminal, the dashboard's own page in a
// WebView (TerminalPane): a session starts when its terminal is first
// attached, and closing the pane leaves it running, as closing the browser
// does. End is the one that stops it.
package dev.builderbot.app.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import dev.builderbot.app.Agent
import dev.builderbot.app.Agents
import dev.builderbot.app.Api
import dev.builderbot.app.arr
import dev.builderbot.app.bool
import dev.builderbot.app.obj
import dev.builderbot.app.str
import dev.builderbot.app.strs
import kotlinx.coroutines.launch
import org.json.JSONObject

// ---- reading the status --------------------------------------------------------

/** This account's own sessions on a project, any live agent's, Claude's
 *  first: (agent, the status's session row). A project on several nodes
 *  may have one per node, each its own row. */
fun ownSessions(status: JSONObject?, project: String): List<Pair<Agent, JSONObject>> {
    if (status == null) return emptyList()
    val rows = status.arr("sessions")
    return Agents.ownNames(status.str("tmux_prefix"), project).flatMap { (a, name) ->
        rows.filter { it.str("name") == name }.map { a to it }
    }
}

/** The one a message or a pill is about: the first running (names.running_session). */
fun ownSession(status: JSONObject?, project: String) = ownSessions(status, project).firstOrNull()

/** What a session is doing, as the pill and the row say it. Every agent's
 *  row carries its state under `claude`, the stored name for any agent's. */
fun sessionWord(row: JSONObject) = if (row.obj("claude").str("state") == "working") "working" else "waiting on you"

/** How this account stands with an agent on a node: {email, plan} or the
 *  like when signed in, null when not (the page's agentOn). A place with
 *  no node (id "") has no sign-in of a node's to ask about. */
fun signedAs(status: JSONObject?, agent: String, node: String): JSONObject? {
    if (node.isBlank()) return JSONObject()
    val rec = if (agent == "claude") status?.obj("claude_auth")?.obj("nodes")
              else status?.obj("agent_auth")?.obj(agent)?.obj("nodes")
    return rec?.optJSONObject(node)
}

/** The sign-in in words: who, and on what plan where the provider says. */
private fun signedWords(rec: JSONObject): String =
    listOf(rec.str("email").ifBlank { rec.str("login").ifBlank { rec.str("account") } }, rec.str("plan"))
        .filter { it.isNotBlank() }.joinToString(", ").let { if (it.isBlank()) "signed in" else "signed in as $it" }

/** Why a lock holds this account out, as the page words it (lockedWhy). */
fun lockedWhy(p: JSONObject) = if (p.bool("locked_admin"))
    "locked by an administrator: nobody starts a session or changes it until one unlocks it"
    else "locked by ${p.str("owner_name").ifBlank { "its owner" }}, its owner: only they work in it until they unlock it"

/** The places a session of this project could run, as the chooser draws
 *  them (claudeNodes): its several nodes, its one, or this machine where a
 *  session runs here (id ""). None where there is nowhere, and
 *  session_why says so. */
private fun placesOf(p: JSONObject): List<JSONObject> {
    val several = p.arr("session_nodes")
    if (several.size > 1) return several
    val id = p.str("session_node")
    if (id.isNotBlank()) return listOf(several.firstOrNull { it.str("id") == id }
        ?: JSONObject().put("id", id).put("name", p.str("session_at")).put("where", "node"))
    return if (p.str("session_why").isBlank()) listOf(JSONObject().put("id", "").put("name", "").put("where", "node")) else emptyList()
}

/** Why no session may start here, or "" (the page's claudeDeadWhy). */
private fun deadWhy(p: JSONObject, running: Boolean): String = when {
    p.bool("locked_me") -> lockedWhy(p)
    p.has("mine") && !p.bool("mine", true) -> "read-only: you hold no role on this project; its owner or an administrator gives you one to work on it"
    p.str("write_why").isNotBlank() -> p.str("write_why")
    p.str("held").isNotBlank() -> p.str("held")
    p.str("session_at").isBlank() && p.str("session_why").isNotBlank() && !running -> p.str("session_why")
    p.bool("node_removed") && !running -> p.str("session_why").ifBlank { "its node was removed: pick another in its settings" }
    else -> ""
}

private fun ago(at: Long): String {
    val d = maxOf(0L, System.currentTimeMillis() / 1000 - at)
    return when {
        d < 90 -> "just now"
        d < 5400 -> "${Math.round(d / 60.0)} min ago"
        d < 172800 -> "${Math.round(d / 3600.0)} h ago"
        else -> "${Math.round(d / 86400.0)} days ago"
    }
}

// ---- the view ------------------------------------------------------------------

/** What a press turned to: the model and effort step for one agent, a
 *  conversation to resume (or none), and whether it is a restart. */
private data class Pick(val agent: Agent, val resume: String, val node: String, val restart: JSONObject? = null)

@Composable
fun AgentView(api: Api, project: String, status: JSONObject?, reloadStatus: () -> Unit,
              openTerm: (arg: String, label: String) -> Unit) {
    val scope = rememberCoroutineScope()
    val p = status?.arr("projects")?.firstOrNull { it.str("name") == project }
    val mine = ownSessions(status, project)
    val (tr, reload) = load("transcripts-$project") { api.transcripts(project) }
    val rows = tr.value?.arr("rows") ?: emptyList()
    var nodeId by remember(project) { mutableStateOf<String?>(null) }
    var pick by remember(project) { mutableStateOf<Pick?>(null) }
    var briefFor by remember(project) { mutableStateOf<Pick?>(null) }
    var ending by remember(project) { mutableStateOf<Pair<Agent, JSONObject>?>(null) }
    var said by remember(project) { mutableStateOf("") }
    val label = p?.str("label")?.ifBlank { null } ?: project

    pick?.let { pk -> StartStep(api, project, p, pk, onCancel = { pick = null }) { arg ->
        pick = null; reloadStatus()
        openTerm(arg, "${pk.agent.name}: $label")
    } }
    briefFor?.let { pk -> BriefStep(api, project, pk.agent, onCancel = { briefFor = null }) {
        briefFor = null; pick = pk
    } }
    ending?.let { (a, row) ->
        AlertDialog(onDismissRequest = { ending = null },
            title = { Text("End your ${a.name} session on $label?") },
            text = { Text("The conversation stops now. Its transcript is kept and can be resumed later.") },
            confirmButton = { Button(onClick = {
                ending = null
                scope.launch {
                    said = try {
                        val r = api.endSession(row.str("name"), row.str("node_id"))
                        r.str("error").ifBlank { "ended your ${a.name} session on $label" }
                    } catch (e: Exception) { e.message ?: "it did not end" }
                    reloadStatus()
                }
            }) { Text("End") } },
            dismissButton = { TextButton(onClick = { ending = null }) { Text("Cancel") } })
    }

    Column(Modifier.fillMaxSize()) {
    // What each session of yours is doing, and the box to say something to
    // it, above the list: these move with every look at the status.
    for ((a, row) in mine) SayBox(api, row, a.name, onSaid = { reloadStatus(); reload() })
    Pull(tr.value == null && tr.error == null, { reload(); reloadStatus() }) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 4.dp)) {
                if (p == null && status != null) Dim("this project is not in the dashboard's list for you")
                if (p != null) {
                    val places = placesOf(p)
                    val several = places.size > 1
                    val runsOn = { n: JSONObject -> mine.any { (_, s) -> n.str("id").isBlank() || s.str("node_id") == n.str("id") } }
                    val n = places.firstOrNull { it.str("id") == nodeId }
                        ?: places.firstOrNull(runsOn) ?: places.firstOrNull { it.str("id") == p.str("session_node") } ?: places.firstOrNull()
                    val dead = deadWhy(p, mine.isNotEmpty())
                    if (several) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (x in places) FilterChip(selected = x.str("id") == n?.str("id"), onClick = { nodeId = x.str("id") },
                            label = { Text(x.str("name") + if (runsOn(x)) " · yours running" else "") })
                    } else if (n != null && n.str("name").isNotBlank()) Dim("on ${n.str("name")}")
                    if (n == null) Text(p.str("session_why").ifBlank { "nowhere for a session to run" }, color = Warn)
                    else if (n.str("where").ifBlank { "node" } != "node") Text(n.str("why"), color = Warn)
                    else {
                        if (dead.isNotBlank()) Text(dead, color = Warn, modifier = Modifier.padding(vertical = 4.dp))
                        val offered = Agents.offered(n.strs("agents"), p.obj("prefs").strs("agents_off"),
                                                     p.obj("prefs").str("agent_default").ifBlank { "claude" })
                        val at = if (several) n.str("id") else ""
                        for (a in offered) {
                            val run = mine.firstOrNull { (x, s) -> x.id == a.id && (n.str("id").isBlank() || s.str("node_id") == n.str("id")) }?.second
                            val last = if (a.id == "claude") p.optJSONObject("last_claude") else p.obj("last_agents").optJSONObject(a.id)
                            AgentRow(a, run, signed = signedAs(status, a.id, n.str("id")), nodeName = n.str("name"),
                                     last = last, dead = dead.isNotBlank(),
                                     onOpen = { openTerm(Agents.termArg(a.id, project, node = at), "${a.name}: $label") },
                                     onRestart = { pick = Pick(a, last?.str("id") ?: "", at, restart = run) },
                                     onEnd = { ending = a to run!! },
                                     onResume = { pick = Pick(a, last?.str("id") ?: "", at) },
                                     onNew = { if (p.bool("brief") && run == null) briefFor = Pick(a, "", at) else pick = Pick(a, "", at) })
                        }
                    }
                }
                if (said.isNotBlank()) Text(said, color = Note, modifier = Modifier.padding(top = 4.dp))
            }
            SectionHead("Conversations")
            Column(Modifier.padding(horizontal = 16.dp)) {
                if (tr.error != null) Problem(tr.error)
                if (tr.value != null && rows.isEmpty()) Dim("none of yours on this project yet")
            }
        }
        items(rows) { r -> LogRow(api, r, showProject = false) }
    }
    }
    }
}

/** One agent's line, as the chooser draws it: its name and how you stand
 *  on it at the left, its presses under it. */
@Composable
private fun AgentRow(a: Agent, run: JSONObject?, signed: JSONObject?, nodeName: String, last: JSONObject?, dead: Boolean,
                     onOpen: () -> Unit, onRestart: () -> Unit, onEnd: () -> Unit, onResume: () -> Unit, onNew: () -> Unit) {
    Panel(Modifier.fillMaxWidth().padding(vertical = 4.dp), bar = if (run != null) Ok else null) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(a.name, fontWeight = FontWeight.SemiBold, color = Ink)
            Spacer(Modifier.width(8.dp))
            Text(when {
                    run != null -> sessionWord(run)
                    signed == null -> "not signed in on ${nodeName.ifBlank { "this node" }}"
                    else -> a.product
                 }, color = if (run != null) (if (sessionWord(run) == "working") Warn else Ok) else if (signed == null) Warn else Dim,
                 style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        // Each agent's sign-in, as the Agents page says it (R95 step 3).
        if (signed != null && signed.length() > 0) Text(signedWords(signed), color = Dim, style = MaterialTheme.typography.bodySmall,
                                                         maxLines = 1, overflow = TextOverflow.Ellipsis)
        val task = run?.obj("claude")?.str("task") ?: ""
        if (task.isNotBlank()) Text(task, color = Dim, style = MaterialTheme.typography.bodySmall, maxLines = 2,
                                    overflow = TextOverflow.Ellipsis)
        Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            when {
                run != null -> {
                    Button(onClick = onOpen) { Text("Open") }
                    // Restart is Claude's, as on the page: it resumes the same
                    // conversation, which is how a session sees what changed.
                    if (a.id == "claude") OutlinedButton(onClick = onRestart) { Text("Restart") }
                    OutlinedButton(onClick = onEnd) { Text("End", color = Bad) }
                }
                signed == null -> Dim("its sign-in is made on the dashboard's Agents page, for that node")
                dead -> {}
                else -> {
                    if (last != null && last.str("id").isNotBlank())
                        OutlinedButton(onClick = onResume) { Text("Resume ${ago(last.optLong("when"))}") }
                    OutlinedButton(onClick = onNew) { Text("New") }
                }
            }
        }
    }
}

/** The menu's second step: the model and effort the session starts on,
 *  opening on the last ones picked, and Start (or Restart, which ends the
 *  running one first and waits for it to go). Saved as this account's own
 *  for the project, as the page saves them; another agent's ride the
 *  terminal's argument too. Hands back the argument to open. */
@Composable
private fun StartStep(api: Api, project: String, p: JSONObject?, pk: Pick, onCancel: () -> Unit, onStart: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    val a = pk.agent
    val yours = p?.obj("yours") ?: JSONObject()
    var model by remember(pk) { mutableStateOf(yours.str(a.modelKey)) }
    var effort by remember(pk) { mutableStateOf(yours.str(a.effortKey)) }
    var busy by remember(pk) { mutableStateOf(false) }
    var said by remember(pk) { mutableStateOf("") }
    AlertDialog(onDismissRequest = { if (!busy) onCancel() },
        title = { Text(when {
            pk.restart != null -> "Restart your ${a.name} session"
            pk.resume.isNotBlank() -> "Resume the ${a.name} conversation"
            else -> "A new ${a.name} conversation" }) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (pk.restart != null) Dim("It ends now and resumes the same conversation, starting fresh so it sees what changed since it started.")
                Text("Model", fontWeight = FontWeight.SemiBold)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (v in listOf("") + a.models)
                        FilterChip(selected = model == v, onClick = { model = v }, label = { Text(v.ifBlank { "${a.name}'s default" }) })
                }
                Spacer(Modifier.height(6.dp))
                Text("Effort", fontWeight = FontWeight.SemiBold)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (v in listOf("") + a.efforts)
                        FilterChip(selected = effort == v, onClick = { effort = v }, label = { Text(v.ifBlank { "default" }) })
                }
                if (said.isNotBlank()) Text(said, color = Bad, modifier = Modifier.padding(top = 6.dp))
            }
        },
        confirmButton = { Button(enabled = !busy, onClick = {
            busy = true; said = ""
            scope.launch {
                said = try {
                    if (model != yours.str(a.modelKey) || effort != yours.str(a.effortKey)) {
                        val r = api.prefs(project, mapOf(a.modelKey to model, a.effortKey to effort))
                        if (r.str("error").isNotBlank()) throw Exception(r.str("error"))
                    }
                    pk.restart?.let { run ->
                        val r = api.endSession(run.str("name"), run.str("node_id"))
                        if (r.str("error").isNotBlank()) throw Exception(r.str("error"))
                        // Started while the old one was still going down, the
                        // new terminal attached to the dying session and showed
                        // it end (the page's restartNow).
                        var gone = false
                        for (i in 0 until 40) {
                            kotlinx.coroutines.delay(500)
                            gone = api.status().arr("sessions").none { it.str("name") == run.str("name") && it.str("node_id") == run.str("node_id") }
                            if (gone) break
                        }
                        if (!gone) throw Exception("your session is still going down; press Restart again in a moment")
                    }
                    onStart(Agents.termArg(a.id, project, pk.resume, model, effort, pk.node))
                    ""
                } catch (e: Exception) { e.message ?: "it did not start" }
                busy = false
            }
        }) { Text(if (busy) (if (pk.restart != null) "Restarting" else "Starting") else if (pk.restart != null) "Restart" else "Start") } },
        dismissButton = { TextButton(enabled = !busy, onClick = onCancel) { Text("Back") } })
}

/** A new project's first session goes through its brief (brief.py): the
 *  brief it was made with, editable, then Build it (staged as the
 *  session's first prompt) or Start without it (set aside). Either way the
 *  model and effort step follows. */
@Composable
private fun BriefStep(api: Api, project: String, a: Agent, onCancel: () -> Unit, onDone: () -> Unit) {
    val scope = rememberCoroutineScope()
    var text by remember(project) { mutableStateOf<String?>(null) }
    var said by remember(project) { mutableStateOf("") }
    var busy by remember(project) { mutableStateOf(false) }
    LaunchedEffect(project) {
        text = try { api.brief(project).let { if (it.str("error").isNotBlank()) { said = it.str("error"); "" } else it.str("text") } }
               catch (e: Exception) { said = "could not read the brief: ${e.message}"; "" }
    }
    fun go(action: String) {
        busy = true; said = ""
        scope.launch {
            said = try {
                val r = api.briefAct(project, action, if (action == "stage") text.orEmpty().trim() else "")
                r.str("error")
            } catch (e: Exception) { e.message ?: "it did not go" }
            busy = false
            if (said.isBlank()) onDone()
        }
    }
    AlertDialog(onDismissRequest = { if (!busy) onCancel() },
        title = { Text("First ${a.name} session on $project") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Dim("Build it hands the session this brief as its first prompt; Start without it puts the brief away. Either way it leaves the project's tree, and its notebook keeps it.")
                if (text == null) Loading()
                else OutlinedTextField(text!!, { text = it }, label = { Text("The brief") },
                                       modifier = Modifier.fillMaxWidth(), minLines = 4, maxLines = 12)
                if (said.isNotBlank()) Text(said, color = Bad)
            }
        },
        confirmButton = { Button(enabled = !busy && text != null, onClick = {
            if (text.orEmpty().isBlank()) said = "the brief is empty: Start without it starts a session with no brief" else go("stage")
        }) { Text("Build it") } },
        dismissButton = { Row {
            TextButton(enabled = !busy, onClick = onCancel) { Text("Back") }
            TextButton(enabled = !busy && text != null, onClick = { go("aside") }) { Text("Start without it") }
        } })
}

// ---- a session's terminal -------------------------------------------------------

/** The dashboard's terminal page for one argument, in a WebView signed in
 *  as the account (Api.webCookie). Attaching it is what starts a session
 *  that is not running; Close detaches and leaves it running. */
@Composable
fun TerminalPane(api: Api, arg: String, label: String, onClose: () -> Unit) {
    androidx.activity.compose.BackHandler { onClose() }
    var url by remember(arg) { mutableStateOf<String?>(null) }
    var said by remember(arg) { mutableStateOf("") }
    LaunchedEffect(arg) {
        try {
            val cookie = api.webCookie()
            val cm = android.webkit.CookieManager.getInstance()
            cm.setAcceptCookie(true)
            cm.setCookie(api.base.trimEnd('/'), "bb_session=$cookie; Path=/")
            cm.flush()
            url = api.termUrl(arg)
        } catch (e: Exception) { said = e.message ?: "the terminal did not open" }
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp, 8.dp, 8.dp, 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = Ink,
                 modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            TextButton(onClick = onClose) { Text("Close") }
        }
        Column(Modifier.padding(horizontal = 16.dp)) {
            Dim("Close leaves the session running; End, on the project's Agent view, stops it.")
            if (said.isNotBlank()) Problem(said)
        }
        val u = url
        if (u == null && said.isBlank()) Loading()
        if (u != null) AndroidView(
            factory = { ctx ->
                android.webkit.WebView(ctx).apply {
                    // The terminal is the dashboard's own page, and xterm is script.
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    webViewClient = android.webkit.WebViewClient()
                    loadUrl(u)
                }
            },
            onRelease = { it.destroy() },
            modifier = Modifier.fillMaxWidth().weight(1f).padding(top = 4.dp))
    }
}
