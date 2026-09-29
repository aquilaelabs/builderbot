// The screens that are not a project: sign-in, the projects list with the
// bell's items above it, the approvals, the nodes, the accounts, the
// profile, and More (about, the watch, and whether this app is behind the
// dashboard it talks to).
package dev.builderbot.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import dev.builderbot.app.Api
import dev.builderbot.app.BuildConfig
import dev.builderbot.app.Store
import dev.builderbot.app.Watch
import dev.builderbot.app.arr
import dev.builderbot.app.bool
import dev.builderbot.app.int
import dev.builderbot.app.obj
import dev.builderbot.app.str
import dev.builderbot.app.strs
import kotlinx.coroutines.launch
import org.json.JSONObject

// ---- small pieces used everywhere -------------------------------------------

@Composable
fun Loading() {
    Row(Modifier.fillMaxWidth().padding(24.dp), horizontalArrangement = Arrangement.Center) {
        CircularProgressIndicator()
    }
}

@Composable
fun Problem(text: String) {
    Text(text, color = Bad, modifier = Modifier.padding(16.dp))
}

@Composable
fun Section(title: String, content: @Composable () -> Unit) {
    Column {
        SectionHead(title)
        Column(Modifier.padding(horizontal = 16.dp)) { content() }
    }
}

@Composable
fun Dim(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = Dim)
}

// A command or a path, in the data voice, set into the panel the way the
// site sets a field: the sunk ground, the corner of a control.
@Composable
fun Mono(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace, color = Ink,
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
            .background(Sunk, RoundedCornerShape(6.dp))
            .padding(8.dp, 6.dp))
}

// One fetch with its outcome, the way every screen loads: null while
// waiting, an error string, or the answer.
class Loaded<T>(val value: T? = null, val error: String? = null)

@Composable
fun <T> load(key: Any?, fetch: suspend () -> T): Pair<Loaded<T>, () -> Unit> {
    var state by remember(key) { mutableStateOf(Loaded<T>()) }
    var tick by remember(key) { mutableStateOf(0) }
    LaunchedEffect(key, tick) {
        state = try { Loaded(fetch()) } catch (e: Exception) { Loaded(error = e.message ?: e.toString()) }
    }
    return state to { tick++ }
}

// Pull down to re-read, on every list: the gesture a phone expects, beside
// the Refresh button each screen keeps for a thumb that is already at the
// top. `reload` is a load()'s second half; the indicator shows while the
// pull is held and goes when the fetch it started has landed.
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun Pull(loading: Boolean, reload: () -> Unit, content: @Composable () -> Unit) {
    var pulled by remember { mutableStateOf(false) }
    if (pulled && !loading) pulled = false
    androidx.compose.material3.pulltorefresh.PullToRefreshBox(
        isRefreshing = pulled && loading,
        onRefresh = { pulled = true; reload() },
        modifier = Modifier.fillMaxSize(),
        content = { content() })
}

// ---- sign in -----------------------------------------------------------------

