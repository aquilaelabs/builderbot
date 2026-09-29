// One project: the notebook's views the app can act on (the roadmap, the
// bugs, the briefing's rules and memories, the artifacts, and the
// repository's state) as sections down one screen with the actions a person
// takes from a phone: add an item, file a bug, close one, hand a step or a
// report to the session that is running, read what is waiting.
//
// Sending is the one that changes what a phone is FOR. The rest is reading
// and filing, which can wait for a desk; a step handed over is work starting
// while you are somewhere else. It is offered only where it can land (a
// session has to be open on the project) because a button that quietly does
// nothing is worse than one that is not there.
//
// The terminals stay the browser's.
package dev.builderbot.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import dev.builderbot.app.Store
import dev.builderbot.app.arr
import dev.builderbot.app.bool
import dev.builderbot.app.int
import dev.builderbot.app.obj
import dev.builderbot.app.str
import dev.builderbot.app.strs
import kotlinx.coroutines.launch

private val VIEWS = listOf("Roadmap", "Bugs", "Briefing", "Artifacts", "Git", "Settings")

// What the settings view offers, in the dashboard's own order and words. The
// lists are the server's (prefs.MODELS, prefs.EFFORTS, prefs.EDIT_MODES) and
// it validates them, so a copy here is a menu rather than a rule: a value it
// does not know is refused with a sentence, not stored.
private val MODELS = listOf("" to "leave as is", "opus" to "Opus", "sonnet" to "Sonnet",
                            "haiku" to "Haiku", "fable" to "Fable")
private val EFFORTS = listOf("" to "leave as is", "low" to "low", "medium" to "medium",
                             "high" to "high", "xhigh" to "xhigh", "max" to "max")

@Composable
fun ProjectScreen(store: Store, name: String) {
    val api = store.api() ?: return
    var view by remember { mutableStateOf("Roadmap") }
    Column(Modifier.fillMaxSize()) {
        Text(name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Ink,
             modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 6.dp))
        // The view strip, the site's: one line of small tabs, the one in
        // front on the deep accent with ink, the rest on the panel with a
        // hairline. Scrolls sideways rather than wrapping: six words do not
        // fit a phone, and a chip that wraps letter by letter takes the whole
        // strip's height with it.
        Row(Modifier.padding(horizontal = 12.dp).horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (v in VIEWS) {
                val on = view == v
                Text(v, color = Ink, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier
                        .background(if (on) AccentDeep else Panel, RoundedCornerShape(6.dp))
                        .border(1.dp, if (on) AccentDeep else Line, RoundedCornerShape(6.dp))
                        .clickable { view = v }
                        .padding(horizontal = 12.dp, vertical = 7.dp))
            }
        }
        when (view) {
            "Roadmap" -> Roadmap(api, name)
            "Bugs" -> Bugs(api, name)
            "Briefing" -> Briefing(api, name)
            "Artifacts" -> Artifacts(api, name)
            "Git" -> Git(api, name)
            "Settings" -> Settings(api, name)
        }
    }
}

// What a send actually did, in the words the panel uses. `sent` is the whole
// question: the server marks a step as gone only when the line landed in the
// pane, so a false here means the session was busy with a dialog and the step
// is still waiting, which is exactly the case worth not lying about.
private fun sent(r: Result<org.json.JSONObject>): String {
    val v = r.getOrElse { return it.message ?: "it did not go" }
    return if (v.bool("sent")) "sent to Claude" else "not sent: the session did not take it"
}

