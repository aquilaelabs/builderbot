// The views a project grew in September, in the shape a phone takes: the
// notebook's Design view (read here; laid out on the dashboard or by a
// session), the project's containers with the three verbs a person presses
// on one, its tests as the last run left them, and a line said to the
// account's own Claude session, which is the one thing a phone could not do
// without a terminal.
package dev.builderbot.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.builderbot.app.Api
import dev.builderbot.app.arr
import dev.builderbot.app.bool
import dev.builderbot.app.int
import dev.builderbot.app.obj
import dev.builderbot.app.str
import dev.builderbot.app.strs
import kotlinx.coroutines.launch
import org.json.JSONObject

// ---- small pieces these views share ----------------------------------------

/** A strip of choices, one in front: the project's own view strip, smaller.
 *  Scrolls sideways rather than wrapping, as that one does. */
@Composable
fun Choices(all: List<String>, picked: Int, onPick: (Int) -> Unit) {
    Row(Modifier.padding(horizontal = 16.dp).horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        all.forEachIndexed { i, label ->
            val on = i == picked
            Text(label, color = Ink, style = MaterialTheme.typography.labelMedium, maxLines = 1,
                modifier = Modifier
                    .background(if (on) AccentDeep else Panel, RoundedCornerShape(6.dp))
                    .border(1.dp, if (on) AccentDeep else Line, RoundedCornerShape(6.dp))
                    .clickable { onPick(i) }
                    .padding(horizontal = 10.dp, vertical = 6.dp))
        }
    }
}

/** A color as the design wrote it: #rrggbb, or #rrggbbaa where it carries
 *  its alpha, which is the stylesheet's order and not Android's. */
fun hexColor(s: String, fallback: Color = Color.Gray): Color {
    val h = s.trim().removePrefix("#")
    return try {
        when (h.length) {
            6 -> Color(0xFF000000 or h.toLong(16))
            8 -> Color((h.substring(6, 8).toLong(16) shl 24) or h.substring(0, 6).toLong(16))
            else -> fallback
        }
    } catch (e: NumberFormatException) { fallback }
}

/** A rule as the Briefing lists one: its name, whether it stands in every
 *  briefing or arrives on its triggers, and its words once it is opened. */