@Composable
fun LoginScreen(store: Store, onDone: (admin: Boolean) -> Unit) {
    var server by remember { mutableStateOf(store.server.ifBlank { "https://" }) }
    var user by remember { mutableStateOf(store.user) }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text("BuilderBot", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold, color = Ink)
        Dim("Sign in with your dashboard account. The address is the one you open in a browser: on your network, or over your tailnet.")
        Spacer(Modifier.height(16.dp))
        OutlinedTextField(server, { server = it }, label = { Text("Dashboard address") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
        OutlinedTextField(user, { user = it }, label = { Text("Account") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(password, { password = it }, label = { Text("Password") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
        if (error.isNotBlank()) Text(error, color = Bad, modifier = Modifier.padding(vertical = 8.dp))
        Spacer(Modifier.height(12.dp))
        Button(enabled = !busy && server.length > 8 && user.isNotBlank() && password.isNotBlank(), onClick = {
            busy = true; error = ""
            scope.launch {
                try {
                    val api = Api(server, user, password)
                    val st = api.status()
                    if (st.str("me").isBlank()) throw Exception("that address answers, but not as a BuilderBot")
                    store.server = server; store.user = user; store.password = password
                    onDone(st.obj("can").optBoolean("admin", false))
                } catch (e: Exception) {
                    error = e.message ?: e.toString()
                }
                busy = false
            }
        }) { Text(if (busy) "Signing in" else "Sign in") }
        // Said before the sign-in, not after (B273): over http the password
        // travels in the clear on this network, on every poll.
        if (server.trim().startsWith("http://"))
            Text("Over http the sign-in and every poll travel in the clear on this network; use https where the dashboard has it",
                 color = Warn, modifier = Modifier.padding(top = 8.dp))
    }
}

// ---- home: the bell's items, then the projects -------------------------------

@Composable
fun HomeScreen(store: Store, onAdmin: (Boolean) -> Unit, onWaiting: (Int) -> Unit = {}, openProject: (String) -> Unit) {
    val api = store.api() ?: return
    val (st, reload) = load("status") { api.status() }
    val s = st.value
    if (s != null){ onAdmin(s.obj("can").optBoolean("admin", false)); onWaiting(s.int("phone_asks")) }
    var find by rememberSaveable { mutableStateOf("") }
    // The account's own Claude sessions, by project: the name the server
    // gives one is the prefix, then claude- and the project as tmux spells it.
    val prefix = s?.str("tmux_prefix") ?: ""
    val sessions = s?.arr("sessions")?.associateBy { it.str("name") } ?: emptyMap()
    fun sessionOf(project: String) = sessions[prefix + ("claude-$project").replace(Regex("[.:]"), "_")]
    // The projects the account keeps on its sidebar, as the sidebar has
    // them; All shows the rest, and a search looks through every one.
    val every = s?.arr("projects") ?: emptyList()
    val kept = every.filter { it.bool("pinned", true) }
    var all by rememberSaveable { mutableStateOf(false) }
    val shown = if (find.isNotBlank()) every.filter { it.str("name").contains(find.trim(), ignoreCase = true) }
                else if (all || kept.isEmpty()) every else kept
    Pull(st.value == null && st.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Mark(26.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text("BuilderBot", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Ink)
                    if (s != null) Text("${s.str("me")} · ${s.obj("image").str("version").ifBlank { "unstamped" }} on ${s.str("host")}",
                        color = Dim, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = reload) { Text("Refresh") }
            }
        }
        if (st.error != null) item { Problem(st.error) }
        if (s == null && st.error == null) item { Loading() }
        if (s != null) {
            val asks = s.int("phone_asks")
            val att = s.arr("attention")
            if (asks > 0 || att.isNotEmpty()) item {
                // The bell's row: amber for a question, red for stopped work,
                // as a bar down the side rather than colored words.
                Panel(Modifier.fillMaxWidth().padding(16.dp, 4.dp), bar = if (att.any { it.bool("window") }) Bad else Warn) {
                    if (asks > 0) Text("$asks question${if (asks == 1) "" else "s"} waiting for your answer; see Approvals", color = Ink)
                    for (a in att) Text(Watch.attentionLine(a), color = if (a.bool("window")) Bad else Warn)
                }
            }
            // What the doctor found, where it found something: an
            // administrator's, and quiet while every check passes.
            // The two levels the Doctor card counts as problems; a check
            // that was skipped is not one.
            val ill = s.obj("doctor").arr("checks").filter { it.str("level") == "FAIL" || it.str("level") == "warn" }
            if (ill.isNotEmpty() && s.obj("can").optBoolean("admin", false)) item {
                Panel(Modifier.fillMaxWidth().padding(16.dp, 4.dp),
                      bar = if (ill.any { it.str("level") == "FAIL" }) Bad else Warn) {
                    Text("The doctor", color = Ink, fontWeight = FontWeight.SemiBold)
                    for (c in ill) {
                        Text(c.str("text"), color = if (c.str("level") == "FAIL") Bad else Warn)
                        if (c.str("detail").isNotBlank()) Dim(c.str("detail"))
                    }
                }
            }
            item {
                SectionHead("Projects")
                // A box to find one in, once the list is longer than a screen.
                if (every.size > 6) OutlinedTextField(find, { find = it }, label = { Text("Find a project") },
                    singleLine = true, modifier = Modifier.fillMaxWidth().padding(16.dp, 0.dp, 16.dp, 6.dp))
                if (every.isEmpty()) Column(Modifier.padding(horizontal = 16.dp)) {
                    Dim("no project yet: New project on the dashboard makes one") }
                else if (shown.isEmpty()) Column(Modifier.padding(horizontal = 16.dp)) {
                    Dim("no project's name has \u201c${find.trim()}\u201d in it") }
            }
            items(shown, key = { it.str("name") }) { p ->
                // A project's row: a panel wearing the project's color down
                // its side, the way its notebook tab does, its state as pills.
                Panel(Modifier.fillMaxWidth().padding(16.dp, 4.dp).clickable { openProject(p.str("name")) },
                      bar = projectTone(p.obj("prefs").str("color"))) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(p.str("name"), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                             color = Ink, modifier = Modifier.weight(1f))
                        // What the account's own session is doing, which is
                        // the question a phone is picked up to ask: working,
                        // or waiting on the person. Somebody else's session
                        // is a plain Claude.
                        val own = sessionOf(p.str("name"))
                        if (own != null) {
                            val working = own.obj("claude").str("state") == "working"
                            Pill(if (working) "working" else "waiting on you", if (working) Warn else Ok)
                        } else if (p.str("session_at").isNotBlank()) Pill("Claude", Ok)
                        if (p.bool("locked")){ Spacer(Modifier.width(6.dp)); Pill("locked", Warn) }
                    }
                    val bits = mutableListOf<String>()
                    if (p.str("git").isNotBlank()) bits += p.str("git")
                    if (p.int("roadmap") > 0) bits += "${p.int("roadmap")} on the roadmap"
                    if (p.int("bugs") > 0) bits += "${p.int("bugs")} open bug${if (p.int("bugs") == 1) "" else "s"}"
                    if (p.int("pending") > 0) bits += "${p.int("pending")} waiting for approval"
                    Spacer(Modifier.height(2.dp))
                    Dim(bits.joinToString(" · ").ifBlank { "nothing waiting" })
                    val task = sessionOf(p.str("name"))?.obj("claude")?.str("task") ?: ""
                    if (task.isNotBlank()) Text(task, color = Dim, style = MaterialTheme.typography.bodySmall,
                        maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    // What is wrong with the project, where something is:
                    // the lines its row carries on the sidebar.
                    for (i in p.arr("issues").take(3))
                        Text(i.str("text"), color = if (i.str("level") == "error") Bad else Warn,
                             style = MaterialTheme.typography.bodySmall)
                }
            }
            if (find.isBlank() && kept.isNotEmpty() && kept.size < every.size) item {
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
                    TextButton(onClick = { all = !all }) {
                        Text(if (all) "Only the ones on my sidebar" else "All ${every.size} projects") }
                }
            }
            item { Spacer(Modifier.height(12.dp)) }
        }
    }
    }
}

// ---- approvals: the phone and root asks, and what sessions have waiting -----------

@Composable
fun ApprovalsScreen(store: Store) {
    val api = store.api() ?: return
    val scope = rememberCoroutineScope()
    val (ph, reloadPh) = load("phone") { api.phone() }
    val (st, reloadSt) = load("status-appr") { api.status() }
    var said by remember { mutableStateOf("") }
    Pull(ph.value == null && ph.error == null, { reloadPh(); reloadSt() }) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Mark(26.dp)
                Spacer(Modifier.width(10.dp))
                Text("Approvals", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = { reloadPh(); reloadSt() }) { Text("Refresh") }
            }
            if (said.isNotBlank()) Text(said, modifier = Modifier.padding(16.dp, 0.dp), color = Note)
        }
        val asks = ph.value?.arr("asks") ?: emptyList()
        if (ph.error != null) item { Problem(ph.error) }
        item { Section("Waiting for your answer") { if (asks.isEmpty()) Dim("nothing: a session asking for your phone, for root on a node, for a rebuild or for a container appears here") } }
        items(asks) { a ->
            val kind = a.str("kind")
            Panel(Modifier.fillMaxWidth().padding(16.dp, 4.dp), bar = if (kind == "root") Bad else Warn) {
                Column {
                    Text(Watch.askTitle(a), color = Ink, fontWeight = FontWeight.SemiBold)
                    Text(a.str("why"), style = MaterialTheme.typography.bodyLarge)
                    Mono(Watch.askCommand(a))
                    // A container is approved by reading its compose file: that
                    // is the request. The env file is never shown, since that
                    // is where a token would be; its keys are, so the reader
                    // knows what it sets.
                    if (kind == "container") {
                        var open by remember(a.int("id")) { mutableStateOf(false) }
                        TextButton(onClick = { open = !open }) { Text(if (open) "Hide the compose file" else "Read the compose file") }
                        if (open) Mono(a.str("detail"))
                        if (a.strs("env_keys").isNotEmpty()) Dim("and an env file setting " + a.strs("env_keys").joinToString(", "))
                        if (a.str("for").isNotBlank()) Dim("shown under ${a.str("for")}")
                    }
                    Dim("${a.str("asker").ifBlank { "a session" }} in ${a.str("project")} · ${a.int("left") / 60} min left to answer")
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.End) {
                        Spacer(Modifier.weight(1f))
                        OutlinedButton(onClick = { scope.launch { said = answer(api, a.int("id"), false); reloadPh() } }) { Text("Deny") }
                        Spacer(Modifier.width(8.dp))
                        Button(onClick = { scope.launch { said = answer(api, a.int("id"), true); reloadPh() } }) { Text("Allow") }
                    }
                }
            }
        }
        val waiting = st.value?.arr("projects")?.filter { it.int("pending") > 0 } ?: emptyList()
        item { Section("Changes a session has waiting") { if (waiting.isEmpty()) Dim("none: roadmap items, bugs, rules and build settings a session added under an ask gate are listed here") } }
        items(waiting) { p -> PendingBlock(api, p.str("name"), onChanged = reloadSt) }
    }
    }
}