@Composable
private fun Roadmap(api: dev.builderbot.app.Api, project: String) {
    val scope = rememberCoroutineScope()
    val (td, reload) = load("roadmap-$project") { api.roadmap(project) }
    var text by remember { mutableStateOf("") }
    var said by remember { mutableStateOf("") }
    val items = td.value?.arr("items") ?: emptyList()
    // Whether there is anything to send TO. The panel's rule, and the
    // server's: no session, no send.
    val live = td.value?.str("session")?.isNotBlank() == true
    Pull(td.value == null && td.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (live) Dim("a Claude session is open on this project")
                OutlinedTextField(text, { text = it }, label = { Text("Add to the roadmap") }, modifier = Modifier.fillMaxWidth())
                Row { Spacer(Modifier.weight(1f)); Button(enabled = text.isNotBlank(), onClick = { scope.launch {
                    said = try { api.roadmapAdd(project, text.trim()); text = ""; "added" } catch (e: Exception) { e.message ?: "" }
                    reload()
                } }) { Text("Add") } }
                if (said.isNotBlank()) Text(said, color = Note)
                if (td.error != null) Problem(td.error)
                if (td.value != null && items.isEmpty()) Dim("nothing on the roadmap")
            }
        }
        items(items) { it ->
            // A shelved item carries WHEN it was shelved, so the field is a
            // time and not a flag; a bare bool read it as false.
            val shelved = it.optLong("shelved", 0L) > 0L || it.optBoolean("shelved")
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Tag("R${it.int("id", it.int("number"))}", color = if (shelved) Dim else Ink, modifier = Modifier.padding(end = 10.dp, top = 1.dp))
                    Text(it.str("text"), modifier = Modifier.weight(1f), color = if (shelved) Dim else Ink)
                    if (shelved){ Spacer(Modifier.width(6.dp)); Pill("shelved", Dim) }
                }
                for ((i, s) in it.arr("steps").withIndex())
                    Text("${i + 1}. ${s.str("text")}" + (if (s.bool("done")) "  \u2713" else if (s.int("sent") > 0) "  (sent)" else ""),
                        color = if (s.bool("done")) Ok else Dim, style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(start = 12.dp, top = 2.dp))
                if (it.str("info").isNotBlank()) Dim("  " + it.str("info").take(200))
                Row {
                    Spacer(Modifier.weight(1f))
                    if (!shelved && live) TextButton(onClick = { scope.launch {
                        said = sent(runCatching { api.roadmapSend(project, it.opt("id"), null, "") })
                        reload()
                    } }) { Text("Send to Claude") }
                    if (!shelved) TextButton(onClick = { scope.launch { runCatching { api.roadmapShelve(project, it.opt("id")) }; reload() } }) { Text("Shelve") }
                }
            }
            Hairline()
        }
    }
    }
}

@Composable
private fun Bugs(api: dev.builderbot.app.Api, project: String) {
    val scope = rememberCoroutineScope()
    val (bg, reload) = load("bugs-$project") { api.bugs(project) }
    var title by remember { mutableStateOf("") }
    var area by remember { mutableStateOf("") }
    var repro by remember { mutableStateOf("") }
    var sev by remember { mutableStateOf("medium") }
    var said by remember { mutableStateOf("") }
    val rows = bg.value?.arr("bugs") ?: emptyList()
    Pull(bg.value == null && bg.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                OutlinedTextField(title, { title = it }, label = { Text("File a bug") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(area, { area = it }, label = { Text("Where it lives") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(repro, { repro = it }, label = { Text("How to reproduce it") }, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (s in listOf("low", "medium", "high")) FilterChip(selected = sev == s, onClick = { sev = s }, label = { Text(s) })
                    Spacer(Modifier.weight(1f))
                    Button(enabled = title.isNotBlank(), onClick = { scope.launch {
                        said = try { api.bugAdd(project, title.trim(), sev, area.trim(), repro.trim()); title = ""; area = ""; repro = ""; "filed" }
                               catch (e: Exception) { e.message ?: "" }
                        reload()
                    } }) { Text("File") }
                }
                if (said.isNotBlank()) Text(said, color = Note)
                if (bg.error != null) Problem(bg.error)
                if (bg.value != null && rows.isEmpty()) Dim("no bugs filed")
            }
        }
        items(rows) { b ->
            val open = b.str("status") == "open"
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Tag("B${b.int("id", b.int("number"))}", color = if (open) Ink else Dim, modifier = Modifier.padding(end = 10.dp, top = 1.dp))
                    Column(Modifier.weight(1f)) {
                        Text(b.str("title"), color = if (open) Ink else Dim)
                        Dim(listOf(if (open) "" else b.str("status"), b.str("area")).filter { it.isNotBlank() }.joinToString(" · "))
                    }
                    Spacer(Modifier.width(8.dp))
                    Pill(b.str("severity"), if (open) severityColor(b.str("severity")) else Dim)
                }
                if (open) Row { Spacer(Modifier.weight(1f))
                    TextButton(onClick = { scope.launch {
                        said = sent(runCatching { api.bugSend(project, b.opt("id"), "") })
                        reload()
                    } }) { Text("Send") }
                    TextButton(onClick = { scope.launch { runCatching { api.bugStatus(project, b.opt("id"), "wontfix", "closed from the app") }; reload() } }) { Text("Won't fix") }
                    TextButton(onClick = { scope.launch { runCatching { api.bugStatus(project, b.opt("id"), "fixed", "closed from the app") }; reload() } }) { Text("Fixed") }
                }
            }
            Hairline()
        }
    }
    }
}