@Composable
fun RuleRow(r: JSONObject, under: String = "") {
    var open by remember(r.str("name"), under) { mutableStateOf(false) }
    val trig = (r.strs("paths") + r.strs("files") + r.strs("words")).filter { it.isNotBlank() }
    Column(Modifier.fillMaxWidth().clickable { open = !open }.padding(16.dp, 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text((if (under.isBlank()) "" else "$under/") + r.str("name"), color = Ink,
                 fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Text(if (trig.isEmpty()) "every session" else "on its triggers",
                 color = if (trig.isEmpty()) Dim else Note, style = MaterialTheme.typography.labelSmall)
        }
        if (open) {
            Text(r.str("text"), color = Ink, modifier = Modifier.padding(top = 4.dp))
            if (trig.isNotEmpty()) Dim("when: " + trig.joinToString(", "))
        }
    }
    Hairline()
}

// ---- the Design view ---------------------------------------------------------
// Read here. A design is laid out where there is room to drag a block, on
// the dashboard, or put there by a session; a phone is where it is looked
// at: which themes, which colors and what each is for, the pages as their
// boards, and the rules, each under what it holds for.

private val ROLE_NAMES = mapOf(
    "bg" to listOf("bg", "background", "page", "page-bg", "cream", "felt"),
    "panel" to listOf("panel", "surface", "card", "frost", "surface-1"),
    "ink" to listOf("ink", "text", "text-primary", "fg", "foreground"),
    "line" to listOf("line", "border", "edge", "outline"),
    "accent" to listOf("accent", "primary", "gold", "brand"))

private fun role(theme: JSONObject?, name: String, fallback: Color): Color {
    val names = ROLE_NAMES[name] ?: listOf(name)
    val hit = theme?.arr("colors")?.firstOrNull { it.str("name").lowercase() in names }
    return if (hit == null) fallback else hexColor(hit.str("hex"), fallback)
}

/** A page's board: its blocks where the design put them, on the frame it
 *  is for, painted in the project's own first theme, which is the one
 *  place here a color is the project's and not the app's. */
@Composable
private fun Board(page: JSONObject, frames: JSONObject, theme: JSONObject?) {
    val g = frames.obj(page.str("frame"))
    val cols = g.int("cols", 12).coerceAtLeast(1)
    val screen = g.int("rows", 8).coerceAtLeast(1)
    // A frame is one screen and a page may be longer than one: the board
    // is as many rows as the page has, and as much taller.
    val rows = maxOf(screen, page.int("rows"))
    val ratio = when (page.str("frame")) { "phone" -> 9f / 16f; "landscape" -> 16f / 9f; else -> 16f / 10f } *
        screen / rows
    val bg = role(theme, "bg", Bg)
    val panel = role(theme, "panel", Panel)
    val ink = role(theme, "ink", Ink)
    val line = role(theme, "line", Line)
    val accent = role(theme, "accent", Accent)
    BoxWithConstraints(Modifier
        .padding(16.dp, 6.dp)
        .widthIn(max = if (page.str("frame") == "phone") 230.dp else 520.dp)
        .fillMaxWidth().aspectRatio(ratio)
        .background(bg, RoundedCornerShape(8.dp))
        .border(1.dp, line, RoundedCornerShape(8.dp))
        .padding(4.dp)) {
        val cw = maxWidth / cols
        val ch = maxHeight / rows
        for (b in page.arr("blocks")) {
            val filled = b.str("kind") in setOf("button", "hero")
            val reading = b.str("kind") in setOf("content", "text")
            Column(Modifier
                .offset(x = cw * b.int("x"), y = ch * b.int("y"))
                .size(cw * b.int("w", 1), ch * b.int("h", 1))
                .padding(1.5.dp)
                .background(if (filled) accent else if (reading) bg else panel, RoundedCornerShape(5.dp))
                .border(1.dp, if (filled) accent else line, RoundedCornerShape(5.dp))
                .padding(4.dp, 2.dp)) {
                Text(b.str("kind").replaceFirstChar { it.uppercase() }, color = if (filled) bg else ink,
                     fontSize = 9.sp, lineHeight = 11.sp, fontWeight = FontWeight.SemiBold,
                     maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (b.str("label").isNotBlank())
                    Text(b.str("label"), color = (if (filled) bg else ink).copy(alpha = .85f), fontSize = 8.sp,
                         lineHeight = 10.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
fun DesignView(api: Api, project: String) {
    val (ds, reload) = load("design-$project") { api.design(project) }
    val d = ds.value
    val lang = d?.obj("language")
    val themes = lang?.arr("themes") ?: emptyList()
    val rules = lang?.arr("rules") ?: emptyList()
    val pages = d?.arr("pages") ?: emptyList()
    val frames = d?.obj("presets")?.obj("frames") ?: JSONObject()
    var themeIx by remember(project) { mutableStateOf(0) }
    var pageIx by remember(project) { mutableStateOf(0) }
    val theme = themes.getOrNull(themeIx.coerceIn(0, maxOf(0, themes.size - 1)))
    val page = pages.getOrNull(pageIx.coerceIn(0, maxOf(0, pages.size - 1)))
    Pull(ds.value == null && ds.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (ds.error != null) Problem(ds.error)
                if (d != null && themes.isEmpty() && pages.isEmpty() && rules.isEmpty())
                    Dim("nothing designed yet: a session that builds this project chooses the look and puts it here, or it is laid out on the dashboard's Design view")
                if (lang != null && (themes.isNotEmpty() || pages.isNotEmpty() || rules.isNotEmpty())) {
                    // A choice nobody has made is left out: a design starts with none.
                    val made = listOf(lang.str("font"), lang.str("corners").let { if (it.isBlank()) "" else "$it corners" },
                                      lang.str("density"), lang.str("motion").let { if (it.isBlank()) "" else "$it motion" })
                        .filter { it.isNotBlank() }
                    if (made.isNotEmpty()) Dim(made.joinToString(" · "))
                    if (lang.str("fonts").isNotBlank()) Dim("set as " + lang.str("fonts"))
                    if (lang.str("scope").isNotBlank()) Dim("governs " + lang.str("scope"))
                }
            }
        }
        if (pages.isNotEmpty()) {
            item {
                SectionHead("Pages")
                Choices(pages.map { it.str("name").ifBlank { "unnamed page" } }, pageIx) { pageIx = it }
            }
            if (page != null) {
                item {
                    Board(page, frames, themes.firstOrNull())
                    Column(Modifier.padding(16.dp, 4.dp)) {
                        Dim(listOf(page.str("platform"), page.str("frame"),
                                   "${page.arr("blocks").size} block${if (page.arr("blocks").size == 1) "" else "s"}",
                                   if (page.obj("layouts").length() > 0)
                                       "also laid out for " + page.obj("layouts").keys().asSequence().joinToString(", ")
                                   else "").filter { it.isNotBlank() }.joinToString(" · "))
                        if (page.str("notes").isNotBlank()) Text(page.str("notes"), color = Ink, modifier = Modifier.padding(top = 4.dp))
                    }
                }
                items(page.arr("rules")) { r -> RuleRow(r, under = "this page") }
            }
        }
        if (themes.isNotEmpty()) {
            item {
                SectionHead("Themes")
                Choices(themes.mapIndexed { i, t -> t.str("name") + (if (i == 0) " (default)" else "") }, themeIx) { themeIx = it }
            }
            if (theme != null) {
                item { Column(Modifier.padding(16.dp, 6.dp)) { Dim(theme.str("mode") + if (themeIx == 0) " · the app starts on it" else "") } }
                items(theme.arr("colors")) { c ->
                    Row(Modifier.fillMaxWidth().padding(16.dp, 5.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(22.dp).background(hexColor(c.str("hex")), RoundedCornerShape(4.dp))
                            .border(1.dp, Line, RoundedCornerShape(4.dp)))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(c.str("name"), color = Ink, fontWeight = FontWeight.SemiBold)
                            if (c.str("means").isNotBlank()) Dim(c.str("means"))
                        }
                        Text(c.str("hex"), color = Dim, fontFamily = FontFamily.Monospace,
                             style = MaterialTheme.typography.bodySmall)
                    }
                }
                items(theme.arr("rules")) { r -> RuleRow(r, under = theme.str("name")) }
            }
        }
        if (rules.isNotEmpty()) {
            item { SectionHead("Rules") }
            items(rules) { r -> RuleRow(r) }
        }
        item { Spacer(Modifier.height(16.dp)) }
    }
    }
}

// ---- the project's containers ------------------------------------------------
// What the Docker view of its notebook lists, and Start, Stop and Rebuild on
// one. Each is a job on the project's node and says so: the row is read
// again rather than guessed at, and the job's own line is what moves.

@Composable
fun DockerView(api: Api, project: String) {
    val scope = rememberCoroutineScope()
    val (dk, reload) = load("docker-$project") { api.docker(project) }
    var said by remember { mutableStateOf("") }
    var ask by remember { mutableStateOf<Pair<String, JSONObject>?>(null) }
    val rows = dk.value?.arr("instances")?.filter { it.str("owner") == project || it.str("project") == project } ?: emptyList()
    val job = dk.value?.obj("job")
    val busy = job?.bool("running") == true

    ask?.let { (action, row) ->
        AlertDialog(onDismissRequest = { ask = null },
            title = { Text(when (action) { "up" -> "Start"; "down" -> "Stop"; else -> "Rebuild" } + " ${row.str("name")}?") },
            text = { Text(when (action) {
                "rebuild" -> "It is built from the project's compose file on its node and started. That takes minutes, and what runs there now stops for it."
                "down" -> "Its containers stop. Their data stays."
                else -> "Its containers start as they were last built."
            }) },
            confirmButton = { Button(onClick = {
                ask = null
                scope.launch {
                    said = try {
                        val r = api.devapp(project, row.str("instance"), action)
                        r.str("error").ifBlank { if (r.has("held")) "asked: it waits on an approval" else "started: the row says what became of it" }
                    } catch (e: Exception) { e.message ?: e.toString() }
                    reload()
                }
            }) { Text(when (action) { "up" -> "Start"; "down" -> "Stop"; else -> "Rebuild" }) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Cancel") } })
    }

    Pull(dk.value == null && dk.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (dk.error != null) Problem(dk.error)
                dk.value?.let { v ->
                    if (v.str("error").isNotBlank()) Text(v.str("error"), color = Bad)
                    if (v.str("why").isNotBlank()) Dim(v.str("why"))
                    if (v.bool("stale")) Dim("as last seen: the node's daemon has not answered since")
                }
                if (said.isNotBlank()) Text(said, color = Note)
                if (busy && job != null) Mono((job.str("step").ifBlank { "working" }) + " " + job.str("name"))
                if (job != null && job.str("error").isNotBlank()) Text(job.str("error"), color = Bad)
                if (dk.value != null && rows.isEmpty())
                    Dim("no container belongs to this project: a compose file at its root and Send to Docker on the dashboard make one")
            }
        }
        items(rows) { r ->
            val running = r.bool("running")
            Panel(Modifier.fillMaxWidth().padding(16.dp, 4.dp), bar = if (running) Ok else Line) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(r.str("name"), color = Ink, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        Pill(if (!r.bool("exists")) "not built" else if (running) "running" else "down",
                             if (running) Ok else Dim)
                    }
                    val built = r.str("built_rev")
                    Dim(listOf(if (built.isNotBlank()) "built from $built" else "",
                               r.strs("ports").joinToString(", ")).filter { it.isNotBlank() }.joinToString(" · "))
                    for (s in r.arr("services"))
                        Text("${s.str("service")}: ${s.str("status").ifBlank { s.str("state") }}",
                             color = if (s.str("state") == "running") Ink else Dim,
                             style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace)
                    val url = r.obj("route").str("url")
                    if (url.isNotBlank()) Dim(url)
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(enabled = !busy, onClick = { ask = (if (running) "down" else "up") to r }) {
                            Text(if (running) "Stop" else "Start") }
                        OutlinedButton(enabled = !busy, onClick = { ask = "rebuild" to r }) { Text("Rebuild") }
                    }
                }
            }
        }
    }
    }
}