suspend fun answer(api: Api, id: Int, allow: Boolean): String = try {
    api.decide(id, allow); if (allow) "allowed: the node is running it" else "denied"
} catch (e: Exception) { e.message ?: e.toString() }

@Composable
fun PendingBlock(api: Api, project: String, onChanged: () -> Unit) {
    val scope = rememberCoroutineScope()
    val (pd, reload) = load("pending-$project") { api.pending(project) }
    val rows = pd.value?.arr("pending")?.filter { !it.bool("settled") } ?: emptyList()
    Column(Modifier.padding(16.dp, 4.dp)) {
        Text(project, fontWeight = FontWeight.SemiBold)
        for (r in rows) Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("${r.str("kind")}: ${r.str("summary")}")
                Dim("${r.str("verb")} by ${r.str("by")}")
            }
            TextButton(onClick = { scope.launch { runCatching { api.pendingAct(project, false, listOf(r.str("id"))) }; reload(); onChanged() } }) { Text("Deny") }
            TextButton(onClick = { scope.launch { runCatching { api.pendingAct(project, true, listOf(r.str("id"))) }; reload(); onChanged() } }) { Text("Approve") }
        }
    }
}

// ---- nodes ---------------------------------------------------------------------

@Composable
fun NodesScreen(store: Store) {
    val api = store.api() ?: return
    val scope = rememberCoroutineScope()
    val (nd, reload) = load("nodes") { api.nodes() }
    var said by remember { mutableStateOf("") }
    val rows = nd.value?.arr("nodes")?.filter { it.str("kind") != "local" && it.str("state") != "retired" } ?: emptyList()
    Pull(nd.value == null && nd.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Nodes", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = reload) { Text("Refresh") }
            }
            if (said.isNotBlank()) Text(said, modifier = Modifier.padding(16.dp, 0.dp), color = Note)
            if (nd.error != null) Problem(nd.error)
            if (nd.value != null && rows.isEmpty()) Dim("no node is enrolled; the dashboard's Nodes tab mints a token for one")
        }
        items(rows) { n ->
            val rep = n.obj("reported")
            val locked = n.obj("config").bool("lock")
            val live = n.bool("live")
            Panel(Modifier.fillMaxWidth().padding(16.dp, 4.dp), bar = if (live) Ok else Warn) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(n.str("name"), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                             color = Ink, modifier = Modifier.weight(1f))
                        Dot(if (live) Ok else Warn)
                        Text(if (live) "live" else n.str("state"), color = if (live) Ok else Warn, style = MaterialTheme.typography.labelMedium)
                        if (locked){ Spacer(Modifier.width(6.dp)); Pill("locked", Warn) }
                    }
                    Dim(listOf(rep.str("os"), if (rep.int("cpu") > 0) "${rep.int("cpu")} cpu · ${rep.int("mem_mb") / 1024}GB" else "",
                               rep.obj("distro").str("pretty")).filter { it.isNotBlank() }.joinToString(" · "))
                    val dist = rep.obj("distro")
                    if (dist.str("pkg").isNotBlank()) Dim("packages: ${dist.str("pkg")} · network: ${dist.str("network").ifBlank { "none" }} · init: ${dist.str("init")}")
                    Row(Modifier.padding(top = 8.dp)) {
                        OutlinedButton(onClick = { scope.launch { said = act(api, n.str("id"), if (locked) "unlock" else "lock"); reload() } }) {
                            Text(if (locked) "Unlock" else "Lock system changes")
                        }
                        Spacer(Modifier.width(8.dp))
                        OutlinedButton(onClick = { scope.launch { said = act(api, n.str("id"), if (n.str("state") == "draining") "online" else "drain"); reload() } }) {
                            Text(if (n.str("state") == "draining") "Undrain" else "Drain")
                        }
                    }
                }
            }
        }
    }
    }
}

