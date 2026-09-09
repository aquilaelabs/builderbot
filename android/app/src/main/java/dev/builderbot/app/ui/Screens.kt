// The screens that are not a project: sign-in, the projects list with the
// bell's items above it, the approvals, the nodes, the accounts, the
// profile, and More (about, the watch, and whether this app is behind the
// dashboard it talks to).
package dev.builderbot.app.ui

import androidx.compose.foundation.clickable
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import dev.builderbot.app.Accent
import dev.builderbot.app.Api
import dev.builderbot.app.Bad
import dev.builderbot.app.BuildConfig
import dev.builderbot.app.Ok
import dev.builderbot.app.Store
import dev.builderbot.app.Warn
import dev.builderbot.app.WatchService
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
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(6.dp))
        content()
    }
}

@Composable
fun Dim(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface.copy(alpha = .6f))
}

@Composable
fun Mono(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace)
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
        Text("BuilderBot", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Dim("Sign in with your dashboard account. The address is the one you open in a browser — on your network, or over your tailnet.")
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
                    onDone(st.obj("can").optBoolean("admin", true))
                } catch (e: Exception) {
                    error = e.message ?: e.toString()
                }
                busy = false
            }
        }) { Text(if (busy) "Signing in" else "Sign in") }
    }
}

// ---- home: the bell's items, then the projects -------------------------------