// ---- the project's tests -------------------------------------------------------

private fun secs(ms: Int) = if (ms >= 60_000) "${ms / 60_000} min ${(ms % 60_000) / 1000} s" else "%.1f s".format(ms / 1000f)

@Composable
fun TestsView(api: Api, project: String) {
    val (ts, reload) = load("tests-$project") { api.tests(project) }
    val t = ts.value
    val suites = t?.arr("suites") ?: emptyList()
    Pull(ts.value == null && ts.error == null, reload) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp, 8.dp)) {
                if (ts.error != null) Problem(ts.error)
                if (t != null && t.int("n") == 0)
                    Dim("no tests on record: a run on the project's node, read in with bb tests ingest, lists them here")
                if (t != null && t.int("n") > 0) {
                    Text("${t.int("n")} tests", color = Ink, fontWeight = FontWeight.SemiBold)
                    Dim(listOf("${secs(t.int("total_ms"))} measured",
                               if (t.int("last_wall_ms") > 0) "last run ${secs(t.int("last_wall_ms"))} of wall" else "",
                               if (t.int("suspect") > 0) "${t.int("suspect")} flagged" else "",
                               if (t.int("undocumented") > 0) "${t.int("undocumented")} undescribed" else "")
                        .filter { it.isNotBlank() }.joinToString(" · "))
                }
            }
        }
        items(suites) { s ->
            Row(Modifier.fillMaxWidth().padding(16.dp, 7.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(s.str("suite").ifBlank { s.str("name") }, color = Ink, modifier = Modifier.weight(1f))
                if (s.int("fail") > 0) { Pill("${s.int("fail")} failing", Bad); Spacer(Modifier.width(8.dp)) }
                if (s.int("suspect") > 0) { Pill("${s.int("suspect")} flagged", Warn); Spacer(Modifier.width(8.dp)) }
                Text("${s.int("n")} · ${secs(s.int("ms"))}", color = Dim, fontFamily = FontFamily.Monospace,
                     style = MaterialTheme.typography.bodySmall)
            }
            Hairline()
        }
    }
    }
}