suspend fun act(api: Api, id: String, action: String): String = try {
    api.nodeAct(id, action); "$action: done"
} catch (e: Exception) { e.message ?: e.toString() }

// ---- users (administrators) ------------------------------------------------------

@Composable
fun UsersScreen(store: Store) {
    val api = store.api() ?: return
    val scope = rememberCoroutineScope()
    val (us, reload) = load("users") { api.users() }
    var said by remember { mutableStateOf("") }
    var open by remember { mutableStateOf("") }      // the account being edited
    var adding by remember { mutableStateOf(false) }
    var ask by remember { mutableStateOf("") }       // the account Remove is asking about
    val all = us.value
    val roles = all?.strs("roles") ?: listOf("user", "admin")
    val everyProject = all?.strs("projects") ?: emptyList()
    val owner = all?.str("owner") ?: ""
    val me = all?.str("me") ?: ""

    if (ask.isNotBlank()) androidx.compose.material3.AlertDialog(
        onDismissRequest = { ask = "" },
        title = { Text("Remove $ask?") },
        text = { Text("The account goes. Its home on a node, and anything it committed, stay where they are.") },
        confirmButton = { Button(onClick = {
            val name = ask; ask = ""
            scope.launch {
                said = try { api.userRemove(name); "$name removed" }
                       catch (e: Exception) { e.message ?: e.toString() }
                reload()
            }
        }) { Text("Remove") } },
        dismissButton = { TextButton(onClick = { ask = "" }) { Text("Cancel") } })

    Pull(us.value == null && us.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Users", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = { adding = !adding }) { Text(if (adding) "Cancel" else "Add") }
                TextButton(onClick = reload) { Text("Refresh") }
            }
            if (said.isNotBlank()) Text(said, Modifier.padding(16.dp, 0.dp), color = Note)
            if (us.error != null) Problem(us.error)
            if (adding) AddAccount(api, roles) { msg -> said = msg; adding = false; reload() }
        }
        items(all?.arr("users") ?: emptyList()) { u ->
            val name = u.str("name")
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(Modifier.clickable { open = if (open == name) "" else name },
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(name, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Text(u.str("role"), color = if (u.str("role") == "user") MaterialTheme.colorScheme.onSurface else Note)
                }
                val pr = u.obj("profile")
                Dim(listOf(pr.str("full_name"), pr.str("email")).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { "no profile yet" })
                Dim("projects: " + u.strs("projects").joinToString(", ").ifBlank { "none" })
                if (open == name) EditAccount(
                    api, u, roles, everyProject,
                    // The owner is the one account that cannot go or be
                    // demoted, and an admin removing themselves is the other
                    // way to be locked out. users.py refuses both; ghosting
                    // them here is so the refusal is not the first you hear.
                    mayRemove = name != owner && name != me,
                    onDone = { msg -> said = msg; open = ""; reload() },
                    onRemove = { ask = name })
            }
            Hairline()
        }
        item { Dim("A user sees only the projects listed for them. Everything here is an administrator's, and the owner cannot be removed or demoted.") }
    }
    }
}

@Composable
private fun AddAccount(api: Api, roles: List<String>, onDone: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf("") }
    var role by remember { mutableStateOf("user") }
    Card(Modifier.fillMaxWidth().padding(16.dp, 6.dp)) {
        Column(Modifier.padding(12.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text("Account name") },
                              singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pw, { pw = it }, label = { Text("Password") }, singleLine = true,
                              visualTransformation = PasswordVisualTransformation(),
                              modifier = Modifier.fillMaxWidth())
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (r in roles) FilterChip(selected = role == r, onClick = { role = r }, label = { Text(r) })
            }
            Button(enabled = name.isNotBlank() && pw.isNotBlank(),
                   onClick = { scope.launch {
                       onDone(try { api.userAdd(name.trim(), pw, role); "${name.trim()} added" }
                              catch (e: Exception) { e.message ?: e.toString() })
                   } }, modifier = Modifier.padding(top = 8.dp)) { Text("Add account") }
            Dim("Projects are given after it exists: open the row.")
        }
    }
}