@Composable
fun HomeScreen(store: Store, onAdmin: (Boolean) -> Unit, openProject: (String) -> Unit) {
    val api = store.api() ?: return
    val (st, reload) = load("status") { api.status() }
    val s = st.value
    if (s != null) onAdmin(s.obj("can").optBoolean("admin", true))
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Projects", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    if (s != null) Dim("${s.str("me")} · BuilderBot ${s.obj("image").str("version").ifBlank { "unstamped" }} on ${s.str("host")}")
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
                Card(Modifier.fillMaxWidth().padding(16.dp, 4.dp)) {
                    Column(Modifier.padding(12.dp)) {
                        if (asks > 0) Text("$asks question${if (asks == 1) "" else "s"} waiting for your answer — see Approvals", color = Warn)
                        for (a in att) Text(WatchService.attentionLine(a), color = if (a.bool("window")) Bad else Warn)
                    }
                }
            }
            items(s.arr("projects")) { p ->
                Column(Modifier.fillMaxWidth().clickable { openProject(p.str("name")) }.padding(16.dp, 10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(p.str("name"), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        if (p.str("session_at").isNotBlank()) Text("Claude", color = Ok, style = MaterialTheme.typography.labelMedium)
                        if (p.bool("locked")) Text("  locked", color = Warn, style = MaterialTheme.typography.labelMedium)
                    }
                    val bits = mutableListOf<String>()
                    if (p.str("git").isNotBlank()) bits += p.str("git")
                    if (p.int("todo") > 0) bits += "${p.int("todo")} on the roadmap"
                    if (p.int("bugs") > 0) bits += "${p.int("bugs")} open bug${if (p.int("bugs") == 1) "" else "s"}"
                    if (p.int("pending") > 0) bits += "${p.int("pending")} waiting for approval"
                    Dim(bits.joinToString(" · ").ifBlank { "nothing waiting" })
                }
                HorizontalDivider()
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
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Approvals", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = { reloadPh(); reloadSt() }) { Text("Refresh") }
            }
            if (said.isNotBlank()) Text(said, modifier = Modifier.padding(16.dp, 0.dp), color = Accent)
        }
        val asks = ph.value?.arr("asks") ?: emptyList()
        if (ph.error != null) item { Problem(ph.error) }
        item { Section("Waiting for your answer") { if (asks.isEmpty()) Dim("nothing — a session asking for your phone, or for root on a node, appears here") } }
        items(asks) { a ->
            val root = a.str("kind") == "root"
            Card(Modifier.fillMaxWidth().padding(16.dp, 4.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text(if (root) "Root on ${a.str("node_name")}" else "The phone on ${a.str("node_name")}",
                        color = if (root) Bad else Warn, fontWeight = FontWeight.SemiBold)
                    Text(a.str("why"), style = MaterialTheme.typography.bodyLarge)
                    Mono((if (root) "# " else "adb ") + a.strs("cmd").joinToString(" "))
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
        item { Section("Changes a session has waiting") { if (waiting.isEmpty()) Dim("none — roadmap items, bugs and rules a session added under an ask gate are listed here") } }
        items(waiting) { p -> PendingBlock(api, p.str("name"), onChanged = reloadSt) }
    }
}

suspend fun answer(api: Api, id: Int, allow: Boolean): String = try {
    api.decide(id, allow); if (allow) "allowed — the node is running it" else "denied"
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
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Nodes", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = reload) { Text("Refresh") }
            }
            if (said.isNotBlank()) Text(said, modifier = Modifier.padding(16.dp, 0.dp), color = Accent)
            if (nd.error != null) Problem(nd.error)
            if (nd.value != null && rows.isEmpty()) Dim("no node is enrolled — the dashboard's Nodes tab mints a token for one")
        }
        items(rows) { n ->
            val rep = n.obj("reported")
            val locked = n.obj("config").bool("lock")
            val live = n.bool("live")
            Card(Modifier.fillMaxWidth().padding(16.dp, 6.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(n.str("name"), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        Text(if (live) "live" else n.str("state"), color = if (live) Ok else Warn, style = MaterialTheme.typography.labelMedium)
                    }
                    Dim(listOf(rep.str("os"), if (rep.int("cpu") > 0) "${rep.int("cpu")} cpu · ${rep.int("mem_mb") / 1024}GB" else "",
                               rep.obj("distro").str("pretty")).filter { it.isNotBlank() }.joinToString(" · "))
                    val dist = rep.obj("distro")
                    if (dist.str("pkg").isNotBlank()) Dim("packages: ${dist.str("pkg")} · network: ${dist.str("network").ifBlank { "none" }} · init: ${dist.str("init")}")
                    if (locked) Text("System changes locked to its own console", color = Warn, style = MaterialTheme.typography.bodySmall)
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

suspend fun act(api: Api, id: String, action: String): String = try {
    api.nodeAct(id, action); "$action: done"
} catch (e: Exception) { e.message ?: e.toString() }

// ---- users (administrators) ------------------------------------------------------

@Composable
fun UsersScreen(store: Store) {
    val api = store.api() ?: return
    val (us, reload) = load("users") { api.users() }
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Users", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                TextButton(onClick = reload) { Text("Refresh") }
            }
            if (us.error != null) Problem(us.error)
            Dim("Roles and projects are changed on the dashboard's Users tab; this is the list.")
        }
        items(us.value?.arr("users") ?: emptyList()) { u ->
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row {
                    Text(u.str("name"), fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Text(u.str("role"), color = if (u.str("role") == "user") MaterialTheme.colorScheme.onSurface else Accent)
                }
                val pr = u.obj("profile")
                Dim(listOf(pr.str("full_name"), pr.str("email")).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { "no profile yet" })
                Dim("projects: " + u.strs("projects").joinToString(", ").ifBlank { "none" })
            }
            HorizontalDivider()
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
    Column(Modifier.fillMaxSize().padding(16.dp)) {
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

// ---- more: the watch, about, and whether this app is behind -----------------------

@Composable
fun MoreScreen(store: Store, isAdmin: Boolean, nav: NavHostController, onSignOut: () -> Unit) {
    val api = store.api() ?: return
    val context = androidx.compose.ui.platform.LocalContext.current
    val (meta, _) = load("meta") { api.meta() }
    var watch by remember { mutableStateOf(store.watch) }
    var poll by remember { mutableStateOf(store.pollSeconds.toString()) }
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("More", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
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
                    Text("The dashboard serves API $serverApi and this build was written for ${BuildConfig.TARGET_API}. Some screens may show blanks until you install the newer app" +
                        (if (m.str("apk").isNotBlank()) ": ${m.str("apk")} in BuilderBot's Artifacts tab." else "."))
                }
            } else if (serverApi < BuildConfig.TARGET_API) Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text("The dashboard is behind this app", color = Warn, fontWeight = FontWeight.SemiBold)
                    Text("It serves API $serverApi; this build expects ${BuildConfig.TARGET_API}. Update the container.")
                }
            }
        }
        TextButton(onClick = { nav.navigate("profile") }) { Text("Profile") }
        if (isAdmin) TextButton(onClick = { nav.navigate("users") }) { Text("Users") }
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Text("The watch", fontWeight = FontWeight.SemiBold)
        Dim("A foreground service polls the dashboard and posts what the bell would show, with Approve and Deny on the notification. No push service: the phone reaches your BuilderBot directly.")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Watch for questions", modifier = Modifier.weight(1f))
            Switch(checked = watch, onCheckedChange = { watch = it; store.watch = it
                if (it) WatchService.startIfWanted(context) else WatchService.stop(context) })
        }
        OutlinedTextField(poll, { poll = it; it.toIntOrNull()?.let { n -> store.pollSeconds = n } },
            label = { Text("Poll every (seconds, 10 to 300)") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Text("About", fontWeight = FontWeight.SemiBold)
        Dim("App ${BuildConfig.VERSION_NAME}, API ${BuildConfig.TARGET_API}" +
            (if (m != null) " · dashboard ${m.str("version").ifBlank { "unstamped" }}, API ${m.int("api")}" else ""))
        Dim("Signed in to ${store.server} as ${store.user}")
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onSignOut) { Text("Sign out") }
    }
}
