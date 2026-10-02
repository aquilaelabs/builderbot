// The notebook's Wiki (R112), on a phone: the dashboard's reader in the
// shape a phone has room for. The pages as chips over one article, the
// article's title over a rule, its Markdown drawn line by line (headings,
// lists, quotes, code and paragraphs), and the pages it links to with
// [[Another page]] as chips under it. Reading only: pages are written on
// the dashboard or by a session with bb wiki.
package dev.builderbot.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import dev.builderbot.app.Api
import dev.builderbot.app.arr
import dev.builderbot.app.str

private val LINK = Regex("""\[\[([^\]|]+)(?:\|([^\]]+))?\]\]""")

// One line of a page as a reader sees it: the marks that only shape the
// text (**, __, `, a link's brackets) taken off.
private fun plain(s: String): String = s
    .replace(LINK) { it.groupValues[1].trim() }
    .replace(Regex("""\[([^\]]*)\]\(([^)\s]+)\)""")) { it.groupValues[1].ifBlank { it.groupValues[2] } }
    .replace(Regex("""\*\*|__|`"""), "")

@Composable
fun WikiView(api: Api, project: String) {
    val (list, reload) = load("wiki-$project") { api.wiki(project) }
    val pages = (list.value?.arr("pages") ?: emptyList()).filter { !it.str("name").startsWith("_") }
    var cur by remember(project) { mutableStateOf("") }
    val name = cur.ifBlank { pages.firstOrNull { it.str("name") == "Home" }?.str("name") ?: pages.firstOrNull()?.str("name") ?: "" }
    val (page, _) = load("wiki-$project-$name-${list.value?.str("rev")}") { if (name.isBlank()) null else api.wikiPage(project, name) }
    Pull(list.value == null && list.error == null, reload) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp, 8.dp)) {
            list.error?.let { Problem(it) }
            if (list.value != null && pages.isEmpty())
                Dim("No pages yet: they are written on the dashboard's Wiki, or by a session with bb wiki save.")
            if (pages.isNotEmpty()) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (p in pages) FilterChip(selected = p.str("name") == name, onClick = { cur = p.str("name") },
                    label = { Text(p.str("title")) })
            }
            val text = page.value?.str("text") ?: ""
            if (name.isNotBlank()) {
                Text(name.replace('-', ' '), style = MaterialTheme.typography.headlineSmall, fontFamily = FontFamily.Serif,
                     color = Ink, modifier = Modifier.padding(top = 10.dp))
                Hairline()
                val by = page.value?.str("by") ?: ""
                if (by.isNotBlank()) Dim("last edited by $by")
            }
            page.error?.let { Problem(it) }
            var fence = false
            val code = StringBuilder()
            for (raw in text.lines()) {
                val l = raw.trimEnd()
                if (l.trimStart().startsWith("```")) {
                    if (fence) {
                        Text(code.toString().trimEnd(), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                             color = Ink, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                                .background(Sunk, RoundedCornerShape(6.dp)).padding(8.dp))
                        code.clear()
                    }
                    fence = !fence
                    continue
                }
                if (fence) { code.append(raw).append('\n'); continue }
                val h = Regex("""^(#{1,6})\s+(.*)$""").find(l)
                when {
                    h != null -> {
                        // The page's own title said again is said once.
                        if (h.groupValues[1].length == 1 && h.groupValues[2].trim().equals(name.replace('-', ' '), true)) continue
                        Text(plain(h.groupValues[2]), fontFamily = FontFamily.Serif, color = Ink,
                             style = if (h.groupValues[1].length <= 2) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium,
                             modifier = Modifier.padding(top = 12.dp))
                        if (h.groupValues[1].length <= 2) Hairline()
                    }
                    l.isBlank() -> {}
                    Regex("""^\s*([-*+]|\d+[.)])\s+""").containsMatchIn(l) ->
                        Text("•  " + plain(l.replace(Regex("""^\s*([-*+]|\d+[.)])\s+"""), "")),
                             fontFamily = FontFamily.Serif, modifier = Modifier.padding(start = 8.dp, top = 2.dp))
                    l.trimStart().startsWith(">") ->
                        Text(plain(l.trimStart().removePrefix(">").trim()), color = Dim, fontFamily = FontFamily.Serif,
                             modifier = Modifier.padding(start = 12.dp, top = 2.dp))
                    l.trimStart().startsWith("|") ->
                        Text(plain(l), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                    else -> Text(plain(l), fontFamily = FontFamily.Serif, modifier = Modifier.padding(top = 4.dp))
                }
            }
            // What the page links to, as the way there.
            val links = LINK.findAll(text).map { it.groupValues[2].ifBlank { it.groupValues[1] }.trim() }.distinct()
                .mapNotNull { t -> pages.firstOrNull { it.str("name").equals(t.replace(' ', '-'), true) }?.str("name") }.toList()
            if (links.isNotEmpty()) {
                SectionHead("Linked from this page", inset = false)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (n in links) FilterChip(selected = false, onClick = { cur = n }, label = { Text(n.replace('-', ' ')) })
                }
            }
            if (pages.isNotEmpty()) Dim("Written on the dashboard's Wiki, or by a session with bb wiki save.")
        }
    }
}