@Composable
private fun EditAccount(api: Api, u: JSONObject, roles: List<String>, everyProject: List<String>,
                        mayRemove: Boolean, onDone: (String) -> Unit, onRemove: () -> Unit) {
    val scope = rememberCoroutineScope()
    val name = u.str("name")
    // Keyed on the account, so opening a second row does not inherit the
    // first one's unsaved picks.
    var role by remember(name) { mutableStateOf(u.str("role")) }
    var picked by remember(name) { mutableStateOf(u.strs("projects").toSet()) }
    var pw by remember(name) { mutableStateOf("") }
    var saving by remember(name) { mutableStateOf(false) }
    Column(Modifier.padding(top = 8.dp)) {
        Text("Role", style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (r in roles) FilterChip(selected = role == r, onClick = { role = r }, label = { Text(r) })
        }
        Text("Projects", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 8.dp))
        if (everyProject.isEmpty()) Dim("no projects to give yet")
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (p in everyProject) FilterChip(
                selected = p in picked,
                onClick = { picked = if (p in picked) picked - p else picked + p },
                label = { Text(p) })
        }
        OutlinedTextField(pw, { pw = it }, label = { Text("New password (leave blank to keep)") },
                          singleLine = true, visualTransformation = PasswordVisualTransformation(),
                          modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !saving, onClick = {
                saving = true
                scope.launch {
                    onDone(try { api.userEdit(name, role, picked.toList(), pw); "$name saved" }
                           catch (e: Exception) { e.message ?: e.toString() })
                }
            }) { Text("Save") }
            if (mayRemove) OutlinedButton(onClick = onRemove) { Text("Remove", color = Bad) }
        }
    }
}

// ---- installing the newer build of this app ------------------------------------
// The card that says the app is behind used to end with "in BuilderBot's
// Artifacts tab", which means: go to a desktop, download a file, move it to
// the phone. The APK is an artifact the dashboard already serves and the
// phone is already authenticated to it, so the whole errand is a download
// and an intent.
//
// Android asks the person to confirm the install every time, and asks for
// "install unknown apps" the first time. This cannot and should not install
// anything quietly. What it removes is the desktop, not the decision.
@Composable
private fun InstallNewer(api: Api, apk: String, sha: String = "") {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var said by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Button(enabled = !busy, onClick = {
            scope.launch {
                busy = true
                said = try {
                    // Into the cache directory the provider publishes, under
                    // the name the dashboard reported, replacing whatever an
                    // earlier attempt left: two builds of the same app in the
                    // cache is a way to install the older one by accident.
                    val dir = java.io.File(context.cacheDir, "apk")
                    dir.mkdirs()
                    dir.listFiles()?.forEach { it.delete() }
                    val file = api.download(api.apkPath(apk), java.io.File(dir, apk))
                    // What arrived is what the dashboard named, or it is not
                    // installed (B273): the download crosses the same network
                    // as the sign-in, and the installer checks nothing.
                    if (sha.isNotBlank()) {
                        val md = java.security.MessageDigest.getInstance("SHA-256")
                        file.inputStream().use { ins ->
                            val buf = ByteArray(1 shl 16)
                            while (true) { val n = ins.read(buf); if (n < 0) break; md.update(buf, 0, n) }
                        }
                        val got = md.digest().joinToString("") { "%02x".format(it) }
                        if (got != sha.lowercase()) { file.delete(); throw Exception("the download did not match the dashboard's checksum; not installed") }
                    }
                    val uri = androidx.core.content.FileProvider.getUriForFile(
                        context, context.packageName + ".files", file)
                    context.startActivity(
                        android.content.Intent(android.content.Intent.ACTION_VIEW)
                            .setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                    ""
                } catch (e: Exception) {
                    // Named rather than swallowed: the two that actually
                    // happen are a dashboard that has no APK in dist/ yet and
                    // a phone that has not been allowed to install from here.
                    e.message ?: "it did not download"
                }
                busy = false
            }
        }) { Text(if (busy) "Downloading…" else "Install it") }
        if (said.isNotBlank()) {
            Spacer(Modifier.width(8.dp))
            Text(said, color = Bad)
        }
    }
}

// ---- profile -------------------------------------------------------------------