@Composable
private fun Briefing(api: dev.builderbot.app.Api, project: String) {
    val (rl, reloadRules) = load("rules-$project") { api.rules(project) }
    // The two halves of the dashboard's Briefing tab, in the same order: what
    // the operator holds a session to, then what a session noticed. Both are
    // read here: a rule is the operator's to write and a memory is the
    // session's, so neither is a thing to type on a phone.
    val (mm, reloadMem) = load("mem-$project") { api.memory(project) }
    val rules = rl.value?.arr("rules") ?: emptyList()
    val mems = mm.value?.arr("memories") ?: emptyList()
    Pull(mm.value == null && mm.error == null, { reloadRules(); reloadMem() }) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (rl.error != null) Problem(rl.error)
                if (rl.value != null) Dim("${rl.value.int("standing")} standing rule${if (rl.value.int("standing") == 1) "" else "s"}, ${rl.value.int("conditional")} conditional · edited on the dashboard's Briefing tab")
                if (rl.value != null && rules.isEmpty()) Dim("no house rules here")
            }
        }
        items(rules) { r ->
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Text(r.str("name"), fontWeight = FontWeight.SemiBold)
                Text(r.str("text"))
                val trig = (r.strs("files") + r.strs("words")).filter { it.isNotBlank() }
                if (trig.isNotEmpty()) Dim("when: " + trig.joinToString(", "))
            }
            Hairline()
        }
        item {
            Column(Modifier.padding(16.dp, 12.dp)) {
                Text("Memory", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                if (mm.error != null) Problem(mm.error)
                if (mm.value != null && mems.isEmpty()) Dim("nothing remembered here yet")
            }
        }
        items(mems) { m ->
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Text(m.str("title").ifBlank { m.str("name") }, fontWeight = FontWeight.SemiBold)
                val about = m.str("hook").ifBlank { m.str("description") }
                if (about.isNotBlank()) Text(about)
                Dim(listOf(m.str("type"), m.str("when")).filter { it.isNotBlank() }.joinToString(" · "))
            }
            Hairline()
        }
    }
    }
}

@Composable
private fun Artifacts(api: dev.builderbot.app.Api, project: String) {
    val (ar, reload) = load("art-$project") { api.artifacts(project) }
    val rows = ar.value?.arr("artifacts") ?: emptyList()
    val b = ar.value?.obj("build")
    Pull(ar.value == null && ar.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (ar.error != null) Problem(ar.error)
                if (b != null) Dim(if (b.str("node").isNotBlank()) "builds on ${b.str("name")}" else "no node: nothing compiles for this project")
                if (ar.value != null && rows.isEmpty()) Dim("nothing in dist/ yet")
            }
        }
        items(rows) { a ->
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Text(a.str("name").ifBlank { a.str("path") })
                Dim(listOf(a.str("path"), if (a.int("size") > 0) "${a.int("size") / 1024} KB" else "").filter { it.isNotBlank() }.joinToString(" · "))
            }
            Hairline()
        }
    }
    }
}

