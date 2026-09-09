// One project: the notebook's views the app can act on — the roadmap, the
// bugs, the briefing's rules, the artifacts, and the repository's state —
// as sections down one screen with the actions a person takes from a phone:
// add an item, file a bug, close one, read what is waiting. Sending a step
// to Claude and the terminals stay the browser's.
package dev.builderbot.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import dev.builderbot.app.Accent
import dev.builderbot.app.Bad
import dev.builderbot.app.Ok
import dev.builderbot.app.Store
import dev.builderbot.app.Warn
import dev.builderbot.app.arr
import dev.builderbot.app.bool
import dev.builderbot.app.int
import dev.builderbot.app.obj
import dev.builderbot.app.str
import dev.builderbot.app.strs
import kotlinx.coroutines.launch

private val VIEWS = listOf("Roadmap", "Bugs", "Briefing", "Artifacts", "Git")

@Composable
fun ProjectScreen(store: Store, name: String) {
    val api = store.api() ?: return
    var view by remember { mutableStateOf("Roadmap") }
    Column(Modifier.fillMaxSize()) {
        Text(name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.padding(16.dp, 12.dp, 16.dp, 4.dp))
        Row(Modifier.padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (v in VIEWS) FilterChip(selected = view == v, onClick = { view = v }, label = { Text(v) })
        }
        when (view) {
            "Roadmap" -> Roadmap(api, name)
            "Bugs" -> Bugs(api, name)
            "Briefing" -> Briefing(api, name)
            "Artifacts" -> Artifacts(api, name)
            "Git" -> Git(api, name)
        }
    }
}

@Composable
private fun Roadmap(api: dev.builderbot.app.Api, project: String) {
    val scope = rememberCoroutineScope()
    val (td, reload) = load("todo-$project") { api.todo(project) }
    var text by remember { mutableStateOf("") }
    var said by remember { mutableStateOf("") }
    val items = td.value?.arr("items") ?: emptyList()
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (td.value?.str("session")?.isNotBlank() == true) Dim("a Claude session is open on this project")
                OutlinedTextField(text, { text = it }, label = { Text("Add to the roadmap") }, modifier = Modifier.fillMaxWidth())
                Row { Spacer(Modifier.weight(1f)); Button(enabled = text.isNotBlank(), onClick = { scope.launch {
                    said = try { api.todoAdd(project, text.trim()); text = ""; "added" } catch (e: Exception) { e.message ?: "" }
                    reload()
                } }) { Text("Add") } }
                if (said.isNotBlank()) Text(said, color = Accent)
                if (td.error != null) Problem(td.error)
                if (td.value != null && items.isEmpty()) Dim("nothing on the roadmap")
            }
        }
        items(items) { it ->
            val shelved = it.bool("shelved")
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Text("R${it.int("number")}", color = if (shelved) MaterialTheme.colorScheme.onSurface.copy(alpha = .5f) else Accent, modifier = Modifier.padding(end = 8.dp))
                    Text(it.str("text"), modifier = Modifier.weight(1f), color = if (shelved) MaterialTheme.colorScheme.onSurface.copy(alpha = .5f) else MaterialTheme.colorScheme.onSurface)
                }
                for ((i, s) in it.arr("steps").withIndex())
                    Dim("  ${i + 1}. ${s.str("text")}" + (if (s.bool("done")) " ✓" else if (s.int("sent") > 0) " (sent)" else ""))
                if (it.str("info").isNotBlank()) Dim("  " + it.str("info").take(200))
                Row {
                    Spacer(Modifier.weight(1f))
                    if (!shelved) TextButton(onClick = { scope.launch { runCatching { api.todoShelve(project, it.opt("id")) }; reload() } }) { Text("Shelve") }
                }
            }
            HorizontalDivider()
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
                if (said.isNotBlank()) Text(said, color = Accent)
                if (bg.error != null) Problem(bg.error)
                if (bg.value != null && rows.isEmpty()) Dim("no bugs filed")
            }
        }
        items(rows) { b ->
            val open = b.str("status") == "open"
            Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Text("B${b.int("number")}", color = if (open) Accent else MaterialTheme.colorScheme.onSurface.copy(alpha = .5f), modifier = Modifier.padding(end = 8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(b.str("title"), color = if (open) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurface.copy(alpha = .5f))
                        Dim(listOf(b.str("severity"), b.str("status"), b.str("area")).filter { it.isNotBlank() }.joinToString(" · "))
                    }
                    Text(b.str("severity"), color = when (b.str("severity")) { "high" -> Bad; "medium" -> Warn; else -> Ok }, style = MaterialTheme.typography.labelMedium)
                }
                if (open) Row { Spacer(Modifier.weight(1f))
                    TextButton(onClick = { scope.launch { runCatching { api.bugStatus(project, b.opt("id"), "wontfix", "closed from the app") }; reload() } }) { Text("Won't fix") }
                    TextButton(onClick = { scope.launch { runCatching { api.bugStatus(project, b.opt("id"), "fixed", "closed from the app") }; reload() } }) { Text("Fixed") }
                }
            }
            HorizontalDivider()
        }
    }
}

@Composable
private fun Briefing(api: dev.builderbot.app.Api, project: String) {
    val (rl, _) = load("rules-$project") { api.rules(project) }
    val rules = rl.value?.arr("rules") ?: emptyList()
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
            HorizontalDivider()
        }
    }
}

@Composable
private fun Artifacts(api: dev.builderbot.app.Api, project: String) {
    val (ar, _) = load("art-$project") { api.artifacts(project) }
    val rows = ar.value?.arr("artifacts") ?: emptyList()
    val b = ar.value?.obj("build")
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
            HorizontalDivider()
        }
    }
}

@Composable
private fun Git(api: dev.builderbot.app.Api, project: String) {
    val (g, reload) = load("git-$project") { api.git(project) }
    val s = g.value?.obj("status") ?: g.value
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