@Composable
fun ProfileScreen(store: Store) {
    val api = store.api() ?: return
    val scope = rememberCoroutineScope()
    val (pf, reload) = load("profile") { api.profile() }
    val p = pf.value?.obj("profile")
    var full by remember(p) { mutableStateOf(p?.str("full_name") ?: "") }
    var email by remember(p) { mutableStateOf(p?.str("email") ?: "") }
    var gitName by remember(p) { mutableStateOf(p?.str("git_name") ?: "") }
    var gitEmail by remember(p) { mutableStateOf(p?.str("git_email") ?: "") }
    var cur by remember { mutableStateOf("") }
    var next by remember { mutableStateOf("") }
    var said by remember { mutableStateOf("") }
    val logs = pf.value?.arr("logs") ?: emptyList()
    LazyColumn(Modifier.fillMaxSize()) {
    item {
    Column(Modifier.fillMaxWidth().padding(16.dp)) {
        Text("Profile", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        if (pf.error != null) Problem(pf.error)
        if (pf.value != null) {
            Dim("${pf.value.str("name")} · ${pf.value.str("role")}" + (if (!pf.value.bool("git_ready")) " · no git identity yet, so no session starts for you" else ""))
            OutlinedTextField(full, { full = it }, label = { Text("Name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(email, { email = it }, label = { Text("Email") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(gitName, { gitName = it }, label = { Text("Git name (blank: your name)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(gitEmail, { gitEmail = it }, label = { Text("Git email (blank: your email)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Row(Modifier.padding(top = 8.dp)) {
                Spacer(Modifier.weight(1f))
                Button(onClick = { scope.launch {
                    said = try { api.profileSave(mapOf("full_name" to full, "email" to email, "git_name" to gitName, "git_email" to gitEmail)); "saved" }
                           catch (e: Exception) { e.message ?: e.toString() }
                    reload()
                } }) { Text("Save") }
            }
            Spacer(Modifier.height(16.dp))
            Text("Password", fontWeight = FontWeight.SemiBold)
            OutlinedTextField(cur, { cur = it }, label = { Text("Current password") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(next, { next = it }, label = { Text("New password (eight characters or more)") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            Row(Modifier.padding(top = 8.dp)) {
                Spacer(Modifier.weight(1f))
                Button(enabled = cur.isNotBlank() && next.length >= 8, onClick = { scope.launch {
                    said = try { api.password(cur, next); store.password = next; cur = ""; next = ""; "password changed" }
                           catch (e: Exception) { e.message ?: e.toString() }
                } }) { Text("Change password") }
            }
            if (said.isNotBlank()) Text(said, color = Accent, modifier = Modifier.padding(top = 8.dp))
        }
    }
    }
    // The account's conversations with Claude, on every project it has
    // them, newest first: the Profile tab's list, with the two things a
    // phone does with one.
    if (pf.value != null) item {
        SectionHead("Conversations")
        if (logs.isEmpty()) Column(Modifier.padding(horizontal = 16.dp)) { Dim("none yet: a Claude session of yours writes one as it goes") }
    }
    items(logs) { r -> LogRow(api, r, showProject = true) }
    }
}

// ---- more: the watch, about, and whether this app is behind -----------------------

@Composable
fun MoreScreen(store: Store, isAdmin: Boolean, nav: NavHostController, onSignOut: () -> Unit) {
    val api = store.api() ?: return
    val context = androidx.compose.ui.platform.LocalContext.current
    val (meta, _) = load("meta") { api.meta() }
    var watch by remember { mutableStateOf(store.watch) }
    var turns by remember { mutableStateOf(store.turns) }
    var watchSaid by remember { mutableStateOf("") }
    var poll by remember { mutableStateOf(store.pollSeconds.toString()) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Mark(26.dp)
            Spacer(Modifier.width(10.dp))
            Text("More", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Ink)
        }
        Spacer(Modifier.height(8.dp))
        // Drift: the dashboard names the API surface it serves; this build
        // names the one it was written against. Ahead means a newer app
        // exists and the dashboard's own Artifacts tab has it.
        val m = meta.value
        if (m != null) {
            val serverApi = m.int("api")
            if (serverApi > BuildConfig.TARGET_API) Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text("This app is behind the dashboard", color = Warn, fontWeight = FontWeight.SemiBold)
                    Text("The dashboard serves API $serverApi and this build was written for ${BuildConfig.TARGET_API}. Some screens may show blanks until the newer app is installed" +
                        (if (m.str("apk").isNotBlank()) ": ${m.str("apk")}." else "."))
                    if (m.str("apk").isNotBlank()) InstallNewer(api, m.str("apk"), m.str("apk_sha256"))
                }
            } else if (serverApi < BuildConfig.TARGET_API) Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text("The dashboard is behind this app", color = Warn, fontWeight = FontWeight.SemiBold)
                    Text("It serves API $serverApi; this build expects ${BuildConfig.TARGET_API}. Update the container.")
                }
            }
        }
        // The other pages, as rows in one panel: a list of places to go,
        // in the site's row shape, rather than three colored words.
        // Tools is not gated on isAdmin: the listing is what a build can
        // use, which is everybody's question, and the server refuses the
        // two buttons.
        val pages = listOf("Profile" to "profile", "Tools" to "tools", "Jobs" to "jobs") +
            (if (isAdmin) listOf("Users" to "users") else emptyList()) + listOf("What's new" to "whatsnew")
        Panel(Modifier.fillMaxWidth()) {
            pages.forEachIndexed { i, (label, route) ->
                if (i > 0) Hairline()
                Row(Modifier.fillMaxWidth().clickable { nav.navigate(route) }.padding(vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(label, color = Ink, modifier = Modifier.weight(1f))
                    Text("\u203a", color = Dim, style = MaterialTheme.typography.titleMedium)
                }
            }
        }
        SectionHead("The watch", inset = false)
        Dim("The app asks the dashboard what the bell would show and posts it, with Approve and Deny on the notification: on the interval below while the app is open, and about once a minute in the background. Nothing stays in the shade between questions. No push service: the phone reaches your BuilderBot directly.")
        // A draft until Save, as every group of settings is: a switch that
        // stopped the watch on a mis-tap had nothing to look at first.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Watch for questions", modifier = Modifier.weight(1f))
            Switch(checked = watch, onCheckedChange = { watch = it; watchSaid = "" })
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Tell me when Claude finishes")
                Dim("a note when a session of yours goes from working to waiting on you")
            }
            Switch(checked = turns, enabled = watch, onCheckedChange = { turns = it; watchSaid = "" })
        }
        OutlinedTextField(poll, { poll = it; watchSaid = "" },
            label = { Text("Poll every (seconds, 10 to 300)") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
        val every = poll.trim().toIntOrNull()
        val pollOk = every != null && every in 10..300
        val changed = watch != store.watch || turns != store.turns || every != store.pollSeconds
        Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (!pollOk) "the poll is a number of seconds from 10 to 300" else watchSaid,
                 color = if (!pollOk) Bad else Note, style = MaterialTheme.typography.bodySmall,
                 modifier = Modifier.weight(1f))
            Button(enabled = changed && pollOk, onClick = {
                store.watch = watch; store.turns = turns; store.pollSeconds = every ?: store.pollSeconds
                if (watch) Watch.startIfWanted(context) else Watch.stop(context)
                watchSaid = "saved"
            }) { Text("Save") }
        }
        // The look: the dashboard's own schemes, by their names. Kept on
        // this device, as the dashboard keeps its own per browser.
        SectionHead("Colors", inset = false)
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (sc in Schemes.all) {
                val on = Schemes.current.name == sc.name
                Column(Modifier
                    .background(sc.panel, RoundedCornerShape(8.dp))
                    .border(if (on) 2.dp else 1.dp, if (on) sc.accent else sc.line, RoundedCornerShape(8.dp))
                    .clickable { Schemes.pick(sc.name); store.scheme = sc.name }
                    .padding(10.dp, 8.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                        for (c in listOf(sc.accent, sc.warn, sc.bad, sc.note))
                            androidx.compose.foundation.layout.Box(
                                Modifier.size(10.dp).background(c, RoundedCornerShape(99.dp)))
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(sc.name, color = sc.ink, style = MaterialTheme.typography.labelMedium)
                }
            }
        }
        SectionHead("About", inset = false)
        Text("app ${BuildConfig.VERSION_NAME} api ${BuildConfig.TARGET_API}" +
            (if (m != null) "\ndashboard ${m.str("version").ifBlank { "unstamped" }} api ${m.int("api")}" else ""),
            color = Dim, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
        Dim("Signed in to ${store.server} as ${store.user}")
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onSignOut) { Text("Sign out") }
    }
}

// ---- tools: what a node carries, and adding to it -------------------------------
// The dashboard's Tools tab, as much of it as a phone is the right shape for:
// which toolchains a store holds, and Install or Remove on one of them. The
// listing is everybody's (what a node carries decides whether a build can run
// there), and the two buttons are an administrator's, which is the server's
// rule and not this screen's opinion.
//
// Android system images are deliberately not here. They are a picker over an
// API-level catalog with flavors and ABIs, and choosing one on a phone is
// worse than choosing it on the tab that has room for it.

@Composable
fun ToolsScreen(store: Store, isAdmin: Boolean) {
    val api = store.api() ?: return
    val scope = rememberCoroutineScope()
    var node by remember { mutableStateOf("") }
    var said by remember { mutableStateOf("") }
    var ask by remember { mutableStateOf<Pair<String, JSONObject>?>(null) }
    val (nd, _) = load("tools-nodes") { api.nodes() }
    val (pk, reload) = load("tools-$node") { api.toolchains(node) }
    val nodes = nd.value?.arr("nodes")
        ?.filter { it.str("kind") == "agent" && it.str("state") != "retired" } ?: emptyList()
    val job = pk.value?.obj("job")
    val busy = job?.bool("running") == true

    // The press, once the dialog has been answered. Reloaded rather than
    // guessed at: an install is a job, and what the row should say next is
    // what the server reports about it, not what pressing implied.
    fun act(action: String, name: String) {
        ask = null
        scope.launch {
            said = try {
                api.toolchainAct(node, action, listOf(name))
                if (action == "install") "installing $name…" else "removing $name…"
            } catch (e: Exception) { e.message ?: e.toString() }
            reload()
        }
    }

    ask?.let { (action, item) ->
        val size = item.str("size")
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { ask = null },
            title = { Text(if (action == "install") "Install ${item.str("label")}?"
                           else "Remove ${item.str("label")}?") },
            text = {
                Column {
                    Text(if (action == "install")
                            "It downloads onto the store " + (if (node.isBlank()) "here" else "on this node") +
                            (if (size.isNotBlank()) " ($size)." else ".")
                         else "The files go; nothing that was built with it is touched.")
                    if (item.strs("needs").isNotEmpty())
                        Dim("needs " + item.strs("needs").joinToString(", "))
                }
            },
            confirmButton = { Button(onClick = { act(action, item.str("name")) }) {
                Text(if (action == "install") "Install" else "Remove") } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Cancel") } })
    }

    Pull(pk.value == null && pk.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Tools", style = MaterialTheme.typography.titleLarge,
                     fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = reload) { Text("Refresh") }
            }
            if (nodes.isNotEmpty()) Row(
                Modifier.fillMaxWidth().padding(16.dp, 0.dp)
                        .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = node.isBlank(), onClick = { node = "" },
                           label = { Text("controller") })
                for (n in nodes) FilterChip(selected = node == n.str("id"),
                                            onClick = { node = n.str("id") },
                                            label = { Text(n.str("name")) })
            }
            if (said.isNotBlank()) Text(said, Modifier.padding(16.dp, 8.dp), color = Note)
            if (pk.error != null) Problem(pk.error)
            pk.value?.let { v ->
                if (v.str("root").isNotBlank())
                    Dim("store: ${v.str("root")}" + if (v.bool("shared")) " (a mapped share)" else "")
            }
            if (busy && job != null) Card(Modifier.fillMaxWidth().padding(16.dp, 6.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.width(16.dp).height(16.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("${job.str("action")} ${job.str("current")}".trim(),
                             fontWeight = FontWeight.SemiBold)
                    }
                    // The last line it printed, which for a download is the
                    // only thing that moves. Not the whole tail: this is a
                    // phone, and the tab with room for the log is the one on
                    // a desk.
                    job.strs("log").lastOrNull { it.isNotBlank() }?.let { Mono(it) }
                }
            }
            if (pk.value == null && pk.error == null) Loading()
        }
        items(pk.value?.arr("items") ?: emptyList()) { p ->
            val installed = p.bool("installed")
            val wrong = p.str("wrong_platform")
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(p.str("label"), fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Text(if (p.bool("unknown")) "unknown"
                         else if (installed) p.str("version").ifBlank { "installed" }
                         else "not installed",
                         color = if (p.bool("unknown")) Warn else if (installed) Ok else MaterialTheme.colorScheme.onSurfaceVariant,
                         style = MaterialTheme.typography.labelMedium)
                }
                Dim(p.str("about"))
                Dim(listOf(p.str("size"), if (p.strs("needs").isEmpty()) "" else "needs " + p.strs("needs").joinToString(", "))
                        .filter { it.isNotBlank() }.joinToString(" · "))
                when {
                    wrong.isNotBlank() -> Text("not for this node: $wrong", color = Warn,
                                               style = MaterialTheme.typography.bodySmall)
                    p.bool("unknown") -> Text("this node has not reported its store yet",
                                              color = Warn, style = MaterialTheme.typography.bodySmall)
                    !isAdmin -> {}
                    else -> Row(Modifier.padding(top = 6.dp)) {
                        OutlinedButton(enabled = !busy,
                                       onClick = { ask = (if (installed) "remove" else "install") to p }) {
                            Text(if (installed) "Remove" else "Install")
                        }
                    }
                }
            }
            Hairline()
        }
        item { if (!isAdmin) Dim("Installing and removing is an administrator's: these are gigabytes on somebody else's disk.") }
    }
    }
}