// ---- a line, said to the account's own session -----------------------------------
// Offered only where it can land: the account's own Claude session on this
// project, running. What it is doing is said beside the box, since a line
// typed into a session that is working waits its turn.

@Composable
fun SayBox(api: Api, session: JSONObject, onSaid: () -> Unit = {}) {
    val scope = rememberCoroutineScope()
    var text by remember(session.str("name")) { mutableStateOf("") }
    var said by remember(session.str("name")) { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val claude = session.obj("claude")
    Column(Modifier.padding(16.dp, 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Dot(if (claude.str("state") == "working") Warn else Ok)
            Text(listOf("Claude is " + claude.str("state").ifBlank { "open" }, claude.str("task"))
                     .filter { it.isNotBlank() }.joinToString(": "),
                 color = Dim, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(text, { text = it }, label = { Text("Say to Claude") },
                              modifier = Modifier.weight(1f), maxLines = 4)
            Spacer(Modifier.width(8.dp))
            Button(enabled = text.isNotBlank() && !busy, onClick = {
                busy = true
                scope.launch {
                    said = try {
                        val r = api.say(session.str("name"), session.str("node_id"), text.trim())
                        r.str("error").ifBlank { text = ""; if (r.bool("sent", true)) "said" else "typed, but not sent: the session did not take it" }
                    } catch (e: Exception) { e.message ?: "it did not go" }
                    busy = false
                    // Its state a moment later: the line it was handed is
                    // what it is working on now.
                    kotlinx.coroutines.delay(2_000); onSaid()
                }
            }) { Text("Send") }
        }
        if (said.isNotBlank()) Text(said, color = Note, style = MaterialTheme.typography.bodySmall)
    }
}

// ---- a file from the dashboard, onto the phone --------------------------------
// A conversation's text and an artifact are both bytes the dashboard
// already serves to this account. They land in one of the cache
// directories the provider publishes (res/xml/file_paths.xml) and are
// handed to whatever on the phone reads them, by a grant on that one file.

private fun safeName(s: String) = s.replace(Regex("[^A-Za-z0-9._-]"), "_").takeLast(80).ifBlank { "file" }

suspend fun fetched(context: android.content.Context, api: Api, path: String, dir: String, name: String): android.net.Uri {
    val d = java.io.File(context.cacheDir, dir)
    d.mkdirs()
    // What an earlier look left goes first: the cache is a hand-over, not a library.
    d.listFiles()?.forEach { it.delete() }
    val file = api.download(path, java.io.File(d, safeName(name)))
    return androidx.core.content.FileProvider.getUriForFile(context, context.packageName + ".files", file)
}

private fun mimeOf(name: String): String =
    android.webkit.MimeTypeMap.getSingleton()
        .getMimeTypeFromExtension(name.substringAfterLast('.', "").lowercase())
        ?: if (name.endsWith(".apk")) "application/vnd.android.package-archive" else "application/octet-stream"

/** Open an artifact with whatever the phone has for its kind. An APK goes
 *  to the installer, which asks the person as it always does. */
suspend fun openArtifact(context: android.content.Context, api: Api, project: String, path: String): String = try {
    val name = path.substringAfterLast('/')
    val uri = fetched(context, api, "/api/artifact?project=${Api.enc(project)}&path=${Api.enc(path)}", "open", name)
    context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW)
        .setDataAndType(uri, mimeOf(name))
        .addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
    ""
} catch (e: android.content.ActivityNotFoundException) {
    "nothing on this phone opens that kind of file"
} catch (e: Exception) { e.message ?: "it did not download" }

private const val TAIL = 8_000L

private fun whenAt(at: Long): String =
    if (at <= 0) "" else java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT)
        .format(java.util.Date(at * 1000))