// ---- what this project's sessions run as -----------------------------------
// The two the dashboard's settings dialog carries and a phone can usefully
// set: the model and the effort. Permissions are NOT here. Claude Code's own
// app is where a session's are changed, which is the operator's own finding
// and a better place for it than a second control saying something similar.
// Both are read WHEN A SESSION STARTS (bb-tty writes them into
// the settings file it launches Claude Code with), so changing one while a
// session is open does nothing to that session until a new one starts. That
// is what the chip is: it ENDS the open session, the same gesture the dialog
// offers, and the Claude button starts one on the new setting, resuming the
// conversation.
//
// Chips rather than dropdowns: every one of these lists is short, a chip row
// shows the current value without a tap, and it is the idiom already on this
// screen. The node, the build and test commands and the notebook gates stay
// the browser's. They are not decisions anybody makes from a phone.
@Composable
private fun Settings(api: dev.builderbot.app.Api, project: String) {
    val scope = rememberCoroutineScope()
    val (st, reload) = load("status-settings-$project") { api.status() }
    val me = st.value?.arr("projects")?.firstOrNull { it.str("name") == project }
    val prefs = me?.obj("prefs")
    val live = me?.str("session_at")?.isNotBlank() == true
    var model by remember(prefs) { mutableStateOf(prefs?.str("model") ?: "") }
    var effort by remember(prefs) { mutableStateOf(prefs?.str("effort") ?: "") }
    var restart by remember(prefs) { mutableStateOf(true) }
    var said by remember { mutableStateOf("") }
    var saving by remember { mutableStateOf(false) }
    val changed = prefs != null && (model != prefs.str("model") || effort != prefs.str("effort"))
    Column(Modifier.fillMaxSize().padding(16.dp, 8.dp)) {
        if (st.error != null) Problem(st.error)
        if (st.value == null && st.error == null) Loading()
        if (prefs == null && st.value != null) Dim("this project has no settings here")
        if (prefs != null) {
            Text("Model", fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((v, l) in MODELS)
                    FilterChip(selected = model == v, onClick = { model = v }, label = { Text(l) })
            }
            Spacer(Modifier.height(8.dp))
            Text("Effort", fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((v, l) in EFFORTS)
                    FilterChip(selected = effort == v, onClick = { effort = v }, label = { Text(l) })
            }
            Spacer(Modifier.height(8.dp))
            if (live) {
                FilterChip(selected = restart, onClick = { restart = !restart },
                           label = { Text("end the session now") })
                Dim(if (restart)
                        "press Claude to start it again, resuming the conversation; anything it is in the middle of is lost"
                    else "saved for the next session; the one running keeps what it started with")
            } else {
                Dim("no session is open, so this takes effect when one starts")
            }
            Row {
                Spacer(Modifier.weight(1f))
                Button(enabled = changed && !saving, onClick = {
                    scope.launch {
                        saving = true
                        said = try {
                            // The request key is still `restart`: an APK older than
                            // the image sends it, and the server has to keep taking it.
                            // What came back changed name with the behaviour.
                            val r = api.prefs(project, mapOf(
                                "model" to model, "effort" to effort,
                                "restart" to (live && restart)))
                            val why = r.str("error")
                            if (why.isNotBlank()) why
                            else if (!live || !restart) "saved"
                            else if (r.bool("ended")) "saved, and the session ended: press Claude to start it again"
                            else ("saved, but the session was not ended: " +
                                  r.str("why").ifBlank { "it is still on what it started with" })
                        } catch (e: Exception) { e.message ?: "it did not save" }
                        saving = false
                        reload()
                    }
                }) { Text(if (live && restart) "Save and end it" else "Save") }
            }
            if (said.isNotBlank()) Text(said, color = Note)
        }
    }
}

@Composable
private fun Git(api: dev.builderbot.app.Api, project: String) {
    val (g, reload) = load("git-$project") { api.git(project) }
    // The answer carries the branch and the files at its top level. This
    // read a `status` object first, through a helper that never answers
    // null, so every project read "on no branch" with nothing changed.
    val s = g.value
    Column(Modifier.fillMaxSize().padding(16.dp, 8.dp)) {
        if (g.error != null) Problem(g.error)
        if (s != null) {
            Text("on ${s.str("branch").ifBlank { "no branch" }}", fontWeight = FontWeight.SemiBold)
            val ahead = s.int("ahead"); val behind = s.int("behind")
            Dim(listOf(if (s.str("upstream").isNotBlank()) "tracking ${s.str("upstream")}" else "no upstream",
                       if (ahead > 0) "$ahead ahead" else "", if (behind > 0) "$behind behind" else "").filter { it.isNotBlank() }.joinToString(" · "))
            val files = s.arr("files")
            Spacer(Modifier.height(8.dp))
            if (files.isEmpty()) Dim("nothing changed and not committed") else Text("${files.size} changed", color = Warn)
            for (f in files.take(40)) Mono("${f.str("state").ifBlank { f.str("x") }} ${f.str("path")}")
            TextButton(onClick = reload) { Text("Refresh") }
        }
    }
}