// ---- what's new: BuilderBot's own changelog -----------------------------------
// What the dashboard's welcome panel shows after an update, to read on the
// way to the desk: each release with what it added, changed and fixed.

@Composable
fun WhatsNewScreen(store: Store) {
    val api = store.api() ?: return
    val (wl, reload) = load("welcome") { api.welcome() }
    val sections = wl.value?.arr("sections") ?: emptyList()
    Pull(wl.value == null && wl.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Text("What's new", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Ink,
                 modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 0.dp))
            if (wl.error != null) Problem(wl.error)
            if (wl.value == null && wl.error == null) Loading()
            if (wl.value != null && sections.isEmpty()) Column(Modifier.padding(16.dp)) { Dim("the dashboard has no changelog to show") }
        }
        for (sec in sections.take(6)) {
            item { SectionHead(sec.str("title")) }
            items(sec.arr("entries")) { e ->
                Row(Modifier.fillMaxWidth().padding(16.dp, 6.dp), verticalAlignment = Alignment.Top) {
                    if (e.str("cat").isNotBlank()) {
                        Pill(e.str("cat"), when (e.str("cat")) { "Added" -> Ok; "Fixed" -> Note; "Removed", "Security" -> Bad
                                                                 "Changed", "Deprecated" -> Warn; else -> Dim },
                             Modifier.padding(top = 3.dp).width(74.dp))
                        Spacer(Modifier.width(10.dp))
                    }
                    Text(e.str("text"), color = Ink, style = MaterialTheme.typography.bodyMedium,
                         modifier = Modifier.weight(1f))
                }
                Hairline()
            }
        }
    }
    }
}