private fun sized(bytes: Long): String = when {
    bytes >= 1 shl 20 -> "%.1f MB".format(bytes / 1048576f)
    bytes >= 1024 -> "${bytes / 1024} KB"
    else -> "$bytes B"
}

/** One conversation of the account's own: what it opened with, when it
 *  was last written, and the two things a phone does with one. Read shows
 *  its end, which is where what Claude last said is; Share hands the whole
 *  text to another app. */
@Composable
fun LogRow(api: Api, row: JSONObject, showProject: Boolean) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    val project = row.str("project")
    val id = row.str("id")
    var tail by remember(id) { mutableStateOf("") }
    var said by remember(id) { mutableStateOf("") }
    var busy by remember(id) { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(16.dp, 8.dp)) {
        Text(row.str("first").ifBlank { "a conversation with no first line" }, color = Ink, maxLines = 2,
             overflow = TextOverflow.Ellipsis)
        Dim(listOf(if (showProject) project else "", whenAt(row.optLong("at")), sized(row.optLong("bytes")) + " as written")
                .filter { it.isNotBlank() }.joinToString(" · "))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (said.isNotBlank()) Text(said, color = Bad, style = MaterialTheme.typography.bodySmall,
                                        modifier = Modifier.weight(1f))
            else Spacer(Modifier.weight(1f))
            TextButton(enabled = !busy, onClick = {
                if (tail.isNotBlank()) { tail = ""; return@TextButton }
                busy = true
                scope.launch {
                    said = try {
                        val d = java.io.File(context.cacheDir, "logs"); d.mkdirs()
                        val f = api.download(api.transcriptPath(project, id), java.io.File(d, "reading.txt"))
                        // Its end: a day's conversation is megabytes, and the
                        // question on a phone is what was said last.
                        val len = f.length()
                        tail = f.inputStream().use { ins ->
                            ins.skip(maxOf(0L, len - TAIL)); ins.readBytes().toString(Charsets.UTF_8) }
                            .let { if (len > TAIL) "[the end of it]\n" + it.substringAfter('\n') else it }
                        f.delete()
                        ""
                    } catch (e: Exception) { e.message ?: "it did not download" }
                    busy = false
                }
            }) { Text(if (tail.isNotBlank()) "Close" else if (busy) "Reading" else "Read the end") }
            TextButton(enabled = !busy, onClick = {
                busy = true
                scope.launch {
                    said = try {
                        val uri = fetched(context, api, api.transcriptPath(project, id), "logs",
                                          "claude-$project-${id.take(8)}.txt")
                        context.startActivity(android.content.Intent.createChooser(
                            android.content.Intent(android.content.Intent.ACTION_SEND)
                                .setType("text/plain")
                                .putExtra(android.content.Intent.EXTRA_STREAM, uri)
                                .addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION),
                            "The conversation").addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                        ""
                    } catch (e: Exception) { e.message ?: "it did not download" }
                    busy = false
                }
            }) { Text("Share") }
        }
        if (tail.isNotBlank()) Mono(tail)
    }
    Hairline()
}

// ---- Claude on this project ----------------------------------------------------
// The account's own session, where one is open: what it is doing and a box
// to say something to it. Under that, the account's conversations here.
// Starting a session stays the dashboard's: it opens a terminal, and the
// terminals are the browser's.

@Composable
fun ClaudeView(api: Api, project: String, session: JSONObject?, reloadStatus: () -> Unit) {
    val (tr, reload) = load("transcripts-$project") { api.transcripts(project) }
    val rows = tr.value?.arr("rows") ?: emptyList()
    Column(Modifier.fillMaxSize()) {
    // Above the list and not a row of it: what the session is doing moves
    // with every look at the status, and a row of a lazy list kept the
    // line it was first drawn with (it read "waiting" under a pill that
    // said working).
    if (session != null) SayBox(api, session, onSaid = { reloadStatus(); reload() })
    else Column(Modifier.padding(16.dp, 8.dp)) {
        Dim("no Claude session of yours is open on this project: the Claude button on the dashboard starts one, and this is where you talk to it from then on")
    }
    Pull(tr.value == null && tr.error == null, { reload(); reloadStatus() }) {
    LazyColumn(Modifier.fillMaxSize()) {
        item {
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