// ---- jobs: what the nodes were asked to do --------------------------------------
// The Jobs tab's list: a build, a test run, a rebuild, a command, each with
// the node it ran on and what became of it. The account's own projects',
// or every one for an administrator, which is the server's rule.

@Composable
fun JobsScreen(store: Store) {
    val api = store.api() ?: return
    val (jb, reload) = load("jobs") { api.jobs() }
    val (nd, _) = load("jobs-nodes") { runCatching { api.nodes() }.getOrNull() }
    val names = nd.value?.arr("nodes")?.associate { it.str("id") to it.str("name") } ?: emptyMap()
    val rows = jb.value?.arr("jobs") ?: emptyList()
    val clock = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT)
    Pull(jb.value == null && jb.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Jobs", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                     color = Ink, modifier = Modifier.weight(1f))
                TextButton(onClick = reload) { Text("Refresh") }
            }
            if (jb.error != null) Problem(jb.error)
            if (jb.value == null && jb.error == null) Loading()
            if (jb.value != null && rows.isEmpty()) Column(Modifier.padding(horizontal = 16.dp)) { Dim("no job on record") }
        }
        items(rows.take(60)) { j ->
            val state = j.str("state")
            val tone = when (state) { "succeeded" -> Ok; "failed", "lost" -> Bad; "running", "queued", "assigned" -> Warn; else -> Dim }
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(listOf(j.str("type"), j.str("project")).filter { it.isNotBlank() }.joinToString(" · "),
                         color = Ink, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Pill(state.ifBlank { "unknown" }, tone)
                }
                val took = j.optLong("ended") - j.optLong("started")
                Dim(listOf(names[j.str("node")] ?: j.str("node"),
                           if (j.optLong("queued") > 0) clock.format(java.util.Date(j.optLong("queued") * 1000)) else "",
                           if (j.optLong("ended") > 0 && took >= 0) "${took}s" else "",
                           if (j.has("exit_code") && !j.isNull("exit_code") && j.int("exit_code") != 0) "exit ${j.int("exit_code")}" else "")
                        .filter { it.isNotBlank() }.joinToString(" · "))
                if (j.str("step").isNotBlank()) Dim(j.str("step"))
                if (j.str("error").isNotBlank()) Text(j.str("error"), color = Bad, style = MaterialTheme.typography.bodySmall)
            }
            Hairline()
        }
    }
    }
}
